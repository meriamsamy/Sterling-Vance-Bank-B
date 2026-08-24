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


class GetRelatedEmployeesArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    customer_id: int = Field(ge=1)


class GetCustomerWireHistoryArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    customer_id: int = Field(ge=1)


class CreateInvestigationArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    customer_id: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500)


class GetInvestigationArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    investigation_id: int = Field(ge=1)


class SubmitInvestigationEvidenceArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    investigation_id: int = Field(ge=1)
    evidence_type: str = Field(min_length=1, max_length=100)
    evidence_data: str = Field(min_length=1)
    source: str = Field(min_length=1, max_length=200)

TOOL_VALIDATORS = {
    "login": LoginArgs,
    "get_account": GetAccountArgs,
    "wire_transfer_initiate": WireTransferArgs,
    "batch_sanctions_scan": BatchScanArgs,
    "get_customer_accounts": GetCustomerAccountsArgs,
    "get_transaction_history": GetTransactionHistoryArgs,
    "check_sanctions": CheckSanctionsArgs,
    "validate_investigation": ValidateInvestigationArgs,
    "get_related_employees": GetRelatedEmployeesArgs,
    "get_customer_wire_history": GetCustomerWireHistoryArgs,
    "create_investigation": CreateInvestigationArgs,
    "get_investigation": GetInvestigationArgs,
    "submit_investigation_evidence": SubmitInvestigationEvidenceArgs,
}

# Suspicious Activity Investigation additions

# Same conventions as the rest of the file: required fields,
# additionalProperties: false, gated to compliance/fraud roles the
# same way batch_sanctions_scan and the other investigation read

GET_RELATED_EMPLOYEES_SCHEMA = {
    "type": "object",
    "properties": {
        "customer_id": {
            "type": "integer",
            "minimum": 1,
            "description": "Positive customer ID to check for related employees (self-dealing evidence).",
        },
    },
    "required": ["customer_id"],
    "additionalProperties": False,
}

GET_CUSTOMER_WIRE_HISTORY_SCHEMA = {
    "type": "object",
    "properties": {
        "customer_id": {
            "type": "integer",
            "minimum": 1,
            "description": "Positive customer ID whose full wire transfer history (across all accounts) should be retrieved.",
        },
    },
    "required": ["customer_id"],
    "additionalProperties": False,
}

CREATE_INVESTIGATION_SCHEMA = {
    "type": "object",
    "properties": {
        "customer_id": {
            "type": "integer",
            "minimum": 1,
            "description": "Positive customer ID this investigation is about.",
        },
        "reason": {
            "type": "string",
            "minLength": 1,
            "maxLength": 500,
            "description": "Why this investigation was opened.",
        },
    },
    "required": ["customer_id", "reason"],
    "additionalProperties": False,
}

GET_INVESTIGATION_SCHEMA = {
    "type": "object",
    "properties": {
        "investigation_id": {
            "type": "integer",
            "minimum": 1,
            "description": "Positive investigation ID from the investigations table.",
        },
    },
    "required": ["investigation_id"],
    "additionalProperties": False,
}

SUBMIT_INVESTIGATION_EVIDENCE_SCHEMA = {
    "type": "object",
    "properties": {
        "investigation_id": {
            "type": "integer",
            "minimum": 1,
            "description": "Positive investigation ID this evidence belongs to.",
        },
        "evidence_type": {
            "type": "string",
            "minLength": 1,
            "maxLength": 100,
            "description": "What kind of evidence this is, e.g. 'customer_statement', 'source_of_funds'.",
        },
        "evidence_data": {
            "type": "string",
            "minLength": 1,
            "description": "The evidence content itself (free text, or a JSON-encoded structured payload).",
        },
        "source": {
            "type": "string",
            "minLength": 1,
            "maxLength": 200,
            "description": "Where this evidence came from, e.g. 'compliance_team', 'customer_email'.",
        },
    },
    "required": ["investigation_id", "evidence_type", "evidence_data", "source"],
    "additionalProperties": False,
}
