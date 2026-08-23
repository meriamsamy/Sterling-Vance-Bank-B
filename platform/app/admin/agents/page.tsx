'use client';

import * as React from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Bot, Search, ArrowRight, Wrench } from 'lucide-react';

import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { StatusBadge } from '@/components/admin/status-badge';
import {
  PageHeader,
  EmptyStateView,
  ErrorStateView,
  LoadingStateView,
} from '@/components/admin/admin-ui';
import { getAgents } from '@/lib/admin-api';
import type { AdminAgent, AgentStatus } from '@/lib/admin-types';

const STATUS_FILTERS: { value: string; label: string }[] = [
  { value: 'all', label: 'All statuses' },
  { value: 'operational', label: 'Operational' },
  { value: 'idle', label: 'Idle' },
  { value: 'offline', label: 'Offline' },
  { value: 'error', label: 'Error' },
];

export default function AdminAgentsPage() {
  const router = useRouter();
  const [agents, setAgents] = React.useState<AdminAgent[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [query, setQuery] = React.useState('');
  const [statusFilter, setStatusFilter] = React.useState('all');

  const load = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getAgents();
      setAgents(data);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : 'Failed to load agents.'
      );
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    load();
  }, [load]);

  const filtered = React.useMemo(() => {
    const q = query.trim().toLowerCase();
    return agents.filter((agent) => {
      const matchesQuery =
        !q ||
        agent.name.toLowerCase().includes(q) ||
        agent.description.toLowerCase().includes(q);
      const matchesStatus =
        statusFilter === 'all' || agent.status === statusFilter;
      return matchesQuery && matchesStatus;
    });
  }, [agents, query, statusFilter]);

  return (
    <div>
      <PageHeader
        title="Agents"
        description="View and manage AI agents registered on the platform."
      />

      <div className="border-b border-border bg-background/80 px-6 py-3 backdrop-blur">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search agents by name or description…"
              className="pl-9"
            />
          </div>
          <Select
            value={statusFilter}
            onValueChange={setStatusFilter}
          >
            <SelectTrigger className="w-full sm:w-44">
              <SelectValue placeholder="Status" />
            </SelectTrigger>
            <SelectContent>
              {STATUS_FILTERS.map((f) => (
                <SelectItem key={f.value} value={f.value}>
                  {f.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      <div className="p-6">
        {error && <ErrorStateView message={error} onRetry={load} />}

        {!error && loading && <LoadingStateView rows={4} />}

        {!error && !loading && filtered.length === 0 && (
          <EmptyStateView
            icon={Bot}
            title="No agents found"
            description={
              agents.length === 0
                ? 'No agents are registered on the platform yet. Connect the admin backend to surface agents.'
                : 'No agents match your current search or filter.'
            }
            action={
              agents.length > 0 ? (
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => {
                    setQuery('');
                    setStatusFilter('all');
                  }}
                >
                  Clear filters
                </Button>
              ) : (
                <Button variant="secondary" size="sm" onClick={load}>
                  Refresh
                </Button>
              )
            }
          />
        )}

        {!error && !loading && filtered.length > 0 && (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {filtered.map((agent) => (
              <Link
                key={agent.id}
                href={`/admin/agents/${encodeURIComponent(agent.id)}`}
              >
                <Card className="group h-full cursor-pointer p-5 transition-all hover:border-primary/40 hover:bg-accent">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-start gap-3">
                      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-primary/30 bg-primary/10">
                        <Bot className="h-5 w-5 text-primary" />
                      </div>
                      <div className="min-w-0">
                        <h3 className="truncate text-sm font-semibold">
                          {agent.name}
                        </h3>
                        <p className="mt-1 line-clamp-2 text-xs leading-snug text-muted-foreground">
                          {agent.description}
                        </p>
                      </div>
                    </div>
                    <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-primary" />
                  </div>

                  <div className="mt-4 flex items-center justify-between">
                    <StatusBadge status={agent.status} />
                    <span className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                      <Wrench className="h-3.5 w-3.5" />
                      {agent.assignedToolCount} tools
                    </span>
                  </div>

                  {agent.capabilities.length > 0 && (
                    <div className="mt-3 flex flex-wrap gap-1.5">
                      {agent.capabilities.slice(0, 3).map((cap) => (
                        <span
                          key={cap}
                          className="rounded-full border border-border bg-muted/50 px-2.5 py-0.5 text-[10px] font-medium text-muted-foreground"
                        >
                          {cap}
                        </span>
                      ))}
                    </div>
                  )}
                </Card>
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
