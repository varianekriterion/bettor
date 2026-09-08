import type {
  AggregatorMatrixRow,
  BetJournalEntry,
  CalculatorRequest,
  CalculatorResponse,
  LeagueInfo,
  LeagueKey,
  LeaguePerformanceSummary,
  MatchCard,
  OddsHistoryResponse,
  Outcome,
  SourcePerformance,
} from "@/types/betting";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") || "http://127.0.0.1:8000";

const DEFAULT_TIMEOUT_MS = 30_000;
/** Match cards fan out odds + xG per fixture; allow headroom on cold cache. */
const MATCHES_TIMEOUT_MS = 90_000;
const OCR_TIMEOUT_MS = 90_000;

async function request<T>(
  path: string,
  init?: RequestInit & { timeoutMs?: number }
): Promise<T> {
  const timeoutMs = init?.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const { timeoutMs: _omit, signal: externalSignal, ...fetchInit } = init ?? {};

  if (externalSignal) {
    if (externalSignal.aborted) controller.abort();
    else externalSignal.addEventListener("abort", () => controller.abort(), { once: true });
  }

  try {
    const res = await fetch(`${API_BASE}${path}`, {
      ...fetchInit,
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        ...(fetchInit.headers || {}),
      },
      cache: "no-store",
    });
    if (!res.ok) {
      const text = await res.text();
      if (res.status === 404) {
        throw new Error(
          "Backend route not found — restart the FastAPI server (uvicorn) to load the journal OCR endpoint."
        );
      }
      throw new Error(text || `Request failed: ${res.status}`);
    }
    return res.json() as Promise<T>;
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new Error(
        `Request timed out after ${Math.round(timeoutMs / 1000)}s — is the backend running at ${API_BASE}?`
      );
    }
    if (err instanceof TypeError) {
      throw new Error(
        `Cannot reach backend at ${API_BASE} — start it with: cd backend && py -m uvicorn app.main:app --reload`
      );
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

export async function fetchLeagues(): Promise<LeagueInfo[]> {
  return request("/api/v1/leagues");
}

export async function fetchMatches(params?: {
  league?: LeagueKey | "all";
  positiveEvOnly?: boolean;
  bankroll?: number;
  todayOnly?: boolean;
  /** Upcoming window in days (UTC). Omit to use server default (7). */
  daysAhead?: number;
}): Promise<MatchCard[]> {
  const q = new URLSearchParams();
  if (params?.league && params.league !== "all") q.set("league", params.league);
  if (params?.positiveEvOnly) q.set("positive_ev_only", "true");
  if (params?.bankroll) q.set("bankroll", String(params.bankroll));
  if (params?.todayOnly) q.set("days_ahead", "1");
  else if (params?.daysAhead !== undefined) q.set("days_ahead", String(params.daysAhead));
  const qs = q.toString();
  return request(`/api/v1/matches${qs ? `?${qs}` : ""}`, {
    timeoutMs: MATCHES_TIMEOUT_MS,
  });
}

export async function fetchOddsHistory(
  matchId: string,
  outcome?: Outcome
): Promise<OddsHistoryResponse> {
  const q = new URLSearchParams();
  if (outcome) q.set("outcome", outcome);
  const qs = q.toString();
  return request(
    `/api/v1/matches/${encodeURIComponent(matchId)}/odds-history${qs ? `?${qs}` : ""}`
  );
}

export async function fetchMatrix(
  league?: LeagueKey | "all",
  daysAhead?: number
): Promise<AggregatorMatrixRow[]> {
  const q = new URLSearchParams();
  if (league && league !== "all") q.set("league", league);
  if (daysAhead !== undefined) q.set("days_ahead", String(daysAhead));
  const qs = q.toString();
  return request(`/api/v1/predictions/matrix${qs ? `?${qs}` : ""}`);
}

export async function postCalculator(body: CalculatorRequest): Promise<CalculatorResponse> {
  return request("/api/v1/calculator", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function fetchPerformance(
  league?: LeagueKey | "all"
): Promise<LeaguePerformanceSummary[]> {
  const q = new URLSearchParams();
  if (league && league !== "all") q.set("league", league);
  const qs = q.toString();
  return request(`/api/v1/performance${qs ? `?${qs}` : ""}`);
}

export async function fetchLeaderboard(): Promise<SourcePerformance[]> {
  return request("/api/v1/performance/leaderboard");
}

export async function fetchJournalStatus(): Promise<{
  ocr_ready: boolean;
  supabase_ready: boolean;
}> {
  return request("/api/v1/journal/status");
}

export async function postParseSlip(
  body: {
    image_base64: string;
    user_id: string;
  },
  signal?: AbortSignal
): Promise<BetJournalEntry> {
  return request("/api/v1/journal/parse-slip", {
    method: "POST",
    body: JSON.stringify(body),
    timeoutMs: OCR_TIMEOUT_MS,
    signal,
  });
}

export { API_BASE };
