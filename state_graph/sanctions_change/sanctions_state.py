from __future__ import annotations

from typing import Any, Literal, TypedDict


ReviewStatus = Literal[
    "open",
    "collecting_evidence",
    "analyzing",
    "waiting",
    "re_evaluating",
    "waiting_for_admin",
    "failed",
    "completed",
]

EventType = Literal[
    "new_evidence",
    "sanctions_update",
    "admin_decision",
    "failure",
]

SanctionsStatus = Literal[
    "CLEAR",
    "SANCTIONED",
]

SanctionsImpact = Literal[
    "unknown",
    "no_impact",
    "affected",
]

RiskLevel = Literal[
    "unknown",
    "low",
    "medium",
    "high",
]

RecommendedAction = Literal[
    "unknown",
    "continue",
    "wait",
    "escalate",
    "hold",
]


class SanctionsReviewState(TypedDict, total=False):
    # ========================================================
    # Identity
    # ========================================================

    review_id: int
    wire_id: int
    customer_id: int

    # ========================================================
    # Wire Context
    # ========================================================

    destination_country: str
    wire_status: str
    wire_amount: float
    source_account_id: int

    # ========================================================
    # Workflow
    # ========================================================

    status: ReviewStatus
    current_node: str

    pending_event: EventType | None
    event_id: str | None

    # ========================================================
    # Evidence
    # ========================================================

    evidence: list[dict[str, Any]]
    new_evidence: list[dict[str, Any]]

    # ========================================================
    # Sanctions Versioning
    # ========================================================

    sanctions_status_at_start: SanctionsStatus | None
    sanctions_version_at_start: int | None

    current_sanctions_version: int | None
    current_sanctions_status: SanctionsStatus | None

    event_sanctions_version: int | None

    sanctions_changed: bool
    sanctions_impact: SanctionsImpact

    previous_sanctions_status: SanctionsStatus | None

    # ========================================================
    # RAG / Policy
    # ========================================================

    policy_query: str | None
    retrieved_policy: list[str]
    policy_answer: str | None

    # ========================================================
    # Analysis
    # ========================================================

    analysis: str | None

    risk_score: float | None
    risk_level: RiskLevel

    recommended_action: RecommendedAction

    # ========================================================
    # Constrained ReAct
    # ========================================================

    react_steps: list[str]
    react_step_count: int
    react_max_steps: int

    # ========================================================
    # Investigation
    # ========================================================

    question: str | None

    investigation_status: str | None
    investigation_answer: str | None
    investigation_reason: str | None

    investigation_history: list[dict[str, Any]]
    investigation_steps: int

    # ========================================================
    # HITL
    # ========================================================

    hitl_required: bool
    hitl_reason: str | None
    hitl_task_id: int | None

    # ========================================================
    # Admin
    # ========================================================

    admin_decision: str | None
    admin_notes: str | None
    admin_id: int | None

    # ========================================================
    # Failure Recovery
    # ========================================================

    failure: dict[str, Any] | None
    failure_ticket_id: int | None

    checkpoint_id: str | None

    error_type: str | None
    error_message: str | None
    failed_node: str | None

    failure_resolved: bool
    failure_resolution_notes: str | None

    # ========================================================
    # Final Decision
    # ========================================================

    decision: str | None
    decision_reason: str | None

    # ========================================================
    # Audit
    # ========================================================

    last_node: str | None
    last_transition: str | None

    created_at: str | None
    updated_at: str | None