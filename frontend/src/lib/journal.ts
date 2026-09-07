import type { BetJournalEntry, BetResult, Outcome } from "@/types/betting";
import { ensureJournalSession, getSupabase, isSupabaseConfigured } from "@/lib/supabase";

const LOCAL_KEY = "betconsensus.bet_journal";

export type JournalDraft = {
  match_id?: string | null;
  match_label?: string | null;
  outcome: Outcome;
  odds: number;
  stake: number;
  units?: number;
  consensus_prob: number;
  ev_pct: number;
  kelly_pct: number;
};

export type JournalUpdate = {
  odds?: number;
  stake?: number;
  units?: number | null;
  outcome?: Outcome;
  result?: BetResult;
  profit?: number | null;
  match_label?: string | null;
};

function readLocal(): BetJournalEntry[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(LOCAL_KEY);
    if (!raw) return [];
    return JSON.parse(raw) as BetJournalEntry[];
  } catch {
    return [];
  }
}

function writeLocal(entries: BetJournalEntry[]) {
  localStorage.setItem(LOCAL_KEY, JSON.stringify(entries.slice(0, 100)));
}

function upsertLocal(entry: BetJournalEntry) {
  const next = readLocal().filter((e) => e.id !== entry.id);
  next.unshift(entry);
  writeLocal(next);
}

function removeLocal(id: string) {
  writeLocal(readLocal().filter((e) => e.id !== id));
}

/** Settle P&L from result + stake + odds. */
export function computeProfit(
  result: BetResult,
  stake: number,
  odds: number
): number | null {
  if (result === "pending") return null;
  if (result === "push") return 0;
  if (result === "win") return Number((stake * (odds - 1)).toFixed(2));
  return Number((-stake).toFixed(2));
}

async function requireSession(): Promise<{
  userId: string | null;
  mode: "supabase" | "local";
  message?: string;
}> {
  return ensureJournalSession();
}

export async function listJournalEntries(): Promise<{
  entries: BetJournalEntry[];
  mode: "supabase" | "local";
  message?: string;
}> {
  const session = await requireSession();
  if (session.mode === "local" || !session.userId) {
    return {
      entries: readLocal().sort(
        (a, b) =>
          new Date(b.placed_at).getTime() - new Date(a.placed_at).getTime()
      ),
      mode: "local",
      message: session.message,
    };
  }

  const supabase = getSupabase()!;
  const { data, error } = await supabase
    .from("bet_journal")
    .select("*")
    .eq("user_id", session.userId)
    .order("placed_at", { ascending: false })
    .limit(100);

  if (error) {
    return {
      entries: readLocal(),
      mode: "local",
      message: `Supabase read failed (${error.message}) — showing local journal.`,
    };
  }

  // Mirror cloud → local for offline resilience.
  const entries = (data || []) as BetJournalEntry[];
  writeLocal(entries);
  return { entries, mode: "supabase" };
}

export async function createJournalEntry(draft: JournalDraft): Promise<{
  entry: BetJournalEntry;
  mode: "supabase" | "local";
  message?: string;
}> {
  const session = await requireSession();
  const placed_at = new Date().toISOString();
  const units = draft.units ?? draft.stake;
  const localEntry: BetJournalEntry = {
    id: crypto.randomUUID(),
    user_id: session.userId,
    match_id: draft.match_id ?? null,
    match_label: draft.match_label ?? null,
    outcome: draft.outcome,
    odds: draft.odds,
    stake: draft.stake,
    units,
    consensus_prob: draft.consensus_prob,
    ev_pct: draft.ev_pct,
    kelly_pct: draft.kelly_pct,
    result: "pending",
    profit: null,
    placed_at,
  };

  upsertLocal(localEntry);

  if (session.mode === "local" || !session.userId || !isSupabaseConfigured) {
    return { entry: localEntry, mode: "local", message: session.message };
  }

  const supabase = getSupabase()!;
  const payload: Record<string, unknown> = {
    user_id: session.userId,
    match_id: draft.match_id || null,
    match_label: draft.match_label || null,
    outcome: draft.outcome,
    odds: draft.odds,
    stake: draft.stake,
    units,
    consensus_prob: draft.consensus_prob,
    ev_pct: draft.ev_pct,
    kelly_pct: draft.kelly_pct,
    result: "pending",
  };

  let { data, error } = await supabase
    .from("bet_journal")
    .insert(payload)
    .select("*")
    .single();

  // Demo FastAPI match IDs often aren't in Supabase yet — retry without FK.
  if (error && payload.match_id) {
    const retry = await supabase
      .from("bet_journal")
      .insert({ ...payload, match_id: null })
      .select("*")
      .single();
    data = retry.data;
    error = retry.error;
  }

  // match_label / units columns may be missing pre-migration 003.
  if (error && /match_label|units/i.test(error.message)) {
    const legacy = { ...payload };
    delete legacy.match_label;
    delete legacy.units;
    const retry = await supabase
      .from("bet_journal")
      .insert({ ...legacy, match_id: null })
      .select("*")
      .single();
    data = retry.data;
    error = retry.error;
  }

  if (error) {
    return {
      entry: localEntry,
      mode: "local",
      message: `Supabase insert failed (${error.message}) — saved locally.`,
    };
  }

  const entry = data as BetJournalEntry;
  upsertLocal(entry);
  return { entry, mode: "supabase" };
}

export async function updateJournalEntry(
  id: string,
  patch: JournalUpdate
): Promise<{
  entry: BetJournalEntry;
  mode: "supabase" | "local";
  message?: string;
}> {
  const session = await requireSession();
  const existing =
    readLocal().find((e) => e.id === id) ||
    (await listJournalEntries()).entries.find((e) => e.id === id);

  if (!existing) {
    throw new Error("Bet not found");
  }

  const nextOdds = patch.odds ?? Number(existing.odds);
  const nextStake = patch.stake ?? Number(existing.stake);
  const nextResult = patch.result ?? existing.result;
  const profit =
    patch.profit !== undefined
      ? patch.profit
      : computeProfit(nextResult, nextStake, nextOdds);

  const merged: BetJournalEntry = {
    ...existing,
    ...patch,
    odds: nextOdds,
    stake: nextStake,
    result: nextResult,
    profit,
  };
  upsertLocal(merged);

  if (session.mode === "local" || !session.userId || !isSupabaseConfigured) {
    return { entry: merged, mode: "local", message: session.message };
  }

  const supabase = getSupabase()!;
  const payload: Record<string, unknown> = {
    odds: nextOdds,
    stake: nextStake,
    result: nextResult,
    profit,
  };
  if (patch.units !== undefined) payload.units = patch.units;
  if (patch.outcome !== undefined) payload.outcome = patch.outcome;
  if (patch.match_label !== undefined) payload.match_label = patch.match_label;

  const { data, error } = await supabase
    .from("bet_journal")
    .update(payload)
    .eq("id", id)
    .eq("user_id", session.userId)
    .select("*")
    .single();

  if (error) {
    // Still keep local write; surface soft failure.
    return {
      entry: merged,
      mode: "local",
      message: `Supabase update failed (${error.message}) — updated locally.`,
    };
  }

  const entry = data as BetJournalEntry;
  upsertLocal(entry);
  return { entry, mode: "supabase" };
}

export async function deleteJournalEntry(id: string): Promise<{
  mode: "supabase" | "local";
  message?: string;
}> {
  const session = await requireSession();
  removeLocal(id);

  if (session.mode === "local" || !session.userId || !isSupabaseConfigured) {
    return { mode: "local", message: session.message };
  }

  const supabase = getSupabase()!;
  const { error } = await supabase
    .from("bet_journal")
    .delete()
    .eq("id", id)
    .eq("user_id", session.userId);

  if (error) {
    return {
      mode: "local",
      message: `Supabase delete failed (${error.message}) — removed locally.`,
    };
  }

  return { mode: "supabase" };
}
