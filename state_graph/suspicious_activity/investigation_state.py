"""
State schema for the Suspicious Activity Investigation graph.

Covers: Issue "Design Suspicious Activity Investigation State Graph"
        Issue "Implement Persistent Investigation State & Checkpointing"

Every field here is something a human looking at a paused/failed run on
the admin platform needs to be able to see — this is the full shape of
what gets written to state_graph/checkpoints.db (via checkpointing_layer.
checkpoint_context()) after every meaningful node transition, not just a
log of what happened.
"""
from __future__ import annotations

from typing import Any, TypedDict


class InvestigationState(TypedDict, total=False):
    # ---- identity (CREATE_INVESTIGATION) ----
    investigation_id: int
    customer_id: int
    reason: str
    status: str
    created_at: str
    updated_at: str

    # ---- collected evidence (COLLECT_EVIDENCE) ----
    # evidence["customer"], evidence["accounts"], evidence["transactions"]
    # (dict keyed by account_id), evidence["wires"], evidence["sanctions_hits"],
    # evidence["related_employees"]
    evidence: dict[str, Any]
    evidence_flags: list[str]          # e.g. ["sanctions", "structuring", "self_dealing"]

    # ---- RAG-grounded sufficiency analysis (ANALYZE_EVIDENCE) ----
    analysis: str                      # human-readable grounded explanation
    rag_context: str                   # retrieved policy text, kept for audit
    missing_evidence: list[str]        # external evidence types still needed, if any

    # ---- external evidence arriving later (WAITING_FOR_EVIDENCE cycle) ----
    new_evidence: dict[str, Any] | None

    # ---- LATS reassessment (REASSESS_INVESTIGATION) ----
    lats_candidates: list[dict[str, Any]]
    candidate_assessment: str
    validation_result: dict[str, Any]  # from validate_investigation()
    risk_level: str                    # "low" | "medium" | "high" | "unknown"
    confidence: float
    assessed_label: str                # "legitimate_activity" | "potential_fraud" | ...

    # ---- HITL ----
    hitl_required: bool
    hitl_task_id: int | None
    hitl_reason: str | None
    admin_decision: str | None         # "approve" | "reject" | "more_evidence"
    admin_notes: str | None

    # ---- failure / ticket (separate path from HITL) ----
    ticket_id: int | None
    error: str | None
    failed_node: str | None

    # ---- final outcome ----
    decision: str | None
    decision_reason: str | None

    # ---- bookkeeping ----
    last_completed_step: str
    current_node: str