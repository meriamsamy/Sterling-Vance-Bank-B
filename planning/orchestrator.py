"""
planning/orchestrator.py — connects teammate 1's BankDynamicDecomposition
(decomposition.py) to teammate 2's router (router.py).

*** REWRITTEN for her latest decomposition.py ***
Her file no longer has a fixed decomposition-first plan; it's a fully
dynamic planner where the LLM chooses one task at a time
(BankDynamicDecomposition.choose_next_task, reusing the toolkit's real
DynamicDecision schema) and expects the caller to supply
`execute_task(task: TaskNode, history) -> observation`. This file builds
that callback: it classifies+routes the task through router.dispatch(),
executes it for real (direct db call / PS / ToT / LATS), and returns the
observation text her run() loop feeds back into the next planning step.

Nothing in decomposition.py was changed. account_ids/customer_id context
that used to live on TaskNode itself (a design from a version of
decomposition.py that no longer exists) is now tracked in a plain dict
inside run_investigation() instead — TaskNode is intentionally strict
(extra="forbid") in her version, so no fields were added to it.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .decomposition import BankDynamicDecomposition, TaskNode
from .router import RoutingTrace, classify_description, dispatch, route_subtask

# Same artifacts/ convention the forked toolkit's own cli.py uses
# (planning_lab/cli.py: save_artifact -> artifacts/run-<timestamp>.json),
# resolved against THIS repo's root (the toolkit is pip-installed, so its
# own ROOT would resolve inside site-packages if we called its
# save_artifact() directly).
ARTIFACTS_DIR = Path(__file__).resolve().parent.parent / "artifacts"


@dataclass
class InvestigationRun:
    order_executed: list[str] = field(default_factory=list)
    llm_calls: int = 0
    trace: RoutingTrace = field(default_factory=RoutingTrace)
    steps: list = field(default_factory=list)  # DynamicStep objects from her DynamicRun


def save_run_artifact(run: InvestigationRun, customer_id: int) -> Path:
    """Persist this run's routing trace (task_id/method/reason/timestamp
    per sub-task) into artifacts/, same JSON-payload style as the
    toolkit's own run artifacts — satisfies Issue #68's 'routing decisions
    are recorded in the execution trace'."""
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = ARTIFACTS_DIR / f"run-{stamp}.json"
    payload = {
        "mode": "dynamic",
        "customer_id": customer_id,
        "order_executed": run.order_executed,
        "llm_calls": run.llm_calls,
        "routing_trace": run.trace.as_payload(),
        "steps": [
            {"task_id": step.task.task_id, "description": step.task.description,
             "action_type": step.task.action_type, "observation": step.observation}
            for step in run.steps
        ],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return path


def run_investigation(
    customer_id: int,
    llm,
    environment=None,
    max_steps: int = 6,
    save_artifact: bool = True,
) -> InvestigationRun:
    """Runs BankDynamicDecomposition against a real customer, routing
    every LLM-chosen task through the real router + real db_access/MCP
    tools. This is the dynamic/interleaved method — the LLM sees each
    real observation before deciding the next task, so it can react to
    something unexpected (a real unlinked counterparty, a real sanctions
    hit) instead of following a plan blind to what's actually being found.
    """
    planner = BankDynamicDecomposition(llm)
    run = InvestigationRun()
    # Mutable context the execute_task closure below reads/updates as the
    # investigation progresses — account_ids only becomes known once the
    # planner actually asks for accounts, since nothing here is fixed order.
    context = {"customer_id": customer_id, "account_ids": []}

    def execute_task(task: TaskNode, history: list[tuple[str, str]]):
        decision = route_subtask(task)
        task.action_type = decision.method  # the hookup her TaskNode.action_type comment anticipates
        operation = classify_description(task.description).direct_operation

        # If the LLM asked for something account-scoped before ever asking
        # for the accounts themselves, don't crash — tell it so, and let
        # the next planning step react (it sees this observation too).
        needs_accounts = decision.method == "direct" and operation != "find_accounts"
        if needs_accounts and not context["account_ids"]:
            return ("No account context yet for this customer — call a task to "
                    "fetch customer accounts first before requesting transactions "
                    "or sanctions checks scoped to specific accounts.")

        evidence = "\n".join(f"[{desc}] {obs}" for desc, obs in history) or "No prior evidence."
        result = dispatch(
            task,
            evidence,
            llm,
            account_ids=context["account_ids"],
            customer_id=context["customer_id"],
            environment=environment,
            trace=run.trace,
        )

        run.order_executed.append(task.task_id)
        if decision.method != "direct":
            run.llm_calls += 1
        if operation == "find_accounts":
            context["account_ids"] = [row["account_id"] for row in result]

        return result if isinstance(result, str) else str(result)

    dynamic_run = planner.run(
        goal=f"Investigate customer {customer_id}'s financial activity for suspicious "
             f"activity and produce a policy-grounded risk recommendation.",
        execute_task=execute_task,
        max_steps=max_steps,
    )
    run.steps = dynamic_run.steps

    if save_artifact:
        save_run_artifact(run, customer_id)

    return run