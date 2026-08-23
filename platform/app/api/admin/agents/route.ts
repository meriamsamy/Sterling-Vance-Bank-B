import { NextResponse } from 'next/server';
import { getAllAgents, getAgentTools } from '@/lib/admin-db';

export const runtime = 'nodejs';

export async function GET() {
  try {
    const agents = getAllAgents();
    const result = agents.map((a) => ({
      id: a.agent_id,
      name: a.name,
      description: a.description ?? '',
      status: 'operational' as const,
      assignedToolCount: getAgentTools(a.agent_id).length,
      capabilities: [],
    }));
    return NextResponse.json(result);
  } catch (err) {
    return NextResponse.json(
      { detail: `Failed to load agents: ${(err as Error).message}` },
      { status: 500 }
    );
  }
}
