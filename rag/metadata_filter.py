from langchain_groq import ChatGroq
from config import API_KEY


llm = ChatGroq(
    api_key=API_KEY,
    model="openai/gpt-oss-20b",
    temperature=0.1
)


def extract_metadata_filter(query):

    prompt = f"""
You are a banking policy query classifier.

The policy contains these sections:

1 Purpose
2 Scope
3 Employee Roles
4 Customer Accounts
5 Wire Transfer Process
6 Transfer Validation
7 Authority Limits
8 Wire Transfer Status
9 Sanctions Screening
10 Suspicious Transaction Detection
11 Structuring Detection
12 Conflict of Interest
13 AI-Assisted Risk Assessment
14 Human Approval
15 Account Freeze Policy
16 Compliance Review
17 Decision Matrix
18 Guiding Principles

Question:
{query}

If the question clearly belongs to ONE section,
return only the section number.

Otherwise return:
none

Answer only the number or none.
"""

    response = llm.invoke(prompt)

    result = response.content.strip()

    if result.isdigit():
        return result

    return None