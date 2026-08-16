from __future__ import annotations
import asyncio
import inspect
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from dotenv import load_dotenv
from langchain_mistralai import ChatMistralAI
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

EVAL_DIR = Path(__file__).resolve().parent
ROOT = EVAL_DIR.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from config import MISTRAL_API_KEY
from planning_eval.metrics import (
    MetricsTracker,
    average_metrics,
    calculate_success_rate,
)
from planning_eval.correctness import evaluate_case_correctness
from planning.decomposition import TaskNode, run_decomposition
from planning.dynamic_decomposition import BankDynamicDecomposition
from planning.algorithms import (
    run_plan_and_solve,
    run_tree_of_thoughts,
    run_lats,
)
from planning.router import dispatch_sync
from planning.self_refine import reflect_and_refine
from planning.reflexion import reflexion
from planning.environment import Environment

MODEL = os.getenv("PLANNING_MODEL", "mistral-small-latest")
TEST_REQUESTS_FILE = EVAL_DIR / "test_requests.json"
README_FILE = EVAL_DIR / "evaluation.md"
ARTIFACT_DIR = EVAL_DIR / "artifacts"
MCP_SERVER_SCRIPT = str(ROOT / "mcp" / "server.py")

EVALUATION_START = "<!-- EVALUATION_START -->"
EVALUATION_END = "<!-- EVALUATION_END -->"


class EvaluationEnvironmentBridge:
    def __init__(
        self,
        environment: Environment,
        task_description: str,
        main_loop: asyncio.AbstractEventLoop,
    ):
        self._environment = environment
        self._task_description = task_description
        self._main_loop = main_loop

    def evaluate(
        self,
        state: str,
        task: str | None = None,
    ):
        evaluation_task = (
            task
            if task is not None
            else self._task_description
        )
        result = self._environment.evaluate(
            state,
            task=evaluation_task,
        )
        if not inspect.isawaitable(result):
            return result

        future = asyncio.run_coroutine_threadsafe(
            result,
            self._main_loop,
        )
        return future.result()


def run_lats_in_worker_thread(
    goal: str,
    context: str,
    llm: Any,
    environment: Any,
) -> Any:
    return asyncio.run(
        run_lats(
            goal,
            context,
            llm,
            environment,
        )
    )


def save_evaluation_artifact(
    cases: list[dict[str, Any]],
    results: list[dict[str, Any]],
) -> Path:
    ARTIFACT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    payload = {
        "type": "planning_evaluation",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": MODEL,
        "test_suite": str(TEST_REQUESTS_FILE),
        "num_cases": len(cases),
        "num_results": len(results),
        "results": results,
        "summary": build_method_summary(results),
    }

    stamp = datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ"
    )

    path = ARTIFACT_DIR / f"run-{stamp}.json"

    path.write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
            default=str,
        ),
        encoding="utf-8",
    )

    return path


def load_test_requests() -> list[dict[str, Any]]:
    with TEST_REQUESTS_FILE.open(
        "r",
        encoding="utf-8",
    ) as f:
        return json.load(f)


def build_llm(
    metrics_tracker: MetricsTracker,
) -> ChatMistralAI:
    if not MISTRAL_API_KEY:
        raise RuntimeError(
            "MISTRAL_API_KEY is not set."
        )

    return ChatMistralAI(
        model=MODEL,
        api_key=MISTRAL_API_KEY,
        temperature=0,
        callbacks=[metrics_tracker],
    )


def extract_account_id(
    text: str,
) -> int | None:
    match = re.search(
        r"account(?:_id)?\s*[#:=]?\s*(\d+)",
        text,
        re.IGNORECASE,
    )
    return int(match.group(1)) if match else None


def extract_customer_id(
    text: str,
) -> int | None:
    match = re.search(
        r"customer(?:_id)?\s*[#:=]?\s*(\d+)",
        text,
        re.IGNORECASE,
    )
    return int(match.group(1)) if match else None


def extract_destination_country(
    text: str,
) -> str | None:
    match = re.search(
        r"destination_country\s*[:=]?\s*([A-Za-z]{2})\b",
        text,
    )
    return (
        match.group(1).upper()
        if match
        else None
    )


def build_evidence_context(
    context: dict[str, Any],
) -> str:
    if not context:
        return "No previous evidence."

    return "\n\n".join(
        f"Previous task: {task_id}\n"
        f"Result:\n{result}"
        for task_id, result in context.items()
    )


def build_evidence_context_from_history(
    history: list[tuple[str, str]],
) -> str:
    if not history:
        return "No previous evidence."

    return "\n\n".join(
        f"Previous task: {description}\n"
        f"Result:\n{observation}"
        for description, observation in history
    )


def dynamic_run_to_text(
    run: Any,
) -> str:
    if not run.steps:
        return "No investigation steps were taken."

    return "\n\n".join(
        f"Step: {step.task.description}\n"
        f"Result: {step.observation}"
        for step in run.steps
    )


def make_decomposition_execute_task(
    llm: Any,
    environment: Any,
):
    def execute_task(
        task: TaskNode,
        context: dict[str, Any],
    ) -> Any:
        evidence = build_evidence_context(context)

        account_id = extract_account_id(
            task.description
        )

        customer_id = extract_customer_id(
            task.description
        )

        destination_country = (
            extract_destination_country(
                task.description
            )
        )

        return dispatch_sync(
            task,
            evidence,
            llm,
            customer_id=customer_id,
            account_ids=(
                [account_id]
                if account_id is not None
                else None
            ),
            destination_country=destination_country,
            environment=environment,
        )

    return execute_task


def make_dynamic_execute_task(
    llm: Any,
    environment: Any,
):
    def execute_task(
        task: TaskNode,
        history: list[tuple[str, str]],
    ) -> Any:
        evidence = (
            build_evidence_context_from_history(
                history
            )
        )

        account_id = extract_account_id(
            task.description
        )

        customer_id = extract_customer_id(
            task.description
        )

        destination_country = (
            extract_destination_country(
                task.description
            )
        )

        return dispatch_sync(
            task,
            evidence,
            llm,
            customer_id=customer_id,
            account_ids=(
                [account_id]
                if account_id is not None
                else None
            ),
            destination_country=destination_country,
            environment=environment,
        )

    return execute_task


def run_decomposition_sync(
    goal: str,
    llm: Any,
    execute_task: Any,
) -> Any:
    return run_decomposition(
        goal,
        llm,
        execute_task,
        max_workers=4,
    )


def run_dynamic_decomposition_sync(
    planner: BankDynamicDecomposition,
    goal: str,
    execute_task: Any,
) -> Any:
    return planner.run(
        goal,
        execute_task,
        max_steps=6,
    )


async def run_method(
    case: dict[str, Any],
    method: str,
    llm: Any,
    session: ClientSession,
) -> dict[str, Any]:
    goal = case["goal"]
    start = time.perf_counter()
    result: Any = None
    metadata: dict[str, Any] = {}
    main_loop = asyncio.get_running_loop()

    if method == "decomposition-first":
        environment = Environment(
            mcp_session=session
        )

        bridge = EvaluationEnvironmentBridge(
            environment=environment,
            task_description=goal,
            main_loop=main_loop,
        )

        execute_task = (
            make_decomposition_execute_task(
                llm,
                bridge,
            )
        )

        run_output = await asyncio.to_thread(
            run_decomposition_sync,
            goal,
            llm,
            execute_task,
        )

        result = run_output

        metadata["planner"] = (
            "BankDecompositionAdapter"
        )

        metadata["task_count"] = len(
            run_output.get("tasks", {})
        )

        metadata["grounded"] = True

        metadata["execution_path"] = (
            "decomposition -> router -> "
            "Environment Bridge -> MCP Server -> DB"
        )

    elif method == "dynamic-decomposition":
        environment = Environment(
            mcp_session=session
        )

        bridge = EvaluationEnvironmentBridge(
            environment=environment,
            task_description=goal,
            main_loop=main_loop,
        )

        planner = BankDynamicDecomposition(
            llm=llm
        )

        execute_task = (
            make_dynamic_execute_task(
                llm,
                bridge,
            )
        )

        dynamic_run = await asyncio.to_thread(
            run_dynamic_decomposition_sync,
            planner,
            goal,
            execute_task,
        )

        result = dynamic_run_to_text(
            dynamic_run
        )

        metadata["planner"] = (
            "BankDynamicDecomposition"
        )

        metadata["steps"] = len(
            dynamic_run.steps
        )

        metadata["grounded"] = True

        metadata["execution_path"] = (
            "dynamic decomposition -> router -> "
            "Environment Bridge -> MCP Server -> DB"
        )

    elif method == "plan-and-solve":
        result = await run_plan_and_solve(
            goal,
            "",
            llm,
        )

        metadata["planner"] = (
            "Plan-and-Solve"
        )

        metadata["grounded"] = False

    elif method == "tree-of-thoughts":
        result = await run_tree_of_thoughts(
            goal,
            "",
            llm,
        )

        metadata["planner"] = (
            "Tree-of-Thoughts"
        )

        metadata["grounded"] = False

    elif method == "lats-grounded":
        environment = Environment(
            mcp_session=session
        )

        bridge = EvaluationEnvironmentBridge(
            environment=environment,
            task_description=goal,
            main_loop=main_loop,
        )

        result = await asyncio.to_thread(
            run_lats_in_worker_thread,
            goal,
            "",
            llm,
            bridge,
        )

        metadata["planner"] = "LATS"
        metadata["grounded"] = True

        metadata["execution_path"] = (
            "LATS -> Environment Bridge -> "
            "MCP Environment -> MCP Server -> DB"
        )

    elif method == "lats-ungrounded":
        from planning_lab.algorithms.environment import (
            Environment as ToolkitEnvironment,
        )

        environment = ToolkitEnvironment()

        result = await run_lats(
            goal,
            "",
            llm,
            environment,
        )

        metadata["planner"] = "LATS"
        metadata["grounded"] = False

        metadata["execution_path"] = (
            "LATS -> Toolkit Environment"
        )

    elif method == "self-refine-grounded":
        environment = Environment(
            mcp_session=session
        )

        draft = await run_plan_and_solve(
            goal,
            "",
            llm,
        )

        draft = str(draft)

        if not draft.strip():
            raise RuntimeError(
                "Self-Refine produced an empty draft."
            )

        reflection = await reflect_and_refine(
            goal=goal,
            draft=draft,
            llm=llm,
            environment=environment,
        )

        result = reflection.revised

        metadata["planner"] = (
            "Self-Refine"
        )

        metadata["grounded"] = True

        metadata["revision_applied"] = (
            reflection.revised
            != reflection.draft
        )

        metadata["grounded_issues"] = getattr(
            reflection,
            "grounded_issues",
            [],
        )

    elif method == "reflexion":
        environment = Environment(
            mcp_session=session
        )

        result = await reflexion(
            task=goal,
            llm=llm,
            environment=environment,
            max_trials=3,
            memory_size=3,
        )

        metadata["planner"] = "Reflexion"

        metadata["trials"] = len(
            result.trials
        )

        metadata["memory_size"] = len(
            result.memory
        )

        metadata["reflexion_success"] = (
            result.success
        )

        metadata["grounded"] = True

    else:
        raise ValueError(
            f"Unknown evaluation method: {method}"
        )

    latency = time.perf_counter() - start

    correctness = evaluate_case_correctness(
        case=case,
        result=result,
    )

    return {
        "case_id": case["id"],
        "goal": goal,
        "method": method,
        "success": correctness["success"],
        "correctness": correctness,
        "latency_seconds": latency,
        "result": str(result),
        "metadata": metadata,
    }


METHOD_NAME_MAP = {
    "decomposition-first": "decomposition-first",
    "dynamic-decomposition": "dynamic-decomposition",
    "plan-and-solve": "plan-and-solve",
    "tree-of-thoughts": "tree-of-thoughts",
    "lats-ungrounded": "lats-ungrounded",
    "lats-grounded": "lats-grounded",
    "self-refine-grounded": "self-refine-grounded",
    "reflexion": "reflexion",
}


def applicable_methods(
    case: dict[str, Any],
) -> list[str]:
    return [
        METHOD_NAME_MAP[method]
        for method in case.get(
            "applicable_methods",
            [],
        )
        if method in METHOD_NAME_MAP
    ]


def get_experiment_number(
    case_id: str,
) -> int | None:
    match = re.search(
        r"experiment_(\d+)",
        case_id,
        re.IGNORECASE,
    )

    if not match:
        return None

    return int(match.group(1))


def filter_results_by_experiments(
    results: list[dict[str, Any]],
    experiment_numbers: set[int],
) -> list[dict[str, Any]]:
    return [
        result
        for result in results
        if (
            get_experiment_number(
                result["case_id"]
            )
            in experiment_numbers
        )
    ]


def build_method_summary(
    results: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    grouped: dict[
        str,
        list[dict[str, Any]]
    ] = {}

    for result in results:
        grouped.setdefault(
            result["method"],
            [],
        ).append(result)

    summary: dict[
        str,
        dict[str, Any]
    ] = {}

    for method, method_results in grouped.items():
        metrics = average_metrics(
            method_results
        )

        matched = sum(
            result.get(
                "correctness",
                {},
            ).get(
                "matched",
                0,
            )
            for result in method_results
        )

        expected = sum(
            result.get(
                "correctness",
                {},
            ).get(
                "expected",
                0,
            )
            for result in method_results
        )

        summary[method] = {
            "task_success_matched": matched,
            "task_success_expected": expected,
            "task_success_fraction": (
                f"{matched}/{expected}"
            ),
            "task_success_percent": (
                calculate_success_rate(
                    method_results
                )
            ),
            "num_cases": len(
                method_results
            ),
            **metrics,
        }

    return summary


def markdown_method_table(
    results: list[dict[str, Any]],
) -> list[str]:
    if not results:
        return [
            "| Method | Task success | Avg. LLM calls | Avg. tokens | Avg. latency | Est. cost/run |",
            "|---|---:|---:|---:|---:|---:|",
            "| No applicable results | — | — | — | — | — |",
        ]

    summary = build_method_summary(
        results
    )

    lines = [
        "| Method | Task success | Avg. LLM calls | Avg. tokens | Avg. latency | Est. cost/run |",
        "|---|---:|---:|---:|---:|---:|",
    ]

    for method in sorted(summary):
        data = summary[method]

        lines.append(
            f"| {method} | "
            f"{data['task_success_fraction']} | "
            f"{data['avg_llm_calls']:.1f} | "
            f"{data['avg_total_tokens']:.0f} | "
            f"{data['avg_latency_seconds']:.3f}s | "
            f"${data['avg_estimated_cost_usd']:.6f} |"
        )

    return lines


def append_section(
    lines: list[str],
    title: str,
    description: str,
    results: list[dict[str, Any]],
) -> None:
    lines.extend([
        f"## {title}",
        "",
        description,
        "",
    ])

    lines.extend(
        markdown_method_table(
            results
        )
    )

    lines.append("")


def generate_evaluation_markdown(
    *,
    cases: list[dict[str, Any]],
    results: list[dict[str, Any]],
) -> None:
    lines: list[str] = [
        EVALUATION_START,
        "# Sterling & Vance Planning Evaluation",
        "",
        f"**Model:** `{MODEL}`",
        "",
        f"**Evaluation cases:** `{len(cases)}`",
        "",
        "**Generated:** "
        f"`{datetime.now(timezone.utc).isoformat()}`",
        "",
        "This report is generated automatically by "
        "`planning_eval/run_evaluation.py`.",
        "",
        "Task success is reported as "
        "`matched/expected` deterministic correctness "
        "evidence rather than as a percentage.",
        "",
        "The deterministic correctness evaluator is "
        "implemented in `planning_eval/correctness.py`.",
        "",
        "## Overall Results",
        "",
        "| Method | Cases | Task success | Avg. LLM calls | Avg. tokens | Avg. latency | Est. cost/run |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]

    overall_summary = build_method_summary(
        results
    )

    for method in sorted(
        overall_summary
    ):
        data = overall_summary[method]

        lines.append(
            f"| {method} | "
            f"{data['num_cases']} | "
            f"{data['task_success_fraction']} | "
            f"{data['avg_llm_calls']:.1f} | "
            f"{data['avg_total_tokens']:.0f} | "
            f"{data['avg_latency_seconds']:.3f}s | "
            f"${data['avg_estimated_cost_usd']:.6f} |"
        )

    experiment_01_02 = (
        filter_results_by_experiments(
            results,
            {1, 2},
        )
    )

    experiment_03_04 = (
        filter_results_by_experiments(
            results,
            {3, 4},
        )
    )

    experiment_05 = (
        filter_results_by_experiments(
            results,
            {5},
        )
    )

    experiment_06 = (
        filter_results_by_experiments(
            results,
            {6},
        )
    )

    experiment_07 = (
        filter_results_by_experiments(
            results,
            {7},
        )
    )

    append_section(
        lines,
        "1. Mechanical and Adaptive Decomposition",
        "Experiments 01–02 compare fixed "
        "decomposition-first planning with "
        "dynamic decomposition.",
        experiment_01_02,
    )

    append_section(
        lines,
        "2. Lookahead and Grounded Planning",
        "Experiments 03–04 compare Plan-and-Solve, "
        "Tree of Thoughts, ungrounded LATS, and "
        "grounded LATS.",
        experiment_03_04,
    )

    append_section(
        lines,
        "3. Reflexion and Self-Correction",
        "Experiment 05 evaluates Reflexion under a "
        "required-risk-factor threshold.",
        experiment_05,
    )

    append_section(
        lines,
        "4. Search Behavior",
        "Experiment 06 compares Tree of Thoughts "
        "with grounded LATS for investigation search "
        "behavior.",
        experiment_06,
    )

    append_section(
        lines,
        "5. Validation Failure Handling",
        "Experiment 07 evaluates whether the planning "
        "pipeline rejects a deliberately invalid "
        "investigation plan containing a dependency "
        "cycle.",
        experiment_07,
    )

    lines.extend([
        "## 6. Case-Level Results",
        "",
        "| Case | Method | Success | Correctness | Calls | Tokens | Latency |",
        "|---|---|---:|---:|---:|---:|---:|",
    ])

    for result in results:
        correctness = result.get(
            "correctness",
            {},
        )

        metrics = result.get(
            "metrics",
            {},
        )

        success = (
            "Yes"
            if result.get("success")
            else "No"
        )

        lines.append(
            f"| {result['case_id']} | "
            f"{result['method']} | "
            f"{success} | "
            f"{correctness.get('matched', 0)}/"
            f"{correctness.get('expected', 0)} "
            f"({correctness.get('score', 0) * 100:.1f}%) | "
            f"{metrics.get('llm_calls', 0)} | "
            f"{metrics.get('total_tokens', 0)} | "
            f"{result.get('latency_seconds', 0):.3f}s |"
        )

    lines.extend([
        "",
        "## 7. Missing Expected Evidence",
        "",
    ])

    any_missing = False

    for result in results:
        missing = (
            result.get(
                "correctness",
                {},
            ).get(
                "missing",
                [],
            )
        )

        if not missing:
            continue

        any_missing = True

        lines.extend([
            f"### {result['case_id']} — "
            f"{result['method']}",
            "",
        ])

        lines.extend(
            f"- `{item}`"
            for item in missing
        )

        lines.append("")

    if not any_missing:
        lines.extend([
            "No expected evidence was missing.",
            "",
        ])

    lines.extend([
        "## 8. Execution Errors",
        "",
    ])

    errors = [
        result
        for result in results
        if "error" in result
    ]

    if not errors:
        lines.extend([
            "No execution errors occurred.",
            "",
        ])
    else:
        lines.extend(
            f"- **{result['case_id']}** — "
            f"`{result['method']}`: "
            f"{result.get('error', 'Unknown error')}"
            for result in errors
        )

        lines.append("")

    lines.extend([
        "## 9. Interpretation",
        "",
        "The evaluation compares planning strategies "
        "using factual task success, LLM resource usage, "
        "latency, and estimated cost.",
        "",
        "Task success is intentionally displayed as "
        "`matched/expected` in aggregate tables, "
        "for example `14/20`, rather than being "
        "collapsed into a 0–100 percentage.",
        "",
        "Grounded methods are considered meaningfully "
        "grounded only when their environment validates "
        "candidate conclusions against the actual "
        "Sterling & Vance banking environment.",
        "",
        "The deterministic correctness evaluator does "
        "not call an additional LLM.",
        "",
        "## 10. Reproducibility",
        "",
        "Raw evaluation evidence is stored in the "
        "`planning_eval/artifacts` directory.",
        "",
        EVALUATION_END,
    ])

    new_evaluation = "\n".join(lines)

    if README_FILE.exists():
        existing_readme = README_FILE.read_text(
            encoding="utf-8"
        )

        start_index = existing_readme.find(
            EVALUATION_START
        )

        end_index = existing_readme.find(
            EVALUATION_END
        )

        if (
            start_index != -1
            and end_index != -1
            and end_index > start_index
        ):
            updated_readme = (
                existing_readme[:start_index]
                + new_evaluation
                + existing_readme[
                    end_index
                    + len(EVALUATION_END):
                ]
            )
        else:
            updated_readme = (
                existing_readme.rstrip()
                + "\n\n"
                + new_evaluation
                + "\n"
            )
    else:
        updated_readme = (
            new_evaluation
            + "\n"
        )

    README_FILE.write_text(
        updated_readme,
        encoding="utf-8",
    )


async def run_evaluation() -> None:
    cases = load_test_requests()
    all_results: list[
        dict[str, Any]
    ] = []

    print("=" * 70)
    print(
        "STERLING & VANCE PLANNING EVALUATION"
    )
    print("=" * 70)
    print(f"Model: {MODEL}")
    print(f"Cases: {len(cases)}\n")

    server_params = StdioServerParameters(
        command=sys.executable,
        args=[MCP_SERVER_SCRIPT],
    )

    async with stdio_client(
        server_params
    ) as (read, write):
        async with ClientSession(
            read,
            write,
        ) as session:
            await session.initialize()

            login_result = (
                await session.call_tool(
                    "login",
                    {"employee_id": 1},
                )
            )

            print("\nMCP Login:")

            for content in (
                login_result.content
            ):
                if hasattr(content, "text"):
                    print(content.text)

            if not any(
                hasattr(content, "text")
                and "Logged in as"
                in content.text
                and "compliance_officer"
                in content.text
                for content in (
                    login_result.content
                )
            ):
                raise RuntimeError(
                    "MCP login failed."
                )

            for case in cases:
                print(
                    f"\n{'-' * 70}"
                )

                print(
                    f"CASE: {case['id']}"
                )

                print(
                    case["goal"]
                )

                methods = (
                    applicable_methods(
                        case
                    )
                )

                print(
                    "Methods: "
                    + ", ".join(methods)
                )

                for method in methods:
                    print(
                        f"\nRunning: {method}"
                    )

                    metrics_tracker = (
                        MetricsTracker(
                            model_name=MODEL
                        )
                    )

                    llm = build_llm(
                        metrics_tracker
                    )

                    try:
                        result = await run_method(
                            case,
                            method,
                            llm,
                            session,
                        )

                        metrics = (
                            metrics_tracker.snapshot()
                        )

                        result["metrics"] = (
                            metrics
                        )

                        all_results.append(
                            result
                        )

                        correctness = (
                            result["correctness"]
                        )

                        print(
                            f"Success: "
                            f"{result['success']}"
                        )

                        print(
                            "Correctness: "
                            f"{correctness['matched']}/"
                            f"{correctness['expected']} "
                            f"({correctness['score'] * 100:.1f}%)"
                        )

                        print(
                            "Latency: "
                            f"{result['latency_seconds']:.3f}s"
                        )

                        print(
                            "LLM calls: "
                            f"{metrics.get('llm_calls', 0)}"
                        )

                        print(
                            "Input tokens: "
                            f"{metrics.get('input_tokens', 0)}"
                        )

                        print(
                            "Output tokens: "
                            f"{metrics.get('output_tokens', 0)}"
                        )

                        print(
                            "Total tokens: "
                            f"{metrics.get('total_tokens', 0)}"
                        )

                        print(
                            "Estimated cost: "
                            f"${metrics.get('estimated_cost_usd', 0.0):.6f}"
                        )

                    except Exception as exc:
                        print(
                            f"ERROR: "
                            f"{type(exc).__name__}: "
                            f"{exc}"
                        )

                        all_results.append({
                            "case_id": case["id"],
                            "goal": case["goal"],
                            "method": method,
                            "success": False,
                            "correctness": {
                                "success": False,
                                "score": 0.0,
                                "matched": 0,
                                "expected": 0,
                                "missing": [
                                    str(exc)
                                ],
                            },
                            "error": str(exc),
                            "error_type": (
                                type(exc).__name__
                            ),
                            "latency_seconds": 0.0,
                            "metrics": {
                                "llm_calls": (
                                    metrics_tracker.llm_calls
                                ),
                                "input_tokens": (
                                    metrics_tracker.input_tokens
                                ),
                                "output_tokens": (
                                    metrics_tracker.output_tokens
                                ),
                                "total_tokens": (
                                    metrics_tracker.total_tokens
                                ),
                                "latency_seconds": 0.0,
                                "estimated_cost_usd": (
                                    metrics_tracker.estimated_cost_usd()
                                ),
                            },
                        })

                    artifact_path = (
                        save_evaluation_artifact(
                            cases,
                            all_results,
                        )
                    )

                    print(
                        "\nCheckpoint artifact:"
                        f"\n{artifact_path}"
                    )

    artifact_path = (
        save_evaluation_artifact(
            cases,
            all_results,
        )
    )

    print(
        f"\nEvaluation artifact:\n"
        f"{artifact_path}"
    )

    generate_evaluation_markdown(
        cases=cases,
        results=all_results,
    )

    print(
        f"\nEvaluation report:\n"
        f"{README_FILE}"
    )

    print(
        "\n" + "=" * 70
    )

    print(
        "FINAL SUMMARY"
    )

    print(
        "=" * 70
    )

    summary = build_method_summary(
        all_results
    )

    for method in sorted(summary):
        data = summary[method]

        print(
            f"{method}: "
            f"{data['task_success_fraction']} success | "
            f"{data['avg_llm_calls']:.1f} calls | "
            f"{data['avg_total_tokens']:.0f} tokens | "
            f"{data['avg_latency_seconds']:.3f}s | "
            f"${data['avg_estimated_cost_usd']:.6f}/run"
        )


if __name__ == "__main__":
    asyncio.run(
        run_evaluation()
    )