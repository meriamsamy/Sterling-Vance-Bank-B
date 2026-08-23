'use client';

import * as React from 'react';
import Link from 'next/link';
import { Wrench, Search, ArrowRight, Bot } from 'lucide-react';

import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
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
import { getTools } from '@/lib/admin-api';
import type { AdminTool } from '@/lib/admin-types';

export default function AdminToolsPage() {
  const [tools, setTools] = React.useState<AdminTool[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [query, setQuery] = React.useState('');
  const [categoryFilter, setCategoryFilter] = React.useState('all');

  const load = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getTools();
      setTools(data);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : 'Failed to load tools.'
      );
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    load();
  }, [load]);

  const categories = React.useMemo(() => {
    const set = new Set(tools.map((t) => t.category));
    return Array.from(set).sort();
  }, [tools]);

  const filtered = React.useMemo(() => {
    const q = query.trim().toLowerCase();
    return tools.filter((tool) => {
      const matchesQuery =
        !q ||
        tool.name.toLowerCase().includes(q) ||
        tool.description.toLowerCase().includes(q);
      const matchesCategory =
        categoryFilter === 'all' || tool.category === categoryFilter;
      return matchesQuery && matchesCategory;
    });
  }, [tools, query, categoryFilter]);

  return (
    <div>
      <PageHeader
        title="MCP Tools"
        description="Tools exposed by the MCP server and their agent assignments."
      />

      <div className="border-b border-border bg-background/80 px-6 py-3 backdrop-blur">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search tools by name or description…"
              className="pl-9"
            />
          </div>
          <Select value={categoryFilter} onValueChange={setCategoryFilter}>
            <SelectTrigger className="w-full sm:w-48">
              <SelectValue placeholder="Category" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All categories</SelectItem>
              {categories.map((c) => (
                <SelectItem key={c} value={c}>
                  {c}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      <div className="p-6">
        {error && <ErrorStateView message={error} onRetry={load} />}

        {!error && loading && <LoadingStateView rows={5} />}

        {!error && !loading && filtered.length === 0 && (
          <EmptyStateView
            icon={Wrench}
            title="No tools found"
            description={
              tools.length === 0
                ? 'No MCP tools are registered yet. Connect the admin backend to surface tools.'
                : 'No tools match your current search or filter.'
            }
            action={
              tools.length > 0 ? (
                <button
                  className="text-sm text-primary hover:underline"
                  onClick={() => {
                    setQuery('');
                    setCategoryFilter('all');
                  }}
                >
                  Clear filters
                </button>
              ) : null
            }
          />
        )}

        {!error && !loading && filtered.length > 0 && (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {filtered.map((tool) => (
              <Link
                key={tool.id}
                href={`/admin/tools/${encodeURIComponent(tool.id)}`}
              >
                <Card className="group h-full cursor-pointer p-5 transition-all hover:border-primary/40 hover:bg-accent">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-start gap-3">
                      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-primary/30 bg-primary/10">
                        <Wrench className="h-5 w-5 text-primary" />
                      </div>
                      <div className="min-w-0">
                        <h3 className="truncate text-sm font-semibold">
                          {tool.name}
                        </h3>
                        <p className="mt-1 line-clamp-2 text-xs leading-snug text-muted-foreground">
                          {tool.description}
                        </p>
                      </div>
                    </div>
                    <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-primary" />
                  </div>

                  <div className="mt-4 flex items-center justify-between">
                    <Badge
                      variant="outline"
                      className="border-0 bg-muted text-[10px] text-muted-foreground"
                    >
                      {tool.category}
                    </Badge>
                    <StatusBadge status={tool.status} />
                  </div>

                  <Separator />
                  <div className="mt-3 flex items-center gap-1.5 text-[11px] text-muted-foreground">
                    <Bot className="h-3.5 w-3.5" />
                    <span>
                      {tool.assignedAgentNames.length} agent
                      {tool.assignedAgentNames.length === 1 ? '' : 's'}
                    </span>
                  </div>
                </Card>
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
