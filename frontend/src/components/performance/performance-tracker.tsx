"use client";

import { useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Badge } from "@/components/ui/badge";
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
import { useLeaderboard, usePerformance } from "@/hooks/use-betting-data";
import { LEAGUE_OPTIONS } from "@/lib/leagues";
import { formatProbPct } from "@/lib/utils";
import type { LeagueKey } from "@/types/betting";

export function PerformanceTracker() {
  const [league, setLeague] = useState<LeagueKey | "all">("all");
  const perfQuery = usePerformance(league);
  const boardQuery = useLeaderboard();

  const summaries = perfQuery.data ?? [];
  const leaderboard = boardQuery.data ?? [];
  const isLoading = perfQuery.isLoading || boardQuery.isLoading;
  const error = perfQuery.error || boardQuery.error;
  const isError = perfQuery.isError || boardQuery.isError;

  const chartData = leaderboard.map((s) => ({
    name: s.source,
    accuracy: Number((s.last_30_days_accuracy * 100).toFixed(1)),
    ev: s.avg_ev_captured,
  }));

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="font-display text-2xl font-bold tracking-tight md:text-3xl">
            Model Performance Tracker
          </h1>
          <p className="mt-1 text-sm text-zinc-400">
            30-day accuracy leaderboard per source and competition
          </p>
        </div>
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
      </div>

      {isError && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
          {error instanceof Error ? error.message : "Failed to load performance"}
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Global 30-day accuracy</CardTitle>
        </CardHeader>
        <CardContent className="h-72">
          {isLoading ? (
            <Skeleton className="h-full w-full" />
          ) : chartData.length === 0 ? (
            <EmptyState
              title="No performance data yet"
              description="Settled results will populate the leaderboard after scrapers sync."
              className="h-full"
            />
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                <XAxis dataKey="name" stroke="#71717a" tick={{ fontSize: 11 }} />
                <YAxis stroke="#71717a" tick={{ fontSize: 11 }} unit="%" />
                <Tooltip
                  contentStyle={{
                    background: "#18181b",
                    border: "1px solid #3f3f46",
                    borderRadius: 8,
                  }}
                />
                <Bar dataKey="accuracy" fill="#34d399" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </CardContent>
      </Card>

      <div className="overflow-hidden rounded-xl border border-zinc-800">
        <table className="w-full min-w-[800px] text-left text-sm">
          <thead className="bg-zinc-900/90 text-[11px] uppercase tracking-wider text-zinc-500">
            <tr>
              <th className="px-4 py-3">Rank</th>
              <th className="px-4 py-3">Source</th>
              <th className="px-4 py-3">Predictions</th>
              <th className="px-4 py-3">Accuracy</th>
              <th className="px-4 py-3">30d Acc</th>
              <th className="px-4 py-3">Brier</th>
              <th className="px-4 py-3">Avg EV cap.</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800/80">
            {isLoading &&
              Array.from({ length: 5 }).map((_, i) => (
                <tr key={i}>
                  {Array.from({ length: 7 }).map((__, j) => (
                    <td key={j} className="px-4 py-3">
                      <Skeleton className="h-4 w-full" />
                    </td>
                  ))}
                </tr>
              ))}
            {!isLoading && leaderboard.length === 0 && !isError && (
              <tr>
                <td colSpan={7}>
                  <EmptyState
                    title="Leaderboard empty"
                    description="Source accuracy appears once settled matches are scored."
                  />
                </td>
              </tr>
            )}
            {!isLoading &&
              leaderboard.map((row) => (
                <tr key={row.source} className="hover:bg-zinc-900/60">
                  <td className="px-4 py-3 font-mono text-zinc-500">
                    #{row.rank}
                  </td>
                  <td className="px-4 py-3 font-medium capitalize text-zinc-100">
                    {row.source}
                  </td>
                  <td className="px-4 py-3 font-mono text-zinc-300">
                    {row.correct}/{row.total_predictions}
                  </td>
                  <td className="px-4 py-3">{formatProbPct(row.accuracy)}</td>
                  <td className="px-4 py-3">
                    <Badge variant="positive">
                      {formatProbPct(row.last_30_days_accuracy)}
                    </Badge>
                  </td>
                  <td className="px-4 py-3 font-mono text-zinc-400">
                    {row.brier_score.toFixed(3)}
                  </td>
                  <td className="px-4 py-3 font-mono text-emerald-400/90">
                    {row.avg_ev_captured > 0 ? "+" : ""}
                    {row.avg_ev_captured.toFixed(1)}%
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {isLoading &&
          Array.from({ length: 4 }).map((_, i) => (
            <Card key={i}>
              <CardHeader>
                <Skeleton className="h-5 w-40" />
              </CardHeader>
              <CardContent className="space-y-2">
                <Skeleton className="h-8 w-full" />
                <Skeleton className="h-8 w-full" />
                <Skeleton className="h-8 w-3/4" />
              </CardContent>
            </Card>
          ))}
        {!isLoading &&
          summaries.map((summary) => (
            <Card key={summary.league}>
              <CardHeader className="flex-row items-center justify-between space-y-0">
                <CardTitle>{summary.league_name}</CardTitle>
                <Badge variant="league">
                  Consensus {formatProbPct(summary.consensus_accuracy)}
                </Badge>
              </CardHeader>
              <CardContent>
                <p className="mb-3 text-xs text-zinc-500">
                  Best source:{" "}
                  <span className="capitalize text-emerald-400">
                    {summary.best_source}
                  </span>
                </p>
                <div className="space-y-2">
                  {summary.sources.map((s) => (
                    <div
                      key={s.source}
                      className="flex items-center justify-between rounded-md bg-zinc-950/50 px-3 py-2"
                    >
                      <span className="text-sm capitalize text-zinc-300">
                        #{s.rank} {s.source}
                      </span>
                      <span className="font-mono text-xs text-zinc-400">
                        {formatProbPct(s.last_30_days_accuracy)} · Brier{" "}
                        {s.brier_score.toFixed(3)}
                      </span>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          ))}
      </div>
    </div>
  );
}
