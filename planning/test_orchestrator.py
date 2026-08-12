"""
Integration tests for orchestrator.py — proves the DAG-to-router wiring
actually works end to end against the real bank.db, not just each piece
in isolation. Still no real Groq calls: a single scripted fake LLM stands
in for every PS/ToT/LATS call, since only the wiring is under test here.
"""
from types import SimpleNamespace

from planning.orchestrator import run_investigation
from planning_lab.models import EnvironmentFeedback


class ScriptedLLM:
    """One fake that answers every algorithm's call shape (plain .invoke
    for PS, .with_structured_output for ToT/LATS) so a full DAG run can
    execute without hitting a real provider. analyze_wires is scripted to
    report an unlinked counterparty so the dynamic-decomposition hook has
    something real to react to."""

    class Structured:
        def __init__(self, owner, schema):
            self.owner, self.schema = owner, schema

        def invoke(self, messages, **kwargs):
            return self.owner.structured(self.schema, messages[-1][1])

    def with_structured_output(self, schema, *, method):
        return self.Structured(self, schema)

    def structured(self, schema, prompt_text: str):
        name = schema.__name__
        if name == "ThoughtCandidates":
            return schema(candidates=["Benign activity", "Structuring pattern"])
        if name == "ThoughtEvaluation":
            return schema(score=0.8, rationale="stub")
        if name == "LATSActionBatch":
            return schema(actions=[
                {"action": "commit", "state": "Recommendation: no structuring or sanctions hits found; clear."},
            ])
        if name == "ValueEstimate":
            return schema(score=0.8)
        return schema(score=0.5)

    def invoke(self, messages, **kwargs):
        prompt = messages[-1][1]
        if "wire transfers for hidden links" in prompt.lower() or "analyze wire transfers" in prompt.lower():
            return SimpleNamespace(
                content="PLAN: review wires.\nSOLUTION: found an unlinked counterparty CP-118 not on file; escalate."
            )
        return SimpleNamespace(content="PLAN: reviewed.\nSOLUTION: no notable findings.")


class AlwaysAcceptEnvironment:
    def evaluate(self, state: str) -> EnvironmentFeedback:
        return EnvironmentFeedback(success=True, score=0.9, details=["stub: accepted"])


def test_decomposition_first_run_executes_all_seven_tasks_in_dependency_order():
    run = run_investigation(customer_id=1, llm=ScriptedLLM(), environment=AlwaysAcceptEnvironment(), dynamic=False)
    assert run.order_executed[0] == "find_accounts"
    assert run.order_executed[-1] == "risk_assessment"
    assert set(run.order_executed) == {
        "find_accounts", "get_transactions", "analyze_wires",
        "check_sanctions", "analyze_structuring", "combine_evidence", "risk_assessment",
    }
    # decomposition-first never looks at analyze_wires' actual output to replan,
    # even though this run's script reports a real unlinked counterparty.
    assert run.dynamic_task_injected is None
    assert "investigate_counterparty_CP-118" not in run.dag.nodes


def test_dynamic_run_injects_counterparty_task_after_observing_analyze_wires():
    run = run_investigation(customer_id=1, llm=ScriptedLLM(), environment=AlwaysAcceptEnvironment(), dynamic=True)
    assert run.dynamic_task_injected == "investigate_counterparty_CP-118"
    assert "investigate_counterparty_CP-118" in run.dag.nodes
    assert "investigate_counterparty_CP-118" in run.order_executed
    # the new task must have actually run (not just been injected) before combine_evidence
    injected_index = run.order_executed.index("investigate_counterparty_CP-118")
    combine_index = run.order_executed.index("combine_evidence")
    assert injected_index < combine_index


def test_router_annotates_action_type_on_every_executed_node():
    run = run_investigation(customer_id=1, llm=ScriptedLLM(), environment=AlwaysAcceptEnvironment(), dynamic=False)
    expected = {
        "find_accounts": "direct", "get_transactions": "direct", "check_sanctions": "direct",
        "analyze_wires": "ps", "analyze_structuring": "ps",
        "combine_evidence": "tot", "risk_assessment": "lats",
    }
    for task_id, method in expected.items():
        assert run.dag.nodes[task_id].action_type == method
        assert run.dag.nodes[task_id].status == "COMPLETED"
        assert run.dag.nodes[task_id].result is not None


def test_check_sanctions_uses_real_account_ids_from_find_accounts():
    run = run_investigation(customer_id=1, llm=ScriptedLLM(), environment=AlwaysAcceptEnvironment(), dynamic=False)
    accounts_result = run.dag.nodes["find_accounts"].result
    assert accounts_result and accounts_result[0]["account_id"] == 1
    sanctions_result = run.dag.nodes["check_sanctions"].result
    assert "checked" in sanctions_result  # ran against real wire_transfers, not a placeholder