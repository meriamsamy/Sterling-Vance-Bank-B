'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';

type Agent = {
  id: string;
  name: string;
  description: string;
  status: string;
  assignedToolCount: number;
};

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

export default function AdminPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [tickets, setTickets] = useState<WorkflowTicket[]>([]);
  const [loading, setLoading] = useState(true);
  const [ticketsLoading, setTicketsLoading] = useState(true);

  useEffect(() => {
    async function loadAgents() {
      try {
        const res = await fetch('/api/admin/agents');

        if (!res.ok) {
          throw new Error('Failed to load agents');
        }

        const data = await res.json();
        setAgents(data);
      } catch (error) {
        console.error(error);
      } finally {
        setLoading(false);
      }
    }

    async function loadTickets() {
      try {
        const res = await fetch('/api/admin/tickets')

        if (!res.ok) {
          throw new Error('Failed to load tickets');
        }

        const data = await res.json();
        setTickets(data);
      } catch (error) {
        console.error(error);
      } finally {
        setTicketsLoading(false);
      }
    }

    loadAgents();
    loadTickets();
  }, []);

  const openTickets = tickets.filter(
    (ticket) => ticket.status !== 'resolved'
  ).length;

  return (
    <div className="min-h-screen bg-background p-8">
      <div className="mx-auto max-w-5xl">

        <div className="mb-8 flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold">
              Admin Dashboard
            </h1>

            <p className="mt-2 text-muted-foreground">
              Manage agents, tools, RAG documents, and workflow tickets.
            </p>
          </div>

          <Link
            href="/"
            className="rounded-md border px-4 py-2 text-sm hover:bg-muted"
          >
            User Chat
          </Link>
        </div>

        <div className="grid gap-6 md:grid-cols-3">

          {/* Agents */}

          <div className="rounded-xl border p-6 md:col-span-3">
            <h2 className="mb-4 text-lg font-semibold">
              Agents
            </h2>

            {loading && (
              <p className="text-muted-foreground">
                Loading agents...
              </p>
            )}

            {!loading && agents.length === 0 && (
              <p className="text-muted-foreground">
                No agents found.
              </p>
            )}

            <div className="grid gap-4 md:grid-cols-2">
              {agents.map((agent) => (
                <div
                  key={agent.id}
                  className="rounded-lg border p-4"
                >
                  <div className="flex items-start justify-between">
                    <h3 className="font-semibold">
                      {agent.name}
                    </h3>

                    <span className="text-xs text-green-600">
                      {agent.status}
                    </span>
                  </div>

                  <p className="mt-2 text-sm text-muted-foreground">
                    {agent.description}
                  </p>

                  <p className="mt-3 text-sm">
                    Tools:
                    <span className="ml-1 font-semibold">
                      {agent.assignedToolCount}
                    </span>
                  </p>

                  <Link
                    href={`/admin/agents/${agent.id}`}
                    className="mt-4 inline-block rounded-md border px-3 py-1 text-sm hover:bg-muted"
                  >
                    Manage Tools
                  </Link>
                </div>
              ))}
            </div>
          </div>

          {/* Tools */}

          <div className="rounded-xl border p-6">
            <h2 className="text-lg font-semibold">
              Tools
            </h2>

            <p className="mt-2 text-sm text-muted-foreground">
              Manage MCP tools assigned to agents.
            </p>

            <Link
              href="/admin/tools"
              className="mt-4 inline-block text-sm underline"
            >
              Open Tools
            </Link>
          </div>

          {/* RAG */}

          <div className="rounded-xl border p-6">
            <h2 className="text-lg font-semibold">
              RAG Documents
            </h2>

            <p className="mt-2 text-sm text-muted-foreground">
              Manage knowledge documents.
            </p>

            <Link
              href="/admin/rag"
              className="mt-4 inline-block text-sm underline"
            >
              Open RAG
            </Link>
          </div>

          {/* Workflow Tickets */}

          <div className="rounded-xl border p-6">
            <div className="flex items-start justify-between">
              <h2 className="text-lg font-semibold">
                Workflow Tickets
              </h2>

              {!ticketsLoading && openTickets > 0 && (
                <span className="rounded-full bg-red-100 px-2 py-1 text-xs font-semibold text-red-700">
                  {openTickets} open
                </span>
              )}
            </div>

            <p className="mt-2 text-sm text-muted-foreground">
              Monitor workflow failures and recovery tickets.
            </p>

            {!ticketsLoading && (
              <p className="mt-3 text-sm">
                Total tickets:
                <span className="ml-1 font-semibold">
                  {tickets.length}
                </span>
              </p>
            )}

            <Link
              href="/admin/tickets"
              className="mt-4 inline-block text-sm underline"
            >
              Open Tickets
            </Link>
          </div>

        </div>
      </div>
    </div>
  );
}