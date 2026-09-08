"use client";

import { format } from "date-fns";
import { Activity, RefreshCw, TrendingUp, Filter } from "lucide-react";
import { useMemo, useState } from "react";
import { LineMovementModal } from "@/components/dashboard/line-movement-modal";
import { MatchSearch } from "@/components/dashboard/match-search";
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
import { matchMatchesQuery } from "@/lib/match-search";
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
  const [league, setLeague] = useState<LeagueKey | "all">("epl");
  const [positiveOnly, setPositiveOnly] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [pinnedMatchId, setPinnedMatchId] = useState<string | null>(null);
  const [selected, setSelected] = useState<SelectedMatch | null>(null);

  const {
    data: matches = [],
    isLoading,
    isFetching,
    isError,
    error,
    refetch,
    dataUpdatedAt,
  } = useMatches(league, positiveOnly);

  const needsSearchIndex = league !== "all" || positiveOnly;
  const { data: searchIndexExtra = [] } = useMatches("all", false, {
    enabled: needsSearchIndex,
  });
  const searchIndex = needsSearchIndex ? searchIndexExtra : matches;

  const displayedMatches = useMemo(() => {
    if (pinnedMatchId) {
      const pinned =
        matches.find((m) => m.id === pinnedMatchId) ??
        searchIndex.find((m) => m.id === pinnedMatchId);
      return pinned ? [pinned] : [];
    }
    if (!searchQuery.trim()) return matches;
    return matches.filter((m) => matchMatchesQuery(m, searchQuery));
  }, [matches, searchIndex, pinnedMatchId, searchQuery]);

  const hasFixtures = matches.length > 0;
  const showSkeleton = isLoading && !hasFixtures;
  const showEmpty = !showSkeleton && displayedMatches.length === 0 && !isError;
  const lastUpdatedLabel =
    dataUpdatedAt > 0 ? format(new Date(dataUpdatedAt), "HH:mm") : null;

  const stats = useMemo(() => {
    const plus = displayedMatches.filter((m) => m.best_edge.is_positive_ev);
    const avgEv =
      plus.length > 0
        ? plus.reduce((s, m) => s + m.best_edge.ev_pct, 0) / plus.length
        : 0;
    return {
      total: displayedMatches.length,
      plusEv: plus.length,
      avgEv,
      avgKelly:
        plus.length > 0
          ? plus.reduce((s, m) => s + m.best_edge.kelly_pct, 0) / plus.length
          : 0,
    };
  }, [displayedMatches]);

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
          <MatchSearch
            matches={searchIndex}
            value={searchQuery}
            onValueChange={(value) => {
              setSearchQuery(value);
              setPinnedMatchId(null);
            }}
            onSelectMatch={(match) => {
              if (match) setPinnedMatchId(match.id);
              else setPinnedMatchId(null);
            }}
            disabled={showSkeleton && searchIndex.length === 0}
          />
          <Select
            value={league}
            onValueChange={(v) => {
              setLeague(v as LeagueKey | "all");
              setPinnedMatchId(null);
            }}
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
        {showSkeleton ? (
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

      {isError && !hasFixtures && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
          Backend unreachable — start the FastAPI server on port 8000.{" "}
          <span className="text-amber-400/80">
            ({(error instanceof Error ? error.message : "error").slice(0, 120)})
          </span>
        </div>
      )}

      {isError && hasFixtures && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
          Backend unreachable — showing your last saved fixtures
          {lastUpdatedLabel ? ` (updated ${lastUpdatedLabel})` : ""}.
        </div>
      )}

      {isFetching && hasFixtures && !isError && (
        <div className="rounded-lg border border-zinc-700/60 bg-zinc-900/50 px-4 py-2 text-sm text-zinc-400">
          Refreshing fixtures…
        </div>
      )}

      <div className="overflow-hidden rounded-xl border border-zinc-800">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[1180px] text-left text-base">
            <thead className="bg-zinc-900/90 text-xs uppercase tracking-wider text-zinc-400">
              <tr>
                <th className="whitespace-nowrap px-4 py-3 font-medium">Kickoff</th>
                <th className="whitespace-nowrap px-4 py-3 font-medium">Match</th>
                <th className="whitespace-nowrap px-4 py-3 font-medium">League</th>
                <th className="whitespace-nowrap px-4 py-3 font-medium">Consensus</th>
                <th className="whitespace-nowrap px-4 py-3 font-medium">Best odds</th>
                <th className="whitespace-nowrap px-4 py-3 font-medium">Pick / Edge</th>
                <th className="whitespace-nowrap px-4 py-3 font-medium">EV%</th>
                <th className="whitespace-nowrap px-4 py-3 font-medium">Kelly%</th>
                <th className="whitespace-nowrap px-4 py-3 font-medium">Lines</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-800/80">
              {showSkeleton && (
                <>
                  <MatchRowSkeleton />
                  <MatchRowSkeleton />
                  <MatchRowSkeleton />
                  <MatchRowSkeleton />
                  <MatchRowSkeleton />
                </>
              )}
              {showEmpty && (
                <tr>
                  <td colSpan={9}>
                    <EmptyState
                      title={
                        searchQuery.trim() || pinnedMatchId
                          ? "No matching fixtures"
                          : "No fixtures available"
                      }
                      description={
                        searchQuery.trim() || pinnedMatchId
                          ? "Try a different team name, switch to All leagues, or clear the search."
                          : "Scrapers or odds APIs may still be syncing. Try another league or refresh in a moment."
                      }
                    />
                  </td>
                </tr>
              )}
              {!showSkeleton &&
                displayedMatches.map((m) => {
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
                      <td className="whitespace-nowrap px-4 py-3.5 font-mono text-sm text-zinc-100">
                        {format(new Date(m.commence_time), "dd MMM HH:mm")}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3.5 font-medium text-zinc-100">
                        {m.home_team} vs {m.away_team}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3.5">
                        <Badge variant="league" className="whitespace-nowrap">
                          {m.league_name}
                        </Badge>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3.5">
                        <div className="whitespace-nowrap text-zinc-100">{consPick}</div>
                        <div className="whitespace-nowrap font-mono text-sm text-zinc-300">
                          H {formatProbPct(m.consensus.home)} · D{" "}
                          {formatProbPct(m.consensus.draw)} · A{" "}
                          {formatProbPct(m.consensus.away)}
                        </div>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3.5 font-mono text-sm text-zinc-100">
                        <div className="whitespace-nowrap">
                          {formatOdds(m.odds.best_home)} /{" "}
                          {formatOdds(m.odds.best_draw)} /{" "}
                          {formatOdds(m.odds.best_away)}
                        </div>
                        {m.odds.best_over != null && m.odds.best_under != null && (
                          <div className="mt-0.5 whitespace-nowrap text-sm text-zinc-300">
                            O/U {m.odds.totals_line ?? 2.5}:{" "}
                            {formatOdds(m.odds.best_over)} /{" "}
                            {formatOdds(m.odds.best_under)}
                          </div>
                        )}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3.5">
                        <div className="flex items-center gap-1.5 whitespace-nowrap">
                          <TrendingUp className="h-4 w-4 shrink-0 text-emerald-400" />
                          <span className="font-medium text-zinc-100">
                            {pickLabel}
                          </span>
                        </div>
                        <div className="whitespace-nowrap font-mono text-sm text-zinc-300">
                          @ {formatOdds(m.best_edge.odds)} · p=
                          {formatProbPct(m.best_edge.probability)}
                        </div>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3.5">
                        <Badge
                          variant={
                            m.best_edge.is_positive_ev ? "positive" : "negative"
                          }
                          className="whitespace-nowrap"
                        >
                          {formatEv(m.best_edge.ev_pct)}
                        </Badge>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3.5 font-mono text-base text-zinc-100">
                        {m.best_edge.kelly_pct.toFixed(2)}%
                      </td>
                      <td className="whitespace-nowrap px-4 py-3.5">
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-7 shrink-0 whitespace-nowrap px-2 text-zinc-300 hover:text-zinc-100"
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
