import { NextRequest, NextResponse } from 'next/server';
import { getAgentById, removeTool } from '@/lib/admin-db';

export const runtime = 'nodejs';

export async function DELETE(
  _req: NextRequest,
  { params }: { params: { agentId: string; toolId: string } }
) {
  try {
    if (!getAgentById(params.agentId)) {
      return NextResponse.json(
        { detail: 'Agent not found' },
        { status: 404 }
      );
    }
    removeTool(params.agentId, params.toolId);
    return NextResponse.json({ ok: true });
  } catch (err) {
    return NextResponse.json(
      { detail: `Failed to remove tool: ${(err as Error).message}` },
      { status: 500 }
    );
  }
}
