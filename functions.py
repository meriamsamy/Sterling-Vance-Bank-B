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
        "name": "Haland",
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
}

    

def get_customer_data(customer_id):

    if customer_id not in customers:
        return None

    return customers[customer_id]

def calculate_dti(customer):

    income = customer["income"]
    debt = customer["monthly_debt"]

    if income == 0:
        return 100

    return round((debt / income) * 100, 2)

def check_basic_eligibility(customer):

    if customer["age"] < 21:
        return False

    if customer["income"] < 8000:
        return False

    if customer["employment_years"] < 1:
        return False

    return True

def evaluate_loan_application(customer):

    dti = calculate_dti(customer)

    if customer["previous_defaults"] >= 2:
        return "REJECT"

    if dti > 50:
        return "REJECT"

    if customer["income"] >= 15000 and dti <= 35:
        return "APPROVE"

    if customer["income"] >= 10000 and dti <= 45:
        return "REVIEW"

    return "REQUEST_DOCUMENTS"

def calculate_max_loan(customer):

    return customer["income"] * 24

def approve_loan(customer):

    amount = calculate_max_loan(customer)

    return {
        "decision": "APPROVED",
        "approved_amount": amount
    }

def reject_loan(reason):

    return {
        "decision": "REJECTED",
        "reason": reason
    }

def request_documents():

    return {
        "decision": "REQUEST_DOCUMENTS",
        "message": "Please upload the required documents."
    }

def generate_report(customer, decision):

    return {
        "customer": customer["name"],
        "decision": decision
    }

def classify_customer(customer):

    if not check_basic_eligibility(customer):
        return "REJECT"

    decision = evaluate_loan_application(customer)

    return decision


