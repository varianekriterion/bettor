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

export type BankrollCurrency = "USD" | "MYR" | "SOL" | "ETH";

export const BANKROLL_CURRENCIES: Record<
  BankrollCurrency,
  { label: string; symbol: string; decimals: number; step: number }
> = {
  USD: { label: "USD", symbol: "$", decimals: 2, step: 10 },
  MYR: { label: "MYR", symbol: "RM", decimals: 2, step: 10 },
  SOL: { label: "Sol", symbol: "◎", decimals: 4, step: 0.1 },
  ETH: { label: "Eth", symbol: "Ξ", decimals: 4, step: 0.01 },
};

export function formatCurrency(amount: number, currency = "€"): string {
  return `${currency}${amount.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

export function formatBankroll(amount: number, currency: BankrollCurrency): string {
  const { symbol, decimals } = BANKROLL_CURRENCIES[currency];
  return `${symbol}${amount.toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
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
