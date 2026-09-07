"use client";

import { format } from "date-fns";
import { Activity, RefreshCw, TrendingUp, Filter } from "lucide-react";
import { useMemo, useState } from "react";
import { LineMovementModal } from "@/components/dashboard/line-movement-modal";
import { BetJournal } from "@/components/journal/bet-journal";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useMatches } from "@/hooks/use-betting-data";
import { LEAGUE_OPTIONS } from "@/lib/leagues";
import {
  formatEv,
  formatOdds,
  formatProbPct,
  outcomeTeamLabel,
} from "@/lib/utils";
import type { LeagueKey, MatchCard, Outcome } from "@/types/betting";

type SelectedMatch = {
  id: string;
  home_team: string;
  away_team: string;
  outcome: Outcome;
};

export function DashboardHome() {
  const [league, setLeague] = useState<LeagueKey | "all">("all");
  const [positiveOnly, setPositiveOnly] = useState(false);
  const [selected, setSelected] = useState<SelectedMatch | null>(null);

  const {
    data: matches = [],
    isLoading,
    isFetching,
    isError,
    error,
    refetch,
  } = useMatches(league, positiveOnly);

  const stats = useMemo(() => {
    const plus = matches.filter((m) => m.best_edge.is_positive_ev);
    const avgEv =
      plus.length > 0
        ? plus.reduce((s, m) => s + m.best_edge.ev_pct, 0) / plus.length
        : 0;
    return {
      total: matches.length,
      plusEv: plus.length,
      avgEv,
      avgKelly:
        plus.length > 0
          ? plus.reduce((s, m) => s + m.best_edge.kelly_pct, 0) / plus.length
          : 0,
    };
  }, [matches]);

  function openLineMovement(m: MatchCard) {
    setSelected({
      id: m.id,
      home_team: m.home_team,
      away_team: m.away_team,
      outcome: m.best_edge.outcome,
    });
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="font-display text-2xl font-bold tracking-tight text-zinc-50 md:text-3xl">
            Live Edge Dashboard
          </h1>
          <p className="mt-1 text-sm text-zinc-400">
            Consensus pick vs bookie odds · +EV% · Quarter-Kelly stake · click a
            row for line movement
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Select
            value={league}
            onValueChange={(v) => setLeague(v as LeagueKey | "all")}
          >
            <SelectTrigger className="w-[180px]">
              <SelectValue placeholder="League" />
            </SelectTrigger>
            <SelectContent>
              {LEAGUE_OPTIONS.map((l) => (
                <SelectItem key={l.value} value={l.value}>
                  {l.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            variant={positiveOnly ? "default" : "secondary"}
            size="sm"
            onClick={() => setPositiveOnly((v) => !v)}
          >
            <Filter className="h-3.5 w-3.5" />
            +EV only
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void refetch()}
            disabled={isFetching}
          >
            <RefreshCw
              className={`h-3.5 w-3.5 ${isFetching ? "animate-spin" : ""}`}
            />
            Refresh
          </Button>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {isLoading ? (
          <>
            <StatSkeleton />
            <StatSkeleton />
            <StatSkeleton />
            <StatSkeleton />
          </>
        ) : (
          <>
            <Stat label="Fixtures" value={String(stats.total)} />
            <Stat label="+EV bets" value={String(stats.plusEv)} accent />
            <Stat label="Avg +EV" value={`${stats.avgEv.toFixed(1)}%`} />
            <Stat label="Avg Kelly" value={`${stats.avgKelly.toFixed(2)}%`} />
          </>
        )}
      </div>

      {isError && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
          Backend unreachable — start the FastAPI server on port 8000.{" "}
          <span className="text-amber-400/80">
            ({(error instanceof Error ? error.message : "error").slice(0, 120)})
          </span>
        </div>
      )}

      <div className="overflow-hidden rounded-xl border border-zinc-800">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[1020px] text-left text-sm">
            <thead className="bg-zinc-900/90 text-[11px] uppercase tracking-wider text-zinc-500">
              <tr>
                <th className="px-4 py-3 font-medium">Kickoff</th>
                <th className="px-4 py-3 font-medium">Match</th>
                <th className="px-4 py-3 font-medium">League</th>
                <th className="px-4 py-3 font-medium">Consensus</th>
                <th className="px-4 py-3 font-medium">Best odds</th>
                <th className="px-4 py-3 font-medium">Pick / Edge</th>
                <th className="px-4 py-3 font-medium">EV%</th>
                <th className="px-4 py-3 font-medium">Kelly%</th>
                <th className="px-4 py-3 font-medium">Lines</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-800/80">
              {isLoading && (
                <>
                  <MatchRowSkeleton />
                  <MatchRowSkeleton />
                  <MatchRowSkeleton />
                  <MatchRowSkeleton />
                  <MatchRowSkeleton />
                </>
              )}
              {!isLoading && matches.length === 0 && !isError && (
                <tr>
                  <td colSpan={9}>
                    <EmptyState
                      title="No fixtures available"
                      description="Scrapers or odds APIs may still be syncing. Try another league or refresh in a moment."
                    />
                  </td>
                </tr>
              )}
              {!isLoading &&
                matches.map((m) => {
                  const pickLabel = outcomeTeamLabel(
                    m.best_edge.outcome,
                    m.home_team,
                    m.away_team
                  );
                  const consPick = outcomeTeamLabel(
                    m.consensus.pick,
                    m.home_team,
                    m.away_team
                  );
                  return (
                    <tr
                      key={m.id}
                      className="cursor-pointer bg-zinc-950/40 transition-colors hover:bg-zinc-900/70"
                      onClick={() => openLineMovement(m)}
                    >
                      <td className="px-4 py-3.5 font-mono text-xs text-zinc-400">
                        {format(new Date(m.commence_time), "dd MMM HH:mm")}
                      </td>
                      <td className="px-4 py-3.5">
                        <div className="font-medium text-zinc-100">
                          {m.home_team}
                        </div>
                        <div className="text-xs text-zinc-500">
                          vs {m.away_team}
                        </div>
                      </td>
                      <td className="px-4 py-3.5">
                        <Badge variant="league">{m.league_name}</Badge>
                      </td>
                      <td className="px-4 py-3.5">
                        <div className="text-zinc-200">{consPick}</div>
                        <div className="font-mono text-[11px] text-zinc-500">
                          H {formatProbPct(m.consensus.home)} · D{" "}
                          {formatProbPct(m.consensus.draw)} · A{" "}
                          {formatProbPct(m.consensus.away)}
                        </div>
                      </td>
                      <td className="px-4 py-3.5 font-mono text-xs text-zinc-300">
                        <div>
                          {formatOdds(m.odds.best_home)} /{" "}
                          {formatOdds(m.odds.best_draw)} /{" "}
                          {formatOdds(m.odds.best_away)}
                        </div>
                        {m.odds.best_over != null && m.odds.best_under != null && (
                          <div className="mt-0.5 text-[10px] text-zinc-500">
                            O/U {m.odds.totals_line ?? 2.5}:{" "}
                            {formatOdds(m.odds.best_over)} /{" "}
                            {formatOdds(m.odds.best_under)}
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3.5">
                        <div className="flex items-center gap-1.5">
                          <TrendingUp className="h-3.5 w-3.5 text-emerald-400" />
                          <span className="font-medium text-zinc-100">
                            {pickLabel}
                          </span>
                        </div>
                        <div className="font-mono text-[11px] text-zinc-500">
                          @ {formatOdds(m.best_edge.odds)} · p=
                          {formatProbPct(m.best_edge.probability)}
                        </div>
                      </td>
                      <td className="px-4 py-3.5">
                        <Badge
                          variant={
                            m.best_edge.is_positive_ev ? "positive" : "negative"
                          }
                        >
                          {formatEv(m.best_edge.ev_pct)}
                        </Badge>
                      </td>
                      <td className="px-4 py-3.5 font-mono text-sm text-zinc-200">
                        {m.best_edge.kelly_pct.toFixed(2)}%
                      </td>
                      <td className="px-4 py-3.5">
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-7 px-2 text-sky-300 hover:text-sky-200"
                          onClick={(e) => {
                            e.stopPropagation();
                            openLineMovement(m);
                          }}
                        >
                          <Activity className="h-3.5 w-3.5" />
                          Chart
                        </Button>
                      </td>
                    </tr>
                  );
                })}
            </tbody>
          </table>
        </div>
      </div>

      <BetJournal matches={matches} />

      <LineMovementModal
        open={selected !== null}
        onOpenChange={(open) => {
          if (!open) setSelected(null);
        }}
        matchId={selected?.id ?? null}
        homeTeam={selected?.home_team}
        awayTeam={selected?.away_team}
        outcome={selected?.outcome}
      />
    </div>
  );
}

function Stat({
  label,
  value,
  accent,
}: {
  label: string;
  value: string;
  accent?: boolean;
}) {
  return (
    <Card>
      <CardHeader className="pb-1">
        <CardTitle className="text-xs font-medium uppercase tracking-wider text-zinc-500">
          {label}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div
          className={`font-display text-2xl font-bold ${
            accent ? "text-emerald-400" : "text-zinc-50"
          }`}
        >
          {value}
        </div>
      </CardContent>
    </Card>
  );
}

function StatSkeleton() {
  return (
    <Card>
      <CardHeader className="pb-1">
        <Skeleton className="h-3 w-16" />
      </CardHeader>
      <CardContent>
        <Skeleton className="h-8 w-20" />
      </CardContent>
    </Card>
  );
}

function MatchRowSkeleton() {
  return (
    <tr>
      {Array.from({ length: 9 }).map((_, i) => (
        <td key={i} className="px-4 py-3.5">
          <Skeleton className="h-4 w-full max-w-[120px]" />
        </td>
      ))}
    </tr>
  );
}
