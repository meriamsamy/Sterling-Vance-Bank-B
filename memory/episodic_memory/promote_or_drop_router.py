"""
Promote-or-drop routing (issue #40).

Fires on messages ShortTermMemory.overflow_candidates() is about to
evict. For each aging message, decides FORGET or PROMOTE, and logs the
reasoning for every decision (both outcomes, not just promotions) to
promote_or_drop_log - that table is the "reasoning a grader can see."

Classification is driven by the *actual* strings mcp/server.py's
wire_transfer() returns as tool results (see server.py):
  - "Wire #{id} held (flags: {flags}). ..."               -> PROMOTE
  - "Wire #{id} of {amount:.2f} approved after compliance
     review."                                              -> PROMOTE
  - "Wire #{id} cancelled by human reviewer."               -> PROMOTE
  - "Wire #{id} of {amount:.2f} approved."  (routine, no
     flags, no compliance review)                           -> FORGET
  - anything else (non-wire messages, non-tool messages)    -> FORGET

None of those strings carry customer_id/employee_id/reviewer_id, so
when promoting, this router does its own read-only lookup against
wire_transfers -> accounts -> compliance_reviews (same bank.db,
same open/close-per-call sqlite3.Row style as episodic_memory.py)
to enrich the episode before calling EpisodicMemory.store_episode().

Hard boundary (per #40's acceptance criteria): this module NEVER
writes to semantic_memory. It only ever writes to promote_or_drop_log
and, via EpisodicMemory, to episodic_memory.
"""

import re
import sqlite3
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Optional

DB_PATH = Path(__file__).resolve().parent.parent.parent / "db" / "bank.db"

# NOTE: importing EpisodicMemory via a sys.path insert of this file's own
# directory rather than a relative package import, since memory/ isn't
# confirmed to have __init__.py yet. If it does (or once it does), this
# can become: from .episodic_memory import EpisodicMemory
sys.path.insert(0, str(Path(__file__).resolve().parent))
from episodic_memory import EpisodicMemory  # noqa: E402


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


_WIRE_ID_RE = re.compile(r"Wire #(\d+)")

_PROMOTE_MARKERS = (
    "held (flags:",
    "approved after compliance review",
    "cancelled by human reviewer",
)


def _extract_transfer_id(content: str) -> Optional[int]:
    match = _WIRE_ID_RE.search(content)
    return int(match.group(1)) if match else None


def _classify(role: str, content: str):
    """
    Returns (should_promote: bool, event_type: str, marker: Optional[str]).
    Only tool-result messages are ever eligible to promote - an
    assistant's prose *mentioning* "approved" doesn't count, only the
    server's own tool-result text does.
    """
    if role != "tool" or not isinstance(content, str):
        return False, "not_tool_result", None

    for marker in _PROMOTE_MARKERS:
        if marker in content:
            event_type = (
                "wire_transfer_flagged" if marker == "held (flags:"
                else "wire_transfer_reviewed"
            )
            return True, event_type, marker

    return False, "routine_or_unflagged", None


def _lookup_transfer_context(conn, transfer_id: int) -> Optional[Dict]:
    """
    Read-only enrichment: the tool-result text alone never carries
    customer_id/employee_id/reviewer_id, so pull them from the same
    bank.db the MCP server already wrote them into.
    """
    row = conn.execute(
        """
        SELECT wt.transfer_id, wt.status, wt.flag_reason,
               wt.initiated_by, a.customer_id
        FROM wire_transfers wt
        LEFT JOIN accounts a ON a.account_id = wt.source_account_id
        WHERE wt.transfer_id = ?
        """,
        (transfer_id,),
    ).fetchone()
    if row is None:
        return None

    review = conn.execute(
        """
        SELECT reviewer_id, decision
        FROM compliance_reviews
        WHERE transfer_id = ?
        ORDER BY timestamp DESC
        LIMIT 1
        """,
        (transfer_id,),
    ).fetchone()

    return {
        "transfer_id": row["transfer_id"],
        "customer_id": row["customer_id"],
        "employee_id": row["initiated_by"],
        "flags": row["flag_reason"],
        "status": row["status"],
        "reviewer_id": review["reviewer_id"] if review else None,
        "decision": review["decision"] if review else None,
    }


def _log_decision(
    conn,
    message_excerpt: str,
    decision: str,
    reason: str,
    linked_episode_id: Optional[int],
    timestamp: str,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO promote_or_drop_log (
            message_excerpt, decision, reason, timestamp, linked_episode_id
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (message_excerpt, decision, reason, timestamp, linked_episode_id),
    )
    conn.commit()
    return cur.lastrowid


def route_overflow(messages: List[Dict]) -> List[Dict]:
    """
    The entry point. Takes exactly what ShortTermMemory.overflow_
    candidates() returns (list of normalized {"role", "content", ...}
    dicts) and, for each one, decides forget or promote, logs why, and
    - only when promoting - persists an episode via EpisodicMemory.

    Returns a list of decision records (useful for the demo script and
    for tests) - never mutates or reads semantic_memory.
    """
    if not messages:
        return []

    episodic = EpisodicMemory()
    conn = get_conn()
    results = []

    try:
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content", "") or ""
            excerpt = content[:200] if isinstance(content, str) else str(content)[:200]
            timestamp = datetime.now(timezone.utc).isoformat()

            should_promote, event_type, marker = _classify(role, content)

            if not should_promote:
                reason = (
                    "No flagged/reviewed wire-transfer pattern matched "
                    f"(role={role!r}, event_type={event_type}); routine or "
                    "unrelated message - not meaningful for long-term recall."
                )
                log_id = _log_decision(conn, excerpt, "forget", reason, None, timestamp)
                results.append({"decision": "forget", "reason": reason, "episode_id": None, "log_id": log_id})
                continue

            transfer_id = _extract_transfer_id(content)
            if transfer_id is None:
                reason = (
                    f"Matched promote marker {marker!r} but no transfer_id "
                    "could be parsed from the tool result - dropping rather "
                    "than promoting an unlinkable event."
                )
                log_id = _log_decision(conn, excerpt, "forget", reason, None, timestamp)
                results.append({"decision": "forget", "reason": reason, "episode_id": None, "log_id": log_id})
                continue

            ctx = _lookup_transfer_context(conn, transfer_id)
            if ctx is None:
                # Defensive fallback: still promote (it's a real flagged
                # event per the tool text) but note the enrichment miss
                # rather than silently dropping a compliance-relevant event.
                episode_id = episodic.store_episode(
                    event_type=event_type,
                    summary=f"Wire #{transfer_id}: {content}",
                    promotion_reason=(
                        f"Matched promote marker {marker!r}, but transfer_id "
                        f"{transfer_id} was not found in wire_transfers at "
                        "enrichment time - stored with degraded context."
                    ),
                    transfer_id=transfer_id,
                )
                reason = f"Promoted (degraded context - transfer_id {transfer_id} not found for enrichment)."
                log_id = _log_decision(conn, excerpt, "promote", reason, episode_id, timestamp)
                results.append({"decision": "promote", "reason": reason, "episode_id": episode_id, "log_id": log_id})
                continue

            summary = (
                f"Wire #{transfer_id} for customer {ctx['customer_id']}: "
                f"flags=[{ctx['flags']}], status={ctx['status']}, "
                f"decision={ctx['decision']}"
            )
            reason = (
                f"Matched promote marker {marker!r} - this is a flagged and/or "
                "compliance-reviewed wire transfer, a meaningful banking event "
                "worth recalling across sessions (issue #39)."
            )
            episode_id = episodic.store_episode(
                event_type=event_type,
                summary=summary,
                promotion_reason=reason,
                transfer_id=ctx["transfer_id"],
                customer_id=ctx["customer_id"],
                employee_id=ctx["employee_id"],
                flags=ctx["flags"],
                decision=ctx["decision"],
                reviewer_id=ctx["reviewer_id"],
            )
            log_id = _log_decision(conn, excerpt, "promote", reason, episode_id, timestamp)
            results.append({"decision": "promote", "reason": reason, "episode_id": episode_id, "log_id": log_id})
    finally:
        conn.close()

    return results