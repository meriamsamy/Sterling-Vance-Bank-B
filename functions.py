customers = {

    1001: {
        "name": "Mohamed Salah",
        "age": 30,
        "income": 18000,
        "monthly_debt": 3000,
        "employment_years": 6,
        "previous_defaults": 0
    },

    1002: {
        "name": "Haaland",
        "age": 24,
        "income": 11000,
        "monthly_debt": 4500,
        "employment_years": 2,
        "previous_defaults": 0
    },

    1003: {
        "name": "Monalisa",
        "age": 35,
        "income": 5000,
        "monthly_debt": 6000,
        "employment_years": 5,
        "previous_defaults": 1
    },

    1004: {
        "name": "Cristiano Ronaldo",
        "age": 30,
        "income": 12000,
        "monthly_debt": 8000,
        "employment_years": 10,
        "previous_defaults": 0
    },

    1005: {
        "name": "Lionel Messi",
        "age": 19,
        "income": 20000,
        "monthly_debt": 4000,
        "employment_years": 1,
        "previous_defaults": 0
    },

     1006: {
    "name": "Ahmed_Freelancer",
    "age": 30,
    "income": 3000,          
    "monthly_debt": 3500,
    "employment_years": 3,
    "previous_defaults": 0
}
}

def get_customer_data(customer_id):
    """
    Retrieve customer information using customer ID.

    Args:
        customer_id (int): Unique customer identifier.

    Returns:
        dict:
            Customer data if found.
    """

    return customers.get(
        customer_id,
        {"error": "Customer not found"}
    )



def calculate_dti(customer_id):
    """
    Calculate Debt-To-Income ratio for a customer.

    Args:
        customer_id (int): Unique customer identifier.

    Returns:
        float:
            Customer DTI percentage.
    """

    customer = get_customer_data(customer_id)

    if "error" in customer:
        return 100

    income = customer["income"]
    debt = customer["monthly_debt"]

    if income == 0:
        return 100

    return round((debt / income) * 100, 2)



def check_basic_eligibility(customer_id):
    """
    Check customer's basic loan eligibility.

    Requirements:
        - Age >= 21
        - Income >= 8000
        - Employment years >= 1

    Args:
        customer_id (int): Unique customer identifier.

    Returns:
        bool:
            True if eligible, otherwise False.
    """

    customer = get_customer_data(customer_id)

    if "error" in customer:
        return False

    return (
        customer["age"] >= 21
        and customer["income"] >= 8000
        and customer["employment_years"] >= 1
    )



def evaluate_loan_application(customer_id):
    """
    Evaluate customer's loan application.

    Rules:
        - Reject previous defaults >= 2.
        - Reject DTI above 50%.
        - Approve high income customers.
        - Review medium risk customers.

    Args:
        customer_id (int): Unique customer identifier.

    Returns:
        str:
            Loan decision.
    """

    customer = get_customer_data(customer_id)

    if "error" in customer:
        return "CUSTOMER_NOT_FOUND"

    dti = calculate_dti(customer_id)

    if customer["previous_defaults"] >= 2:
        return "REJECT"

    if dti > 50:
        return "REJECT"

    if customer["income"] >= 15000 and dti <= 35:
        return "APPROVE"

    if customer["income"] >= 10000 and dti <= 45:
        return "REVIEW"

    return "REQUEST_DOCUMENTS"



def calculate_max_loan(customer_id):
    """
    Calculate maximum loan amount.

    Formula:
        income * 24

    Args:
        customer_id (int): Unique customer identifier.

    Returns:
        int:
            Maximum loan amount.
    """

    customer = get_customer_data(customer_id)

    if "error" in customer:
        return 0

    return customer["income"] * 24



def approve_loan(customer_id):
    """
    Approve loan application.

    Args:
        customer_id (int): Unique customer identifier.

    Returns:
        dict:
            Approval decision and amount.
    """

    amount = calculate_max_loan(customer_id)

    return {
        "decision": "APPROVED",
        "approved_amount": amount
    }



def reject_loan(reason):
    """
    Reject loan application.

    Args:
        reason (str): Rejection reason.

    Returns:
        dict:
            Rejection result.
    """

    return {
        "decision": "REJECTED",
        "reason": reason
    }



def request_documents():
    """
    Request additional documents.

    Returns:
        dict:
            Document request message.
    """

    return {
        "decision": "REQUEST_DOCUMENTS",
        "message": "Please upload the required documents."
    }



def generate_report(customer_id, decision):
    """
    Generate loan application report.

    Args:
        customer_id (int): Unique customer identifier.
        decision (str): Final decision.

    Returns:
        dict:
            Customer report.
    """

    customer = get_customer_data(customer_id)

    return {
        "customer": customer.get("name", "Unknown"),
        "decision": decision
    }



def classify_customer(customer_id):
    """
    Classify customer's loan application.

    Args:
        customer_id (int): Unique customer identifier.

    Returns:
        str:
            Final classification.
    """

    if not check_basic_eligibility(customer_id):
        return "REJECT"

    return evaluate_loan_application(customer_id)
