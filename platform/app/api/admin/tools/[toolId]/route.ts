import { NextRequest, NextResponse } from 'next/server';
import { getAllTools, getToolAssignments } from '@/lib/admin-db';

export const runtime = 'nodejs';

export async function GET(
  _req: NextRequest,
  { params }: { params: { toolId: string } }
) {
  try {
    const tools = getAllTools();
    const tool = tools.find((t) => t.tool_name === params.toolId);
    if (!tool) {
      return NextResponse.json(
        { detail: 'Tool not found' },
        { status: 404 }
      );
    }
    const assignments = getToolAssignments(tool.tool_name);
    return NextResponse.json({
      id: tool.tool_name,
      name: tool.tool_name,
      description: tool.description ?? '',
      category: tool.category,
      status: tool.status as 'active' | 'disabled' | 'error',
      assignedAgentIds: assignments.map((a) => a.agent_id),
      assignedAgentNames: assignments.map((a) => a.name),
    });
  } catch (err) {
    return NextResponse.json(
      { detail: `Failed to load tool: ${(err as Error).message}` },
      { status: 500 }
    );
  }
}
