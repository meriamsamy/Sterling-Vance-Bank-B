import networkx as nx
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

# 1️⃣ Task Data Model
class TaskNode(BaseModel):
    task_id: str
    description: str
    action_type: str = "PENDING_ROUTING"  # لتستلمه "البنت 2" في الـ Router
    dependencies: List[str] = Field(default_factory=list)
    status: str = "PENDING"               # PENDING, IN_PROGRESS, COMPLETED, FAILED
    result: Optional[Any] = None


# 2️⃣ Investigation DAG Engine with Robust Cycle Check
class InvestigationDAG:
    def __init__(self):
        self.graph = nx.DiGraph()
        self.nodes: Dict[str, TaskNode] = {}

    def add_task(self, node: TaskNode) -> bool:
        """إضافة عقدة جديدة مع فحص الـ Cycle Check"""
        self.graph.add_node(node.task_id)
        for dep in node.dependencies:
            self.graph.add_edge(dep, node.task_id)

        # ⚠️ CYCLE CHECK
        if not nx.is_directed_acyclic_graph(self.graph):
            self.graph.remove_node(node.task_id)
            raise ValueError(f"❌ [Cycle Detected]: Adding task '{node.task_id}' creates a loop!")

        self.nodes[node.task_id] = node
        return True

    def add_dependency_edge(self, u: str, v: str):
        """إضافة سهم بين عقدتين موجودتين مع حماية من الـ Cycle Check"""
        self.graph.add_edge(u, v)
        if not nx.is_directed_acyclic_graph(self.graph):
            self.graph.remove_edge(u, v)
            raise ValueError(f"❌ [Cycle Detected]: Adding edge '{u} -> {v}' creates a loop!")

    def get_executable_tasks(self) -> List[TaskNode]:
        """استخراج المهام الجاهزة للتنفيذ"""
        executable = []
        for task_id, node in self.nodes.items():
            if node.status == "PENDING":
                deps_satisfied = all(
                    self.nodes[dep].status == "COMPLETED"
                    for dep in node.dependencies if dep in self.nodes
                )
                if deps_satisfied:
                    executable.append(node)
        return executable

    def mark_completed(self, task_id: str, result: Any):
        if task_id in self.nodes:
            self.nodes[task_id].status = "COMPLETED"
            self.nodes[task_id].result = result


# 3️⃣ Decomposer Adapter (Wrapping & Extending Toolkit Functionality)
class TaskDecomposerAdapter:
    """
    Adapter Class: بيربط الـ Goal Decomposition والـ Dynamic Adaptation
    بشكل آمن ومحمي بالـ Cycle Check.
    """
    def __init__(self, dag: InvestigationDAG):
        self.dag = dag

    def decompose_goal(self, customer_id: str) -> InvestigationDAG:
        """1️⃣ Decomposition-First: بناء الهيكل المبدئية للـ DAG"""
        initial_tasks = [
            TaskNode(task_id="find_accounts", description=f"Fetch linked accounts for customer {customer_id}"),
            TaskNode(task_id="get_transactions", description="Fetch transaction history", dependencies=["find_accounts"]),
            TaskNode(task_id="analyze_wires", description="Analyze wire transfers for hidden links", dependencies=["find_accounts"]),
            TaskNode(task_id="check_sanctions", description="Check sanctions database", dependencies=["find_accounts"]),
            TaskNode(task_id="analyze_structuring", description="Analyze deposit structuring patterns", dependencies=["get_transactions"]),
            TaskNode(task_id="combine_evidence", description="Consolidate evidence from all sources", dependencies=["analyze_structuring", "analyze_wires", "check_sanctions"]),
            TaskNode(task_id="risk_assessment", description="Provide AML risk assessment", dependencies=["combine_evidence"])
        ]

        for task in initial_tasks:
            self.dag.add_task(task)

        return self.dag

    def apply_dynamic_decomposition(self, completed_task: TaskNode, output: Dict[str, Any]):
        """2️⃣ Dynamic Adaptation مع التثبت الآمن للـ Dynamic Edges"""
        # عند اكتشاف طرف ثالث غير معروف أثناء تحليل الـ Wires
        if completed_task.task_id == "analyze_wires" and output.get("unlinked_counterparty"):
            counterparty_id = output.get("unlinked_counterparty")
            new_task_id = f"investigate_counterparty_{counterparty_id}"

            if new_task_id not in self.dag.nodes:
                print(f"⚡ [Dynamic Adaptation]: Discovered counterparty '{counterparty_id}'. Injecting task...")

                dynamic_node = TaskNode(
                    task_id=new_task_id,
                    description=f"Investigate counterparty {counterparty_id}",
                    dependencies=["analyze_wires"]
                )

                # إضافة العقدة مع Cycle Check
                self.dag.add_task(dynamic_node)

                # ربط العقدة الجديدة بـ combine_evidence مع Cycle Check آمن للأداة!
                if "combine_evidence" in self.dag.nodes:
                    self.dag.nodes["combine_evidence"].dependencies.append(new_task_id)
                    # استخدام الميثود الآمنة لفحص الـ Edge
                    self.dag.add_dependency_edge(new_task_id, "combine_evidence")