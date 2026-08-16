"""
planning/orchestrator.py — connects teammate 1's two decomposition methods
(decomposition.py's BankDecompositionAdapter = decomposition-first, and
dynamic_decomposition.py's BankDynamicDecomposition = dynamic/interleaved)
to teammate 2's router (router.py).

*** UPDATED ***
Two entry points now, one per method she actually built — both were
required by the lab ("both methods, not one"), and she implemented them as
two separate files rather than one replacing the other:

  run_investigation_decomposition_first() -> BankDecompositionAdapter.decompose()
      + .execute() (full plan up front, parallel ThreadPoolExecutor batches)

  run_investigation_dynamic() -> BankDynamicDecomposition.run()
      (LLM chooses one task at a time, reacts to each real observation)

Both her callback contracts (execute_task) are plain sync callables, called
from a worker thread (decomposition-first) or a plain sync loop (dynamic).
router.dispatch() is properly async now (see its docstring for why), so
both execute_task closures below call router.dispatch_sync() — the safe
sync bridge — instead of dispatch() directly.

Neither of her files was changed to build this.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .decomposition import BankDecompositionAdapter, TaskNode as DecompFirstTaskNode
from .dynamic_decomposition import BankDynamicDecomposition, TaskNode as DynamicTaskNode
from .router import RoutingTrace, classify_description, dispatch_sync, route_subtask

# Same artifacts/ convention the forked toolkit's own cli.py uses
# (planning_lab/cli.py: save_artifact -> artifacts/run-<timestamp>.json),
# resolved against THIS repo's root (the toolkit is pip-installed, so its
# own ROOT would resolve inside site-packages if we called its
# save_artifact() directly).
ARTIFACTS_DIR = Path(__file__).resolve().parent.parent / "artifacts"


@dataclass
class InvestigationRun:
    mode: str  # "decomposition-first" | "dynamic"
    order_executed: list[str] = field(default_factory=list)
    llm_calls: int = 0
    trace: RoutingTrace = field(default_factory=RoutingTrace)
    detail: dict = field(default_factory=dict)  # mode-specific payload for the artifact


def save_run_artifact(run: InvestigationRun, customer_id: int) -> Path:
    """Persist this run's routing trace into artifacts/, same JSON-payload
    style as the toolkit's own run artifacts — satisfies Issue #68's
    'routing decisions are recorded in the execution trace'."""
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = ARTIFACTS_DIR / f"run-{stamp}.json"
    payload = {
        "mode": run.mode,
        "customer_id": customer_id,
        "order_executed": run.order_executed,
        "llm_calls": run.llm_calls,
        "routing_trace": run.trace.as_payload(),
        **run.detail,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return path


def _investigation_goal(customer_id: int) -> str:
    return (
        f"Investigate customer {customer_id}'s financial activity for suspicious "
        f"activity and produce a policy-grounded risk recommendation."
    )


# ---------------------------------------------------------------------------
# Decomposition-first — planning/decomposition.py
# ---------------------------------------------------------------------------
def run_investigation_decomposition_first(
    customer_id: int,
    llm,
    environment=None,
    save_artifact: bool = True,
) -> InvestigationRun:
    adapter = BankDecompositionAdapter(llm)
    dag = adapter.decompose(_investigation_goal(customer_id))

    run = InvestigationRun(mode="decomposition-first")
    context = {"customer_id": customer_id, "account_ids": []}

    def execute_task(task: DecompFirstTaskNode, dependency_outputs: dict):
        decision = route_subtask(task)
        task.action_type = decision.method
        operation = classify_description(task.description).direct_operation

        needs_accounts = decision.method == "direct" and operation != "find_accounts"
        if needs_accounts and not context["account_ids"]:
            return ("No account context yet for this customer — the accounts task "
                    "must complete before transactions/sanctions lookups scoped to accounts.")

        evidence = "\n".join(f"[{dep}] {out}" for dep, out in dependency_outputs.items()) or "No prior evidence."
        result = dispatch_sync(
            task, evidence, llm,
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

    outputs = adapter.execute(dag, execute_task)

    run.detail = {
        "topological_order": dag.topological_order(),
        "execution_batches": dag.execution_batches(),
        "tasks": {
            task_id: {"description": t.description, "action_type": t.action_type,
                      "dependencies": t.dependencies, "status": t.status, "result": t.result}
            for task_id, t in dag.nodes.items()
        },
        "outputs": outputs,
    }

    if save_artifact:
        save_run_artifact(run, customer_id)
    return run


# ---------------------------------------------------------------------------
# Dynamic / interleaved — planning/dynamic_decomposition.py
# ---------------------------------------------------------------------------
def run_investigation_dynamic(
    customer_id: int,
    llm,
    environment=None,
    max_steps: int = 6,
    save_artifact: bool = True,
) -> InvestigationRun:
    planner = BankDynamicDecomposition(llm)
    run = InvestigationRun(mode="dynamic")
    context = {"customer_id": customer_id, "account_ids": []}

    def execute_task(task: DynamicTaskNode, history: list[tuple[str, str]]):
        decision = route_subtask(task)
        task.action_type = decision.method
        operation = classify_description(task.description).direct_operation

        needs_accounts = decision.method == "direct" and operation != "find_accounts"
        if needs_accounts and not context["account_ids"]:
            return ("No account context yet for this customer — call a task to "
                    "fetch customer accounts first before requesting transactions "
                    "or sanctions checks scoped to specific accounts.")

        evidence = "\n".join(f"[{desc}] {obs}" for desc, obs in history) or "No prior evidence."
        result = dispatch_sync(
            task, evidence, llm,
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
        goal=_investigation_goal(customer_id),
        execute_task=execute_task,
        max_steps=max_steps,
    )

    run.detail = {
        "steps": [
            {"task_id": step.task.task_id, "description": step.task.description,
             "action_type": step.task.action_type, "observation": step.observation}
            for step in dynamic_run.steps
        ],
    }

    if save_artifact:
        save_run_artifact(run, customer_id)
    return run