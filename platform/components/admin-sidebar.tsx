'use client';

import * as React from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  LayoutDashboard,
  Bot,
  Wrench,
  FileText,
  Building2,
  ArrowLeftRight,
  Sun,
  Moon,
} from 'lucide-react';

import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import { Badge } from '@/components/ui/badge';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { useTheme } from '@/components/theme-provider';

const NAV_ITEMS = [
  { href: '/admin', label: 'Dashboard', icon: LayoutDashboard },
  { href: '/admin/agents', label: 'Agents', icon: Bot },
  { href: '/admin/tools', label: 'MCP Tools', icon: Wrench },
  { href: '/admin/documents', label: 'RAG Documents', icon: FileText },
] as const;

export function AdminSidebar() {
  const pathname = usePathname();
  const { theme, toggleTheme } = useTheme();

  return (
    <aside className="bg-sidebar text-sidebar-foreground flex h-full w-72 flex-col border-r border-sidebar-border">
      <div className="flex h-16 items-center gap-2.5 px-5">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/15 ring-1 ring-primary/30">
          <Building2 className="h-5 w-5 text-primary" />
        </div>
        <div className="flex flex-col leading-tight">
          <span className="text-sm font-semibold tracking-tight">
            Sentinel
          </span>
          <span className="text-[11px] text-muted-foreground">
            Admin Console
          </span>
        </div>
      </div>

      <Separator className="bg-sidebar-border" />

      <nav className="flex flex-col gap-1 px-3 pt-4">
        <p className="px-2 pb-2 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Platform
        </p>
        {NAV_ITEMS.map((item) => {
          const active =
            item.href === '/admin'
              ? pathname === '/admin'
              : pathname.startsWith(item.href);
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                'group relative flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left transition-colors',
                active
                  ? 'bg-white/10 ring-1 ring-white/15'
                  : 'hover:bg-white/5'
              )}
            >
              <div
                className={cn(
                  'flex h-8 w-8 shrink-0 items-center justify-center rounded-md transition-colors',
                  active
                    ? 'bg-primary/20 text-primary'
                    : 'bg-white/5 text-muted-foreground group-hover:text-sidebar-foreground'
                )}
              >
                <Icon className="h-4 w-4" />
              </div>
              <span
                className={cn(
                  'text-sm font-medium',
                  active
                    ? 'text-sidebar-foreground'
                    : 'text-sidebar-foreground/90'
                )}
              >
                {item.label}
              </span>
            </Link>
          );
        })}
      </nav>

      <div className="px-3 pt-5">
        <p className="px-2 pb-2 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          User area
        </p>
        <Link
          href="/user"
          className="group flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left transition-colors hover:bg-white/5"
        >
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-white/5 text-muted-foreground group-hover:text-sidebar-foreground">
            <ArrowLeftRight className="h-4 w-4" />
          </div>
          <span className="text-sm font-medium text-sidebar-foreground/90">
            User Chat
          </span>
        </Link>
      </div>

      <div className="mt-auto flex items-center justify-between border-t border-sidebar-border px-4 py-3">
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
        </div>
        <Badge
          variant="secondary"
          className="border-0 bg-primary/15 text-[10px] text-primary"
        >
          Admin
        </Badge>
      </div>
    </aside>
  );
}
