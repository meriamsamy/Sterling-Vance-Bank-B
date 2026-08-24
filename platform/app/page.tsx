'use client';

import Link from 'next/link';

export default function Home() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-background">
      <div className="w-full max-w-md space-y-6 p-6">
        <div className="text-center">
          <h1 className="text-3xl font-bold">
            Sterling & Vance Bank
          </h1>

          <p className="mt-2 text-muted-foreground">
            Choose how you want to access the platform
          </p>
        </div>

        <div className="grid gap-4">
          <Link
            href="/user"
            className="rounded-xl border p-6 transition hover:bg-muted"
          >
            <h2 className="text-xl font-semibold">User</h2>
            <p className="mt-2 text-sm text-muted-foreground">
              Chat with the available AI agents.
            </p>
          </Link>

          <Link
            href="/admin"
            className="rounded-xl border p-6 transition hover:bg-muted"
          >
            <h2 className="text-xl font-semibold">Admin</h2>
            <p className="mt-2 text-sm text-muted-foreground">
              Manage agents, tools, and RAG documents.
            </p>
          </Link>
        </div>
      </div>
    </main>
  );
}