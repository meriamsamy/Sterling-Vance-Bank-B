import { NextResponse } from 'next/server';
import { getAllTools, getToolAssignments } from '@/lib/admin-db';

export const runtime = 'nodejs';

export async function GET() {
  try {
    const tools = getAllTools();
    const result = tools.map((t) => {
      const assignments = getToolAssignments(t.tool_name);
      return {
        id: t.tool_name,
        name: t.tool_name,
        description: t.description ?? '',
        category: t.category,
        status: t.status as 'active' | 'disabled' | 'error',
        assignedAgentIds: assignments.map((a) => a.agent_id),
        assignedAgentNames: assignments.map((a) => a.name),
      };
    });
    return NextResponse.json(result);
  } catch (err) {
    return NextResponse.json(
      { detail: `Failed to load tools: ${(err as Error).message}` },
      { status: 500 }
    );
  }
}
