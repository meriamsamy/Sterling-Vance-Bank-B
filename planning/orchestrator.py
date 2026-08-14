"""
planning/orchestrator.py — connects teammate 1's InvestigationDAG
(decomposition.py) to teammate 2's router (router.py). This is the piece
that was missing before: something that actually walks
get_executable_tasks(), calls dispatch() for each one, and feeds results
back with mark_completed().

Ownership note: this file sits between two concerns and touches both.
decomposition.py itself is unchanged except for two additive fields on
TaskNode (account_ids, destination_country) — no cycle-check or
decomposition logic was touched. Recommend teammate 1 reviews this PR
since it drives her DAG; teammate 3 should review the LATS/environment
plumbing once planning/environment.py exists.

Demonstrates BOTH decomposition methods on the same real request type,
which the lab requires:
- run_investigation(..., dynamic=False): decomposition-first — the full
  7-task plan from decompose_goal() is built up front, then executed in
  topological batches, blind to what analyze_wires finds.
- run_investigation(..., dynamic=True): dynamic/interleaved — after
  analyze_wires actually executes, its real output is inspected and
  apply_dynamic_decomposition() can inject a new counterparty sub-task
  that decomposition-first would never have planned for.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .decomposition import InvestigationDAG, TaskDecomposerAdapter, TaskNode
from .router import RoutingTrace, dispatch, route_subtask

# Same artifacts/ convention the forked toolkit's own cli.py uses
# (planning_lab/cli.py: save_artifact -> artifacts/run-<timestamp>.json),
# extended with a routing_trace field rather than a second logging system.
# Resolved against THIS repo's root, not the toolkit's — the toolkit is
# pip-installed (git+...), so its own ROOT would resolve inside
# site-packages if we called its save_artifact() directly.
ARTIFACTS_DIR = Path(__file__).resolve().parent.parent / "artifacts"

# Very small, literal parse of analyze_wires' free-text PS output looking
# for something like "counterparty ACC_UNKNOWN_99" or "unknown counterparty
# CP-118". This is the "early sub-task result reshaping what comes next"
# trigger the lab asks for — kept intentionally simple since it only
# gates whether apply_dynamic_decomposition() fires, not a decision itself.
_COUNTERPARTY_PATTERN = re.compile(
    r"(?:unlinked|unknown|unrecognized)\s+counterpart(?:y|ies)[:\s]+([A-Z0-9_\-]+)",
    re.IGNORECASE,
)


def _extract_unlinked_counterparty(analyze_wires_output: str) -> str | None:
    if not isinstance(analyze_wires_output, str):
        return None
    match = _COUNTERPARTY_PATTERN.search(analyze_wires_output)
    return match.group(1) if match else None


@dataclass
class InvestigationRun:
    dag: InvestigationDAG
    llm_calls: int = 0
    tokens_estimate: int = 0
    order_executed: list[str] = field(default_factory=list)
    dynamic_task_injected: str | None = None
    trace: RoutingTrace = field(default_factory=RoutingTrace)


def save_run_artifact(run: InvestigationRun, customer_id: int, dynamic: bool) -> Path:
    """Persist this run's routing trace (task_id/method/reason/timestamp
    per sub-task) into artifacts/, same JSON-payload style as the
    toolkit's own run artifacts — satisfies 'routing decisions are
    recorded in the execution trace' (Issue #68)."""
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = ARTIFACTS_DIR / f"run-{stamp}.json"
    payload = {
        "mode": "dynamic" if dynamic else "decomposition-first",
        "customer_id": customer_id,
        "order_executed": run.order_executed,
        "dynamic_task_injected": run.dynamic_task_injected,
        "llm_calls": run.llm_calls,
        "routing_trace": run.trace.as_payload(),
        "results": {task_id: run.dag.nodes[task_id].result for task_id in run.order_executed},
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return path


def _evidence_context(dag: InvestigationDAG, node: TaskNode) -> str:
    """Join completed dependency results into the context a sub-task's
    algorithm (PS/ToT/LATS) reasons over. Direct-route dependency results
    are dicts/lists (real db rows); str() is fine, they aren't fed back
    into a prompt that would displace real data with a summary."""
    if not node.dependencies:
        return "No prior evidence — this is a root sub-task."
    parts = []
    for dep_id in node.dependencies:
        dep = dag.nodes.get(dep_id)
        if dep and dep.result is not None:
            parts.append(f"[{dep_id}] {dep.result}")
    return "\n".join(parts) or "Dependencies completed with no reportable output."


def run_investigation(
    customer_id: int,
    llm,
    environment=None,
    dynamic: bool = True,
    save_artifact: bool = True,
) -> InvestigationRun:
    """Run the full investigation DAG for one customer.

    dynamic=True  -> interleaved: apply_dynamic_decomposition() can inject
                      investigate_counterparty_* tasks after analyze_wires
                      actually runs (see module docstring).
    dynamic=False -> decomposition-first: the initial 7-task plan from
                      decompose_goal() is executed as-is; a real
                      counterparty discovery is logged but never acted on,
                      which is the divergence case the lab asks to show.
    save_artifact -> writes the run's routing trace to artifacts/ when
                      True (default). Tests set this False to avoid
                      littering the repo with run-*.json files.
    """
    dag = InvestigationDAG()
    adapter = TaskDecomposerAdapter(dag)
    adapter.decompose_goal(str(customer_id))

    run = InvestigationRun(dag=dag)
    context = {"customer_id": customer_id, "account_ids": [], "destination_countries": []}

    while True:
        executable = dag.get_executable_tasks()
        if not executable:
            break
        for node in executable:
            node.status = "IN_PROGRESS"
            decision = route_subtask(node.task_id)
            node.action_type = decision.method  # the hookup teammate 1 already anticipated

            evidence = _evidence_context(dag, node)
            result = dispatch(
                node.task_id,
                node.description,
                evidence,
                llm,
                account_ids=node.account_ids or context["account_ids"],
                customer_id=context["customer_id"],
                destination_country=node.destination_country,
                environment=environment,
                trace=run.trace,
            )
            dag.mark_completed(node.task_id, result)
            run.order_executed.append(node.task_id)
            if decision.method != "direct":
                run.llm_calls += 1

            # Propagate discovered context to sub-tasks that still need it.
            if node.task_id == "find_accounts":
                context["account_ids"] = [row["account_id"] for row in result]
            if node.task_id == "check_sanctions":
                context["destination_countries"] = result.get("checked", [])

            # --- [DYNAMIC DECOMPOSITION HOOK] ---
            # Only wired up when dynamic=True. decomposition-first mode
            # deliberately skips this so the two modes can be compared on
            # the same request (see README's comparison table).
            if dynamic and node.task_id == "analyze_wires":
                counterparty = _extract_unlinked_counterparty(result)
                if counterparty:
                    adapter.apply_dynamic_decomposition(node, {"unlinked_counterparty": counterparty})
                    run.dynamic_task_injected = f"investigate_counterparty_{counterparty}"

    if save_artifact:
        save_run_artifact(run, customer_id, dynamic)

    return run