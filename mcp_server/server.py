"""
Sterling & Vance wire transfer server.

Covers all 8 protocol concerns.

[CAPABILITY NEGOTIATION]
[NOTIFICATIONS]
[ELICITATION]
[RESOURCES]
[PROMPTS]
[TRANSPORT]
[PROGRESS TRACKING]
[DEFENSIVE TOOL DESIGN]

"""

import asyncio
import os
import sys
import re
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any
from weakref import WeakKeyDictionary, WeakSet
from collections import defaultdict

import mcp.types as types
from mcp.server import Server, NotificationOptions
from mcp.server.stdio import stdio_server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

from mcp_server import db_access as db

from .schemas import (
    LOGIN_SCHEMA,
    GET_ACCOUNT_SCHEMA,
    WIRE_TRANSFER_SCHEMA,
    BATCH_SCAN_SCHEMA,
    GET_CUSTOMER_ACCOUNTS_SCHEMA,
    GET_TRANSACTION_HISTORY_SCHEMA,
    CHECK_SANCTIONS_SCHEMA,
    VALIDATE_INVESTIGATION_OUTPUT_SCHEMA,
    TOOL_VALIDATORS,
    GET_RELATED_EMPLOYEES_SCHEMA,
    GET_CUSTOMER_WIRE_HISTORY_SCHEMA,
    CREATE_INVESTIGATION_SCHEMA,
    GET_INVESTIGATION_SCHEMA,
    SUBMIT_INVESTIGATION_EVIDENCE_SCHEMA,
)

from pydantic import ValidationError, BaseModel
from .policy_document import WIRE_TRANSFER_POLICY

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

# ============================================================
# LANGGRAPH IMPORTS
# ============================================================

from langgraph.types import Command
from langgraph.checkpoint.memory import MemorySaver


# ============================================================
# CUSTOMER RISK GRAPH INTEGRATION
# ============================================================

from state_graph.customer_risk.graph import build_customer_risk_graph


# ============================================================
# SANCTIONS STATE GRAPH INTEGRATION
# ============================================================

from state_graph.sanctions_change.sanctions_graph import graph_builder

# ISSUE #98 completion (HITL / failure-ticket surfacing):
# sanctions_graph_runner.py already has a full, DURABLE
# (checkpoint_context-backed, not the in-memory MemorySaver used
# below for /invoke) implementation of "read the paused state" /
# "resume after an admin decision" / "resume after a ticket is
# resolved". We reuse it as-is instead of reinventing thread
# reconstruction here - it's already correct and it's what makes
# the paused state survive a server restart, which an in-memory
# checkpointer cannot do.
#
# We import the *_async variants (not resume_after_admin /
# get_review_state / resume_after_ticket_resolution) because those
# public wrappers call asyncio.run(...) internally, which raises
# if called from inside a FastAPI async handler that's already
# running inside an event loop.
from state_graph.sanctions_change.sanctions_graph_runner import (
    default_thread_id as sanctions_default_thread_id,
    _get_review_state_async as sanctions_get_review_state,
    _resume_after_admin_async as sanctions_resume_after_admin,
    _resume_after_ticket_resolution_async as sanctions_resume_after_ticket,
)


# ============================================================
# CUSTOMER RISK GRAPH
# ============================================================

customer_risk_graph = build_customer_risk_graph()


# ============================================================
# SANCTIONS GRAPH
# ============================================================

sanctions_checkpointer = MemorySaver()

sanctions_graph = graph_builder.compile(
    checkpointer=sanctions_checkpointer
)


# ============================================================
# CUSTOMER ID / WIRE ID EXTRACTION
# ============================================================

def extract_customer_id(message: str) -> int:
    match = re.search(
        r"customer(?:\s+id)?\s*#?\s*(\d+)",
        message,
        re.IGNORECASE,
    )
    if not match:
        raise ValueError(
            "Could not find a customer ID. "
            "Example: 'Check customer 5'."
        )
    return int(match.group(1))


def extract_wire_id(message: str) -> int:
    match = re.search(
        r"(?:wire|transfer)"
        r"(?:\s+id)?"
        r"\s*#?\s*(\d+)",
        message,
        re.IGNORECASE,
    )
    if not match:
        raise ValueError(
            "Could not find a wire or transfer ID. "
            "Example: 'Review wire 15'."
        )
    return int(match.group(1))


# ============================================================
# MCP SERVER
# ============================================================
#
# NOTE: the MCP `Server` instance and its handlers are defined
# BEFORE the FastAPI `app` below, because the FastAPI app needs to
# mount the MCP streamable-HTTP transport (session_manager) inside
# its own lifespan. Keeping everything in one process/one app is
# what makes "admin assigns a tool -> live agent sees it right
# away" possible; splitting them into two separate apps (as the
# previous draft did with a standalone run_http()) would make that
# impossible without extra IPC.


server = Server("sterling-vance-wire-server")


WIRE_TRANSFER_POLICY_URI = (
    "policy://sterling-vance/wire-transfer-controls"
)

COMPLIANCE_HOLD_PROMPT_NAME = (
    "draft_compliance_hold_notice"
)


# ============================================================
# ISSUE #98 FIX (A): PER-CONNECTION SESSION STATE
# ============================================================
#
# Keyed off the actual ServerSession object for this connection
# (ctx.session), not a shared global. WeakKeyDictionary means the
# entry is dropped automatically once the session object itself is
# garbage-collected on disconnect - no separate cleanup hook needed.

_SESSION_STATE: "WeakKeyDictionary" = WeakKeyDictionary()


def _session_state(ctx) -> dict:
    sess = ctx.session
    state = _SESSION_STATE.get(sess)
    if state is None:
        state = {"employee_id": None, "agent_id": None}
        _SESSION_STATE[sess] = state
    return state


# ============================================================
# ISSUE #98 FIX (B): LIVE AGENT -> SESSION REGISTRY
# ============================================================
#
# Lets the admin API push a "your tool list changed" notification
# to an agent connection that is live *right now*, in addition to
# the backend enforcement in call_tool() (which is what actually
# makes removal effective even without this notification - this is
# purely so a connected client doesn't have to wait for its next
# unrelated list_tools() poll to notice a change).

AGENT_LIVE_SESSIONS: "defaultdict[str, WeakSet]" = defaultdict(WeakSet)


async def _notify_agent_tools_changed(agent_id: str) -> None:
    for sess in list(AGENT_LIVE_SESSIONS.get(agent_id, ())):
        try:
            await sess.send_tool_list_changed()
        except Exception:
            # Best-effort push; live enforcement in call_tool()/
            # list_tools() is the real source of truth regardless.
            pass


# ============================================================
# ISSUE #98: AGENT REGISTRATION SCHEMA
# ============================================================

REGISTER_AGENT_SCHEMA = {
    "type": "object",
    "properties": {
        "agent_id": {
            "type": "string",
            "description": (
                "Stable unique id for this agent, e.g. "
                "'loan_agent' or 'sanctions_change_agent'. "
                "Reused on every reconnect."
            ),
        },
        "name": {
            "type": "string",
            "description": "Human-readable agent name for the admin platform.",
        },
        "description": {
            "type": "string",
            "description": "Short description of what this agent does.",
        },
    },
    "required": ["agent_id"],
    "additionalProperties": False,
}


# ============================================================
# BASE TOOLS
# ============================================================

BASE_TOOLS = [
    types.Tool(
        name="login",
        description="Log in as an employee for this session.",
        inputSchema=LOGIN_SCHEMA,
    ),
    types.Tool(
        name="get_account",
        description="Look up an account (read-only).",
        inputSchema=GET_ACCOUNT_SCHEMA,
    ),
    types.Tool(
        name="wire_transfer_initiate",
        description=(
            "Send a wire transfer. High-risk wires "
            "get held for review."
        ),
        inputSchema=WIRE_TRANSFER_SCHEMA,
    ),
    types.Tool(
        name="register_agent",
        description=(
            "Identify this connection as a specific agent. Call "
            "this once, right after connecting, before calling "
            "any other tool. The agent then only sees/can invoke "
            "the tools assigned to it by an administrator."
        ),
        inputSchema=REGISTER_AGENT_SCHEMA,
    ),
]


# ============================================================
# COMPLIANCE TOOLS
# ============================================================

COMPLIANCE_TOOLS = [
    types.Tool(
        name="batch_sanctions_scan",
        description=(
            "Scan all transactions against the sanctions "
            "list. Reports progress as it runs."
        ),
        inputSchema=BATCH_SCAN_SCHEMA,
    ),
    types.Tool(
        name="get_customer_accounts",
        description=(
            "List all accounts linked to a customer "
            "(read-only)."
        ),
        inputSchema=GET_CUSTOMER_ACCOUNTS_SCHEMA,
    ),
    types.Tool(
        name="get_transaction_history",
        description=(
            "Recent transaction history for one account "
            "(read-only)."
        ),
        inputSchema=GET_TRANSACTION_HISTORY_SCHEMA,
    ),
    types.Tool(
        name="check_sanctions",
        description=(
            "Check whether a destination country is on "
            "the sanctions list (read-only)."
        ),
        inputSchema=CHECK_SANCTIONS_SCHEMA,
    ),
]


# ============================================================
# VALIDATION TOOLS
# ============================================================

VALIDATION_TOOLS = [
    types.Tool(
        name="validate_investigation",
        description=(
            "Validate a planning agent investigation result "
            "against the real Sterling & Vance banking database."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": (
                        "The investigation sub-task "
                        "being evaluated."
                    ),
                },
                "candidate": {
                    "type": "string",
                    "description": (
                        "The planning agent's proposed result."
                    ),
                },
            },
            "required": ["task", "candidate"],
            "additionalProperties": False,
        },
        outputSchema=VALIDATE_INVESTIGATION_OUTPUT_SCHEMA,
    )
]


ALL_TOOLS_BY_NAME: dict[str, types.Tool] = {
    t.name: t
    for t in (BASE_TOOLS + COMPLIANCE_TOOLS + VALIDATION_TOOLS)
}

# Tools that must always work regardless of agent assignment.
AGENT_EXEMPT_TOOLS = {"register_agent"}


def _current_agent_id(ctx) -> str | None:
    return _session_state(ctx).get("agent_id")


def _agent_tool_allowed(ctx, tool_name: str) -> bool:
    """
    Backend enforcement check.

    - No agent identified on this connection -> legacy behavior,
      nothing extra is blocked (keeps existing employee-login
      flows working exactly as before this change).
    - Agent identified -> the tool must be present in that
      agent's live agent_tools assignment, checked fresh against
      the database on every single call (no cache), so an admin
      removing a tool takes effect on this agent's very next call.
    """
    if tool_name in AGENT_EXEMPT_TOOLS:
        return True

    agent_id = _current_agent_id(ctx)
    if agent_id is None:
        return True

    return db.is_tool_assigned(agent_id, tool_name)


# ============================================================
# INVESTIGATION TOOLS
# ============================================================

INVESTIGATION_TOOLS = [
    types.Tool(
        name="get_related_employees",
        description="List employees related to a customer (self-dealing/conflict-of-interest evidence, read-only).",
        inputSchema=GET_RELATED_EMPLOYEES_SCHEMA,
    ),
    types.Tool(
        name="get_customer_wire_history",
        description="Full wire transfer history (amount, status, destination, timestamp) across all of a customer's accounts, read-only.",
        inputSchema=GET_CUSTOMER_WIRE_HISTORY_SCHEMA,
    ),
    types.Tool(
        name="create_investigation",
        description="Open a new suspicious activity investigation for a customer and start the investigation state graph.",
        inputSchema=CREATE_INVESTIGATION_SCHEMA,
    ),
    types.Tool(
        name="get_investigation",
        description="Look up a suspicious activity investigation's current status (read-only).",
        inputSchema=GET_INVESTIGATION_SCHEMA,
    ),
    types.Tool(
        name="submit_investigation_evidence",
        description="Submit new evidence for an investigation that is waiting on it — resumes the paused investigation graph.",
        inputSchema=SUBMIT_INVESTIGATION_EVIDENCE_SCHEMA,
    ),
]


# ============================================================
# ALL TOOLS REGISTRY
# ============================================================

ALL_TOOLS_BY_NAME: dict[str, types.Tool] = {
    t.name: t
    for t in (
        BASE_TOOLS
        + COMPLIANCE_TOOLS
        + VALIDATION_TOOLS
        + INVESTIGATION_TOOLS
    )
}


# Tools that must always work regardless of agent assignment.
AGENT_EXEMPT_TOOLS = {"register_agent"}


def _current_agent_id(ctx) -> str | None:
    return _session_state(ctx).get("agent_id")


def _agent_tool_allowed(ctx, tool_name: str) -> bool:
    """
    Backend enforcement check.

    - No agent identified on this connection -> legacy behavior,
      nothing extra is blocked.
    - Agent identified -> the tool must be present in that
      agent's live agent_tools assignment, checked fresh against
      the database on every single call.
    """
    if tool_name in AGENT_EXEMPT_TOOLS:
        return True

    agent_id = _current_agent_id(ctx)

    if agent_id is None:
        return True

    return db.is_tool_assigned(agent_id, tool_name)


# ============================================================
# LIST TOOLS
# ============================================================

@server.list_tools()
async def list_tools():
    ctx = server.request_context
    state = _session_state(ctx)
    emp_id = state["employee_id"]

    # --------------------------------------------------------
    # Determine tools allowed by employee role
    # --------------------------------------------------------

    if emp_id is None:
        role_allowed = BASE_TOOLS

    else:
        employee = db.get_employee(emp_id)

        if employee is None:
            role_allowed = BASE_TOOLS

        elif employee["role"] in (
            "compliance_officer",
            "fraud_investigator",
        ):
            role_allowed = (
                BASE_TOOLS
                + COMPLIANCE_TOOLS
                + VALIDATION_TOOLS
                + INVESTIGATION_TOOLS
            )

        else:
            role_allowed = BASE_TOOLS

    # --------------------------------------------------------
    # Agent-specific tool assignment
    # --------------------------------------------------------

    agent_id = _current_agent_id(ctx)

    # No agent connected -> preserve legacy role-based behavior
    if agent_id is None:
        return role_allowed

    # Agent connected -> only return tools assigned to that agent
    assigned = set(db.get_agent_tools(agent_id))

    return [
        tool
        for tool in role_allowed
        if tool.name in AGENT_EXEMPT_TOOLS
        or tool.name in assigned
    ]


# ============================================================
# CALL TOOL
# ============================================================

@server.call_tool()
async def call_tool(name: str, args: dict):

    # --------------------------------------------------------
    # Validate tool arguments
    # --------------------------------------------------------

    validator = TOOL_VALIDATORS.get(name)

    if validator is not None:
        try:
            validated_args = validator.model_validate(args)
            args = validated_args.model_dump()

        except ValidationError:
            return [
                types.TextContent(
                    type="text",
                    text="Invalid tool arguments.",
                )
            ]

    # --------------------------------------------------------
    # Agent assignment enforcement
    # --------------------------------------------------------

    ctx = server.request_context

    if not _agent_tool_allowed(ctx, name):
        return [
            types.TextContent(
                type="text",
                text=(
                    f"Rejected: tool '{name}' is not assigned to "
                    f"agent '{_current_agent_id(ctx)}'. An administrator "
                    "must assign it from the platform first."
                ),
            )
        ]

    # --------------------------------------------------------
    # BASE TOOLS
    # --------------------------------------------------------

    if name == "register_agent":
        return await register_agent(args, ctx)

    if name == "login":
        return await login(args, ctx)

    if name == "get_account":
        return get_account(args)

    if name == "wire_transfer_initiate":
        return await wire_transfer(args, ctx)

    # --------------------------------------------------------
    # COMPLIANCE TOOLS
    # --------------------------------------------------------

    if name == "batch_sanctions_scan":
        return await batch_scan(args, ctx)

    if name == "get_customer_accounts":
        return get_customer_accounts(args)

    if name == "get_transaction_history":
        return get_transaction_history(args)

    if name == "check_sanctions":
        return check_sanctions(args)

    # --------------------------------------------------------
    # VALIDATION TOOL
    # --------------------------------------------------------

    if name == "validate_investigation":
        return await validate_investigation(
            task=args["task"],
            candidate=args["candidate"],
        )

    # --------------------------------------------------------
    # SUSPICIOUS ACTIVITY INVESTIGATION TOOLS
    # --------------------------------------------------------

    if name == "get_related_employees":
        return get_related_employees(args)

    if name == "get_customer_wire_history":
        return get_customer_wire_history(args)

    if name == "create_investigation":
        return await create_investigation_tool(args)

    if name == "get_investigation":
        return get_investigation_tool(args)

    if name == "submit_investigation_evidence":
        return await submit_investigation_evidence_tool(args)

    raise ValueError(f"unknown tool: {name}")


# ============================================================
# RESOURCES
# ============================================================

@server.list_resources()
async def list_resources():
    return [
        types.Resource(
            uri=WIRE_TRANSFER_POLICY_URI,
            name="Wire Transfer Escalation Policy",
            description=(
                "Internal compliance policy defining "
                "sanctions, structuring, self-dealing, "
                "and authority-limit rules."
            ),
            mimeType="text/markdown",
        )
    ]


@server.read_resource()
async def read_resource(uri: str):
    if str(uri) == WIRE_TRANSFER_POLICY_URI:
        return WIRE_TRANSFER_POLICY
    raise ValueError(f"unknown resource: {uri}")


# ============================================================
# PROMPTS
# ============================================================

@server.list_prompts()
async def list_prompts():
    return [
        types.Prompt(
            name=COMPLIANCE_HOLD_PROMPT_NAME,
            description=(
                "Draft a customer-facing explanation "
                "for why a wire transfer was held."
            ),
            arguments=[
                types.PromptArgument(
                    name="transfer_id",
                    description="The held wire's transfer_id",
                    required=True,
                ),
            ],
        )
    ]


@server.get_prompt()
async def get_prompt(name: str, arguments: dict | None):
    if name != COMPLIANCE_HOLD_PROMPT_NAME:
        raise ValueError(f"unknown prompt: {name}")

    transfer_id = (arguments or {}).get("transfer_id", "{transfer_id}")

    text = (
        f"Write a short, professional message to a "
        f"Sterling & Vance customer explaining that "
        f"wire transfer #{transfer_id} has been placed "
        f"on hold pending compliance review. "
        f"Do not state the specific flag reason. "
        f"Only say that additional review is required "
        f"by policy, and give a realistic turnaround "
        f"time of 1-2 business days."
    )

    return types.GetPromptResult(
        description=f"Compliance hold notice for transfer #{transfer_id}",
        messages=[
            types.PromptMessage(
                role="user",
                content=types.TextContent(type="text", text=text),
            )
        ],
    )


# ============================================================
# LOGIN
# ============================================================

async def login(args, ctx):

    employee = db.get_employee(args["employee_id"])

    if employee is None:
        return [
            types.TextContent(type="text", text="No employee with that ID.")
        ]

    gains_tools = employee["role"] in (
        "compliance_officer",
        "fraud_investigator",
    )

    _session_state(ctx)["employee_id"] = employee["employee_id"]

    if gains_tools:
        await ctx.session.send_tool_list_changed()
        return [
            types.TextContent(
                type="text",
                text=(
                    f"Logged in as {employee['name']} "
                    f"({employee['role']}). "
                    f"Compliance tools unlocked."
                ),
            )
        ]

    return [
        types.TextContent(
            type="text",
            text=f"Logged in as {employee['name']} ({employee['role']}).",
        )
    ]


# ============================================================
# ISSUE #98: REGISTER AGENT
# ============================================================

async def register_agent(args, ctx):

    agent_id = args["agent_id"]
    name = args.get("name") or agent_id
    description = args.get("description")

    existing = db.get_agent(agent_id)

    if existing is None:
        db.create_agent(
            agent_id=agent_id,
            name=name,
            description=description,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    state = _session_state(ctx)

    # If this connection had previously registered as a *different*
    # agent_id, drop it from that agent's live-session set first so
    # the registry doesn't leak a stale mapping.
    previous_agent_id = state.get("agent_id")
    if previous_agent_id and previous_agent_id != agent_id:
        AGENT_LIVE_SESSIONS.get(previous_agent_id, set()).discard(ctx.session)

    state["agent_id"] = agent_id
    AGENT_LIVE_SESSIONS[agent_id].add(ctx.session)

    await ctx.session.send_tool_list_changed()

    assigned_count = len(db.get_agent_tools(agent_id))

    return [
        types.TextContent(
            type="text",
            text=(
                f"Agent '{agent_id}' connected "
                f"({assigned_count} tool(s) currently assigned). "
                "Tool access is now scoped to this agent's "
                "admin-managed assignments."
            ),
        )
    ]


def get_account(args):

    account = db.get_account(args["account_id"])

    if account is None:
        return [types.TextContent(type="text", text="Account not found.")]

    return [
        types.TextContent(
            type="text",
            text=(
                f"Account {account['account_id']}: "
                f"balance {account['balance']:.2f}"
            ),
        )
    ]


# ============================================================
# INVESTIGATION TOOLS
# ============================================================

def get_customer_accounts(args):

    accounts = db.get_customer_accounts(args["customer_id"])

    if not accounts:
        return [
            types.TextContent(
                type="text",
                text=f"No accounts found for customer {args['customer_id']}.",
            )
        ]

    lines = [
        (
            f"- account {a['account_id']} "
            f"({a['account_type']}): "
            f"balance {a['balance']:.2f}"
        )
        for a in accounts
    ]

    return [
        types.TextContent(
            type="text",
            text=(
                f"Accounts for customer {args['customer_id']}:\n"
                + "\n".join(lines)
            ),
        )
    ]


def get_transaction_history(args):

    history = db.get_transaction_history(args["account_id"])

    return [
        types.TextContent(
            type="text",
            text=(
                history
                or f"No transactions found for account {args['account_id']}."
            ),
        )
    ]


def check_sanctions(args):

    country = args["destination_country"]
    hit = db.is_sanctioned(country)

    return [
        types.TextContent(
            type="text",
            text=f"{country}: {'SANCTIONED' if hit else 'clear'}",
        )
    ]

# Suspicious Activity Investigation additions

def get_related_employees(args):
    employees = db.get_related_employees(args["customer_id"])

    if not employees:
        return [
            types.TextContent(
                type="text",
                text=f"No employees related to customer {args['customer_id']}.",
            )
        ]

    lines = [
        f"- employee {e['employee_id']} ({e['name']}, {e['role']})"
        for e in employees
    ]

    return [
        types.TextContent(
            type="text",
            text=(
                f"Employees related to customer {args['customer_id']}:\n"
                + "\n".join(lines)
            ),
        )
    ]


def get_customer_wire_history(args):
    accounts = db.get_customer_accounts(args["customer_id"])
    account_ids = [a["account_id"] for a in accounts]
    wires = db.get_customer_wire_transfers(account_ids)

    if not wires:
        return [
            types.TextContent(
                type="text",
                text=f"No wire transfers found for customer {args['customer_id']}.",
            )
        ]

    lines = [
        f"- transfer #{w['transfer_id']}: ${w['amount']:.2f} -> "
        f"{w['destination_country']} status={w['status']} "
        f"flags={w['flag_reason'] or 'none'}"
        for w in wires
    ]

    return [
        types.TextContent(
            type="text",
            text=(
                f"Wire transfers for customer {args['customer_id']}:\n"
                + "\n".join(lines)
            ),
        )
    ]


def get_investigation_tool(args):
    row = db.get_investigation(args["investigation_id"])

    if row is None:
        return [
            types.TextContent(
                type="text",
                text=f"No investigation #{args['investigation_id']}.",
            )
        ]

    return [
        types.TextContent(
            type="text",
            text=(
                f"Investigation #{row['investigation_id']} "
                f"(customer {row['customer_id']}): status={row['status']}, "
                f"risk_level={row['risk_level']}, "
                f"decision={row['decision'] or 'pending'}."
            ),
        )
    ]


# create_investigation and submit_investigation_evidence are the two
# tools that actually drive the state graph, not just touch the DB —
# calling db.create_investigation() directly here (bypassing the graph
# runner) would create an orphaned investigations row with no
# thread_id, one the graph never actually manages. So these import
# investigation_graph_runner and call INTO it.
#
# That import is deliberately done HERE, inside the function body, not
# at the top of server.py: investigation_graph_runner.py ->
# investigation_graph.py -> investigation_lats.py, which itself lazily
# imports `from server import validate_investigation` inside its own
# function body for the exact same reason (see investigation_lats.py's
# comment above reassess_investigation()). Both sides import lazily so
# neither module has to fully exist yet at the other's import time —
# only at actual call time, by which point both are already loaded.

async def create_investigation_tool(args):
    from state_graph.suspicious_activity.investigation_graph_runner import (
        start_investigation,
    )

    result = await start_investigation(
        customer_id=args["customer_id"],
        reason=args["reason"],
    )

    return [
        types.TextContent(
            type="text",
            text=(
                f"Investigation #{result.get('investigation_id')} opened "
                f"for customer {args['customer_id']}. Status: {result.get('status')}."
                + (
                    f" Paused: {result['interrupt'].get('reason')}."
                    if result.get("status") == "paused"
                    else ""
                )
            ),
        )
    ]


async def submit_investigation_evidence_tool(args):
    from state_graph.suspicious_activity.investigation_graph_runner import (
        submit_external_evidence,
    )

    result = await submit_external_evidence(
        investigation_id=args["investigation_id"],
        evidence={args["evidence_type"]: {
            "evidence_data": args["evidence_data"],
            "source": args["source"],
        }},
    )

    return [
        types.TextContent(
            type="text",
            text=(
                f"Evidence submitted for investigation #{args['investigation_id']}. "
                f"Status: {result.get('status')}."
            ),
        )
    ]


# ============================================================
# SAMPLING
# ============================================================

def client_supports_sampling(ctx) -> bool:
    try:
        caps = ctx.session.client_params.capabilities
        return caps is not None and caps.sampling is not None
    except AttributeError:
        return False


def client_supports_elicitation(ctx) -> bool:
    try:
        caps = ctx.session.client_params.capabilities
        return caps is not None and caps.elicitation is not None
    except AttributeError:
        return False


async def analyze_wire_risk(transaction_history: str, ctx) -> str:

    if not client_supports_sampling(ctx):
        return (
            "Risk Assessment: medium\n"
            "Analysis: client does not declare "
            "sampling support; falling back to "
            "rule-based risk assessment."
        )

    result = await ctx.session.create_message(
        messages=[
            types.SamplingMessage(
                role="user",
                content=types.TextContent(
                    type="text",
                    text=(
                        "You are a fraud analysis assistant. "
                        "Classify this transaction history's "
                        "risk as LOW, MEDIUM, or HIGH and "
                        "explain briefly.\n\n"
                        f"Transaction history:\n{transaction_history}"
                    ),
                ),
            )
        ],
        max_tokens=200,
    )

    analysis = result.content.text

    print(f"\n[SAMPLING] AI risk analysis:\n{analysis}\n", file=sys.stderr)

    risk = (
        "high"
        if "HIGH" in analysis.upper()
        else "medium"
        if "MEDIUM" in analysis.upper()
        else "low"
    )

    return f"Risk Assessment: {risk}\n\nAnalysis:\n{analysis}"


# ============================================================
# GROUNDED VALIDATION HELPERS
# ============================================================

def _extract_ids(text: str, patterns: list[str]) -> list[int]:
    ids: set[int] = set()
    for pattern in patterns:
        for match in re.findall(pattern, text, re.IGNORECASE):
            try:
                ids.add(int(match))
            except ValueError:
                continue
    return sorted(ids)


def _extract_status(text: str) -> str | None:
    text_lower = text.lower()
    statuses = {"pending_manual_review", "approved", "rejected"}
    for status in statuses:
        if status in text_lower:
            return status
    aliases = {
        "pending": "pending_manual_review",
        "held": "pending_manual_review",
        "on hold": "pending_manual_review",
    }
    for alias, status in aliases.items():
        if alias in text_lower:
            return status
    return None


def _extract_amount(text: str) -> float | None:
    match = re.search(
        r"(?:amount|value)\s*[:=]?\s*\$?\s*([\d,]+(?:\.\d+)?)",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    return float(match.group(1).replace(",", ""))


def _extract_balance(text: str) -> float | None:
    match = re.search(
        r"(?:balance|available balance)\s*[:=]?\s*\$?\s*([\d,]+(?:\.\d+)?)",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    return float(match.group(1).replace(",", ""))


# ============================================================
# VALIDATE INVESTIGATION
# ============================================================

async def validate_investigation(task: str, candidate: str) -> dict[str, Any]:

    if not task.strip():
        return {"success": False, "details": ["Validation task is empty."]}

    if not candidate.strip():
        return {"success": False, "details": ["Candidate result is empty."]}

    checks: list[bool] = []
    details: list[str] = [
        "SOURCE OF TRUTH: Sterling & Vance real SQLite database."
    ]

    customer_ids = _extract_ids(
        candidate,
        [r"customer\s*#?\s*(\d+)", r"customer_id\s*[:=]\s*(\d+)"],
    )

    customer_accounts: dict[int, list[dict]] = {}

    for customer_id in customer_ids:
        accounts = db.get_customer_accounts(customer_id)
        customer_accounts[customer_id] = accounts

        if not accounts:
            checks.append(False)
            details.append(
                f"Grounded DB check failed: "
                f"no accounts found for customer #{customer_id}."
            )
        else:
            checks.append(True)
            details.append(
                f"Grounded DB check passed: "
                f"customer #{customer_id} has {len(accounts)} account(s)."
            )

    transaction_ids = _extract_ids(
        candidate,
        [
            r"transaction\s*#?\s*(\d+)",
            r"transaction_id\s*[:=]\s*(\d+)",
            r"txn\s*#?\s*(\d+)",
            r"txn_id\s*[:=]\s*(\d+)",
        ],
    )

    if transaction_ids:
        account_ids = _extract_ids(
            candidate,
            [r"account\s*#?\s*(\d+)", r"account_id\s*[:=]\s*(\d+)"],
        )

        if account_ids:
            for account_id in account_ids:
                history = db.get_transaction_history(account_id)

                if history and history != "No recent transactions found.":
                    checks.append(True)
                    details.append(
                        f"Transaction evidence check passed for "
                        f"account #{account_id}."
                    )
                else:
                    checks.append(False)
                    details.append(
                        f"Transaction evidence check failed for "
                        f"account #{account_id}."
                    )
        else:
            checks.append(False)
            details.append(
                "Transaction IDs were referenced but "
                "no account ID was provided."
            )

    transfer_ids = _extract_ids(
        candidate,
        [
            r"transfer\s*#?\s*(\d+)",
            r"wire\s*#?\s*(\d+)",
            r"transfer_id\s*[:=]\s*(\d+)",
            r"wire_transfer_id\s*[:=]\s*(\d+)",
        ],
    )

    for transfer_id in transfer_ids:
        row = db.get_wire_transfer(transfer_id)

        if row is None:
            checks.append(False)
            details.append(f"Wire transfer #{transfer_id} does not exist.")
        else:
            checks.append(True)
            details.append(f"Wire transfer #{transfer_id} exists.")

    account_ids = _extract_ids(
        candidate,
        [r"account\s*#?\s*(\d+)", r"account_id\s*[:=]\s*(\d+)"],
    )

    for account_id in account_ids:
        row = db.get_account(account_id)

        if row is None:
            checks.append(False)
            details.append(f"Account #{account_id} does not exist.")
        else:
            checks.append(True)
            details.append(f"Account #{account_id} exists.")

    employee_ids = _extract_ids(
        candidate,
        [r"employee\s*#?\s*(\d+)", r"employee_id\s*[:=]\s*(\d+)"],
    )

    for employee_id in employee_ids:
        row = db.get_employee(employee_id)

        if row is None:
            checks.append(False)
            details.append(f"Employee #{employee_id} does not exist.")
        else:
            checks.append(True)
            details.append(f"Employee #{employee_id} exists.")

    if not (
        customer_ids or transfer_ids or account_ids
        or transaction_ids or employee_ids
    ):
        checks.append(False)
        details.append("Candidate does not reference a concrete banking object.")

    success = bool(checks) and all(checks)

    details.append(
        "All grounded database checks passed."
        if success
        else "At least one grounded database check failed."
    )

    return {"success": success, "details": details}


# ============================================================
# WIRE TRANSFER
# ============================================================

async def wire_transfer(args, ctx):

    state = _session_state(ctx)
    emp_id = state["employee_id"]

    if emp_id is None:
        return [
            types.TextContent(type="text", text="Rejected: no one is logged in.")
        ]

    if args["employee_id"] != emp_id:
        return [
            types.TextContent(
                type="text",
                text="Rejected: employee_id doesn't match this session.",
            )
        ]

    employee = db.get_employee(emp_id)
    source = db.get_account(args["source_account_id"])
    amount = args["amount"]

    if source is None:
        return [
            types.TextContent(
                type="text", text="Rejected: source account doesn't exist."
            )
        ]

    if source["balance"] < amount:
        return [
            types.TextContent(type="text", text="Rejected: insufficient funds.")
        ]

    limit = db.WIRE_AUTHORITY_LIMIT[employee["role"]]

    if amount > limit:
        return [
            types.TextContent(
                type="text",
                text=(
                    f"Rejected: {amount:.2f} exceeds "
                    f"{employee['role']}'s limit of {limit}."
                ),
            )
        ]

    flags = []

    if db.is_sanctioned(args["destination_country"]):
        flags.append("sanctions")

    if db.looks_like_structuring(source["account_id"]):
        flags.append("structuring")

    if db.is_self_dealing(employee):
        flags.append("self_dealing")

    if flags:
        history = db.get_transaction_history(source["account_id"])
        analysis = await analyze_wire_risk(history, ctx)

        if "HIGH" in analysis.upper():
            flags.append("ai_high_risk")

    timestamp = datetime.now(timezone.utc).isoformat()

    if flags:
        transfer_id = db.insert_wire_transfer(
            source_account_id=source["account_id"],
            destination_account_num=args["destination_account_num"],
            destination_country=args["destination_country"],
            amount=amount,
            status="pending_manual_review",
            flag_reason=",".join(flags),
            initiated_by=emp_id,
            approved_by=None,
            timestamp=timestamp,
        )

        if not client_supports_elicitation(ctx):
            return [
                types.TextContent(
                    type="text",
                    text=(
                        f"Wire #{transfer_id} held (flags: {', '.join(flags)}). "
                        "This client does not support human approval."
                    ),
                )
            ]

        result = await ctx.session.elicit(
            message=(
                "High-risk wire transfer detected.\n\n"
                f"Flags: {', '.join(flags)}\n\n"
                "Approve this transfer?"
            ),
            requestedSchema=types.ElicitRequestedSchema(
                type="object",
                properties={
                    "approved": {
                        "type": "boolean",
                        "description": "Approve or reject this transfer",
                    }
                },
                required=["approved"],
                additionalProperties=False,
            ),
        )

        approved = (
            result.action == "accept"
            and bool(result.content.get("approved"))
        )

        db.insert_compliance_review(
            transfer_id=transfer_id,
            reviewer_id=emp_id,
            decision="approved" if approved else "rejected",
            notes=f"Elicited human decision for flags: {', '.join(flags)}",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        if not approved:
            db.set_wire_approver(transfer_id, approved_by=emp_id, status="rejected")
            return [
                types.TextContent(
                    type="text",
                    text=f"Wire #{transfer_id} cancelled by human reviewer.",
                )
            ]

        db.debit_account(source["account_id"], amount)
        db.set_wire_approver(transfer_id, approved_by=emp_id, status="approved")

        return [
            types.TextContent(
                type="text",
                text=(
                    f"Wire #{transfer_id} of {amount:.2f} approved "
                    "after compliance review."
                ),
            )
        ]

    transfer_id = db.insert_wire_transfer(
        source_account_id=source["account_id"],
        destination_account_num=args["destination_account_num"],
        destination_country=args["destination_country"],
        amount=amount,
        status="approved",
        flag_reason=None,
        initiated_by=emp_id,
        approved_by=None,
        timestamp=timestamp,
    )

    db.debit_account(source["account_id"], amount)

    return [
        types.TextContent(
            type="text",
            text=f"Wire #{transfer_id} of {amount:.2f} approved.",
        )
    ]


# ============================================================
# PROGRESS TRACKING
# ============================================================

async def batch_scan(args, ctx):

    employee = db.get_employee(args["employee_id"])

    if employee is None or employee["role"] not in (
        "compliance_officer",
        "fraud_investigator",
    ):
        return [
            types.TextContent(
                type="text",
                text="Rejected: requires compliance or fraud investigator role.",
            )
        ]

    total = db.get_transaction_count()

    progress_token = (
        getattr(ctx.meta, "progressToken", None) if ctx.meta else None
    )

    for scanned in range(1, total + 1):
        await asyncio.sleep(0.1)

        if progress_token is not None:
            await ctx.session.send_progress_notification(
                progress_token=progress_token,
                progress=scanned,
                total=total,
            )

    return [
        types.TextContent(type="text", text=f"Scanned {total} transactions.")
    ]


# ============================================================
# MCP INITIALIZATION OPTIONS
# ============================================================

def build_init_options():
    return server.create_initialization_options(
        notification_options=NotificationOptions(tools_changed=True),
        experimental_capabilities={},
    )


_original_create_initialization_options = server.create_initialization_options


def _create_initialization_options_with_our_defaults(*args, **kwargs):
    kwargs.setdefault(
        "notification_options", NotificationOptions(tools_changed=True)
    )
    kwargs.setdefault("experimental_capabilities", {})
    return _original_create_initialization_options(*args, **kwargs)


server.create_initialization_options = (
    _create_initialization_options_with_our_defaults
)


# ============================================================
# ISSUE #98 FIX (B): MCP HTTP TRANSPORT MOUNTED INTO THE ADMIN APP
# ============================================================
#
# Same process as /invoke, /sanctions/resume and the new /admin/*
# routes below, via FastAPI's lifespan + .mount(). This is what
# makes AGENT_LIVE_SESSIONS / _notify_agent_tools_changed actually
# work: the admin endpoint and the live agent connection are two
# request handlers inside the same Python process, sharing the
# same in-memory registry.

mcp_session_manager = StreamableHTTPSessionManager(app=server)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with mcp_session_manager.run():
        yield


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/mcp", app=mcp_session_manager.handle_request)


# ============================================================
# ADMIN: AGENT & TOOL MANAGEMENT (ISSUE #98)
# ============================================================

class ToolAssignRequest(BaseModel):
    tool_name: str


@app.get("/admin/tools")
async def admin_list_all_tools():
    """Full catalog of tools this MCP server knows how to serve,
    i.e. what an admin is allowed to pick from when assigning."""
    return [
        {"name": t.name, "description": t.description}
        for t in ALL_TOOLS_BY_NAME.values()
        if t.name not in AGENT_EXEMPT_TOOLS
    ]


@app.get("/admin/agents")
async def admin_list_agents():
    """Every agent that has ever self-registered, each with its
    currently assigned tools and whether it is connected right
    now (i.e. has a live MCP session on this process)."""
    # BUG FIX: db_access.py's real function is get_agents(), not
    # list_agents() - this line was raising AttributeError on every
    # call before this fix.
    agents = db.get_agents()

    return [
        {
            **agent,
            "connected": len(AGENT_LIVE_SESSIONS.get(agent["agent_id"], ())) > 0,
            "assigned_tools": db.get_agent_tools(agent["agent_id"]),
        }
        for agent in agents
    ]


@app.get("/admin/agents/{agent_id}/tools")
async def admin_get_agent_tools(agent_id: str):
    agent = db.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Unknown agent.")

    return {
        "agent_id": agent_id,
        "assigned_tools": db.get_agent_tools(agent_id),
    }


@app.post("/admin/agents/{agent_id}/tools")
async def admin_assign_tool(agent_id: str, body: ToolAssignRequest):
    agent = db.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Unknown agent.")

    if body.tool_name not in ALL_TOOLS_BY_NAME or body.tool_name in AGENT_EXEMPT_TOOLS:
        raise HTTPException(
            status_code=400, detail=f"Unknown tool: {body.tool_name}"
        )

    # BUG FIX: db_access.py's real function is add_agent_tool(), not
    # assign_tool_to_agent() - same AttributeError issue as above.
    db.add_agent_tool(agent_id, body.tool_name)
    await _notify_agent_tools_changed(agent_id)

    return {
        "agent_id": agent_id,
        "assigned_tools": db.get_agent_tools(agent_id),
    }


@app.delete("/admin/agents/{agent_id}/tools/{tool_name}")
async def admin_unassign_tool(agent_id: str, tool_name: str):
    agent = db.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Unknown agent.")

    # BUG FIX: db_access.py's real function is remove_agent_tool(),
    # not remove_tool_from_agent().
    db.remove_agent_tool(agent_id, tool_name)
    await _notify_agent_tools_changed(agent_id)

    return {
        "agent_id": agent_id,
        "assigned_tools": db.get_agent_tools(agent_id),
    }


# ============================================================
# ADMIN: HITL TASKS & WORKFLOW TICKETS (ISSUE #98 completion)
# ============================================================
#
# Completes the third admin bullet: an admin opens a pending HITL
# request or an open failure ticket, sees the graph's persisted
# state at the point it paused/failed, acts on it, and the
# underlying run resumes.
#
# Scope: wired up for workflow_type == "sanctions_review" only -
# that's the sanctions_change durable workflow, whose runner
# (sanctions_graph_runner.py) already has a real checkpointer and
# real resume functions. human_review_tasks / workflow_tickets rows
# created by the suspicious_activity/investigation graph use a
# different workflow_type and a different graph instance; wiring
# those up is a separate, later change - the detail endpoints below
# say so explicitly for that workflow_type instead of silently
# doing nothing.
#
# human_review_tasks / workflow_tickets don't have db_access.py
# getters for a single row by id (only create/complete/resolve), so
# small local read helpers are added here rather than guessing at
# a db_access.py change that wasn't requested this round.

def _get_human_review_task(task_id: int) -> dict | None:
    conn = db.get_conn()
    row = conn.execute(
        "SELECT * FROM human_review_tasks WHERE task_id = ?",
        (task_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def _list_human_review_tasks() -> list[dict]:
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT * FROM human_review_tasks ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def _get_workflow_ticket(ticket_id: int) -> dict | None:
    conn = db.get_conn()
    row = conn.execute(
        "SELECT * FROM workflow_tickets WHERE ticket_id = ?",
        (ticket_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def _list_workflow_tickets() -> list[dict]:
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT * FROM workflow_tickets ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def _serialize_graph_snapshot(snapshot) -> dict:
    """The bits of a LangGraph StateSnapshot that are actually
    useful to an admin looking at a paused/failed run: the full
    persisted state values, and what node(s) it's waiting on."""
    return {
        "values": snapshot.values,
        "next": list(snapshot.next),
        "is_paused": bool(snapshot.next),
    }


SANCTIONS_WORKFLOW_TYPE = "sanctions_review"


@app.get("/admin/hitl")
async def admin_list_hitl_tasks():
    """Every HITL task, oldest-decision-needed-ish ordering left to
    the frontend (createdAt is included) - both pending and
    completed, so the admin platform can show the full history."""
    return _list_human_review_tasks()


@app.get("/admin/hitl/{task_id}")
async def admin_get_hitl_task(task_id: int):
    """A single HITL task plus the graph's persisted state at
    (or since) the point it paused - not just the DB row."""
    task = _get_human_review_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Unknown HITL task.")

    if task["workflow_type"] != SANCTIONS_WORKFLOW_TYPE:
        return {
            "task": task,
            "graph_state": None,
            "note": (
                f"Live graph-state lookup isn't wired up for "
                f"workflow_type={task['workflow_type']!r} yet - only "
                f"{SANCTIONS_WORKFLOW_TYPE!r} is."
            ),
        }

    thread_id = sanctions_default_thread_id(task["wire_id"])
    snapshot = await sanctions_get_review_state(
        wire_id=task["wire_id"],
        thread_id=thread_id,
    )

    return {
        "task": task,
        "thread_id": thread_id,
        "graph_state": _serialize_graph_snapshot(snapshot),
    }


class HitlDecisionRequest(BaseModel):
    decision: str  # "approved" | "rejected" | "modified"
    admin_id: int
    notes: str = ""


@app.post("/admin/hitl/{task_id}/resume")
async def admin_resume_hitl_task(task_id: int, body: HitlDecisionRequest):
    """Act on a pending HITL task and resume the exact paused run.

    This calls back into the SAME durable graph/checkpointer that
    paused it (via sanctions_graph_runner) - it is not starting a
    new run, it's continuing the interrupted one from its persisted
    checkpoint."""
    task = _get_human_review_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Unknown HITL task.")

    if task["workflow_type"] != SANCTIONS_WORKFLOW_TYPE:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Resume isn't wired up for workflow_type="
                f"{task['workflow_type']!r} yet."
            ),
        )

    if task["status"] == "completed":
        raise HTTPException(
            status_code=400,
            detail="This HITL task is already completed.",
        )

    try:
        result = await sanctions_resume_after_admin(
            wire_id=task["wire_id"],
            decision=body.decision,
            admin_id=body.admin_id,
            notes=body.notes,
            thread_id=sanctions_default_thread_id(task["wire_id"]),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to resume HITL task: {str(e)}",
        )

    # sanctions_resume_after_admin() already calls
    # db.complete_human_review_task() internally once the graph
    # confirms hitl_task_id - re-read the row so the response
    # reflects the post-resume state, not the pre-resume one.
    updated_task = _get_human_review_task(task_id)

    return {
        "task": updated_task,
        "graph_result": result,
    }


@app.get("/admin/tickets")
async def admin_list_tickets():
    return _list_workflow_tickets()


@app.get("/admin/tickets/{ticket_id}")
async def admin_get_ticket(ticket_id: int):
    """A single failure ticket plus the graph's persisted state at
    the point it failed."""
    ticket = _get_workflow_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Unknown ticket.")

    if ticket["workflow_type"] != SANCTIONS_WORKFLOW_TYPE:
        return {
            "ticket": ticket,
            "graph_state": None,
            "note": (
                f"Live graph-state lookup isn't wired up for "
                f"workflow_type={ticket['workflow_type']!r} yet - only "
                f"{SANCTIONS_WORKFLOW_TYPE!r} is."
            ),
        }

    thread_id = sanctions_default_thread_id(ticket["wire_id"])
    snapshot = await sanctions_get_review_state(
        wire_id=ticket["wire_id"],
        thread_id=thread_id,
    )

    return {
        "ticket": ticket,
        "thread_id": thread_id,
        "graph_state": _serialize_graph_snapshot(snapshot),
    }


class TicketResolveRequest(BaseModel):
    notes: str = ""


@app.post("/admin/tickets/{ticket_id}/resume")
async def admin_resume_ticket(ticket_id: int, body: TicketResolveRequest):
    """Mark a failure ticket resolved and resume the exact run that
    failed, from its persisted checkpoint - same durable-graph
    pattern as the HITL resume above."""
    ticket = _get_workflow_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Unknown ticket.")

    if ticket["workflow_type"] != SANCTIONS_WORKFLOW_TYPE:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Resume isn't wired up for workflow_type="
                f"{ticket['workflow_type']!r} yet."
            ),
        )

    if ticket["status"] == "resolved":
        raise HTTPException(
            status_code=400, detail="This ticket is already resolved."
        )

    try:
        result = await sanctions_resume_after_ticket(
            wire_id=ticket["wire_id"],
            notes=body.notes,
            thread_id=sanctions_default_thread_id(ticket["wire_id"]),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to resume ticket: {str(e)}",
        )

    updated_ticket = _get_workflow_ticket(ticket_id)

    return {
        "ticket": updated_ticket,
        "graph_result": result,
    }


# ============================================================
# FRONTEND / AGENT GATEWAY  (unchanged from before)
# ============================================================

@app.post("/invoke")
async def invoke_agent(data: dict):

    agent_name = data.get("agent_name")
    message = data.get("message")
    thread_id = data.get("thread_id") or "default-thread"

    if not agent_name or not message:
        raise HTTPException(
            status_code=400, detail="Missing agent_name or message."
        )

    if agent_name == "customer-risk-monitoring":

        try:
            customer_id = extract_customer_id(message)

            config = {
                "configurable": {"thread_id": f"customer-risk:{thread_id}"}
            }

            existing = customer_risk_graph.get_state(config)

            if existing.next:
                response_text = (
                    "This Customer Risk review is currently paused "
                    "awaiting admin action (Human-in-the-Loop). "
                    "Please resolve it from the admin panel."
                )
            else:
                initial_state = {
                    "run_id": thread_id,
                    "customer_id": customer_id,
                    "message": message,
                    "last_processed_transaction_id": None,
                    "checkpoint_version": 0,
                }

                result = customer_risk_graph.invoke(initial_state, config=config)

                response_text = (
                    "Customer Risk Monitoring\n\n"
                    f"Customer ID: {customer_id}\n"
                    f"Status: {result.get('status', 'N/A')}\n"
                    f"Current Risk: {result.get('current_risk_level', 'N/A')}\n"
                    f"Assessed Risk: {result.get('assessed_risk_level', 'N/A')}\n"
                    f"Confidence: {result.get('assessment_confidence', 'N/A')}\n"
                    f"Reason: {result.get('risk_reason', 'N/A')}"
                )

            return {"response": response_text, "thread_id": thread_id}

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Customer Risk Graph failed: {str(e)}"
            )

    elif agent_name == "sanctions-change":

        try:
            wire_id = extract_wire_id(message)
            sanctions_thread_id = f"sanctions:{thread_id}:{wire_id}"
            config = {"configurable": {"thread_id": sanctions_thread_id}}

            existing_state = sanctions_graph.get_state(config)

            if existing_state.next:
                graph_state = existing_state.values or {}
                current_node = graph_state.get("current_node", "Unknown")
                status = graph_state.get("status", "waiting")

                response_text = (
                    "Sanctions Review\n\n"
                    f"Wire ID: {wire_id}\n"
                    f"Status: {status}\n"
                    f"Current Step: {current_node}\n\n"
                    "This review is currently waiting for "
                    "human or external-event input."
                )
            else:
                initial_state = {
                    "run_id": thread_id,
                    "wire_id": wire_id,
                    "review_id": None,
                    "status": "analyzing",
                    "pending_event": None,
                    "event_id": None,
                    "sanctions_changed": False,
                    "hitl_required": False,
                    "hitl_task_id": None,
                    "hitl_reason": None,
                    "recommended_action": None,
                    "admin_decision": None,
                    "admin_id": None,
                    "admin_notes": "",
                    "failure_resolved": False,
                    "failure_resolution_notes": "",
                    "failed_node": None,
                    "error_type": None,
                    "error_message": None,
                    "failure": None,
                    "retrieved_policy": [],
                    "investigation_history": [],
                    "investigation_steps": 0,
                    "current_node": "start",
                    "updated_at": None,
                }

                result = sanctions_graph.invoke(initial_state, config=config)

                response_text = (
                    "Sanctions Review\n\n"
                    f"Wire ID: {wire_id}\n"
                    f"Status: {result.get('status', 'N/A')}\n"
                    f"Risk Level: {result.get('risk_level', 'N/A')}\n"
                    f"Decision: {result.get('decision', 'N/A')}\n"
                    f"Recommended Action: {result.get('recommended_action', 'N/A')}\n"
                    f"Analysis: {result.get('analysis', 'N/A')}"
                )

            return {
                "response": response_text,
                "thread_id": thread_id,
                "wire_id": wire_id,
            }

        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Sanctions State Graph failed: {str(e)}"
            )

    elif agent_name == "planning-decomposition":
        response_text = f"[Planning Decomposition Live Agent] Processed: {message}"

    elif agent_name == "memory-rag":
        response_text = f"[Memory & RAG Live Agent] Processed: {message}"

    else:
        raise HTTPException(status_code=400, detail=f"Unknown agent: {agent_name}")

    return {"response": response_text, "thread_id": thread_id}


@app.post("/sanctions/resume")
async def resume_sanctions(data: dict):

    thread_id = data.get("thread_id")
    wire_id = data.get("wire_id")
    resume_data = data.get("resume")

    if not thread_id:
        raise HTTPException(status_code=400, detail="Missing thread_id.")
    if wire_id is None:
        raise HTTPException(status_code=400, detail="Missing wire_id.")
    if resume_data is None:
        raise HTTPException(status_code=400, detail="Missing resume data.")

    sanctions_thread_id = f"sanctions:{thread_id}:{wire_id}"
    config = {"configurable": {"thread_id": sanctions_thread_id}}

    try:
        result = sanctions_graph.invoke(Command(resume=resume_data), config=config)

        return {
            "response": "Sanctions review resumed successfully.",
            "thread_id": thread_id,
            "wire_id": wire_id,
            "status": result.get("status", "N/A"),
            "result": result,
        }

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to resume sanctions review: {str(e)}"
        )


# ============================================================
# STDIO TRANSPORT (dev/local only)
# ============================================================
#
# NOTE: this spins up the MCP server as its own process/stdio
# pipe, separate from the `app` FastAPI process above - fine for
# quick manual testing with an MCP Inspector, but an agent
# connected this way will NOT show up as "connected" in
# /admin/agents (that registry lives inside the `app` process) and
# won't receive live push notifications from admin actions. Use
# the HTTP transport (mounted at /mcp inside `app`, see below) for
# anything the admin platform needs to see.

async def run_stdio():
    async with stdio_server() as (read, write):
        await server.run(read, write, build_init_options())


# ============================================================
# MAIN
# ============================================================
#
# TRANSPORT=stdio -> standalone stdio server, admin platform blind
#                     to it (dev/testing only, see note above).
# TRANSPORT=http (default) -> uvicorn serves `app`, which contains
#                     /invoke, /sanctions/resume, /admin/*, AND the
#                     live MCP endpoint at /mcp. This is the mode
#                     the admin platform needs.

async def main():
    transport = os.getenv("TRANSPORT", "http").lower()

    if transport == "stdio":
        await run_stdio()
        return

    import uvicorn

    config = uvicorn.Config(
        app,
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        log_level="info",
    )
    await uvicorn.Server(config).serve()


if __name__ == "__main__":
    asyncio.run(main())