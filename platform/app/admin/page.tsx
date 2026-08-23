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

export default function AdminPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);

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

    loadAgents();
  }, []);

  return (
    <div className="min-h-screen bg-background p-8">
      <div className="mx-auto max-w-5xl">

        <div className="mb-8 flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold">
              Admin Dashboard
            </h1>

            <p className="mt-2 text-muted-foreground">
              Manage agents, tools, and RAG documents.
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

          <div className="rounded-xl border p-6 md:col-span-3">

            <h2 className="text-lg font-semibold mb-4">
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

                  <div className="flex justify-between items-start">

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
                    <span className="font-semibold ml-1">
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


        </div>

      </div>
    </div>
  );
}