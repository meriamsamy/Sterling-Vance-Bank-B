"""
Episodic memory storage and retrieval (issue #39).

Stores curated, meaningful banking events - not raw conversation
turns. Only ever written to by the promote-or-drop router
(memory/episodic_memory/promote_or_drop_router.py, issue #40); this
module itself never decides what gets promoted, it just persists and
retrieves what it's told to.

Talks to the same db/bank.db as mcp/db_access.py, using the same
connection pattern (sqlite3.Row, open/close per call) so it fits the
existing codebase instead of introducing a second style.
"""

import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Optional

DB_PATH = Path(__file__).resolve().parent.parent.parent / "db" / "bank.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


class EpisodicMemory:
    """
    Storage and retrieval for promoted banking events (flagged wire
    transfers, their compliance outcomes, and similar events worth
    remembering across sessions per #39: "the agent cannot remember
    previous fraud investigations or important banking events after
    the session is closed.")
    """

    def store_episode(
        self,
        event_type: str,
        summary: str,
        promotion_reason: str,
        transfer_id: Optional[int] = None,
        customer_id: Optional[int] = None,
        employee_id: Optional[int] = None,
        flags: Optional[str] = None,
        decision: Optional[str] = None,
        reviewer_id: Optional[int] = None,
    ) -> int:
        """
        Persist one promoted event. Returns the new episode_id.

        Called by the promote-or-drop router when it decides an aging
        short-term memory item is worth keeping - never called
        directly from the agent loop or from consolidation.
        """
        promoted_at = datetime.now(timezone.utc).isoformat()

        conn = get_conn()
        cur = conn.execute(
            """
            INSERT INTO episodic_memory (
                event_type, transfer_id, customer_id, employee_id,
                flags, decision, reviewer_id, summary, promoted_at,
                promotion_reason, consolidated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                event_type,
                transfer_id,
                customer_id,
                employee_id,
                flags,
                decision,
                reviewer_id,
                summary,
                promoted_at,
                promotion_reason,
            ),
        )
        conn.commit()
        episode_id = cur.lastrowid
        conn.close()
        return episode_id

    def get_episode(self, episode_id: int) -> Optional[sqlite3.Row]:
        """Return a single episode by id, or None if it doesn't exist."""
        conn = get_conn()
        row = conn.execute(
            "SELECT * FROM episodic_memory WHERE episode_id = ?",
            (episode_id,),
        ).fetchone()
        conn.close()
        return row

    def get_episodes_for_customer(
        self,
        customer_id: int,
        limit: int = 20,
    ) -> List[sqlite3.Row]:
        """
        Return past events for a customer, most recent first. This is
        the real recall query: "has this customer been flagged
        before?" instead of re-reading raw wire_transfers every time.
        """
        conn = get_conn()
        rows = conn.execute(
            """
            SELECT *
            FROM episodic_memory
            WHERE customer_id = ?
            ORDER BY promoted_at DESC
            LIMIT ?
            """,
            (customer_id, limit),
        ).fetchall()
        conn.close()
        return rows

    def get_recent_episodes(
        self,
        limit: int = 20,
    ) -> List[sqlite3.Row]:
        """Return the most recently promoted episodes across all customers."""
        conn = get_conn()
        rows = conn.execute(
            """
            SELECT *
            FROM episodic_memory
            ORDER BY promoted_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        conn.close()
        return rows

    def get_unconsolidated_episodes(self) -> List[sqlite3.Row]:
        """
        Return episodes not yet processed by a consolidation pass
        (consolidated = 0). This is the read side of the boundary with
        semantic memory: consolidation.py (#41) pulls from here, but
        episodic_memory.py never writes to semantic_memory itself.
        """
        conn = get_conn()
        rows = conn.execute(
            """
            SELECT *
            FROM episodic_memory
            WHERE consolidated = 0
            ORDER BY promoted_at ASC
            """
        ).fetchall()
        conn.close()
        return rows

    def mark_consolidated(self, episode_ids: List[int]) -> None:
        """
        Flip consolidated = 1 for the given episode ids. Called by the
        consolidation pass after it has folded these episodes into
        semantic_memory, so the same episode is never re-consolidated.
        """
        if not episode_ids:
            return

        conn = get_conn()
        placeholders = ",".join("?" for _ in episode_ids)

        conn.execute(
            f"""
            UPDATE episodic_memory
            SET consolidated = 1
            WHERE episode_id IN ({placeholders})
            """,
            episode_ids,
        )

        conn.commit()
        conn.close()