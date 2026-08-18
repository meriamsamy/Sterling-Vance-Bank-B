"""
Input schemas for every tool. Required fields + additionalProperties: false
on all of them — an incomplete or extra field gets rejected before it ever
reaches our code.
"""
from pydantic import BaseModel , ConfigDict , Field

LOGIN_SCHEMA = {
    "type": "object",
    "properties": {
        "employee_id": {
            "type": "integer",
            "minimum": 1,
            "description": "Positive employee ID from the employees table.",
        },
    },
    "required": ["employee_id"],
    "additionalProperties": False,
}

GET_ACCOUNT_SCHEMA = {
    "type": "object",
    "properties": {
        "account_id": {
            "type": "integer",
            "minimum": 1,
            "description": "Positive account ID from the accounts table.",
        },
    },
    "required": ["account_id"],
    "additionalProperties": False,
}

WIRE_TRANSFER_SCHEMA = {
    "type": "object",
    "properties": {
        "employee_id": {
            "type": "integer",
            "minimum": 1,
            "description": "Positive employee ID; must match the logged-in session.",
        },

        "source_account_id": {
            "type": "integer",
            "minimum": 1,
            "description": "Positive ID of the source account to debit.",
        },

        "destination_account_num": {
            "type": "string",
            "minLength": 3,
            "maxLength": 34,
            "description": "External destination account number in country-prefixed format, such as FR-9988776655.",
        },

        "destination_country": {
            "type": "string",
            "minLength": 2,
            "maxLength": 2,
            "pattern": "^[A-Z]{2}$",
            "description": "Two-letter uppercase ISO-style country code, such as FR, EG, or IR.",
        },

        "amount": {
            "type": "number",
            "exclusiveMinimum": 0,
            "maximum": 1000000,
            "description": "Positive wire amount in USD; maximum accepted transfer amount is 1,000,000.",
        },
    },
    "required": [
        "employee_id",
        "source_account_id",
        "destination_account_num",
        "destination_country",
        "amount",
    ],
    "additionalProperties": False,
}

BATCH_SCAN_SCHEMA = {
    "type": "object",
    "properties": {
        "employee_id": {
            "type": "integer",
            "minimum": 1,
            "description": "Positive employee ID; employee must have compliance_officer or fraud_investigator role.",
        },
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
        "customer_id": {
            "type": "integer",
            "minimum": 1,
            "description": "Positive customer ID from the customers table.",
        },
    },
    "required": ["customer_id"],
    "additionalProperties": False,
}

GET_TRANSACTION_HISTORY_SCHEMA = {
    "type": "object",
    "properties": {
        "account_id": {
            "type": "integer",
            "minimum": 1,
            "description": "Positive account ID whose recent transaction history should be retrieved.",
        },
    },
    "required": ["account_id"],
    "additionalProperties": False,
}

CHECK_SANCTIONS_SCHEMA = {
    "type": "object",
    "properties": {
        "destination_country": {
            "type": "string",
            "minLength": 2,
            "maxLength": 2,
            "pattern": "^[A-Z]{2}$",
            "description": "Two-letter uppercase country code to check against the sanctions list.",
        },
    },
    "required": ["destination_country"],
    "additionalProperties": False,
}


VALIDATE_INVESTIGATION_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "success": {
            "type": "boolean",
            "description": "Whether all grounded investigation checks passed.",
        },
        "details": {
            "type": "array",
            "description": "Human-readable details explaining the validation checks and their results.",
            "items": {
                "type": "string",
                "description": "A single validation result or explanation.",
            },
        },
    },
    "required": ["success", "details"],
    "additionalProperties": False,
}

# ================= SERVER-SIDE VALIDATION =================
class LoginArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    employee_id: int = Field(ge=1)


class GetAccountArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_id: int = Field(ge=1)


class WireTransferArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    employee_id: int = Field(ge=1)
    source_account_id: int = Field(ge=1)
    destination_account_num: str = Field(min_length=3, max_length=34)
    destination_country: str = Field(
        min_length=2,
        max_length=2,
        pattern=r"^[A-Z]{2}$",
    )
    amount: float = Field(gt=0, le=1_000_000)


class BatchScanArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    employee_id: int = Field(ge=1)


class GetCustomerAccountsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: int = Field(ge=1)


class GetTransactionHistoryArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: int = Field(ge=1)


class CheckSanctionsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    destination_country: str = Field(
        min_length=2,
        max_length=2,
        pattern=r"^[A-Z]{2}$",
    )


class ValidateInvestigationArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task: str = Field(min_length=1)
    candidate: str = Field(min_length=1)

TOOL_VALIDATORS = {
    "login": LoginArgs,
    "get_account": GetAccountArgs,
    "wire_transfer_initiate": WireTransferArgs,
    "batch_sanctions_scan": BatchScanArgs,
    "get_customer_accounts": GetCustomerAccountsArgs,
    "get_transaction_history": GetTransactionHistoryArgs,
    "check_sanctions": CheckSanctionsArgs,
    "validate_investigation": ValidateInvestigationArgs,
}