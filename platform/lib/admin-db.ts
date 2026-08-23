import { join } from "node:path";
import { existsSync } from "node:fs";

// node:sqlite is experimental in Node 22 and not in @types/node 20.
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

const DB_PATH = join(
  process.cwd(),
  "..",
  "db",
  "bank.db"
);

let _db: SQLiteDB | null = null;

function db(): SQLiteDB {
  if (!_db) {
    if (!existsSync(DB_PATH)) {
      throw new Error(
        `Database not found: ${DB_PATH}`
      );
    }

    _db = new DatabaseSync(DB_PATH) as SQLiteDB;

    _db.exec(
      "PRAGMA foreign_keys = ON"
    );
  }

  return _db;
}


export interface AgentRow {
  agent_id: string;
  name: string;
  description: string;
  created_at: string;
}


export interface ToolRow {
  tool_name: string;
  description: string;
  category: string;
  status: string;
}


export function getAllAgents(): AgentRow[] {

  const rows = db()
    .prepare(
      `
      SELECT
        agent_id,
        name,
        description,
        created_at
      FROM agents
      ORDER BY name
      `
    )
    .all() as unknown as AgentRow[];

  return rows;
}


export function getAgentById(
  agentId: string
): AgentRow | null {

  const row = db()
    .prepare(
      `
      SELECT
        agent_id,
        name,
        description,
        created_at
      FROM agents
      WHERE agent_id = ?
      `
    )
    .get(agentId) as unknown as
    | AgentRow
    | undefined;

  return row ?? null;
}


export function getAgentTools(
  agentId: string
): ToolRow[] {

  const rows = db()
    .prepare(
      `
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
      `
    )
    .all(agentId) as unknown as ToolRow[];

  return rows;
}


export function getAllTools(): ToolRow[] {

  const rows = db()
    .prepare(
      `
      SELECT
        tool_name,
        description,
        category,
        status
      FROM tools
      ORDER BY tool_name
      `
    )
    .all() as unknown as ToolRow[];

  return rows;
}


export function getAvailableTools(
  agentId: string
): ToolRow[] {

  const rows = db()
    .prepare(
      `
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
      `
    )
    .all(agentId) as unknown as ToolRow[];

  return rows;
}


export function assignTool(
  agentId: string,
  toolName: string
): void {

  db()
    .prepare(
      `
      INSERT OR IGNORE INTO agent_tools
      (
        agent_id,
        tool_name
      )
      SELECT ?, ?
      WHERE EXISTS (
        SELECT 1
        FROM tools
        WHERE tool_name = ?
      )
      `
    )
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
    .prepare(
      `
      DELETE FROM agent_tools
      WHERE agent_id = ?
        AND tool_name = ?
      `
    )
    .run(
      agentId,
      toolName
    );
}


export function getToolAssignments(
  toolName: string
): AgentRow[] {

  const rows = db()
    .prepare(
      `
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
      `
    )
    .all(toolName) as unknown as AgentRow[];

  return rows;
}