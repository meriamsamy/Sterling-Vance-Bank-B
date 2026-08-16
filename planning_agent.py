import asyncio
import os
from pathlib import Path
import sys
from datetime import datetime
import json

from dotenv import load_dotenv

load_dotenv()
sys.path.append(str(Path(__file__).resolve().parent.parent))

from typing import Any
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
from langchain_mistralai import ChatMistralAI
from config import MISTRAL_API_KEY

# ============================================================
# planning (No RAG, No Memory)
# ============================================================
from planning.decomposition import BankDecompositionAdapter
from planning.environment import Environment
from planning.orchestrator import run_investigation
from planning.self_refine import reflect_and_refine
from planning.reflexion import reflexion
from planning_eval.metrics import MetricsTracker

# ============================================================
# CONFIGURATION
# ============================================================
TRANSPORT = os.getenv("TRANSPORT", "stdio").lower()
MISTRAL_MODEL = os.getenv("PLANNING_MODEL", "mistral-small-latest")
SELF_REFINE_TASKS = {"combine_evidence"}
REFLEXION_FALLBACK_TASKS = {"risk_assessment"}

metrics_tracker = MetricsTracker()

# ============================================================
# SYSTEM PROMPT FOR PLANNING AGENT
# ============================================================
SYSTEM_PROMPT = """
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

Do not use RAG or long-term memory.
"""

# ============================================================
# LLM BUILDER
# ============================================================
def build_llm() -> ChatMistralAI:
    if not MISTRAL_API_KEY:
        raise RuntimeError("MISTRAL_API_KEY is not set.")

    return ChatMistralAI(
        model=MISTRAL_MODEL,
        api_key=MISTRAL_API_KEY,
        temperature=0,
        callbacks=[metrics_tracker],
    )


# ============================================================
# ELICITATION / HUMAN APPROVAL
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
# REFINEMENT & REFLEXION WRAPPERS
# ============================================================
async def apply_self_refine(
    task,
    raw_result: Any,
    llm: Any,
    environment: Environment,
) -> Any:
    draft = (
        raw_result
        if isinstance(raw_result, str)
        else str(raw_result)
    )

    reflection = await reflect_and_refine(
        goal=task.description,
        draft=draft,
        llm=llm,
        environment=environment,
    )

    return reflection.revised


async def apply_reflexion_fallback(
    task,
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

    result = await reflexion(
        task=task.description,
        llm=llm,
        environment=environment,
        max_trials=3,
        memory_size=3,
    )

    return result.output


# ============================================================
# PLANNING AGENT
# ============================================================
class PlanningAgent:
    def __init__(
        self,
        session: ClientSession,
        llm: ChatMistralAI,
    ):
        # The Planning Agent owns the MCP connection.
        self.session = session
        self.llm = llm

        # The Environment uses the SAME MCP session.
        self.environment = Environment(
            mcp_session=session
        )

        self.adapter = BankDecompositionAdapter(
            self.llm
        )

    async def run(
        self,
        goal: str,
        dynamic: bool = True,
        save_artifact: bool = True,
    ) -> dict[str, Any]:

        metrics_tracker.reset()

        start_time = datetime.now()

        # --------------------------------------------------------
        # 1. Planning Agent performs decomposition.
        # --------------------------------------------------------
        dag = self.adapter.decompose(goal)

        # --------------------------------------------------------
        # 2. Orchestrator executes the already-created DAG.
        #
        # The SAME ClientSession owned by the Planning Agent is
        # passed down to dispatch() and the Environment.
        # --------------------------------------------------------
        customer_id = None

        result = await run_investigation(
            dag=dag,
            adapter=self.adapter,
            session=self.session,
            llm=self.llm,
            environment=self.environment,
            dynamic=dynamic,
            save_artifact=save_artifact,
            customer_id=customer_id,
        )

        latency = (
            datetime.now() - start_time
        ).total_seconds()

        metrics = metrics_tracker.snapshot()

        completed_tasks = sum(
            1
            for task in dag.nodes.values()
            if task.status == "COMPLETED"
        )

        return {
            "goal": goal,
            "method": (
                "dynamic-interleaved-dag-routing"
                if dynamic
                else "decomposition-first-dag-routing"
            ),
            "model": MISTRAL_MODEL,
            "latency_seconds": round(
                latency,
                6,
            ),
            "metrics": {
                **metrics,
                "completed_tasks": completed_tasks,
                "llm_calls": result.llm_calls,
            },
            "order_executed": result.order_executed,
            "dynamic_task_injected": (
                result.dynamic_task_injected
            ),
            "routing_trace": result.trace.as_payload(),
            "outputs": {
                task_id: dag.nodes[task_id].result
                for task_id in result.order_executed
            },
        }


# ============================================================
# MAIN APPLICATION LOOP
# ============================================================
async def main():
    llm = build_llm()

    async def handle_sampling(
        context,
        params: types.CreateMessageRequestParams,
    ):
        message = params.messages[-1]

        prompt = (
            message.content.text
            if isinstance(
                message.content,
                types.TextContent,
            )
            else str(message.content)
        )

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

    async def message_handler(message):
        if isinstance(message, Exception):
            print(
                f"[message_handler] transport error: {message}"
            )

    server_params = StdioServerParameters(
        command="python",
        args=["mcp/server.py"],
    )

    async def run_session(session):
        await session.initialize()

        print(
            f"\n=== Sterling & Vance Bank Planning Agent "
            f"Connected (Using Mistral: {MISTRAL_MODEL}) ==="
        )

        # The Planning Agent owns this MCP session.
        agent = PlanningAgent(
            session,
            llm,
        )

        while True:
            user_goal = input(
                "\nInvestigation Request "
                "(e.g., Investigate customer X's financial activity): "
            ).strip()

            if user_goal.lower() in ("exit", "quit"):
                break

            if not user_goal:
                continue

            try:
                print(
                    "\n[Planning Agent] "
                    "Decomposing request and initiating Investigation DAG..."
                )

                result = await agent.run(
                    user_goal,
                    dynamic=True,
                    save_artifact=True,
                )

                print(
                    "\n"
                    + "=" * 40
                    + " INVESTIGATION REPORT "
                    + "=" * 40
                )

                print(
                    json.dumps(
                        result,
                        indent=2,
                        ensure_ascii=False,
                    )
                )

                print("=" * 102)

            except Exception as exc:
                print(
                    f"\n[Error during execution]: {exc}"
                )

    if TRANSPORT == "http":
        from mcp.client.streamable_http import (
            streamablehttp_client,
        )

        url = os.getenv(
            "MCP_SERVER_URL",
            "http://localhost:8000/mcp",
        )

        async with streamablehttp_client(url) as (
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

    else:
        async with stdio_client(
            server_params
        ) as (read, write):

            async with ClientSession(
                read,
                write,
                elicitation_callback=handle_elicitation,
                sampling_callback=handle_sampling,
                message_handler=message_handler,
            ) as session:
                await run_session(session)


if __name__ == "__main__":
    asyncio.run(main())

