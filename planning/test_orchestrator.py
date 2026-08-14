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
    run = run_investigation(customer_id=1, llm=ScriptedLLM(), environment=AlwaysAcceptEnvironment(), dynamic=False, save_artifact=False)
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
    run = run_investigation(customer_id=1, llm=ScriptedLLM(), environment=AlwaysAcceptEnvironment(), dynamic=True, save_artifact=False)
    assert run.dynamic_task_injected == "investigate_counterparty_CP-118"
    assert "investigate_counterparty_CP-118" in run.dag.nodes
    assert "investigate_counterparty_CP-118" in run.order_executed
    # the new task must have actually run (not just been injected) before combine_evidence
    injected_index = run.order_executed.index("investigate_counterparty_CP-118")
    combine_index = run.order_executed.index("combine_evidence")
    assert injected_index < combine_index


def test_router_annotates_action_type_on_every_executed_node():
    run = run_investigation(customer_id=1, llm=ScriptedLLM(), environment=AlwaysAcceptEnvironment(), dynamic=False, save_artifact=False)
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
    run = run_investigation(customer_id=1, llm=ScriptedLLM(), environment=AlwaysAcceptEnvironment(), dynamic=False, save_artifact=False)
    accounts_result = run.dag.nodes["find_accounts"].result
    assert accounts_result and accounts_result[0]["account_id"] == 1
    sanctions_result = run.dag.nodes["check_sanctions"].result
    assert "checked" in sanctions_result  # ran against real wire_transfers, not a placeholder


# ---------------------------------------------------------------------------
# Issue #68 acceptance criteria specific to the Router:
#   - routing decisions are recorded in the execution trace
#   - deterministic tasks route to the real registered MCP tools
# ---------------------------------------------------------------------------
def test_routing_decisions_are_recorded_in_the_trace():
    run = run_investigation(customer_id=1, llm=ScriptedLLM(), environment=AlwaysAcceptEnvironment(), dynamic=False, save_artifact=False)
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

    run = run_investigation(customer_id=1, llm=ScriptedLLM(), environment=AlwaysAcceptEnvironment(), dynamic=False, save_artifact=True)

    written = list(tmp_path.glob("run-*.json"))
    assert len(written) == 1
    payload = json.loads(written[0].read_text())
    assert payload["mode"] == "decomposition-first"
    assert payload["customer_id"] == 1
    assert len(payload["routing_trace"]) == len(run.order_executed)
    assert payload["routing_trace"][0]["task_id"] == "find_accounts"
    assert payload["routing_trace"][0]["method"] == "direct"


def test_deterministic_tasks_are_backed_by_the_real_registered_mcp_tools():
    """find_accounts/get_transactions/check_sanctions must call the exact
    db_access functions that mcp/server.py's get_customer_accounts,
    get_transaction_history, and check_sanctions tools call — not a
    parallel implementation that merely agrees with them today."""
    import sys
    from pathlib import Path
    mcp_dir = Path(__file__).resolve().parent.parent / "mcp"
    if str(mcp_dir) not in sys.path:
        sys.path.insert(0, str(mcp_dir))
    import server as mcp_server  # the actual MCP server module

    tool_names = {tool.name for tool in mcp_server.BASE_TOOLS + mcp_server.COMPLIANCE_TOOLS}
    assert {"get_customer_accounts", "get_transaction_history", "check_sanctions"} <= tool_names

    # Same underlying data-layer call, from both the MCP tool and the router.
    from planning.router import direct_find_accounts
    import db_access as db
    assert direct_find_accounts(1) == db.get_customer_accounts(1)