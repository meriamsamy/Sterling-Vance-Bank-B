'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';

type HumanReviewTask = {
  id: number;
  workflowType: string;
  wireId: number | null;
  reviewId: number | null;
  status: string;
  reason: string;
  recommendedAction: string | null;
  assignedTo: number | null;
  decision: string | null;
  notes: string | null;
  createdAt: string;
  completedAt: string | null;
};

export default function HITLPage() {
  const [tasks, setTasks] = useState<HumanReviewTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [processingId, setProcessingId] = useState<number | null>(null);

  useEffect(() => {
    async function loadTasks() {
      try {
        const res = await fetch('/api/admin/hitl');

        if (!res.ok) {
          throw new Error('Failed to load HITL tasks');
        }

        const data = await res.json();
        setTasks(data);
      } catch (err) {
        console.error(err);
        setError('Failed to load HITL tasks.');
      } finally {
        setLoading(false);
      }
    }

    loadTasks();
  }, []);

  async function handleDecision(
    taskId: number,
    decision: 'approved' | 'rejected'
  ) {
    try {
      setProcessingId(taskId);

      const res = await fetch('/api/admin/hitl', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          taskId,
          decision,
        }),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => null);

        throw new Error(
          data?.detail || 'Failed to submit HITL decision'
        );
      }

      setTasks((prev) =>
        prev.map((task) =>
          task.id === taskId
            ? {
                ...task,
                status: 'completed',
                decision,
                completedAt: new Date().toISOString(),
              }
            : task
        )
      );
    } catch (err) {
      console.error(err);

      alert(
        err instanceof Error
          ? err.message
          : 'Failed to submit HITL decision'
      );
    } finally {
      setProcessingId(null);
    }
  }

  const pendingTasks = tasks.filter(
    (task) => task.status !== 'completed'
  );

  const completedTasks = tasks.filter(
    (task) => task.status === 'completed'
  );

  return (
    <div className="min-h-screen bg-background p-8">
      <div className="mx-auto max-w-6xl">

        {/* Header */}
        <div className="mb-8 flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold">
              Human-in-the-Loop
            </h1>

            <p className="mt-2 text-muted-foreground">
              Review workflow decisions that require human approval.
            </p>
          </div>

          <Link
            href="/admin"
            className="rounded-md border px-4 py-2 text-sm hover:bg-muted"
          >
            Back to Dashboard
          </Link>
        </div>

        {/* Summary */}
        <div className="mb-8 grid gap-4 md:grid-cols-3">

          <div className="rounded-xl border p-5">
            <p className="text-sm text-muted-foreground">
              Total Tasks
            </p>

            <p className="mt-2 text-2xl font-bold">
              {tasks.length}
            </p>
          </div>

          <div className="rounded-xl border p-5">
            <p className="text-sm text-muted-foreground">
              Pending Review
            </p>

            <p className="mt-2 text-2xl font-bold">
              {pendingTasks.length}
            </p>
          </div>

          <div className="rounded-xl border p-5">
            <p className="text-sm text-muted-foreground">
              Completed
            </p>

            <p className="mt-2 text-2xl font-bold">
              {completedTasks.length}
            </p>
          </div>

        </div>

        {/* Loading */}
        {loading && (
          <div className="rounded-xl border p-6">
            <p className="text-muted-foreground">
              Loading HITL tasks...
            </p>
          </div>
        )}

        {/* Error */}
        {!loading && error && (
          <div className="rounded-xl border border-red-200 p-6">
            <p className="text-red-600">
              {error}
            </p>
          </div>
        )}

        {/* Empty */}
        {!loading && !error && tasks.length === 0 && (
          <div className="rounded-xl border p-8 text-center">
            <h2 className="font-semibold">
              No HITL tasks
            </h2>

            <p className="mt-2 text-sm text-muted-foreground">
              There are currently no human review tasks.
            </p>
          </div>
        )}

        {/* Tasks */}
        {!loading && !error && tasks.length > 0 && (
          <div className="space-y-4">

            {tasks.map((task) => (
              <div
                key={task.id}
                className="rounded-xl border p-6"
              >

                {/* Task Header */}
                <div className="flex items-start justify-between gap-4">

                  <div>
                    <h2 className="font-semibold">
                      HITL Task #{task.id}
                    </h2>

                    <p className="mt-1 text-sm text-muted-foreground">
                      {task.workflowType}
                    </p>
                  </div>

                  <span
                    className={`rounded-full px-3 py-1 text-xs font-semibold ${
                      task.status === 'completed'
                        ? 'bg-green-100 text-green-700'
                        : 'bg-yellow-100 text-yellow-700'
                    }`}
                  >
                    {task.status}
                  </span>

                </div>

                {/* Task Information */}
                <div className="mt-5 grid gap-4 md:grid-cols-2">

                  <div>
                    <p className="text-xs text-muted-foreground">
                      Wire ID
                    </p>

                    <p className="mt-1 text-sm">
                      {task.wireId ?? '—'}
                    </p>
                  </div>

                  <div>
                    <p className="text-xs text-muted-foreground">
                      Review ID
                    </p>

                    <p className="mt-1 text-sm">
                      {task.reviewId ?? '—'}
                    </p>
                  </div>

                  <div>
                    <p className="text-xs text-muted-foreground">
                      Reason
                    </p>

                    <p className="mt-1 text-sm">
                      {task.reason}
                    </p>
                  </div>

                  <div>
                    <p className="text-xs text-muted-foreground">
                      Recommended Action
                    </p>

                    <p className="mt-1 text-sm">
                      {task.recommendedAction ?? '—'}
                    </p>
                  </div>

                  <div>
                    <p className="text-xs text-muted-foreground">
                      Assigned To
                    </p>

                    <p className="mt-1 text-sm">
                      {task.assignedTo ?? 'Unassigned'}
                    </p>
                  </div>

                  <div>
                    <p className="text-xs text-muted-foreground">
                      Created At
                    </p>

                    <p className="mt-1 text-sm">
                      {task.createdAt}
                    </p>
                  </div>

                  <div>
                    <p className="text-xs text-muted-foreground">
                      Decision
                    </p>

                    <p className="mt-1 text-sm">
                      {task.decision ?? 'No decision yet'}
                    </p>
                  </div>

                  <div>
                    <p className="text-xs text-muted-foreground">
                      Completed At
                    </p>

                    <p className="mt-1 text-sm">
                      {task.completedAt ?? 'Not completed'}
                    </p>
                  </div>

                </div>

                {/* Notes */}
                {task.notes && (
                  <div className="mt-5 rounded-lg bg-muted p-4">
                    <p className="text-xs font-semibold">
                      Notes
                    </p>

                    <p className="mt-2 text-sm text-muted-foreground">
                      {task.notes}
                    </p>
                  </div>
                )}

                {/* APPROVE / REJECT */}
                {task.status !== 'completed' && (
                  <div className="mt-6 flex gap-3 border-t pt-5">

                    <button
                      onClick={() =>
                        handleDecision(task.id, 'approved')
                      }
                      disabled={processingId === task.id}
                      className="rounded-md bg-green-600 px-5 py-2 text-sm font-semibold text-white hover:bg-green-700 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {processingId === task.id
                        ? 'Processing...'
                        : 'Approve'}
                    </button>

                    <button
                      onClick={() =>
                        handleDecision(task.id, 'rejected')
                      }
                      disabled={processingId === task.id}
                      className="rounded-md bg-red-600 px-5 py-2 text-sm font-semibold text-white hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {processingId === task.id
                        ? 'Processing...'
                        : 'Reject'}
                    </button>

                  </div>
                )}

                {/* Decision Result */}
                {task.status === 'completed' && (
                  <div className="mt-6 rounded-lg border p-4">
                    <p className="text-sm font-semibold">
                      Human Decision
                    </p>

                    <p className="mt-1 text-sm">
                      {task.decision === 'approved'
                        ? 'Approved'
                        : 'Rejected'}
                    </p>
                  </div>
                )}

              </div>
            ))}

          </div>
        )}

      </div>
    </div>
  );
}