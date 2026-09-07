"use client";

import { Activity } from "lucide-react";
import { useState } from "react";
import { LineMovementModal } from "@/components/dashboard/line-movement-modal";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useMatrix } from "@/hooks/use-betting-data";
import { LEAGUE_OPTIONS } from "@/lib/leagues";
import { formatEv, formatProbPct } from "@/lib/utils";
import type { LeagueKey, Outcome, PredictionSource } from "@/types/betting";
import { SOURCE_LABELS } from "@/types/betting";

const SOURCES: PredictionSource[] = [
  "forebet",
  "predictz",
  "windrawwin",
  "betimate",
  "footballwhispers",
];

type SelectedMatch = {
  id: string;
  home_team: string;
  away_team: string;
  outcome: Outcome;
};

export function AggregatorMatrix() {
  const [league, setLeague] = useState<LeagueKey | "all">("all");
  const [selected, setSelected] = useState<SelectedMatch | null>(null);
  const { data: rows = [], isLoading, isFetching, isError, error, refetch } =
    useMatrix(league);

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="font-display text-2xl font-bold tracking-tight md:text-3xl">
            Aggregator Matrix
          </h1>
          <p className="mt-1 text-sm text-zinc-400">
            Side-by-side source picks vs master Bayesian consensus · open a row
            for line movement
          </p>
        </div>
        <div className="flex gap-2">
          <Select
            value={league}
            onValueChange={(v) => setLeague(v as LeagueKey | "all")}
          >
            <SelectTrigger className="w-[180px]">
              <SelectValue />
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
            variant="outline"
            size="sm"
            onClick={() => void refetch()}
            disabled={isFetching}
          >
            Refresh
          </Button>
        </div>
      </div>

      {isError && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
          {error instanceof Error ? error.message : "Failed to load matrix"}
        </div>
      )}

      <div className="overflow-hidden rounded-xl border border-zinc-800">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[1180px] text-left text-sm">
            <thead className="bg-zinc-900/90 text-[11px] uppercase tracking-wider text-zinc-500">
              <tr>
                <th className="sticky left-0 z-10 bg-zinc-900 px-4 py-3 font-medium">
                  Match
                </th>
                {SOURCES.map((s) => (
                  <th key={s} className="px-3 py-3 font-medium">
                    {SOURCE_LABELS[s]}
                  </th>
                ))}
                <th className="px-3 py-3 font-medium text-emerald-400/90">
                  Master Consensus
                </th>
                <th className="px-3 py-3 font-medium">Edge</th>
                <th className="px-3 py-3 font-medium">Lines</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-800/80">
              {isLoading &&
                Array.from({ length: 5 }).map((_, i) => (
                  <tr key={i}>
                    {Array.from({ length: 9 }).map((__, j) => (
                      <td key={j} className="px-3 py-3">
                        <Skeleton className="h-10 w-full" />
                      </td>
                    ))}
                  </tr>
                ))}
              {!isLoading && rows.length === 0 && !isError && (
                <tr>
                  <td colSpan={9}>
                    <EmptyState
                      title="Matrix is empty"
                      description="No source predictions for this league yet. Wait for scrapers to sync, then refresh."
                    />
                  </td>
                </tr>
              )}
              {!isLoading &&
                rows.map((row) => (
                  <tr
                    key={row.match_id}
                    className="cursor-pointer hover:bg-zinc-900/60"
                    onClick={() =>
                      setSelected({
                        id: row.match_id,
                        home_team: row.home_team,
                        away_team: row.away_team,
                        outcome: row.best_edge.outcome,
                      })
                    }
                  >
                    <td className="sticky left-0 z-10 bg-zinc-950 px-4 py-3">
                      <div className="font-medium text-zinc-100">
                        {row.home_team}
                      </div>
                      <div className="text-xs text-zinc-500">
                        vs {row.away_team}
                      </div>
                      <Badge variant="league" className="mt-1">
                        {row.league.toUpperCase()}
                      </Badge>
                    </td>
                    {SOURCES.map((s) => {
                      const cell = row.sources[s];
                      return (
                        <td key={s} className="px-3 py-3 align-top">
                          {cell ? (
                            <div>
                              <div className="font-semibold uppercase text-zinc-200">
                                {cell.pick[0]}
                              </div>
                              <div className="mt-1 space-y-0.5 font-mono text-[10px] text-zinc-500">
                                <div>H {formatProbPct(cell.home, 0)}</div>
                                <div>D {formatProbPct(cell.draw, 0)}</div>
                                <div>A {formatProbPct(cell.away, 0)}</div>
                              </div>
                            </div>
                          ) : (
                            <span className="text-zinc-600">—</span>
                          )}
                        </td>
                      );
                    })}
                    <td className="bg-emerald-500/5 px-3 py-3 align-top">
                      <div className="font-semibold uppercase text-emerald-300">
                        {row.consensus.pick}
                      </div>
                      <div className="mt-1 space-y-0.5 font-mono text-[10px] text-emerald-400/70">
                        <div>H {formatProbPct(row.consensus.home, 0)}</div>
                        <div>D {formatProbPct(row.consensus.draw, 0)}</div>
                        <div>A {formatProbPct(row.consensus.away, 0)}</div>
                      </div>
                    </td>
                    <td className="px-3 py-3 align-top">
                      <Badge
                        variant={
                          row.best_edge.is_positive_ev ? "positive" : "negative"
                        }
                      >
                        {formatEv(row.best_edge.ev_pct)}
                      </Badge>
                      <div className="mt-1 font-mono text-[10px] text-zinc-500">
                        Kelly {row.best_edge.kelly_pct.toFixed(2)}%
                      </div>
                    </td>
                    <td className="px-3 py-3 align-top">
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 px-2 text-sky-300 hover:text-sky-200"
                        onClick={(e) => {
                          e.stopPropagation();
                          setSelected({
                            id: row.match_id,
                            home_team: row.home_team,
                            away_team: row.away_team,
                            outcome: row.best_edge.outcome,
                          });
                        }}
                      >
                        <Activity className="h-3.5 w-3.5" />
                        Chart
                      </Button>
                    </td>
                  </tr>
                ))}
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
