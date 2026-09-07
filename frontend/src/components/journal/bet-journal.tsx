"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookMarked, Loader2, Pencil, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import {
  createJournalEntry,
  deleteJournalEntry,
  listJournalEntries,
  updateJournalEntry,
} from "@/lib/journal";
import { formatCurrency, formatEv, formatOdds } from "@/lib/utils";
import type { BetJournalEntry, BetResult, MatchCard, Outcome } from "@/types/betting";
import { OUTCOME_LABELS } from "@/types/betting";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";

type Props = {
  matches: MatchCard[];
};

const RESULT_OPTIONS: BetResult[] = ["pending", "win", "loss", "push"];

export function BetJournal({ matches }: Props) {
  const qc = useQueryClient();
  const journalQuery = useQuery({
    queryKey: ["bet-journal"],
    queryFn: listJournalEntries,
  });

  const [matchId, setMatchId] = useState<string>("");
  const [outcome, setOutcome] = useState<Outcome>("home");
  const [odds, setOdds] = useState(2.0);
  const [stake, setStake] = useState(25);
  const [units, setUnits] = useState(1);
  const [status, setStatus] = useState<string | null>(null);
  const [editing, setEditing] = useState<BetJournalEntry | null>(null);
  const [editOdds, setEditOdds] = useState(2);
  const [editStake, setEditStake] = useState(25);
  const [editUnits, setEditUnits] = useState(1);
  const [editResult, setEditResult] = useState<BetResult>("pending");

  const selected = useMemo(
    () => matches.find((m) => m.id === matchId) ?? null,
    [matches, matchId]
  );

  const applyMatchDefaults = (id: string) => {
    setMatchId(id);
    const m = matches.find((x) => x.id === id);
    if (!m) return;
    setOutcome(m.best_edge.outcome);
    setOdds(Number(m.best_edge.odds.toFixed(2)));
    const suggestedStake = Math.max(
      1,
      Number(((1000 * m.best_edge.kelly_pct) / 100).toFixed(2))
    );
    setStake(suggestedStake);
    setUnits(Number(Math.max(0.25, m.best_edge.kelly_pct / 25).toFixed(2)));
  };

  const invalidate = () => void qc.invalidateQueries({ queryKey: ["bet-journal"] });

  const saveMutation = useMutation({
    mutationFn: createJournalEntry,
    onSuccess: (res) => {
      invalidate();
      setStatus(
        res.mode === "supabase"
          ? "Bet added to Supabase bet_journal."
          : res.message || "Saved locally (browser)."
      );
    },
    onError: (err) => {
      setStatus(err instanceof Error ? err.message : "Failed to save bet");
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Parameters<typeof updateJournalEntry>[1] }) =>
      updateJournalEntry(id, patch),
    onSuccess: (res) => {
      invalidate();
      setEditing(null);
      setStatus(
        res.mode === "supabase"
          ? "Bet updated in Supabase."
          : res.message || "Updated locally."
      );
    },
    onError: (err) => {
      setStatus(err instanceof Error ? err.message : "Failed to update bet");
    },
  });

  const deleteMutation = useMutation({
    mutationFn: deleteJournalEntry,
    onSuccess: (res) => {
      invalidate();
      if (editing) setEditing(null);
      setStatus(
        res.mode === "supabase"
          ? "Bet deleted from Supabase."
          : res.message || "Deleted locally."
      );
    },
    onError: (err) => {
      setStatus(err instanceof Error ? err.message : "Failed to delete bet");
    },
  });

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!selected) {
      setStatus("Select a match first.");
      return;
    }
    const edge =
      selected.edges.find((ed) => ed.outcome === outcome) ?? selected.best_edge;
    saveMutation.mutate({
      match_id: selected.id,
      match_label: `${selected.home_team} vs ${selected.away_team}`,
      outcome,
      odds,
      stake,
      units,
      consensus_prob: edge.probability,
      ev_pct: edge.ev_pct,
      kelly_pct: edge.kelly_pct,
    });
  };

  const startEdit = (row: BetJournalEntry) => {
    setEditing(row);
    setEditOdds(Number(row.odds));
    setEditStake(Number(row.stake));
    setEditUnits(Number(row.units ?? row.stake));
    setEditResult(row.result);
  };

  const saveEdit = () => {
    if (!editing) return;
    updateMutation.mutate({
      id: editing.id,
      patch: {
        odds: editOdds,
        stake: editStake,
        units: editUnits,
        result: editResult,
      },
    });
  };

  const entries = journalQuery.data?.entries ?? [];
  const mode = journalQuery.data?.mode;

  const settledPnL = useMemo(() => {
    return entries.reduce((sum, e) => sum + (e.profit != null ? Number(e.profit) : 0), 0);
  }, [entries]);

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <BookMarked className="h-4 w-4 text-emerald-400" />
            <CardTitle>Bet Journal</CardTitle>
          </div>
          {entries.length > 0 && (
            <Badge variant={settledPnL >= 0 ? "positive" : "negative"}>
              P&amp;L {formatCurrency(settledPnL)}
            </Badge>
          )}
        </div>
        <CardDescription>
          Add, update odds/result, and delete bets
          {mode === "supabase"
            ? " — synced to Supabase bet_journal (RLS)"
            : " — local until Supabase auth is connected"}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <form
          onSubmit={onSubmit}
          className="grid gap-3 sm:grid-cols-2 lg:grid-cols-6"
        >
          <div className="space-y-1.5 sm:col-span-2 lg:col-span-2">
            <Label>Match</Label>
            <Select
              value={matchId || undefined}
              onValueChange={applyMatchDefaults}
              disabled={matches.length === 0}
            >
              <SelectTrigger>
                <SelectValue placeholder="Select fixture" />
              </SelectTrigger>
              <SelectContent>
                {matches.map((m) => (
                  <SelectItem key={m.id} value={m.id}>
                    {m.home_team} vs {m.away_team}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label>Pick</Label>
            <Select
              value={outcome}
              onValueChange={(v) => setOutcome(v as Outcome)}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(["home", "draw", "away"] as Outcome[]).map((o) => (
                  <SelectItem key={o} value={o}>
                    {OUTCOME_LABELS[o]}
                    {selected
                      ? ` · ${
                          o === "home"
                            ? selected.home_team
                            : o === "away"
                              ? selected.away_team
                              : "Draw"
                        }`
                      : ""}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label>Odds</Label>
            <Input
              type="number"
              min={1.01}
              step={0.01}
              value={odds}
              onChange={(e) => setOdds(Number(e.target.value))}
            />
          </div>
          <div className="space-y-1.5">
            <Label>Stake</Label>
            <Input
              type="number"
              min={0.01}
              step={0.5}
              value={stake}
              onChange={(e) => setStake(Number(e.target.value))}
            />
          </div>
          <div className="space-y-1.5">
            <Label>Units</Label>
            <div className="flex gap-2">
              <Input
                type="number"
                min={0.01}
                step={0.25}
                value={units}
                onChange={(e) => setUnits(Number(e.target.value))}
              />
              <Button type="submit" disabled={saveMutation.isPending || !matchId}>
                {saveMutation.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  "Add"
                )}
              </Button>
            </div>
          </div>
        </form>

        {selected && (
          <div className="flex flex-wrap gap-2 text-[11px] text-zinc-500">
            <span>
              Consensus p=
              {(
                (selected.edges.find((e) => e.outcome === outcome) ??
                  selected.best_edge
                ).probability * 100
              ).toFixed(1)}
              %
            </span>
            <span>·</span>
            <span>
              Model EV{" "}
              {formatEv(
                (selected.edges.find((e) => e.outcome === outcome) ??
                  selected.best_edge
                ).ev_pct
              )}
            </span>
            <span>·</span>
            <span>
              Kelly{" "}
              {(
                selected.edges.find((e) => e.outcome === outcome) ??
                selected.best_edge
              ).kelly_pct.toFixed(2)}
              %
            </span>
          </div>
        )}

        {status && <p className="text-xs text-zinc-400">{status}</p>}
        {journalQuery.data?.message && mode === "local" && (
          <p className="text-xs text-amber-400/90">{journalQuery.data.message}</p>
        )}

        {editing && (
          <div className="rounded-lg border border-zinc-700 bg-zinc-900/60 p-4">
            <div className="mb-3 flex items-center justify-between gap-2">
              <div>
                <div className="text-sm font-medium text-zinc-100">
                  Edit bet
                </div>
                <div className="text-xs text-zinc-500">
                  {editing.match_label || editing.match_id || "Manual entry"}
                </div>
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setEditing(null)}
              >
                Cancel
              </Button>
            </div>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
              <div className="space-y-1.5">
                <Label>Odds</Label>
                <Input
                  type="number"
                  min={1.01}
                  step={0.01}
                  value={editOdds}
                  onChange={(e) => setEditOdds(Number(e.target.value))}
                />
              </div>
              <div className="space-y-1.5">
                <Label>Stake</Label>
                <Input
                  type="number"
                  min={0.01}
                  step={0.5}
                  value={editStake}
                  onChange={(e) => setEditStake(Number(e.target.value))}
                />
              </div>
              <div className="space-y-1.5">
                <Label>Units</Label>
                <Input
                  type="number"
                  min={0.01}
                  step={0.25}
                  value={editUnits}
                  onChange={(e) => setEditUnits(Number(e.target.value))}
                />
              </div>
              <div className="space-y-1.5">
                <Label>Result</Label>
                <Select
                  value={editResult}
                  onValueChange={(v) => setEditResult(v as BetResult)}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {RESULT_OPTIONS.map((r) => (
                      <SelectItem key={r} value={r}>
                        {r}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="flex items-end">
                <Button
                  className="w-full"
                  onClick={saveEdit}
                  disabled={updateMutation.isPending}
                >
                  {updateMutation.isPending ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    "Save changes"
                  )}
                </Button>
              </div>
            </div>
          </div>
        )}

        <div className="overflow-hidden rounded-lg border border-zinc-800">
          {journalQuery.isLoading ? (
            <div className="space-y-2 p-4">
              <Skeleton className="h-8 w-full" />
              <Skeleton className="h-8 w-full" />
              <Skeleton className="h-8 w-3/4" />
            </div>
          ) : entries.length === 0 ? (
            <EmptyState
              title="No bets logged yet"
              description="Pick a fixture, set stake/units and odds, then hit Add."
              className="py-8"
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[760px] text-left text-sm">
                <thead className="bg-zinc-900/90 text-[11px] uppercase tracking-wider text-zinc-500">
                  <tr>
                    <th className="px-3 py-2 font-medium">Match</th>
                    <th className="px-3 py-2 font-medium">Pick</th>
                    <th className="px-3 py-2 font-medium">Odds</th>
                    <th className="px-3 py-2 font-medium">Stake</th>
                    <th className="px-3 py-2 font-medium">Units</th>
                    <th className="px-3 py-2 font-medium">EV</th>
                    <th className="px-3 py-2 font-medium">Result</th>
                    <th className="px-3 py-2 font-medium">P&amp;L</th>
                    <th className="px-3 py-2 font-medium">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-800/80">
                  {entries.map((row) => (
                    <tr key={row.id} className="hover:bg-zinc-900/50">
                      <td className="px-3 py-2.5 text-zinc-300">
                        {row.match_label || row.match_id || "—"}
                      </td>
                      <td className="px-3 py-2.5 capitalize text-zinc-200">
                        {row.outcome}
                      </td>
                      <td className="px-3 py-2.5 font-mono text-zinc-300">
                        {formatOdds(Number(row.odds))}
                      </td>
                      <td className="px-3 py-2.5 font-mono text-zinc-300">
                        {formatCurrency(Number(row.stake))}
                      </td>
                      <td className="px-3 py-2.5 font-mono text-zinc-300">
                        {Number(row.units ?? row.stake).toFixed(2)}u
                      </td>
                      <td className="px-3 py-2.5">
                        <Badge
                          variant={
                            Number(row.ev_pct) > 0 ? "positive" : "negative"
                          }
                        >
                          {formatEv(Number(row.ev_pct))}
                        </Badge>
                      </td>
                      <td className="px-3 py-2.5">
                        <Select
                          value={row.result}
                          onValueChange={(v) =>
                            updateMutation.mutate({
                              id: row.id,
                              patch: { result: v as BetResult },
                            })
                          }
                          disabled={updateMutation.isPending}
                        >
                          <SelectTrigger className="h-8 w-[110px] capitalize">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {RESULT_OPTIONS.map((r) => (
                              <SelectItem key={r} value={r} className="capitalize">
                                {r}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </td>
                      <td className="px-3 py-2.5 font-mono text-sm">
                        {row.profit == null ? (
                          <span className="text-zinc-600">—</span>
                        ) : (
                          <span
                            className={
                              Number(row.profit) >= 0
                                ? "text-emerald-400"
                                : "text-rose-400"
                            }
                          >
                            {formatCurrency(Number(row.profit))}
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2.5">
                        <div className="flex items-center gap-1">
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8 text-zinc-400 hover:text-zinc-100"
                            onClick={() => startEdit(row)}
                            title="Edit odds / stake / result"
                          >
                            <Pencil className="h-3.5 w-3.5" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8 text-zinc-400 hover:text-rose-400"
                            disabled={deleteMutation.isPending}
                            onClick={() => {
                              if (
                                typeof window !== "undefined" &&
                                window.confirm("Delete this bet from your journal?")
                              ) {
                                deleteMutation.mutate(row.id);
                              }
                            }}
                            title="Delete bet"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
