"""
Tests for the Planning-algorithms + routing concern.

*** REWRITTEN: async ***
router.dispatch() and algorithms.run_plan_and_solve/run_tree_of_thoughts/
run_lats are now `async def` (see router.py's module docstring for why:
teammate 3's real Environment.evaluate() is async, and the toolkit's own
lats() is sync with no await). Tests call them with asyncio.run() from
plain sync test functions — no pytest-asyncio dependency needed.

No real Groq calls: scripted fake LLMs throughout.
"""
import asyncio
from types import SimpleNamespace

import pytest

from planning.decomposition import TaskNode as DecompFirstTaskNode
from planning.dynamic_decomposition import TaskNode as DynamicTaskNode
from planning.router import classify_description, route_subtask, dispatch, dispatch_sync, _EnvironmentBridge
from planning.algorithms import run_plan_and_solve, run_tree_of_thoughts, run_lats
from planning_lab.models import EnvironmentFeedback
from planning_lab.algorithms.tree_of_thoughts import ThoughtCandidates, ThoughtEvaluation
from planning_lab.algorithms.lats import LATSActionBatch


def run(coro):
    """Shorthand for asyncio.run() in test bodies."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# [CLASSIFICATION / ROUTING] — pure sync logic, no I/O
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("description,expected_method", [
    ("Fetch customer accounts", "direct"),
    ("Retrieve transaction history for account 501", "direct"),
    ("Check wire transfer destinations against sanctions list", "direct"),
    ("Analyze wire transfers for hidden links", "ps"),
    ("Analyze deposit structuring patterns", "ps"),
    ("Investigate counterparty relationship for CP-118", "ps"),
    ("Consolidate evidence from all investigation sources", "tot"),
    ("Provide final AML risk assessment recommendation", "lats"),
])
def test_classify_description_matches_investigation_areas(description, expected_method):
    assert classify_description(description).method == expected_method


def test_unrecognized_description_defaults_to_ps_not_a_crash():
    result = classify_description("Do something entirely unrelated to banking")
    assert result.method == "ps"
    assert "defaulted" in result.reason.lower()


def test_route_subtask_works_with_either_teammate_1_tasknode_class():
    # decomposition.py's TaskNode and dynamic_decomposition.py's TaskNode
    # are two separate classes (both Pydantic, both extra="forbid") — the
    # router must not care which one it's given, only task_id/description.
    node_a = DecompFirstTaskNode(task_id="t1", description="Fetch customer accounts")
    node_b = DynamicTaskNode(task_id="dynamic_1", description="Fetch customer accounts")
    assert route_subtask(node_a).method == route_subtask(node_b).method == "direct"


# ---------------------------------------------------------------------------
# [ASYNC DISPATCH]
# ---------------------------------------------------------------------------
def test_dispatch_requires_an_environment_for_lats_and_says_why():
    node = DynamicTaskNode(task_id="dynamic_3", description="Provide final risk assessment recommendation")
    with pytest.raises(ValueError, match="planning/environment.py"):
        run(dispatch(node, "evidence...", llm=None, environment=None))


class RecordingLLM:
    def __init__(self, content: str):
        self.content = content
        self.prompts: list[str] = []

    def invoke(self, messages, **kwargs):
        self.prompts.append(messages[-1][1])
        return SimpleNamespace(content=self.content)


def test_plan_and_solve_runs_on_real_transaction_evidence():
    llm = RecordingLLM("PLAN: inspect near-threshold deposits.\nSOLUTION: 4 deposits of 4,600-4,900 in 10 days match structuring.")
    evidence = "Type: deposit, Amount: 4800, Source: cash, Time: 2026-07-01"
    result = run(run_plan_and_solve("Analyze deposit structuring patterns for account 501", evidence, llm))
    assert "structuring" in result.lower()
    assert "4800" in llm.prompts[0]


def test_dispatch_routes_ps_classified_task_through_plan_and_solve():
    llm = RecordingLLM("PLAN: review wires.\nSOLUTION: single low-value domestic wire, no red flags.")
    node = DynamicTaskNode(task_id="dynamic_2", description="Analyze wire transfers for hidden links")
    result = run(dispatch(node, "1 wire, $200, domestic", llm))
    assert "no red flags" in result.lower()


def test_dispatch_sync_bridges_the_coroutine_for_sync_callers():
    """This is exactly what orchestrator.py's execute_task closures do —
    calling the async dispatch() from a plain sync function."""
    llm = RecordingLLM("PLAN: review wires.\nSOLUTION: single low-value domestic wire, no red flags.")
    node = DecompFirstTaskNode(task_id="t2", description="Analyze wire transfers for hidden links")
    result = dispatch_sync(node, "1 wire, $200, domestic", llm)
    assert "no red flags" in result.lower()


# ---------------------------------------------------------------------------
# [ToT]
# ---------------------------------------------------------------------------
class ToTLLM:
    class Structured:
        def __init__(self, owner, schema):
            self.owner, self.schema = owner, schema

        def invoke(self, messages, **kwargs):
            return self.owner.structured(self.schema, messages[-1][1])

    def with_structured_output(self, schema, *, method):
        return self.Structured(self, schema)

    def structured(self, schema, prompt_text: str):
        if schema is ThoughtCandidates:
            return schema(candidates=["Benign high-volume merchant activity", "Structuring to evade CTR reporting"])
        if schema is ThoughtEvaluation:
            candidate_line = prompt_text.lower().rsplit("candidate path:", 1)[-1]
            if "structuring" in candidate_line:
                return schema(score=0.85, rationale="Repeated near-$5,000 deposits match known structuring pattern.")
            return schema(score=0.35, rationale="No independent evidence supports a benign explanation here.")
        return schema(score=0.5)


def test_dispatch_routes_evidence_consolidation_through_tree_of_thoughts():
    node = DynamicTaskNode(task_id="dynamic_4", description="Consolidate evidence from all investigation sources")
    result = run(dispatch(node, "3 deposits of 4,700-4,900 in 6 days", ToTLLM()))
    assert isinstance(result, list) and result
    assert "structuring" in result[0].state.lower()


# ---------------------------------------------------------------------------
# [LATS + ENVIRONMENT BRIDGE] — the core of this update
# ---------------------------------------------------------------------------
class SyncFakeEnvironment:
    """Old-style sync environment — proves the bridge still supports the
    calling convention used before grounding existed."""
    def __init__(self, feedback: list[EnvironmentFeedback]):
        self._feedback = iter(feedback)

    def evaluate(self, state: str) -> EnvironmentFeedback:
        return next(self._feedback)


class RealisticAsyncEnvironment:
    """Mirrors teammate 3's actual planning/environment.py signature:
    async def evaluate(self, candidate, task=None, execute_task=None)."""
    def __init__(self):
        self.calls: list[tuple[str, str | None]] = []

    async def evaluate(self, candidate: str, task=None, execute_task=None) -> EnvironmentFeedback:
        await asyncio.sleep(0)  # forces a real event-loop hop, not just a plain call
        self.calls.append((candidate, task))
        success = "sanctions" in candidate.lower()
        return EnvironmentFeedback(success=success, score=0.95 if success else 0.2, details=["real async evaluate ran"])


class LATSLLM:
    class Structured:
        def __init__(self, owner, schema):
            self.owner, self.schema = owner, schema

        def invoke(self, messages, **kwargs):
            return self.owner.structured(self.schema)

    def with_structured_output(self, schema, *, method):
        return self.Structured(self, schema)

    def structured(self, schema):
        if schema is LATSActionBatch:
            return schema(actions=[
                {"action": "weak", "state": "Recommendation: insufficient detail."},
                {"action": "strong", "state": "Recommendation: customer's wire is a sanctions hit; escalate."},
            ])
        return schema(score=0.7)

    def invoke(self, messages, **kwargs):
        return SimpleNamespace(content="First branch lacked a definite position; commit to one next.")


def test_environment_bridge_handles_sync_environment_unchanged():
    bridge = _EnvironmentBridge(SyncFakeEnvironment([EnvironmentFeedback(success=True, score=0.9, details=["ok"])]))
    feedback = bridge.evaluate("some candidate")
    assert feedback.success is True


def test_environment_bridge_awaits_a_genuinely_async_environment():
    async_env = RealisticAsyncEnvironment()
    bridge = _EnvironmentBridge(async_env, task_description="Provide final risk assessment recommendation")
    feedback = bridge.evaluate("Recommendation: sanctions hit found; escalate.")
    assert feedback.success is True
    assert async_env.calls == [("Recommendation: sanctions hit found; escalate.", "Provide final risk assessment recommendation")]


def test_dispatch_routes_risk_assessment_through_lats_with_sync_environment():
    environment = SyncFakeEnvironment([
        EnvironmentFeedback(success=False, score=0.3, details=["stub: insufficient detail"]),
        EnvironmentFeedback(success=True, score=0.95, details=["stub: accepted"]),
    ])
    node = DynamicTaskNode(task_id="dynamic_5", description="Provide final risk assessment recommendation")
    result = run(dispatch(node, "Wire to a sanctioned country; no other flags investigated yet.", LATSLLM(), environment=environment))
    assert result.success is True
    assert "sanctions" in result.output.lower()


def test_dispatch_routes_risk_assessment_through_lats_with_real_async_environment():
    """The actual scenario this update exists for: a genuinely async
    Environment (teammate 3's real signature) plugged straight into
    dispatch() without either side needing to know about the other."""
    environment = RealisticAsyncEnvironment()
    node = DynamicTaskNode(task_id="dynamic_5", description="Provide final risk assessment recommendation")
    result = run(dispatch(node, "Wire to a sanctioned country.", LATSLLM(), environment=environment))
    assert result.success is True
    assert "sanctions" in result.output.lower()
    assert environment.calls  # proves the real async evaluate() actually ran