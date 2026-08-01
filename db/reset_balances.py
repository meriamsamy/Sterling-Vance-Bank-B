"""
Resets every account back to its original seed.sql balance.
Run before each demo so results are repeatable, not dependent on how much
money got spent in the last run.

Usage (from project root): python db/reset_balances.py
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "bank.db"

ORIGINAL_BALANCES = {
    1: 5000.00,
    2: 10000.00,
    3: 15000.00,
}


def main():
    conn = sqlite3.connect(DB_PATH)
    for account_id, balance in ORIGINAL_BALANCES.items():
        conn.execute(
            "UPDATE accounts SET balance = ? WHERE account_id = ?",
            (balance, account_id),
        )
    conn.commit()
    conn.close()
    print("Balances reset:", ORIGINAL_BALANCES)


if __name__ == "__main__":
    main()
