from __future__ import annotations

from typing import Any
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[2]

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

MCP_DIR = ROOT_DIR / "mcp"

if str(MCP_DIR) not in sys.path:
    sys.path.insert(0, str(MCP_DIR))

import db_access as db

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from state_graph.sanctions_change.sanctions_state import SanctionsReviewState
from state_graph.sanctions_change.sanctions_nodes import (
    load_review,
    collect_evidence,
    detect_sanctions_change,
    prepare_re_evaluation,
    complete_review,
    fail_review,
    utc_now,
)
from state_graph.sanctions_change.sanctions_constrained import constrained_react_node

from rag.hybrid_rag import hybrid_rag

# ============================================================
# [CONDITIONAL ROUTING]
# Graph routing depends on workflow state and failure status.
# ============================================================

def route_after_load(state: SanctionsReviewState):
    if state.get("status") == "failed":
        return "reset_after_failure"
    return "collect_evidence"


def route_after_evidence(state: SanctionsReviewState):
    if state.get("status") == "failed":
        return "reset_after_failure"
    return "detect_sanctions_change"


def route_after_sanctions_check(state: SanctionsReviewState):
    if state.get("status") == "failed":
        return "reset_after_failure"

    # [DYNAMIC RE-EVALUATION] Re-evaluate if sanctions changed
    # while the wire was open or new evidence arrived.
    if (
        state.get("sanctions_changed")
        or state.get("pending_event") == "new_evidence"
    ):
        return "re_evaluate"

    return "waiting_for_event"


def route_after_re_evaluation(state: SanctionsReviewState):
    if state.get("status") == "failed":
        return "reset_after_failure"

    # [HITL GATE] Workflow-level decisions are routed to a human.
    if state.get("hitl_required"):
        return "waiting_for_admin"

    return "complete_review"


def route_after_admin(state: SanctionsReviewState):
    if state.get("status") == "failed":
        return "reset_after_failure"

    if state.get("admin_decision") in {
        "approved",
        "rejected",
        "modified",
    }:
        return "complete_review"

    raise ValueError("Cannot continue without a valid admin decision.")


def route_after_external_event(state: SanctionsReviewState):
    event = state.get("pending_event")

    # [EVENT-DRIVEN RESUME] Different external events resume
    # different parts of the investigation.
    if event == "new_evidence":
        return "collect_evidence"

    if event == "sanctions_update":
        return "detect_sanctions_change"

    raise ValueError(f"Unsupported external event: {event}")


def route_after_failure_reset(state: SanctionsReviewState):
    # [FAILURE RECOVERY] Resume from the node that actually failed.
    failed_node = state.get("failed_node")

    valid_nodes = {
        "load_review",
        "collect_evidence",
        "detect_sanctions_change",
        "prepare_re_evaluation",
        "re_evaluate",
        "complete_review",
    }

    if failed_node not in valid_nodes:
        raise ValueError(
            f"Cannot recover unknown failed node: {failed_node}"
        )

    return failed_node


# ============================================================
# [INTERRUPT / DURABLE WAIT]
# Workflow can safely pause and resume after an external event.
# ============================================================

def waiting_for_event(state: SanctionsReviewState) -> dict[str, Any]:
    event = interrupt({
        "type": "external_event",
        "workflow": "sanctions_review",
        "wire_id": state.get("wire_id"),
        "review_id": state.get("review_id"),
        "reason": "Waiting for an external event.",
        "allowed_events": [
            "new_evidence",
            "sanctions_update",
        ],
    })

    if not isinstance(event, dict):
        raise ValueError("External event must be a dictionary.")

    event_type = event.get("event_type")

    if event_type not in {
        "new_evidence",
        "sanctions_update",
    }:
        raise ValueError(
            f"Unsupported external event: {event_type}"
        )

    return {
        "pending_event": event_type,
        "event_id": event.get("event_id"),
        "status": "re_evaluating",
        "current_node": "waiting_for_event",
        "updated_at": utc_now(),
    }


# ============================================================
# [HITL / HUMAN-IN-THE-LOOP]
# Irreversible or high-risk decisions require human approval.
# ============================================================

def waiting_for_admin(state: SanctionsReviewState) -> dict[str, Any]:
    decision = interrupt({
        "type": "human_review",
        "workflow": "sanctions_review",
        "wire_id": state.get("wire_id"),
        "review_id": state.get("review_id"),
        "task_id": state.get("hitl_task_id"),
        "reason": state.get("hitl_reason"),
        "recommended_action": state.get("recommended_action"),
    })

    if not isinstance(decision, dict):
        raise ValueError("Admin decision must be a dictionary.")

    admin_decision = decision.get("decision")

    if admin_decision not in {
        "approved",
        "rejected",
        "modified",
    }:
        raise ValueError("Invalid admin decision.")

    return {
        "admin_decision": admin_decision,
        "admin_id": decision.get("admin_id"),
        "admin_notes": decision.get("notes", ""),
        "decision": admin_decision,
        "status": "analyzing",
        "current_node": "waiting_for_admin",
        "updated_at": utc_now(),
    }


# ============================================================
# [FAILURE RECOVERY / HUMAN RESOLUTION]
# Failed workflows pause until the persisted failure ticket
# is explicitly resolved.
# ============================================================

def reset_after_failure(state: SanctionsReviewState) -> dict[str, Any]:
    resolution = interrupt({
        "type": "ticket_resolution",
        "workflow": "sanctions_review",
        "wire_id": state.get("wire_id"),
        "review_id": state.get("review_id"),
        "ticket_id": state.get("failure_ticket_id"),
        "failed_node": state.get("failed_node"),
        "error_type": state.get("error_type"),
        "error_message": state.get("error_message"),
        "failure": state.get("failure"),
        "reason": (
            "Workflow execution failed. "
            "The workflow is paused until the failure "
            "ticket is explicitly resolved."
        ),
    })

    if not isinstance(resolution, dict):
        raise ValueError("Ticket resolution must be a dictionary.")

    if resolution.get("action") != "resolved":
        raise ValueError(
            "Workflow ticket must be explicitly resolved."
        )

    return {
        "status": "re_evaluating",
        "pending_event": "failure",
        "current_node": "reset_after_failure",
        "failure_resolved": True,
        "failure_resolution_notes": resolution.get("notes", ""),
        "updated_at": utc_now(),
    }


# ============================================================
# [HYBRID RAG + CONSTRAINED REACT]
# RAG grounds the investigation in policy; constrained ReAct
# performs bounded evidence-based investigation through MCP.
# ============================================================

async def re_evaluate(
    state: SanctionsReviewState,
) -> dict[str, Any]:
    try:
        country = state.get("destination_country", "")
        current_status = state.get(
            "current_sanctions_status",
            "UNKNOWN",
        )

        # [POLICY GROUNDING]
        policy_query = (
            "What is the required action when the sanctions "
            "status of a destination country changes while "
            "an open wire transfer review is still in progress?"
        )

        policy_result = hybrid_rag(policy_query)
        policy_context = policy_result.get("context", "")
        policy_answer = policy_result.get("answer", "")

        retrieved_policy = list(
            state.get("retrieved_policy", [])
        )

        if policy_context:
            retrieved_policy.append(policy_context)

        # [BOUNDED REASONING]
        question = (
            f"Re-evaluate wire #{state.get('wire_id')} "
            f"because the sanctions status for '{country}' "
            f"changed or new evidence arrived during an open "
            f"manual review. Current sanctions status: "
            f"'{current_status}'. Verify the wire, account, "
            f"transactions and sanctions evidence using MCP. "
            f"Do not invent evidence. Escalate if unsafe "
            f"or inconclusive."
        )

        react_result = await constrained_react_node({
            **state,
            "question": question,
            "retrieved_policy": retrieved_policy,
        })

        investigation_status = react_result.get(
            "investigation_status",
            "escalated",
        )
        investigation_answer = react_result.get(
            "investigation_answer",
            "",
        )
        investigation_reason = react_result.get(
            "investigation_reason"
        )
        investigation_history = react_result.get(
            "investigation_history",
            [],
        )
        investigation_steps = react_result.get(
            "investigation_steps",
            0,
        )

        analysis = (
            f"Policy grounding: {policy_answer}\n\n"
            f"Investigation result: {investigation_answer}"
        )

        # [HITL DECISION RULE]
        # Sanctioned destinations or inconclusive investigations
        # must not be finalized automatically.
        requires_hitl = (
            current_status == "SANCTIONED"
            or investigation_status == "escalated"
        )

        if requires_hitl:
            hitl_reason = (
                "The destination country became SANCTIONED "
                "during an open wire review, or the investigation "
                "could not safely reach a final conclusion."
            )

            # [IDEMPOTENCY] Reuse an existing HITL task instead
            # of creating duplicate tasks after graph resumption.
            task_id = state.get("hitl_task_id")

            if task_id is None:
                task_id = db.create_human_review_task(
                    workflow_type="sanctions_review",
                    wire_id=state.get("wire_id"),
                    review_id=state.get("review_id"),
                    status="open",
                    reason=hitl_reason,
                    recommended_action="escalate",
                    created_at=utc_now(),
                )

            return {
                "status": "waiting_for_admin",
                "hitl_required": True,
                "hitl_task_id": task_id,
                "hitl_reason": hitl_reason,
                "recommended_action": "escalate",
                "risk_level": "high",
                "analysis": analysis,
                "retrieved_policy": retrieved_policy,
                "policy_query": policy_query,
                "policy_answer": policy_answer,
                "investigation_status": investigation_status,
                "investigation_answer": investigation_answer,
                "investigation_reason": investigation_reason,
                "investigation_history": investigation_history,
                "investigation_steps": investigation_steps,
                "current_node": "re_evaluate",
                "last_node": state.get("current_node"),
            }

        # [SAFE AUTOMATIC PATH]
        return {
            "status": "analyzing",
            "hitl_required": False,
            "hitl_task_id": None,
            "recommended_action": "continue",
            "risk_level": "low",
            "decision": "continue",
            "decision_reason": (
                "No material sanctions impact was "
                "identified after re-evaluation."
            ),
            "analysis": analysis,
            "retrieved_policy": retrieved_policy,
            "policy_query": policy_query,
            "policy_answer": policy_answer,
            "investigation_status": investigation_status,
            "investigation_answer": investigation_answer,
            "investigation_reason": investigation_reason,
            "investigation_history": investigation_history,
            "investigation_steps": investigation_steps,
            "current_node": "re_evaluate",
            "last_node": state.get("current_node"),
        }

    except Exception as e:
        return fail_review(
            state=state,
            error=e,
            failed_node="re_evaluate",
        )


# ============================================================
# [STATE GRAPH CONSTRUCTION]
# Graph owns durable orchestration, routing, HITL, retries/recovery,
# and termination. Constrained ReAct remains inside one node.
# ============================================================

def build_graph():
    builder = StateGraph(SanctionsReviewState)

    builder.add_node("load_review", load_review)
    builder.add_node("collect_evidence", collect_evidence)
    builder.add_node(
        "detect_sanctions_change",
        detect_sanctions_change,
    )
    builder.add_node(
        "prepare_re_evaluation",
        prepare_re_evaluation,
    )
    builder.add_node("re_evaluate", re_evaluate)
    builder.add_node("waiting_for_event", waiting_for_event)
    builder.add_node("waiting_for_admin", waiting_for_admin)
    builder.add_node(
        "reset_after_failure",
        reset_after_failure,
    )
    builder.add_node("complete_review", complete_review)

    # [START]
    builder.add_edge(START, "load_review")

    # [CONDITIONAL EDGE] Load -> evidence or failure recovery.
    builder.add_conditional_edges(
        "load_review",
        route_after_load,
        {
            "collect_evidence": "collect_evidence",
            "reset_after_failure": "reset_after_failure",
        },
    )

    # Evidence -> sanctions check.
    builder.add_conditional_edges(
        "collect_evidence",
        route_after_evidence,
        {
            "detect_sanctions_change": "detect_sanctions_change",
            "reset_after_failure": "reset_after_failure",
        },
    )

    # [SANCTIONS CHANGE ROUTING]
    builder.add_conditional_edges(
        "detect_sanctions_change",
        route_after_sanctions_check,
        {
            "re_evaluate": "prepare_re_evaluation",
            "waiting_for_event": "waiting_for_event",
            "reset_after_failure": "reset_after_failure",
        },
    )

    builder.add_edge(
        "prepare_re_evaluation",
        "re_evaluate",
    )

    # [HITL ROUTING] Re-evaluation decides whether human review is needed.
    builder.add_conditional_edges(
        "re_evaluate",
        route_after_re_evaluation,
        {
            "waiting_for_admin": "waiting_for_admin",
            "complete_review": "complete_review",
            "reset_after_failure": "reset_after_failure",
        },
    )

    # [HUMAN DECISION ROUTING]
    builder.add_conditional_edges(
        "waiting_for_admin",
        route_after_admin,
        {
            "complete_review": "complete_review",
            "reset_after_failure": "reset_after_failure",
        },
    )

    # [EXTERNAL EVENT ROUTING]
    builder.add_conditional_edges(
        "waiting_for_event",
        route_after_external_event,
        {
            "collect_evidence": "collect_evidence",
            "detect_sanctions_change": "detect_sanctions_change",
        },
    )

    # [FAILURE RECOVERY]
    builder.add_conditional_edges(
        "reset_after_failure",
        route_after_failure_reset,
        {
            "load_review": "load_review",
            "collect_evidence": "collect_evidence",
            "detect_sanctions_change": "detect_sanctions_change",
            "prepare_re_evaluation": "prepare_re_evaluation",
            "re_evaluate": "re_evaluate",
            "complete_review": "complete_review",
        },
    )

    # [TERMINATION]
    builder.add_edge("complete_review", END)

    return builder


graph_builder = build_graph()