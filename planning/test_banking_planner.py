import pytest
from planning.decomposition import InvestigationDAG, TaskDecomposerAdapter, TaskNode

def test_decomposition_and_dynamic_cycle_protection():
    dag = InvestigationDAG()
    decomposer = TaskDecomposerAdapter(dag)

    # 1. Decomposition First
    decomposer.decompose_goal("CUST_7700")
    assert "find_accounts" in dag.nodes
    assert len(dag.nodes) == 7

    # 2. Dynamic Decomposition Test
    wire_task = dag.nodes["analyze_wires"]
    decomposer.apply_dynamic_decomposition(wire_task, {"unlinked_counterparty": "ACC_UNKNOWN_99"})
    
    dynamic_task_id = "investigate_counterparty_ACC_UNKNOWN_99"
    assert dynamic_task_id in dag.nodes
    assert dynamic_task_id in dag.nodes["combine_evidence"].dependencies

    # 3. Dynamic Edge Cycle Check Test (إنشاء لفة جافة محظورة)
    with pytest.raises(ValueError, match="Cycle Detected"):
        # محاولة جعل combine_evidence تعتمد على نفسها عبر حلقة عكسية
        dag.add_dependency_edge("combine_evidence", "analyze_wires")

if __name__ == "__main__":
    test_decomposition_and_dynamic_cycle_protection()
    print("✅ All Tests Passed Successfully!")