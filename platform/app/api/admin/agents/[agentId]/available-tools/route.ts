import { NextRequest, NextResponse } from 'next/server';
import {
  getAgentById,
  getAllTools,
  getAgentTools,
} from '@/lib/admin-db';

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

    const allTools = getAllTools();

    const assigned = new Set(
      getAgentTools(params.agentId).map(
        (t) => t.tool_name
      )
    );

    return NextResponse.json(
      allTools.map((t) => ({
        toolId: t.tool_name,
        toolName: t.tool_name,
        toolDescription: t.description ?? '',
        category: t.category,
        alreadyAssigned: assigned.has(
          t.tool_name
        ),
      }))
    );

  } catch (err) {
    return NextResponse.json(
      {
        detail: `Failed to load tools: ${
          (err as Error).message
        }`,
      },
      { status: 500 }
    );
  }
}