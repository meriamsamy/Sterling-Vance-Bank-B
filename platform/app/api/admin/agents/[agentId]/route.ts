import { NextRequest, NextResponse } from 'next/server';
import { getAgentById, getAgentTools } from '@/lib/admin-db';

export const runtime = 'nodejs';

export async function GET(
  _req: NextRequest,
  { params }: { params: { agentId: string } }
) {
  try {
    const agent = getAgentById(params.agentId);
    if (!agent) {
      return NextResponse.json(
        { detail: 'Agent not found' },
        { status: 404 }
      );
    }
    const tools = getAgentTools(params.agentId);
    return NextResponse.json({
      id: agent.agent_id,
      name: agent.name,
      description: agent.description ?? '',
      status: 'operational' as const,
      assignedToolCount: tools.length,
      capabilities: [],
    });
  } catch (err) {
    return NextResponse.json(
      { detail: `Failed to load agent: ${(err as Error).message}` },
      { status: 500 }
    );
  }
}
