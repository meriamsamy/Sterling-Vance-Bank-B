from pathlib import Path
import sys
sys.path.append(str(Path(__file__).resolve().parent.parent))

from langchain_groq import ChatGroq
from config import API_KEY
from validation_schema import AgentStep, MAX_STEPS
from allow_tools import ALLOWED_TOOLS, ALLOWED_TOOL_NAMES

llm = ChatGroq(
    model="llama-3.3-70b-versatile",
    groq_api_key=API_KEY,
    temperature=0,
    model_kwargs={
        "response_format": {
            "type": "json_object"
        }
    }
)

SYSTEM_PROMPT = f"""
You are a constrained ReAct loan approval agent.

Every response MUST be a JSON object.

The JSON MUST always contain these fields:

{{
    "action": "tool_call | final_answer | escalate",
    "tool": "tool_name or null",
    "input": {{}},
    "reasoning": "short explanation"
}}

Example tool call:

{{
    "action": "tool_call",
    "tool": "get_customer_data",
    "input": {{
        "customer_id": 1001
    }},
    "reasoning": "Need customer information before evaluating the loan."
}}

Example final answer:

{{
    "action": "final_answer",
    "tool": null,
    "input": {{}},
    "reasoning": "Loan approved because eligibility criteria were satisfied."
}}

Rules:

Allowed tools:
{ALLOWED_TOOL_NAMES}

Tool arguments:

get_customer_data:
{{"customer_id": int}}

evaluate_loan_application:
{{"customer_id": int}}

generate_report:
{{"customer_id": int, "decision": str}}

Never omit action.
Never omit reasoning.
Never return text outside JSON.

Maximum steps:
{MAX_STEPS}
"""

def call_tool(tool_name, tool_input):

    if tool_name not in ALLOWED_TOOLS:
        raise Exception(
            f"Tool {tool_name} is not allowed"
        )


    if tool_name == "get_customer_data":
        return ALLOWED_TOOLS[tool_name](
            customer_id=tool_input["customer_id"]
        )


    if tool_name == "evaluate_loan_application":
        return ALLOWED_TOOLS[tool_name](
            customer_id=tool_input["customer_id"]
        )


    if tool_name == "generate_report":
        return ALLOWED_TOOLS[tool_name](
            customer_id=tool_input["customer_id"],
            decision=tool_input["decision"]
        )



def run_constrained_agent(question):

    history = []

    for step_number in range(MAX_STEPS):

        print(f"\nSTEP {step_number + 1}/{MAX_STEPS}")

        response = llm.invoke(
            [
                ("system", SYSTEM_PROMPT),
                ("user", question),
                (
                    "user",
                    f"""
        Previous steps and tool results:

        {history}

        Continue from the previous state.
        Do not repeat tools that already returned results.
        Choose the next required action only.
        """
                )
            ]
        )

        print("RAW RESPONSE:")
        print(response)
        step = AgentStep.model_validate_json(
            response.content
        )


        print("\nAgent Step:")
        print("\nAction:", step.action)
        print("Tool:", step.tool)
        print("Input:", step.input)
        print("Reasoning:", step.reasoning)


        history.append(
            step.model_dump()
        )


        if step.action == "tool_call":

            result = call_tool(
                step.tool,
                step.input
            )

            print("\nTool Result:")
            print(result)


            history.append(
                {
                    "role": "tool",
                    "tool": step.tool,
                    "result": result
                }
            )


        elif step.action == "final_answer":

            print("\nFINAL ANSWER:")
            print(step.reasoning)

            return


        elif step.action == "escalate":

            print("\nESCALATED:")
            print(step.reasoning)

            return



    print("\nESCALATED:")
    print("Maximum steps reached without final decision.")



question = """
Customer ID is 1001.

Evaluate the customer's loan application.
Approve if eligible.
Reject if not eligible.
Generate a report.
"""


if __name__ == "__main__":
    run_constrained_agent(question)