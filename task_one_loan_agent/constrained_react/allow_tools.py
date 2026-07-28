from pathlib import Path
import sys
sys.path.append(str(Path(__file__).resolve().parent.parent))

from functions import (
    get_customer_data,
    evaluate_loan_application,
    generate_report
)

ALLOWED_TOOLS = {
    "get_customer_data": get_customer_data,
    "evaluate_loan_application": evaluate_loan_application,
    "generate_report": generate_report
}

ALLOWED_TOOL_NAMES = list(ALLOWED_TOOLS.keys())