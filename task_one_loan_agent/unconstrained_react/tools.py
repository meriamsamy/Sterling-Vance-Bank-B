from langchain.tools import tool
from functions import *

tools = [
    tool(get_customer_data),
    tool(calculate_dti),
    tool(check_basic_eligibility),
    tool(evaluate_loan_application),
    tool(calculate_max_loan),
    tool(approve_loan),
    tool(reject_loan),
    tool(request_documents),
    tool(generate_report),
    tool(classify_customer),
]