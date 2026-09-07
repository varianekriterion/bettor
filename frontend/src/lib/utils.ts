import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatPct(value: number, digits = 1): string {
  return `${value >= 0 ? "" : ""}${(value * (Math.abs(value) <= 1 ? 100 : 1)).toFixed(digits)}%`;
}

export function formatProbPct(prob: number, digits = 1): string {
  return `${(prob * 100).toFixed(digits)}%`;
}

export function formatOdds(odds: number): string {
  return odds.toFixed(2);
}

export function formatEv(evPct: number): string {
  const sign = evPct > 0 ? "+" : "";
  return `${sign}${evPct.toFixed(1)}%`;
}

export function formatCurrency(amount: number, currency = "€"): string {
  return `${currency}${amount.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

export function outcomeTeamLabel(
  outcome: "home" | "draw" | "away",
  home: string,
  away: string
): string {
  if (outcome === "home") return home;
  if (outcome === "away") return away;
  return "Draw";
}
