from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[2]

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from mcp_server import db_access as db

from state_graph.sanctions_change.sanctions_state import SanctionsReviewState

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def update_transition(
    state: SanctionsReviewState,
    node_name: str,
    status: str,
    **updates: Any,
) -> dict[str, Any]:
    """Centralized state transition tracking for the durable State Graph."""
    previous_node = state.get("current_node")
    return {
        **updates,
        "last_node": previous_node,
        "current_node": node_name,
        "status": status,
        "last_transition": f"{previous_node or 'START'} -> {node_name}",
        "updated_at": utc_now(),
    }


def fail_review(
    state: SanctionsReviewState,
    error: Exception | str,
    failed_node: str,
) -> dict[str, Any]:
    """Persist workflow failure and return a recoverable failed state."""
    if isinstance(error, Exception):
        error_type = type(error).__name__
        error_message = str(error)
    else:
        error_type = "WorkflowError"
        error_message = str(error)

    timestamp = utc_now()

    # [DURABLE FAILURE HANDLING] Persist failure as a workflow ticket.
    ticket_id = db.create_workflow_ticket(
        workflow_type="sanctions_review",
        wire_id=state.get("wire_id"),
        review_id=state.get("review_id"),
        status="open",
        error_type=error_type,
        error_message=error_message,
        failed_node=failed_node,
        created_at=timestamp,
    )

    return update_transition(
        state=state,
        node_name=failed_node,
        status="failed",
        failure={
            "type": error_type,
            "message": error_message,
            "node": failed_node,
            "timestamp": timestamp,
        },
        failure_ticket_id=ticket_id,
        error_type=error_type,
        error_message=error_message,
        failed_node=failed_node,
        hitl_required=False,
        decision=None,
    )


# ============================================================
# LOAD
# ============================================================

def load_review(state: SanctionsReviewState) -> dict[str, Any]:
    """Load and validate the wire before starting investigation."""
    try:
        wire_id = state.get("wire_id")
        if wire_id is None:
            raise ValueError("wire_id is required to start sanctions review.")

        wire = db.get_wire_transfer(wire_id)
        if wire is None:
            raise ValueError(f"Wire transfer #{wire_id} does not exist.")

        if wire["status"] != "pending_manual_review":
            raise ValueError(
                f"Wire #{wire_id} is not an open manual review. "
                f"Current status: {wire['status']}"
            )

        source_account_id = wire["source_account_id"]
        account = db.get_account(source_account_id)
        if account is None:
            raise ValueError(
                f"Source account #{source_account_id} does not exist."
            )

        customer_id = account["customer_id"]
        if not db.get_customer_accounts(customer_id):
            raise ValueError(f"Customer #{customer_id} has no accounts.")

        country = wire["destination_country"]

        # [SANCTIONS VERSIONING] Capture the sanctions state at workflow start.
        sanctions_status = db.get_sanctions_status(country)
        current_version = db.get_sanctions_version()

        start_status = state.get("sanctions_status_at_start")
        start_version = state.get("sanctions_version_at_start")

        if start_status is None:
            start_status = sanctions_status
        if start_version is None:
            start_version = current_version

        return update_transition(
            state=state,
            node_name="load_review",
            status="collecting_evidence",
            review_id=state.get("review_id"),
            wire_id=wire["transfer_id"],
            customer_id=customer_id,
            destination_country=country,
            wire_status=wire["status"],
            wire_amount=float(wire["amount"]),
            source_account_id=source_account_id,
            sanctions_status_at_start=start_status,
            sanctions_version_at_start=start_version,
            current_sanctions_version=current_version,
            current_sanctions_status=sanctions_status,
            previous_sanctions_status=state.get("current_sanctions_status"),
            sanctions_changed=state.get("sanctions_changed", False),
            sanctions_impact=state.get("sanctions_impact", "unknown"),
            evidence=list(state.get("evidence", [])),
            new_evidence=[],
            retrieved_policy=list(state.get("retrieved_policy", [])),
            react_steps=list(state.get("react_steps", [])),
            react_step_count=state.get("react_step_count", 0),
            react_max_steps=state.get("react_max_steps", 6),
            risk_level=state.get("risk_level", "unknown"),
            recommended_action=state.get("recommended_action", "unknown"),
            hitl_required=False,
            hitl_reason=None,
            failure=state.get("failure"),
            failure_ticket_id=state.get("failure_ticket_id"),
            error_type=state.get("error_type"),
            error_message=state.get("error_message"),
            failed_node=state.get("failed_node"),
        )

    except Exception as e:
        return fail_review(state, e, "load_review")


# ============================================================
# EVIDENCE
# ============================================================

def collect_evidence(state: SanctionsReviewState) -> dict[str, Any]:
    """Collect grounded DB evidence required for sanctions investigation."""
    try:
        account_id = state.get("source_account_id")
        country = state.get("destination_country")

        if account_id is None:
            raise ValueError("source_account_id is missing.")
        if not country:
            raise ValueError("destination_country is missing.")

        account = db.get_account(account_id)
        if account is None:
            raise ValueError(
                f"Account #{account_id} disappeared during investigation."
            )

        customer_id = account["customer_id"]
        customer_accounts = db.get_customer_accounts(customer_id)
        transaction_history = db.get_transaction_history(account_id)

        # [GROUNDING] Re-read sanctions data instead of relying only on old state.
        sanctions_status = db.get_sanctions_status(country)
        sanctions_version = db.get_sanctions_version()
        collected_at = utc_now()

        new_evidence = [
            {
                "type": "account",
                "account_id": account_id,
                "balance": float(account["balance"]),
                "account_type": account["account_type"],
                "customer_id": customer_id,
                "collected_at": collected_at,
            },
            {
                "type": "customer_accounts",
                "customer_id": customer_id,
                "accounts": customer_accounts,
                "collected_at": collected_at,
            },
            {
                "type": "transaction_history",
                "account_id": account_id,
                "data": transaction_history,
                "collected_at": collected_at,
            },
            {
                "type": "sanctions_check",
                "country": country,
                "status": sanctions_status,
                "version": sanctions_version,
                "collected_at": collected_at,
            },
        ]

        return update_transition(
            state=state,
            node_name="collect_evidence",
            status="analyzing",
            new_evidence=new_evidence,
            current_sanctions_status=sanctions_status,
            current_sanctions_version=sanctions_version,
        )

    except Exception as e:
        return fail_review(state, e, "collect_evidence")


# ============================================================
# SANCTIONS CHANGE
# ============================================================

def detect_sanctions_change(
    state: SanctionsReviewState,
) -> dict[str, Any]:
    """Detect sanctions changes that happened while the review was open."""
    try:
        country = state.get("destination_country")
        if not country:
            raise ValueError("destination_country is missing.")

        start_version = state.get("sanctions_version_at_start")
        current_version = db.get_sanctions_version()
        current_status = db.get_sanctions_status(country)

        if start_version is None:
            start_version = current_version

        # [CONCURRENCY / EXTERNAL CHANGE DETECTION]
        # Compare events after the version captured when this review started.
        changes = db.get_sanctions_changes_since(country, start_version)

        if changes:
            latest = changes[-1]
            changed = True
            previous_status = latest["previous_status"]
            event_id = latest["event_id"]
            event_version = latest["version"]
            sanctions_impact = "affected"
        else:
            changed = False
            previous_status = state.get(
                "current_sanctions_status",
                state.get("sanctions_status_at_start"),
            )
            event_id = state.get("event_id")
            event_version = state.get("event_sanctions_version")
            sanctions_impact = "no_impact"

        return update_transition(
            state=state,
            node_name="detect_sanctions_change",
            status=(
                "re_evaluating"
                if (
                    changed
                    or state.get("pending_event") == "new_evidence"
                )
                else "waiting"
            ),
            previous_sanctions_status=previous_status,
            current_sanctions_status=current_status,
            current_sanctions_version=current_version,
            event_id=event_id,
            event_sanctions_version=event_version,
            sanctions_changed=changed,
            sanctions_impact=sanctions_impact,
        )

    except Exception as e:
        return fail_review(state, e, "detect_sanctions_change")


# ============================================================
# PREPARE RE-EVALUATION
# ============================================================

def prepare_re_evaluation(
    state: SanctionsReviewState,
) -> dict[str, Any]:
    """Merge new evidence and reset decision-specific analysis state."""
    try:
        evidence = list(state.get("evidence", []))
        new_evidence = list(state.get("new_evidence", []))

        # [EVIDENCE MERGING] Prevent duplicate evidence after re-entry.
        existing = {repr(item) for item in evidence}

        for item in new_evidence:
            if repr(item) not in existing:
                evidence.append(item)
                existing.add(repr(item))

        return update_transition(
            state=state,
            node_name="prepare_re_evaluation",
            status="analyzing",
            evidence=evidence,
            new_evidence=[],
            analysis=None,
            risk_score=None,
            risk_level="unknown",
            recommended_action="unknown",
            hitl_required=False,
            hitl_reason=None,
            hitl_task_id=None,
            decision=None,
            decision_reason=None,
            investigation_status=None,
            investigation_answer=None,
            investigation_reason=None,
            investigation_history=[],
            investigation_steps=0,
        )

    except Exception as e:
        return fail_review(state, e, "prepare_re_evaluation")


# ============================================================
# COMPLETE
# ============================================================

def complete_review(
    state: SanctionsReviewState,
) -> dict[str, Any]:
    """Finish the workflow only after a final decision exists."""
    try:
        decision = state.get("decision")

        if not decision:
            raise ValueError(
                "Cannot complete review without a final decision."
            )

        return update_transition(
            state=state,
            node_name="complete_review",
            status="completed",
        )

    except Exception as e:
        return fail_review(state, e, "complete_review")