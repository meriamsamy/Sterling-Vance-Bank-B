import asyncio
import os
from pathlib import Path
import sys
from datetime import datetime
import json

from dotenv import load_dotenv

load_dotenv()
sys.path.append(str(Path(__file__).resolve().parent.parent))

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
from langchain_groq import ChatGroq
from langchain_core.tools import StructuredTool
from langchain.agents import create_agent
from langchain_core.messages import SystemMessage, ToolMessage, convert_to_messages
from pydantic import BaseModel, Field
from config import API_KEY
from rag.hybrid_rag import hybrid_rag

# ============================================================
# CONFIGURATION
# ============================================================

ACTIVE_CONTEXT_STRATEGY = os.getenv("CONTEXT_STRATEGY", "masking")
# ============================================================
# SYSTEM PROMPT
# ============================================================

SYSTEM_PROMPT = """
You are a banking assistant.

You have access to:

1. Hybrid RAG
   - Retrieved knowledge from the bank's document knowledge base.
   - Hybrid RAG is ALWAYS executed before every user request.

2. MCP banking tools
   - login
   - get_account
   - wire_transfer_initiate
   - batch_sanctions_scan

3. Memory systems
   - Short-term conversation memory
   - Scratchpad working memory
   - Long-term episodic memory
   - Long-term semantic/consolidated memory

Rules:

- Hybrid RAG is always executed before answering every user request.
- Use retrieved RAG knowledge as supporting evidence when relevant.
- If RAG retrieves no relevant documents, do not invent bank policy.
- Always use MCP tools for live banking operations.
- Never claim that a banking operation succeeded unless the MCP tool
  returned a successful result.
- Retrieved RAG knowledge must never override actual MCP tool results.
- Use short-term memory to understand the current conversation.
- Use long-term memory when previous transactions, transaction history,
  suspicious patterns, fraud patterns, or previous events are relevant.
- Use the scratchpad as internal working state.
- wire_transfer_initiate handles compliance holds and human approval internally.
- Call wire_transfer_initiate directly for transfer requests.
- Do not ask the user for transfer approval yourself.
- If an MCP tool returns an error, report the failure plainly.
"""

# ============================================================
# ELICITATION
# ============================================================

async def handle_elicitation(context, params):
    print("\n--- HUMAN APPROVAL REQUIRED ---")
    print(params.message)
    answer = input("Approve transfer? (yes/no): ")
    return types.ElicitResult(action="accept", content={"approved": answer.lower() == "yes"})

# ============================================================
# MCP TOOL SCHEMAS
# ============================================================

class LoginArgs(BaseModel):
    employee_id: int = Field(description="employee_id from employees table")

class GetAccountArgs(BaseModel):
    account_id: int = Field(description="account_id to look up")

class WireTransferArgs(BaseModel):
    employee_id: int
    source_account_id: int
    destination_account_num: str
    destination_country: str
    amount: float

class BatchScanArgs(BaseModel):
    employee_id: int

SCHEMAS = {
    "login": LoginArgs,
    "get_account": GetAccountArgs,
    "wire_transfer_initiate": WireTransferArgs,
    "batch_sanctions_scan": BatchScanArgs,
}

# ============================================================
# LONG-TERM MEMORY
#
# Real retrieval, backed by the actual EpisodicMemory / SemanticMemory
# stores (db/bank.db, memory/episodic_memory/, memory/semantic_memory/)
# instead of an in-process placeholder. Episodes are written only by
# the Promote-or-Drop Router when short-term memory overflows (see
# route_and_log below); semantic facts are written only by the
# periodic consolidation pass (memory/semantic_memory/consolidation.py).
# This function never writes to either store - it only reads.
# ============================================================

_LONG_TERM_MEMORY_KEYWORDS = (
    "transfer", "transaction", "fraud", "suspicious",
    "history", "pattern", "previous", "last", "risk",
)


def retrieve_long_term_memory(query: str) -> str:
    """
    Cheap keyword gate first (avoids a DB round-trip on requests that
    have nothing to do with history/risk), then a real read against
    both stores INDEPENDENTLY - episodic and semantic memory don't
    gate each other, since a customer can have a consolidated
    semantic risk_level fact with no recent episodes (or vice versa),
    and either store being empty must never silently hide the other.
    Whatever comes back still has to pass verify_long_term_memory()'s
    Self-RAG-style check before it ever reaches the agent - this
    function only retrieves, it does not decide relevance.
    """
    from memory.episodic_memory.episodic_memory import EpisodicMemory
    from memory.semantic_memory.semantic_memory import SemanticMemory

    query_lower = query.lower()
    if not any(keyword in query_lower for keyword in _LONG_TERM_MEMORY_KEYWORDS):
        return ""

    episodic = EpisodicMemory()
    semantic = SemanticMemory()

    episodes = episodic.get_recent_episodes(limit=10)
    facts = semantic.get_all_active_facts("customer", "risk_level")

    if not episodes and not facts:
        return ""

    memory_parts = []

    if episodes:
        memory_parts.append("Recent Episodic Memory:")
        for episode in episodes:
            memory_parts.append(
                f"- Episode #{episode['episode_id']} ({episode['event_type']}): "
                f"{episode['summary']}"
            )

    if facts:
        memory_parts.append("\nConsolidated Semantic Memory:")
        for fact in facts:
            memory_parts.append(
                f"- Customer {fact['entity_id']}: risk_level={fact['fact_value']} "
                f"(version {fact['version']})"
            )

    return "\n".join(memory_parts)


def route_and_log(candidates, scratchpad):
    """
    The route_fn handed to ShortTermMemory.add_message_with_routing()
    and to the STEP 11 bulk-overflow handling below. Delegates the
    actual forget-vs-promote decision to promote_or_drop_router.py
    (which never writes to semantic memory itself - only to
    episodic_memory and promote_or_drop_log), and mirrors every
    decision into the scratchpad so it's visible in the turn's
    working state, not just in the DB log.
    """
    from memory.episodic_memory.promote_or_drop_router import route_overflow

    if not candidates:
        return []

    decisions = route_overflow(candidates)

    for decision in decisions:
        print(
            f"[MEMORY] {decision['decision'].upper()} "
            f"(episode_id={decision.get('episode_id')})"
        )
        print(f"[MEMORY] Reason: {decision['reason']}")

        scratchpad.add_note(
            f"Memory routing: {decision['decision']} "
            f"(episode_id={decision.get('episode_id')})"
        )

    return decisions

# ============================================================
# MCP TOOL WRAPPER
# ============================================================

def convert_mcp_tool(session, mcp_tool):
    async def progress_handler(progress: float, total: float | None, message: str | None = None):
        if total:
            print(f"[progress] {int(progress)}/{int(total)} scanned", end="\r")
        else:
            print(f"[progress] {progress}", end="\r")

    async def call(**kwargs):
        if mcp_tool.name == "batch_sanctions_scan":
            result = await session.call_tool(mcp_tool.name, arguments=kwargs, progress_callback=progress_handler)
        else:
            result = await session.call_tool(mcp_tool.name, arguments=kwargs)

        text = "\n".join(item.text for item in result.content if hasattr(item, "text"))

        if result.isError:
            return f"TOOL ERROR: {text}"

        return text

    return StructuredTool.from_function(
        coroutine=call,
        name=mcp_tool.name,
        description=mcp_tool.description,
        args_schema=SCHEMAS[mcp_tool.name],
    )

# ============================================================
# AGENT
# ============================================================

def build_agent(llm, tools):
    llm_with_tools = llm.bind_tools(tools)
    return create_agent(model=llm_with_tools, tools=tools, system_prompt=SYSTEM_PROMPT)

# ============================================================
# LONG-TERM MEMORY — POST-RETRIEVAL VERIFICATION
# ============================================================

class MemoryVerificationResult(BaseModel):
    episodic_relevant: bool = False
    semantic_relevant: bool = False
    supported: bool = False
    reason: str = ""

async def verify_long_term_memory(llm, query, memory_context):
    verification_prompt = f"""
You are a memory verification component for a banking AI assistant.

Your job is to verify whether retrieved long-term memory is relevant
and actually supports the user's current request.

USER REQUEST:
{query}

RETRIEVED LONG-TERM MEMORY:
{memory_context}

Evaluate the memory in two parts:

1. episodic_relevant:
   True if the retrieved episodic events are relevant to the user's request.

2. semantic_relevant:
   True if the retrieved consolidated/semantic facts are relevant to the user's request.

3. supported:
   True ONLY if the retrieved memory provides useful evidence for answering the request.

Do NOT mark memory as supported merely because it contains similar words.
It must actually help answer the request.

Return ONLY valid JSON in this exact format:

{{
    "episodic_relevant": true,
    "semantic_relevant": true,
    "supported": true,
    "reason": "short explanation"
}}
"""

    result = await llm.ainvoke(verification_prompt)
    text = result.content if isinstance(result.content, str) else str(result.content)

    try:
        data = json.loads(text)
        return MemoryVerificationResult(
            episodic_relevant=bool(data.get("episodic_relevant", False)),
            semantic_relevant=bool(data.get("semantic_relevant", False)),
            supported=bool(data.get("supported", False)),
            reason=str(data.get("reason", "")),
        )
    except Exception as exc:
        return MemoryVerificationResult(
            episodic_relevant=False,
            semantic_relevant=False,
            supported=False,
            reason=f"Memory verification failed: {type(exc).__name__}",
        )

# ============================================================
# LONG-TERM MEMORY — POST-GENERATION VERIFICATION
# ============================================================

async def verify_memory_answer(llm, query, memory_context, generated_answer):
    prompt = f"""
You are a strict verification component for a banking AI assistant.

Your ONLY job is to verify claims that depend on the retrieved long-term memory.

USER REQUEST:
{query}

VERIFIED LONG-TERM MEMORY:
{memory_context}

GENERATED ANSWER:
{generated_answer}

Rules:

- supported = true ONLY if important claims attributed to long-term memory are supported by the retrieved memory.
- If the answer contains an important claim from long-term memory that is not supported by the memory, set supported = false.
- Do not use general world knowledge.
- Do not assume missing information.
- Do not evaluate claims supported by MCP tool results.
- Do not evaluate claims supported by Hybrid RAG documents.
- Do not evaluate claims supported by the current conversation.
- This verification is specifically checking long-term memory grounding.

Return ONLY valid JSON:

{{
    "supported": true,
    "reason": "short explanation"
}}
"""

    result = await llm.ainvoke(prompt)
    text = result.content if isinstance(result.content, str) else str(result.content)

    try:
        data = json.loads(text)
        return {
            "supported": bool(data.get("supported", False)),
            "reason": str(data.get("reason", "")),
        }
    except Exception as exc:
        return {
            "supported": False,
            "reason": f"Memory answer verification failed: {type(exc).__name__}",
        }

# ============================================================
# MAIN
# ============================================================

async def main():
    transport = os.getenv("TRANSPORT", "stdio").lower()

    # ========================================================
    # LLM
    # ========================================================

    llm = ChatGroq(groq_api_key=API_KEY, model="openai/gpt-oss-20b", temperature=0.1)

    # ========================================================
    # SAMPLING
    # ========================================================

    async def handle_sampling(context, params: types.CreateMessageRequestParams):
        result = await llm.ainvoke(params.messages[-1].content.text)
        text = result.content if isinstance(result.content, str) else "".join(block.get("text", "") for block in result.content if isinstance(block, dict))

        return types.CreateMessageResult(
            role="assistant",
            content=types.TextContent(type="text", text=text),
            model="gpt-oss-20b",
            stopReason="endTurn",
        )

    # ========================================================
    # NOTIFICATIONS
    # ========================================================

    tools_ref = {"dirty": False}

    async def message_handler(message):
        if isinstance(message, Exception):
            print(f"[message_handler] transport error: {message}")
            return

        notif = getattr(message, "root", message)
        method = getattr(notif, "method", None)

        if method == "notifications/tools/list_changed":
            print("\n[notification] tools/list_changed received")
            tools_ref["dirty"] = True
        elif method == "notifications/progress":
            p = notif.params
            print(f"[progress] {p.progress}/{p.total}", end="\r")

    # ========================================================
    # MCP SERVER
    # ========================================================

    server_params = StdioServerParameters(command="python", args=["mcp_server/server.py"])

    # ========================================================
    # SESSION
    # ========================================================

    async def run_session(session):
        init_result = await session.initialize()
        caps = init_result.capabilities

        print("\nMCP Connected.")
        print(f"tools.listChanged = {bool(caps.tools and caps.tools.listChanged)}")
        print(f"resources = {caps.resources is not None}")
        print(f"prompts = {caps.prompts is not None}")

        # ====================================================
        # RESOURCES
        # ====================================================

        policy_text = ""

        if caps.resources is not None:
            resources = await session.list_resources()

            for resource in resources.resources:
                print(f"[resource] {resource.name} ({resource.uri})")

            if resources.resources:
                policy = await session.read_resource(resources.resources[0].uri)
                policy_text = policy.contents[0].text

        # ====================================================
        # PROMPTS
        # ====================================================

        if caps.prompts is not None:
            prompts = await session.list_prompts()

            for prompt in prompts.prompts:
                print(f"[prompt] {prompt.name}: {prompt.description}")

        # ====================================================
        # MCP TOOLS
        # ====================================================

        mcp_tools = await session.list_tools()
        print("\nAvailable MCP Tools:", [tool.name for tool in mcp_tools.tools])

        tools = [convert_mcp_tool(session, tool) for tool in mcp_tools.tools]
        print("\nAgent Tools:", [tool.name for tool in tools])

        agent = build_agent(llm, tools)
        print("\nAgent Ready")

        # ====================================================
        # MEMORY SYSTEMS
        # ====================================================

        from memory.short_term_memory.short_term_memory import ShortTermMemory
        from memory.short_term_memory.scratchpad import Scratchpad
        from memory.context_strategies.context_manager import ContextManager

        short_term_memory = ShortTermMemory(max_messages=20)
        scratchpad = Scratchpad()
        context_manager = ContextManager()

        # ShortTermMemory.add_message_with_routing() refuses to evict
        # anything without an explicit route_fn - this is the one
        # route_fn used by every add_message call site below, so
        # overflow is always handled the same way, not just at the
        # one place someone remembered to wire it up.
        def route_fn(candidates):
            return route_and_log(candidates, scratchpad)

        # ====================================================
        # MCP RESOURCE → SHORT-TERM MEMORY
        # ====================================================

        if policy_text:
            short_term_memory.add_message_with_routing(
                "user", f"[Bank Policy Reference]\n\n{policy_text}", route_fn=route_fn
            )
            short_term_memory.add_message_with_routing(
                "assistant", "Policy reference loaded.", route_fn=route_fn
            )

        # ====================================================
        # LIVE LOOP
        # ====================================================

        while True:
            user = input("\nRequest: ")

            if user.lower() in ("exit", "quit"):
                break

            # =================================================
            # STEP 1 — USER → SHORT-TERM MEMORY
            # =================================================

            short_term_memory.add_message_with_routing("user", user, route_fn=route_fn)

            # =================================================
            # STEP 2 — SCRATCHPAD
            # =================================================

            scratchpad.set_goal(user)
            scratchpad.set_current_step("Retrieving context")

            # =================================================
            # STEP 3 — SHORT-TERM CONTEXT
            # =================================================

            raw_context = context_manager.process(ACTIVE_CONTEXT_STRATEGY, short_term_memory.get_messages())
            context_messages = []

            for message in raw_context:
                if isinstance(message, dict):
                    if message.get("role") in ("tool", "function"):
                        message.setdefault("tool_call_id", "fallback_call_id")
                        message.setdefault("name", "unknown_tool")
                    context_messages.extend(convert_to_messages([message]))
                elif isinstance(message, ToolMessage):
                    if not getattr(message, "tool_call_id", None):
                        message.tool_call_id = "fallback_call_id"
                    if not getattr(message, "name", None):
                        message.name = "unknown_tool"
                    context_messages.append(message)
                else:
                    context_messages.append(message)

            # =================================================
            # STEP 4 — HYBRID RAG
            # ALWAYS RUNS
            # =================================================

            scratchpad.set_current_step("Running Hybrid RAG retrieval")
            print("\n[HYBRID RAG] Searching...")

            rag_result = hybrid_rag(user)

            print("[HYBRID RAG]")
            print("Status:", rag_result.get("status", "UNKNOWN"))
            print("Documents:", rag_result.get("documents_used", 0))

            retrieved_context = rag_result.get("context", "")

            if retrieved_context:
                context_messages.insert(
                    0,
                    SystemMessage(
                        content="[Hybrid RAG Retrieved Knowledge]\n\n" + retrieved_context + "\n\nUse this retrieved knowledge as supporting evidence. It must not override actual MCP tool results."
                    ),
                )
            else:
                context_messages.insert(
                    0,
                    SystemMessage(content="[Hybrid RAG Result]\nNo relevant bank documents were retrieved for this request."),
                )

            # =================================================
            # STEP 5 — LONG-TERM MEMORY
            # =================================================

            scratchpad.set_current_step("Retrieving long-term memory")
            long_term_context = retrieve_long_term_memory(user)

            if long_term_context:
                print("[LONG-TERM MEMORY] Relevant memories found.")

                memory_verification = await verify_long_term_memory(
                    llm=llm,
                    query=user,
                    memory_context=long_term_context,
                )

                print(f"[LONG-TERM MEMORY] Episodic relevant: {memory_verification.episodic_relevant}")
                print(f"[LONG-TERM MEMORY] Semantic relevant: {memory_verification.semantic_relevant}")
                print(f"[LONG-TERM MEMORY] Supported: {memory_verification.supported}")
                print(f"[LONG-TERM MEMORY] Reason: {memory_verification.reason}")

                if memory_verification.supported:
                    print("[LONG-TERM MEMORY] Verification PASSED.")
                    context_messages.insert(
                        0,
                        SystemMessage(
                            content="[Verified Long-Term Memory]\n\n" + long_term_context + "\n\nThis memory was verified as relevant to the current request."
                        ),
                    )
                else:
                    print("[LONG-TERM MEMORY] Verification FAILED.")
                    print("[LONG-TERM MEMORY] Memory will NOT be provided to the agent.")
            else:
                print("[LONG-TERM MEMORY] No relevant memories found.")
                memory_verification = MemoryVerificationResult(
                    episodic_relevant=False,
                    semantic_relevant=False,
                    supported=False,
                    reason="No memory retrieved.",
                )

            # =================================================
            # STEP 6 — SCRATCHPAD CONTEXT
            # =================================================

            scratchpad_state = scratchpad.get_state()
            scratchpad_context = (
                "[Internal Scratchpad State]\n"
                f"Goal: {scratchpad_state['goal']}\n"
                f"Current Step: {scratchpad_state['current_step']}\n"
                f"Notes: {', '.join(scratchpad_state['notes'])}"
            )

            context_messages.insert(0, SystemMessage(content=scratchpad_context))

            # =================================================
            # STEP 7 — AGENT
            # =================================================

            scratchpad.set_current_step("Calling agent")
            response = await agent.ainvoke({"messages": context_messages})

            # =================================================
            # STEP 8 — MEMORY ANSWER VERIFICATION
            # =================================================

            generated_answer = response["messages"][-1].content
            final_response = response
            # Tracks whichever message list was actually sent to the
            # agent for the response we're keeping - context_messages
            # normally, or fallback_context_messages if the verified
            # long-term memory got stripped out and the agent was
            # re-invoked below. STEP 9 needs this exact list (not
            # context_messages) to correctly slice out only the
            # messages the agent generated this turn.
            final_context_messages = context_messages

            if long_term_context and memory_verification.supported:
                print("\n[LONG-TERM MEMORY] Verifying generated answer...")

                answer_verification = await verify_memory_answer(
                    llm=llm,
                    query=user,
                    memory_context=long_term_context,
                    generated_answer=generated_answer,
                )

                print(f"[LONG-TERM MEMORY] Answer supported: {answer_verification['supported']}")
                print(f"[LONG-TERM MEMORY] Reason: {answer_verification['reason']}")

                if answer_verification["supported"]:
                    print("[LONG-TERM MEMORY] Answer verification PASSED.")
                else:
                    print("[LONG-TERM MEMORY] Answer verification FAILED.")
                    print("[LONG-TERM MEMORY] Original answer will NOT be shown.")
                    print("[LONG-TERM MEMORY] Regenerating without long-term memory...")

                    fallback_context_messages = [
                        message for message in context_messages
                        if not (
                            isinstance(message, SystemMessage)
                            and message.content.startswith("[Verified Long-Term Memory]")
                        )
                    ]

                    final_response = await agent.ainvoke({"messages": fallback_context_messages})
                    generated_answer = final_response["messages"][-1].content
                    final_context_messages = fallback_context_messages
                    print("[LONG-TERM MEMORY] Fallback answer generated without long-term memory.")
            else:
                print("[LONG-TERM MEMORY] Answer verification skipped (no verified memory used).")

            # =================================================
            # STEP 9 — NEW MESSAGES GENERATED THIS TURN
            # =================================================
            #
            # final_context_messages is whichever input list actually
            # produced final_response (context_messages, or
            # fallback_context_messages after a failed verification -
            # they can differ in length, so the offset MUST come from
            # whichever one was really used, not always context_messages).
            #
            # This slice is also what keeps STEP 11 architecturally
            # correct: new_messages contains only what the agent itself
            # generated (tool calls, tool results, the final answer) -
            # never the RAG / long-term-memory / scratchpad
            # SystemMessages that were injected into the *input*, and
            # never messages that were already sitting in
            # short_term_memory before this turn.

            new_messages = final_response["messages"][len(final_context_messages):]

            for message in new_messages:
                tool_name = getattr(message, "name", None)
                if tool_name:
                    scratchpad.add_note(f"Tool call: {tool_name}")

            # =================================================
            # STEP 10 — OUTPUT
            # =================================================

            print("\nAssistant:")
            print(final_response["messages"][-1].content)

            # =================================================
            # STEP 11 — SAVE CONVERSATION
            # =================================================
            #
            # Only the messages generated THIS turn (new_messages) are
            # added to short-term memory - never the full
            # final_response["messages"] list, which also contains the
            # injected RAG/long-term-memory/scratchpad context and the
            # messages short-term memory already had before this turn.
            #
            # Each message is added one at a time through
            # add_normalized_message_with_routing(), so if adding it
            # would overflow short-term memory, exactly the one real
            # oldest message gets routed through the Promote-or-Drop
            # Router before it's evicted - never a message that was
            # already routed earlier, and never a bulk re-routing pass.

            for message in new_messages:
                normalized = short_term_memory._normalize(message)
                short_term_memory.add_normalized_message_with_routing(
                    normalized, route_fn=route_fn
                )

            # =================================================
            # STEP 12 — RESET SCRATCHPAD
            # =================================================

            scratchpad.set_current_step("Waiting for next request")
            print("\n[scratchpad]", scratchpad.get_state())

            # =================================================
            # STEP 13 — REFRESH MCP TOOLS
            # =================================================

            if tools_ref["dirty"]:
                mcp_tools = await session.list_tools()
                tools = [convert_mcp_tool(session, tool) for tool in mcp_tools.tools]
                agent = build_agent(llm, tools)
                tools_ref["dirty"] = False
                print("Client updated its tool list:", [tool.name for tool in tools])

    # ========================================================
    # TRANSPORT
    # ========================================================

    if transport == "http":
        from mcp.client.streamable_http import streamablehttp_client

        url = os.getenv("MCP_SERVER_URL", "http://localhost:8000/mcp")

        async with streamablehttp_client(url) as (read, write, _):
            async with ClientSession(
                read,
                write,
                elicitation_callback=handle_elicitation,
                sampling_callback=handle_sampling,
                message_handler=message_handler,
            ) as session:
                await run_session(session)
    else:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(
                read,
                write,
                elicitation_callback=handle_elicitation,
                sampling_callback=handle_sampling,
                message_handler=message_handler,
            ) as session:
                await run_session(session)

# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    asyncio.run(main())