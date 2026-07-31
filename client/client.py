import asyncio
from pathlib import Path
import sys
import sqlite3

sys.path.append(str(Path(__file__).resolve().parent.parent))

DB_PATH = Path(__file__).resolve().parent.parent / "db" / "bank.db"
conn = sqlite3.connect(DB_PATH)


from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client

from langchain_groq import ChatGroq
from langchain_core.tools import StructuredTool
from langchain.agents import create_agent
from pydantic import BaseModel, Field

from config import API_KEY


# -------- ELICITATION CALLBACK --------

async def handle_elicitation(context, params):

    print("\n--- HUMAN APPROVAL REQUIRED ---")
    print(params.message)

    answer = input("Approve transfer? (yes/no): ")

    return types.ElicitResult(
        action="accept",
        content={
            "approved": answer.lower() == "yes"
        }
    )


# -------- TOOL SCHEMAS --------

class LoginArgs(BaseModel):
    employee_id: int = Field(
        description="employee_id from the employees table"
    )


class GetAccountArgs(BaseModel):
    account_id: int = Field(
        description="account_id to look up"
    )


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

    async def call(**kwargs):

        result = await session.call_tool(
            mcp_tool.name,
            arguments=kwargs
        )

        return "\n".join(
            item.text
            for item in result.content
            if hasattr(item, "text")
        )

    return StructuredTool.from_function(
        coroutine=call,
        name=mcp_tool.name,
        description=mcp_tool.description,
        args_schema=SCHEMAS[mcp_tool.name],
    )


# -------- MAIN --------

async def main():

    server_params = StdioServerParameters(
        command="python",
        args=["mcp/server.py"]
    )


    # Client model used for Agent + Sampling
    llm = ChatGroq(
        api_key=API_KEY,
        model="openai/gpt-oss-20b",
        temperature=0.1
    )


    # -------- SAMPLING CALLBACK --------
    async def handle_sampling(request: types.CreateMessageRequest):

        print("SAMPLING REQUEST RECEIVED")

        print(request.messages)

        result = await llm.ainvoke(
            request.messages[-1].content.text
        )

        return types.CreateMessageResult(
            role="assistant",
            content=types.TextContent(
                type="text",
                text=result.content
            ),
            model="gpt-oss-20b",
            stopReason="endTurn"
        )


    async with stdio_client(server_params) as (read, write):

        async with ClientSession(
            read,
            write,
            elicitation_callback=handle_elicitation,
            sampling_callback=handle_sampling
        ) as session:

        
            # Capability Negotiation
            await session.initialize()

            print("MCP Connected")


            # Tool Discovery
            mcp_tools = await session.list_tools()

            print("\nAvailable MCP Tools:")

            for tool in mcp_tools.tools:
                print("-", tool.name)


            tools = [
                convert_mcp_tool(session, tool)
                for tool in mcp_tools.tools
            ]


            llm_with_tools = llm.bind_tools(tools)


            agent = create_agent(
                model=llm_with_tools,
                tools=tools,
                system_prompt="""
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
- If human approval is requested, wait for the result before responding.
"""
            )


            print("\nAgent Ready")


            while True:

                user = input("\nRequest: ")

                if user.lower() in ["exit", "quit"]:
                    break


                response = await agent.ainvoke(
                    {
                        "messages": [
                            {
                                "role": "user",
                                "content": user
                            }
                        ]
                    }
                )

                print("\nAssistant:")
                print(response["messages"][-1].content)

                # React to tool list change
                new_tools = await session.list_tools()

                old = {t.name for t in mcp_tools.tools}
                new = {t.name for t in new_tools.tools}

                if old != new:
                    print("\nNotification received: tools/list_changed")

                    mcp_tools = new_tools

                    tools = [
                        convert_mcp_tool(session, tool)
                        for tool in mcp_tools.tools
                    ]

                    llm_with_tools = llm.bind_tools(tools)

                    agent = create_agent(
                        model=llm_with_tools,
                        tools=tools,
                        system_prompt="""
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
- If human approval is requested, wait for the result before responding.
""",
                    )

                    print("Client updated its tool list.")



if __name__ == "__main__":
    asyncio.run(main())