"""
Standalone demo for issue #40 - proves both outcomes (forget AND
promote) fire correctly and get logged, using messages shaped exactly
like ShortTermMemory.overflow_candidates() would hand back.

Usage (from project root): python memory/episodic_memory/demo_promote_or_drop.py
"""

import sqlite3
from pathlib import Path

from promote_or_drop_router import route_overflow, get_conn

DB_PATH = Path(__file__).resolve().parent.parent.parent / "db" / "bank.db"


def _find_real_flagged_transfer_id():
    """
    Pull a real transfer_id from the current bank.db rather than
    hardcoding one, so this demo works regardless of seed data.
    """
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT transfer_id FROM wire_transfers WHERE flag_reason IS NOT NULL LIMIT 1"
    ).fetchone()
    conn.close()
    return row[0] if row else None


def main():
    real_id = _find_real_flagged_transfer_id()

    fake_messages = [
        # Routine, unflagged wire -> should FORGET
        {"role": "tool", "name": "wire_transfer_initiate",
         "content": "Wire #9999 of 500.00 approved."},
        # Non-tool chatter -> should FORGET
        {"role": "assistant", "content": "Sure, I can help you look up that account."},
    ]

    if real_id is not None:
        fake_messages.append(
            {"role": "tool", "name": "wire_transfer_initiate",
             "content": f"Wire #{real_id} of 1000.00 approved after compliance review."}
        )
    else:
        # No flagged transfer exists yet - still demonstrate the promote
        # path end-to-end via the degraded-context fallback.
        fake_messages.append(
            {"role": "tool", "name": "wire_transfer_initiate",
             "content": "Wire #77777 held (flags: sanctions, structuring)."}
        )

    results = route_overflow(fake_messages)

    print("=== promote-or-drop results ===")
    for r in results:
        print(f"[{r['decision'].upper()}] episode_id={r['episode_id']} log_id={r['log_id']}")
        print(f"  reason: {r['reason']}\n")

    conn = get_conn()
    print("=== promote_or_drop_log (last 5 rows) ===")
    for row in conn.execute("SELECT * FROM promote_or_drop_log ORDER BY log_id DESC LIMIT 5"):
        print(dict(row))
    conn.close()


if __name__ == "__main__":
    main()