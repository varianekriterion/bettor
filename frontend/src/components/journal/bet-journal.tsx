"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookMarked, Check, ImagePlus, Loader2, Pencil, RotateCcw, Trash2, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AuthDialog } from "@/components/auth/auth-dialog";
import { useAuth } from "@/contexts/auth-context";
import { fetchJournalStatus, postParseSlip } from "@/lib/api";
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
import { ConfirmDialog } from "@/components/ui/confirm-dialog";

type Props = {
  matches: MatchCard[];
};

const RESULT_OPTIONS: BetResult[] = ["pending", "win", "loss", "push"];
const MAX_SLIP_IMAGES = 10;
const OCR_CONCURRENCY = 2;

type SlipStatus = "draft" | "parsing" | "done" | "error";

type SlipQueueItem = {
  id: string;
  preview: string;
  status: SlipStatus;
  label?: string;
  error?: string;
};

function readImageFile(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(new Error("Failed to read image"));
    reader.readAsDataURL(file);
  });
}

/** Shrink screenshots before OCR — large base64 payloads slow uploads to a crawl. */
async function compressImage(dataUrl: string, maxWidth = 1200): Promise<string> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      const scale = Math.min(1, maxWidth / img.width);
      const w = Math.round(img.width * scale);
      const h = Math.round(img.height * scale);
      const canvas = document.createElement("canvas");
      canvas.width = w;
      canvas.height = h;
      const ctx = canvas.getContext("2d");
      if (!ctx) {
        resolve(dataUrl);
        return;
      }
      ctx.drawImage(img, 0, 0, w, h);
      resolve(canvas.toDataURL("image/jpeg", 0.85));
    };
    img.onerror = () => reject(new Error("Failed to compress image"));
    img.src = dataUrl;
  });
}

export function BetJournal({ matches }: Props) {
  const qc = useQueryClient();
  const { user, loading: authLoading, configured: authConfigured } = useAuth();
  const [authDialogOpen, setAuthDialogOpen] = useState(false);
  const journalQuery = useQuery({
    queryKey: ["bet-journal"],
    queryFn: listJournalEntries,
  });
  const statusQuery = useQuery({
    queryKey: ["journal-status"],
    queryFn: fetchJournalStatus,
    staleTime: 60_000,
  });

  const [matchId, setMatchId] = useState<string>("");
  const [matchLabel, setMatchLabel] = useState("");
  const [outcome, setOutcome] = useState<Outcome>("home");
  const [odds, setOdds] = useState(2.0);
  const [stake, setStake] = useState(25);
  const [units, setUnits] = useState(1);
  const [status, setStatus] = useState<string | null>(null);
  const [editing, setEditing] = useState<BetJournalEntry | null>(null);
  const [editMatchLabel, setEditMatchLabel] = useState("");
  const [editOutcome, setEditOutcome] = useState<Outcome>("home");
  const [editOdds, setEditOdds] = useState(2);
  const [editStake, setEditStake] = useState(25);
  const [editUnits, setEditUnits] = useState(1);
  const [editResult, setEditResult] = useState<BetResult>("pending");
  const [slipItems, setSlipItems] = useState<SlipQueueItem[]>([]);
  const [slipDragOver, setSlipDragOver] = useState(false);
  const [deleteTargetId, setDeleteTargetId] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const processingRef = useRef(false);
  const abortControllersRef = useRef<Map<string, AbortController>>(new Map());

  const selected = useMemo(
    () => matches.find((m) => m.id === matchId) ?? null,
    [matches, matchId]
  );

  const applyMatchDefaults = (id: string) => {
    setMatchId(id);
    const m = matches.find((x) => x.id === id);
    if (!m) return;
    setMatchLabel(`${m.home_team} vs ${m.away_team}`);
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

  useEffect(() => {
    if (!authLoading) invalidate();
  }, [user?.id, authLoading]);

  const draftSlips = slipItems.filter((item) => item.status === "draft");
  const slipParsing = slipItems.some((item) => item.status === "parsing");
  const slipSlotsLeft = MAX_SLIP_IMAGES - slipItems.length;
  const ocrReady = statusQuery.data?.ocr_ready ?? true;

  const updateSlipItem = useCallback((id: string, patch: Partial<SlipQueueItem>) => {
    setSlipItems((prev) => prev.map((item) => (item.id === id ? { ...item, ...patch } : item)));
  }, []);

  const cancelSlipItem = useCallback((id: string) => {
    abortControllersRef.current.get(id)?.abort();
    abortControllersRef.current.delete(id);
    setSlipItems((prev) => prev.filter((item) => item.id !== id));
  }, []);

  const parseOneSlip = useCallback(
    async (item: SlipQueueItem): Promise<{ ok: true; label: string } | { ok: false; error: string }> => {
      if (!user?.id) {
        return { ok: false, error: "Sign in to parse slips with OCR." };
      }
      if (!ocrReady) {
        return { ok: false, error: "OCR unavailable — set OPENAI_API_KEY on the backend." };
      }

      const controller = new AbortController();
      abortControllersRef.current.set(item.id, controller);
      updateSlipItem(item.id, { status: "parsing", error: undefined });

      try {
        const compressed = await compressImage(item.preview);
        const entry = await postParseSlip(
          { image_base64: compressed, user_id: user.id },
          controller.signal
        );
        const stakeLabel = Number(entry.stake).toFixed(2);
        const label = entry.ocr_applied
          ? `${entry.match_label || "bet"} · ${entry.outcome} @ ${Number(entry.odds).toFixed(2)} · $${stakeLabel}`
          : `${entry.match_label || "bet"} @ ${Number(entry.odds).toFixed(2)}`;
        return { ok: true, label };
      } catch (err) {
        if (controller.signal.aborted) {
          return { ok: false, error: "Cancelled" };
        }
        const msg =
          err instanceof Error ? err.message : "OCR failed — edit the bet manually in the table.";
        return { ok: false, error: msg };
      } finally {
        abortControllersRef.current.delete(item.id);
      }
    },
    [ocrReady, updateSlipItem, user?.id]
  );

  const processSlipBatch = useCallback(async () => {
    if (processingRef.current || authLoading) return;

    const toProcess = slipItems.filter((item) => item.status === "draft" || item.status === "error");
    if (toProcess.length === 0) return;

    if (!user?.id) {
      setAuthDialogOpen(true);
      setStatus("Sign in to parse and save slip screenshots.");
      return;
    }

    processingRef.current = true;
    setStatus(null);

    let savedCount = 0;
    let errorCount = 0;

    try {
      for (let i = 0; i < toProcess.length; i += OCR_CONCURRENCY) {
        const batch = toProcess.slice(i, i + OCR_CONCURRENCY);
        const results = await Promise.all(
          batch.map(async (item) => {
            const result = await parseOneSlip(item);
            if (result.ok) {
              updateSlipItem(item.id, { status: "done", label: result.label, error: undefined });
              return "saved" as const;
            }
            if (result.error === "Cancelled") {
              return "cancelled" as const;
            }
            updateSlipItem(item.id, { status: "error", error: result.error });
            return "error" as const;
          })
        );
        savedCount += results.filter((r) => r === "saved").length;
        errorCount += results.filter((r) => r === "error").length;
      }

      if (savedCount > 0) {
        invalidate();
      }

      if (savedCount > 0 && errorCount === 0) {
        setStatus(
          savedCount === 1
            ? "Slip parsed and saved to your journal."
            : `${savedCount} slips parsed and saved to your journal.`
        );
      } else if (savedCount > 0 && errorCount > 0) {
        setStatus(`${savedCount} saved, ${errorCount} failed — retry or edit manually.`);
      } else if (errorCount > 0) {
        setStatus(`${errorCount} slip(s) failed — check errors below or add bets manually.`);
      }
    } finally {
      processingRef.current = false;
    }
  }, [authLoading, parseOneSlip, slipItems, updateSlipItem, user?.id]);

  const addSlipFiles = useCallback(
    async (files: FileList | File[]) => {
      const imageFiles = Array.from(files).filter((f) => f.type.startsWith("image/"));
      if (imageFiles.length === 0) {
        setStatus("Only image files (PNG, JPEG, etc.) are supported.");
        return;
      }

      const available = MAX_SLIP_IMAGES - slipItems.length;
      if (available <= 0) {
        setStatus(`Maximum ${MAX_SLIP_IMAGES} slips at a time — remove one to add more.`);
        return;
      }

      const toAdd = imageFiles.slice(0, available);
      if (imageFiles.length > available) {
        setStatus(`Added ${available} of ${imageFiles.length} — max ${MAX_SLIP_IMAGES} at a time.`);
      } else {
        setStatus(null);
      }

      const newItems: SlipQueueItem[] = [];
      for (const file of toAdd) {
        try {
          const raw = await readImageFile(file);
          const preview = await compressImage(raw);
          newItems.push({
            id: crypto.randomUUID(),
            preview,
            status: "draft",
          });
        } catch {
          setStatus(`Failed to read ${file.name}.`);
        }
      }

      if (newItems.length === 0) return;
      setSlipItems((prev) => [...prev, ...newItems]);
    },
    [slipItems.length]
  );

  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => {
      const items = e.clipboardData?.items;
      if (!items) return;
      const imageFiles: File[] = [];
      for (const item of items) {
        if (item.type.startsWith("image/")) {
          const file = item.getAsFile();
          if (file) imageFiles.push(file);
        }
      }
      if (imageFiles.length > 0) {
        e.preventDefault();
        void addSlipFiles(imageFiles);
      }
    };
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, [addSlipFiles]);

  const onSlipFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (files?.length) void addSlipFiles(files);
    e.target.value = "";
  };

  const onSlipDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setSlipDragOver(false);
    const files = e.dataTransfer.files;
    if (files?.length) void addSlipFiles(files);
  };

  const saveMutation = useMutation({
    mutationFn: createJournalEntry,
    onSuccess: (res) => {
      invalidate();
      setStatus(
        res.mode === "supabase"
          ? "Bet added to your journal."
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
          ? "Bet updated."
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
          ? "Bet deleted."
          : res.message || "Deleted locally."
      );
    },
    onError: (err) => {
      setStatus(err instanceof Error ? err.message : "Failed to delete bet");
    },
  });

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const label =
      matchLabel.trim() ||
      (selected ? `${selected.home_team} vs ${selected.away_team}` : "");
    if (!label) {
      setStatus("Enter a match name or select a fixture.");
      return;
    }
    const edge = selected
      ? selected.edges.find((ed) => ed.outcome === outcome) ?? selected.best_edge
      : null;
    saveMutation.mutate({
      match_id: selected?.id ?? null,
      match_label: label,
      outcome,
      odds,
      stake,
      units,
      consensus_prob: edge?.probability ?? 0,
      ev_pct: edge?.ev_pct ?? 0,
      kelly_pct: edge?.kelly_pct ?? 0,
    });
  };

  const startEdit = (row: BetJournalEntry) => {
    setEditing(row);
    setEditMatchLabel(row.match_label || row.match_id || "");
    setEditOutcome(row.outcome);
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
        match_label: editMatchLabel.trim() || null,
        outcome: editOutcome,
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

  const processableCount = slipItems.filter(
    (item) => item.status === "draft" || item.status === "error"
  ).length;

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
          Log bets manually or batch-upload slip screenshots
          {user
            ? " — synced to Supabase"
            : authConfigured
              ? " — sign in to sync across devices"
              : " — local until Supabase is configured"}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        {!authLoading && authConfigured && !user && (
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-amber-500/30 bg-amber-950/20 px-4 py-3">
            <p className="text-sm text-amber-100/90">
              Sign in to save bets and parse slip screenshots with OCR.
            </p>
            <Button size="sm" className="h-8 shrink-0" onClick={() => setAuthDialogOpen(true)}>
              Sign in
            </Button>
          </div>
        )}

        {!ocrReady && statusQuery.isSuccess && (
          <p className="text-xs text-amber-400/90">
            Slip OCR is offline — add OPENAI_API_KEY to the backend. You can still log bets manually.
          </p>
        )}

        <AuthDialog open={authDialogOpen} onOpenChange={setAuthDialogOpen} />
        <ConfirmDialog
          open={deleteTargetId !== null}
          onOpenChange={(open) => {
            if (!open) setDeleteTargetId(null);
          }}
          title="Delete bet?"
          description="This bet will be permanently removed from your journal."
          confirmLabel="Delete"
          cancelLabel="Cancel"
          variant="danger"
          loading={deleteMutation.isPending}
          onConfirm={() => {
            if (deleteTargetId) deleteMutation.mutate(deleteTargetId);
          }}
        />

        <div
          onDragOver={(e) => {
            e.preventDefault();
            setSlipDragOver(true);
          }}
          onDragLeave={() => setSlipDragOver(false)}
          onDrop={onSlipDrop}
          className={`rounded-lg border border-dashed px-4 py-4 transition-colors ${
            slipDragOver
              ? "border-emerald-400/70 bg-emerald-950/30"
              : "border-zinc-700 bg-zinc-900/40"
          }`}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            multiple
            className="hidden"
            onChange={onSlipFileChange}
          />

          {slipItems.length > 0 && (
            <div className="mb-4 flex flex-wrap gap-3">
              {slipItems.map((item) => (
                <div
                  key={item.id}
                  className="group relative h-28 w-24 shrink-0 overflow-hidden rounded-md border border-zinc-700 bg-zinc-950"
                >
                  <img
                    src={item.preview}
                    alt="Bet slip preview"
                    className="h-full w-full object-cover object-top"
                  />
                  {item.status === "parsing" && (
                    <div className="absolute inset-0 flex flex-col items-center justify-center gap-1 bg-black/70">
                      <Loader2 className="h-5 w-5 animate-spin text-emerald-400" />
                      <span className="text-[9px] text-zinc-300">Parsing…</span>
                    </div>
                  )}
                  {item.status === "done" && (
                    <div className="absolute inset-x-0 bottom-0 bg-emerald-950/95 px-1 py-0.5">
                      <div className="flex items-center gap-0.5">
                        <Check className="h-3 w-3 shrink-0 text-emerald-400" />
                        <span className="truncate text-[9px] leading-tight text-emerald-100">
                          {item.label || "Saved"}
                        </span>
                      </div>
                    </div>
                  )}
                  {item.status === "error" && (
                    <div className="absolute inset-x-0 bottom-0 bg-rose-950/95 px-1 py-0.5">
                      <span className="line-clamp-2 text-[9px] leading-tight text-rose-200">
                        {item.error || "Failed"}
                      </span>
                    </div>
                  )}
                  {item.status === "draft" && (
                    <div className="absolute inset-x-0 bottom-0 bg-zinc-900/90 px-1 py-0.5">
                      <span className="text-[9px] text-zinc-400">Ready</span>
                    </div>
                  )}
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      cancelSlipItem(item.id);
                    }}
                    className="absolute right-0.5 top-0.5 flex h-5 w-5 items-center justify-center rounded-full bg-zinc-900/90 text-zinc-300 shadow hover:bg-rose-900 hover:text-rose-200"
                    aria-label="Remove slip image"
                  >
                    <X className="h-3 w-3" />
                  </button>
                  {item.status === "error" && !slipParsing && (
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        updateSlipItem(item.id, { status: "draft", error: undefined });
                      }}
                      className="absolute bottom-0.5 right-0.5 flex h-5 w-5 items-center justify-center rounded-full bg-zinc-900/90 text-zinc-300 shadow hover:bg-emerald-900 hover:text-emerald-200"
                      aria-label="Retry slip"
                    >
                      <RotateCcw className="h-3 w-3" />
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}

          <div
            role="button"
            tabIndex={0}
            onClick={() => {
              if (slipSlotsLeft > 0) fileInputRef.current?.click();
            }}
            onKeyDown={(e) => {
              if ((e.key === "Enter" || e.key === " ") && slipSlotsLeft > 0) {
                fileInputRef.current?.click();
              }
            }}
            className={`flex min-h-[72px] flex-col items-center justify-center gap-2 text-center ${
              slipSlotsLeft > 0 ? "cursor-pointer hover:opacity-90" : "cursor-not-allowed opacity-60"
            }`}
          >
            <ImagePlus className="h-6 w-6 text-zinc-500" />
            <p className="text-sm text-zinc-300">
              Paste slip screenshots (Ctrl+V) or click to upload
            </p>
            <p className="text-[11px] text-zinc-500">
              Add up to {MAX_SLIP_IMAGES}, then click Process — GPT-4o vision extracts match, pick,
              odds &amp; stake
              {slipItems.length > 0 && (
                <span className="text-zinc-400">
                  {" "}
                  · {slipItems.length}/{MAX_SLIP_IMAGES} added
                  {draftSlips.length > 0 && ` · ${draftSlips.length} ready`}
                </span>
              )}
            </p>
          </div>

          {slipItems.length > 0 && (
            <div className="mt-3 flex flex-wrap justify-end gap-2">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-7 text-xs text-zinc-400"
                disabled={slipParsing}
                onClick={() => {
                  abortControllersRef.current.forEach((c) => c.abort());
                  abortControllersRef.current.clear();
                  setSlipItems([]);
                }}
              >
                Clear all
              </Button>
              <Button
                type="button"
                size="sm"
                className="h-7 text-xs"
                disabled={slipParsing || processableCount === 0}
                onClick={() => void processSlipBatch()}
              >
                {slipParsing ? (
                  <>
                    <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                    Processing…
                  </>
                ) : (
                  `Process ${processableCount} slip${processableCount === 1 ? "" : "s"}`
                )}
              </Button>
            </div>
          )}
        </div>

        <form onSubmit={onSubmit} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-7">
          <div className="space-y-1.5 sm:col-span-2">
            <Label>Match name</Label>
            <Input
              placeholder="e.g. Arsenal vs Chelsea"
              value={matchLabel}
              onChange={(e) => setMatchLabel(e.target.value)}
            />
          </div>
          <div className="space-y-1.5 sm:col-span-2">
            <Label>Fixture (optional)</Label>
            <Select
              value={matchId || undefined}
              onValueChange={applyMatchDefaults}
              disabled={matches.length === 0}
            >
              <SelectTrigger>
                <SelectValue placeholder="Link to fixture" />
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
            <Select value={outcome} onValueChange={(v) => setOutcome(v as Outcome)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(["home", "draw", "away"] as Outcome[]).map((o) => (
                  <SelectItem key={o} value={o}>
                    {OUTCOME_LABELS[o]}
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
              <Button type="submit" disabled={saveMutation.isPending}>
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
                (selected.edges.find((e) => e.outcome === outcome) ?? selected.best_edge)
                  .probability * 100
              ).toFixed(1)}
              %
            </span>
            <span>·</span>
            <span>
              Model EV{" "}
              {formatEv(
                (selected.edges.find((e) => e.outcome === outcome) ?? selected.best_edge).ev_pct
              )}
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
              <div className="text-sm font-medium text-zinc-100">Edit bet</div>
              <Button variant="ghost" size="sm" onClick={() => setEditing(null)}>
                Cancel
              </Button>
            </div>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <div className="space-y-1.5 sm:col-span-2">
                <Label>Match name</Label>
                <Input
                  value={editMatchLabel}
                  onChange={(e) => setEditMatchLabel(e.target.value)}
                  placeholder="e.g. Arsenal vs Chelsea"
                />
              </div>
              <div className="space-y-1.5">
                <Label>Pick</Label>
                <Select
                  value={editOutcome}
                  onValueChange={(v) => setEditOutcome(v as Outcome)}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {(["home", "draw", "away"] as Outcome[]).map((o) => (
                      <SelectItem key={o} value={o}>
                        {OUTCOME_LABELS[o]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
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
              <div className="flex items-end sm:col-span-2">
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
              description="Upload slips and click Process, or add a bet manually above."
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
                          variant={Number(row.ev_pct) > 0 ? "positive" : "negative"}
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
                            title="Edit bet"
                          >
                            <Pencil className="h-3.5 w-3.5" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8 text-zinc-400 hover:text-rose-400"
                            disabled={deleteMutation.isPending}
                            onClick={() => setDeleteTargetId(row.id)}
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
