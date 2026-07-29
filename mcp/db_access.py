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


def get_transaction_count() -> int:
    conn = get_conn()
    count = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    conn.close()
    return count
