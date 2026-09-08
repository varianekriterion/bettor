import type { MatchCard } from "@/types/betting";

const CLUB_SUFFIXES =
  /\b(fc|cf|sc|ac|as|ssc|afc|bfc|fk|sk|cd|ud|sd|rc|rb|sv|vfb|tsv|1\.?\s*fc)\b/gi;

export function normalizeSearch(text: string): string {
  return text
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(CLUB_SUFFIXES, "")
    .replace(/[^a-z0-9\s]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function splitVersusQuery(query: string): [string, string] | null {
  const parts = query.split(/\s+(?:v|vs|versus|-)\s+/i);
  if (parts.length !== 2) return null;
  const left = normalizeSearch(parts[0]!);
  const right = normalizeSearch(parts[1]!);
  if (!left || !right) return null;
  return [left, right];
}

function tokenScore(haystack: string, needle: string): number {
  if (!needle) return 0;
  if (haystack === needle) return 100;
  if (haystack.startsWith(needle)) return 85;
  const wordStart = haystack
    .split(" ")
    .some((word) => word.startsWith(needle) || word === needle);
  if (wordStart) return 70;
  if (haystack.includes(needle)) return 55;
  return 0;
}

export function scoreMatch(match: MatchCard, rawQuery: string): number {
  const query = normalizeSearch(rawQuery);
  if (!query) return 0;

  const home = normalizeSearch(match.home_team);
  const away = normalizeSearch(match.away_team);
  const combined = `${home} ${away}`;
  const label = `${home} vs ${away}`;

  const versus = splitVersusQuery(rawQuery);
  if (versus) {
    const [left, right] = versus;
    const direct =
      (tokenScore(home, left) + tokenScore(away, right)) / 2 +
      (home.includes(left) && away.includes(right) ? 15 : 0);
    const flipped =
      (tokenScore(home, right) + tokenScore(away, left)) / 2 +
      (home.includes(right) && away.includes(left) ? 10 : 0);
    return Math.max(direct, flipped);
  }

  const tokens = query.split(" ").filter(Boolean);
  if (tokens.length > 1) {
    const allTokensHit = tokens.every(
      (t) => home.includes(t) || away.includes(t) || label.includes(t)
    );
    if (allTokensHit) {
      const avg =
        tokens.reduce(
          (sum, t) =>
            sum + Math.max(tokenScore(home, t), tokenScore(away, t), tokenScore(label, t)),
          0
        ) / tokens.length;
      return avg + 8;
    }
  }

  return Math.max(
    tokenScore(home, query),
    tokenScore(away, query),
    tokenScore(combined, query),
    tokenScore(label, query) * 0.95
  );
}

export function filterAndRankMatches(
  matches: MatchCard[],
  rawQuery: string,
  limit = 8
): MatchCard[] {
  const query = rawQuery.trim();
  if (!query) return [];

  return matches
    .map((match) => ({ match, score: scoreMatch(match, query) }))
    .filter(({ score }) => score >= 40)
    .sort((a, b) => {
      if (b.score !== a.score) return b.score - a.score;
      return (
        new Date(a.match.commence_time).getTime() -
        new Date(b.match.commence_time).getTime()
      );
    })
    .slice(0, limit)
    .map(({ match }) => match);
}

export function matchSearchLabel(match: MatchCard): string {
  return `${match.home_team} vs ${match.away_team}`;
}

export function matchMatchesQuery(match: MatchCard, rawQuery: string): boolean {
  return scoreMatch(match, rawQuery) >= 40;
}

export type HighlightSegment = { text: string; match: boolean };

export function highlightSegments(
  text: string,
  rawQuery: string
): HighlightSegment[] {
  const query = normalizeSearch(rawQuery);
  if (!query) return [{ text, match: false }];

  const tokens = query.split(" ").filter(Boolean);
  if (tokens.length === 0) return [{ text, match: false }];

  const ranges: { start: number; end: number }[] = [];
  const lowerText = text.toLowerCase();

  for (const token of tokens) {
    let from = 0;
    while (from < lowerText.length) {
      const idx = lowerText.indexOf(token, from);
      if (idx === -1) break;
      ranges.push({ start: idx, end: idx + token.length });
      from = idx + token.length;
    }
  }

  if (ranges.length === 0) return [{ text, match: false }];

  ranges.sort((a, b) => a.start - b.start);
  const merged: { start: number; end: number }[] = [];
  for (const range of ranges) {
    const last = merged[merged.length - 1];
    if (!last || range.start > last.end) merged.push({ ...range });
    else last.end = Math.max(last.end, range.end);
  }

  const segments: HighlightSegment[] = [];
  let cursor = 0;
  for (const { start, end } of merged) {
    if (cursor < start) {
      segments.push({ text: text.slice(cursor, start), match: false });
    }
    segments.push({ text: text.slice(start, end), match: true });
    cursor = end;
  }
  if (cursor < text.length) {
    segments.push({ text: text.slice(cursor), match: false });
  }
  return segments.length > 0 ? segments : [{ text, match: false }];
}
