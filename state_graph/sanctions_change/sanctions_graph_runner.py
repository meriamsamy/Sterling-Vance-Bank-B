from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import db_access as db
from langgraph.types import Command

from state_graph.checkpointing_layer import checkpointer

from .sanctions_graph import graph_builder


# ============================================================
# [DURABLE EXECUTION] Compile the graph with a persistent
# checkpointer so state survives pauses, crashes, and resumes.
# ============================================================

graph = graph_builder.compile(
    checkpointer=checkpointer,
)


# ============================================================
# [THREAD-BASED STATE]
# Each wire review gets a stable thread_id so LangGraph can
# retrieve and resume the exact workflow state.
# ============================================================

def make_config(thread_id: str) -> dict[str, Any]:
    return {
        "configurable": {
            "thread_id": thread_id,
        }
    }


def default_thread_id(wire_id: int) -> str:
    return f"wire-review-{wire_id}"


# ============================================================
# [START WORKFLOW]
# Initialize the durable State Graph for a wire investigation.
# ============================================================

def start_review(
    wire_id: int,
    thread_id: str | None = None,
) -> dict[str, Any]:
    thread_id = thread_id or default_thread_id(wire_id)

    initial_state = {
        "wire_id": wire_id,
        "status": "open",
        "pending_event": None,
        "sanctions_changed": False,
        "sanctions_impact": "unknown",
        "hitl_required": False,
        "hitl_task_id": None,
        "failure_ticket_id": None,
        "failure_resolved": False,
        "risk_level": "unknown",
        "recommended_action": "unknown",
        "evidence": [],
        "new_evidence": [],
        "retrieved_policy": [],
        "react_steps": [],
        "react_step_count": 0,
        "react_max_steps": 6,
        "investigation_history": [],
        "investigation_steps": 0,
    }

    return graph.invoke(
        initial_state,
        config=make_config(thread_id),
    )


# ============================================================
# [EXTERNAL EVENT RESUME]
# Resume an interrupted workflow when new evidence or a
# sanctions update occurs while the wire review is open.
# ============================================================

def resume_after_event(
    wire_id: int,
    event_type: str,
    thread_id: str | None = None,
    event_id: str | None = None,
) -> dict[str, Any]:
    if event_type not in {
        "new_evidence",
        "sanctions_update",
    }:
        raise ValueError(
            f"Unsupported external event: {event_type}"
        )

    thread_id = thread_id or default_thread_id(wire_id)

    # [INTERRUPT/RESUME] Command.resume continues the exact
    # checkpointed workflow instead of starting a new graph run.
    return graph.invoke(
        Command(
            resume={
                "event_type": event_type,
                "event_id": event_id,
            }
        ),
        config=make_config(thread_id),
    )


# ============================================================
# [HITL RESUME]
# Resume the graph after a compliance/admin decision.
# ============================================================

def resume_after_admin(
    wire_id: int,
    decision: str,
    admin_id: int,
    notes: str = "",
    thread_id: str | None = None,
) -> dict[str, Any]:
    if decision not in {
        "approved",
        "rejected",
        "modified",
    }:
        raise ValueError(
            f"Unsupported admin decision: {decision}"
        )

    thread_id = thread_id or default_thread_id(wire_id)
    config = make_config(thread_id)

    result = graph.invoke(
        Command(
            resume={
                "decision": decision,
                "admin_id": admin_id,
                "notes": notes,
            }
        ),
        config=config,
    )

    # [AUDIT TRAIL] Persist completion of the human review
    # after the graph resumes from the HITL interrupt.
    snapshot = graph.get_state(config)
    task_id = snapshot.values.get("hitl_task_id")

    if task_id is not None:
        db.complete_human_review_task(
            task_id=task_id,
            decision=decision,
            notes=notes,
            assigned_to=admin_id,
            completed_at=utc_now(),
        )

    return result


# ============================================================
# [FAILURE RECOVERY]
# Resolve the persisted workflow ticket, then resume the
# checkpointed graph from the failure interrupt.
# ============================================================

def resume_after_ticket_resolution(
    wire_id: int,
    notes: str = "",
    thread_id: str | None = None,
) -> dict[str, Any]:
    thread_id = thread_id or default_thread_id(wire_id)
    config = make_config(thread_id)

    snapshot = graph.get_state(config)
    ticket_id = snapshot.values.get("failure_ticket_id")

    if ticket_id is None:
        raise ValueError(
            "No failure ticket exists for this workflow."
        )

    # [DURABLE FAILURE HANDLING] Mark the persisted failure
    # ticket as resolved before allowing workflow continuation.
    db.resolve_workflow_ticket(
        ticket_id=ticket_id,
        resolved_at=utc_now(),
    )

    return graph.invoke(
        Command(
            resume={
                "action": "resolved",
                "notes": notes,
            }
        ),
        config=config,
    )


# ============================================================
# [STATE INSPECTION]
# Read the latest checkpoint without executing the graph.
# ============================================================

def get_review_state(
    wire_id: int,
    thread_id: str | None = None,
):
    thread_id = thread_id or default_thread_id(wire_id)

    return graph.get_state(
        make_config(thread_id)
    )


def is_waiting(
    wire_id: int,
    thread_id: str | None = None,
) -> bool:
    # [WORKFLOW STATUS] snapshot.next indicates whether the
    # durable graph has a pending node/interrupt to resume.
    snapshot = get_review_state(
        wire_id,
        thread_id,
    )
    return bool(snapshot.next)


# ============================================================
# [UTC TIMESTAMP]
# Consistent timezone-aware timestamps for audit records.
# ============================================================

def utc_now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()