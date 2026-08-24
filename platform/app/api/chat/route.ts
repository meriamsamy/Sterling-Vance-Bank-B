import { NextResponse } from 'next/server';

const PYTHON_BACKEND_URL = process.env.PYTHON_BACKEND_URL || 'http://localhost:8000';

export async function POST(req: Request) {
  try {
    const body = await req.json();
    const { agent_name, message, thread_id } = body;

    const pythonResponse = await fetch(`${PYTHON_BACKEND_URL}/invoke`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        agent_name,
        message,
        thread_id,
      }),
    });

    if (!pythonResponse.ok) {
      const errorText = await pythonResponse.text();
      return NextResponse.json(
        { error: `Python Backend Error: ${errorText}` },
        { status: pythonResponse.status }
      );
    }

    const data = await pythonResponse.json();
    
    return NextResponse.json({
      response: data.response,
      thread_id: data.thread_id,
    });

  } catch (error: any) {
    return NextResponse.json(
      { error: `Gateway Connection Failed: ${error.message}` },
      { status: 500 }
    );
  }
}