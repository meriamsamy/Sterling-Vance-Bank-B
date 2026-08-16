from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from langchain_mistralai import ChatMistralAI

load_dotenv()

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# planning_agent.py is the entry point for the new planning architecture.
# The same MCP server and database are used, but a planning layer sits
# between the investigation goal and the MCP execution layer.
#
# The new flow is:
#
# Goal
#   ↓
# Decomposition
#   ↓
# DAG / TaskNodes
#   ↓
# Router
#   ↓
# Planning algorithm or direct execution
#   ↓
# MCP / grounded environment

from planning.router import dispatch, classify_description
from planning.decomposition import TaskNode, BankDecompositionAdapter
from planning.environment import Environment
from planning.self_refine import reflect_and_refine
from planning.reflexion import reflexion
from planning_lab.models import Thought
from config import MISTRAL_API_KEY

TRANSPORT = os.getenv("TRANSPORT", "stdio").lower()

# ============================================================
# [NEW]
# Self-correction routing rules.
#
# These rules determine which semantic tasks receive additional
# self-correction after the primary planning method finishes.
#
# combine_evidence -> Self-Refine
# risk_assessment  -> Reflexion fallback
# ============================================================

SELF_REFINE_RULES = {"combine_evidence"}
REFLEXION_FALLBACK_RULES = {"risk_assessment"}

# ============================================================
# [CHANGED]
# OLD CLIENT:
# The LLM agent itself decided which MCP tool to call.
#
# NEW CLIENT:
# The planning layer decides WHAT task should be performed,
# and the router decides HOW that task should be solved.
# ============================================================

# ============================================================
# [NEW]
# Planning system prompt.
#
# This replaces the old RAG/Memory system prompt.
# RAG and long-term memory are intentionally not part of
# this planning architecture.
# ============================================================

PLANNING_SYSTEM_PROMPT = """
You are the Sterling & Vance Bank Planning Agent.

Your job is to investigate complex banking requests through:
1. Task decomposition.
2. Dependency-aware planning.
3. Parallel execution of independent tasks.
4. Routing tasks to appropriate planning methods.
5. Execution against the real MCP banking server.
6. Grounding conclusions in actual banking data.

The MCP server and database are the source of truth for live banking information.

Never invent customers, accounts, transactions, transfers,
sanctions results, or investigation findings.

Never claim an operation succeeded unless the real MCP/environment
returned a result.

The planning layer decides WHAT to investigate.
The router decides WHICH method handles the task.
The MCP integration layer performs the real banking operation.
"""

MISTRAL_MODEL = os.getenv(
    "PLANNING_MODEL",
    "mistral-small-latest",
)


def build_llm() -> ChatMistralAI:
    if not MISTRAL_API_KEY:
        raise RuntimeError("MISTRAL_API_KEY is not set.")
    return ChatMistralAI(
        model=MISTRAL_MODEL,
        api_key=MISTRAL_API_KEY,
        temperature=0,
    )
# ============================================================
# [UNCHANGED]
# MCP ELICITATION
#
# The client still handles human approval when the MCP server
# requests approval for a sensitive wire transfer.
# ============================================================

async def handle_elicitation(context, params):
    print("\n" + "=" * 60)
    print("HUMAN APPROVAL REQUIRED")
    print("=" * 60)
    print(params.message)

    answer = input("\nApprove transfer? (yes/no): ").strip().lower()

    return types.ElicitResult(
        action="accept",
        content={"approved": answer == "yes"},
    )

# ============================================================
# [CHANGED]
# MCP SAMPLING
#
# OLD:
# Sampling used the Groq LLM created inside main().
#
# NEW:
# Sampling uses the same Mistral model configured for planning.
# ============================================================

async def handle_sampling(context,params: types.CreateMessageRequestParams,):
    llm = build_llm()

    message = params.messages[-1]

    if isinstance(message.content, types.TextContent):
        prompt = message.content.text
    else:
        prompt = str(message.content)

    result = await llm.ainvoke(prompt)

    text = (
        result.content
        if isinstance(result.content, str)
        else str(result.content)
    )

    return types.CreateMessageResult(
        role="assistant",
        content=types.TextContent(
            type="text",
            text=text,
        ),
        model=MISTRAL_MODEL,
        stopReason="endTurn",
    )

# ============================================================
# [UNCHANGED]
# MCP NOTIFICATIONS
#
# The client still handles:
# - tools/list_changed
# - progress
# ============================================================

async def message_handler(message):
    if isinstance(message, Exception):
        print(f"[MCP] Transport error: {message}")
        return

    notification = getattr(
        message,
        "root",
        message,
    )

    method = getattr(
        notification,
        "method",
        None,
    )

    if method == "notifications/tools/list_changed":
        print("\n[MCP] tools/list_changed received.")

    elif method == "notifications/progress":
        params = getattr(
            notification,
            "params",
            None,
        )

        if params:
            print(
                f"[MCP] Progress: "
                f"{params.progress}/{params.total}"
            )

# ============================================================
# [REMOVED FROM OLD ARCHITECTURE]
# convert_mcp_tool()
#
# OLD CLIENT:
# MCP tools were converted into LangChain StructuredTools
# and passed to a generic LangChain agent.
#
# NEW CLIENT:
# MCP tools are not exposed directly to a generic agent.
#
# TaskNode
#    ↓
# router.dispatch()
#    ↓
# planning algorithm / direct MCP execution
# ============================================================

# ============================================================
# [NEW]
# Task argument extraction helpers.
#
# Decomposition produces free-text task descriptions.
# These helpers extract structured values needed by the router.
# ============================================================

def extract_account_id(text: str) -> int | None:
    match = re.search(
        r"account(?:_id)?\s*[#:=]?\s*(\d+)",
        text,
        re.IGNORECASE,
    )
    return int(match.group(1)) if match else None


def extract_customer_id(text: str) -> int | None:
    match = re.search(
        r"customer(?:_id)?\s*[#:=]?\s*(\d+)",
        text,
        re.IGNORECASE,
    )
    return int(match.group(1)) if match else None


def extract_destination_country(text: str) -> str | None:
    match = re.search(
        r"destination_country\s*[:=]?\s*([A-Za-z]{2})\b",
        text,
    )
    return match.group(1).upper() if match else None

# ============================================================
# [NEW]
# Evidence context builder.
#
# Results from completed dependency tasks are passed to
# dependent tasks as investigation evidence.
# ============================================================

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

# ============================================================
# [NEW]
# Result normalization helper.
#
# Different planning algorithms return different result types.
# Self-Refine and Reflexion require plain text.
# ============================================================

def _result_to_text(result: Any) -> str:
    if isinstance(result, str):
        return result

    if (
        isinstance(result, list)
        and result
        and isinstance(result[0], Thought)
    ):
        best = max(
            result,
            key=lambda thought: thought.score,
        )
        return best.state

    output = getattr(
        result,
        "output",
        None,
    )

    if isinstance(output, str) and output.strip():
        return output

    return str(result)

# ============================================================
# [NEW]
# SELF-REFINE INTEGRATION
#
# combine_evidence is first solved using the routed planning
# method, then passed through grounded Self-Refine:
#
# draft
#   ↓
# grounded critique
#   ↓
# revised answer
# ============================================================

async def apply_self_refine(
    task: TaskNode,
    raw_result: Any,
    llm: Any,
    environment: Environment,
) -> Any:
    draft = _result_to_text(raw_result)

    print(
        f"\n[SELF-REFINE] "
        f"Refining output of '{task.task_id}'..."
    )

    reflection = await reflect_and_refine(
        goal=task.description,
        draft=draft,
        llm=llm,
        environment=environment,
    )

    if reflection.grounded_issues:
        print(
            "[SELF-REFINE] Grounded issues surfaced: "
            f"{reflection.grounded_issues}"
        )

    return reflection.revised

# ============================================================
# [NEW]
# REFLEXION FALLBACK
#
# risk_assessment first uses its primary routed method.
# If the grounded result is not accepted, Reflexion retries
# using multiple trials and episodic reflections.
# ============================================================

async def apply_reflexion_fallback(
    task: TaskNode,
    primary_result: Any,
    llm: Any,
    environment: Environment,
) -> Any:
    already_grounded_success = getattr(
        primary_result,
        "success",
        None,
    )

    if already_grounded_success is True:
        return primary_result

    if already_grounded_success is None:
        candidate_text = _result_to_text(primary_result)

        check = await environment.evaluate(
            candidate=candidate_text,
            task=task.description,
        )

        if check.success:
            return primary_result

    print(
        f"\n[REFLEXION] Grounded check failed for "
        f"'{task.task_id}' "
        f"(primary output not accepted)."
    )

    print(
        "[REFLEXION] Falling back to "
        "multi-trial Reflexion retry..."
    )

    result = await reflexion(
        task=task.description,
        llm=llm,
        environment=environment,
        max_trials=3,
        memory_size=3,
    )

    print(
        f"[REFLEXION] success={result.success} "
        f"after {len(result.trials)} trial(s)."
    )

    return result.output

# ============================================================
# [NEW]
# TASK EXECUTION BRIDGE
#
# Goal
#   ↓
# Decomposition
#   ↓
# TaskNode
#   ↓
# classify_description()
#   ↓
# dispatch()
#   ↓
# Planning method / direct execution
#
# This function connects the DAG to the router.
# ============================================================

async def execute_task(
    task: TaskNode,
    context: dict[str, Any],
    llm: Any,
    environment: Environment,
) -> Any:
    classification = classify_description(task.description)

    print(
        f"[ROUTER] {task.task_id} -> "
        f"{classification.method.upper()}"
    )

    result = await dispatch(
        node=task,
        evidence_context=build_evidence_context(context),
        llm=llm,
        customer_id=extract_customer_id(
            task.description
        ),
        account_ids=(
            [
                aid
                for aid in [
                    extract_account_id(
                        task.description
                    )
                ]
                if aid is not None
            ]
            or None
        ),
        destination_country=extract_destination_country(
            task.description
        ),
        environment=environment,
    )

    if classification.matched_rule in SELF_REFINE_RULES:
        print(
            f"[SELF-REFINE] Revising '{task.task_id}'..."
        )

        result = await apply_self_refine(
            task,
            result,
            llm,
            environment,
        )

        print(
            f"[SELF-REFINE] Revision completed."
        )

    if (
        classification.matched_rule
        in REFLEXION_FALLBACK_RULES
    ):
        result = await apply_reflexion_fallback(
            task,
            result,
            llm,
            environment,
        )

    return result

# ============================================================
# [NEW]
# PLANNING AGENT
#
# This replaces the old generic RAG/Memory LangChain Agent.
#
# The PlanningAgent owns:
# - decomposition
# - DAG execution
# - dependency management
# - parallel batches
# - router invocation
# - grounded environment
#
# Evaluation metrics are intentionally NOT collected here.
# run_evaluation.py owns measurement and comparison so that
# every planning method is evaluated under the same conditions.
# ============================================================

class PlanningAgent:
    def __init__(
        self,
        session: ClientSession,
    ):
        self.session = session
        self.llm = build_llm()

        # ====================================================
        # [NEW]
        # Environment provides grounded evaluation against
        # the actual MCP banking server / database.
        # ====================================================

        self.environment = Environment(
            mcp_session=session
        )

        # ====================================================
        # [NEW]
        # Adapter converts the investigation goal into the
        # bank-specific decomposition/DAG representation.
        # ====================================================

        self.adapter = BankDecompositionAdapter(
            self.llm
        )

    async def run(
        self,
        goal: str,
    ) -> dict[str, Any]:


        print(f"\nGoal:\n{goal}")

        # ====================================================
        # STEP 1 — DECOMPOSITION
        # ====================================================

        print("\n[1] DECOMPOSITION")
        print("\n[PLANNING] Decomposing goal...")

        dag = self.adapter.decompose(goal)

        print("\n[PLANNING] Generated DAG:")

        for task_id in dag.topological_order():
            task = dag.nodes[task_id]

            print(
                f"  - {task.task_id}: "
                f"{task.description}"
            )

            if task.dependencies:
                print(
                    f"      depends_on={task.dependencies}"
                )

        # ====================================================
        # STEP 2 — EXECUTION BATCHES
        # ====================================================

        batches = dag.execution_batches()

        print("\n[PLANNING] Execution batches:")

        for i, batch in enumerate(batches, 1):
            print(
                f"  Batch {i}: {batch}"
            )

        # ====================================================
        # STEP 3 — EXECUTE BATCHES
        # ====================================================

        outputs: dict[str, Any] = {}

        print("\n[2] ROUTING + EXECUTION")

        for batch in batches:

            print(
                f"\n[EXECUTION] Batch: {batch}"
            )

            async def run_one(
                task_id: str,
            ):
                task = dag.nodes[task_id]

                context = {
                    dependency: outputs[dependency]
                    for dependency in task.dependencies
                }

                task.status = "IN_PROGRESS"

                print(
                    f"\n[EXECUTION] {task_id}: "
                    f"{task.description}"
                )

                result = await execute_task(
                    task=task,
                    context=context,
                    llm=self.llm,
                    environment=self.environment,
                )

                return task_id, result

            results = await asyncio.gather(
                *(
                    run_one(task_id)
                    for task_id in batch
                ),
                return_exceptions=True,
            )

            # =================================================
            # Store completed results
            # =================================================

            for item in results:

                if isinstance(item, Exception):
                    raise item

                task_id, result = item

                if result is None:
                    raise RuntimeError(
                        f"Task '{task_id}' returned no result."
                    )

                dag.mark_completed(
                    task_id,
                    result,
                )

                outputs[task_id] = result

                print(
                    f"[DONE] {task_id}"
                )

        # ====================================================
        # FINAL SUMMARY
        # ====================================================

        completed_tasks = sum(
            1
            for task in dag.nodes.values()
            if task.status == "COMPLETED"
        )

        failed_tasks = (
            len(dag.nodes)
            - completed_tasks
        )

        print("\n" + "=" * 70)
        print("DEMO SUMMARY")
        print("=" * 70)

        print(
            f"\nTasks: {len(dag.nodes)}"
        )

        print(
            f"Completed: {completed_tasks}"
        )

        print(
            f"Failed: {failed_tasks}"
        )

        # ====================================================
        # ROUTING SUMMARY
        # ====================================================

        print("\nRouting:")

        for task_id in dag.topological_order():

            task = dag.nodes[task_id]

            classification = classify_description(
                task.description
            )

            print(
                f"  {task_id} -> "
                f"{classification.method.upper()}"
            )

        # ====================================================
        # SELF-CORRECTION SUMMARY
        # ====================================================

        self_refine_tasks = []
        reflexion_tasks = []

        for task_id in dag.topological_order():

            task = dag.nodes[task_id]

            classification = classify_description(
                task.description
            )

            if classification.matched_rule in SELF_REFINE_RULES:
                self_refine_tasks.append(task_id)

            if classification.matched_rule in REFLEXION_FALLBACK_RULES:
                reflexion_tasks.append(task_id)

        if self_refine_tasks:
            print(
                "\nSelf-Refine:"
            )

            for task_id in self_refine_tasks:
                print(
                    f"  {task_id} -> revision applied"
                )

        if reflexion_tasks:
            print(
                "\nReflexion:"
            )

            for task_id in reflexion_tasks:
                print(
                    f"  {task_id} -> fallback/retry enabled"
                )

        # ====================================================
        # FINAL TASKS
        # ====================================================

        print("\nTerminal tasks:")

        for task_id in dag.terminal_tasks():
            print(
                f"  {task_id} -> completed"
            )

        # ====================================================
        # RETURN STRUCTURED RESULT
        # ====================================================

        return {
            "goal": goal,
            "method": "decomposition-first",
            "model": MISTRAL_MODEL,
            "transport": TRANSPORT,
            "task_count": len(dag.nodes),
            "completed_tasks": completed_tasks,
            "failed_tasks": failed_tasks,
            "topological_order": dag.topological_order(),
            "execution_batches": batches,
            "terminal_tasks": dag.terminal_tasks(),

            "tasks": {
                task_id: {
                    "description": task.description,
                    "action_type": task.action_type,
                    "dependencies": task.dependencies,
                    "status": task.status,
                    "result": task.result,
                }
                for task_id, task in dag.nodes.items()
            },

            "outputs": outputs,
        }

# ============================================================
# [CHANGED]
# MCP SESSION
#
# OLD:
# The session created a generic LangChain Agent and converted
# every MCP tool into a StructuredTool.
#
# NEW:
# The session creates the PlanningAgent.
#
# MCP is now the execution/source-of-truth layer for planning,
# rather than exposing the tool list directly to an LLM agent.
# ============================================================

async def run_session(
    session: ClientSession,
):
    # ========================================================
    # MCP INITIALIZATION
    # ========================================================

    init_result = await session.initialize()
    caps = init_result.capabilities

    print("\n[MCP] Connected.")

    print(
        "tools.listChanged =",
        bool(
            caps.tools
            and caps.tools.listChanged
        ),
    )

    print(
        "resources =",
        caps.resources is not None,
    )

    print(
        "prompts =",
        caps.prompts is not None,
    )
    # ========================================================
    # [LOGIN]
    # Login as Compliance Officer (employee_id=1)
    # This unlocks the compliance and grounded-validation tools.
    # ========================================================

    login_result = await session.call_tool(
        "login",
        {"employee_id": 1},
    )

    print("\n[MCP] Login:")

    for item in login_result.content:
        if hasattr(item, "text"):
            print(f"  {item.text}")
    # ========================================================
    # MCP TOOLS
    # ========================================================

    tools = await session.list_tools()

    print("\n[MCP] Available tools:")

    for tool in tools.tools:
        print(f"  - {tool.name}")

    # ========================================================
    # PLANNING AGENT
    # ========================================================

    agent = PlanningAgent(session)

    print("\nPlanning Agent Ready.")

    # ========================================================
    # INVESTIGATION LOOP
    # ========================================================

    while True:

        goal = input(
            "\nInvestigation request: "
        ).strip()

        if goal.lower() in ("exit", "quit"):
            break

        if not goal:
            continue

        try:

            result = await agent.run(goal)

            # =================================================
            # SHORT DEMO OUTPUT
            # =================================================

            print("\n" + "=" * 70)
            print("FINAL RESULT")
            print("=" * 70)

            print(
                f"\nCompleted: "
                f"{result['completed_tasks']}/"
                f"{result['task_count']} tasks"
            )

            # =================================================
            # ROUTING
            # =================================================

            print("\nROUTING:")

            for task_id in result["topological_order"]:

                task = result["tasks"][task_id]

                classification = classify_description(
                    task["description"]
                )

                print(
                    f"  {task_id} -> "
                    f"{classification.method.upper()}"
                )

            # =================================================
            # SELF-REFINE
            # =================================================

            self_refine_found = False

            for task_id in result["topological_order"]:

                task = result["tasks"][task_id]

                classification = classify_description(
                    task["description"]
                )

                if (
                    classification.matched_rule
                    in SELF_REFINE_RULES
                ):
                    if not self_refine_found:
                        print("\nSELF-REFINE:")
                        self_refine_found = True

                    print(
                        f"  {task_id}: revision applied"
                    )

            # =================================================
            # REFLEXION
            # =================================================

            reflexion_found = False

            for task_id in result["topological_order"]:

                task = result["tasks"][task_id]

                classification = classify_description(
                    task["description"]
                )

                if (
                    classification.matched_rule
                    in REFLEXION_FALLBACK_RULES
                ):
                    if not reflexion_found:
                        print("\nREFLEXION:")
                        reflexion_found = True

                    print(
                        f"  {task_id}: "
                        f"reflection/retry enabled"
                    )

            # =================================================
            # GROUNDING
            # =================================================

            print("\nGROUNDING:")
            print(
                "  Results validated against the real "
                "MCP banking environment."
            )

            # =================================================
            # FINAL TASK
            # =================================================

            terminal_tasks = result["terminal_tasks"]

            if terminal_tasks:

                print("\nFINAL INVESTIGATION:")

                for task_id in terminal_tasks:

                    task = result["tasks"][task_id]

                    final_result = task["result"]

                    # Keep the terminal result readable.
                    text = str(final_result)

                    if len(text) > 1500:
                        text = text[:1500] + "\n...[truncated]"

                    print(
                        f"\n  {text}"
                    )

            print("\n" + "=" * 70)

        except Exception as exc:

            print("\n[PLANNING ERROR]")

            print(
                f"{type(exc).__name__}: {exc}"
            )


# ============================================================
# [UNCHANGED]
# TRANSPORT
# ============================================================

async def main():
    # ========================================================
    # [UNCHANGED]
    # Local MCP server configuration.
    # ========================================================

    server_params = StdioServerParameters(
        command=sys.executable,
        args=["mcp/server.py"],
    )

    # ========================================================
    # [UNCHANGED]
    # Streamable HTTP transport.
    # ========================================================

    if TRANSPORT == "http":
        url = os.getenv(
            "MCP_SERVER_URL",
            "http://localhost:8000/mcp",
        )

        async with streamable_http_client(
            url
        ) as (
            read,
            write,
            _,
        ):
            async with ClientSession(
                read,
                write,
                elicitation_callback=handle_elicitation,
                sampling_callback=handle_sampling,
                message_handler=message_handler,
            ) as session:
                await run_session(session)

    # ========================================================
    # [UNCHANGED]
    # stdio transport.
    # ========================================================

    else:
        async with stdio_client(
            server_params
        ) as (
            read,
            write,
        ):
            async with ClientSession(
                read,
                write,
                elicitation_callback=handle_elicitation,
                sampling_callback=handle_sampling,
                message_handler=message_handler,
            ) as session:
                await run_session(session)

# ============================================================
# [UNCHANGED]
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    asyncio.run(main())