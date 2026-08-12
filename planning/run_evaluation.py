from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from planning.artifacts.decomposition import (
    BankDecompositionAdapter,
    TaskNode as DecompositionTask,
)

from planning.artifacts.dynamic_decomposition import (
    BankDynamicDecomposition,
    TaskNode as DynamicTask,
)

# ============================================================
# Paths
# ============================================================

ROOT = Path(
    __file__
).resolve().parent

REQUESTS_FILE = (
    ROOT / "test_requests.json"
)

ARTIFACTS_DIR = (
    ROOT / "artifacts"
)

ARTIFACTS_DIR.mkdir(
    exist_ok=True
)


# ============================================================
# Load requests
# ============================================================


def load_requests() -> list[
    dict[str, str]
]:

    with REQUESTS_FILE.open(
        "r",
        encoding="utf-8",
    ) as file:

        return json.load(file)


# ============================================================
# JSON serialization
# ============================================================


def serialize(
    value: Any,
) -> Any:

    if hasattr(
        value,
        "model_dump",
    ):

        return value.model_dump()

    if isinstance(
        value,
        dict,
    ):

        return {
            key: serialize(item)
            for key, item
            in value.items()
        }

    if isinstance(
        value,
        list,
    ):

        return [
            serialize(item)
            for item in value
        ]

    if isinstance(
        value,
        tuple,
    ):

        return [
            serialize(item)
            for item in value
        ]

    return value


# ============================================================
# BANK EXECUTOR
# ============================================================

def bank_execute_task_decomposition(
    task: DecompositionTask,
    context: dict[str, Any],
) -> str:
    """
    TEMPORARY bank executor.

    Replace the body of this function with
    your real MCP/router call.

    The planner itself must NOT call MCP directly.
    """

    dependency_text = (
        "\n".join(
            f"{key}: {value}"
            for key, value
            in context.items()
        )
        or "No dependency outputs."
    )

    return (
        f"Executed banking investigation task: "
        f"{task.description}\n"
        f"Dependency context:\n"
        f"{dependency_text}"
    )


def bank_execute_task_dynamic(
    task: DynamicTask,
    history: list[
        tuple[str, str]
    ],
) -> str:
    """
    TEMPORARY bank executor.

    Replace the body with your real
    MCP/router call.
    """

    previous = (
        "\n".join(
            f"{name}: {result}"
            for name, result
            in history
        )
        or "No previous observations."
    )

    return (
        f"Executed banking investigation task: "
        f"{task.description}\n"
        f"Previous observations:\n"
        f"{previous}"
    )


# ============================================================
# DECOMPOSITION-FIRST
# ============================================================


def evaluate_decomposition(
    llm: Any,
    requests: list[
        dict[str, str]
    ],
) -> list[
    dict[str, Any]
]:

    adapter = (
        BankDecompositionAdapter(
            llm
        )
    )

    results = []

    for request in requests:

        request_id = request["id"]

        goal = request["goal"]

        print(
            "\n"
            + "=" * 70
        )

        print(
            f"[DECOMPOSITION] "
            f"{request_id}"
        )

        started = time.perf_counter()

        try:

            dag = adapter.decompose(
                goal
            )

            outputs = adapter.execute(
                dag,
                bank_execute_task_decomposition,
            )

            elapsed = (
                time.perf_counter()
                - started
            )

            result = {
                "request_id": request_id,
                "goal": goal,
                "status": "success",
                "execution_time_seconds": elapsed,
                "task_count": len(
                    dag.nodes
                ),
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
                        "result": serialize(
                            task.result
                        ),
                    }
                    for task_id, task
                    in dag.nodes.items()
                },
                "outputs": serialize(
                    outputs
                ),
            }

            results.append(
                result
            )

            print(
                f"SUCCESS | "
                f"{len(dag.nodes)} tasks | "
                f"{elapsed:.2f}s"
            )

        except Exception as exc:

            elapsed = (
                time.perf_counter()
                - started
            )

            result = {
                "request_id": request_id,
                "goal": goal,
                "status": "failed",
                "execution_time_seconds": elapsed,
                "error": str(exc),
            }

            results.append(
                result
            )

            print(
                f"FAILED | {exc}"
            )

    return results


# ============================================================
# DYNAMIC
# ============================================================


def evaluate_dynamic(
    llm: Any,
    requests: list[
        dict[str, str]
    ],
    max_steps: int = 6,
) -> list[
    dict[str, Any]
]:

    results = []

    for request in requests:

        request_id = request["id"]

        goal = request["goal"]

        print(
            "\n"
            + "=" * 70
        )

        print(
            f"[DYNAMIC] "
            f"{request_id}"
        )

        started = time.perf_counter()

        try:

            planner = (
                BankDynamicDecomposition(
                    llm
                )
            )

            run = planner.run(
                goal=goal,
                execute_task=(
                    bank_execute_task_dynamic
                ),
                max_steps=max_steps,
            )

            elapsed = (
                time.perf_counter()
                - started
            )

            history = [
                {
                    "task_id": (
                        step.task.task_id
                    ),
                    "task": (
                        step.task.description
                    ),
                    "observation": (
                        serialize(
                            step.observation
                        )
                    ),
                }
                for step in run.steps
            ]

            result = {
                "request_id": request_id,
                "goal": goal,
                "status": "success",
                "execution_time_seconds": elapsed,
                "steps": len(
                    run.steps
                ),
                "history": history,
                "final_observation": (
                    serialize(
                        run.steps[-1].observation
                    )
                    if run.steps
                    else ""
                ),
                "dag": {
                    "topological_order": (
                        planner.dag.topological_order()
                    ),
                    "tasks": {
                        task_id: {
                            "description": task.description,
                            "dependencies": task.dependencies,
                            "status": task.status,
                            "result": serialize(
                                task.result
                            ),
                        }
                        for task_id, task
                        in planner.dag.nodes.items()
                    },
                },
            }

            results.append(
                result
            )

            print(
                f"SUCCESS | "
                f"{len(run.steps)} steps | "
                f"{elapsed:.2f}s"
            )

        except Exception as exc:

            elapsed = (
                time.perf_counter()
                - started
            )

            result = {
                "request_id": request_id,
                "goal": goal,
                "status": "failed",
                "execution_time_seconds": elapsed,
                "error": str(exc),
            }

            results.append(
                result
            )

            print(
                f"FAILED | {exc}"
            )

    return results


# ============================================================
# Comparison
# ============================================================


def build_comparison(
    decomposition_results,
    dynamic_results,
):

    dynamic_by_id = {
        item["request_id"]: item
        for item
        in dynamic_results
    }

    comparison = []

    for decomposition in (
        decomposition_results
    ):

        request_id = (
            decomposition[
                "request_id"
            ]
        )

        dynamic = (
            dynamic_by_id.get(
                request_id,
                {},
            )
        )

        comparison.append(
            {
                "request_id": request_id,
                "decomposition_status": (
                    decomposition.get(
                        "status"
                    )
                ),
                "dynamic_status": (
                    dynamic.get(
                        "status"
                    )
                ),
                "decomposition_time_seconds": (
                    decomposition.get(
                        "execution_time_seconds"
                    )
                ),
                "dynamic_time_seconds": (
                    dynamic.get(
                        "execution_time_seconds"
                    )
                ),
                "decomposition_tasks": (
                    decomposition.get(
                        "task_count"
                    )
                ),
                "dynamic_steps": (
                    dynamic.get(
                        "steps"
                    )
                ),
            }
        )

    return comparison


# ============================================================
# Save JSON
# ============================================================


def save_json(
    filename: str,
    data: Any,
) -> None:

    path = (
        ARTIFACTS_DIR
        / filename
    )

    with path.open(
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            serialize(data),
            file,
            indent=2,
            ensure_ascii=False,
        )


# ============================================================
# MAIN
# ============================================================


def main():

    print(
        "=" * 70
    )

    print(
        "BANK PLANNING EVALUATION"
    )

    print(
        "=" * 70
    )

    requests = load_requests()

    print(
        f"\nLoaded "
        f"{len(requests)} requests."
    )

    # ========================================================
    # LLM
    # ========================================================
    #
    # IMPORTANT:
    #
    # Replace this import with the SAME LLM
    # configuration already used by your project.
    #
    # Example:
    #
    # from config import llm
    #
    # Do NOT create a second LLM configuration
    # if the project already has one.
    #
    # ========================================================

    from config import API_KEY
    from langchain_groq import ChatGroq

    llm = ChatGroq(
        api_key=API_KEY,
        model="openai/gpt-oss-20b",
        temperature=0.1,
    )

    # ========================================================
    # Run decomposition
    # ========================================================

    decomposition_results = (
        evaluate_decomposition(
            llm,
            requests,
        )
    )

    # ========================================================
    # Run dynamic
    # ========================================================

    dynamic_results = (
        evaluate_dynamic(
            llm,
            requests,
        )
    )

    # ========================================================
    # Comparison
    # ========================================================

    comparison = build_comparison(
        decomposition_results,
        dynamic_results,
    )

    # ========================================================
    # Artifacts
    # ========================================================

    save_json(
        "decomposition_traces.json",
        decomposition_results,
    )

    save_json(
        "dynamic_traces.json",
        dynamic_results,
    )

    save_json(
        "comparison.json",
        comparison,
    )

    # ========================================================
    # Print comparison
    # ========================================================

    print(
        "\n"
        + "=" * 70
    )

    print(
        "COMPARISON"
    )

    print(
        "=" * 70
    )

    for row in comparison:

        print(
            f"\nRequest: "
            f"{row['request_id']}"
        )

        print(
            "  Decomposition: "
            f"{row['decomposition_status']}"
        )

        print(
            "  Dynamic: "
            f"{row['dynamic_status']}"
        )

        print(
            "  Decomposition tasks: "
            f"{row['decomposition_tasks']}"
        )

        print(
            "  Dynamic steps: "
            f"{row['dynamic_steps']}"
        )

        print(
            "  Decomposition time: "
            f"{row['decomposition_time_seconds']:.2f}s"
        )

        print(
            "  Dynamic time: "
            f"{row['dynamic_time_seconds']:.2f}s"
        )

    print(
        "\nArtifacts:"
    )

    print(
        ARTIFACTS_DIR
    )


if __name__ == "__main__":
    main()