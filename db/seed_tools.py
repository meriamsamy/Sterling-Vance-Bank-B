import sqlite3


TOOLS = [
    {
        "tool_name": "login",
        "description": "Log in as an employee for this session.",
        "category": "banking",
    },
    {
        "tool_name": "get_account",
        "description": "Look up an account (read-only).",
        "category": "banking",
    },
    {
        "tool_name": "wire_transfer_initiate",
        "description": "Send a wire transfer.",
        "category": "banking",
    },
    {
        "tool_name": "batch_sanctions_scan",
        "description": "Scan transactions against sanctions.",
        "category": "compliance",
    },
    {
        "tool_name": "get_customer_accounts",
        "description": "List customer accounts.",
        "category": "compliance",
    },
    {
        "tool_name": "get_transaction_history",
        "description": "Get transaction history.",
        "category": "compliance",
    },
    {
        "tool_name": "check_sanctions",
        "description": "Check destination country sanctions.",
        "category": "compliance",
    },
    {
        "tool_name": "validate_investigation",
        "description": "Validate planning output.",
        "category": "planning",
    },
]


conn = sqlite3.connect("db/bank.db")

for tool in TOOLS:
    conn.execute(
        """
        INSERT OR REPLACE INTO tools
        (
            tool_name,
            description,
            category,
            status
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            tool["tool_name"],
            tool["description"],
            tool["category"],
            "active",
        )
    )

conn.commit()
conn.close()

print("Tools seeded successfully")