"""
Semantic memory storage and versioning (issue #41).

Only ever written to by consolidation.py's periodic pass - never by
the promote-or-drop router (memory/episodic_memory/promote_or_drop_router.py),
which is a hard boundary from #40's acceptance criteria. This module
itself doesn't decide facts, it just persists/versions/retrieves what
consolidation tells it to.

Same bank.db, same open/close-per-call sqlite3.Row style as
episodic_memory.py, for consistency across the memory/ package.
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


class SemanticMemory:
    """Fact storage with versioning, expiration, and conflict tracking."""

    def get_active_fact(
        self, entity_type: str, entity_id: int, fact_key: str
    ) -> Optional[sqlite3.Row]:
        conn = get_conn()
        row = conn.execute(
            """
            SELECT * FROM semantic_memory
            WHERE entity_type = ? AND entity_id = ? AND fact_key = ?
              AND status = 'active'
            ORDER BY version DESC LIMIT 1
            """,
            (entity_type, entity_id, fact_key),
        ).fetchone()
        conn.close()
        return row

    def get_fact_history(
        self, entity_type: str, entity_id: int, fact_key: str
    ) -> List[sqlite3.Row]:
        """Every version of this fact, oldest first - the full audit trail."""
        conn = get_conn()
        rows = conn.execute(
            """
            SELECT * FROM semantic_memory
            WHERE entity_type = ? AND entity_id = ? AND fact_key = ?
            ORDER BY version ASC
            """,
            (entity_type, entity_id, fact_key),
        ).fetchall()
        conn.close()
        return rows

    def insert_fact_version(
        self,
        entity_type: str,
        entity_id: int,
        fact_key: str,
        fact_value: str,
        source_episode_ids: List[int],
        contradiction_note: Optional[str] = None,
    ) -> int:
        """
        Insert a new fact version as the active one. Caller (consolidation.py)
        is responsible for superseding any prior active row first - this
        method only ever appends, never overwrites in place.
        """
        prior = self.get_active_fact(entity_type, entity_id, fact_key)
        next_version = (prior["version"] + 1) if prior else 1
        now = datetime.now(timezone.utc).isoformat()

        conn = get_conn()
        cur = conn.execute(
            """
            INSERT INTO semantic_memory (
                entity_type, entity_id, fact_key, fact_value, version,
                valid_from, valid_to, status, source_episode_ids,
                superseded_by, contradiction_note, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, NULL, 'active', ?, NULL, ?, ?)
            """,
            (
                entity_type,
                entity_id,
                fact_key,
                fact_value,
                next_version,
                now,
                ",".join(str(i) for i in source_episode_ids),
                contradiction_note,
                now,
            ),
        )
        conn.commit()
        fact_id = cur.lastrowid
        conn.close()
        return fact_id

    def supersede_fact(self, fact_id: int, superseded_by: int) -> None:
        """
        Close out an old active row instead of overwriting it: sets
        valid_to = now, status = 'superseded', and points to the fact_id
        that replaced it. History is preserved, never lost.
        """
        now = datetime.now(timezone.utc).isoformat()
        conn = get_conn()
        conn.execute(
            """
            UPDATE semantic_memory
            SET valid_to = ?, status = 'superseded', superseded_by = ?
            WHERE fact_id = ?
            """,
            (now, superseded_by, fact_id),
        )
        conn.commit()
        conn.close()

    def expire_stale_facts(self, max_age_days: int = 180) -> List[int]:
        """
        Marks active facts older than max_age_days as 'expired' (not
        deleted, not superseded - a distinct status for "nobody has
        confirmed this is still true"). Returns the fact_ids expired.
        Independent of conflict resolution - this is the "expiration of
        outdated facts" acceptance criterion, callable on its own
        periodic cadence.
        """
        cutoff = datetime.now(timezone.utc).timestamp() - (max_age_days * 86400)
        conn = get_conn()
        rows = conn.execute(
            "SELECT fact_id, valid_from FROM semantic_memory WHERE status = 'active'"
        ).fetchall()

        expired_ids = []
        for row in rows:
            valid_from_ts = datetime.fromisoformat(row["valid_from"]).timestamp()
            if valid_from_ts < cutoff:
                expired_ids.append(row["fact_id"])

        if expired_ids:
            placeholders = ",".join("?" for _ in expired_ids)
            conn.execute(
                f"UPDATE semantic_memory SET status = 'expired' WHERE fact_id IN ({placeholders})",
                expired_ids,
            )
            conn.commit()

        conn.close()
        return expired_ids