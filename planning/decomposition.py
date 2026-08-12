from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

import networkx as nx
from pydantic import BaseModel, ConfigDict, Field

from planning_lab.algorithms.decomposition import decompose_goal
from planning_lab.models import Plan


# ============================================================
# 1. Bank-specific task representation
# ============================================================


class TaskNode(BaseModel):
    """
    Bank-specific representation of a planning task.

    The task itself does not know how to call MCP/database tools.
    The bank integration/router decides how the task is executed.
    """

    model_config = ConfigDict(extra="forbid")

    task_id: str
    description: str

    action_type: str = "PENDING_ROUTING"

    dependencies: list[str] = Field(
        default_factory=list
    )

    status: str = "PENDING"

    result: Any | None = None


# ============================================================
# 2. Bank Investigation DAG
# ============================================================


class InvestigationDAG:
    """
    Bank-specific DAG used after Amr's generic Plan
    has been generated and validated.

    NetworkX is used for:
    - dependency representation
    - cycle detection
    - topological ordering
    - parallel execution batches
    """

    def __init__(self) -> None:
        self.graph = nx.DiGraph()
        self.nodes: dict[str, TaskNode] = {}

    # --------------------------------------------------------
    # Add task
    # --------------------------------------------------------

    def add_task(
        self,
        node: TaskNode,
    ) -> None:
        """
        Add a task while preserving DAG validity.
        """

        if node.task_id in self.nodes:
            raise ValueError(
                f"Task '{node.task_id}' already exists."
            )

        missing = (
            set(node.dependencies)
            - self.nodes.keys()
        )

        if missing:
            raise ValueError(
                f"Task '{node.task_id}' has unknown "
                f"dependencies: {sorted(missing)}"
            )

        self.graph.add_node(
            node.task_id
        )

        for dependency in node.dependencies:
            self.graph.add_edge(
                dependency,
                node.task_id,
            )

        if not nx.is_directed_acyclic_graph(
            self.graph
        ):
            self.graph.remove_node(
                node.task_id
            )

            raise ValueError(
                f"Adding task '{node.task_id}' "
                "creates a cycle."
            )

        self.nodes[node.task_id] = node

    # --------------------------------------------------------
    # Add dependency
    # --------------------------------------------------------

    def add_dependency_edge(
        self,
        source: str,
        target: str,
    ) -> None:
        """
        Add dependency source -> target while preserving DAG.
        """

        if source not in self.nodes:
            raise ValueError(
                f"Unknown source task: {source}"
            )

        if target not in self.nodes:
            raise ValueError(
                f"Unknown target task: {target}"
            )

        if source == target:
            raise ValueError(
                f"Task '{source}' cannot depend on itself."
            )

        if self.graph.has_edge(
            source,
            target,
        ):
            return

        self.graph.add_edge(
            source,
            target,
        )

        if not nx.is_directed_acyclic_graph(
            self.graph
        ):
            self.graph.remove_edge(
                source,
                target,
            )

            raise ValueError(
                f"Adding dependency "
                f"'{source} -> {target}' "
                "creates a cycle."
            )

        if source not in self.nodes[
            target
        ].dependencies:

            self.nodes[
                target
            ].dependencies.append(
                source
            )

    # --------------------------------------------------------
    # Executable tasks
    # --------------------------------------------------------

    def get_executable_tasks(
        self,
    ) -> list[TaskNode]:
        """
        Return pending tasks whose dependencies
        have all completed.
        """

        executable: list[TaskNode] = []

        for node in self.nodes.values():

            if node.status != "PENDING":
                continue

            if all(
                self.nodes[
                    dependency
                ].status == "COMPLETED"
                for dependency in node.dependencies
            ):
                executable.append(node)

        return executable

    # --------------------------------------------------------
    # Status updates
    # --------------------------------------------------------

    def mark_completed(
        self,
        task_id: str,
        result: Any,
    ) -> None:

        if task_id not in self.nodes:
            raise ValueError(
                f"Unknown task: {task_id}"
            )

        self.nodes[
            task_id
        ].status = "COMPLETED"

        self.nodes[
            task_id
        ].result = result

    def mark_failed(
        self,
        task_id: str,
        result: Any,
    ) -> None:

        if task_id not in self.nodes:
            raise ValueError(
                f"Unknown task: {task_id}"
            )

        self.nodes[
            task_id
        ].status = "FAILED"

        self.nodes[
            task_id
        ].result = result

    # --------------------------------------------------------
    # Graph utilities
    # --------------------------------------------------------

    def topological_order(
        self,
    ) -> list[str]:

        return list(
            nx.topological_sort(
                self.graph
            )
        )

    def execution_batches(
        self,
    ) -> list[list[str]]:
        """
        Tasks in the same generation have
        no dependency between them and can
        therefore execute in parallel.
        """

        return [
            sorted(batch)
            for batch in nx.topological_generations(
                self.graph
            )
        ]

    def terminal_tasks(
        self,
    ) -> list[str]:

        return [
            node
            for node, degree
            in self.graph.out_degree()
            if degree == 0
        ]


# ============================================================
# 3. Convert Amr Plan -> Bank InvestigationDAG
# ============================================================


def plan_to_investigation_dag(
    plan: Plan,
) -> InvestigationDAG:
    """
    Adapt Amr's generic validated Plan into
    the bank-specific InvestigationDAG.

    IMPORTANT:

    We do NOT generate the plan here.

    Amr's toolkit remains responsible for:

    - LLM decomposition
    - task schema
    - dependency validation
    - cycle detection
    - topological ordering

    This function only adapts the result
    to the bank representation.
    """

    dag = InvestigationDAG()

    for task_id in plan.topological_order():

        task = plan.task(
            task_id
        )

        bank_task = TaskNode(
            task_id=task.id,
            description=task.instruction,
            action_type="PENDING_ROUTING",
            dependencies=list(
                task.depends_on
            ),
        )

        dag.add_task(
            bank_task
        )

    return dag


# ============================================================
# 4. Decomposition-first Adapter
# ============================================================


class BankDecompositionAdapter:
    """
    Bank adapter around Amr's decomposition-first method.

    Flow:

        Real bank request
              |
              v
        Amr decompose_goal()
              |
              v
        Validated Plan
              |
              v
        Bank InvestigationDAG
              |
              v
        Parallel DAG execution
              |
              v
        MCP / DB router
    """

    def __init__(
        self,
        llm: Any,
    ) -> None:

        self.llm = llm

    # --------------------------------------------------------
    # Decompose
    # --------------------------------------------------------

    def decompose(
        self,
        goal: str,
    ) -> InvestigationDAG:
        """
        Generate the complete plan using Amr's
        original decomposition implementation.
        """

        plan = decompose_goal(
            goal,
            self.llm,
        )

        return plan_to_investigation_dag(
            plan
        )

    # --------------------------------------------------------
    # Execute
    # --------------------------------------------------------

    def execute(
        self,
        dag: InvestigationDAG,
        execute_task: Callable[
            [TaskNode, dict[str, Any]],
            Any,
        ],
        max_workers: int = 4,
    ) -> dict[str, Any]:
        """
        Execute the generated DAG.

        The actual bank/MCP execution is delegated
        to execute_task.
        """

        outputs: dict[str, Any] = {}

        for batch in dag.execution_batches():

            if not batch:
                continue

            def run_task(
                task_id: str,
            ) -> tuple[str, Any]:

                task = dag.nodes[
                    task_id
                ]

                context = {
                    dependency: outputs[
                        dependency
                    ]
                    for dependency
                    in task.dependencies
                }

                task.status = "IN_PROGRESS"

                result = execute_task(
                    task,
                    context,
                )

                return (
                    task_id,
                    result,
                )

            with ThreadPoolExecutor(
                max_workers=min(
                    max_workers,
                    len(batch),
                )
            ) as pool:

                futures = {
                    pool.submit(
                        run_task,
                        task_id,
                    ): task_id
                    for task_id in batch
                }

                for future in as_completed(
                    futures
                ):

                    task_id = futures[
                        future
                    ]

                    try:

                        _, result = (
                            future.result()
                        )

                        if result is None:
                            raise RuntimeError(
                                f"Task '{task_id}' "
                                "returned no result."
                            )

                        dag.mark_completed(
                            task_id,
                            result,
                        )

                        outputs[
                            task_id
                        ] = result

                    except Exception as exc:

                        dag.mark_failed(
                            task_id,
                            str(exc),
                        )

                        raise

        return outputs


# ============================================================
# 5. Complete decomposition-first run
# ============================================================


def run_decomposition(
    goal: str,
    llm: Any,
    execute_task: Callable[
        [TaskNode, dict[str, Any]],
        Any,
    ],
    max_workers: int = 4,
) -> dict[str, Any]:
    """
    Convenience function for evaluation.
    """

    adapter = BankDecompositionAdapter(
        llm
    )

    dag = adapter.decompose(
        goal
    )

    outputs = adapter.execute(
        dag,
        execute_task,
        max_workers=max_workers,
    )

    return {
        "method": "decomposition-first",
        "goal": goal,
        "topological_order": (
            dag.topological_order()
        ),
        "execution_batches": (
            dag.execution_batches()
        ),
        "terminal_tasks": (
            dag.terminal_tasks()
        ),
        "tasks": {
            task_id: {
                "description": task.description,
                "action_type": task.action_type,
                "dependencies": task.dependencies,
                "status": task.status,
                "result": task.result,
            }
            for task_id, task
            in dag.nodes.items()
        },
        "outputs": outputs,
    }