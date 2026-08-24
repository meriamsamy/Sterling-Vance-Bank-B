import { NextResponse } from 'next/server';
import { resolveWorkflowTicket } from '@/lib/admin-db';

export const runtime = 'nodejs';

export async function POST(req: Request) {
  try {
    const { ticketId } = await req.json();

    if (!ticketId) {
      return NextResponse.json(
        { detail: 'ticketId is required' },
        { status: 400 }
      );
    }

    resolveWorkflowTicket(Number(ticketId));

    return NextResponse.json({ success: true });
  } catch (err) {
    console.error('Failed to resolve workflow ticket:', err);

    return NextResponse.json(
      {
        detail: `Failed to resolve ticket: ${
          (err as Error).message
        }`,
      },
      { status: 500 }
    );
  }
}