"""
Talks to db/bank.db (built from schema.sql + seed.sql). No fake data here —
if it's not in the real schema, it's not in this file.
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "db" / "bank.db"

# Roles that don't exist in schema.sql get a hardcoded authority limit,
# since employees table has no limit column.
WIRE_AUTHORITY_LIMIT = {
    "teller": 5000,
    "compliance_officer": 250000,
    "fraud_investigator": 250000,
}

STRUCTURING_THRESHOLD = 5000     # deposits just under this, repeated, look like structuring
STRUCTURING_COUNT = 3            # this many near-threshold deposits = flag


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_employee(employee_id: int):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM employees WHERE employee_id = ?", (employee_id,)
    ).fetchone()
    conn.close()
    return row


def get_account(account_id: int):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM accounts WHERE account_id = ?", (account_id,)
    ).fetchone()
    conn.close()
    return row

def get_transaction_history(account_id):

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT type, amount, source, timestamp
        FROM transactions
        WHERE account_id = ?
        ORDER BY timestamp DESC
        LIMIT 10
        """,
        (account_id,)
    )

    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return "No recent transactions found."

    history = []

    for row in rows:
        history.append(
            f"Type: {row['type']}, Amount: {row['amount']}, Source: {row['source']}, Time: {row['timestamp']}"
        )

    return "\n".join(history)

def is_sanctioned(country_code: str) -> bool:
    conn = get_conn()
    row = conn.execute(
        "SELECT 1 FROM sanctions_list WHERE country_code = ?", (country_code,)
    ).fetchone()
    conn.close()
    return row is not None


def looks_like_structuring(account_id: int) -> bool:
    conn = get_conn()
    count = conn.execute(
        """SELECT COUNT(*) FROM transactions
           WHERE account_id = ? AND type = 'deposit' AND amount BETWEEN ? AND ?""",
        (account_id, STRUCTURING_THRESHOLD - 500, STRUCTURING_THRESHOLD - 1),
    ).fetchone()[0]
    conn.close()
    return count >= STRUCTURING_COUNT


def is_self_dealing(employee_row) -> bool:
    # an employee tied to a customer (family/self) has a conflict of interest
    # on any wire they initiate, not just ones touching that customer's account
    if employee_row is None:
        return False
    return employee_row["related_customer_id"] is not None


def insert_wire_transfer(**fields) -> int:
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO wire_transfers
           (source_account_id, destination_account_num, destination_country,
            amount, status, flag_reason, initiated_by, approved_by, timestamp)
           VALUES (:source_account_id, :destination_account_num, :destination_country,
                   :amount, :status, :flag_reason, :initiated_by, :approved_by, :timestamp)""",
        fields,
    )
    conn.commit()
    transfer_id = cur.lastrowid
    conn.close()
    return transfer_id


def update_account_balance(account_id: int, new_balance: float):
    conn = get_conn()
    conn.execute(
        "UPDATE accounts SET balance = ? WHERE account_id = ?", (new_balance, account_id)
    )
    conn.commit()
    conn.close()


def debit_account(account_id: int, amount: float) -> float:
    """Atomically debit an account and return the new balance.
    Called from wire_transfer() once a transfer is actually approved -
    previously this never happened, so approved wires didn't move money.
    """
    conn = get_conn()
    row = conn.execute(
        "SELECT balance FROM accounts WHERE account_id = ?", (account_id,)
    ).fetchone()
    new_balance = row["balance"] - amount
    conn.execute(
        "UPDATE accounts SET balance = ? WHERE account_id = ?", (new_balance, account_id)
    )
    conn.commit()
    conn.close()
    return new_balance


def set_wire_approver(transfer_id: int, approved_by: int, status: str):
    """Record who actually approved/rejected a held transfer.
    Previously approved_by was always written as NULL, even after a human
    signed off via elicitation - no audit trail of who approved what.
    """
    conn = get_conn()
    conn.execute(
        "UPDATE wire_transfers SET approved_by = ?, status = ? WHERE transfer_id = ?",
        (approved_by, status, transfer_id),
    )
    conn.commit()
    conn.close()


def insert_compliance_review(transfer_id: int, reviewer_id: int, decision: str, notes: str, timestamp: str) -> int:
    """Log the human decision on a flagged wire into compliance_reviews.
    This table existed in schema.sql/the ERD but nothing ever wrote to it -
    every elicitation outcome now leaves an audit record here.
    """
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO compliance_reviews (transfer_id, reviewer_id, decision, notes, timestamp)
           VALUES (?, ?, ?, ?, ?)""",
        (transfer_id, reviewer_id, decision, notes, timestamp),
    )
    conn.commit()
    review_id = cur.lastrowid
    conn.close()
    return review_id


def get_transaction_count() -> int:
    conn = get_conn()
    count = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    conn.close()
    return count
