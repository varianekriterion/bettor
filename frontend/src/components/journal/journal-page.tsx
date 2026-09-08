"use client";

import { BetJournal } from "@/components/journal/bet-journal";
import { useMatches } from "@/hooks/use-betting-data";

export function JournalPage() {
  const { data: matches = [] } = useMatches("all", false);

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div>
        <h1 className="font-display text-2xl font-bold tracking-tight text-zinc-50">
          Bet Journal
        </h1>
        <p className="mt-1 text-sm text-zinc-400">
          Track every bet — upload slip screenshots in batch or log manually.
        </p>
      </div>
      <BetJournal matches={matches} />
    </div>
  );
}
