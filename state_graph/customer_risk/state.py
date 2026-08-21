from __future__ import annotations

from typing import Any, Literal
from typing_extensions import TypedDict


RiskLevel = Literal["low", "medium", "high"]

WorkflowStatus = Literal[
    "starting",
    "collecting_activity",
    "planning_review",
    "retrieving_policy",
    "assessing_risk",
    "waiting_for_activity",
    "risk_changed",
    "escalated",
    "failed",
]


class CustomerRiskState(TypedDict, total=False):

    # =========================
    # Identity
    # =========================
    run_id: str
    customer_id: int

    # =========================
    # Risk
    # =========================
    current_risk_level: RiskLevel
    previous_risk_level: RiskLevel | None
    assessed_risk_level: RiskLevel

    # =========================
    # Activity
    # =========================
    last_processed_transaction_id: int | None
    triggering_transaction_id: int | None
    recent_activity: list[dict[str, Any]]

    # =========================
    # LLM / Investigation
    # =========================
    decomposition: dict[str, Any]
    policy_context: str
    policy_status: str

    # =========================
    # Assessment
    # =========================
    risk_changed: bool
    risk_reason: str
    assessment_confidence: float

    # =========================
    # Workflow
    # =========================
    status: WorkflowStatus
    current_node: str

    # =========================
    # Shared infrastructure
    # =========================
    hitl_task_id: str | None
    failure_ticket_id: str | None

    # HITL decision
    admin_decision: Literal["approve", "reject"] | None
    admin_reason: str | None

    # Audit / checkpoint metadata
    checkpoint_version: int
    
    # =========================
    # Persistence / Audit
    # =========================
    checkpoint_version: int
    started_at: str
    updated_at: str

