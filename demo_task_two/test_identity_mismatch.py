"""
Calls wire_transfer_initiate directly over MCP, bypassing the LLM agent
entirely. Needed for test cases the LLM will never naturally produce on its
own - like a deliberately mismatched employee_id, since the agent always
fills that field in correctly from whoever is logged in.

Usage: python demo/test_identity_mismatch.py
"""

import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER_PARAMS = StdioServerParameters(command="python", args=["mcp/server.py"])


async def main():
    async with stdio_client(SERVER_PARAMS) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            login_result = await session.call_tool("login", arguments={"employee_id": 4})
            print("Login:", login_result.content[0].text)

            # employee_id below deliberately does NOT match who just logged
            # in (4) - this is Bug/Concern 8's authorization check.
            result = await session.call_tool(
                "wire_transfer_initiate",
                arguments={
                    "employee_id": 1,  # mismatched on purpose
                    "source_account_id": 2,
                    "destination_account_num": "FR123",
                    "destination_country": "FR",
                    "amount": 100,
                },
            )
            print("Mismatched wire attempt:", result.content[0].text)
            assert result.isError or "match" in result.content[0].text.lower(), (
                "Expected the handler to reject the mismatched employee_id"
            )
            print("\nPASS: mismatched employee_id was rejected as expected.")


if __name__ == "__main__":
    asyncio.run(main())
