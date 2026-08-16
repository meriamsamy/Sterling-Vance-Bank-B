"""
Input schemas for every tool. Required fields + additionalProperties: false
on all of them — an incomplete or extra field gets rejected before it ever
reaches our code.
"""

LOGIN_SCHEMA = {
    "type": "object",
    "properties": {
        "employee_id": {"type": "integer", "description": "employee_id from the employees table"},
    },
    "required": ["employee_id"],
    "additionalProperties": False,
}

GET_ACCOUNT_SCHEMA = {
    "type": "object",
    "properties": {
        "account_id": {"type": "integer", "description": "account_id to look up"},
    },
    "required": ["account_id"],
    "additionalProperties": False,
}

WIRE_TRANSFER_SCHEMA = {
    "type": "object",
    "properties": {
        "employee_id": {"type": "integer", "description": "must match the logged-in session"},
        "source_account_id": {"type": "integer"},
        "destination_account_num": {"type": "string", "description": "external account number, e.g. FR-9988776655"},
        "destination_country": {"type": "string", "minLength": 2, "maxLength": 2},
        "amount": {"type": "number", "exclusiveMinimum": 0, "maximum": 1000000},
    },
    "required": [
        "employee_id", "source_account_id", "destination_account_num",
        "destination_country", "amount",
    ],
    "additionalProperties": False,
}

BATCH_SCAN_SCHEMA = {
    "type": "object",
    "properties": {
        "employee_id": {"type": "integer", "description": "must be compliance_officer or fraud_investigator"},
    },
    "required": ["employee_id"],
    "additionalProperties": False,
}

# --- Investigation tools (read-only) — added for the Planning Agent's
# Router (Issue #68). Same access model as batch_sanctions_scan: these
# only make sense for compliance/fraud roles, so they're gated the same
# way in server.py's list_tools(). No new data or capability beyond what
# db_access.py and the existing schema already have.

GET_CUSTOMER_ACCOUNTS_SCHEMA = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "integer", "description": "customer_id from the customers table"},
    },
    "required": ["customer_id"],
    "additionalProperties": False,
}

GET_TRANSACTION_HISTORY_SCHEMA = {
    "type": "object",
    "properties": {
        "account_id": {"type": "integer", "description": "account_id to fetch transaction history for"},
    },
    "required": ["account_id"],
    "additionalProperties": False,
}

CHECK_SANCTIONS_SCHEMA = {
    "type": "object",
    "properties": {
        "destination_country": {"type": "string", "minLength": 2, "maxLength": 2},
    },
    "required": ["destination_country"],
    "additionalProperties": False,
}

VALIDATE_INVESTIGATION_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "success": {
            "type": "boolean",
        },
        "details": {
            "type": "array",
            "items": {
                "type": "string",
            },
        },
    },
    "required": ["success", "details"],
    "additionalProperties": False,
}