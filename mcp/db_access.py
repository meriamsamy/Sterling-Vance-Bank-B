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

# add it ti use call it in validate_investigation()
def get_wire_transfer(transfer_id: int):
    """Get one wire transfer by ID for grounded investigation validation."""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM wire_transfers WHERE transfer_id = ?",
        (transfer_id,),
    ).fetchone()
    conn.close()
    return row

def get_customer_accounts(customer_id: int):
    """All accounts linked to a customer — backs the get_customer_accounts
    investigation tool. Read-only, same table get_account already reads."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT account_id, account_type, balance FROM accounts WHERE customer_id = ?",
        (customer_id,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_wire_destination_countries(account_ids: list[int]):
    """Distinct real outbound wire destinations for these accounts —
    backs check_sanctions when a specific country isn't already known."""
    if not account_ids:
        return []
    conn = get_conn()
    placeholders = ",".join("?" for _ in account_ids)
    rows = conn.execute(
        f"SELECT DISTINCT destination_country FROM wire_transfers "
        f"WHERE source_account_id IN ({placeholders})",
        account_ids,
    ).fetchall()
    conn.close()
    return [row["destination_country"] for row in rows if row["destination_country"]]

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

def get_sanctions_status(country_code: str) -> str:
    """
    Return the current sanctions status of a country.
    """

    return (
        "SANCTIONED"
        if is_sanctioned(country_code)
        else "CLEAR"
    )


def get_sanctions_version() -> int:
    """
    Return the current global sanctions-list version.
    """

    conn = get_conn()

    row = conn.execute(
        """
        SELECT version
        FROM sanctions_metadata
        WHERE id = 1
        """
    ).fetchone()

    conn.close()

    if row is None:
        return 1

    return int(row["version"])


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


def credit_account(account_id: int, amount: float) -> float:
    """Add money to an account. The counterpart to debit_account() -
    useful for topping test accounts back up between demo runs, since
    every approved wire permanently reduces the source balance.
    """
    conn = get_conn()
    row = conn.execute(
        "SELECT balance FROM accounts WHERE account_id = ?", (account_id,)
    ).fetchone()
    new_balance = row["balance"] + amount
    conn.execute(
        "UPDATE accounts SET balance = ? WHERE account_id = ?", (new_balance, account_id)
    )
    conn.commit()
    conn.close()
    return new_balance


def set_wire_approver(
    transfer_id: int, approved_by: int, status: str):
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

def update_sanctions_status(
    country_code: str,
    sanctioned: bool,
    timestamp: str,
):
    """
    Update the current sanctions status and record the
    change as a versioned external event.

    This simulates an external sanctions-list update
    arriving while an investigation is open.
    """

    conn = get_conn()

    existing = conn.execute(
        """
        SELECT 1
        FROM sanctions_list
        WHERE country_code = ?
        """,
        (country_code,),
    ).fetchone()

    previous_status = (
        "SANCTIONED"
        if existing is not None
        else "CLEAR"
    )

    new_status = (
        "SANCTIONED"
        if sanctioned
        else "CLEAR"
    )

    # No actual change
    if previous_status == new_status:

        version_row = conn.execute(
            """
            SELECT version
            FROM sanctions_metadata
            WHERE id = 1
            """
        ).fetchone()

        version = (
            int(version_row["version"])
            if version_row
            else 1
        )

        conn.close()

        return {
            "changed": False,
            "version": version,
            "previous_status": previous_status,
            "new_status": new_status,
        }

    # --------------------------------------------------------
    # Update current sanctions list
    # --------------------------------------------------------

    if sanctioned:

        conn.execute(
            """
            INSERT OR REPLACE INTO sanctions_list(
                country_code,
                reason,
                last_updated
            )
            VALUES (?, ?, ?)
            """,
            (
                country_code,
                "External sanctions update",
                timestamp,
            ),
        )

    else:

        conn.execute(
            """
            DELETE FROM sanctions_list
            WHERE country_code = ?
            """,
            (country_code,),
        )

    # --------------------------------------------------------
    # Increment sanctions version
    # --------------------------------------------------------

    conn.execute(
        """
        UPDATE sanctions_metadata
        SET version = version + 1
        WHERE id = 1
        """
    )

    version_row = conn.execute(
        """
        SELECT version
        FROM sanctions_metadata
        WHERE id = 1
        """
    ).fetchone()

    version = int(version_row["version"])

    # --------------------------------------------------------
    # Persist external event
    # --------------------------------------------------------

    cur = conn.execute(
        """
        INSERT INTO sanctions_history(
            country_code,
            previous_status,
            new_status,
            version,
            changed_at
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            country_code,
            previous_status,
            new_status,
            version,
            timestamp,
        ),
    )

    event_id = cur.lastrowid

    conn.commit()
    conn.close()

    return {
        "changed": True,
        "event_id": event_id,
        "version": version,
        "previous_status": previous_status,
        "new_status": new_status,
    }

def get_sanctions_changes_since(
    country_code: str,
    version: int,
):
    """
    Return sanctions changes for a country that occurred
    after the supplied version.
    """

    conn = get_conn()

    rows = conn.execute(
        """
        SELECT
            event_id,
            country_code,
            previous_status,
            new_status,
            version,
            changed_at
        FROM sanctions_history
        WHERE country_code = ?
          AND version > ?
        ORDER BY version ASC
        """,
        (
            country_code,
            version,
        ),
    ).fetchall()

    conn.close()

    return [dict(row) for row in rows]

def create_workflow_ticket(
    workflow_type: str,
    wire_id: int | None,
    review_id: int | None,
    status: str,
    error_type: str | None,
    error_message: str | None,
    failed_node: str | None,
    created_at: str,
) -> int:

    conn = get_conn()

    cur = conn.execute(
        """
        INSERT INTO workflow_tickets (
            workflow_type,
            wire_id,
            review_id,
            status,
            error_type,
            error_message,
            failed_node,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            workflow_type,
            wire_id,
            review_id,
            status,
            error_type,
            error_message,
            failed_node,
            created_at,
        ),
    )

    conn.commit()

    ticket_id = cur.lastrowid

    conn.close()

    return ticket_id


def create_human_review_task(
    workflow_type: str,
    wire_id: int | None,
    review_id: int | None,
    status: str,
    reason: str,
    recommended_action: str | None,
    created_at: str,
) -> int:

    conn = get_conn()

    cur = conn.execute(
        """
        INSERT INTO human_review_tasks (
            workflow_type,
            wire_id,
            review_id,
            status,
            reason,
            recommended_action,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            workflow_type,
            wire_id,
            review_id,
            status,
            reason,
            recommended_action,
            created_at,
        ),
    )

    conn.commit()

    task_id = cur.lastrowid

    conn.close()

    return task_id


def complete_human_review_task(
    task_id: int,
    decision: str,
    notes: str,
    assigned_to: int,
    completed_at: str,
):

    conn = get_conn()

    conn.execute(
        """
        UPDATE human_review_tasks
        SET
            status = 'completed',
            decision = ?,
            notes = ?,
            assigned_to = ?,
            completed_at = ?
        WHERE task_id = ?
        """,
        (
            decision,
            notes,
            assigned_to,
            completed_at,
            task_id,
        ),
    )

    conn.commit()
    conn.close()

def resolve_workflow_ticket(
    ticket_id: int,
    resolved_at: str,
):
    """Mark a previously opened workflow failure as resolved."""

    conn = get_conn()

    conn.execute(
        """
        UPDATE workflow_tickets
        SET
            status = 'resolved',
            resolved_at = ?
        WHERE ticket_id = ?
        """,
        (
            resolved_at,
            ticket_id,
        ),
    )

    conn.commit()
    conn.close()

