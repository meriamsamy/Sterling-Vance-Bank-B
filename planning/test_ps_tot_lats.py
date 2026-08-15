"""
Tests for the Planning-algorithms + routing concern, rewritten against
teammate 1's latest decomposition.py (BankDynamicDecomposition — a fully
dynamic, LLM-driven planner; no more fixed decomposition-first task_ids).
No real Groq calls: scripted fake LLMs throughout.
"""
from types import SimpleNamespace

import pytest

from planning.decomposition import DynamicDecision, TaskNode
from planning.router import classify_description, route_subtask, dispatch
from planning.algorithms import run_plan_and_solve, run_tree_of_thoughts, run_lats
from planning.orchestrator import run_investigation
from planning_lab.models import EnvironmentFeedback
from planning_lab.algorithms.tree_of_thoughts import ThoughtCandidates, ThoughtEvaluation
from planning_lab.algorithms.lats import LATSActionBatch


# ---------------------------------------------------------------------------
# [CLASSIFICATION / ROUTING] — now description-based, not task_id-based
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


def test_route_subtask_takes_the_shared_tasknode_schema():
    node = TaskNode(task_id="dynamic_1", description="Fetch customer accounts")
    decision = route_subtask(node)
    assert decision.task_id == "dynamic_1"
    assert decision.method == "direct"


def test_dispatch_requires_an_environment_for_lats_and_says_why():
    node = TaskNode(task_id="dynamic_3", description="Provide final risk assessment recommendation")
    with pytest.raises(ValueError, match="planning/environment.py"):
        dispatch(node, "evidence...", llm=None, environment=None)


# ---------------------------------------------------------------------------
# [PS]
# ---------------------------------------------------------------------------
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
    result = run_plan_and_solve("Analyze deposit structuring patterns for account 501", evidence, llm)
    assert "structuring" in result.lower()
    assert "4800" in llm.prompts[0]


def test_dispatch_routes_ps_classified_task_through_plan_and_solve():
    llm = RecordingLLM("PLAN: review wires.\nSOLUTION: single low-value domestic wire, no red flags.")
    node = TaskNode(task_id="dynamic_2", description="Analyze wire transfers for hidden links")
    result = dispatch(node, "1 wire, $200, domestic", llm)
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
    node = TaskNode(task_id="dynamic_4", description="Consolidate evidence from all investigation sources")
    result = dispatch(node, "3 deposits of 4,700-4,900 in 6 days", ToTLLM())
    assert isinstance(result, list) and result
    assert "structuring" in result[0].state.lower()


# ---------------------------------------------------------------------------
# [LATS]
# ---------------------------------------------------------------------------
class MinimalFakeEnvironment:
    def __init__(self, feedback: list[EnvironmentFeedback]):
        self._feedback = iter(feedback)

    def evaluate(self, state: str) -> EnvironmentFeedback:
        return next(self._feedback)


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


def test_dispatch_routes_risk_assessment_through_lats_when_environment_given():
    environment = MinimalFakeEnvironment([
        EnvironmentFeedback(success=False, score=0.3, details=["stub: insufficient detail"]),
        EnvironmentFeedback(success=True, score=0.95, details=["stub: accepted"]),
    ])
    node = TaskNode(task_id="dynamic_5", description="Provide final risk assessment recommendation")
    result = dispatch(node, "Wire to a sanctioned country; no other flags investigated yet.", LATSLLM(), environment=environment)
    assert result.success is True
    assert "sanctions" in result.output.lower()


# ---------------------------------------------------------------------------
# [ORCHESTRATOR] — end to end against the real bank.db, through
# BankDynamicDecomposition.run()
# ---------------------------------------------------------------------------
class ScriptedDynamicLLM:
    """Drives a full 3-step investigation: accounts -> sanctions check ->
    risk assessment, then done=True. Mirrors real DynamicDecision usage."""

    def __init__(self):
        self.decisions = iter([
            DynamicDecision(done=False, next_task="Fetch customer accounts"),
            DynamicDecision(done=False, next_task="Check wire transfer destinations against sanctions list"),
            DynamicDecision(done=False, next_task="Provide final risk assessment recommendation"),
            DynamicDecision(done=True, next_task=""),
        ])

    class Structured:
        def __init__(self, owner, schema):
            self.owner, self.schema = owner, schema

        def invoke(self, messages, **kwargs):
            return self.owner.structured(self.schema, messages[-1][1])

    def with_structured_output(self, schema, *, method):
        return self.Structured(self, schema)

    def structured(self, schema, prompt_text):
        if schema is DynamicDecision:
            return next(self.decisions)
        if schema.__name__ == "LATSActionBatch":
            return schema(actions=[{"action": "commit", "state": "Recommendation: no structuring or sanctions hits found; clear."}])
        return schema(score=0.8)

    def invoke(self, messages, **kwargs):
        return SimpleNamespace(content="PLAN: reviewed.\nSOLUTION: no notable findings.")


class AlwaysAcceptEnvironment:
    def evaluate(self, state: str) -> EnvironmentFeedback:
        return EnvironmentFeedback(success=True, score=0.9, details=["stub: accepted"])


def test_orchestrator_drives_a_full_dynamic_investigation_end_to_end():
    run = run_investigation(customer_id=1, llm=ScriptedDynamicLLM(), environment=AlwaysAcceptEnvironment(), save_artifact=False)
    assert run.order_executed == ["dynamic_1", "dynamic_2", "dynamic_3"]
    methods = [step.task.action_type for step in run.steps]
    assert methods == ["direct", "direct", "lats"]


def test_orchestrator_uses_real_account_ids_before_sanctions_check():
    run = run_investigation(customer_id=1, llm=ScriptedDynamicLLM(), environment=AlwaysAcceptEnvironment(), save_artifact=False)
    accounts_step, sanctions_step, _ = run.steps
    assert "account_id" in accounts_step.observation or "account_id" in str(accounts_step.observation)
    assert "checked" in str(sanctions_step.observation)  # ran against real wire_transfers, not a placeholder


def test_orchestrator_asks_planner_to_fetch_accounts_first_when_missing():
    class SkipsAccountsLLM(ScriptedDynamicLLM):
        def __init__(self):
            self.decisions = iter([
                DynamicDecision(done=False, next_task="Retrieve transaction history for account 501"),
                DynamicDecision(done=True, next_task=""),
            ])

    run = run_investigation(customer_id=1, llm=SkipsAccountsLLM(), environment=AlwaysAcceptEnvironment(), save_artifact=False)
    assert "fetch customer accounts first" in str(run.steps[0].observation).lower()


def test_routing_decisions_are_recorded_in_the_trace():
    run = run_investigation(customer_id=1, llm=ScriptedDynamicLLM(), environment=AlwaysAcceptEnvironment(), save_artifact=False)
    recorded_ids = [entry["task_id"] for entry in run.trace.as_payload()]
    assert recorded_ids == run.order_executed
    for entry in run.trace.as_payload():
        assert entry["method"] in {"direct", "ps", "tot", "lats"}
        assert entry["reason"]
        assert entry["timestamp"] > 0


def test_run_artifact_is_written_with_routing_trace(tmp_path, monkeypatch):
    import json
    import planning.orchestrator as orchestrator_module
    monkeypatch.setattr(orchestrator_module, "ARTIFACTS_DIR", tmp_path)

    run_investigation(customer_id=1, llm=ScriptedDynamicLLM(), environment=AlwaysAcceptEnvironment(), save_artifact=True)

    written = list(tmp_path.glob("run-*.json"))
    assert len(written) == 1
    payload = json.loads(written[0].read_text())
    assert payload["mode"] == "dynamic"
    assert payload["customer_id"] == 1
    assert len(payload["routing_trace"]) == 3
    assert payload["routing_trace"][0]["task_id"] == "dynamic_1"


def test_deterministic_tasks_are_backed_by_the_real_registered_mcp_tools():
    """direct routes must call the exact db_access functions that back
    mcp/server.py's get_customer_accounts / check_sanctions tools."""
    import sys
    from pathlib import Path
    mcp_dir = Path(__file__).resolve().parent.parent / "mcp"
    if str(mcp_dir) not in sys.path:
        sys.path.insert(0, str(mcp_dir))
    import server as mcp_server
    import db_access as db

    tool_names = {tool.name for tool in mcp_server.BASE_TOOLS + mcp_server.COMPLIANCE_TOOLS}
    assert {"get_customer_accounts", "get_transaction_history", "check_sanctions"} <= tool_names

    from planning.router import direct_find_accounts
    assert direct_find_accounts(1) == db.get_customer_accounts(1)