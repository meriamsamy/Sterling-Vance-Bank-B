"""
The Suspicious Activity Investigation graph.

Covers: Issue "Design Suspicious Activity Investigation State Graph"
        Issue "Implement External Evidence Waiting & Resume"
        Issue "Implement HITL Escalation for Investigation"

Shape:

    create_investigation
          |
    collect_initial_evidence
          |
    analyze_evidence  <---------------------+
          |                                 |
    [missing_evidence?]                     |
       /             |                      |
      NO             YES                    |
      |               |                     |
      v               v                     |
  reassess_       wait_for_evidence         |
  investigation        |                    |
      |          ingest_new_evidence -------+
  [hitl_required?]
     /        \
    NO         YES
    |           |
    v           v
  close_    waiting_for_admin
  investigation    |
    ^         [admin_decision?]
    |          /      |      \
    |     approve  reject  more_evidence
    |         /      /          |
    +---------+-----+           v
                          wait_for_evidence

wait_for_evidence and waiting_for_admin are the two genuine pauses —
implemented with LangGraph's interrupt(), which persists the paused
state to state_graph/checkpoints.db (via checkpointing_layer.
checkpoint_context()) and stops execution until something calls
graph.ainvoke(Command(resume=...), config) with the SAME thread_id.
That resume can come minutes or days later, from a completely different
process — that's the whole point of using a durable SQLite checkpointer
instead of an in-memory one.

Failure handling is NOT modeled as graph nodes/edges — see the comment
in investigation_nodes.py above create_failure_ticket(). Nodes let
exceptions propagate; investigation_graph_runner.py is where failures
actually get caught and turned into tickets.
"""
from __future__ import annotations

from typing import Any

from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt

from state_graph.suspicious_activity.investigation_state import InvestigationState
from state_graph.suspicious_activity.investigation_nodes import (
    create_investigation,
    collect_initial_evidence,
    ingest_new_evidence,
    update_transition,
)
from state_graph.suspicious_activity.investigation_rag import analyze_evidence
from state_graph.suspicious_activity.investigation_lats import reassess_investigation


# ============================================================
# WAIT_FOR_EVIDENCE — genuine pause, Issue 4
# ============================================================

def wait_for_evidence(state: InvestigationState) -> InvestigationState:
    payload: dict[str, Any] = interrupt({
        "reason": "waiting_for_evidence",
        "investigation_id": state.get("investigation_id"),
        "missing_evidence": state.get("missing_evidence"),
        "analysis": state.get("analysis"),
    })
    # Execution only reaches this point after graph.ainvoke(
    #   Command(resume=payload), config
    # ) is called with the same thread_id — potentially a different
    # process, potentially days later. `payload` is expected to be a
    # dict like {"wires": [...], "customer_statement": "..."} keyed by
    # evidence_type, produced by investigation_graph_runner.
    # submit_external_evidence().
    return update_transition(
        state=state,
        node_name="wait_for_evidence",
        status="analyzing_evidence",
        new_evidence=payload or {},
    )


# ============================================================
# WAITING_FOR_ADMIN — genuine pause, Issue 5
# ============================================================

def waiting_for_admin(state: InvestigationState) -> InvestigationState:
    decision_payload: dict[str, Any] = interrupt({
        "reason": "hitl_required",
        "investigation_id": state.get("investigation_id"),
        "hitl_task_id": state.get("hitl_task_id"),
        "hitl_reason": state.get("hitl_reason"),
        "candidate_assessment": state.get("candidate_assessment"),
        "risk_level": state.get("risk_level"),
        "confidence": state.get("confidence"),
    })
    # Resumed via graph.ainvoke(Command(resume={"decision": "...",
    # "notes": "..."}), config) — see investigation_graph_runner.
    # resolve_hitl_task(), which is also where the human_review_tasks
    # row actually gets marked completed, tied to the real admin actor.
    return update_transition(
        state=state,
        node_name="waiting_for_admin",
        status="admin_decided",
        admin_decision=decision_payload.get("decision"),
        admin_notes=decision_payload.get("notes"),
    )


# ============================================================
# CLOSE_INVESTIGATION — terminal node
# ============================================================

def close_investigation(state: InvestigationState) -> InvestigationState:
    admin_decision = state.get("admin_decision")
    label = state.get("assessed_label", "insufficient_evidence")

    if admin_decision == "reject":
        decision = "rejected"
        reason = f"Rejected by admin. {state.get('hitl_reason', '')}"
    elif admin_decision == "approve":
        decision = f"closed_{label}"
        reason = f"Approved by admin. {state.get('candidate_assessment', '')}"
    else:
        # Closed without ever needing HITL — low risk, high confidence,
        # grounded validation passed.
        decision = f"closed_{label}"
        reason = state.get("candidate_assessment", "")

    return update_transition(
        state=state,
        node_name="close_investigation",
        status="closed",
        decision=decision,
        decision_reason=reason,
    )


# ============================================================
# Routing
# ============================================================

def route_after_analysis(state: InvestigationState) -> str:
    return "wait_for_evidence" if state.get("missing_evidence") else "reassess_investigation"


def route_after_reassessment(state: InvestigationState) -> str:
    return "waiting_for_admin" if state.get("hitl_required") else "close_investigation"


def route_after_admin(state: InvestigationState) -> str:
    if state.get("admin_decision") == "more_evidence":
        return "wait_for_evidence"
    return "close_investigation"


# ============================================================
# Graph assembly
# ============================================================

def build_graph() -> StateGraph:
    graph = StateGraph(InvestigationState)

    graph.add_node("create_investigation", create_investigation)
    graph.add_node("collect_initial_evidence", collect_initial_evidence)
    graph.add_node("analyze_evidence", analyze_evidence)
    graph.add_node("wait_for_evidence", wait_for_evidence)
    graph.add_node("ingest_new_evidence", ingest_new_evidence)
    graph.add_node("reassess_investigation", reassess_investigation)
    graph.add_node("waiting_for_admin", waiting_for_admin)
    graph.add_node("close_investigation", close_investigation)

    graph.add_edge(START, "create_investigation")
    graph.add_edge("create_investigation", "collect_initial_evidence")
    graph.add_edge("collect_initial_evidence", "analyze_evidence")

    graph.add_conditional_edges(
        "analyze_evidence",
        route_after_analysis,
        {
            "wait_for_evidence": "wait_for_evidence",
            "reassess_investigation": "reassess_investigation",
        },
    )

    # The cycle: wait -> ingest -> re-analyze -> (still missing?) -> wait again
    graph.add_edge("wait_for_evidence", "ingest_new_evidence")
    graph.add_edge("ingest_new_evidence", "analyze_evidence")

    graph.add_conditional_edges(
        "reassess_investigation",
        route_after_reassessment,
        {
            "waiting_for_admin": "waiting_for_admin",
            "close_investigation": "close_investigation",
        },
    )

    graph.add_conditional_edges(
        "waiting_for_admin",
        route_after_admin,
        {
            "wait_for_evidence": "wait_for_evidence",
            "close_investigation": "close_investigation",
        },
    )

    graph.add_edge("close_investigation", END)

    return graph