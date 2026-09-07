import type {
  AggregatorMatrixRow,
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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
    cache: "no-store",
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `Request failed: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export async function fetchLeagues(): Promise<LeagueInfo[]> {
  return request("/api/v1/leagues");
}

export async function fetchMatches(params?: {
  league?: LeagueKey | "all";
  positiveEvOnly?: boolean;
  bankroll?: number;
}): Promise<MatchCard[]> {
  const q = new URLSearchParams();
  if (params?.league && params.league !== "all") q.set("league", params.league);
  if (params?.positiveEvOnly) q.set("positive_ev_only", "true");
  if (params?.bankroll) q.set("bankroll", String(params.bankroll));
  const qs = q.toString();
  return request(`/api/v1/matches${qs ? `?${qs}` : ""}`);
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

export async function fetchMatrix(league?: LeagueKey | "all"): Promise<AggregatorMatrixRow[]> {
  const q = new URLSearchParams();
  if (league && league !== "all") q.set("league", league);
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

export { API_BASE };
