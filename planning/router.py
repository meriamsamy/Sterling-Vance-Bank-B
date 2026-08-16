"""
[ROUTING LOGIC — locatable concern]

Classifies each investigation TaskNode by its description text (task_ids
are generic — "dynamic_1" under BankDynamicDecomposition, "t1"/"t2" under
decompose_goal's decomposition-first plans — neither carries meaning) and
executes it through the right strategy: a direct MCP/db call, PS, ToT, or
LATS.

*** UPDATED: async, and wired to teammate 3's real (async) Environment ***

Two things forced this update, discovered by actually checking the live
repo instead of assuming:

1. planning/environment.py's real Environment.evaluate() is `async def`
   (it awaits real MCP tool calls). The toolkit's own lats() is plain sync
   and calls `environment.evaluate(state)` with no await — so a naive
   async Environment would just hand back an unexecuted coroutine and
   silently break LATS. _EnvironmentBridge below fixes that without
   touching the toolkit's lats() implementation at all (still called
   as-is from algorithms.run_lats, inside asyncio.to_thread — see that
   file's docstring).

2. BOTH of teammate 1's decomposition entry points call execute_task
   SYNCHRONOUSLY, not awaited:
     - decomposition.py's BankDecompositionAdapter.execute() calls it from
       ThreadPoolExecutor worker threads
     - dynamic_decomposition.py's BankDynamicDecomposition.run() calls it
       from a plain sync loop
   So dispatch() itself needed to become properly async (to await
   run_lats/run_plan_and_solve/run_tree_of_thoughts, which are now async —
   see algorithms.py), but orchestrator.py's execute_task callbacks handed
   to her code still need to be plain sync callables. dispatch_sync() below
   is that bridge: it runs dispatch()'s coroutine to completion safely,
   whether or not the calling thread already has an event loop running.
"""
from __future__ import annotations

import asyncio
import inspect
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

_MCP_DIR = Path(__file__).resolve().parent.parent / "mcp"
if str(_MCP_DIR) not in sys.path:
    sys.path.insert(0, str(_MCP_DIR))

import db_access as db  # noqa: E402

from .algorithms import EvaluationEnvironment, RouteDecision, run_lats, run_plan_and_solve, run_tree_of_thoughts
from .decomposition import TaskNode


@dataclass
class RoutingTrace:
    """Records every routing decision dispatch() makes, in the same
    lightweight style as the forked toolkit's own artifacts/run-*.json
    (planning_lab/cli.py's save_artifact): a flat list of dicts, no
    separate logging system."""

    entries: list[dict] = field(default_factory=list)

    def record(self, decision: RouteDecision) -> None:
        self.entries.append({
            "task_id": decision.task_id,
            "method": decision.method,
            "reason": decision.reason,
            "timestamp": time.time(),
        })

    def as_payload(self) -> list[dict]:
        return list(self.entries)


# ---------------------------------------------------------------------------
# Description classification. Ordered rules, first match wins. Specific
# reasoning categories (risk assessment, evidence consolidation,
# structuring, counterparty/relationship, wire analysis) are checked
# BEFORE generic lookup keywords (sanction/transaction/account), because a
# description like "check destination against sanctions list" should
# resolve as a deterministic lookup even if it also mentions "wire".
# ---------------------------------------------------------------------------
_CLASSIFICATION_RULES: list[tuple[str, re.Pattern, str, str | None]] = [
    ("risk_assessment", re.compile(r"risk assessment|recommendation|final (verdict|decision)", re.IGNORECASE), "lats", None),
    ("combine_evidence", re.compile(r"consolidat|combine evidence|evidence consolidation", re.IGNORECASE), "tot", None),
    ("structuring", re.compile(r"structur", re.IGNORECASE), "ps", None),
    ("counterparty", re.compile(r"counterpart|relationship", re.IGNORECASE), "ps", None),
    ("sanctions_lookup", re.compile(r"sanction", re.IGNORECASE), "direct", "check_sanctions"),
    ("wire_analysis", re.compile(r"wire transfer|wire", re.IGNORECASE), "ps", None),
    ("transactions_lookup", re.compile(r"transaction|deposit history", re.IGNORECASE), "direct", "get_transactions"),
    ("accounts_lookup", re.compile(r"\baccounts?\b", re.IGNORECASE), "direct", "find_accounts"),
]

_REASONS: dict[str, str] = {
    "direct": "Deterministic lookup against the real schema — a single db_access call, no ambiguity to plan over.",
    "ps": "One clear sequence (fetch pattern -> analyze -> finding); no competing hypotheses to search over.",
    "tot": "Several plausible competing explanations for the same evidence; needs generate/evaluate/prune, not one pass.",
    "lats": "Final recommendation; a wrong output is costly, so candidates must be scored by real DB feedback, not self-opinion.",
}

_DEFAULT_METHOD = "ps"  # safest general-purpose reasoning fallback for a description that matched nothing


@dataclass
class Classification:
    method: str
    direct_operation: str | None
    reason: str
    matched_rule: str | None


def classify_description(description: str) -> Classification:
    for rule_name, pattern, method, direct_op in _CLASSIFICATION_RULES:
        if pattern.search(description):
            return Classification(method=method, direct_operation=direct_op, reason=_REASONS[method], matched_rule=rule_name)
    return Classification(
        method=_DEFAULT_METHOD,
        direct_operation=None,
        reason=_REASONS[_DEFAULT_METHOD] + " (no keyword matched; defaulted to PS rather than guessing at a direct call.)",
        matched_rule=None,
    )


def route_subtask(node: TaskNode) -> RouteDecision:
    classification = classify_description(node.description)
    return RouteDecision(task_id=node.task_id, method=classification.method, reason=classification.reason)


# ---------------------------------------------------------------------------
# Direct tool-call handlers — no LLM, no planning algorithm. Call the exact
# db_access.py functions that back the registered MCP tools
# get_customer_accounts / get_transaction_history / check_sanctions.
# ---------------------------------------------------------------------------
def direct_find_accounts(customer_id: int) -> list[dict]:
    return db.get_customer_accounts(customer_id)


def direct_get_transactions(account_id: int) -> str:
    return db.get_transaction_history(account_id)


def direct_check_sanctions(destination_country: str) -> bool:
    return db.is_sanctioned(destination_country)


def direct_get_destination_countries(account_ids: list[int]) -> list[str]:
    return db.get_wire_destination_countries(account_ids)


# ---------------------------------------------------------------------------
# [ASYNC <-> SYNC ENVIRONMENT BRIDGE]
# Wraps whatever `environment` object dispatch() is given so it always
# presents the sync `.evaluate(state) -> EnvironmentFeedback` shape the
# toolkit's lats() expects, regardless of whether the real object underneath
# is teammate 3's async Environment (planning/environment.py) or a plain
# sync fake (used in this file's own tests / before grounding existed).
# Detection is automatic (inspect.iscoroutinefunction), so neither side has
# to know about the other's calling convention.
# ---------------------------------------------------------------------------
class _EnvironmentBridge:
    """
    Adapts the real async Environment to the synchronous interface
    expected by the toolkit's LATS implementation.

    planning_lab.lats.lats() is synchronous and does:

        feedback = environment.evaluate(state)

    The real banking Environment is asynchronous, so this bridge
    schedules its coroutine back onto the main MCP event loop.

    IMPORTANT:
    Do NOT use asyncio.run() here.

    The MCP ClientSession belongs to the main event loop. Running
    the Environment inside asyncio.run() from the LATS worker thread
    creates a different event loop and can cause mcp_session.call_tool()
    to hang indefinitely.
    """

    def __init__(
        self,
        environment,
        task_description: str | None = None,
        main_loop=None,
    ):
        self._environment = environment
        self._task_description = task_description
        self._main_loop = main_loop

    def evaluate(self, state: str):
        print(
            "[BRIDGE] BEFORE environment.evaluate()",
            flush=True,
        )

        result = self._environment.evaluate(
            state,
            task=self._task_description,
        )

        print(
            f"[BRIDGE] got result type: {type(result)}",
            flush=True,
        )

        if inspect.isawaitable(result):

            if self._main_loop is None:
                raise RuntimeError(
                    "Main event loop is required for async Environment."
                )

            print(
                "[BRIDGE] Scheduling Environment coroutine "
                "on main MCP event loop...",
                flush=True,
            )

            future = asyncio.run_coroutine_threadsafe(
                result,
                self._main_loop,
            )

            print(
                "[BRIDGE] Waiting for Environment result...",
                flush=True,
            )

            try:
                result = future.result()

            except Exception:
                print(
                    "[BRIDGE] Environment coroutine FAILED",
                    flush=True,
                )
                raise

            print(
                "[BRIDGE] Environment result received",
                flush=True,
            )

        return result


def _run_coro_sync(coro):
    """Runs an async coroutine to completion from a plain sync caller.
    Used by dispatch_sync() so dispatch() can stay properly async while
    still plugging directly into both of teammate 1's sync execute_task
    contracts (ThreadPoolExecutor workers in decomposition.py, and a plain
    sync loop in dynamic_decomposition.py)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # A loop is already running in this thread (shouldn't happen given both
    # of her callback contracts are sync, but handled rather than crashing).
    box: dict = {}
    def _runner():
        box["value"] = asyncio.run(coro)
    thread = threading.Thread(target=_runner)
    thread.start()
    thread.join()
    return box["value"]


async def dispatch(
    node: TaskNode,
    evidence_context: str,
    llm,
    *,
    account_ids: list[int] | None = None,
    customer_id: int | None = None,
    destination_country: str | None = None,
    environment=None,
    trace: RoutingTrace | None = None,
):
    """Execute one TaskNode through whatever route_subtask() decided.
    `environment` may be teammate 3's real async Environment or a sync
    fake — either works, see _EnvironmentBridge above.
    """
    decision = route_subtask(node)
    if trace is not None:
        trace.record(decision)

    if decision.method == "direct":
        classification = classify_description(node.description)
        op = classification.direct_operation
        if op == "find_accounts":
            return await asyncio.to_thread(direct_find_accounts, customer_id)
        if op == "get_transactions":
            return await asyncio.to_thread(direct_get_transactions, (account_ids or [None])[0])
        if op == "check_sanctions":
            countries = [destination_country] if destination_country else await asyncio.to_thread(direct_get_destination_countries, account_ids or [])
            if not countries:
                return {"checked": [], "sanctioned": [], "note": "No outbound wire history for this customer yet."}
            sanctioned = [c for c in countries if await asyncio.to_thread(direct_check_sanctions, c)]
            return {"checked": countries, "sanctioned": sanctioned}
        raise ValueError(f"Classified as direct but no direct_operation resolved for: {node.description!r}")

    if decision.method == "ps":
        return await run_plan_and_solve(node.description, evidence_context, llm)

    if decision.method == "tot":
        return await run_tree_of_thoughts(node.description, evidence_context, llm)

    if decision.method == "lats":
        if environment is None:
            raise ValueError(
                "This task classified as risk_assessment -> LATS, which requires a "
                "grounded `environment` (see planning/environment.py, owned by the "
                "Self-Correction + Grounding concern). Pass it in explicitly."
            )
        main_loop = asyncio.get_running_loop()

        bridge = _EnvironmentBridge(
            environment,
            task_description=node.description,
            main_loop=main_loop,
        )
        return await run_lats(node.description, evidence_context, llm, bridge)

    raise ValueError(f"Unknown route method: {decision.method!r}")


def dispatch_sync(node: TaskNode, evidence_context: str, llm, **kwargs):
    """Sync-callable wrapper around dispatch(), for the two places that
    need a plain sync callback: decomposition.py's BankDecompositionAdapter
    (called from ThreadPoolExecutor workers) and dynamic_decomposition.py's
    BankDynamicDecomposition (called from a plain sync loop). Both live in
    orchestrator.py."""
    return _run_coro_sync(dispatch(node, evidence_context, llm, **kwargs))