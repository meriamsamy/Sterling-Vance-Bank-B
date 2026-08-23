'use client';

import * as React from 'react';
import { AdminSidebar } from '@/components/admin-sidebar';
import { Button } from '@/components/ui/button';
import { Sheet, SheetContent, SheetTrigger } from '@/components/ui/sheet';
import { Menu, Building2 } from 'lucide-react';

export default function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const [mobileOpen, setMobileOpen] = React.useState(false);

  return (
    <div className="flex h-screen w-full overflow-hidden bg-background">
      {/* Desktop sidebar */}
      <div className="hidden md:flex">
        <AdminSidebar />
      </div>

      {/* Mobile sidebar via Sheet */}
      <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
        <SheetContent
          side="left"
          className="w-72 border-sidebar-border bg-sidebar p-0"
        >
          <AdminSidebar />
        </SheetContent>
      </Sheet>

      <main className="flex h-full flex-1 flex-col">
        {/* Mobile top bar */}
        <div className="flex h-14 items-center gap-3 border-b border-border bg-background/80 px-4 backdrop-blur md:hidden">
          <Sheet>
            <SheetTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                aria-label="Open navigation"
              >
                <Menu className="h-4 w-4" />
              </Button>
            </SheetTrigger>
          </Sheet>
          <div className="flex items-center gap-2">
            <div className="flex h-7 w-7 items-center justify-center rounded-md bg-primary/15 ring-1 ring-primary/30">
              <Building2 className="h-4 w-4 text-primary" />
            </div>
            <span className="text-sm font-semibold tracking-tight">
              Sentinel Admin
            </span>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto scrollbar-thin">
          {children}
        </div>
      </main>
    </div>
  );
}
