import { NextRequest, NextResponse } from 'next/server';
import { getAgentById, getAgentTools, assignTool } from '@/lib/admin-db';

export const runtime = 'nodejs';

export async function GET(
  _req: NextRequest,
  { params }: { params: { agentId: string } }
) {
  try {
    if (!getAgentById(params.agentId)) {
      return NextResponse.json(
        { detail: 'Agent not found' },
        { status: 404 }
      );
    }
    const tools = getAgentTools(params.agentId);
    return NextResponse.json(
      tools.map((t) => ({
        toolId: t.tool_name,
        toolName: t.tool_name,
        toolDescription: t.description ?? '',
        category: t.category,
        status: t.status as 'active' | 'disabled' | 'error',
      }))
    );
  } catch (err) {
    return NextResponse.json(
      { detail: `Failed to load agent tools: ${(err as Error).message}` },
      { status: 500 }
    );
  }
}

export async function POST(
  req: NextRequest,
  { params }: { params: { agentId: string } }
) {
  try {
    if (!getAgentById(params.agentId)) {
      return NextResponse.json(
        { detail: 'Agent not found' },
        { status: 404 }
      );
    }
    const body = await req.json();
    const toolId = body?.toolId;
    if (!toolId || typeof toolId !== 'string') {
      return NextResponse.json(
        { detail: 'toolId is required' },
        { status: 400 }
      );
    }
    assignTool(params.agentId, toolId);
    return NextResponse.json({ ok: true });
  } catch (err) {
    return NextResponse.json(
      { detail: `Failed to assign tool: ${(err as Error).message}` },
      { status: 500 }
    );
  }
}
