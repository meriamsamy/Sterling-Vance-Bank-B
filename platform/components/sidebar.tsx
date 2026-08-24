'use client';

import * as React from 'react';
import {
  ShieldAlert,
  Workflow,
  BrainCircuit,
  Check,
  ChevronRight,
  Plus,
  CircleDot,
  Building2,
  Settings,
  LifeBuoy,
} from 'lucide-react';

import { cn } from '@/lib/utils';
import { AGENT_LIST, type AgentId, type AgentDefinition } from '@/lib/agents';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { useTheme } from '@/components/theme-provider';
import { Sun, Moon } from 'lucide-react';

const ICONS = {
  ShieldAlert,
  Workflow,
  BrainCircuit,
} as const;

interface SidebarProps {
  activeAgentId: AgentId;
  onAgentChange: (id: AgentId) => void;
  threadId: string | null;
  threadCreatedAt: number | null;
  messageCount: number;
  onNewThread: () => void;
}

function formatThreadTime(ts: number | null): string {
  if (!ts) return 'No active thread';
  const date = new Date(ts);
  return date.toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatThreadId(id: string | null): string {
  if (!id) return '—';
  return id.length > 18 ? `${id.slice(0, 8)}…${id.slice(-6)}` : id;
}

export function Sidebar({
  activeAgentId,
  onAgentChange,
  threadId,
  threadCreatedAt,
  messageCount,
  onNewThread,
}: SidebarProps) {
  const { theme, toggleTheme } = useTheme();
  const activeAgent = AGENT_LIST.find((a) => a.id === activeAgentId)!;

  return (
    <aside className="bg-sidebar text-sidebar-foreground flex h-full w-72 flex-col border-r border-sidebar-border">
      {/* Brand */}
      <div className="flex h-16 items-center gap-2.5 px-5">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/15 ring-1 ring-primary/30">
          <Building2 className="h-5 w-5 text-primary" />
        </div>
        <div className="flex flex-col leading-tight">
          <span className="text-sm font-semibold tracking-tight">
            Sentinel
          </span>
          <span className="text-[11px] text-muted-foreground">
            Banking AI Platform
          </span>
        </div>
      </div>

      <Separator className="bg-sidebar-border" />

      {/* New thread */}
      <div className="px-3 pt-4">
        <Button
          onClick={onNewThread}
          variant="secondary"
          className="w-full justify-start gap-2 bg-white/5 text-sidebar-foreground hover:bg-white/10"
        >
          <Plus className="h-4 w-4" />
          New conversation
        </Button>
      </div>

      {/* Agents */}
      <div className="px-3 pt-5">
        <p className="px-2 pb-2 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Agents
        </p>
        <nav className="flex flex-col gap-1">
          {AGENT_LIST.map((agent) => (
            <AgentButton
              key={agent.id}
              agent={agent}
              active={agent.id === activeAgentId}
              onClick={() => onAgentChange(agent.id)}
            />
          ))}
        </nav>
      </div>

      {/* Active thread info */}
      <div className="mt-auto px-3 pb-3">
        <Separator className="mb-3 bg-sidebar-border" />
        <div className="rounded-lg border border-sidebar-border bg-white/5 p-3">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              Active thread
            </span>
            <CircleDot
              className={cn(
                'h-3 w-3',
                threadId ? 'text-success' : 'text-muted-foreground'
              )}
            />
          </div>
          <dl className="space-y-1.5 text-xs">
            <div className="flex items-center justify-between gap-2">
              <dt className="text-muted-foreground">Agent</dt>
              <dd className="truncate font-medium text-sidebar-foreground">
                {activeAgent.shortName}
              </dd>
            </div>
            <div className="flex items-center justify-between gap-2">
              <dt className="text-muted-foreground">Thread ID</dt>
              <dd className="truncate font-mono text-[11px] text-sidebar-foreground">
                {formatThreadId(threadId)}
              </dd>
            </div>
            <div className="flex items-center justify-between gap-2">
              <dt className="text-muted-foreground">Started</dt>
              <dd className="font-medium text-sidebar-foreground">
                {formatThreadTime(threadCreatedAt)}
              </dd>
            </div>
            <div className="flex items-center justify-between gap-2">
              <dt className="text-muted-foreground">Messages</dt>
              <dd className="font-medium text-sidebar-foreground">
                {messageCount}
              </dd>
            </div>
          </dl>
        </div>
      </div>

      {/* Footer controls */}
      <div className="flex items-center justify-between border-t border-sidebar-border px-4 py-3">
        <div className="flex items-center gap-1">
          <TooltipProvider delayDuration={200}>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={toggleTheme}
                  className="h-8 w-8 text-muted-foreground hover:text-sidebar-foreground"
                >
                  {theme === 'dark' ? (
                    <Sun className="h-4 w-4" />
                  ) : (
                    <Moon className="h-4 w-4" />
                  )}
                </Button>
              </TooltipTrigger>
              <TooltipContent side="top">
                {theme === 'dark' ? 'Light mode' : 'Dark mode'}
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
          <TooltipProvider delayDuration={200}>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8 text-muted-foreground hover:text-sidebar-foreground"
                >
                  <Settings className="h-4 w-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent side="top">Settings</TooltipContent>
            </Tooltip>
          </TooltipProvider>
          <TooltipProvider delayDuration={200}>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8 text-muted-foreground hover:text-sidebar-foreground"
                >
                  <LifeBuoy className="h-4 w-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent side="top">Support</TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </div>
        <span className="text-[11px] text-muted-foreground">v1.0.0</span>
      </div>
    </aside>
  );
}

function AgentButton({
  agent,
  active,
  onClick,
}: {
  agent: AgentDefinition;
  active: boolean;
  onClick: () => void;
}) {
  const Icon = ICONS[agent.icon];
  return (
    <button
      onClick={onClick}
      className={cn(
        'group relative flex w-full items-start gap-3 rounded-lg px-3 py-2.5 text-left transition-colors',
        active
          ? 'bg-white/10 ring-1 ring-white/15'
          : 'hover:bg-white/5'
      )}
    >
      <div
        className={cn(
          'mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md transition-colors',
          active
            ? 'bg-primary/20 text-primary'
            : 'bg-white/5 text-muted-foreground group-hover:text-sidebar-foreground'
        )}
      >
        <Icon className="h-4 w-4" />
      </div>
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center gap-2">
          <span
            className={cn(
              'truncate text-sm font-medium',
              active ? 'text-sidebar-foreground' : 'text-sidebar-foreground/90'
            )}
          >
            {agent.shortName}
          </span>
          {active && (
            <Badge
              variant="secondary"
              className="ml-auto shrink-0 border-0 bg-success/15 text-[10px] text-success"
            >
              <Check className="mr-1 h-2.5 w-2.5" />
              Active
            </Badge>
          )}
        </div>
        <span className="mt-0.5 line-clamp-2 text-[11px] leading-snug text-muted-foreground">
          {agent.description}
        </span>
      </div>
      {active && (
        <ChevronRight className="absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-primary" />
      )}
    </button>
  );
}
