"use client";

import { format } from "date-fns";
import { ArrowDownRight, ArrowUpRight, TrendingUp } from "lucide-react";
import { useMemo } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceArea,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { useOddsHistory } from "@/hooks/use-betting-data";
import {
  formatEv,
  formatOdds,
  formatProbPct,
  outcomeTeamLabel,
} from "@/lib/utils";
import type { Outcome } from "@/types/betting";

type LineMovementModalProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  matchId: string | null;
  homeTeam?: string;
  awayTeam?: string;
  outcome?: Outcome;
};

export function LineMovementModal({
  open,
  onOpenChange,
  matchId,
  homeTeam,
  awayTeam,
  outcome,
}: LineMovementModalProps) {
  const { data, isLoading, isError, error } = useOddsHistory(
    matchId,
    outcome,
    open
  );

  const chartData = useMemo(() => {
    if (!data?.points?.length) return [];
    return data.points.map((p) => ({
      t: format(new Date(p.captured_at), "dd MMM HH:mm"),
      ts: p.captured_at,
      bookie: Number((p.bookie_implied_prob * 100).toFixed(2)),
      consensus: Number((p.consensus_prob * 100).toFixed(2)),
      delta: Number((p.delta_prob * 100).toFixed(2)),
      ev: p.ev_pct,
      isPositive: p.is_positive_ev,
      bookieOdds: p.bookie_odds,
      trueOdds: p.consensus_true_odds,
    }));
  }, [data]);

  const valueZones = useMemo(() => {
    // Highlight stretches where consensus > bookie implied (+EV territory).
    const zones: { x1: string; x2: string }[] = [];
    if (chartData.length < 2) return zones;
    let start: string | null = null;
    for (let i = 0; i < chartData.length; i++) {
      const positive = chartData[i].consensus > chartData[i].bookie;
      if (positive && start === null) {
        start = chartData[i].t;
      }
      if ((!positive || i === chartData.length - 1) && start !== null) {
        const endIdx = positive && i === chartData.length - 1 ? i : Math.max(0, i - 1);
        zones.push({ x1: start, x2: chartData[endIdx].t });
        start = null;
      }
    }
    return zones;
  }, [chartData]);

  const titleHome = data?.home_team ?? homeTeam ?? "Home";
  const titleAway = data?.away_team ?? awayTeam ?? "Away";
  const tracked = data?.outcome ?? outcome ?? "home";
  const pickLabel = outcomeTeamLabel(tracked, titleHome, titleAway);
  const valueShift = data?.value_shift_ev ?? 0;
  const improving = valueShift > 0.05;
  const worsening = valueShift < -0.05;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Line Movement</DialogTitle>
          <DialogDescription>
            {titleHome} vs {titleAway}
            {data?.league_name ? ` · ${data.league_name}` : ""} — bookie implied
            probability vs Bayesian consensus for{" "}
            <span className="text-zinc-200">{pickLabel}</span>
          </DialogDescription>
        </DialogHeader>

        <div className="overflow-y-auto px-5 py-4">
          {isLoading && (
            <div className="space-y-3">
              <Skeleton className="h-16 w-full" />
              <Skeleton className="h-64 w-full" />
            </div>
          )}

          {isError && (
            <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
              {error instanceof Error
                ? error.message
                : "Failed to load odds history"}
            </div>
          )}

          {!isLoading && data && (
            <>
              <div className="mb-4 grid gap-3 sm:grid-cols-4">
                <Metric
                  label="Opening"
                  value={
                    data.opening
                      ? `${formatOdds(data.opening.bookie_odds)} · ${formatProbPct(data.opening.bookie_implied_prob)}`
                      : "—"
                  }
                  sub={
                    data.opening
                      ? `EV ${formatEv(data.opening.ev_pct)}`
                      : undefined
                  }
                />
                <Metric
                  label="Current"
                  value={
                    data.current
                      ? `${formatOdds(data.current.bookie_odds)} · ${formatProbPct(data.current.bookie_implied_prob)}`
                      : "—"
                  }
                  sub={
                    data.current
                      ? `EV ${formatEv(data.current.ev_pct)}`
                      : undefined
                  }
                />
                <Metric
                  label="Consensus true odds"
                  value={
                    data.current
                      ? formatOdds(data.current.consensus_true_odds)
                      : "—"
                  }
                  sub={
                    data.current
                      ? `p=${formatProbPct(data.current.consensus_prob)}`
                      : undefined
                  }
                />
                <div className="rounded-lg border border-zinc-800 bg-zinc-900/50 px-3 py-2.5">
                  <div className="text-[11px] uppercase tracking-wider text-zinc-500">
                    Value shift
                  </div>
                  <div className="mt-1 flex items-center gap-1.5">
                    {improving ? (
                      <ArrowUpRight className="h-4 w-4 text-emerald-400" />
                    ) : worsening ? (
                      <ArrowDownRight className="h-4 w-4 text-rose-400" />
                    ) : (
                      <TrendingUp className="h-4 w-4 text-zinc-500" />
                    )}
                    <span
                      className={`font-mono text-lg font-semibold ${
                        improving
                          ? "text-emerald-400"
                          : worsening
                            ? "text-rose-400"
                            : "text-zinc-200"
                      }`}
                    >
                      {formatEv(valueShift)}
                    </span>
                  </div>
                  <div className="mt-1 flex flex-wrap gap-1.5">
                    {data.into_positive_ev && (
                      <Badge variant="positive">Deeper +EV</Badge>
                    )}
                    {data.current?.is_positive_ev && (
                      <Badge variant="positive">+EV now</Badge>
                    )}
                    {!data.current?.is_positive_ev && (
                      <Badge variant="negative">No edge</Badge>
                    )}
                  </div>
                </div>
              </div>

              <div className="h-72 w-full rounded-lg border border-zinc-800 bg-zinc-950/80 p-2 sm:h-80">
                {chartData.length === 0 ? (
                  <div className="flex h-full items-center justify-center text-sm text-zinc-500">
                    No line samples yet
                  </div>
                ) : (
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart
                      data={chartData}
                      margin={{ top: 12, right: 16, left: 0, bottom: 8 }}
                    >
                      <CartesianGrid
                        strokeDasharray="3 3"
                        stroke="#27272a"
                        vertical={false}
                      />
                      {valueZones.map((z, i) => (
                        <ReferenceArea
                          key={`${z.x1}-${z.x2}-${i}`}
                          x1={z.x1}
                          x2={z.x2}
                          fill="#34d399"
                          fillOpacity={0.08}
                          ifOverflow="extendDomain"
                        />
                      ))}
                      <XAxis
                        dataKey="t"
                        tick={{ fill: "#71717a", fontSize: 11 }}
                        axisLine={{ stroke: "#3f3f46" }}
                        tickLine={false}
                        minTickGap={28}
                      />
                      <YAxis
                        tick={{ fill: "#71717a", fontSize: 11 }}
                        axisLine={false}
                        tickLine={false}
                        tickFormatter={(v: number) => `${v}%`}
                        domain={["auto", "auto"]}
                        width={42}
                      />
                      <Tooltip
                        contentStyle={{
                          background: "#09090b",
                          border: "1px solid #27272a",
                          borderRadius: 8,
                          fontSize: 12,
                        }}
                        labelStyle={{ color: "#a1a1aa" }}
                        formatter={(value, name) => {
                          const n = String(name);
                          const label =
                            n === "bookie"
                              ? "Bookie implied"
                              : n === "consensus"
                                ? "Bayesian consensus"
                                : n;
                          return [`${Number(value).toFixed(1)}%`, label];
                        }}
                      />
                      <Legend
                        wrapperStyle={{ fontSize: 12, color: "#a1a1aa" }}
                        formatter={(value) =>
                          value === "bookie"
                            ? "Bookie line"
                            : value === "consensus"
                              ? "Bayesian consensus"
                              : value
                        }
                      />
                      <Line
                        type="monotone"
                        dataKey="bookie"
                        name="bookie"
                        stroke="#38bdf8"
                        strokeWidth={2}
                        dot={{ r: 3, fill: "#38bdf8" }}
                        activeDot={{ r: 5 }}
                      />
                      <Line
                        type="monotone"
                        dataKey="consensus"
                        name="consensus"
                        stroke="#34d399"
                        strokeWidth={2.25}
                        dot={{ r: 3, fill: "#34d399" }}
                        activeDot={{ r: 5 }}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                )}
              </div>

              <p className="mt-3 text-[11px] leading-relaxed text-zinc-500">
                Green band marks windows where consensus probability sits above
                the bookie implied line (positive edge). Delta is measured vs
                Bayesian consensus true odds (
                {data.current
                  ? formatOdds(data.current.consensus_true_odds)
                  : "—"}
                ). Source: {data.source}.
              </p>

              {data.points.length > 0 && (
                <div className="mt-4 overflow-hidden rounded-lg border border-zinc-800">
                  <table className="w-full text-left text-xs">
                    <thead className="bg-zinc-900/90 text-[10px] uppercase tracking-wider text-zinc-500">
                      <tr>
                        <th className="px-3 py-2 font-medium">Time</th>
                        <th className="px-3 py-2 font-medium">Bookie</th>
                        <th className="px-3 py-2 font-medium">Implied</th>
                        <th className="px-3 py-2 font-medium">Consensus</th>
                        <th className="px-3 py-2 font-medium">Δ vs true</th>
                        <th className="px-3 py-2 font-medium">EV%</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-zinc-800/80">
                      {data.points.map((p) => (
                        <tr key={p.captured_at} className="bg-zinc-950/40">
                          <td className="px-3 py-2 font-mono text-zinc-400">
                            {format(new Date(p.captured_at), "dd MMM HH:mm")}
                          </td>
                          <td className="px-3 py-2 font-mono text-zinc-200">
                            {formatOdds(p.bookie_odds)}
                          </td>
                          <td className="px-3 py-2 font-mono text-sky-300/90">
                            {formatProbPct(p.bookie_implied_prob)}
                          </td>
                          <td className="px-3 py-2 font-mono text-emerald-300/90">
                            {formatProbPct(p.consensus_prob)}
                          </td>
                          <td className="px-3 py-2 font-mono">
                            <span
                              className={
                                p.delta_prob > 0
                                  ? "text-emerald-400"
                                  : "text-rose-400"
                              }
                            >
                              {p.delta_prob > 0 ? "+" : ""}
                              {(p.delta_prob * 100).toFixed(1)}pp
                            </span>
                          </td>
                          <td className="px-3 py-2">
                            <Badge
                              variant={
                                p.is_positive_ev ? "positive" : "negative"
                              }
                            >
                              {formatEv(p.ev_pct)}
                            </Badge>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

function Metric({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/50 px-3 py-2.5">
      <div className="text-[11px] uppercase tracking-wider text-zinc-500">
        {label}
      </div>
      <div className="mt-1 font-mono text-sm font-semibold text-zinc-100">
        {value}
      </div>
      {sub && <div className="mt-0.5 font-mono text-[11px] text-zinc-500">{sub}</div>}
    </div>
  );
}
