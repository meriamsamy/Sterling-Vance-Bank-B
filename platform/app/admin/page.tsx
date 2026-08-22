'use client';

import Link from 'next/link';

export default function AdminPage() {
  return (
    <div className="min-h-screen bg-background p-8">
      <div className="mx-auto max-w-5xl">
        <div className="mb-8 flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold">Admin Dashboard</h1>
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
          <div className="rounded-xl border p-6">
            <h2 className="text-lg font-semibold">Agents</h2>
            <p className="mt-2 text-sm text-muted-foreground">
              View and manage connected agents.
            </p>
          </div>

          <div className="rounded-xl border p-6">
            <h2 className="text-lg font-semibold">Tools</h2>
            <p className="mt-2 text-sm text-muted-foreground">
              Add or remove tools available to agents.
            </p>
          </div>

          <div className="rounded-xl border p-6">
            <h2 className="text-lg font-semibold">RAG Documents</h2>
            <p className="mt-2 text-sm text-muted-foreground">
              Add or remove knowledge documents.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}