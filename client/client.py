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

ACTIVE_CONTEXT_STRATEGY = os.getenv("CONTEXT_STRATEGY", "zone")

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
# ============================================================

class IntegratedMemorySystem:
    def __init__(self):
        self.episodes = []
        self.facts = {}

    def log_transfer(self, employee_id, source_account_id, amount, target_account, destination_country, result_text, is_suspicious=False):
        episode = {
            "type": "wire_transfer",
            "employee_id": employee_id,
            "source_account_id": source_account_id,
            "amount": amount,
            "target_account": target_account,
            "destination_country": destination_country,
            "result": result_text,
            "is_suspicious": is_suspicious,
            "timestamp": datetime.now().isoformat(),
        }
        self.episodes.append(episode)
        print("\n[LONG-TERM MEMORY] Transfer episode stored.")
        self.consolidate(employee_id)

    def consolidate(self, employee_id):
        transfers = [
            episode for episode in self.episodes
            if episode["employee_id"] == employee_id and episode["type"] == "wire_transfer"
        ]
        suspicious_count = sum(1 for transfer in transfers if transfer["is_suspicious"])

        if suspicious_count >= 3:
            self.facts[f"employee_{employee_id}_fraud_pattern"] = {
                "type": "fraud_pattern",
                "employee_id": employee_id,
                "suspicious_transfers": suspicious_count,
                "timestamp": datetime.now().isoformat(),
            }
            print("[LONG-TERM MEMORY] Fraud pattern consolidated.")

    def retrieve_relevant_memory(self, query):
        query_lower = query.lower()
        keywords = ["transfer", "transaction", "fraud", "suspicious", "history", "pattern", "previous", "last"]

        if not any(keyword in query_lower for keyword in keywords):
            return ""

        relevant_episodes = self.episodes[-5:]
        relevant_facts = list(self.facts.values())

        if not relevant_episodes and not relevant_facts:
            return ""

        memory_parts = []

        if relevant_episodes:
            memory_parts.append("Recent Episodic Memory:")
            for episode in relevant_episodes:
                memory_parts.append(str(episode))

        if relevant_facts:
            memory_parts.append("\nConsolidated Semantic Memory:")
            for fact in relevant_facts:
                memory_parts.append(str(fact))

        return "\n".join(memory_parts)

# ============================================================
# MCP TOOL WRAPPER
# ============================================================

def convert_mcp_tool(session, mcp_tool, memory_system):
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

        if mcp_tool.name == "wire_transfer_initiate":
            suspicious_keywords = ["suspicious", "fraud", "sanction", "compliance", "hold", "review", "risk"]
            is_suspicious = any(keyword in text.lower() for keyword in suspicious_keywords)

            memory_system.log_transfer(
                employee_id=kwargs["employee_id"],
                source_account_id=kwargs["source_account_id"],
                amount=kwargs["amount"],
                target_account=kwargs["destination_account_num"],
                destination_country=kwargs["destination_country"],
                result_text=text,
                is_suspicious=is_suspicious,
            )

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
    # LONG-TERM MEMORY
    # ========================================================

    memory_system = IntegratedMemorySystem()

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

    server_params = StdioServerParameters(command="python", args=["mcp/server.py"])

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

        tools = [convert_mcp_tool(session, tool, memory_system) for tool in mcp_tools.tools]
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

        # ====================================================
        # MCP RESOURCE → SHORT-TERM MEMORY
        # ====================================================

        if policy_text:
            short_term_memory.add_message("user", f"[Bank Policy Reference]\n\n{policy_text}")
            short_term_memory.add_message("assistant", "Policy reference loaded.")

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

            short_term_memory.add_message("user", user)

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
            long_term_context = memory_system.retrieve_relevant_memory(user)

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
                    print("[LONG-TERM MEMORY] Fallback answer generated without long-term memory.")
            else:
                print("[LONG-TERM MEMORY] Answer verification skipped (no verified memory used).")

            # =================================================
            # STEP 9 — TOOL NOTES
            # =================================================

            new_messages = final_response["messages"][len(context_messages):]

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

            SCRATCHPAD_MARKER = "[Internal Scratchpad State]"

            persisted_messages = [
                message for message in final_response["messages"]
                if SCRATCHPAD_MARKER not in (
                    message.get("content", "") if isinstance(message, dict) else str(getattr(message, "content", ""))
                )
            ]

            short_term_memory.replace_messages(persisted_messages)

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
                tools = [convert_mcp_tool(session, tool, memory_system) for tool in mcp_tools.tools]
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
