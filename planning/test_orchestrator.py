"""
Integration tests for orchestrator.py — both entry points, end to end
against the real bank.db. No real Groq calls: scripted fake LLMs.
"""
import json

from planning.dynamic_decomposition import DynamicDecision
from planning.orchestrator import run_investigation_decomposition_first, run_investigation_dynamic
from planning_lab.models import EnvironmentFeedback
from types import SimpleNamespace


class AlwaysAcceptEnvironment:
    def evaluate(self, state: str) -> EnvironmentFeedback:
        return EnvironmentFeedback(success=True, score=0.9, details=["stub: accepted"])


# ---------------------------------------------------------------------------
# Decomposition-first (planning/decomposition.py -> decompose_goal)
# ---------------------------------------------------------------------------
class ScriptedPlanLLM:
    def __init__(self, tasks):
        self._tasks = tasks

    class Structured:
        def __init__(self, owner, schema):
            self.owner, self.schema = owner, schema

        def invoke(self, messages, **kwargs):
            return self.owner.structured(self.schema, messages[-1][1])

    def with_structured_output(self, schema, *, method):
        return self.Structured(self, schema)

    def structured(self, schema, prompt_text):
        name = schema.__name__
        if name == "GeneratedPlan":
            return schema(goal="placeholder", tasks=self._tasks)
        if name == "LATSActionBatch":
            return schema(actions=[{"action": "commit", "state": "Recommendation: no structuring or sanctions hits found; clear."}])
        if name == "ThoughtCandidates":
            return schema(candidates=["Benign activity", "Structuring pattern"])
        if name == "ThoughtEvaluation":
            return schema(score=0.8, rationale="stub")
        return schema(score=0.8)

    def invoke(self, messages, **kwargs):
        return SimpleNamespace(content="PLAN: reviewed.\nSOLUTION: no notable findings.")


def _three_task_plan():
    return [
        {"id": "t1", "instruction": "Fetch customer accounts", "depends_on": []},
        {"id": "t2", "instruction": "Check wire transfer destinations against sanctions list", "depends_on": ["t1"]},
        {"id": "t3", "instruction": "Provide final risk assessment recommendation", "depends_on": ["t2"]},
    ]


def test_decomposition_first_executes_the_full_plan_in_dependency_order():
    run = run_investigation_decomposition_first(
        customer_id=1, llm=ScriptedPlanLLM(_three_task_plan()),
        environment=AlwaysAcceptEnvironment(), save_artifact=False,
    )
    assert run.mode == "decomposition-first"
    assert run.order_executed == ["t1", "t2", "t3"]
    assert run.detail["tasks"]["t1"]["action_type"] == "direct"
    assert run.detail["tasks"]["t2"]["action_type"] == "direct"
    assert run.detail["tasks"]["t3"]["action_type"] == "lats"


def test_decomposition_first_uses_real_account_ids_before_sanctions_check():
    run = run_investigation_decomposition_first(
        customer_id=1, llm=ScriptedPlanLLM(_three_task_plan()),
        environment=AlwaysAcceptEnvironment(), save_artifact=False,
    )
    assert "account_id" in run.detail["outputs"]["t1"]
    assert "checked" in run.detail["outputs"]["t2"]  # ran against real wire_transfers


def test_decomposition_first_runs_independent_branches_as_parallel_batches():
    parallel_plan = [
        {"id": "t1", "instruction": "Fetch customer accounts", "depends_on": []},
        {"id": "t2a", "instruction": "Analyze wire transfers for hidden links", "depends_on": ["t1"]},
        {"id": "t2b", "instruction": "Analyze deposit structuring patterns", "depends_on": ["t1"]},
        {"id": "t3", "instruction": "Consolidate evidence from all investigation sources", "depends_on": ["t2a", "t2b"]},
    ]
    run = run_investigation_decomposition_first(
        customer_id=1, llm=ScriptedPlanLLM(parallel_plan),
        environment=AlwaysAcceptEnvironment(), save_artifact=False,
    )
    batches = run.detail["execution_batches"]
    assert batches[0] == ["t1"]
    assert set(batches[1]) == {"t2a", "t2b"}  # same generation -> genuinely parallel
    assert batches[2] == ["t3"]


# ---------------------------------------------------------------------------
# Dynamic / interleaved (planning/dynamic_decomposition.py)
# ---------------------------------------------------------------------------
class ScriptedDynamicLLM:
    def __init__(self, decisions):
        self.decisions = iter(decisions)

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


def _standard_three_step_script():
    return [
        DynamicDecision(done=False, next_task="Fetch customer accounts"),
        DynamicDecision(done=False, next_task="Check wire transfer destinations against sanctions list"),
        DynamicDecision(done=False, next_task="Provide final risk assessment recommendation"),
        DynamicDecision(done=True, next_task=""),
    ]


def test_dynamic_investigation_runs_end_to_end():
    run = run_investigation_dynamic(
        customer_id=1, llm=ScriptedDynamicLLM(_standard_three_step_script()),
        environment=AlwaysAcceptEnvironment(), save_artifact=False,
    )
    assert run.mode == "dynamic"
    assert run.order_executed == ["dynamic_1", "dynamic_2", "dynamic_3"]
    methods = [step["action_type"] for step in run.detail["steps"]]
    assert methods == ["direct", "direct", "lats"]


def test_dynamic_investigation_asks_for_accounts_first_when_skipped():
    script = [
        DynamicDecision(done=False, next_task="Retrieve transaction history for account 501"),
        DynamicDecision(done=True, next_task=""),
    ]
    run = run_investigation_dynamic(
        customer_id=1, llm=ScriptedDynamicLLM(script),
        environment=AlwaysAcceptEnvironment(), save_artifact=False,
    )
    assert "fetch customer accounts first" in run.detail["steps"][0]["observation"].lower()


def test_dynamic_investigation_works_with_a_real_async_environment():
    class RealisticAsyncEnvironment:
        def __init__(self):
            self.calls = []

        async def evaluate(self, candidate, task=None, execute_task=None):
            import asyncio
            await asyncio.sleep(0)
            self.calls.append(candidate)
            return EnvironmentFeedback(success=True, score=0.9, details=["real async"])

    env = RealisticAsyncEnvironment()
    run = run_investigation_dynamic(
        customer_id=1, llm=ScriptedDynamicLLM(_standard_three_step_script()),
        environment=env, save_artifact=False,
    )
    assert run.order_executed == ["dynamic_1", "dynamic_2", "dynamic_3"]
    assert env.calls  # the real async evaluate() genuinely ran


# ---------------------------------------------------------------------------
# Shared: routing trace + artifact persistence (Issue #68 acceptance criteria)
# ---------------------------------------------------------------------------
def test_routing_decisions_are_recorded_in_the_trace_for_both_modes():
    dynamic_run = run_investigation_dynamic(
        customer_id=1, llm=ScriptedDynamicLLM(_standard_three_step_script()),
        environment=AlwaysAcceptEnvironment(), save_artifact=False,
    )
    decomp_run = run_investigation_decomposition_first(
        customer_id=1, llm=ScriptedPlanLLM(_three_task_plan()),
        environment=AlwaysAcceptEnvironment(), save_artifact=False,
    )
    for run in (dynamic_run, decomp_run):
        recorded_ids = [entry["task_id"] for entry in run.trace.as_payload()]
        assert recorded_ids == run.order_executed
        for entry in run.trace.as_payload():
            assert entry["method"] in {"direct", "ps", "tot", "lats"}
            assert entry["reason"]
            assert entry["timestamp"] > 0


def test_run_artifact_is_written_with_routing_trace(tmp_path, monkeypatch):
    import planning.orchestrator as orchestrator_module
    monkeypatch.setattr(orchestrator_module, "ARTIFACTS_DIR", tmp_path)

    run_investigation_dynamic(
        customer_id=1, llm=ScriptedDynamicLLM(_standard_three_step_script()),
        environment=AlwaysAcceptEnvironment(), save_artifact=True,
    )

    written = list(tmp_path.glob("run-*.json"))
    assert len(written) == 1
    payload = json.loads(written[0].read_text())
    assert payload["mode"] == "dynamic"
    assert payload["customer_id"] == 1
    assert len(payload["routing_trace"]) == 3


def test_deterministic_tasks_are_backed_by_the_real_registered_mcp_tools():
    from mcp_server import server as mcp_server
    from mcp_server import db_access as db

    tool_names = {tool.name for tool in mcp_server.BASE_TOOLS + mcp_server.COMPLIANCE_TOOLS}
    assert {"get_customer_accounts", "get_transaction_history", "check_sanctions"} <= tool_names

    from planning.router import direct_find_accounts
    assert direct_find_accounts(1) == db.get_customer_accounts(1)