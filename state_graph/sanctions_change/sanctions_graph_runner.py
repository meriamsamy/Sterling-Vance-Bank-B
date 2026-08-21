from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from pathlib import Path
import sys
import asyncio
from contextlib import asynccontextmanager

ROOT_DIR = Path(__file__).resolve().parents[2]

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

MCP_DIR = ROOT_DIR / "mcp"

if str(MCP_DIR) not in sys.path:
    sys.path.insert(0, str(MCP_DIR))

import db_access as db

from langgraph.types import Command

from state_graph.checkpointing_layer import checkpoint_context

from .sanctions_graph import graph_builder


# ============================================================
# [DURABLE EXECUTION] Compile the graph with a persistent
# checkpointer so state survives pauses, crashes, and resumes.
#
# AsyncSqliteSaver is used because some graph operations are
# executed through LangGraph's async API.
# ============================================================

# ============================================================
# [DURABLE EXECUTION]
# Compile the graph with a persistent async checkpointer.
#
# The checkpointer lifetime is managed by checkpoint_context().
# ============================================================

@asynccontextmanager
async def _get_graph():

    async with checkpoint_context() as checkpointer:

        graph = graph_builder.compile(
            checkpointer=checkpointer,
        )

        yield graph


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

async def _start_review_async(
    wire_id: int,
    thread_id: str | None = None,
) -> dict[str, Any]:

    thread_id = (
        thread_id
        or default_thread_id(wire_id)
    )

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

    async with _get_graph() as graph:

        return await graph.ainvoke(
            initial_state,
            config=make_config(thread_id),
        )


def start_review(
    wire_id: int,
    thread_id: str | None = None,
) -> dict[str, Any]:

    return asyncio.run(
        _start_review_async(
            wire_id=wire_id,
            thread_id=thread_id,
        )
    )


# ============================================================
# [EXTERNAL EVENT RESUME]
# Resume an interrupted workflow when new evidence or a
# sanctions update occurs while the wire review is open.
# ============================================================

async def _resume_after_event_async(
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

    thread_id = (
        thread_id
        or default_thread_id(wire_id)
    )

    # ========================================================
    # [INTERRUPT/RESUME]
    # Command.resume continues the exact checkpointed
    # workflow instead of starting a new graph run.
    # ========================================================

    async with _get_graph() as graph:

        return await graph.ainvoke(
            Command(
                resume={
                    "event_type": event_type,
                    "event_id": event_id,
                }
            ),
            config=make_config(thread_id),
        )


def resume_after_event(
    wire_id: int,
    event_type: str,
    thread_id: str | None = None,
    event_id: str | None = None,
) -> dict[str, Any]:

    return asyncio.run(
        _resume_after_event_async(
            wire_id=wire_id,
            event_type=event_type,
            thread_id=thread_id,
            event_id=event_id,
        )
    )


# ============================================================
# [HITL RESUME]
# Resume the graph after a compliance/admin decision.
# ============================================================

async def _resume_after_admin_async(
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

    thread_id = (
        thread_id
        or default_thread_id(wire_id)
    )

    config = make_config(thread_id)

    async with _get_graph() as graph:

        result = await graph.ainvoke(
            Command(
                resume={
                    "decision": decision,
                    "admin_id": admin_id,
                    "notes": notes,
                }
            ),
            config=config,
        )

        # ====================================================
        # [AUDIT TRAIL]
        # Persist completion of the human review
        # after the graph resumes from the HITL interrupt.
        # ====================================================

        snapshot = await graph.aget_state(config)

        task_id = snapshot.values.get(
            "hitl_task_id"
        )

        if task_id is not None:

            db.complete_human_review_task(
                task_id=task_id,
                decision=decision,
                notes=notes,
                assigned_to=admin_id,
                completed_at=utc_now(),
            )

        return result


def resume_after_admin(
    wire_id: int,
    decision: str,
    admin_id: int,
    notes: str = "",
    thread_id: str | None = None,
) -> dict[str, Any]:

    return asyncio.run(
        _resume_after_admin_async(
            wire_id=wire_id,
            decision=decision,
            admin_id=admin_id,
            notes=notes,
            thread_id=thread_id,
        )
    )


# ============================================================
# [FAILURE RECOVERY]
# Resolve the persisted workflow ticket, then resume the
# checkpointed graph from the failure interrupt.
# ============================================================

async def _resume_after_ticket_resolution_async(
    wire_id: int,
    notes: str = "",
    thread_id: str | None = None,
) -> dict[str, Any]:

    thread_id = (
        thread_id
        or default_thread_id(wire_id)
    )

    config = make_config(thread_id)

    async with _get_graph() as graph:

        snapshot = await graph.aget_state(config)

        ticket_id = snapshot.values.get(
            "failure_ticket_id"
        )

        if ticket_id is None:

            raise ValueError(
                "No failure ticket exists for this workflow."
            )

        # ====================================================
        # [DURABLE FAILURE HANDLING]
        # Mark the persisted failure ticket as resolved
        # before allowing workflow continuation.
        # ====================================================

        db.resolve_workflow_ticket(
            ticket_id=ticket_id,
            resolved_at=utc_now(),
        )

        return await graph.ainvoke(
            Command(
                resume={
                    "action": "resolved",
                    "notes": notes,
                }
            ),
            config=config,
        )


def resume_after_ticket_resolution(
    wire_id: int,
    notes: str = "",
    thread_id: str | None = None,
) -> dict[str, Any]:

    return asyncio.run(
        _resume_after_ticket_resolution_async(
            wire_id=wire_id,
            notes=notes,
            thread_id=thread_id,
        )
    )


# ============================================================
# [STATE INSPECTION]
# Read the latest checkpoint without executing the graph.
# ============================================================

async def _get_review_state_async(
    wire_id: int,
    thread_id: str | None = None,
):

    thread_id = (
        thread_id
        or default_thread_id(wire_id)
    )

    async with _get_graph() as graph:

        return await graph.aget_state(
            make_config(thread_id)
        )


def get_review_state(
    wire_id: int,
    thread_id: str | None = None,
):

    return asyncio.run(
        _get_review_state_async(
            wire_id=wire_id,
            thread_id=thread_id,
        )
    )


def is_waiting(
    wire_id: int,
    thread_id: str | None = None,
) -> bool:

    # ========================================================
    # [WORKFLOW STATUS]
    # snapshot.next indicates whether the durable graph
    # has a pending node/interrupt to resume.
    # ========================================================

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


# ============================================================
# [DEMO / LOCAL TEST]
# ============================================================

def main():

    wire_id = 42

    print("=" * 60)

    print(
        f"Starting sanctions review for Wire #{wire_id}"
    )

    print("=" * 60)

    try:

        result = start_review(wire_id)

        print("\n[WORKFLOW RESULT]")

        print(result)

        print("\n[CHECKPOINT STATE]")

        snapshot = get_review_state(wire_id)

        print(
            f"Status: "
            f"{snapshot.values.get('status')}"
        )

        print(
            f"Current node: "
            f"{snapshot.values.get('current_node')}"
        )

        print(
            f"Sanctions status: "
            f"{snapshot.values.get('current_sanctions_status')}"
        )

        print(
            f"Sanctions changed: "
            f"{snapshot.values.get('sanctions_changed')}"
        )

        print(
            f"Risk level: "
            f"{snapshot.values.get('risk_level')}"
        )

        print(
            f"Recommended action: "
            f"{snapshot.values.get('recommended_action')}"
        )

        print(
            f"Decision: "
            f"{snapshot.values.get('decision')}"
        )

        print(
            f"Waiting: "
            f"{is_waiting(wire_id)}"
        )

        if snapshot.next:

            print("\n[WAITING FOR]")

            print(snapshot.next)

    except Exception as e:

        print("\n[ERROR]")

        print(type(e).__name__)

        print(str(e))


import uuid


def run_hitl_demo():
    wire_id = 11
    admin_id = 1

    # Unique thread so every demo run starts clean
    thread_id = f"wire-review-{wire_id}-demo-{uuid.uuid4().hex}"

    print("=" * 70)
    print("STERLING & VANCE — SANCTIONS HITL DEMO")
    print("=" * 70)

    print(f"\nThread ID: {thread_id}")

    # ------------------------------------------------------------
    # 1. Start workflow
    # ------------------------------------------------------------
    print(f"\n[1] Starting review for Wire #{wire_id}...")

    start_review(
        wire_id=wire_id,
        thread_id=thread_id,
    )

    snapshot = get_review_state(
        wire_id=wire_id,
        thread_id=thread_id,
    )

    print("Status:", snapshot.values.get("status"))
    print("Current node:", snapshot.values.get("current_node"))
    print("Next:", snapshot.next)

    # IMPORTANT:
    # current_node is the node that just executed.
    # snapshot.next tells us what LangGraph will execute next.
    if "waiting_for_event" not in snapshot.next:
        print("\n[ERROR] Expected workflow to wait for an external event.")
        print("Actual current node:", snapshot.values.get("current_node"))
        print("Actual next:", snapshot.next)
        return

    print("\n[OK] Workflow is waiting for an external event.")

    # ------------------------------------------------------------
    # 2. Get destination country
    # ------------------------------------------------------------
    country = snapshot.values.get("destination_country")

    if not country:
        print("\n[ERROR] Destination country not found.")
        return

    print(f"\n[2] Destination country: {country}")

    # ------------------------------------------------------------
    # 3. Get current sanctions status
    # ------------------------------------------------------------
    current_status = db.get_sanctions_status(country)
    current_version = db.get_sanctions_version()

    print("Current sanctions status:", current_status)
    print("Current sanctions version:", current_version)

    # ------------------------------------------------------------
    # 4. Create REAL sanctions change
    # ------------------------------------------------------------
    if current_status == "SANCTIONED":
        print("\n[3] Country is already sanctioned.")
        print("Temporarily clearing it...")

        db.update_sanctions_status(
            country_code=country,
            sanctioned=False,
            timestamp=utc_now(),
        )

    print("\n[3] Creating sanctions update...")

    event = db.update_sanctions_status(
        country_code=country,
        sanctioned=True,
        timestamp=utc_now(),
    )

    print("External sanctions event:")
    print(event)

    if not event.get("changed"):
        print("\n[ERROR] No sanctions change was created.")
        return

    # ------------------------------------------------------------
    # 5. Resume after external event
    # ------------------------------------------------------------
    print("\n[4] Resuming workflow after sanctions update...")

    resume_after_event(
        wire_id=wire_id,
        event_type="sanctions_update",
        event_id=str(event["event_id"]),
        thread_id=thread_id,
    )

    snapshot = get_review_state(
        wire_id=wire_id,
        thread_id=thread_id,
    )

    print("\n" + "-" * 70)
    print("AFTER SANCTIONS UPDATE")
    print("-" * 70)

    print("Status:", snapshot.values.get("status"))
    print("Current node:", snapshot.values.get("current_node"))
    print("Sanctions changed:", snapshot.values.get("sanctions_changed"))
    print("Sanctions impact:", snapshot.values.get("sanctions_impact"))
    print("HITL required:", snapshot.values.get("hitl_required"))
    print("HITL task ID:", snapshot.values.get("hitl_task_id"))
    print("Next:", snapshot.next)

    # ------------------------------------------------------------
    # 6. Verify HITL
    # ------------------------------------------------------------
    if not snapshot.values.get("hitl_required"):
        print("\n[ERROR] Workflow did not reach HITL.")
        return

    if "waiting_for_admin" not in snapshot.next:
        print("\n[ERROR] HITL is required but workflow is not waiting for admin.")
        print("Current node:", snapshot.values.get("current_node"))
        print("Next:", snapshot.next)
        return

    print("\n[OK] Workflow reached HITL.")

    print("\n" + "=" * 70)
    print("                 HUMAN REVIEW REQUIRED")
    print("=" * 70)

    print(f"""
Wire ID:              {wire_id}
Destination Country:  {country}
Sanctions Changed:    {snapshot.values.get("sanctions_changed")}
Sanctions Impact:     {snapshot.values.get("sanctions_impact")}
Risk Level:           {snapshot.values.get("risk_level")}
Recommended Action:   {snapshot.values.get("recommended_action")}
HITL Task ID:         {snapshot.values.get("hitl_task_id")}
""")

    # ------------------------------------------------------------
    # 7. Ask admin
    # ------------------------------------------------------------
    while True:
        decision = input(
            "\nAdmin decision [approved/rejected]: "
        ).strip().lower()

        if decision in {"approved", "rejected"}:
            break

        print("Invalid decision.")
        print("Please enter: approved or rejected")

    notes = input("Notes (optional): ").strip()

    # ------------------------------------------------------------
    # 8. Resume after admin decision
    # ------------------------------------------------------------
    print("\n[5] Resuming workflow after admin decision...")

    result = resume_after_admin(
        wire_id=wire_id,
        decision=decision,
        admin_id=admin_id,
        notes=notes,
        thread_id=thread_id,
    )

    # ------------------------------------------------------------
    # 9. Final state
    # ------------------------------------------------------------
    snapshot = get_review_state(
        wire_id=wire_id,
        thread_id=thread_id,
    )

    print("\n" + "=" * 70)
    print("                    FINAL RESULT")
    print("=" * 70)

    print("Status:", snapshot.values.get("status"))
    print("Current node:", snapshot.values.get("current_node"))
    print("Decision:", snapshot.values.get("decision"))
    print("HITL task ID:", snapshot.values.get("hitl_task_id"))
    print("Next:", snapshot.next)

    print("\nWorkflow result:")
    print(result)

if __name__ == "__main__":
    run_hitl_demo()