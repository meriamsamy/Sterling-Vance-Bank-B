from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import networkx as nx

from pydantic import BaseModel, ConfigDict, Field

from planning_lab.algorithms.dynamic_decomposition import (
    DynamicDecision,
)


# ============================================================
# 1. Bank-specific task
# ============================================================


class TaskNode(BaseModel):
    """
    One dynamically generated banking investigation task.
    """

    model_config = ConfigDict(
        extra="forbid"
    )

    task_id: str

    description: str

    action_type: str = "PENDING_ROUTING"

    dependencies: list[str] = Field(
        default_factory=list
    )

    status: str = "PENDING"

    result: Any | None = None


# ============================================================
# 2. Investigation DAG
# ============================================================


class InvestigationDAG:

    def __init__(self) -> None:

        self.graph = nx.DiGraph()

        self.nodes: dict[
            str,
            TaskNode,
        ] = {}

    # --------------------------------------------------------
    # Add task
    # --------------------------------------------------------

    def add_task(
        self,
        node: TaskNode,
    ) -> None:

        if node.task_id in self.nodes:
            raise ValueError(
                f"Task '{node.task_id}' "
                "already exists."
            )

        missing = (
            set(node.dependencies)
            - self.nodes.keys()
        )

        if missing:
            raise ValueError(
                f"Task '{node.task_id}' "
                f"has unknown dependencies: "
                f"{sorted(missing)}"
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
                f"Adding task "
                f"'{node.task_id}' "
                "creates a cycle."
            )

        self.nodes[
            node.task_id
        ] = node

    # --------------------------------------------------------
    # Add dependency edge
    # --------------------------------------------------------

    def add_dependency_edge(
        self,
        source: str,
        target: str,
    ) -> None:

        if source not in self.nodes:
            raise ValueError(
                f"Unknown source task: "
                f"{source}"
            )

        if target not in self.nodes:
            raise ValueError(
                f"Unknown target task: "
                f"{target}"
            )

        if source == target:
            raise ValueError(
                "A task cannot depend "
                "on itself."
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
                f"Adding '{source} -> "
                f"{target}' creates a cycle."
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
    # Status
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
    # Executable tasks
    # --------------------------------------------------------

    def get_executable_tasks(
        self,
    ) -> list[TaskNode]:

        return [
            node
            for node
            in self.nodes.values()
            if (
                node.status == "PENDING"
                and all(
                    self.nodes[
                        dependency
                    ].status == "COMPLETED"
                    for dependency
                    in node.dependencies
                )
            )
        ]

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


# ============================================================
# 3. Dynamic execution trace
# ============================================================


@dataclass
class DynamicStep:

    task: TaskNode

    observation: Any

    planner_calls: int = 1


@dataclass
class DynamicRun:

    steps: list[
        DynamicStep
    ] = field(
        default_factory=list
    )

    @property
    def observations(
        self,
    ) -> list[tuple[str, Any]]:

        return [
            (
                step.task.task_id,
                step.observation,
            )
            for step in self.steps
        ]


# ============================================================
# 4. Bank Dynamic Planner
# ============================================================


class BankDynamicDecomposition:
    """
    Bank-specific adapter around Amr's dynamic
    decomposition idea.

    Flow:

        goal
          ↓
        choose task
          ↓
        bank/MCP execution
          ↓
        observation
          ↓
        choose next task
          ↓
        ...
    """

    def __init__(
        self,
        llm: Any,
    ) -> None:

        self.llm = llm

        self.dag = InvestigationDAG()

    # --------------------------------------------------------
    # Planner decision
    # --------------------------------------------------------

    def choose_next_task(
        self,
        goal: str,
        history: list[
            tuple[str, str]
        ],
    ) -> DynamicDecision:
        """
        Reuse Amr's DynamicDecision schema.

        The LLM only decides WHAT should happen next.
        It does not execute the banking task.
        """

        observation = (
            "\n".join(
                f"{task}: {result}"
                for task, result
                in history
            )
            or "None"
        )

        decision = (
            self.llm
            .with_structured_output(
                DynamicDecision,
                method="json_schema",
            )
            .invoke(
                [
                    (
                        "system",
                        """
You are an adaptive banking
investigation planner.

Use previous observations before
deciding what should happen next.

Choose exactly one concrete
investigation task at a time.

The task must be executable by
a bank integration layer.

Possible investigation areas include:

- customer accounts
- transactions
- wire transfers
- sanctions
- structuring
- counterparties
- relationships
- evidence consolidation
- risk assessment

Do not assume information that
has not been observed.

Set done=true only when enough
investigation has been completed
to satisfy the goal.

When done=true, next_task must
be an empty string.
""",
                    ),
                    (
                        "human",
                        f"""
Goal:
{goal}

Completed work and observations:
{observation}

Decide the single best next
investigation task.
""",
                    ),
                ],
                temperature=0.1,
            )
        )

        return decision

    # --------------------------------------------------------
    # Create task
    # --------------------------------------------------------

    def create_task(
        self,
        task_description: str,
        previous_task: TaskNode | None = None,
    ) -> TaskNode:
        """
        Convert the planner's textual decision
        into a bank TaskNode.
        """

        task_id = (
            f"dynamic_"
            f"{len(self.dag.nodes) + 1}"
        )

        dependencies: list[str] = []

        if previous_task is not None:

            dependencies = [
                previous_task.task_id
            ]

        task = TaskNode(
            task_id=task_id,
            description=task_description,
            action_type="PENDING_ROUTING",
            dependencies=dependencies,
        )

        self.dag.add_task(
            task
        )

        return task

    # --------------------------------------------------------
    # Run
    # --------------------------------------------------------

    def run(
        self,
        goal: str,
        execute_task: Callable[
            [TaskNode, list[tuple[str, str]]],
            Any,
        ],
        max_steps: int = 6,
    ) -> DynamicRun:
        """
        Run dynamic/interleaved investigation.

        The LLM chooses the next task.

        execute_task performs the actual
        bank/MCP/database operation.
        """

        run = DynamicRun()

        previous_task: TaskNode | None = None

        for _ in range(
            max_steps
        ):

            # ----------------------------------------------
            # Build history
            # ----------------------------------------------

            history = [
                (
                    step.task.description,
                    str(step.observation),
                )
                for step in run.steps
            ]

            # ----------------------------------------------
            # Ask planner what to do next
            # ----------------------------------------------

            decision = (
                self.choose_next_task(
                    goal,
                    history,
                )
            )

            # ----------------------------------------------
            # Investigation finished
            # ----------------------------------------------

            if decision.done:
                break

            task_description = (
                decision.next_task.strip()
            )

            if not task_description:
                raise ValueError(
                    "Dynamic planner returned "
                    "an empty next_task while "
                    "done=false."
                )

            # ----------------------------------------------
            # Create bank task
            # ----------------------------------------------

            task = self.create_task(
                task_description,
                previous_task,
            )

            task.status = "IN_PROGRESS"

            # ----------------------------------------------
            # REAL BANK EXECUTION
            # ----------------------------------------------

            observation = execute_task(
                task,
                history,
            )

            if observation is None:

                raise RuntimeError(
                    f"Task '{task.task_id}' "
                    "returned no observation."
                )

            if (
                isinstance(
                    observation,
                    str,
                )
                and not observation.strip()
            ):

                raise RuntimeError(
                    f"Task '{task.task_id}' "
                    "returned an empty observation."
                )

            # ----------------------------------------------
            # Mark completed
            # ----------------------------------------------

            self.dag.mark_completed(
                task.task_id,
                observation,
            )

            # ----------------------------------------------
            # Store trace
            # ----------------------------------------------

            run.steps.append(
                DynamicStep(
                    task=task,
                    observation=observation,
                )
            )

            previous_task = task

        return run