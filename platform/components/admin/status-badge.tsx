'use client';

import * as React from 'react';
import { cn } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';
import type {
  AgentStatus,
  ToolStatus,
  DocumentStatus,
  ServerStatus,
} from '@/lib/admin-types';

type AnyStatus =
  | AgentStatus
  | ToolStatus
  | DocumentStatus
  | ServerStatus
  | string;

const STATUS_MAP: Record<
  string,
  { label: string; className: string }
> = {
  operational: {
    label: 'Operational',
    className: 'bg-success/15 text-success',
  },
  idle: {
    label: 'Idle',
    className: 'bg-muted text-muted-foreground',
  },
  offline: {
    label: 'Offline',
    className: 'bg-muted text-muted-foreground',
  },
  error: {
    label: 'Error',
    className: 'bg-destructive/15 text-destructive',
  },
  active: {
    label: 'Active',
    className: 'bg-success/15 text-success',
  },
  disabled: {
    label: 'Disabled',
    className: 'bg-muted text-muted-foreground',
  },
  degraded: {
    label: 'Degraded',
    className: 'bg-warning/15 text-warning',
  },
  queued: {
    label: 'Queued',
    className: 'bg-muted text-muted-foreground',
  },
  processing: {
    label: 'Processing',
    className: 'bg-warning/15 text-warning',
  },
  indexed: {
    label: 'Indexed',
    className: 'bg-success/15 text-success',
  },
  failed: {
    label: 'Failed',
    className: 'bg-destructive/15 text-destructive',
  },
};

interface StatusBadgeProps {
  status: AnyStatus;
  className?: string;
}

export function StatusBadge({ status, className }: StatusBadgeProps) {
  const config = STATUS_MAP[status] ?? {
    label: status.charAt(0).toUpperCase() + status.slice(1),
    className: 'bg-muted text-muted-foreground',
  };
  return (
    <Badge
      variant="outline"
      className={cn('border-0 text-[10px]', config.className, className)}
    >
      <span
        className={cn(
          'mr-1 h-1.5 w-1.5 rounded-full',
          status === 'operational' && 'bg-success',
          status === 'active' && 'bg-success',
          status === 'indexed' && 'bg-success',
          status === 'idle' && 'bg-muted-foreground',
          status === 'offline' && 'bg-muted-foreground',
          status === 'disabled' && 'bg-muted-foreground',
          status === 'queued' && 'bg-muted-foreground',
          status === 'error' && 'bg-destructive',
          status === 'failed' && 'bg-destructive',
          status === 'degraded' && 'bg-warning',
          status === 'processing' && 'bg-warning'
        )}
      />
      {config.label}
    </Badge>
  );
}
