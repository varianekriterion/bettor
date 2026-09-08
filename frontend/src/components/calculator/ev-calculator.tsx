"use client";

import { useEffect, useMemo, useState } from "react";
import { useCalculator } from "@/hooks/use-betting-data";
import {
  BANKROLL_CURRENCIES,
  formatBankroll,
  formatEv,
  type BankrollCurrency,
} from "@/lib/utils";
import type { CalculatorRequest, CalculatorResponse } from "@/types/betting";
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

function localCalculate(input: CalculatorRequest): CalculatorResponse {
  const p = input.win_probability;
  const b = input.decimal_odds - 1;
  const q = 1 - p;
  const evDecimal = p * b - q;
  const full = Math.max(0, (b * p - q) / b);
  const frac = full * input.kelly_fraction;
  const stake = input.bankroll * frac;
  return {
    ev_pct: evDecimal * 100,
    ev_decimal: evDecimal,
    is_positive_ev: evDecimal > 0,
    fair_odds: p > 0 ? 1 / p : Infinity,
    full_kelly_pct: full * 100,
    fractional_kelly_pct: frac * 100,
    recommended_stake: stake,
    expected_return: stake * evDecimal,
    edge: b * p - q,
    kelly_fraction_used: input.kelly_fraction,
  };
}

export function EvCalculator() {
  const [bankroll, setBankroll] = useState(1000);
  const [currency, setCurrency] = useState<BankrollCurrency>("USD");
  const [odds, setOdds] = useState(2.1);
  const [prob, setProb] = useState(0.52);
  const [kellyFraction, setKellyFraction] = useState(0.25);
  const [debounced, setDebounced] = useState<CalculatorRequest>({
    bankroll: 1000,
    decimal_odds: 2.1,
    win_probability: 0.52,
    kelly_fraction: 0.25,
  });

  const input: CalculatorRequest = useMemo(
    () => ({
      bankroll,
      decimal_odds: odds,
      win_probability: prob,
      kelly_fraction: kellyFraction,
    }),
    [bankroll, odds, prob, kellyFraction]
  );

  useEffect(() => {
    const t = setTimeout(() => setDebounced(input), 250);
    return () => clearTimeout(t);
  }, [input]);

  const valid =
    debounced.bankroll > 0 &&
    debounced.decimal_odds > 1 &&
    debounced.win_probability > 0 &&
    debounced.win_probability < 1 &&
    debounced.kelly_fraction > 0 &&
    debounced.kelly_fraction <= 1;

  const { data, isFetching, isError, error } = useCalculator(debounced, valid);
  const fallback = useMemo(() => localCalculate(debounced), [debounced]);
  const result = data ?? fallback;

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div>
        <h1 className="font-display text-2xl font-bold tracking-tight md:text-3xl">
          +EV Calculator
        </h1>
        <p className="mt-1 text-sm text-zinc-400">
          Bankroll · decimal odds · win probability → stake & expected return
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Inputs</CardTitle>
            <CardDescription>
              Uses EV% = (p·(odds−1) − (1−p)) × 100 and fractional Kelly
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <Field label="Bankroll">
              <div className="mb-2 flex gap-2">
                {(Object.keys(BANKROLL_CURRENCIES) as BankrollCurrency[]).map((c) => (
                  <Button
                    key={c}
                    size="sm"
                    variant={currency === c ? "default" : "secondary"}
                    onClick={() => setCurrency(c)}
                  >
                    {BANKROLL_CURRENCIES[c].label}
                  </Button>
                ))}
              </div>
              <div className="relative">
                <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-sm text-zinc-500">
                  {BANKROLL_CURRENCIES[currency].symbol}
                </span>
                <Input
                  type="number"
                  min={0}
                  step={BANKROLL_CURRENCIES[currency].step}
                  value={bankroll}
                  onChange={(e) => setBankroll(Number(e.target.value))}
                  className="pl-8"
                />
              </div>
            </Field>
            <Field label="Decimal odds">
              <Input
                type="number"
                min={1.01}
                step={0.01}
                value={odds}
                onChange={(e) => setOdds(Number(e.target.value))}
              />
            </Field>
            <Field label={`Win probability (${(prob * 100).toFixed(1)}%)`}>
              <Input
                type="range"
                min={0.01}
                max={0.99}
                step={0.005}
                value={prob}
                onChange={(e) => setProb(Number(e.target.value))}
                className="h-2 cursor-pointer accent-emerald-500"
              />
              <Input
                type="number"
                min={0.01}
                max={0.99}
                step={0.01}
                value={prob}
                onChange={(e) => setProb(Number(e.target.value))}
                className="mt-2"
              />
            </Field>
            <Field label={`Kelly fraction (${kellyFraction}x)`}>
              <div className="flex gap-2">
                {[0.1, 0.25, 0.5, 1].map((f) => (
                  <Button
                    key={f}
                    size="sm"
                    variant={kellyFraction === f ? "default" : "secondary"}
                    onClick={() => setKellyFraction(f)}
                  >
                    {f === 1 ? "Full" : `${f}x`}
                  </Button>
                ))}
              </div>
            </Field>
            {isError && (
              <p className="text-xs text-amber-400/90">
                API offline — using local math
                {error instanceof Error ? ` (${error.message.slice(0, 80)})` : ""}
              </p>
            )}
          </CardContent>
        </Card>

        <Card className="border-emerald-500/20">
          <CardHeader>
            <CardTitle>Output</CardTitle>
            <CardDescription>
              {isFetching ? "Syncing with API…" : "Live results via /api/v1/calculator"}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {result ? (
              <>
                <div className="flex items-center justify-between rounded-lg bg-zinc-950/60 px-4 py-3">
                  <span className="text-sm text-zinc-400">Expected Value</span>
                  <Badge variant={result.is_positive_ev ? "positive" : "negative"}>
                    {formatEv(result.ev_pct)}
                  </Badge>
                </div>
                <Metric
                  label="Recommended stake"
                  value={formatBankroll(result.recommended_stake, currency)}
                  highlight
                />
                <Metric
                  label="Stake % of bankroll"
                  value={`${result.fractional_kelly_pct.toFixed(2)}%`}
                />
                <Metric
                  label="Full Kelly"
                  value={`${result.full_kelly_pct.toFixed(2)}%`}
                />
                <Metric
                  label="Expected profit on stake"
                  value={formatBankroll(result.expected_return, currency)}
                />
                <Metric label="Fair odds" value={result.fair_odds.toFixed(3)} />
                <Metric label="Edge (b·p − q)" value={result.edge.toFixed(4)} />
                {!result.is_positive_ev && (
                  <p className="rounded-md border border-rose-500/20 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
                    Negative EV — Kelly stake floored to zero. Do not bet.
                  </p>
                )}
              </>
            ) : (
              <p className="text-sm text-zinc-500">Enter inputs to calculate.</p>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-2">
      <Label>{label}</Label>
      {children}
    </div>
  );
}

function Metric({
  label,
  value,
  highlight,
}: {
  label: string;
  value: string;
  highlight?: boolean;
}) {
  return (
    <div className="flex items-center justify-between border-b border-zinc-800/80 py-2 last:border-0">
      <span className="text-sm text-zinc-400">{label}</span>
      <span
        className={`font-mono text-sm ${
          highlight ? "text-lg font-semibold text-emerald-400" : "text-zinc-100"
        }`}
      >
        {value}
      </span>
    </div>
  );
}
