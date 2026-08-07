"""
Applies the Memory Lab tables (episodic_memory, promote_or_drop_log,
semantic_memory) to the existing db/bank.db, without touching any
existing table or data.

Idempotent: every CREATE is IF NOT EXISTS, so running this twice is
harmless. Run once after pulling this branch.

Usage (from project root): python db/migrate_memory_tables.py
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "bank.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"

# The exact statements this migration is responsible for - pulled from
# schema.sql so there is one source of truth, not two copies that can
# drift apart.
MEMORY_TABLE_NAMES = ("episodic_memory", "promote_or_drop_log", "semantic_memory")


def _extract_memory_statements(schema_sql: str) -> str:
    marker = "-- Memory Lab additions (Task 2)"
    idx = schema_sql.find(marker)
    if idx == -1:
        raise RuntimeError(
            "Memory Lab schema block not found in schema.sql - "
            "did the marker comment get removed or edited?"
        )
    return schema_sql[idx:]


def main():
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    memory_sql = _extract_memory_statements(schema_sql)

    conn = sqlite3.connect(DB_PATH)
    conn.executescript(memory_sql)
    conn.commit()

    existing = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    conn.close()

    missing = [t for t in MEMORY_TABLE_NAMES if t not in existing]
    if missing:
        raise RuntimeError(f"Migration did not create: {missing}")

    print("Memory Lab tables ready:", ", ".join(MEMORY_TABLE_NAMES))


if __name__ == "__main__":
    main()