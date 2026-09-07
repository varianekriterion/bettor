"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchLeaderboard,
  fetchMatches,
  fetchMatrix,
  fetchOddsHistory,
  fetchPerformance,
  postCalculator,
} from "@/lib/api";
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

export function useMatches(
  league: LeagueKey | "all",
  positiveEvOnly: boolean
) {
  return useQuery({
    queryKey: queryKeys.matches(league, positiveEvOnly),
    queryFn: () => fetchMatches({ league, positiveEvOnly }),
    refetchInterval: 60_000,
  });
}

export function useMatrix(league: LeagueKey | "all") {
  return useQuery({
    queryKey: queryKeys.matrix(league),
    queryFn: () => fetchMatrix(league),
    refetchInterval: 60_000,
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
    refetchInterval: 60_000,
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
