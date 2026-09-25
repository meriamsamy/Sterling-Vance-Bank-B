"""
Durable runner for the Customer Risk Monitoring state graph.

The runner owns:
- durable SQLite checkpoint lifecycle
- workflow thread IDs
- starting a workflow
- reading the latest checkpoint
- resuming an interrupted HITL task
- resuming when new customer activity arrives
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from langgraph.types import Command

from mcp_server import db_access as db
from state_graph.checkpointing_layer import checkpoint_context

from .graph import build_customer_risk_graph


# ------------------------------------------------------------------
# Workflow identity
# ------------------------------------------------------------------

def default_thread_id(customer_id: int) -> str:
    """
    Return the durable LangGraph thread ID for a customer.

    This must NOT depend on the chat/conversation thread.
    """
    return f"customer-risk-{customer_id}"


def make_config(thread_id: str) -> dict[str, Any]:
    return {
        "configurable": {
            "thread_id": thread_id,
        }
    }


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_graph(checkpointer):
    """
    Build the Customer Risk graph using the supplied durable
    checkpointer.
    """
    return build_customer_risk_graph(checkpointer=checkpointer)


# ------------------------------------------------------------------
# Start workflow
# ------------------------------------------------------------------

async def _start_customer_risk_async(
    customer_id: int,
    thread_id: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """
    Start a Customer Risk workflow.
    """

    workflow_thread_id = thread_id or default_thread_id(customer_id)

    initial_state = {
        "run_id": run_id or workflow_thread_id,
        "customer_id": customer_id,
        "last_processed_transaction_id": None,
        "checkpoint_version": 0,
    }

    config = make_config(workflow_thread_id)

    async with checkpoint_context() as checkpointer:
        graph = _get_graph(checkpointer)

        result = await graph.ainvoke(
            initial_state,
            config=config,
        )

        snapshot = await graph.aget_state(config)

    return {
        "result": result,
        "snapshot": snapshot,
        "thread_id": workflow_thread_id,
    }


# ------------------------------------------------------------------
# Read workflow state
# ------------------------------------------------------------------

async def _get_customer_risk_state_async(
    customer_id: int,
    thread_id: str | None = None,
):
    """
    Read the latest durable checkpoint for a Customer Risk workflow.
    """

    workflow_thread_id = thread_id or default_thread_id(customer_id)
    config = make_config(workflow_thread_id)

    async with checkpoint_context() as checkpointer:
        graph = _get_graph(checkpointer)

        snapshot = await graph.aget_state(config)

    return snapshot


# ------------------------------------------------------------------
# Resume after Admin HITL decision
# ------------------------------------------------------------------

async def _resume_customer_risk_async(
    customer_id: int,
    decision: str,
    assigned_to: int,
    reason: str = "",
    thread_id: str | None = None,
) -> dict[str, Any]:
    """
    Resume a paused Customer Risk HITL workflow.

    The DB HITL task is marked completed only after the graph
    successfully resumes.
    """

    if decision not in {"approve", "reject"}:
        raise ValueError(
            "Customer Risk decision must be 'approve' or 'reject'."
        )

    workflow_thread_id = thread_id or default_thread_id(customer_id)
    config = make_config(workflow_thread_id)

    resume_data = {
        "decision": decision,
        "reason": reason,
    }

    async with checkpoint_context() as checkpointer:
        graph = _get_graph(checkpointer)

        result = await graph.ainvoke(
            Command(resume=resume_data),
            config=config,
        )

        snapshot = await graph.aget_state(config)

    values = snapshot.values or {}
    task_id = values.get("hitl_task_id")

    if task_id is not None:
        db.complete_human_review_task(
            task_id=int(task_id),
            decision=decision,
            notes=reason,
            assigned_to=int(assigned_to),
            completed_at=_utc_now(),
        )

    return {
        "result": result,
        "snapshot": snapshot,
        "thread_id": workflow_thread_id,
    }


# ------------------------------------------------------------------
# Resume after new customer activity
# ------------------------------------------------------------------

async def _resume_after_activity_async(
    customer_id: int,
    transaction_id: int,
    thread_id: str | None = None,
) -> dict[str, Any]:
    """
    Resume the durable Customer Risk workflow when new activity arrives.

    This resumes the interrupt created by wait_for_activity().
    """

    workflow_thread_id = thread_id or default_thread_id(customer_id)
    config = make_config(workflow_thread_id)

    resume_data = {
        "transaction_id": transaction_id,
    }

    async with checkpoint_context() as checkpointer:
        graph = _get_graph(checkpointer)

        result = await graph.ainvoke(
            Command(resume=resume_data),
            config=config,
        )

        snapshot = await graph.aget_state(config)

    return {
        "result": result,
        "snapshot": snapshot,
        "thread_id": workflow_thread_id,
    }


# ------------------------------------------------------------------
# Public synchronous wrappers
# ------------------------------------------------------------------

def start_customer_risk(
    customer_id: int,
    thread_id: str | None = None,
    run_id: str | None = None,
):
    return asyncio.run(
        _start_customer_risk_async(
            customer_id=customer_id,
            thread_id=thread_id,
            run_id=run_id,
        )
    )


def get_customer_risk_state(
    customer_id: int,
    thread_id: str | None = None,
):
    return asyncio.run(
        _get_customer_risk_state_async(
            customer_id=customer_id,
            thread_id=thread_id,
        )
    )


def resume_customer_risk(
    customer_id: int,
    decision: str,
    assigned_to: int,
    reason: str = "",
    thread_id: str | None = None,
):
    return asyncio.run(
        _resume_customer_risk_async(
            customer_id=customer_id,
            decision=decision,
            assigned_to=assigned_to,
            reason=reason,
            thread_id=thread_id,
        )
    )


def resume_after_activity(
    customer_id: int,
    transaction_id: int,
    thread_id: str | None = None,
):
    return asyncio.run(
        _resume_after_activity_async(
            customer_id=customer_id,
            transaction_id=transaction_id,
            thread_id=thread_id,
        )
    )


# ------------------------------------------------------------------
# Async versions for FastAPI
# ------------------------------------------------------------------

start_customer_risk_async = _start_customer_risk_async
get_customer_risk_state_async = _get_customer_risk_state_async
resume_customer_risk_async = _resume_customer_risk_async
resume_after_activity_async = _resume_after_activity_async
