import { NextResponse } from 'next/server';

import { getHumanReviewTasks } from '@/lib/admin-db';

export const runtime = 'nodejs';

export async function GET() {
  try {
    const tasks = getHumanReviewTasks();

    const result = tasks.map((task) => ({
      id: task.task_id,
      workflowType: task.workflow_type,
      wireId: task.wire_id,
      reviewId: task.review_id,
      status: task.status,
      reason: task.reason,
      recommendedAction: task.recommended_action,
      assignedTo: task.assigned_to,
      decision: task.decision,
      notes: task.notes,
      createdAt: task.created_at,
      completedAt: task.completed_at,
    }));

    return NextResponse.json(result);
  } catch (err) {
    return NextResponse.json(
      {
        detail: `Failed to load HITL tasks: ${
          (err as Error).message
        }`,
      },
      { status: 500 }
    );
  }
}