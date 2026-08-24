'use client';

import * as React from 'react';
import { ShieldAlert, Workflow, BrainCircuit, ArrowRight } from 'lucide-react';
import { type AgentDefinition } from '@/lib/agents';
import { cn } from '@/lib/utils';

const ICONS = { ShieldAlert, Workflow, BrainCircuit } as const;

interface EmptyStateProps {
  agent: AgentDefinition;
  onSuggestionClick: (text: string) => void;
}

const SUGGESTIONS: Record<string, string[]> = {
  'customer-risk-monitoring': [
    'Show me customers with elevated risk scores in the last 24 hours.',
    'Explain the top 3 risk signals flagged for account #4471-A.',
    'Which portfolios crossed the high-risk threshold this week?',
  ],
  'planning-decomposition': [
    'Decompose the loan onboarding workflow into sub-tasks.',
    'Plan the steps for a KYC re-verification campaign.',
    'Break down the quarterly compliance audit process.',
  ],
  'memory-rag': [
    'What is our internal policy on high-value wire transfers?',
    'Summarize the latest AML regulatory guidance.',
    'Find procedures for handling dormant accounts.',
  ],
};

export function EmptyState({ agent, onSuggestionClick }: EmptyStateProps) {
  const Icon = ICONS[agent.icon];
  const suggestions = SUGGESTIONS[agent.id] ?? [];

  return (
    <div className="flex h-full flex-col items-center justify-center px-6 py-10">
      <div className="flex h-14 w-14 items-center justify-center rounded-2xl border border-primary/30 bg-primary/10">
        <Icon className="h-7 w-7 text-primary" />
      </div>
      <h2 className="mt-5 text-lg font-semibold tracking-tight">
        {agent.name}
      </h2>
      <p className="mt-1.5 max-w-md text-center text-sm text-muted-foreground">
        {agent.description} Start a conversation or try one of the prompts
        below.
      </p>

      <div className="mt-8 grid w-full max-w-2xl gap-2.5 sm:grid-cols-2">
        {suggestions.map((text) => (
          <button
            key={text}
            onClick={() => onSuggestionClick(text)}
            className={cn(
              'group flex items-start gap-3 rounded-xl border border-border bg-card p-3.5 text-left transition-all hover:border-primary/40 hover:bg-accent'
            )}
          >
            <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
              <ArrowRight className="h-3.5 w-3.5" />
            </span>
            <span className="text-sm leading-snug text-foreground/90">
              {text}
            </span>
          </button>
        ))}
      </div>

      <div className="mt-8 flex flex-wrap items-center justify-center gap-2">
        {agent.capabilities.map((cap) => (
          <span
            key={cap}
            className="rounded-full border border-border bg-muted/50 px-3 py-1 text-[11px] font-medium text-muted-foreground"
          >
            {cap}
          </span>
        ))}
      </div>
    </div>
  );
}
