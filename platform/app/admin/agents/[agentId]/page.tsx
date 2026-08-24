'use client';

import * as React from 'react';
import { useParams, useRouter } from 'next/navigation';
import {
  Bot,
  Wrench,
  ArrowLeft,
  Plus,
  Trash2,
  Search,
  Loader2,
} from 'lucide-react';

import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet';
import { StatusBadge } from '@/components/admin/status-badge';
import {
  PageHeader,
  ErrorStateView,
  LoadingStateView,
  EmptyStateView,
} from '@/components/admin/admin-ui';
import {
  getAgent,
  getAgentTools,
  getAvailableTools,
  assignToolToAgent,
  removeToolFromAgent,
  AdminApiError,
} from '@/lib/admin-api';
import type {
  AdminAgent,
  AgentToolAssignment,
  AvailableTool,
} from '@/lib/admin-types';

export default function AgentDetailPage() {
  const params = useParams<{ agentId: string }>();
  const router = useRouter();
  const agentId = decodeURIComponent(params.agentId);

  const [agent, setAgent] = React.useState<AdminAgent | null>(null);
  const [tools, setTools] = React.useState<AgentToolAssignment[]>([]);
  const [available, setAvailable] = React.useState<AvailableTool[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  const [assignOpen, setAssignOpen] = React.useState(false);
  const [assignQuery, setAssignQuery] = React.useState('');
  const [assigning, setAssigning] = React.useState(false);

  const [removeTarget, setRemoveTarget] =
    React.useState<AgentToolAssignment | null>(null);
  const [removing, setRemoving] = React.useState(false);

  const load = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [a, t] = await Promise.all([
        getAgent(agentId),
        getAgentTools(agentId),
      ]);
      setAgent(a);
      setTools(t);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : 'Failed to load agent.'
      );
    } finally {
      setLoading(false);
    }
  }, [agentId]);

  React.useEffect(() => {
    load();
  }, [load]);

  const refreshAvailable = React.useCallback(async () => {
    try {
      const list = await getAvailableTools(agentId);
      setAvailable(list);
    } catch {
      setAvailable([]);
    }
  }, [agentId]);

  const handleOpenAssign = async () => {
    setAssignOpen(true);
    setAssignQuery('');
    await refreshAvailable();
  };

  const handleAssign = async (toolId: string) => {
    setAssigning(true);
    try {
      await assignToolToAgent(agentId, toolId);
      const [t, a] = await Promise.all([
        getAgentTools(agentId),
        getAvailableTools(agentId),
      ]);
      setTools(t);
      setAvailable(a);
    } catch (err) {
      const msg =
        err instanceof AdminApiError
          ? err.message
          : 'Failed to assign tool.';
      setError(msg);
    } finally {
      setAssigning(false);
    }
  };

  const handleConfirmRemove = async () => {
    if (!removeTarget) return;
    setRemoving(true);
    try {
      await removeToolFromAgent(agentId, removeTarget.toolId);
      setTools((prev) =>
        prev.filter((t) => t.toolId !== removeTarget.toolId)
      );
      setRemoveTarget(null);
    } catch (err) {
      const msg =
        err instanceof AdminApiError
          ? err.message
          : 'Failed to remove tool.';
      setError(msg);
    } finally {
      setRemoving(false);
    }
  };

  const filteredAvailable = React.useMemo(() => {
    const q = assignQuery.trim().toLowerCase();
    if (!q) return available;
    return available.filter(
      (t) =>
        t.toolName.toLowerCase().includes(q) ||
        t.toolDescription.toLowerCase().includes(q) ||
        t.category.toLowerCase().includes(q)
    );
  }, [available, assignQuery]);

  return (
    <div>
      <PageHeader
        title={agent ? agent.name : 'Agent'}
        description={agent ? agent.description : undefined}
        action={
          <Button
            variant="ghost"
            size="sm"
            onClick={() => router.push('/admin/agents')}
            className="gap-1.5"
          >
            <ArrowLeft className="h-4 w-4" />
            Back to agents
          </Button>
        }
      />

      <div className="p-6">
        {error && (
          <div className="mb-4 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
            {error}
          </div>
        )}

        {loading && <LoadingStateView rows={4} />}

        {!loading && !agent && error && (
          <ErrorStateView message={error} onRetry={load} />
        )}

        {!loading && agent && (
          <>
            <Card className="mb-6 p-5">
              <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex items-center gap-3">
                  <div className="flex h-12 w-12 items-center justify-center rounded-xl border border-primary/30 bg-primary/10">
                    <Bot className="h-6 w-6 text-primary" />
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <h2 className="text-base font-semibold">
                        {agent.name}
                      </h2>
                      <StatusBadge status={agent.status} />
                    </div>
                    <p className="mt-0.5 text-sm text-muted-foreground">
                      {agent.description}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <Badge variant="secondary" className="gap-1">
                    <Wrench className="h-3 w-3" />
                    {tools.length} assigned
                  </Badge>
                  <Button
                    size="sm"
                    onClick={handleOpenAssign}
                    className="gap-1.5"
                  >
                    <Plus className="h-4 w-4" />
                    Add tool
                  </Button>
                </div>
              </div>

              {agent.capabilities.length > 0 && (
                <>
                  <Separator className="my-4" />
                  <div className="flex flex-wrap gap-1.5">
                    {agent.capabilities.map((cap) => (
                      <span
                        key={cap}
                        className="rounded-full border border-border bg-muted/50 px-2.5 py-0.5 text-[11px] font-medium text-muted-foreground"
                      >
                        {cap}
                      </span>
                    ))}
                  </div>
                </>
              )}
            </Card>

            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-sm font-semibold tracking-tight">
                Assigned MCP Tools
              </h3>
            </div>

            {tools.length === 0 ? (
              <EmptyStateView
                icon={Wrench}
                title="No tools assigned"
                description="This agent has no MCP tools assigned yet. Use the button above to assign a tool."
                action={
                  <Button size="sm" onClick={handleOpenAssign} className="gap-1.5">
                    <Plus className="h-4 w-4" />
                    Add tool
                  </Button>
                }
              />
            ) : (
              <div className="space-y-3">
                {tools.map((tool) => (
                  <Card key={tool.toolId} className="p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex items-start gap-3">
                        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-border bg-muted/40">
                          <Wrench className="h-4 w-4 text-muted-foreground" />
                        </div>
                        <div className="min-w-0">
                          <div className="flex items-center gap-2">
                            <h4 className="text-sm font-medium">
                              {tool.toolName}
                            </h4>
                            <StatusBadge status={tool.status} />
                          </div>
                          <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">
                            {tool.toolDescription}
                          </p>
                          <Badge
                            variant="outline"
                            className="mt-2 border-0 bg-muted text-[10px] text-muted-foreground"
                          >
                            {tool.category}
                          </Badge>
                        </div>
                      </div>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setRemoveTarget(tool)}
                        className="shrink-0 gap-1.5 text-destructive hover:bg-destructive/10 hover:text-destructive"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                        Remove
                      </Button>
                    </div>
                  </Card>
                ))}
              </div>
            )}
          </>
        )}
      </div>

      {/* Assign tool sheet */}
      <Sheet open={assignOpen} onOpenChange={setAssignOpen}>
        <SheetTrigger className="hidden" />
        <SheetContent className="w-full sm:max-w-md">
          <SheetHeader>
            <SheetTitle>Assign MCP Tool</SheetTitle>
          </SheetHeader>
          <div className="mt-4 space-y-4">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={assignQuery}
                onChange={(e) => setAssignQuery(e.target.value)}
                placeholder="Search available tools…"
                className="pl-9"
              />
            </div>

            <div className="space-y-2 overflow-y-auto">
              {filteredAvailable.length === 0 ? (
                <p className="py-8 text-center text-sm text-muted-foreground">
                  No available tools to assign.
                </p>
              ) : (
                filteredAvailable.map((tool) => (
                  <div
                    key={tool.toolId}
                    className="flex items-start justify-between gap-3 rounded-lg border border-border p-3"
                  >
                    <div className="min-w-0">
                      <p className="text-sm font-medium">{tool.toolName}</p>
                      <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">
                        {tool.toolDescription}
                      </p>
                      <Badge
                        variant="outline"
                        className="mt-1.5 border-0 bg-muted text-[10px] text-muted-foreground"
                      >
                        {tool.category}
                      </Badge>
                    </div>
                    <Button
                      size="sm"
                      variant="secondary"
                      disabled={assigning || tool.alreadyAssigned}
                      onClick={() => handleAssign(tool.toolId)}
                      className="shrink-0 gap-1.5"
                    >
                      {assigning ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Plus className="h-3.5 w-3.5" />
                      )}
                      {tool.alreadyAssigned ? 'Assigned' : 'Assign'}
                    </Button>
                  </div>
                ))
              )}
            </div>
          </div>
        </SheetContent>
      </Sheet>

      {/* Remove confirmation dialog */}
      <Dialog
        open={!!removeTarget}
        onOpenChange={(open) => !open && setRemoveTarget(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Remove tool from agent?</DialogTitle>
            <DialogDescription>
              {removeTarget && (
                <>
                  Remove <strong>{removeTarget.toolName}</strong> from{' '}
                  <strong>{agent?.name}</strong>? The agent will no longer be
                  able to use this tool.
                </>
              )}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="ghost"
              onClick={() => setRemoveTarget(null)}
              disabled={removing}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={handleConfirmRemove}
              disabled={removing}
              className="gap-1.5"
            >
              {removing && <Loader2 className="h-4 w-4 animate-spin" />}
              Remove tool
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
