'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';

type WorkflowTicket = {
  id: number;
  workflowType: string;
  wireId: number | null;
  reviewId: number | null;
  status: string;
  errorType: string | null;
  errorMessage: string | null;
  failedNode: string | null;
  createdAt: string;
  resolvedAt: string | null;
};

export default function TicketsPage() {
  const [tickets, setTickets] = useState<WorkflowTicket[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function loadTickets() {
      try {
        const res = await fetch('/api/admin/tickets');


        if (!res.ok) {
          throw new Error('Failed to load tickets');
        }

        const data = await res.json();
        setTickets(data);
      } catch (err) {
        console.error(err);
        setError('Failed to load workflow tickets.');
      } finally {
        setLoading(false);
      }
    }

    loadTickets();
  }, []);

  const openTickets = tickets.filter(
    (ticket) => ticket.status !== 'resolved'
  );

  const resolvedTickets = tickets.filter(
    (ticket) => ticket.status === 'resolved'
  );

  return (
    <div className="min-h-screen bg-background p-8">
      <div className="mx-auto max-w-6xl">

        {/* Header */}
        <div className="mb-8 flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold">
              Workflow Tickets
            </h1>

            <p className="mt-2 text-muted-foreground">
              Monitor workflow failures and recovery tickets.
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
              Total Tickets
            </p>

            <p className="mt-2 text-2xl font-bold">
              {tickets.length}
            </p>
          </div>

          <div className="rounded-xl border p-5">
            <p className="text-sm text-muted-foreground">
              Open Tickets
            </p>

            <p className="mt-2 text-2xl font-bold">
              {openTickets.length}
            </p>
          </div>

          <div className="rounded-xl border p-5">
            <p className="text-sm text-muted-foreground">
              Resolved
            </p>

            <p className="mt-2 text-2xl font-bold">
              {resolvedTickets.length}
            </p>
          </div>

        </div>

        {/* Loading */}
        {loading && (
          <div className="rounded-xl border p-6">
            <p className="text-muted-foreground">
              Loading workflow tickets...
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
        {!loading && !error && tickets.length === 0 && (
          <div className="rounded-xl border p-8 text-center">
            <h2 className="font-semibold">
              No workflow tickets
            </h2>

            <p className="mt-2 text-sm text-muted-foreground">
              There are currently no workflow failures recorded.
            </p>
          </div>
        )}

        {/* Tickets */}
        {!loading && !error && tickets.length > 0 && (
          <div className="space-y-4">

            {tickets.map((ticket) => (
              <div
                key={ticket.id}
                className="rounded-xl border p-6"
              >

                {/* Ticket header */}
                <div className="flex items-start justify-between gap-4">

                  <div>
                    <h2 className="font-semibold">
                      Ticket #{ticket.id}
                    </h2>

                    <p className="mt-1 text-sm text-muted-foreground">
                      {ticket.workflowType}
                    </p>
                  </div>

                  <span
                    className={`rounded-full px-3 py-1 text-xs font-semibold ${
                      ticket.status === 'resolved'
                        ? 'bg-green-100 text-green-700'
                        : 'bg-red-100 text-red-700'
                    }`}
                  >
                    {ticket.status}
                  </span>

                </div>

                {/* Ticket information */}
                <div className="mt-5 grid gap-4 md:grid-cols-2">

                  <div>
                    <p className="text-xs text-muted-foreground">
                      Wire ID
                    </p>

                    <p className="mt-1 text-sm">
                      {ticket.wireId ?? '—'}
                    </p>
                  </div>

                  <div>
                    <p className="text-xs text-muted-foreground">
                      Review ID
                    </p>

                    <p className="mt-1 text-sm">
                      {ticket.reviewId ?? '—'}
                    </p>
                  </div>

                  <div>
                    <p className="text-xs text-muted-foreground">
                      Error Type
                    </p>

                    <p className="mt-1 text-sm">
                      {ticket.errorType ?? '—'}
                    </p>
                  </div>

                  <div>
                    <p className="text-xs text-muted-foreground">
                      Failed Node
                    </p>

                    <p className="mt-1 text-sm">
                      {ticket.failedNode ?? '—'}
                    </p>
                  </div>

                  <div>
                    <p className="text-xs text-muted-foreground">
                      Created At
                    </p>

                    <p className="mt-1 text-sm">
                      {ticket.createdAt}
                    </p>
                  </div>

                  <div>
                    <p className="text-xs text-muted-foreground">
                      Resolved At
                    </p>

                    <p className="mt-1 text-sm">
                      {ticket.resolvedAt ?? 'Not resolved'}
                    </p>
                  </div>

                </div>

                {/* Error message */}
                {ticket.errorMessage && (
                  <div className="mt-5 rounded-lg bg-muted p-4">
                    <p className="text-xs font-semibold">
                      Error Message
                    </p>

                    <p className="mt-2 text-sm text-muted-foreground">
                      {ticket.errorMessage}
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