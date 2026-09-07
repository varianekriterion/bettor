-- Phase 1: pgvector + long-term "AI memory" of settled bets.
--
-- One embedded row per settled bet_journal entry, denormalizing enough of
-- bet_journal + predictions (tipster call, our EV/Kelly call, actual result)
-- into `content` for retrieval, plus structured fields in `metadata` for
-- filtering. Populated by the FastAPI background embedding job — this
-- migration only creates the storage + retrieval surface.

create extension if not exists "vector";

create table if not exists public.bet_journal_vectors (
  id uuid primary key default gen_random_uuid(),
  bet_id uuid not null references public.bet_journal(id) on delete cascade,
  match_id text references public.matches(id) on delete set null,
  prediction_id uuid references public.predictions(id) on delete set null,
  user_id uuid not null references public.profiles(id) on delete cascade,

  -- Denormalized for cheap filtering without a join back to predictions.
  source text,

  -- The plain-text summary that was embedded, e.g.:
  -- "Girona vs Betis (La Liga, 2026-01-14). Tipster 'forebet' picked BTTS/home win
  --  at 62% confidence. Our consensus gave home 51% vs bookmaker-implied 44%
  --  (+9.2% EV, 2.1% Kelly stake). User bet €25 on home @ 2.10. Result: draw
  --  (loss). Consensus overweighted home xG from a small sample."
  content text not null,

  -- Structured fields for hybrid filtering (e.g. "only mistakes", "only this source").
  -- Expected keys: outcome, odds, stake, consensus_prob, tipster_prob, ev_pct,
  -- kelly_pct, result ('win'|'loss'|'push'), profit, was_mistake (bool).
  metadata jsonb not null default '{}'::jsonb,

  embedding vector(1536) not null,           -- text-embedding-3-small dimensionality
  embedding_model text not null default 'text-embedding-3-small',

  created_at timestamptz not null default now(),

  unique (bet_id)  -- one memory row per settled bet; re-embed via upsert
);

create index if not exists bet_journal_vectors_bet_idx on public.bet_journal_vectors (bet_id);
create index if not exists bet_journal_vectors_match_idx on public.bet_journal_vectors (match_id);
create index if not exists bet_journal_vectors_user_idx on public.bet_journal_vectors (user_id);

-- Approximate nearest-neighbour index for cosine similarity search.
-- `lists = 100` is a reasonable starting point for a small/medium table;
-- re-run `ANALYZE public.bet_journal_vectors` (or rebuild with a higher
-- `lists`) once there are tens of thousands of rows.
create index if not exists bet_journal_vectors_embedding_idx
  on public.bet_journal_vectors
  using ivfflat (embedding vector_cosine_ops)
  with (lists = 100);

alter table public.bet_journal_vectors enable row level security;

-- Users can read their own AI memory (e.g. from a "why did the AI say that"
-- debug view). Writes come from the FastAPI background job via the
-- service-role key, which bypasses RLS, so no insert/update policy is
-- granted to regular authenticated users.
create policy "Users read own bet memories" on public.bet_journal_vectors
  for select using (auth.uid() = user_id);

comment on table public.bet_journal_vectors is
  'AI long-term memory: one embedding per settled bet (tipster call + our EV/Kelly call + actual outcome), used by the chat agent''s search_past_bet_mistakes tool.';

-- Cosine-similarity search RPC. Callable from the FastAPI backend
-- (service role — bypasses RLS, so pass match_user_id explicitly) or
-- directly via supabase-js `.rpc()` from an authenticated client.
create or replace function public.match_bet_journal_vectors(
  query_embedding vector(1536),
  match_user_id uuid,
  match_count int default 5,
  min_similarity float default 0.0
)
returns table (
  id uuid,
  bet_id uuid,
  match_id text,
  source text,
  content text,
  metadata jsonb,
  similarity float
)
language sql stable
as $$
  select
    v.id,
    v.bet_id,
    v.match_id,
    v.source,
    v.content,
    v.metadata,
    1 - (v.embedding <=> query_embedding) as similarity
  from public.bet_journal_vectors v
  where v.user_id = match_user_id
    and 1 - (v.embedding <=> query_embedding) >= min_similarity
  order by v.embedding <=> query_embedding
  limit match_count;
$$;
