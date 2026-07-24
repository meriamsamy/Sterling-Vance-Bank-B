import sys
import os
import json

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage

from config import API_KEY

from functions import (
    get_customer_data,
    approve_loan,
    reject_loan,
    request_documents,
    generate_report
)
llm = ChatGroq(
    model="llama-3.3-70b-versatile",
    api_key=API_KEY,
    temperature=0,
    model_kwargs={
        "response_format": {"type": "json_object"}
    }
)
system_prompt = """
You are a loan routing classifier.

Classify the loan application into ONE label only.

APPROVE
REJECT
REQUEST_DOCUMENTS

Return JSON only.

Example:
{
    "route": "APPROVE"
}
"""
def classify_customer(customer):

    response = llm.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=json.dumps(customer))
    ])

    result = json.loads(response.content)
    return result["route"]
def routing_agent(customer_id):

    customer = get_customer_data(customer_id)

    if "error" in customer:
        return customer

    route = classify_customer(customer)

    if route == "APPROVE":
        result = approve_loan(customer_id)

    elif route == "REJECT":
        result = reject_loan("Rejected by Routing Agent")

    elif route == "REQUEST_DOCUMENTS":
        result = request_documents()

    else:
        result = reject_loan("Unknown Route")

    report = generate_report(customer_id, result["decision"])

    return {
        "route": route,
        "result": result,
        "report": report
    }

if __name__ == "__main__":

    customer_id = 1001

    output = routing_agent(customer_id)

    print(json.dumps(output, indent=4))