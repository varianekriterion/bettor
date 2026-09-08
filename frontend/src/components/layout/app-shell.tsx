"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import {
  Activity,
  BookMarked,
  Calculator,
  ChevronLeft,
  ChevronRight,
  Grid3X3,
  LayoutDashboard,
  Radar,
} from "lucide-react";
import { ChatDrawer } from "@/components/chat/chat-drawer";
import { AuthButton } from "@/components/auth/auth-button";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/journal", label: "Bet Journal", icon: BookMarked },
  { href: "/matrix", label: "Aggregator Matrix", icon: Grid3X3 },
  { href: "/calculator", label: "EV Calculator", icon: Calculator },
  { href: "/performance", label: "Model Tracker", icon: Activity },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100">
      <div className="pointer-events-none fixed inset-0 bg-[radial-gradient(ellipse_at_top,_rgba(16,185,129,0.08),_transparent_50%),radial-gradient(ellipse_at_bottom_right,_rgba(14,165,233,0.06),_transparent_45%)]" />
      <div className="relative flex min-h-screen">
        <aside
          className={cn(
            "sticky top-0 hidden h-screen shrink-0 flex-col border-r border-zinc-800/80 bg-zinc-950/80 py-4 backdrop-blur transition-[width,padding] duration-200 ease-in-out md:flex",
            collapsed ? "w-[4.5rem] px-2" : "w-56 px-3"
          )}
        >
          <div
            className={cn(
              "mb-6 flex items-center",
              collapsed ? "flex-col gap-2 px-0" : "justify-between gap-2 px-1"
            )}
          >
            {collapsed ? (
              <button
                type="button"
                onClick={() => setCollapsed((prev) => !prev)}
                aria-label="Expand sidebar"
                className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-zinc-800 bg-zinc-900/50 text-zinc-400 transition-colors hover:bg-zinc-900 hover:text-zinc-200"
              >
                <ChevronRight className="h-4 w-4" />
              </button>
            ) : null}
            <div
              className={cn(
                "flex min-w-0 items-center",
                collapsed ? "justify-center" : "gap-2.5"
              )}
            >
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-emerald-500/15 ring-1 ring-emerald-500/40">
                <Radar className="h-5 w-5 text-emerald-400" />
              </div>
              {!collapsed && (
                <div className="min-w-0">
                  <div className="font-display text-sm font-bold tracking-tight text-zinc-50">
                    BetConsensus
                  </div>
                  <div className="text-[10px] uppercase tracking-[0.18em] text-zinc-500">
                    Engine
                  </div>
                </div>
              )}
            </div>
            {!collapsed ? (
              <button
                type="button"
                onClick={() => setCollapsed((prev) => !prev)}
                aria-label="Collapse sidebar"
                className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-zinc-800 bg-zinc-900/50 text-zinc-400 transition-colors hover:bg-zinc-900 hover:text-zinc-200"
              >
                <ChevronLeft className="h-4 w-4" />
              </button>
            ) : null}
          </div>
          <nav className="flex flex-1 flex-col gap-1">
            {NAV.map((item) => {
              const active =
                item.href === "/"
                  ? pathname === "/"
                  : pathname.startsWith(item.href);
              const Icon = item.icon;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  title={collapsed ? item.label : undefined}
                  className={cn(
                    "flex items-center rounded-lg py-2.5 text-sm transition-colors",
                    collapsed ? "justify-center px-2" : "gap-3 px-3",
                    active
                      ? "bg-emerald-500/10 text-emerald-300 ring-1 ring-emerald-500/25"
                      : "text-zinc-400 hover:bg-zinc-900 hover:text-zinc-100"
                  )}
                >
                  <Icon className="h-4 w-4 shrink-0" />
                  {!collapsed && <span className="truncate">{item.label}</span>}
                </Link>
              );
            })}
          </nav>
          {!collapsed && (
            <div className="mt-auto rounded-lg border border-zinc-800 bg-zinc-900/50 p-3 text-[11px] leading-relaxed text-zinc-500">
              Quarter-Kelly default · Multiplicative + power devig · Bayesian
              consensus across 5 sources
            </div>
          )}
        </aside>

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-20 border-b border-zinc-800/80 bg-zinc-950/85 backdrop-blur">
            <div className="flex items-center justify-between gap-4 px-4 py-3 md:px-8">
              <div className="md:hidden">
                <div className="font-display text-sm font-bold">BetConsensus</div>
              </div>
              <div className="hidden text-sm text-zinc-400 md:block">
                Football Edge
              </div>
              <div className="flex items-center gap-2">
                <AuthButton />
                <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-[11px] font-medium text-emerald-300">
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" />
                  Live feed
                </span>
              </div>
            </div>
            <nav className="flex gap-1 overflow-x-auto px-4 pb-3 md:hidden">
              {NAV.map((item) => {
                const active =
                  item.href === "/"
                    ? pathname === "/"
                    : pathname.startsWith(item.href);
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={cn(
                      "whitespace-nowrap rounded-md px-3 py-1.5 text-xs",
                      active
                        ? "bg-emerald-500/15 text-emerald-300"
                        : "bg-zinc-900 text-zinc-400"
                    )}
                  >
                    {item.label}
                  </Link>
                );
              })}
            </nav>
          </header>
          <main className="flex-1 px-4 py-6 md:px-8 md:py-8">{children}</main>
        </div>
      </div>
      <ChatDrawer />
    </div>
  );
}
