"""
End-to-end demo for issue #41: creates two REAL episodes for an
existing seeded customer (Ahmed Ali, customer_id=1) via the actual
PR 3 router - not hand-crafted episodic_memory rows - so the
contradiction consolidation resolves comes from genuine promoted
events, matching db/seed.sql's existing customer/account data.

Episode A: a new wire flagged 'structuring', compliance decision
           'approved' -> derives risk_level='medium'.
Episode B: a new wire flagged 'sanctions' (no decision needed) ->
           derives risk_level='high'.
These two disagree for the same customer -> a real contradiction for
consolidation to resolve (newer wins, versioned, contradiction_note).

Usage (from project root): python memory/semantic_memory/demo_consolidation.py
"""

import sqlite3
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "episodic_memory"))
from promote_or_drop_router import route_overflow  # noqa: E402
from consolidation import run_consolidation  # noqa: E402
from semantic_memory import SemanticMemory  # noqa: E402

DB_PATH = Path(__file__).resolve().parent.parent.parent / "db" / "bank.db"

CUSTOMER_ID = 1          # Ahmed Ali, from db/seed.sql
SOURCE_ACCOUNT_ID = 1    # Ahmed Ali's account, from db/seed.sql


def _seed_two_real_wires():
    """
    Inserts two real wire_transfers (+ one compliance_review) rows into
    bank.db, exactly like mcp/server.py's wire_transfer() would - so the
    router's DB enrichment lookup in PR 3 finds real data, not a mock.
    """
    conn = sqlite3.connect(DB_PATH)
    now = datetime.now(timezone.utc).isoformat()

    # Episode A: structuring, cleared by compliance -> should derive 'medium'
    cur = conn.execute(
        """
        INSERT INTO wire_transfers (
            source_account_id, destination_account_num, destination_country,
            amount, status, flag_reason, initiated_by, approved_by, timestamp
        ) VALUES (?, 'US-1112223333', 'US', 9500.00, 'approved', 'structuring', 4, 1, ?)
        """,
        (SOURCE_ACCOUNT_ID, now),
    )
    transfer_a = cur.lastrowid
    conn.execute(
        """
        INSERT INTO compliance_reviews (transfer_id, reviewer_id, decision, notes, timestamp)
        VALUES (?, 1, 'approved', 'Cleared after reviewing transaction pattern.', ?)
        """,
        (transfer_a, now),
    )

    # Episode B: sanctions, later timestamp -> should derive 'high'
    cur = conn.execute(
        """
        INSERT INTO wire_transfers (
            source_account_id, destination_account_num, destination_country,
            amount, status, flag_reason, initiated_by, approved_by, timestamp
        ) VALUES (?, 'KP-9998887777', 'KP', 4200.00, 'flagged', 'sanctions', 4, NULL, ?)
        """,
        (SOURCE_ACCOUNT_ID, now),
    )
    transfer_b = cur.lastrowid

    conn.commit()
    conn.close()
    return transfer_a, transfer_b


def main():
    transfer_a, transfer_b = _seed_two_real_wires()
    print(f"Seeded real wires: transfer_a={transfer_a} (structuring/approved), "
          f"transfer_b={transfer_b} (sanctions)\n")

    # Feed real-shaped tool-result messages through the ACTUAL PR3 router,
    # exactly what ShortTermMemory.overflow_candidates() would hand it.
    messages = [
        {"role": "tool", "name": "wire_transfer_initiate",
         "content": f"Wire #{transfer_a} of 9500.00 approved after compliance review."},
        {"role": "tool", "name": "wire_transfer_initiate",
         "content": f"Wire #{transfer_b} held (flags: sanctions)."},
    ]
    routing_results = route_overflow(messages)

    print("=== router decisions (PR 3) ===")
    for r in routing_results:
        print(f"[{r['decision'].upper()}] episode_id={r['episode_id']} - {r['reason']}\n")

    # Consolidation is a SEPARATE, explicit call - not triggered above.
    print("=== running consolidation pass (separate, periodic) ===")
    actions = run_consolidation()
    for a in actions:
        print(a)

    print("\n=== resulting semantic_memory fact history for customer 1 / risk_level ===")
    semantic = SemanticMemory()
    for row in semantic.get_fact_history("customer", CUSTOMER_ID, "risk_level"):
        print(dict(row))


if __name__ == "__main__":
    main()