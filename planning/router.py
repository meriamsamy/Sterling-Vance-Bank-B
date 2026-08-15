"""
[ROUTING LOGIC — locatable concern]

*** UPDATED to match teammate 1's rewritten decomposition.py ***
Her TaskDecomposerAdapter/decompose_goal/apply_dynamic_decomposition API
(the fixed 7-task plan with semantic task_ids like "find_accounts") is
gone. It's replaced by BankDynamicDecomposition — a fully dynamic planner
that asks the LLM to choose ONE task at a time (reusing the toolkit's own
DynamicDecision schema) and hands each one to a caller-supplied
`execute_task(task: TaskNode, history)` callback. Task ids are now generic
(dynamic_1, dynamic_2, ...); there is nothing semantic left to match by id.

So routing changed from "look up task_id in a fixed table" to "classify
the task's actual description text" — the task_id can't tell you anything
anymore, only what the LLM asked to be done. route_subtask() below takes
the description string and matches it against the same investigation
areas her own system prompt lists (accounts, transactions, wire transfers,
sanctions, structuring, counterparties, relationships, evidence
consolidation, risk assessment) — same set, same intent, just read from
free text instead of a fixed id.

dispatch() now takes a TaskNode directly (the shared schema, per Issue
#68's "must use the shared task schema" constraint) instead of loose
positional strings, so orchestrator.py's execute_task callback can hand
BankDynamicDecomposition's TaskNode straight through with no translation
layer in between.
"""
from __future__ import annotations

import re
import sys
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
# Description classification. Ordered rules, first match wins. Order
# matters: specific reasoning categories (risk assessment, evidence
# consolidation, structuring, counterparty/relationship, wire analysis) are
# checked BEFORE generic lookup keywords (sanction/transaction/account),
# because a description like "analyze wire transfers for hidden links"
# contains no lookup keyword but "check destination against sanctions
# list" should resolve as a deterministic lookup even though it mentions
# "wire" too — sanctions is checked first for exactly that reason.
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
    """Takes the shared TaskNode schema directly. Classifies by
    node.description since task_id (dynamic_1, dynamic_2, ...) carries no
    semantic meaning under BankDynamicDecomposition."""
    classification = classify_description(node.description)
    return RouteDecision(task_id=node.task_id, method=classification.method, reason=classification.reason)


# ---------------------------------------------------------------------------
# Direct tool-call handlers — no LLM, no planning algorithm. These call the
# exact same db_access.py functions that back the registered MCP tools
# get_customer_accounts / get_transaction_history / check_sanctions in
# mcp/server.py (added in Issue #68).
# ---------------------------------------------------------------------------
def direct_find_accounts(customer_id: int) -> list[dict]:
    return db.get_customer_accounts(customer_id)


def direct_get_transactions(account_id: int) -> str:
    return db.get_transaction_history(account_id)


def direct_check_sanctions(destination_country: str) -> bool:
    return db.is_sanctioned(destination_country)


def direct_get_destination_countries(account_ids: list[int]) -> list[str]:
    """Real outbound wire destinations for these accounts — used when a
    check_sanctions sub-task isn't given one specific country up front."""
    return db.get_wire_destination_countries(account_ids)


def dispatch(
    node: TaskNode,
    evidence_context: str,
    llm,
    *,
    account_ids: list[int] | None = None,
    customer_id: int | None = None,
    destination_country: str | None = None,
    environment: EvaluationEnvironment | None = None,
    trace: RoutingTrace | None = None,
):
    """Execute one TaskNode through whatever route_subtask() decided.
    Direct routes bypass the LLM entirely; ps/tot hand off to
    algorithms.py, which hands off to the forked toolkit; lats also needs
    a real `environment` (teammate 3's planning/environment.py) — passed
    in here, never built here.

    If `trace` is given, the routing decision is recorded before
    execution, independent of whether execution succeeds.
    """
    decision = route_subtask(node)
    if trace is not None:
        trace.record(decision)

    if decision.method == "direct":
        classification = classify_description(node.description)
        op = classification.direct_operation
        if op == "find_accounts":
            return direct_find_accounts(customer_id)
        if op == "get_transactions":
            return direct_get_transactions((account_ids or [None])[0])
        if op == "check_sanctions":
            countries = [destination_country] if destination_country else direct_get_destination_countries(account_ids or [])
            if not countries:
                return {"checked": [], "sanctioned": [], "note": "No outbound wire history for this customer yet."}
            return {"checked": countries, "sanctioned": [c for c in countries if direct_check_sanctions(c)]}
        raise ValueError(f"Classified as direct but no direct_operation resolved for: {node.description!r}")

    if decision.method == "ps":
        return run_plan_and_solve(node.description, evidence_context, llm)

    if decision.method == "tot":
        return run_tree_of_thoughts(node.description, evidence_context, llm)

    if decision.method == "lats":
        if environment is None:
            raise ValueError(
                "This task classified as risk_assessment -> LATS, which requires a "
                "grounded `environment` (see planning/environment.py, owned by the "
                "Self-Correction + Grounding concern). Pass it in explicitly."
            )
        return run_lats(node.description, evidence_context, llm, environment)

    raise ValueError(f"Unknown route method: {decision.method!r}")