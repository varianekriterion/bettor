-- Step 3: Real prediction settlement + 30-day tipster accuracy rollup.
--
-- Adds settlement status on individual predictions and a rolling performance
-- table consumed by performance_service / Bayesian consensus weighting.

-- Settlement outcome per prediction row (null = not yet scored)
alter table public.predictions
  add column if not exists status text
    check (status in ('WON', 'LOST', 'VOID'));

create index if not exists predictions_status_idx
  on public.predictions (status)
  where status is not null;

-- Rolling 30-day accuracy aggregates per tipster source + league
create table if not exists public.tipster_performance (
  id uuid primary key default gen_random_uuid(),
  source text not null,
  league text not null,
  total_picks int not null default 0,
  won_picks int not null default 0,
  win_rate numeric(6,4) not null default 0,
  brier_score numeric(8,6) not null default 0.25,
  updated_at timestamptz not null default now(),
  unique (source, league)
);

create index if not exists tipster_performance_lookup_idx
  on public.tipster_performance (league, source);

alter table public.tipster_performance enable row level security;

create policy "Public read tipster performance"
  on public.tipster_performance for select using (true);

comment on table public.tipster_performance is
  'Rolling 30-day settled-prediction accuracy per tipster source and league; '
  'refreshed by settlement_service after each settlement run.';
