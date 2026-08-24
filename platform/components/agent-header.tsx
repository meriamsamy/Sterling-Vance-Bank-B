'use client';

import * as React from 'react';
import { cn } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';
import { ShieldAlert, Workflow, BrainCircuit, Sparkles } from 'lucide-react';
import { type AgentDefinition } from '@/lib/agents';

const ICONS = { ShieldAlert, Workflow, BrainCircuit } as const;

interface AgentHeaderProps {
  agent: AgentDefinition;
  threadId: string | null;
  online: boolean;
}

export function AgentHeader({ agent, threadId, online }: AgentHeaderProps) {
  const Icon = ICONS[agent.icon];

  return (
    <header className="flex h-16 shrink-0 items-center justify-between border-b border-border bg-background/80 px-6 backdrop-blur">
      <div className="flex items-center gap-3">
        <div
          className={cn(
            'flex h-9 w-9 items-center justify-center rounded-lg border',
            'border-primary/30 bg-primary/10'
          )}
        >
          <Icon className="h-4.5 w-4.5 text-primary" />
        </div>
        <div className="flex flex-col">
          <div className="flex items-center gap-2">
            <h1 className="text-sm font-semibold tracking-tight">
              {agent.name}
            </h1>
            <Badge
              variant="outline"
              className={cn(
                'border-0 text-[10px]',
                online
                  ? 'bg-success/15 text-success'
                  : 'bg-muted text-muted-foreground'
              )}
            >
              <span
                className={cn(
                  'mr-1 h-1.5 w-1.5 rounded-full',
                  online ? 'bg-success' : 'bg-muted-foreground'
                )}
              />
              {online ? 'Operational' : 'Offline'}
            </Badge>
          </div>
          <p className="text-[11px] text-muted-foreground">
            {agent.description}
          </p>
        </div>
      </div>

      <div className="hidden items-center gap-2 md:flex">
        <div className="flex items-center gap-1.5 rounded-md border border-border bg-muted/40 px-2.5 py-1.5">
          <Sparkles className="h-3.5 w-3.5 text-primary" />
          <span className="text-[11px] font-medium text-muted-foreground">
            LangGraph
          </span>
        </div>
        <div className="flex items-center gap-1.5 rounded-md border border-border bg-muted/40 px-2.5 py-1.5">
          <span className="text-[11px] text-muted-foreground">Thread</span>
          <span className="font-mono text-[11px] text-foreground">
            {threadId ? threadId.slice(0, 8) : '—'}
          </span>
        </div>
      </div>
    </header>
  );
}
