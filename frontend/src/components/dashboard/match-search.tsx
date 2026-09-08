"use client";

import { format } from "date-fns";
import { Search, X } from "lucide-react";
import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  filterAndRankMatches,
  highlightSegments,
  matchSearchLabel,
} from "@/lib/match-search";
import { cn } from "@/lib/utils";
import type { MatchCard } from "@/types/betting";

type MatchSearchProps = {
  matches: MatchCard[];
  value: string;
  onValueChange: (value: string) => void;
  onSelectMatch?: (match: MatchCard | null) => void;
  className?: string;
  disabled?: boolean;
};

function HighlightedText({
  text,
  query,
  className,
}: {
  text: string;
  query: string;
  className?: string;
}) {
  const segments = highlightSegments(text, query);
  return (
    <span className={className}>
      {segments.map((seg, i) =>
        seg.match ? (
          <mark
            key={i}
            className="rounded-sm bg-emerald-500/25 px-0.5 text-emerald-200"
          >
            {seg.text}
          </mark>
        ) : (
          <span key={i}>{seg.text}</span>
        )
      )}
    </span>
  );
}

export function MatchSearch({
  matches,
  value,
  onValueChange,
  onSelectMatch,
  className,
  disabled,
}: MatchSearchProps) {
  const listId = useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);

  const suggestions = useMemo(
    () => filterAndRankMatches(matches, value, 8),
    [matches, value]
  );

  const showDropdown = open && value.trim().length > 0;

  const close = useCallback(() => {
    setOpen(false);
    setActiveIndex(-1);
  }, []);

  const selectMatch = useCallback(
    (match: MatchCard) => {
      onValueChange(matchSearchLabel(match));
      onSelectMatch?.(match);
      close();
      inputRef.current?.blur();
    },
    [close, onSelectMatch, onValueChange]
  );

  useEffect(() => {
    if (!showDropdown) setActiveIndex(-1);
    else if (activeIndex >= suggestions.length) setActiveIndex(-1);
  }, [activeIndex, showDropdown, suggestions.length]);

  useEffect(() => {
    function onPointerDown(e: MouseEvent) {
      if (!rootRef.current?.contains(e.target as Node)) close();
    }
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, [close]);

  return (
    <div ref={rootRef} className={cn("relative w-full sm:w-[280px]", className)}>
      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-500" />
        <Input
          ref={inputRef}
          type="search"
          role="combobox"
          aria-expanded={showDropdown}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={
            activeIndex >= 0 ? `${listId}-option-${activeIndex}` : undefined
          }
          autoComplete="off"
          spellCheck={false}
          placeholder="Search teams or fixtures…"
          value={value}
          disabled={disabled}
          className="h-9 pl-9 pr-9"
          onFocus={() => setOpen(true)}
          onChange={(e) => {
            onValueChange(e.target.value);
            setOpen(true);
            setActiveIndex(-1);
          }}
          onKeyDown={(e) => {
            if (!showDropdown && e.key === "ArrowDown" && value.trim()) {
              setOpen(true);
              setActiveIndex(0);
              e.preventDefault();
              return;
            }
            if (!showDropdown) return;

            if (e.key === "ArrowDown") {
              e.preventDefault();
              setActiveIndex((i) =>
                i < suggestions.length - 1 ? i + 1 : 0
              );
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setActiveIndex((i) =>
                i > 0 ? i - 1 : suggestions.length - 1
              );
            } else if (e.key === "Enter") {
              e.preventDefault();
              if (activeIndex >= 0 && suggestions[activeIndex]) {
                selectMatch(suggestions[activeIndex]!);
              } else if (suggestions[0]) {
                selectMatch(suggestions[0]);
              }
            } else if (e.key === "Escape") {
              close();
              inputRef.current?.blur();
            }
          }}
        />
        {value && (
          <button
            type="button"
            aria-label="Clear search"
            className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-0.5 text-zinc-500 transition-colors hover:bg-zinc-800 hover:text-zinc-200"
            onClick={() => {
              onValueChange("");
              onSelectMatch?.(null);
              setOpen(false);
              inputRef.current?.focus();
            }}
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>

      {showDropdown && (
        <div
          id={listId}
          role="listbox"
          className="absolute z-50 mt-1.5 w-full overflow-hidden rounded-lg border border-zinc-700 bg-zinc-900 shadow-xl shadow-black/40"
        >
          {suggestions.length === 0 ? (
            <div className="px-3 py-4 text-center text-sm text-zinc-500">
              No fixtures match &ldquo;{value.trim()}&rdquo;
            </div>
          ) : (
            <ul className="max-h-[320px] overflow-y-auto py-1">
              {suggestions.map((match, index) => {
                const active = index === activeIndex;
                return (
                  <li key={match.id} role="presentation">
                    <button
                      id={`${listId}-option-${index}`}
                      type="button"
                      role="option"
                      aria-selected={active}
                      className={cn(
                        "flex w-full flex-col gap-1 px-3 py-2.5 text-left transition-colors",
                        active
                          ? "bg-emerald-500/10 text-zinc-50"
                          : "text-zinc-200 hover:bg-zinc-800/80"
                      )}
                      onMouseEnter={() => setActiveIndex(index)}
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={() => selectMatch(match)}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-sm font-medium">
                            <HighlightedText
                              text={match.home_team}
                              query={value}
                            />
                            <span className="mx-1.5 text-zinc-600">vs</span>
                            <HighlightedText
                              text={match.away_team}
                              query={value}
                            />
                          </div>
                          <div className="mt-0.5 font-mono text-[11px] text-zinc-500">
                            {format(new Date(match.commence_time), "EEE d MMM · HH:mm")}
                          </div>
                        </div>
                        <div className="flex shrink-0 flex-col items-end gap-1">
                          <Badge variant="league" className="max-w-[110px] truncate">
                            {match.league_name}
                          </Badge>
                          {match.best_edge.is_positive_ev && (
                            <Badge variant="positive" className="text-[10px]">
                              +EV
                            </Badge>
                          )}
                        </div>
                      </div>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
