import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from functions import(
     get_customer_data,
     calculate_dti,
     approve_loan,
     reject_loan,
     generate_report
)

def reactive_agent(customer_id):

    customer = get_customer_data(customer_id)

    if "error" in customer:
        return "CUSTOMER_NOT_FOUND"
    
    dti = calculate_dti(customer_id)

    if dti < 40:
        result = approve_loan(customer_id)
    else:
        result = reject_loan("High DTI")

    report = generate_report(customer_id,result["decision"])

    return {
        "result": result,
        "report": report
    }
