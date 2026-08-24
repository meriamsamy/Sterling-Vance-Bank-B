import { NextRequest, NextResponse } from 'next/server';
import type { AgentId } from '@/lib/agents';

export const runtime = 'nodejs';

interface ChatRequestBody {
  agent_name?: string;
  message?: string;
  thread_id?: string;
}

const PYTHON_BACKEND_URL =
  process.env.PYTHON_BACKEND_URL ?? 'http://localhost:8000';

export async function POST(req: NextRequest) {
  let body: ChatRequestBody;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json(
      { error: 'Invalid JSON body.' },
      { status: 400 }
    );
  }

  const agent_name = body.agent_name?.trim();
  const message = body.message?.trim();
  const thread_id = body.thread_id?.trim();

  if (!agent_name) {
    return NextResponse.json(
      { error: 'Missing required field: agent_name.' },
      { status: 400 }
    );
  }
  if (!message) {
    return NextResponse.json(
      { error: 'Missing required field: message.' },
      { status: 400 }
    );
  }

  const validAgents: AgentId[] = [
    'customer-risk-monitoring',
    'planning-decomposition',
    'memory-rag',
  ];
  if (!validAgents.includes(agent_name as AgentId)) {
    return NextResponse.json(
      { error: `Unknown agent: ${agent_name}.` },
      { status: 400 }
    );
  }

  const payload = {
    agent_name,
    message,
    thread_id: thread_id || null,
  };

  try {
    const upstream = await fetch(`${PYTHON_BACKEND_URL}/invoke`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(60_000),
    });

    if (!upstream.ok) {
      const text = await upstream.text().catch(() => '');
      return NextResponse.json(
        {
          error: 'Upstream agent error.',
          detail: text || `Status ${upstream.status}`,
        },
        { status: 502 }
      );
    }

    const data = await upstream.json().catch(() => ({}));
    return NextResponse.json({
      response:
        data.response ??
        data.output ??
        data.message ??
        'Agent returned an empty response.',
      thread_id: data.thread_id ?? thread_id ?? null,
    });
  } catch (err) {
    const detail =
      err instanceof Error ? err.message : 'Unknown fetch failure.';
    return NextResponse.json(
      {
        error: 'Failed to reach the Python backend.',
        detail,
        fallback:
          'The Python LangGraph server is not running. Connect it at PYTHON_BACKEND_URL to enable live agent responses.',
      },
      { status: 503 }
    );
  }
}

export async function OPTIONS() {
  return new NextResponse(null, {
    status: 204,
    headers: {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
    },
  });
}
