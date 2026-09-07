-- Bet journal: match labels, units, and explicit RLS CRUD policies.
-- Ensures authenticated (incl. anonymous) users can fully manage their own bets.

-- Display label for fixtures (survives when match_id FK is null / demo IDs).
alter table public.bet_journal
  add column if not exists match_label text;

-- Stake size in bankroll units (independent of currency stake).
alter table public.bet_journal
  add column if not exists units numeric(10,3);

-- Backfill units from stake where missing (1 currency unit ≈ 1 journal unit).
update public.bet_journal
set units = stake
where units is null;

-- Tighten / clarify RLS: drop broad FOR ALL, add explicit CRUD policies.
drop policy if exists "Users manage own bets" on public.bet_journal;

drop policy if exists "Users select own bets" on public.bet_journal;
create policy "Users select own bets" on public.bet_journal
  for select
  using (auth.uid() = user_id);

drop policy if exists "Users insert own bets" on public.bet_journal;
create policy "Users insert own bets" on public.bet_journal
  for insert
  with check (auth.uid() = user_id);

drop policy if exists "Users update own bets" on public.bet_journal;
create policy "Users update own bets" on public.bet_journal
  for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

drop policy if exists "Users delete own bets" on public.bet_journal;
create policy "Users delete own bets" on public.bet_journal
  for delete
  using (auth.uid() = user_id);

-- Profiles: allow users to upsert their own row (needed for anon → journal FK).
drop policy if exists "Users insert own profile" on public.profiles;
create policy "Users insert own profile" on public.profiles
  for insert
  with check (auth.uid() = id);

-- Ensure updated_at on matches stays writable by service role (no RLS write needed).
comment on table public.bet_journal is
  'Personal bet log; RLS restricts all CRUD to auth.uid() = user_id';
