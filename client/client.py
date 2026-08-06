import asyncio
import os
from pathlib import Path
import sys
from dotenv import load_dotenv

load_dotenv()
sys.path.append(str(Path(__file__).resolve().parent.parent))

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client

from langchain_groq import ChatGroq
from langchain_core.tools import StructuredTool
from langchain.agents import create_agent
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage,convert_to_messages
from pydantic import BaseModel, Field

from config import API_KEY
ACTIVE_CONTEXT_STRATEGY = os.getenv("CONTEXT_STRATEGY", "zone")

SYSTEM_PROMPT = """
You are a banking assistant.

Use MCP tools for all banking operations.

Available operations:
- login: authenticate employee session.
- get_account: retrieve account information.
- wire_transfer_initiate: initiate wire transfers.
- batch_sanctions_scan: scan transactions when available.

Rules:
- Always call tools instead of answering banking requests from memory.
- Never claim an operation succeeded unless the tool returned success.
- wire_transfer_initiate handles compliance holds and human approval
  internally. Call it directly for every transfer request, even ones you
  suspect are high-risk. Do not ask the user for approval yourself, and do
  not describe a hold as having happened before calling the tool - the tool
  call itself will pause for a human approver when needed.
- If a tool result contains an error, report the failure plainly instead of
  inventing a plausible-sounding outcome.
"""


# -------- ELICITATION CALLBACK --------

async def handle_elicitation(context, params):
    print("\n--- HUMAN APPROVAL REQUIRED ---")
    print(params.message)
    answer = input("Approve transfer? (yes/no): ")
    return types.ElicitResult(action="accept", content={"approved": answer.lower() == "yes"})


# -------- TOOL SCHEMAS --------

class LoginArgs(BaseModel):
    employee_id: int = Field(description="employee_id from the employees table")


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


# -------- MCP TOOL WRAPPER --------

def convert_mcp_tool(session, mcp_tool):
    async def progress_handler(progress: float, total: float | None, message: str | None = None):
        # [PROGRESS TRACKING] this is the actual hook the SDK uses - progress
        # notifications are correlated to the specific in-flight call via
        # this callback, not broadcast through the generic message_handler.
        if total:
            print(f"[progress] {int(progress)}/{int(total)} scanned", end="\r")
        else:
            print(f"[progress] {progress}", end="\r")

    async def call(**kwargs):
        if mcp_tool.name == "batch_sanctions_scan":
            result = await session.call_tool(
                mcp_tool.name, arguments=kwargs, progress_callback=progress_handler
            )
        else:
            result = await session.call_tool(mcp_tool.name, arguments=kwargs)

        text = "\n".join(item.text for item in result.content if hasattr(item, "text"))

        # A tool-level failure (isError=True) was previously joined and
        # handed to the model exactly like a success, so the LLM improvised
        # a plausible-sounding answer around a real crash instead of
        # reporting it. Surface it plainly instead.
        if result.isError:
            return f"TOOL ERROR: {text}"
        return text

    return StructuredTool.from_function(
        coroutine=call,
        name=mcp_tool.name,
        description=mcp_tool.description,
        args_schema=SCHEMAS[mcp_tool.name],
    )


def build_agent(llm, tools):
    llm_with_tools = llm.bind_tools(tools)
    return create_agent(model=llm_with_tools, tools=tools, system_prompt=SYSTEM_PROMPT)


# -------- MAIN --------

async def main():
    transport = os.getenv("TRANSPORT", "stdio").lower()

    # Client model used for both the LangChain agent and MCP sampling.
    llm = ChatGroq(groq_api_key=API_KEY, model="openai/gpt-oss-20b", temperature=0.1)

    # -------- SAMPLING CALLBACK --------
    # [SAMPLING] The server never reasons on its own model - every
    # create_message() call it makes gets routed here, through the
    # *client's* model, per the spec.
    async def handle_sampling(context, params: types.CreateMessageRequestParams):
        result = await llm.ainvoke(params.messages[-1].content.text)
        text = result.content if isinstance(result.content, str) else "".join(
            block.get("text", "") for block in result.content if isinstance(block, dict)
        )
        return types.CreateMessageResult(
            role="assistant",
            content=types.TextContent(type="text", text=text),
            model="gpt-oss-20b",
            stopReason="endTurn",
        )

    # -------- [NOTIFICATIONS] --------
    # Real push handling instead of polling list_tools() after every turn.
    # mcp==1.24.0's ClientSession has no per-notification-type callback
    # (e.g. no `tool_list_changed_callback` kwarg - that's a later SDK
    # version). All server->client notifications instead arrive through
    # one generic `message_handler`, so we check the notification's
    # method name ourselves and only react to tools/list_changed.
    tools_ref = {"dirty": False}

    async def message_handler(message) -> None:
        if isinstance(message, Exception):
            print(f"[message_handler] transport error: {message}")
            return
        # ServerNotification is a discriminated-union wrapper; the actual
        # notification (with its .method) lives at .root on some SDK
        # versions and directly on the object on others - handle both.
        notif = getattr(message, "root", message)
        method = getattr(notif, "method", None)
        if method == "notifications/tools/list_changed":
            print("\n[notification] tools/list_changed received - refreshing tool list")
            tools_ref["dirty"] = True
        elif method == "notifications/progress":
            # Progress is actually delivered via the per-call progress_callback
            # in convert_mcp_tool() now (that's the mechanism the SDK
            # correlates to a specific in-flight request). This branch is a
            # harmless fallback in case a future call doesn't register one.
            p = notif.params
            print(f"[progress] {p.progress}/{p.total} scanned", end="\r")

    server_params = StdioServerParameters(command="python", args=["mcp/server.py"])

    async def run_session(session: ClientSession):
        # [CAPABILITY NEGOTIATION] Check what the *server* actually
        # declared during initialize before relying on it, instead of
        # assuming every server supports resources/prompts/notifications.
        init_result = await session.initialize()
        caps = init_result.capabilities
        print("MCP Connected. Server capabilities:")
        print(f"  tools.listChanged = {bool(caps.tools and caps.tools.listChanged)}")
        print(f"  resources         = {caps.resources is not None}")
        print(f"  prompts           = {caps.prompts is not None}")

        # [RESOURCES] Read the policy document once, up front, instead of
        # wrapping it in a tool the model would have to "call" every time.
        if caps.resources is not None:
            resources = await session.list_resources()
            for r in resources.resources:
                print(f"\n[resource available] {r.name} ({r.uri})")
            if resources.resources:
                policy = await session.read_resource(resources.resources[0].uri)
                print("--- policy document loaded into context ---")
                print(policy.contents[0].text[:200] + "...\n")
        else:
            print("Server did not declare a resources capability - skipping policy fetch.")

        # [PROMPTS] Surface the canned template a host could offer a user.
        if caps.prompts is not None:
            prompts = await session.list_prompts()
            for p in prompts.prompts:
                print(f"[prompt available] {p.name}: {p.description}")

        mcp_tools = await session.list_tools()
        print("\nAvailable MCP Tools:", [t.name for t in mcp_tools.tools])

        tools = [convert_mcp_tool(session, t) for t in mcp_tools.tools]
        agent = build_agent(llm, tools)
        print("\nAgent Ready")

        # [RESOURCES] Fetching the policy is pointless if the model never
        # actually sees it - previously this was only printed to the
        # terminal. Seed the conversation with it so questions like "what's
        # the wire transfer policy" can actually be answered.


        from memory.short_term_memory.short_term_memory import ShortTermMemory
        from memory.short_term_memory.scratchpad import Scratchpad
        from memory.context_strategies.context_manager import ContextManager

        memory = ShortTermMemory(max_messages=20)
        scratchpad = Scratchpad()
        context_manager = ContextManager()

        if caps.resources is not None and resources.resources:

            memory.add_message(
                "user",
                f"Reference material - the bank's wire transfer policy:\n\n{policy.contents[0].text}"
            )

            memory.add_message(
                "assistant",
                "Understood, I'll use this policy when answering compliance questions."
            )


        while True:
            user = input("\nRequest: ")
            if user.lower() in ("exit", "quit"):
                break

            # -------- SCRATCHPAD: working state --------
            scratchpad.set_goal(user)
            scratchpad.set_current_step("Calling MCP tools to fulfill the request")

            memory.add_message("user", user)

            raw_context = context_manager.process(
                ACTIVE_CONTEXT_STRATEGY,
                memory.get_messages()
            )
            
            context_messages = []
            for m in raw_context:
                if isinstance(m, dict):
                    if m.get("role") in ("tool", "function"):
                        if "tool_call_id" not in m:
                            m["tool_call_id"] = "fallback_call_id"
                        if "name" not in m:
                            m["name"] = "unknown_tool"
                    context_messages.extend(convert_to_messages([m]))
                elif isinstance(m, ToolMessage):
                    if not getattr(m, "tool_call_id", None):
                        m.tool_call_id = "fallback_call_id"
                    if not getattr(m, "name", None):
                        m.name = "unknown_tool"
                    context_messages.append(m)
                else:
                    context_messages.append(m)
                               
            scratchpad_state = scratchpad.get_state()
            scratchpad_context_str = (
                f"[Internal Scratchpad State]\n"
                f"Goal: {scratchpad_state['goal']}\n"
                f"Current Step: {scratchpad_state['current_step']}\n"
                f"Notes: {', '.join(scratchpad_state['notes'])}\n"
            )

            augmented_context = [
                SystemMessage(content=scratchpad_context_str)
            ] + context_messages

            response = await agent.ainvoke({"messages": augmented_context})

            # Record what actually happened this turn as scratchpad notes -
            # only the messages the agent added THIS turn. response
            # includes the full history again, so slicing off
            # augmented_context avoids re-adding old tool calls as
            # duplicate notes on every subsequent turn.
            new_messages = response["messages"][len(augmented_context):]
            for msg in new_messages:
                tool_name = getattr(msg, "name", None)
                if tool_name:
                    scratchpad.add_note(f"Tool call: {tool_name}")

            print("\nAssistant:")
            print(response["messages"][-1].content)

            print("\n[scratchpad state]", scratchpad.get_state())

            # The injected "[Internal Scratchpad State]" SystemMessage is a
            # per-turn snapshot, not part of the real conversation - if we
            # store it in `memory` it gets treated like any other chat
            # message by the pruning strategies and piles up stale copies
            # of the scratchpad every turn. Strip it before persisting.
            SCRATCHPAD_MARKER = "[Internal Scratchpad State]"
            persisted_messages = [
                m for m in response["messages"]
                if SCRATCHPAD_MARKER not in (
                    m.get("content", "") if isinstance(m, dict)
                    else str(getattr(m, "content", ""))
                )
            ]
            memory.replace_messages(persisted_messages)
            scratchpad.set_current_step("Waiting for next request")

            # [NOTIFICATIONS] React only if the server actually pushed a change
            if tools_ref["dirty"]:
                mcp_tools = await session.list_tools()
                tools = [convert_mcp_tool(session, t) for t in mcp_tools.tools]
                agent = build_agent(llm, tools)
                tools_ref["dirty"] = False
                print("Client updated its tool list:", [t.name for t in mcp_tools.tools])

    if transport == "http":
        from mcp.client.streamable_http import streamablehttp_client

        url = os.getenv("MCP_SERVER_URL", "http://localhost:8000/mcp")
        async with streamablehttp_client(url) as (read, write, _):
            async with ClientSession(
                read, write,
                elicitation_callback=handle_elicitation,
                sampling_callback=handle_sampling,
                message_handler=message_handler,
            ) as session:
                await run_session(session)
    else:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(
                read, write,
                elicitation_callback=handle_elicitation,
                sampling_callback=handle_sampling,
                message_handler=message_handler,
            ) as session:
                await run_session(session)


if __name__ == "__main__":
    asyncio.run(main())