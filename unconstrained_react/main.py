from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parent.parent))

from langchain.agents import create_agent
from langchain_groq import ChatGroq 
from config import API_KEY
from tools import tools


llm = ChatGroq(
    model="llama-3.3-70b-versatile",
    groq_api_key=API_KEY,
    temperature=0
)
tool_calls = 0
total_tokens = 0
total_time = 0

prompt = """You are an AI loan approval agent for Sterling and Vance Bank. 

Your job is to evaluate loan applications.

You may use any available tool whenever you think it is helpful.

Reason step by step, choose tools freely, and stop only when you have enough information to provide the final answer.
"""

agent = create_agent(
    model=llm,
    tools=tools,
    system_prompt=prompt,
    )

question = """
Customer ID is 1001.

Evaluate the customer's loan application.
If eligible, approve the loan.
Otherwise reject it.
Request any missing documents if necessary.
Finally generate a report.
"""


def run_unconstrained_agent(question):

    global tool_calls, total_tokens, total_time

    for chunk in agent.stream(
        {"messages": [("user", question)]},
        stream_mode="updates"
    ):

        if "model" in chunk:

            message = chunk["model"]["messages"][-1]

            if message.content:

                print("\nAgent:")
                print(message.content)

            metadata = message.response_metadata

            if metadata:

                print("\nResponse Metadata:")
                print(metadata)

                usage = metadata.get("token_usage", {})

                total_tokens += usage.get("total_tokens", 0)

                total_time += metadata.get("total_time", 0)

        elif "tools" in chunk:

            tool_calls += 1

            tool_message = chunk["tools"]["messages"][0]

            print("\nTool:")
            print(tool_message.name)
            print(tool_message.content)

    print("\nsummary for comparison table:")
    print(f"Tool Calls : {tool_calls}")
    print(f"Total Tokens : {total_tokens}")

if __name__ == "__main__":
    run_unconstrained_agent(question)