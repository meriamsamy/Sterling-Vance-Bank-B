'use client';

import * as React from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { Wrench, ArrowLeft, Bot } from 'lucide-react';

import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { StatusBadge } from '@/components/admin/status-badge';
import {
  PageHeader,
  ErrorStateView,
  LoadingStateView,
  EmptyStateView,
} from '@/components/admin/admin-ui';
import { getTool } from '@/lib/admin-api';
import type { AdminTool } from '@/lib/admin-types';

export default function ToolDetailPage() {
  const params = useParams<{ toolId: string }>();
  const router = useRouter();
  const toolId = decodeURIComponent(params.toolId);

  const [tool, setTool] = React.useState<AdminTool | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getTool(toolId);
      setTool(data);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : 'Failed to load tool.'
      );
    } finally {
      setLoading(false);
    }
  }, [toolId]);

  React.useEffect(() => {
    load();
  }, [load]);

  return (
    <div>
      <PageHeader
        title={tool ? tool.name : 'Tool'}
        description={tool ? tool.description : undefined}
        action={
          <Button
            variant="ghost"
            size="sm"
            onClick={() => router.push('/admin/tools')}
            className="gap-1.5"
          >
            <ArrowLeft className="h-4 w-4" />
            Back to tools
          </Button>
        }
      />

      <div className="p-6">
        {loading && <LoadingStateView rows={3} />}

        {!loading && !tool && error && (
          <ErrorStateView message={error} onRetry={load} />
        )}

        {!loading && tool && (
          <>
            <Card className="mb-6 p-5">
              <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex items-center gap-3">
                  <div className="flex h-12 w-12 items-center justify-center rounded-xl border border-primary/30 bg-primary/10">
                    <Wrench className="h-6 w-6 text-primary" />
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <h2 className="text-base font-semibold">
                        {tool.name}
                      </h2>
                      <StatusBadge status={tool.status} />
                    </div>
                    <p className="mt-0.5 text-sm text-muted-foreground">
                      {tool.description}
                    </p>
                  </div>
                </div>
                <Badge
                  variant="outline"
                  className="border-0 bg-muted text-[11px] text-muted-foreground"
                >
                  {tool.category}
                </Badge>
              </div>
            </Card>

            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-sm font-semibold tracking-tight">
                Assigned Agents
              </h3>
              <span className="text-[11px] text-muted-foreground">
                {tool.assignedAgentNames.length} agent
                {tool.assignedAgentNames.length === 1 ? '' : 's'}
              </span>
            </div>

            {tool.assignedAgentNames.length === 0 ? (
              <EmptyStateView
                icon={Bot}
                title="No agents assigned"
                description="This tool is not currently assigned to any agent."
              />
            ) : (
              <div className="space-y-3">
                {tool.assignedAgentNames.map((name, idx) => (
                  <Link
                    key={tool.assignedAgentIds[idx] ?? name}
                    href={`/admin/agents/${encodeURIComponent(
                      tool.assignedAgentIds[idx] ?? ''
                    )}`}
                  >
                    <Card className="group flex cursor-pointer items-center gap-3 p-4 transition-all hover:border-primary/40 hover:bg-accent">
                      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-border bg-muted/40">
                        <Bot className="h-4 w-4 text-muted-foreground" />
                      </div>
                      <div className="flex-1">
                        <p className="text-sm font-medium">{name}</p>
                        <p className="text-[11px] text-muted-foreground">
                          {tool.assignedAgentIds[idx] ?? '—'}
                        </p>
                      </div>
                    </Card>
                  </Link>
                ))}
              </div>
            )}

            <Separator className="my-6" />

            <Card className="p-4">
              <p className="text-xs text-muted-foreground">
                Tool assignment is managed from the agent detail view. Open an
                agent to assign or remove this tool.
              </p>
            </Card>
          </>
        )}
      </div>
    </div>
  );
}
