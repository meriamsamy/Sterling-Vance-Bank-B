"""
The functions the platform backend (admin + user surfaces) actually
calls. Nothing in state_graph/suspicious_activity/*.py talks to an HTTP
framework directly — this module is the seam: a Flask/FastAPI route
handler imports these functions, everything below only knows about
LangGraph + the database.

Covers: Issue "Implement Persistent Investigation State & Checkpointing"
        Issue "Implement Failure Ticket & Recovery Path"
        Issue "Add Investigation Database Support"

Thread IDs: LangGraph needs a thread_id BEFORE the first invoke, but
investigation_id is only generated INSIDE the graph (by
create_investigation, since it's the one calling db.create_investigation).
So start_investigation() mints its own thread_id up front, runs the
graph, reads back the real investigation_id the graph just created, and
writes the (investigation_id -> thread_id) mapping into the
investigations.thread_id column. Every other function here looks the
mapping up from the database rather than assuming any particular
thread_id shape — that's what makes "resume potentially from a totally
different process, days later" actually work: nothing but the DB row
needs to survive between calls.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from langgraph.types import Command

from state_graph.checkpointing_layer import checkpoint_context
from state_graph.suspicious_activity.investigation_graph import build_graph
from state_graph.suspicious_activity.investigation_nodes import create_failure_ticket

import sys
from pathlib import Path

MCP_DIR = Path(__file__).resolve().parents[2] / "mcp_server"
if str(MCP_DIR) not in sys.path:
    sys.path.insert(0, str(MCP_DIR))
import mcp_server.db_access as db  # noqa: E402

WORKFLOW_TYPE = "suspicious_activity"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _thread_id_for(investigation_id: int) -> str:
    row = db.get_investigation(investigation_id)
    if row is None or not row.get("thread_id"):
        raise ValueError(
            f"No thread_id on record for investigation #{investigation_id}. "
            "Was it created through start_investigation()?"
        )
    return row["thread_id"]


def _extract_interrupt_payload(snapshot) -> dict[str, Any] | None:
    """
    A paused run's interrupt payload lives on the state snapshot's
    pending tasks, not on the returned state values. Structured this
    way so admin/user surfaces can show *why* a run is paused (the
    dict passed to interrupt({...}) in investigation_graph.py) without
    needing to know LangGraph's internals themselves.
    """
    for task in getattr(snapshot, "tasks", ()) or ():
        interrupts = getattr(task, "interrupts", ()) or ()
        if interrupts:
            return interrupts[0].value
    return None


async def _describe(graph, config: dict) -> dict[str, Any]:
    snapshot = await graph.aget_state(config)
    interrupt_payload = _extract_interrupt_payload(snapshot)
    if interrupt_payload is not None:
        return {
            "paused": True,
            "interrupt": interrupt_payload,
            "values": snapshot.values,
        }
    return {
        "paused": False,
        "interrupt": None,
        "values": snapshot.values,
    }


async def _run(
    graph,
    config: dict,
    input_or_command: Any,
    investigation_id: int | None,
) -> dict[str, Any]:
    """
    Every entry point below routes through here. This is the ONE place
    that catches unplanned node failures (Issue 6) — nodes themselves
    let exceptions propagate (see investigation_nodes.py), so whatever
    exception surfaces here means LangGraph's checkpoint reflects the
    LAST NODE THAT ACTUALLY COMPLETED, and `.next` tells us exactly
    which node was about to run when it broke.
    """
    try:
        await graph.ainvoke(input_or_command, config)
    except Exception as e:
        snapshot = await graph.aget_state(config)
        failed_node = snapshot.next[0] if snapshot.next else "unknown"
        inv_id = investigation_id or snapshot.values.get("investigation_id")
        ticket_id = create_failure_ticket(inv_id, failed_node, e)
        return {
            "status": "failed",
            "investigation_id": inv_id,
            "ticket_id": ticket_id,
            "failed_node": failed_node,
            "error": f"{type(e).__name__}: {e}",
        }

    described = await _describe(graph, config)
    if described["paused"]:
        return {
            "status": "paused",
            "investigation_id": described["values"].get("investigation_id"),
            "interrupt": described["interrupt"],
        }
    return {
        "status": "closed",
        "investigation_id": described["values"].get("investigation_id"),
        "decision": described["values"].get("decision"),
        "decision_reason": described["values"].get("decision_reason"),
    }


# ============================================================
# Public API
# ============================================================

async def start_investigation(customer_id: int, reason: str) -> dict[str, Any]:
    thread_id = f"investigation-{uuid.uuid4().hex[:16]}"
    config = {"configurable": {"thread_id": thread_id}}

    async with checkpoint_context() as checkpointer:
        graph = build_graph().compile(checkpointer=checkpointer)

        result = await _run(
            graph,
            config,
            {"customer_id": customer_id, "reason": reason},
            investigation_id=None,
        )

        investigation_id = result.get("investigation_id")
        if investigation_id is not None:
            db.update_investigation(investigation_id, updated_at=_utc_now(), thread_id=thread_id)

        return result


async def submit_external_evidence(
    investigation_id: int,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    """
    The resume side of WAITING_FOR_EVIDENCE. `evidence` is keyed by
    evidence_type, e.g. {"customer_statement": "...", "source_of_funds": "..."}.
    This is what the submit_investigation_evidence MCP tool (Issue 8)
    calls under the hood — an external system or a compliance officer
    submitting a document doesn't need to know anything about LangGraph,
    just an investigation_id and a payload.
    """
    thread_id = _thread_id_for(investigation_id)
    config = {"configurable": {"thread_id": thread_id}}

    async with checkpoint_context() as checkpointer:
        graph = build_graph().compile(checkpointer=checkpointer)
        return await _run(graph, config, Command(resume=evidence), investigation_id)


async def resolve_hitl_task(
    investigation_id: int,
    decision: str,
    notes: str,
    assigned_to: int,
) -> dict[str, Any]:
    """
    Called by the admin platform when an admin acts on a pending HITL
    task. decision must be one of "approve" | "reject" | "more_evidence"
    (investigation_graph.route_after_admin only understands those).

    Marks the human_review_tasks row completed FIRST (so the admin
    platform's own list immediately reflects it was acted on), then
    resumes the graph with the admin's actual decision — the resumed
    run reads admin_decision from this exact payload, not a hardcoded
    auto-approve.
    """
    thread_id = _thread_id_for(investigation_id)
    config = {"configurable": {"thread_id": thread_id}}

    async with checkpoint_context() as checkpointer:
        graph = build_graph().compile(checkpointer=checkpointer)
        snapshot = await graph.aget_state(config)
        task_id = snapshot.values.get("hitl_task_id")

        if task_id is not None:
            db.complete_human_review_task(
                task_id=task_id,
                decision=decision,
                notes=notes,
                assigned_to=assigned_to,
                completed_at=_utc_now(),
            )

        return await _run(
            graph,
            config,
            Command(resume={"decision": decision, "notes": notes}),
            investigation_id,
        )


async def resolve_failure_ticket(investigation_id: int, ticket_id: int) -> dict[str, Any]:
    """
    Called once an admin has fixed whatever the failure ticket
    describes. Marks the ticket resolved, then resumes with `None` as
    input — LangGraph's own semantics for "continue from the last
    checkpoint," which retries the exact node that raised, not the one
    after it (see investigation_nodes.create_failure_ticket for why
    that only works because nodes don't swallow their own exceptions).
    """
    db.resolve_workflow_ticket(ticket_id, resolved_at=_utc_now())

    thread_id = _thread_id_for(investigation_id)
    config = {"configurable": {"thread_id": thread_id}}

    async with checkpoint_context() as checkpointer:
        graph = build_graph().compile(checkpointer=checkpointer)
        return await _run(graph, config, None, investigation_id)


async def get_investigation_snapshot(investigation_id: int) -> dict[str, Any]:
    """Read-only status check for the platform's investigation detail view."""
    thread_id = _thread_id_for(investigation_id)
    config = {"configurable": {"thread_id": thread_id}}

    async with checkpoint_context() as checkpointer:
        graph = build_graph().compile(checkpointer=checkpointer)
        return await _describe(graph, config)