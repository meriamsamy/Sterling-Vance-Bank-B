import { NextResponse } from 'next/server';

import { getWorkflowTickets } from '@/lib/admin-db';

export const runtime = 'nodejs';

export async function GET() {
  try {
    const tickets = getWorkflowTickets();

    const result = tickets.map((ticket) => ({
      id: ticket.ticket_id,
      workflowType: ticket.workflow_type,
      wireId: ticket.wire_id,
      reviewId: ticket.review_id,
      status: ticket.status,
      errorType: ticket.error_type,
      errorMessage: ticket.error_message,
      failedNode: ticket.failed_node,
      createdAt: ticket.created_at,
      resolvedAt: ticket.resolved_at,
    }));

    return NextResponse.json(result);
  } catch (err) {
    console.error('Failed to load workflow tickets:', err);

    return NextResponse.json(
      {
        detail: `Failed to load workflow tickets: ${
          (err as Error).message
        }`,
      },
      { status: 500 }
    );
  }
}