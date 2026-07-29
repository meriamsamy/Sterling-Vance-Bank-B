"""
Sterling & Vance wire transfer server.

Covers 3 protocol concerns:
- notifications: new tools show up once a compliance/fraud employee logs in
- progress tracking: the sanctions scan reports as it goes instead of going silent
- defensive design: wire_transfer_initiate double-checks everything itself

Run: pip install mcp && python server.py
"""

import asyncio

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

import db_access as db
from schemas import LOGIN_SCHEMA, GET_ACCOUNT_SCHEMA, WIRE_TRANSFER_SCHEMA, BATCH_SCAN_SCHEMA

server = Server("sterling-vance-wire-server")

# session state is just "who's logged in right now" - one connection, one employee
session = {"employee_id": None}

BASE_TOOLS = [
    types.Tool(name="login", description="Log in as an employee for this session.", inputSchema=LOGIN_SCHEMA),
    types.Tool(name="get_account", description="Look up an account (read-only).", inputSchema=GET_ACCOUNT_SCHEMA),
    types.Tool(name="wire_transfer_initiate", description="Send a wire transfer. High-risk wires get held for review.", inputSchema=WIRE_TRANSFER_SCHEMA),
]

# only shows up once a compliance/fraud employee logs in - see login handler below
COMPLIANCE_TOOLS = [
    types.Tool(name="batch_sanctions_scan", description="Scan all transactions against the sanctions list. Reports progress as it runs.", inputSchema=BATCH_SCAN_SCHEMA),
]


@server.list_tools()
async def list_tools():
    emp_id = session["employee_id"]
    if emp_id is None:
        return BASE_TOOLS
    employee = db.get_employee(emp_id)
    if employee["role"] in ("compliance_officer", "fraud_investigator"):
        return BASE_TOOLS + COMPLIANCE_TOOLS
    return BASE_TOOLS


@server.call_tool()
async def call_tool(name: str, args: dict):
    ctx = server.request_context
    if name == "login":
        return await login(args, ctx)
    if name == "get_account":
        return get_account(args)
    if name == "wire_transfer_initiate":
        return wire_transfer(args)
    if name == "batch_sanctions_scan":
        return await batch_scan(args, ctx)
    raise ValueError(f"unknown tool: {name}")


# --- notifications ---
# a teller can't see batch_sanctions_scan. the moment a compliance officer or
# fraud investigator logs in, the tool list actually changes, so we tell the
# client instead of making it guess or reconnect.
async def login(args, ctx):
    employee = db.get_employee(args["employee_id"])
    if employee is None:
        return [types.TextContent(type="text", text="No employee with that ID.")]

    gains_tools = employee["role"] in ("compliance_officer", "fraud_investigator")
    session["employee_id"] = employee["employee_id"]

    if gains_tools:
        await ctx.session.send_tool_list_changed()
        return [types.TextContent(type="text", text=f"Logged in as {employee['name']} ({employee['role']}). Compliance tools unlocked.")]
    return [types.TextContent(type="text", text=f"Logged in as {employee['name']} ({employee['role']}).")]


def get_account(args):
    account = db.get_account(args["account_id"])
    if account is None:
        return [types.TextContent(type="text", text="Account not found.")]
    return [types.TextContent(type="text", text=f"Account {account['account_id']}: balance {account['balance']:.2f}")]


# --- defensive design ---
# 1) schema already caught bad types/missing fields
# 2) here we check things a schema can't: does the account exist, is there
#    enough money, is the employee actually allowed to move this much
# 3) employee_id in the args isn't trusted - it has to match who's logged in
def wire_transfer(args):
    emp_id = session["employee_id"]
    if emp_id is None:
        return [types.TextContent(type="text", text="Rejected: no one is logged in.")]
    if args["employee_id"] != emp_id:
        return [types.TextContent(type="text", text="Rejected: employee_id doesn't match this session.")]

    employee = db.get_employee(emp_id)
    source = db.get_account(args["source_account_id"])
    amount = args["amount"]

    if source is None:
        return [types.TextContent(type="text", text="Rejected: source account doesn't exist.")]
    if source["balance"] < amount:
        return [types.TextContent(type="text", text="Rejected: insufficient funds.")]
    limit = db.WIRE_AUTHORITY_LIMIT[employee["role"]]
    if amount > limit:
        return [types.TextContent(type="text", text=f"Rejected: {amount:.2f} exceeds {employee['role']}'s limit of {limit}.")]

    flags = []
    if db.is_sanctioned(args["destination_country"]):
        flags.append("sanctions")
    if db.looks_like_structuring(source["account_id"]):
        flags.append("structuring")
    if db.is_self_dealing(employee):
        flags.append("self_dealing")

    status = "flagged" if (flags and employee["role"] == "teller") else "approved"
    transfer_id = db.insert_wire_transfer(
        source_account_id=source["account_id"],
        destination_account_num=args["destination_account_num"],
        destination_country=args["destination_country"],
        amount=amount,
        status=status,
        flag_reason=",".join(flags) if flags else None,
        initiated_by=emp_id,
        approved_by=None,
        timestamp="now",
    )

    if status == "flagged":
        return [types.TextContent(type="text", text=f"Wire #{transfer_id} HELD for review - flags: {', '.join(flags)}")]

    db.update_account_balance(source["account_id"], source["balance"] - amount)
    return [types.TextContent(type="text", text=f"Wire #{transfer_id} of {amount:.2f} approved.")]


# --- progress tracking ---
# real work here is small (seed data), but this is where a nightly scan over
# thousands of transactions would report as it goes instead of blocking
async def batch_scan(args, ctx):
    employee = db.get_employee(args["employee_id"])
    if employee is None or employee["role"] not in ("compliance_officer", "fraud_investigator"):
        return [types.TextContent(type="text", text="Rejected: requires compliance or fraud investigator role.")]

    total = db.get_transaction_count()
    progress_token = getattr(ctx.request, "progress_token", None)

    for scanned in range(1, total + 1):
        await asyncio.sleep(0.1)  # stands in for real scan work
        if progress_token is not None:
            await ctx.session.send_progress_notification(progress_token=progress_token, progress=scanned, total=total)

    return [types.TextContent(type="text", text=f"Scanned {total} transactions.")]


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
