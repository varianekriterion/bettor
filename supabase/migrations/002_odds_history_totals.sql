-- Extend odds_snapshots for market type (h2h / totals) and over/under lines.
-- Enables Opening vs Current line-movement tracking across sync cycles.

alter table public.odds_snapshots
  add column if not exists market_type text not null default 'h2h'
    check (market_type in ('h2h', 'totals'));

alter table public.odds_snapshots
  add column if not exists line numeric(5,2);

alter table public.odds_snapshots
  add column if not exists over_odds numeric(8,3);

alter table public.odds_snapshots
  add column if not exists under_odds numeric(8,3);

-- Totals rows only fill over/under; allow nullable 1X2 columns for those rows.
alter table public.odds_snapshots alter column home_odds drop not null;
alter table public.odds_snapshots alter column draw_odds drop not null;
alter table public.odds_snapshots alter column away_odds drop not null;

-- Drop legacy always-positive checks if present, then re-add nullable-safe ones.
alter table public.odds_snapshots drop constraint if exists odds_snapshots_home_odds_check;
alter table public.odds_snapshots drop constraint if exists odds_snapshots_draw_odds_check;
alter table public.odds_snapshots drop constraint if exists odds_snapshots_away_odds_check;

alter table public.odds_snapshots
  add constraint odds_snapshots_home_odds_check
  check (home_odds is null or home_odds > 1);

alter table public.odds_snapshots
  add constraint odds_snapshots_draw_odds_check
  check (draw_odds is null or draw_odds > 1);

alter table public.odds_snapshots
  add constraint odds_snapshots_away_odds_check
  check (away_odds is null or away_odds > 1);

alter table public.odds_snapshots
  drop constraint if exists odds_snapshots_over_odds_check;
alter table public.odds_snapshots
  add constraint odds_snapshots_over_odds_check
  check (over_odds is null or over_odds > 1);

alter table public.odds_snapshots
  drop constraint if exists odds_snapshots_under_odds_check;
alter table public.odds_snapshots
  add constraint odds_snapshots_under_odds_check
  check (under_odds is null or under_odds > 1);

alter table public.odds_snapshots
  drop constraint if exists odds_snapshots_market_row_check;
alter table public.odds_snapshots
  add constraint odds_snapshots_market_row_check
  check (
    (market_type = 'h2h' and home_odds is not null and draw_odds is not null and away_odds is not null)
    or
    (market_type = 'totals' and over_odds is not null and under_odds is not null and line is not null)
  );

create index if not exists odds_match_market_idx
  on public.odds_snapshots (match_id, market_type, captured_at desc);
