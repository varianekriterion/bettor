import type { LeagueKey, MatchCard } from "@/types/betting";

const STORAGE_PREFIX = "bettor:matches:v1";
/** Keep local snapshots for 24h — enough to survive overnight tabs. */
const MAX_AGE_MS = 24 * 60 * 60_000;

type CachedMatches = {
  savedAt: number;
  league: LeagueKey | "all";
  positiveEvOnly: boolean;
  data: MatchCard[];
};

function cacheKey(league: LeagueKey | "all", positiveEvOnly: boolean): string {
  return `${STORAGE_PREFIX}:${league}:${positiveEvOnly ? "ev" : "all"}`;
}

export function readMatchesCache(
  league: LeagueKey | "all",
  positiveEvOnly: boolean
): CachedMatches | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(cacheKey(league, positiveEvOnly));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as CachedMatches;
    if (!parsed?.data?.length) return null;
    if (Date.now() - parsed.savedAt > MAX_AGE_MS) {
      localStorage.removeItem(cacheKey(league, positiveEvOnly));
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

export function writeMatchesCache(
  league: LeagueKey | "all",
  positiveEvOnly: boolean,
  data: MatchCard[]
): void {
  if (typeof window === "undefined" || data.length === 0) return;
  try {
    const payload: CachedMatches = {
      savedAt: Date.now(),
      league,
      positiveEvOnly,
      data,
    };
    localStorage.setItem(cacheKey(league, positiveEvOnly), JSON.stringify(payload));
  } catch {
    // Quota exceeded or private mode — ignore.
  }
}
