-- BetConsensus Engine — Supabase schema
-- Run in Supabase SQL editor or via CLI migrations

create extension if not exists "pgcrypto";

-- Leagues
create table if not exists public.leagues (
  key text primary key,
  name text not null,
  odds_api_key text not null,
  short_name text not null,
  active boolean not null default true
);

insert into public.leagues (key, name, odds_api_key, short_name) values
  ('ucl', 'UEFA Champions League', 'soccer_uefa_champs_league', 'UCL'),
  ('epl', 'Premier League', 'soccer_epl', 'EPL'),
  ('laliga', 'La Liga', 'soccer_spain_la_liga', 'LaLiga'),
  ('bundesliga', 'Bundesliga', 'soccer_germany_bundesliga', 'Bundesliga'),
  ('seriea', 'Serie A', 'soccer_italy_serie_a', 'Serie A'),
  ('uel', 'Europa League', 'soccer_uefa_europa_league', 'UEL')
on conflict (key) do nothing;

-- Matches
create table if not exists public.matches (
  id text primary key,
  league_key text not null references public.leagues(key),
  home_team text not null,
  away_team text not null,
  commence_time timestamptz not null,
  status text not null default 'scheduled',
  result_outcome text check (result_outcome in ('home', 'draw', 'away')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists matches_league_time_idx on public.matches (league_key, commence_time);

-- Bookmaker odds snapshots
create table if not exists public.odds_snapshots (
  id uuid primary key default gen_random_uuid(),
  match_id text not null references public.matches(id) on delete cascade,
  bookmaker text not null,
  home_odds numeric(8,3) not null check (home_odds > 1),
  draw_odds numeric(8,3) not null check (draw_odds > 1),
  away_odds numeric(8,3) not null check (away_odds > 1),
  captured_at timestamptz not null default now()
);

create index if not exists odds_match_idx on public.odds_snapshots (match_id, captured_at desc);

-- Source predictions
create table if not exists public.predictions (
  id uuid primary key default gen_random_uuid(),
  match_id text not null references public.matches(id) on delete cascade,
  source text not null,
  home_prob numeric(8,6) not null,
  draw_prob numeric(8,6) not null,
  away_prob numeric(8,6) not null,
  pick text not null check (pick in ('home', 'draw', 'away')),
  scraped_at timestamptz not null default now(),
  unique (match_id, source, scraped_at)
);

create index if not exists predictions_match_idx on public.predictions (match_id, scraped_at desc);

-- Consensus runs
create table if not exists public.consensus_runs (
  id uuid primary key default gen_random_uuid(),
  match_id text not null references public.matches(id) on delete cascade,
  home_prob numeric(8,6) not null,
  draw_prob numeric(8,6) not null,
  away_prob numeric(8,6) not null,
  pick text not null check (pick in ('home', 'draw', 'away')),
  confidence numeric(8,6) not null,
  source_weights jsonb not null default '{}'::jsonb,
  best_outcome text not null,
  best_odds numeric(8,3) not null,
  ev_pct numeric(10,4) not null,
  kelly_pct numeric(10,4) not null,
  created_at timestamptz not null default now()
);

-- Source performance (rolling window aggregates)
create table if not exists public.source_performance (
  id uuid primary key default gen_random_uuid(),
  source text not null,
  league_key text not null references public.leagues(key),
  window_days int not null default 30,
  total_predictions int not null default 0,
  correct int not null default 0,
  accuracy numeric(6,4) not null default 0,
  brier_score numeric(8,6) not null default 0.25,
  avg_ev_captured numeric(8,4) not null default 0,
  computed_at timestamptz not null default now(),
  unique (source, league_key, window_days, computed_at)
);

-- User profiles (extends Supabase auth.users)
create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  display_name text,
  bankroll numeric(14,2) not null default 1000,
  kelly_fraction numeric(4,3) not null default 0.250,
  preferred_leagues text[] not null default array['epl','laliga','bundesliga','seriea','ucl','uel'],
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Bet journal
create table if not exists public.bet_journal (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles(id) on delete cascade,
  match_id text references public.matches(id),
  outcome text not null check (outcome in ('home', 'draw', 'away')),
  odds numeric(8,3) not null,
  stake numeric(14,2) not null,
  consensus_prob numeric(8,6) not null,
  ev_pct numeric(10,4) not null,
  kelly_pct numeric(10,4) not null,
  result text check (result in ('win', 'loss', 'push', 'pending')),
  profit numeric(14,2),
  placed_at timestamptz not null default now()
);

-- RLS
alter table public.profiles enable row level security;
alter table public.bet_journal enable row level security;
alter table public.matches enable row level security;
alter table public.odds_snapshots enable row level security;
alter table public.predictions enable row level security;
alter table public.consensus_runs enable row level security;
alter table public.source_performance enable row level security;
alter table public.leagues enable row level security;

-- Public read for market data
create policy "Public read leagues" on public.leagues for select using (true);
create policy "Public read matches" on public.matches for select using (true);
create policy "Public read odds" on public.odds_snapshots for select using (true);
create policy "Public read predictions" on public.predictions for select using (true);
create policy "Public read consensus" on public.consensus_runs for select using (true);
create policy "Public read performance" on public.source_performance for select using (true);

-- Users manage own profile & journal
create policy "Users read own profile" on public.profiles
  for select using (auth.uid() = id);
create policy "Users update own profile" on public.profiles
  for update using (auth.uid() = id);
create policy "Users insert own profile" on public.profiles
  for insert with check (auth.uid() = id);

create policy "Users manage own bets" on public.bet_journal
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- Auto-create profile on signup
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer set search_path = public
as $$
begin
  insert into public.profiles (id, display_name)
  values (new.id, coalesce(new.raw_user_meta_data->>'display_name', split_part(new.email, '@', 1)));
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute procedure public.handle_new_user();
