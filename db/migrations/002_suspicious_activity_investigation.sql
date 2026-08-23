-- ============================================================
-- Suspicious Activity Investigation state (Issue 7).
--
-- Reuses the existing shared workflow_tickets / human_review_tasks
-- tables already in schema.sql (they're generic: workflow_type
-- distinguishes 'suspicious_activity' rows from 'sanctions_change'
-- rows, etc.) — this migration only adds the two tables specific to
-- the investigation lifecycle itself: the investigation record, and
-- its evidence log.
--
-- Idempotent (IF NOT EXISTS): safe to run more than once.
--
-- Run (from project root):
--   sqlite3 db/bank.db < db/migrations/002_suspicious_activity_investigation.sql
-- ============================================================

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS investigations (
    investigation_id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL,              -- collecting_evidence | analyzing_evidence |
                                        -- waiting_for_evidence | reassessing |
                                        -- waiting_for_admin | closed | rejected | failed
    risk_level TEXT,                   -- low | medium | high | unknown
    confidence REAL,
    decision TEXT,                     -- closed_legitimate_activity | closed_potential_fraud |
                                        -- closed_potential_money_laundering | rejected
    decision_reason TEXT,
    thread_id TEXT,                    -- LangGraph checkpoint thread — see
                                        -- investigation_graph_runner._thread_id_for()
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
);

CREATE INDEX IF NOT EXISTS idx_investigations_thread_id
    ON investigations (thread_id);

CREATE TABLE IF NOT EXISTS investigation_evidence (
    id INTEGER PRIMARY KEY,
    investigation_id INTEGER NOT NULL,
    evidence_type TEXT NOT NULL,       -- customer | accounts | transactions |
                                        -- wires | sanctions | related_employees |
                                        -- external (anything submitted later)
    evidence_data TEXT NOT NULL,       -- JSON-encoded snapshot
    source TEXT NOT NULL,              -- 'mcp:get_customer_accounts', 'external:compliance_team', ...
    created_at TEXT NOT NULL,
    FOREIGN KEY (investigation_id) REFERENCES investigations(investigation_id)
);

CREATE INDEX IF NOT EXISTS idx_investigation_evidence_investigation
    ON investigation_evidence (investigation_id);

CREATE INDEX IF NOT EXISTS idx_investigations_status
    ON investigations (status);