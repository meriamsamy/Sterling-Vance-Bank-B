from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional

from config import API_KEY
from langchain_groq import ChatGroq
from langgraph.types import interrupt

from mcp import db_access as db
from planning.decomposition import BankDecompositionAdapter
from rag.hybrid_rag import hybrid_rag

from .state import CustomerRiskState
from .utils import handle_node_failure


risk_llm = ChatGroq(
    api_key=API_KEY,
    model="qwen/qwen3.6-27b",
    temperature=0.0,
    max_tokens=4096,
)


def _now() -> str:
    """Return a UTC timestamp for workflow auditing."""
    return datetime.now(timezone.utc).isoformat()


def load_customer_state(
    state: CustomerRiskState,
) -> dict[str, Any]:
    """Load the customer's current persisted risk level."""

    customer_id = state["customer_id"]

    conn = db.get_conn()

    customer = conn.execute(
        """
        SELECT customer_id, name, risk_level
        FROM customers
        WHERE customer_id = ?
        """,
        (customer_id,),
    ).fetchone()

    conn.close()

    if customer is None:
        raise ValueError(
            f"Customer {customer_id} does not exist."
        )

    now = _now()

    return {
        "current_risk_level": customer["risk_level"],
        "previous_risk_level": state.get(
            "current_risk_level"
        ),
        "assessed_risk_level": customer["risk_level"],
        "status": "collecting_activity",
        "current_node": "load_customer_state",
        "started_at": state.get("started_at", now),
        "updated_at": now,
        "checkpoint_version": state.get(
            "checkpoint_version", 0
        ),
    }


def collect_recent_activity(
    state: CustomerRiskState,
) -> dict[str, Any]:
    """Collect transactions relevant to the monitored customer."""

    customer_id = state["customer_id"]

    transactions = db.get_customer_recent_transactions(
        customer_id=customer_id,
        after_transaction_id=state.get(
            "last_processed_transaction_id"
        ),
    )

    latest_transaction_id = (
        max(
            transaction["transaction_id"]
            for transaction in transactions
        )
        if transactions
        else state.get("last_processed_transaction_id")
    )

    return {
        "recent_activity": transactions,
        "last_processed_transaction_id": latest_transaction_id,
        "status": "planning_review",
        "current_node": "collect_recent_activity",
        "updated_at": _now(),
    }


def decompose_risk_review(
    state: CustomerRiskState,
) -> dict[str, Any]:
    """Create a structured investigation plan for the risk review."""

    customer_id = state["customer_id"]

    goal = f"""
    Assess whether the current risk level of customer {customer_id}
    is still consistent with the customer's recent transaction activity.

    Break the investigation into concrete banking analysis tasks.

    The investigation should cover:
    - current customer risk level
    - recent transaction behavior
    - historical activity patterns
    - suspicious activity indicators
    - relevant bank policy requirements
    """

    adapter = BankDecompositionAdapter(risk_llm)

    dag = adapter.decompose(goal)

    decomposition = {
        "topological_order": dag.topological_order(),
        "execution_batches": dag.execution_batches(),
        "tasks": {
            task_id: {
                "description": task.description,
                "dependencies": task.dependencies,
            }
            for task_id, task in dag.nodes.items()
        },
    }

    return {
        "decomposition": decomposition,
        "status": "retrieving_policy",
        "current_node": "decompose_risk_review",
        "updated_at": _now(),
    }


def retrieve_risk_policy(
    state: CustomerRiskState,
) -> dict[str, Any]:
    """Retrieve relevant bank policy using the existing Hybrid RAG."""

    current_risk = state["current_risk_level"]

    question = f"""
    What Sterling & Vance Bank policies are relevant when assessing
    whether a customer's current risk level should remain {current_risk}
    based on recent transaction activity, suspicious transaction patterns,
    structuring, sanctions, or other financial-crime indicators?

    Return only information supported by the retrieved bank documents.
    """

    result = hybrid_rag(question)

    if result["status"] not in {
        "VERIFIED",
        "NO_DOCUMENTS",
    }:
        raise RuntimeError(
            "Risk policy retrieval could not be verified."
        )

    return {
        "policy_context": result["context"],
        "policy_status": result["status"],
        "current_node": "retrieve_risk_policy",
        "status": "assessing_risk",
        "updated_at": _now(),
    }


def assess_risk_consistency(
    state: CustomerRiskState,
) -> dict[str, Any]:
    """Assess whether the customer's current risk still fits the evidence."""

    current = state["current_risk_level"]

    activity = state.get("recent_activity", [])
    policy = state.get("policy_context", "")
    decomposition = state.get("decomposition", {})

    prompt = f"""
You are a banking risk assessment assistant.

Determine whether the customer's CURRENT risk level is still
consistent with the observed activity.

Current risk level:
{current}

Recent transaction activity:
{activity}

Investigation plan:
{decomposition}

Relevant bank policy:
{policy}

Return exactly in this key-value format (one per line):

RISK=<low|medium|high>
CONFIDENCE=<0.0-1.0>
REASON=<short explanation>

Do not invent transactions or policy rules.
Use only the provided evidence.
"""

    response = risk_llm.invoke(prompt).content.strip()

    parsed = parse_risk_response(response)

    assessed = parsed["risk"]

    return {
        "assessed_risk_level": assessed,
        "assessment_confidence": parsed["confidence"],
        "risk_reason": parsed["reason"],
        "risk_changed": assessed != current,
        "status": (
            "risk_changed"
            if assessed != current
            else "waiting_for_activity"
        ),
        "current_node": "assess_risk_consistency",
        "updated_at": _now(),
    }


def risk_review_human_approval(
    state: CustomerRiskState,
) -> dict[str, Any]:
    """Pause the graph and request an admin decision."""

    request = {
        "type": "customer_risk_review",
        "customer_id": state["customer_id"],
        "current_risk_level": state["current_risk_level"],
        "assessed_risk_level": state["assessed_risk_level"],
        "confidence": state["assessment_confidence"],
        "reason": state["risk_reason"],
    }

    decision = interrupt(request)

    return {
        "admin_decision": decision["decision"],
        "admin_reason": decision.get("reason"),
        "status": "admin_decision_received",
        "current_node": "risk_review_human_approval",
        "updated_at": _now(),
    }


def wait_for_activity(
    state: CustomerRiskState,
) -> dict[str, Any]:
    """
    Put the monitoring workflow into its logical waiting state.

    The actual suspend/resume behavior is handled by the graph's
    persistence/runtime layer.
    """

    return {
        "status": "waiting_for_activity",
        "current_node": "wait_for_activity",
        "updated_at": _now(),
    }


def parse_risk_response(
    text: str,
) -> dict[str, Any]:
    """Validate and parse the constrained risk assessment output using regex."""

    risk_match = re.search(r"RISK\s*=\s*(low|medium|high)", text, re.IGNORECASE)
    confidence_match = re.search(r"CONFIDENCE\s*=\s*([0-9.]+)", text, re.IGNORECASE)
    reason_match = re.search(r"REASON\s*=\s*(.+)", text, re.IGNORECASE)

    if not risk_match:
        raise ValueError(f"Could not parse valid RISK from model output: {text}")

    risk = risk_match.group(1).lower()

    try:
        confidence = float(confidence_match.group(1)) if confidence_match else 0.0
    except ValueError as exc:
        raise ValueError("Invalid confidence returned by model.") from exc

    if not 0 <= confidence <= 1:
        raise ValueError("Confidence must be between 0 and 1.")

    reason = reason_match.group(1).strip() if reason_match else "No reason provided."

    return {
        "risk": risk,
        "confidence": confidence,
        "reason": reason,
    }


@handle_node_failure
def apply_admin_decision(
    state: CustomerRiskState,
) -> dict[str, Any]:
    """Apply the admin's HITL decision directly to the database."""
    decision = state.get("admin_decision")
    customer_id = state["customer_id"]
    assessed_risk = state["assessed_risk_level"]

    if decision == "approve":
        with sqlite3.connect("db/bank.db", timeout=30.0) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")  
            conn.execute(
                "UPDATE customers SET risk_level = ? WHERE customer_id = ?",
                (assessed_risk, customer_id),
            )
            conn.commit()

        return {
            "current_risk_level": assessed_risk,
            "previous_risk_level": state["current_risk_level"],
            "status": "waiting_for_activity",
            "current_node": "apply_admin_decision",
            "updated_at": _now(),
        }

    return {
        "status": "waiting_for_activity",
        "current_node": "apply_admin_decision",
        "updated_at": _now(),
    }