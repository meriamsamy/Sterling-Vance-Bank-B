import { join } from "node:path";
import { existsSync } from "node:fs";

// node:sqlite is experimental in Node 22 and may not exist
// in the installed @types/node version.
// Using require + a local interface avoids the type error.
const { DatabaseSync } = require("node:sqlite") as {
  DatabaseSync: any;
};

type SQLiteDB = {
  prepare(sql: string): {
    all(...params: unknown[]): Record<string, unknown>[];
    get(...params: unknown[]): Record<string, unknown> | undefined;
    run(...params: unknown[]): void;
  };

  exec(sql: string): void;

  close(): void;
};

function getDatabasePath(): string {
  const candidates = [
    // When Next.js runs from /platform
    join(process.cwd(), "..", "db", "bank.db"),

    // When Next.js runs from project root
    join(process.cwd(), "db", "bank.db"),
  ];

  const existing = candidates.find((path) =>
    existsSync(path)
  );

  if (!existing) {
    throw new Error(
      `Database not found. Tried:\n${candidates.join("\n")}`
    );
  }

  return existing;
}

let _db: SQLiteDB | null = null;

function db(): SQLiteDB {
  if (!_db) {
    const DB_PATH = getDatabasePath();

    _db = new DatabaseSync(DB_PATH) as SQLiteDB;

    _db.exec(`
      PRAGMA foreign_keys = ON;
    `);
  }

  return _db;
}

/* ============================================================
   AGENTS
   ============================================================ */

export interface AgentRow {
  agent_id: string;
  name: string;
  description: string;
  created_at: string;
}

export function getAllAgents(): AgentRow[] {
  const rows = db()
    .prepare(`
      SELECT
        agent_id,
        name,
        description,
        created_at
      FROM agents
      ORDER BY name
    `)
    .all() as unknown as AgentRow[];

  return rows;
}

export function getAgentById(
  agentId: string
): AgentRow | null {
  const row = db()
    .prepare(`
      SELECT
        agent_id,
        name,
        description,
        created_at
      FROM agents
      WHERE agent_id = ?
    `)
    .get(agentId) as unknown as
    | AgentRow
    | undefined;

  return row ?? null;
}

/* ============================================================
   TOOLS
   ============================================================ */

export interface ToolRow {
  tool_name: string;
  description: string;
  category: string;
  status: string;
}

export function getAgentTools(
  agentId: string
): ToolRow[] {
  const rows = db()
    .prepare(`
      SELECT
        t.tool_name,
        t.description,
        t.category,
        t.status
      FROM agent_tools at
      JOIN tools t
        ON t.tool_name = at.tool_name
      WHERE at.agent_id = ?
      ORDER BY t.tool_name
    `)
    .all(agentId) as unknown as ToolRow[];

  return rows;
}

export function getAllTools(): ToolRow[] {
  const rows = db()
    .prepare(`
      SELECT
        tool_name,
        description,
        category,
        status
      FROM tools
      ORDER BY tool_name
    `)
    .all() as unknown as ToolRow[];

  return rows;
}

export function getAvailableTools(
  agentId: string
): ToolRow[] {
  const rows = db()
    .prepare(`
      SELECT
        t.tool_name,
        t.description,
        t.category,
        t.status
      FROM tools t
      WHERE t.tool_name NOT IN (
        SELECT tool_name
        FROM agent_tools
        WHERE agent_id = ?
      )
      ORDER BY t.tool_name
    `)
    .all(agentId) as unknown as ToolRow[];

  return rows;
}

export function assignTool(
  agentId: string,
  toolName: string
): void {
  db()
    .prepare(`
      INSERT OR IGNORE INTO agent_tools (
        agent_id,
        tool_name
      )
      SELECT ?, ?
      WHERE EXISTS (
        SELECT 1
        FROM tools
        WHERE tool_name = ?
      )
    `)
    .run(
      agentId,
      toolName,
      toolName
    );
}

export function removeTool(
  agentId: string,
  toolName: string
): void {
  db()
    .prepare(`
      DELETE FROM agent_tools
      WHERE agent_id = ?
        AND tool_name = ?
    `)
    .run(
      agentId,
      toolName
    );
}

export function getToolAssignments(
  toolName: string
): AgentRow[] {
  const rows = db()
    .prepare(`
      SELECT
        a.agent_id,
        a.name,
        a.description,
        a.created_at
      FROM agent_tools at
      JOIN agents a
        ON a.agent_id = at.agent_id
      WHERE at.tool_name = ?
      ORDER BY a.name
    `)
    .all(toolName) as unknown as AgentRow[];

  return rows;
}

/* ============================================================
   HUMAN-IN-THE-LOOP
   ============================================================ */

export interface HumanReviewTaskRow {
  task_id: number;
  workflow_type: string;
  wire_id: number | null;
  review_id: number | null;
  status: string;
  reason: string;
  recommended_action: string | null;
  assigned_to: number | null;
  decision: string | null;
  notes: string | null;
  created_at: string;
  completed_at: string | null;
}

export function getHumanReviewTasks(): HumanReviewTaskRow[] {
  const rows = db()
    .prepare(`
      SELECT
        task_id,
        workflow_type,
        wire_id,
        review_id,
        status,
        reason,
        recommended_action,
        assigned_to,
        decision,
        notes,
        created_at,
        completed_at
      FROM human_review_tasks
      ORDER BY
        CASE
          WHEN status = 'pending' THEN 0
          ELSE 1
        END,
        created_at DESC
    `)
    .all() as unknown as HumanReviewTaskRow[];

  return rows;
}

export function getHumanReviewTaskById(
  taskId: number
): HumanReviewTaskRow | null {
  const row = db()
    .prepare(`
      SELECT
        task_id,
        workflow_type,
        wire_id,
        review_id,
        status,
        reason,
        recommended_action,
        assigned_to,
        decision,
        notes,
        created_at,
        completed_at
      FROM human_review_tasks
      WHERE task_id = ?
    `)
    .get(taskId) as unknown as
    | HumanReviewTaskRow
    | undefined;

  return row ?? null;
}

/**
 * Fallback/audit operation.
 *
 * IMPORTANT:
 * The normal HITL flow should resume the LangGraph
 * first. The Python workflow should then persist
 * the final human decision.
 *
 * This function is kept for DB-side completion when
 * needed by the backend.
 */
export function completeHumanReviewTask(
  taskId: number,
  decision: 'approved' | 'rejected' | 'modified',
  notes: string | null = null,
  assignedTo: number | null = null
): void {
  db()
    .prepare(`
      UPDATE human_review_tasks
      SET
        status = 'completed',
        decision = ?,
        notes = ?,
        assigned_to = ?,
        completed_at = CURRENT_TIMESTAMP
      WHERE task_id = ?
        AND status != 'completed'
    `)
    .run(decision, notes, assignedTo, taskId);
}

/* ============================================================
   WORKFLOW FAILURE TICKETS
   ============================================================ */

export interface WorkflowTicketRow {
  ticket_id: number;
  workflow_type: string;
  wire_id: number | null;
  review_id: number | null;
  status: string;
  error_type: string | null;
  error_message: string | null;
  failed_node: string | null;
  created_at: string;
  resolved_at: string | null;
}

export function getWorkflowTickets(): WorkflowTicketRow[] {
  const rows = db()
    .prepare(`
      SELECT
        ticket_id,
        workflow_type,
        wire_id,
        review_id,
        status,
        error_type,
        error_message,
        failed_node,
        created_at,
        resolved_at
      FROM workflow_tickets
      ORDER BY
        CASE
          WHEN status != 'resolved' THEN 0
          ELSE 1
        END,
        created_at DESC
    `)
    .all() as unknown as WorkflowTicketRow[];

  return rows;
}

export function getWorkflowTicketById(
  ticketId: number
): WorkflowTicketRow | null {
  const row = db()
    .prepare(`
      SELECT
        ticket_id,
        workflow_type,
        wire_id,
        review_id,
        status,
        error_type,
        error_message,
        failed_node,
        created_at,
        resolved_at
      FROM workflow_tickets
      WHERE ticket_id = ?
    `)
    .get(ticketId) as unknown as
    | WorkflowTicketRow
    | undefined;

  return row ?? null;
}

export function resolveWorkflowTicket(
  ticketId: number
): void {
  db()
    .prepare(`
      UPDATE workflow_tickets
      SET
        status = 'resolved',
        resolved_at = CURRENT_TIMESTAMP
      WHERE ticket_id = ?
    `)
    .run(ticketId);
}