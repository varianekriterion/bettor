"use client";

import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  fetchLeaderboard,
  fetchMatches,
  fetchMatrix,
  fetchOddsHistory,
  fetchPerformance,
  postCalculator,
} from "@/lib/api";
import { readMatchesCache, writeMatchesCache } from "@/lib/matches-cache";
import type {
  CalculatorRequest,
  LeagueKey,
  Outcome,
} from "@/types/betting";

export const queryKeys = {
  matches: (league: LeagueKey | "all", positiveEvOnly: boolean) =>
    ["matches", league, positiveEvOnly] as const,
  matrix: (league: LeagueKey | "all") => ["matrix", league] as const,
  performance: (league: LeagueKey | "all") => ["performance", league] as const,
  leaderboard: ["leaderboard"] as const,
  calculator: (input: CalculatorRequest) => ["calculator", input] as const,
  oddsHistory: (matchId: string, outcome?: Outcome) =>
    ["odds-history", matchId, outcome ?? "default"] as const,
};

/** Poll interval for live odds feed (ms). Keep >= backend CACHE_TTL_SECONDS to save API credits. */
const MATCHES_REFETCH_MS = 5 * 60_000;
const MATRIX_REFETCH_MS = 5 * 60_000;
const MATCHES_GC_MS = 30 * 60_000;

async function fetchMatchesWithFallback(
  league: LeagueKey | "all",
  positiveEvOnly: boolean
) {
  const cached = readMatchesCache(league, positiveEvOnly);
  try {
    const data = await fetchMatches({ league, positiveEvOnly });
    if (data.length > 0) {
      writeMatchesCache(league, positiveEvOnly, data);
      return data;
    }
    if (cached?.data.length) return cached.data;
    return data;
  } catch {
    if (cached?.data.length) return cached.data;
    throw new Error(
      `Cannot load fixtures for ${league} — backend unreachable and no saved snapshot.`
    );
  }
}

export function useMatches(
  league: LeagueKey | "all",
  positiveEvOnly: boolean,
  options?: { enabled?: boolean }
) {
  return useQuery({
    queryKey: queryKeys.matches(league, positiveEvOnly),
    queryFn: () => fetchMatchesWithFallback(league, positiveEvOnly),
    initialData: () => readMatchesCache(league, positiveEvOnly)?.data,
    placeholderData: keepPreviousData,
    staleTime: 2 * 60_000,
    gcTime: MATCHES_GC_MS,
    refetchInterval: MATCHES_REFETCH_MS,
    enabled: options?.enabled ?? true,
  });
}

export function useMatrix(league: LeagueKey | "all") {
  return useQuery({
    queryKey: queryKeys.matrix(league),
    queryFn: () => fetchMatrix(league),
    placeholderData: keepPreviousData,
    staleTime: 2 * 60_000,
    gcTime: MATCHES_GC_MS,
    refetchInterval: MATRIX_REFETCH_MS,
  });
}

export function useOddsHistory(
  matchId: string | null,
  outcome?: Outcome,
  enabled = true
) {
  return useQuery({
    queryKey: queryKeys.oddsHistory(matchId ?? "", outcome),
    queryFn: () => fetchOddsHistory(matchId!, outcome),
    enabled: Boolean(matchId) && enabled,
    refetchInterval: 5 * 60_000,
  });
}

export function usePerformance(league: LeagueKey | "all") {
  return useQuery({
    queryKey: queryKeys.performance(league),
    queryFn: () => fetchPerformance(league),
  });
}

export function useLeaderboard() {
  return useQuery({
    queryKey: queryKeys.leaderboard,
    queryFn: fetchLeaderboard,
  });
}

export function useCalculator(input: CalculatorRequest, enabled = true) {
  return useQuery({
    queryKey: queryKeys.calculator(input),
    queryFn: () => postCalculator(input),
    enabled,
    placeholderData: (prev) => prev,
  });
}

export function useInvalidateMatches() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: ["matches"] });
}

export function useCalculatorMutation() {
  return useMutation({
    mutationFn: postCalculator,
  });
}
