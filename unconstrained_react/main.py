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
    for chunk in agent.stream(
    {"messages": [("user", question)]},stream_mode="updates"):
        if "model" in chunk:
            message = chunk["model"]["messages"][-1]
            if message.content:
                print("\nAgent:")
                print(message.content)

        elif "tools" in chunk:
            tool_message = chunk["tools"]["messages"][0]

            print("\nTool:")
            print(f"{tool_message.name}")
            print(tool_message.content)


if __name__ == "__main__":
    run_unconstrained_agent(question)