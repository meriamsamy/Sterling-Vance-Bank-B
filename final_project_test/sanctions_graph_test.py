"""
End-to-end integration tests for the Sterling & Vance
Sanctions Review State Graph.

Covers:

1. Initial graph execution.
2. Durable checkpoint creation.
3. Explicit waiting for an external event.
4. Real sanctions-list change during an open review.
5. Sanctions change detection and re-evaluation.
6. RAG / investigation state persistence.
7. HITL task creation and human/admin resume.
8. Real node failure.
9. Persistent workflow failure ticket.
10. Ticket resolution and workflow resume.
11. Fresh Python process checkpoint recovery.
12. Sanctions history persistence.
13. State completeness.
14. HITL and failure paths are distinct.

The real bank DB is backed up before the test
and restored afterward.

Run from repository root:

    python -u ".\final_project_test\sanctions_graph_test.py"
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path


# ============================================================
# PROJECT ROOT
# ============================================================

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ============================================================
# PROJECT DB ACCESS
#
# db_access.py is inside:
#
#     mcp/db_access.py
#
# We intentionally import the project's file directly rather
# than importing the external Python package named "mcp".
# ============================================================

MCP_DIR = ROOT / "mcp"

if not MCP_DIR.exists():
    raise FileNotFoundError(
        f"Project mcp directory not found: {MCP_DIR}"
    )

if str(MCP_DIR) not in sys.path:
    sys.path.insert(0, str(MCP_DIR))

import db_access as db


# ============================================================
# REAL BANK DATABASE
# ============================================================

BANK_DB = Path(db.DB_PATH)


# ============================================================
# GRAPH IMPORTS
# ============================================================

from state_graph.sanctions_change import sanctions_nodes

from state_graph.sanctions_change.sanctions_graph_runner import (
    get_review_state,
    resume_after_admin,
    resume_after_event,
    resume_after_ticket_resolution,
    start_review,
)

# ============================================================
# TEST IDENTIFIERS
# ============================================================

TEST_PREFIX = (
    f"sanctions-test-{uuid.uuid4().hex[:8]}"
)

WIRE_ID: int | None = None
THREAD_ID: str | None = None
FAILURE_THREAD_ID: str | None = None

BACKUP_DB: Path | None = None


# ============================================================
# ASSERTION HELPERS
# ============================================================

def check(
    condition: bool,
    message: str,
) -> None:

    if not condition:
        raise AssertionError(
            f"[FAIL] {message}"
        )

    print(
        f"[PASS] {message}"
    )


def print_state(
    label: str,
    snapshot,
) -> None:

    state = snapshot.values

    print()
    print(
        f"--- {label} ---"
    )

    print(
        "current_node:",
        state.get("current_node"),
    )

    print(
        "last_node:",
        state.get("last_node"),
    )

    print(
        "status:",
        state.get("status"),
    )

    print(
        "pending_event:",
        state.get("pending_event"),
    )

    print(
        "sanctions_changed:",
        state.get("sanctions_changed"),
    )

    print(
        "sanctions_impact:",
        state.get("sanctions_impact"),
    )

    print(
        "hitl_required:",
        state.get("hitl_required"),
    )

    print(
        "hitl_task_id:",
        state.get("hitl_task_id"),
    )

    print(
        "failure_ticket_id:",
        state.get("failure_ticket_id"),
    )

    print(
        "failure_resolved:",
        state.get("failure_resolved"),
    )

    print(
        "failed_node:",
        state.get("failed_node"),
    )

    print(
        "error_type:",
        state.get("error_type"),
    )

    print(
        "decision:",
        state.get("decision"),
    )

    print(
        "next:",
        snapshot.next,
    )


# ============================================================
# TIMESTAMP
# ============================================================

def utc_now() -> str:

    return datetime.now(
        timezone.utc
    ).isoformat()


# ============================================================
# DATABASE BACKUP
# ============================================================

def backup_database() -> Path:
    """
    Create a complete SQLite backup before the integration test.

    The test is allowed to mutate:
        - sanctions_list
        - sanctions_metadata
        - sanctions_history
        - workflow_tickets
        - human_review_tasks
        - compliance_reviews
        - other test-related DB state

    Everything is restored afterward.
    """

    if not BANK_DB.exists():
        raise FileNotFoundError(
            f"Bank database not found: {BANK_DB}"
        )

    fd, path = tempfile.mkstemp(
        prefix="bank-test-backup-",
        suffix=".db",
    )

    os.close(fd)

    backup_path = Path(path)

    source = sqlite3.connect(
        BANK_DB
    )

    destination = sqlite3.connect(
        backup_path
    )

    try:

        with destination:
            source.backup(
                destination
            )

    finally:

        source.close()
        destination.close()

    return backup_path


# ============================================================
# DATABASE RESTORE
# ============================================================

def restore_database(
    backup_path: Path,
) -> None:

    source = sqlite3.connect(
        backup_path
    )

    destination = sqlite3.connect(
        BANK_DB
    )

    try:

        with destination:
            source.backup(
                destination
            )

    finally:

        source.close()
        destination.close()

        backup_path.unlink(
            missing_ok=True
        )


# ============================================================
# FIND REAL OPEN WIRE
# ============================================================

def find_open_wire() -> int:
    """
    Find a real pending_manual_review wire.

    No fake wire is inserted.
    """

    conn = db.get_conn()

    try:

        row = conn.execute(
            """
            SELECT transfer_id
            FROM wire_transfers
            WHERE status = 'pending_manual_review'
            ORDER BY transfer_id
            LIMIT 1
            """
        ).fetchone()

    finally:

        conn.close()

    if row is None:

        raise RuntimeError(
            """
No pending_manual_review wire exists in bank.db.

The integration test requires at least one real
flagged wire in the seeded database.
"""
        )

    return int(
        row["transfer_id"]
    )


# ============================================================
# FIND REAL COMPLIANCE OFFICER
# ============================================================

def find_compliance_officer() -> int:
    """
    Find a real compliance officer from employees.

    We do not assume employee_id=1.
    """

    conn = db.get_conn()

    try:

        row = conn.execute(
            """
            SELECT employee_id
            FROM employees
            WHERE role = 'compliance_officer'
            ORDER BY employee_id
            LIMIT 1
            """
        ).fetchone()

    finally:

        conn.close()

    if row is None:

        raise RuntimeError(
            """
No compliance_officer exists in employees.

The HITL integration test requires a real
compliance officer.
"""
        )

    return int(
        row["employee_id"]
    )


# ============================================================
# GET WIRE COUNTRY
# ============================================================

def get_wire_country(
    wire_id: int,
) -> str:

    row = db.get_wire_transfer(
        wire_id
    )

    if row is None:

        raise RuntimeError(
            f"Wire {wire_id} does not exist."
        )

    country = row[
        "destination_country"
    ]

    if not country:

        raise RuntimeError(
            f"Wire {wire_id} has no destination country."
        )

    return str(
        country
    )


# ============================================================
# FORCE SANCTIONS STATUS
# ============================================================

def set_sanctions_status(
    country: str,
    sanctioned: bool,
) -> dict:
    """
    Apply a real sanctions update.

    If the requested status is already current,
    no event is produced.

    The caller can therefore use this helper to
    create a real external sanctions event.
    """

    current = (
        db.get_sanctions_status(
            country
        )
    )

    desired = (
        "SANCTIONED"
        if sanctioned
        else "CLEAR"
    )

    if current == desired:

        return {
            "changed": False,
            "version": db.get_sanctions_version(),
            "previous_status": current,
            "new_status": current,
        }

    return db.update_sanctions_status(
        country_code=country,
        sanctioned=sanctioned,
        timestamp=utc_now(),
    )


# ============================================================
# CREATE REAL SANCTIONS CHANGE
# ============================================================

def create_sanctions_event(
    country: str,
) -> dict:
    """
    Guarantee a real CLEAR -> SANCTIONED transition.

    If the country is already sanctioned, we first restore it
    to CLEAR and then apply the real SANCTIONED update.

    The whole DB will be restored after the test.
    """

    current = (
        db.get_sanctions_status(
            country
        )
    )

    if current == "SANCTIONED":

        clear_event = set_sanctions_status(
            country,
            sanctioned=False,
        )

        check(
            clear_event["changed"] is True,
            "Existing sanctioned country was temporarily cleared.",
        )

    event = set_sanctions_status(
        country,
        sanctioned=True,
    )

    check(
        event["changed"] is True,
        "Real sanctions status change was created.",
    )

    return event


# ============================================================
# TEST 1
# INITIAL GRAPH EXECUTION
# ============================================================

def test_start_and_checkpoint() -> None:

    global WIRE_ID
    global THREAD_ID

    WIRE_ID = find_open_wire()

    THREAD_ID = (
        f"{TEST_PREFIX}-main-{WIRE_ID}"
    )

    print()
    print("=" * 70)
    print(
        "TEST 1 — INITIAL GRAPH EXECUTION + CHECKPOINT"
    )
    print("=" * 70)

    print(
        f"Using real wire: {WIRE_ID}"
    )

    result = start_review(
        wire_id=WIRE_ID,
        thread_id=THREAD_ID,
    )

    check(
        result is not None,
        "Graph returned a result.",
    )

    snapshot = get_review_state(
        wire_id=WIRE_ID,
        thread_id=THREAD_ID,
    )

    print_state(
        "Initial checkpoint",
        snapshot,
    )

    state = snapshot.values

    check(
        state.get("wire_id") == WIRE_ID,
        "Wire ID persisted in graph state.",
    )

    check(
        bool(
            state.get(
                "destination_country"
            )
        ),
        "Destination country persisted.",
    )

    check(
        state.get("wire_status") is not None,
        "Wire status persisted.",
    )

    check(
        state.get("wire_amount") is not None,
        "Wire amount persisted.",
    )

    check(
        state.get(
            "source_account_id"
        ) is not None,
        "Source account ID persisted.",
    )

    check(
        state.get("current_node")
        is not None,
        "Current graph node persisted.",
    )

    check(
        state.get("updated_at")
        is not None,
        "Transition timestamp persisted.",
    )

    check(
        "evidence" in state,
        "Evidence field exists.",
    )

    check(
        "sanctions_version_at_start"
        in state,
        "Initial sanctions version persisted.",
    )

    check(
        snapshot.next,
        "Graph produced a resumable checkpoint.",
    )


# ============================================================
# TEST 2
# EXPLICIT EXTERNAL EVENT WAIT
# ============================================================

def test_waiting_for_external_event() -> None:

    print()
    print("=" * 70)
    print(
        "TEST 2 — EXTERNAL EVENT WAIT"
    )
    print("=" * 70)

    snapshot = get_review_state(
        wire_id=WIRE_ID,
        thread_id=THREAD_ID,
    )

    print_state(
        "External-event checkpoint",
        snapshot,
    )

    state = snapshot.values

    check(
        state.get("status")
        == "waiting",
        "Workflow status is waiting.",
    )

    check(
        snapshot.next,
        "External-event checkpoint is resumable.",
    )


# ============================================================
# TEST 3
# REAL SANCTIONS CHANGE
# ============================================================

def test_sanctions_update() -> None:

    print()
    print("=" * 70)
    print(
        "TEST 3 — REAL SANCTIONS CHANGE DURING OPEN REVIEW"
    )
    print("=" * 70)

    snapshot_before = get_review_state(
        wire_id=WIRE_ID,
        thread_id=THREAD_ID,
    )

    state_before = (
        snapshot_before.values
    )

    country = state_before.get(
        "destination_country"
    )

    check(
        bool(country),
        "Destination country exists.",
    )

    start_version = state_before.get(
        "sanctions_version_at_start"
    )

    check(
        start_version is not None,
        "Workflow has a starting sanctions version.",
    )

    print(
        f"Country: {country}"
    )

    print(
        f"Starting sanctions version: {start_version}"
    )

    # --------------------------------------------------------
    # REAL EXTERNAL CHANGE
    # --------------------------------------------------------

    event = create_sanctions_event(
        country
    )

    print()
    print(
        "External sanctions event:"
    )
    print(
        event
    )

    check(
        event.get("event_id")
        is not None,
        "Sanctions event received a persistent event ID.",
    )

    check(
        event["version"]
        > start_version,
        "Sanctions version increased.",
    )

    check(
        event["previous_status"]
        != event["new_status"],
        "Sanctions status actually changed.",
    )

    check(
        event["new_status"]
        == "SANCTIONED",
        "Country became sanctioned.",
    )

    # --------------------------------------------------------
    # RESUME GRAPH
    # --------------------------------------------------------

    result = resume_after_event(
        wire_id=WIRE_ID,
        event_type="sanctions_update",
        event_id=str(
            event["event_id"]
        ),
        thread_id=THREAD_ID,
    )

    check(
        result is not None,
        "Graph resumed after sanctions event.",
    )

    snapshot_after = get_review_state(
        wire_id=WIRE_ID,
        thread_id=THREAD_ID,
    )

    print_state(
        "After sanctions update",
        snapshot_after,
    )

    state_after = (
        snapshot_after.values
    )

    check(
        state_after.get(
            "current_sanctions_version"
        )
        >= event["version"],
        "Graph loaded the new sanctions version.",
    )

    check(
        state_after.get(
            "current_sanctions_status"
        )
        == "SANCTIONED",
        "Graph sees the country as sanctioned.",
    )

    check(
        state_after.get(
            "sanctions_changed"
        )
        is True,
        "Graph detected sanctions change.",
    )

    check(
        state_after.get(
            "sanctions_impact"
        )
        == "affected",
        "Graph marked the review as affected.",
    )


# ============================================================
# TEST 4
# RE-EVALUATION
# ============================================================

def test_re_evaluation() -> None:

    print()
    print("=" * 70)
    print(
        "TEST 4 — RE-EVALUATION"
    )
    print("=" * 70)

    snapshot = get_review_state(
        wire_id=WIRE_ID,
        thread_id=THREAD_ID,
    )

    print_state(
        "Re-evaluation checkpoint",
        snapshot,
    )

    state = snapshot.values

    # --------------------------------------------------------
    # RAG
    # --------------------------------------------------------

    check(
        "retrieved_policy" in state,
        "Retrieved policy field exists.",
    )

    check(
        state.get(
            "retrieved_policy"
        ) is not None,
        "RAG policy output is populated.",
    )

    # --------------------------------------------------------
    # INVESTIGATION
    # --------------------------------------------------------

    check(
        "investigation_history"
        in state,
        "Investigation history exists.",
    )

    check(
        "investigation_steps"
        in state,
        "Investigation step count exists.",
    )

    check(
        "investigation_status"
        in state,
        "Investigation status exists.",
    )

    # --------------------------------------------------------
    # RE-EVALUATION RESULT
    # --------------------------------------------------------

    valid_nodes = {
        "re_evaluate",
        "waiting_for_admin",
        "complete_review",
        "waiting_for_event",
    }

    check(
        state.get(
            "current_node"
        )
        in valid_nodes,
        "Workflow reached a valid post-sanctions state.",
    )

    check(
        state.get(
            "hitl_required"
        )
        is True
        or state.get(
            "decision"
        ) is not None
        or state.get(
            "status"
        )
        in {
            "waiting_for_admin",
            "completed",
        },
        "Re-evaluation produced a workflow outcome.",
    )


# ============================================================
# TEST 5
# HITL
# ============================================================

def test_hitl() -> None:

    print()
    print("=" * 70)
    print(
        "TEST 5 — HUMAN-IN-THE-LOOP"
    )
    print("=" * 70)

    admin_id = (
        find_compliance_officer()
    )

    print(
        f"Using real compliance officer: {admin_id}"
    )

    snapshot = get_review_state(
        wire_id=WIRE_ID,
        thread_id=THREAD_ID,
    )

    print_state(
        "HITL checkpoint",
        snapshot,
    )

    state = snapshot.values

    check(
        state.get(
            "hitl_required"
        )
        is True,
        "Graph escalated the sanctions-affected case to HITL.",
    )

    check(
        state.get(
            "status"
        )
        == "waiting_for_admin",
        "Graph is waiting for administrator action.",
    )

    task_id = state.get(
        "hitl_task_id"
    )

    check(
        task_id is not None,
        "HITL task ID exists in graph state.",
    )

    check(
        snapshot.next,
        "HITL checkpoint is resumable.",
    )

    # --------------------------------------------------------
    # VERIFY DATABASE TASK
    # --------------------------------------------------------

    conn = db.get_conn()

    try:

        task = conn.execute(
            """
            SELECT *
            FROM human_review_tasks
            WHERE task_id = ?
            """,
            (task_id,),
        ).fetchone()

    finally:

        conn.close()

    check(
        task is not None,
        "HITL task exists in database.",
    )

    check(
        task["status"] == "open",
        "HITL task is open.",
    )

    check(
        task["wire_id"] == WIRE_ID,
        "HITL task belongs to the correct wire.",
    )

    # --------------------------------------------------------
    # ADMIN RESUME
    # --------------------------------------------------------

    result = resume_after_admin(
        wire_id=WIRE_ID,
        decision="rejected",
        admin_id=admin_id,
        notes=(
            "Integration test: sanctions status changed "
            "during an open review."
        ),
        thread_id=THREAD_ID,
    )

    check(
        result is not None,
        "Graph resumed after admin decision.",
    )

    snapshot_after = get_review_state(
        wire_id=WIRE_ID,
        thread_id=THREAD_ID,
    )

    print_state(
        "After admin resume",
        snapshot_after,
    )

    state_after = (
        snapshot_after.values
    )

    check(
        state_after.get(
            "decision"
        )
        == "rejected",
        "Admin decision entered graph state.",
    )

    # --------------------------------------------------------
    # VERIFY TASK COMPLETION
    # --------------------------------------------------------

    conn = db.get_conn()

    try:

        task = conn.execute(
            """
            SELECT *
            FROM human_review_tasks
            WHERE task_id = ?
            """,
            (task_id,),
        ).fetchone()

    finally:

        conn.close()

    check(
        task is not None,
        "HITL task still exists after completion.",
    )

    check(
        task["status"]
        == "completed",
        "HITL task is completed.",
    )

    check(
        task["decision"]
        == "rejected",
        "Admin decision persisted on HITL task.",
    )

    check(
        task["assigned_to"]
        == admin_id,
        "Real admin ID persisted on HITL task.",
    )


# ============================================================
# TEST 6
# REAL FAILURE -> TICKET -> RESUME
# ============================================================

def test_real_failure_and_resume() -> None:

    global FAILURE_THREAD_ID

    print()
    print("=" * 70)
    print(
        "TEST 6 — REAL FAILURE + TICKET + RESUME"
    )
    print("=" * 70)

    FAILURE_THREAD_ID = (
        f"{TEST_PREFIX}-failure-{WIRE_ID}"
    )

    # --------------------------------------------------------
    # START INDEPENDENT FAILURE WORKFLOW
    # --------------------------------------------------------

    result = start_review(
        wire_id=WIRE_ID,
        thread_id=FAILURE_THREAD_ID,
    )

    check(
        result is not None,
        "Independent failure workflow started.",
    )

    before_failure = get_review_state(
        wire_id=WIRE_ID,
        thread_id=FAILURE_THREAD_ID,
    )

    print_state(
        "Before injected failure",
        before_failure,
    )

    check(
        before_failure.values.get("status") == "waiting",
        "Failure workflow is waiting for an external event.",
    )

    check(
        "waiting_for_event" in before_failure.next,
        "Failure workflow can resume through waiting_for_event.",
    )

    # --------------------------------------------------------
    # INJECT REAL FAILURE
    # --------------------------------------------------------

    original_get_account = (
        sanctions_nodes.db.get_account
    )

    def failing_get_account(
        account_id: int,
    ):
        raise RuntimeError(
            "Intentional integration-test failure "
            "inside collect_evidence."
        )

    sanctions_nodes.db.get_account = (
        failing_get_account
    )

    try:

        try:

            resume_after_event(
                wire_id=WIRE_ID,
                event_type="new_evidence",
                event_id=(
                    f"{TEST_PREFIX}-failure-event"
                ),
                thread_id=FAILURE_THREAD_ID,
            )

        except Exception as exc:

            print()
            print(
                "[INFO] Expected injected exception:"
            )
            print(
                repr(exc)
            )

    finally:

        sanctions_nodes.db.get_account = (
            original_get_account
        )

    # --------------------------------------------------------
    # CHECK FAILURE CHECKPOINT
    # --------------------------------------------------------

    failed_snapshot = get_review_state(
        wire_id=WIRE_ID,
        thread_id=FAILURE_THREAD_ID,
    )

    print_state(
        "After injected failure",
        failed_snapshot,
    )

    failed_state = (
        failed_snapshot.values
    )

    check(
        failed_state.get(
            "status"
        )
        == "failed"
        or failed_state.get(
            "current_node"
        )
        == "reset_after_failure",
        "Workflow entered the failure-recovery path.",
    )

    ticket_id = failed_state.get(
        "failure_ticket_id"
    )

    check(
        ticket_id is not None,
        "Failure ticket ID persisted in graph state.",
    )

    check(
        failed_state.get(
            "failed_node"
        )
        == "collect_evidence",
        "Failed node was recorded correctly.",
    )

    check(
        failed_state.get(
            "error_type"
        )
        == "RuntimeError",
        "RuntimeError was persisted.",
    )

    check(
        "Intentional integration-test failure"
        in failed_state.get(
            "error_message",
            "",
        ),
        "Failure message was persisted.",
    )

    # --------------------------------------------------------
    # VERIFY DATABASE TICKET
    # --------------------------------------------------------

    conn = db.get_conn()

    try:

        ticket = conn.execute(
            """
            SELECT *
            FROM workflow_tickets
            WHERE ticket_id = ?
            """,
            (ticket_id,),
        ).fetchone()

    finally:

        conn.close()

    check(
        ticket is not None,
        "Failure ticket exists in database.",
    )

    check(
        ticket["status"]
        == "open",
        "Failure ticket starts open.",
    )

    check(
        ticket["wire_id"]
        == WIRE_ID,
        "Failure ticket belongs to correct wire.",
    )

    check(
        ticket["failed_node"]
        == "collect_evidence",
        "Ticket contains failed node.",
    )

    check(
        ticket["error_type"]
        == "RuntimeError",
        "Ticket contains error type.",
    )

    check(
        "Intentional integration-test failure"
        in ticket["error_message"],
        "Ticket contains error message.",
    )

    # --------------------------------------------------------
    # FAILURE != HITL
    # --------------------------------------------------------

    check(
        failed_state.get(
            "hitl_required"
        )
        is False,
        "Failure path is separate from HITL.",
    )

    # --------------------------------------------------------
    # RESOLVE TICKET
    # --------------------------------------------------------

    result = resume_after_ticket_resolution(
        wire_id=WIRE_ID,
        notes=(
            "Integration test resolved the failure. "
            "Database access was restored."
        ),
        thread_id=FAILURE_THREAD_ID,
    )

    check(
        result is not None,
        "Workflow resumed after ticket resolution.",
    )

    # --------------------------------------------------------
    # CHECK RECOVERY
    # --------------------------------------------------------

    recovered_snapshot = get_review_state(
        wire_id=WIRE_ID,
        thread_id=FAILURE_THREAD_ID,
    )

    print_state(
        "After failure-ticket resolution",
        recovered_snapshot,
    )

    recovered_state = (
        recovered_snapshot.values
    )

    check(
        recovered_state.get(
            "failure_resolved"
        )
        is True,
        "Failure resolution persisted in graph state.",
    )

    check(
        recovered_state.get(
            "status"
        )
        != "failed",
        "Workflow left the failed state.",
    )

    check(
        recovered_state.get(
            "current_node"
        )
        in {
            "collect_evidence",
            "detect_sanctions_change",
            "waiting_for_event",
            "re_evaluate",
            "waiting_for_admin",
            "complete_review",
        },
        "Workflow resumed to a valid graph node.",
    )

    # --------------------------------------------------------
    # VERIFY RESOLVED TICKET
    # --------------------------------------------------------

    conn = db.get_conn()

    try:

        ticket = conn.execute(
            """
            SELECT *
            FROM workflow_tickets
            WHERE ticket_id = ?
            """,
            (ticket_id,),
        ).fetchone()

    finally:

        conn.close()

    check(
        ticket is not None,
        "Resolved ticket still exists.",
    )

    check(
        ticket["status"]
        == "resolved",
        "Failure ticket is marked resolved.",
    )

    check(
        ticket["resolved_at"]
        is not None,
        "Ticket resolution timestamp persisted.",
    )


# ============================================================
# TEST 7
# SANCTIONS HISTORY
# ============================================================

def test_sanctions_history() -> None:

    print()
    print("=" * 70)
    print(
        "TEST 7 — SANCTIONS HISTORY"
    )
    print("=" * 70)

    snapshot = get_review_state(
        wire_id=WIRE_ID,
        thread_id=THREAD_ID,
    )

    state = snapshot.values

    country = state.get(
        "destination_country"
    )

    start_version = state.get(
        "sanctions_version_at_start"
    )

    changes = db.get_sanctions_changes_since(
        country,
        start_version,
    )

    check(
        isinstance(
            changes,
            list,
        ),
        "Sanctions history returns a list.",
    )

    check(
        len(changes) > 0,
        "At least one sanctions change was persisted.",
    )

    latest = changes[-1]

    check(
        latest["country_code"]
        == country,
        "Sanctions event belongs to reviewed country.",
    )

    check(
        latest["version"]
        > start_version,
        "Sanctions event has a newer version.",
    )

    check(
        latest["previous_status"]
        != latest["new_status"],
        "History contains an actual status transition.",
    )


# ============================================================
# TEST 8
# FRESH PROCESS CHECKPOINT
# ============================================================

def test_fresh_process_checkpoint() -> None:

    print()
    print("=" * 70)
    print(
        "TEST 8 — FRESH PYTHON PROCESS CHECKPOINT"
    )
    print("=" * 70)

    target_thread = (
        FAILURE_THREAD_ID
    )

    check(
        target_thread is not None,
        "Failure workflow thread exists.",
    )

    current_snapshot = (
        get_review_state(
            wire_id=WIRE_ID,
            thread_id=target_thread,
        )
    )

    current_state = (
        current_snapshot.values
    )

    expected_node = (
        current_state.get(
            "current_node"
        )
    )

    expected_status = (
        current_state.get(
            "status"
        )
    )

    # --------------------------------------------------------
    # Fresh Python process.
    #
    # We explicitly add ROOT to sys.path so the child process
    # can import the project packages.
    # --------------------------------------------------------

    script = f"""
import sys

ROOT = {str(ROOT)!r}

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from state_graph.sanctions_change.sanctions_graph_runner import (
    get_review_state,
)

snapshot = get_review_state(
    wire_id={WIRE_ID},
    thread_id={target_thread!r},
)

print(
    "WIRE_ID="
    + str(snapshot.values.get("wire_id"))
)

print(
    "CURRENT_NODE="
    + str(snapshot.values.get("current_node"))
)

print(
    "STATUS="
    + str(snapshot.values.get("status"))
)

print(
    "FAILURE_RESOLVED="
    + str(snapshot.values.get("failure_resolved"))
)

print(
    "NEXT="
    + repr(snapshot.next)
)
"""

    process = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    print()
    print(
        "Fresh process stdout:"
    )
    print(
        process.stdout
    )

    if process.stderr:

        print()
        print(
            "Fresh process stderr:"
        )
        print(
            process.stderr
        )

    check(
        process.returncode == 0,
        "Fresh Python process loaded the checkpoint.",
    )

    stdout = process.stdout

    check(
        f"WIRE_ID={WIRE_ID}"
        in stdout,
        "Fresh process recovered the same wire ID.",
    )

    check(
        f"CURRENT_NODE={expected_node}"
        in stdout,
        "Fresh process recovered the same graph node.",
    )

    check(
        f"STATUS={expected_status}"
        in stdout,
        "Fresh process recovered the same status.",
    )

    check(
        "FAILURE_RESOLVED=True"
        in stdout,
        "Fresh process recovered failure-resolution state.",
    )


# ============================================================
# TEST 9
# STATE COMPLETENESS
# ============================================================

def test_state_completeness() -> None:

    print()
    print("=" * 70)
    print(
        "TEST 9 — STATE COMPLETENESS"
    )
    print("=" * 70)

    snapshot = get_review_state(
        wire_id=WIRE_ID,
        thread_id=THREAD_ID,
    )

    state = snapshot.values

    required_fields = {
        "wire_id",
        "destination_country",
        "wire_status",
        "wire_amount",
        "source_account_id",

        "evidence",
        "new_evidence",

        "retrieved_policy",

        "current_sanctions_version",
        "current_sanctions_status",

        "sanctions_version_at_start",
        "sanctions_status_at_start",

        "sanctions_changed",
        "sanctions_impact",

        "risk_level",
        "recommended_action",

        "investigation_history",
        "investigation_steps",
        "investigation_status",

        "status",
        "current_node",
        "updated_at",
    }

    for field in sorted(
        required_fields
    ):

        check(
            field in state,
            f"State contains '{field}'.",
        )


# ============================================================
# TEST 10
# HITL VS FAILURE
# ============================================================

def test_hitl_and_failure_are_distinct() -> None:

    print()
    print("=" * 70)
    print(
        "TEST 10 — HITL VS FAILURE SEPARATION"
    )
    print("=" * 70)

    hitl_snapshot = (
        get_review_state(
            wire_id=WIRE_ID,
            thread_id=THREAD_ID,
        )
    )

    failure_snapshot = (
        get_review_state(
            wire_id=WIRE_ID,
            thread_id=FAILURE_THREAD_ID,
        )
    )

    hitl_state = (
        hitl_snapshot.values
    )

    failure_state = (
        failure_snapshot.values
    )

    check(
        hitl_state.get(
            "hitl_task_id"
        )
        is not None,
        "HITL workflow has a human-review task.",
    )

    check(
        failure_state.get(
            "failure_ticket_id"
        )
        is not None,
        "Failure workflow has a failure ticket.",
    )

    check(
        failure_state.get(
            "hitl_required"
        )
        is False,
        "Failure workflow is not represented as HITL.",
    )


# ============================================================
# MAIN
# ============================================================

def main() -> None:

    global BACKUP_DB

    print()
    print("=" * 70)
    print(
        "STERLING & VANCE"
    )
    print(
        "SANCTIONS GRAPH E2E INTEGRATION TEST"
    )
    print("=" * 70)

    print(
        f"Project root: {ROOT}"
    )

    print(
        f"Bank DB: {BANK_DB}"
    )

    print(
        f"Test prefix: {TEST_PREFIX}"
    )

    # --------------------------------------------------------
    # BACKUP REAL DB
    # --------------------------------------------------------

    BACKUP_DB = backup_database()

    print()
    print(
        f"[PASS] Database backup created: {BACKUP_DB}"
    )

    try:

        # ----------------------------------------------------
        # RUN TESTS
        # ----------------------------------------------------

        test_start_and_checkpoint()

        test_waiting_for_external_event()

        test_sanctions_update()

        test_re_evaluation()

        test_hitl()

        test_real_failure_and_resume()

        test_sanctions_history()

        test_fresh_process_checkpoint()

        test_state_completeness()

        test_hitl_and_failure_are_distinct()

        # ----------------------------------------------------
        # SUCCESS
        # ----------------------------------------------------

        print()
        print("=" * 70)
        print(
            "ALL SANCTIONS GRAPH TESTS PASSED"
        )
        print("=" * 70)

    except Exception:

        print()
        print("=" * 70)
        print(
            "SANCTIONS GRAPH TEST FAILED"
        )
        print("=" * 70)

        raise

    finally:

        # ----------------------------------------------------
        # ALWAYS RESTORE REAL DATABASE
        # ----------------------------------------------------

        if BACKUP_DB is not None:

            print()
            print(
                "Restoring original bank.db..."
            )

            restore_database(
                BACKUP_DB
            )

            print(
                "[PASS] Original bank.db restored."
            )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()