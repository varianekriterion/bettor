# Bettor / BetConsensus Engine — Project Status

_Compiled 2026-09-08 from a full read of the codebase (backend + frontend + Supabase migrations)._

---

## 1. What this project does

**Bettor** ("BetConsensus Engine") is a sports-betting analytics tool for European football.
It answers one question: *"Do multiple independent prediction sources agree the bookmaker's
odds are wrong, and if so, how much should I bet?"*

**Pipeline:**

1. **Collect odds** — 1X2 (h2h) and totals (O/U 2.5) bookmaker odds from The Odds API, or
   deterministic demo fixtures when no key is configured.
2. **Collect predictions** — scrapers pull win/draw/win picks for the same fixtures from five
   tipster sites (Forebet, PredictZ, WinDrawWin, Betimate, FootballWhispers). Every scraper
   fails soft to a seeded, deterministic "demo" prediction if the site blocks/CAPTCHAs/errors,
   so the pipeline never hard-crashes.
3. **Devig bookmaker odds** — multiplicative (proportional) or power (Shin-style) method.
4. **Build consensus** — performance-weighted Bayesian blend of the five sources (weighted by
   rolling 30-day accuracy, weak sources floored not zeroed), blended with a market-derived
   prior.
5. **Compute edge** — EV% and fractional-Kelly (default Quarter-Kelly, 0.25×) stake per outcome.
6. **Strategy overlays (Phase 2/4 rules)** — xG/xGA "attacking pressure" scoring, a
   relegation-desperation "motivation flag" that swaps in away-venue-isolated xGA, and a
   "BTTS lucky-not-good" rule that halves the Kelly stake when a team's high BTTS rate isn't
   backed by real xG.
7. **Track accuracy** — settled results feed back into source weighting (currently seeded, see
   §3 below).
8. **AI chat layer (Phase 1/3)** — a LangChain tool-calling agent (streamed via SSE) that can
   look up xG stats, tipster accuracy, and the signed-in user's own past-bet history
   (pgvector semantic search over settled bets) to answer questions in a chat drawer.
9. **Surface it** — dashboard (live matches, consensus %, EV%, Kelly stake, line-movement
   modal), matrix view (per-source picks vs. consensus), calculator, performance leaderboard,
   bet journal, and the chat drawer.

### Stack

| Layer | Tech |
|---|---|
| Frontend | Next.js 14 (App Router) + TypeScript, Tailwind, Radix/Shadcn-style UI, Recharts, TanStack Query, `react-markdown` |
| Backend | Python FastAPI, httpx + BeautifulSoup (+ Playwright installed), Pandas/NumPy, APScheduler |
| AI | LangChain + `langchain-openai`, OpenAI (`text-embedding-3-small`, `gpt-4o-mini`) |
| Data sources | The Odds API, Forebet/PredictZ/WinDrawWin/Betimate/FootballWhispers scrapers, Understat (via `understat` PyPI pkg) |
| DB / Auth | Supabase (Postgres + pgvector, Row-Level Security, Auth) |

---

## 2. Features currently in the codebase

### Core quant engine (`backend/app/core/math_engine.py`)
- Multiplicative and power (Shin) devigging
- Performance-weighted Bayesian consensus with market prior
- EV% and fair-odds calculation
- Fractional Kelly staking (configurable fraction, default 0.25×)
- Poisson xG → W/D/L probability model (`xg_implied_probabilities`), meant as an extra
  blended source, not a replacement for tipster consensus
- Attacking-pressure composite score (shots-on-target + corners vs. league baseline)
- Relegation-desperation "motivation" flag + away-isolated-xGA resolution rule
- BTTS "lucky, not good" flag that halves Kelly stake for flagged outcomes
- Fully unit-tested (`backend/tests/test_math_engine.py`)

### Data pipeline
- `odds_service.py` — Odds API client for h2h + totals markets, with cached demo fixtures
  for 6 leagues (EPL, La Liga, Bundesliga, Serie A, UCL, UEL)
- `scrapers/` — 5 tipster scrapers, each with retry/backoff, rate limiting, and a seeded
  deterministic demo fallback (`scrapers/base.py`, `scrapers/errors.py`)
- `understat_service.py` — trailing-form xG/xGA lookup via the `understat` package for
  EPL/La Liga/Bundesliga/Serie A (not UCL/UEL — Understat doesn't cover them); seeded demo
  fallback otherwise
- `standings_service.py` — seeded league standings context feeding the relegation-desperation
  flag; seeded BTTS rate feeding the "lucky not good" flag
- `sync_service.py` + `scheduler.py` — APScheduler job resyncing predictions every 30 min
  (configurable) for all active leagues, writing to Supabase when configured
- `cache.py` — TTL cache for odds/prediction lookups
- `odds_history_service.py` — tracks opening vs. current bookmaker line movement per match

### Dashboard / UI (`frontend/src/app`, `components`)
- `/` — live match feed with league filter, +EV-only toggle, consensus %, EV%, Kelly stake,
  line-movement modal
- `/matrix` — per-source (tipster) picks vs. master consensus, side by side
- `/calculator` — standalone EV/Kelly calculator (odds, probability, bankroll → stake)
- `/performance` — per-league + global 30-day source accuracy leaderboard (charts)
- Bet journal component — logs bets the user actually placed; writes to Supabase
  `bet_journal` when configured, else falls back to browser storage
- Chat drawer — floating AI assistant panel, streamed responses, suggested prompts, renders
  markdown tables from tool output

### AI / RAG layer (Phase 1 & 3)
- `POST /api/v1/chat` — SSE-streamed LangChain tool-calling agent (`gpt-4o-mini` by default)
  with 3 tools:
  - `query_xg_stats` — live/demo xG, xGA, shots-on-target, corners, attacking pressure
  - `query_tipster_accuracy` — per-league or global 30-day source leaderboard
  - `search_past_bet_mistakes` — pgvector semantic search over the signed-in user's own
    settled-bet history
- `embedding_service.py` — background job that embeds every newly-settled `bet_journal` row
  (via OpenAI embeddings) into `bet_journal_vectors` for the RAG tool above; runs on its own
  scheduler interval (default 15 min) and via an admin trigger endpoint
- `rag_service.py` — query-side embedding + Supabase RPC (`match_bet_journal_vectors`)
  semantic search

### Admin / ops
- `POST /api/v1/admin/sync` (+ `/sync/status`) — manual scraper refresh, optional
  `X-Admin-Token` auth
- `POST /api/v1/admin/embed-bet-memory` (+ `/status`) — manual bet-memory embedding backfill
- `GET /health` — liveness check

### Database (Supabase, `supabase/migrations/`)
- `001_initial_schema.sql` — leagues, matches, odds_snapshots, predictions, consensus_runs,
  bet_journal, RLS policies
- `002_odds_history_totals.sql` — odds line-history + totals (O/U) market columns
- `003_bet_journal_rls_crud.sql` — full CRUD RLS policies for the bet journal
- `004_pgvector_bet_memory.sql` — pgvector extension, `bet_journal_vectors` table, and the
  `match_bet_journal_vectors` similarity-search RPC

### Testing
- `backend/tests/test_math_engine.py` — devig/consensus/EV/Kelly/strategy-rule unit tests
- `backend/tests/test_sync_pipeline.py` — scraper fail-soft + sync pipeline tests

---

## 3. APIs that are missing / not fully wired

| API / integration | Status | Notes |
|---|---|---|
| **The Odds API** | ⚠️ Optional, demo by default | Code is complete; needs `ODDS_API_KEY` + `USE_DEMO_DATA=false` to go live. No paid-tier plan chosen yet. |
| **OpenAI** (chat + embeddings) | ⚠️ Optional, disabled by default | Chat endpoint returns `503` and embedding backfill no-ops without `OPENAI_API_KEY`. Code is complete for both `text-embedding-3-small` and `gpt-4o-mini`. |
| **Understat** (`understat` PyPI package) | ⚠️ Installed manually, demo by default | Requires `pip install --no-deps understat==0.1.14` (its packaging conflicts with the project's `pytest` pin — documented in `requirements.txt`). Only covers EPL/La Liga/Bundesliga/Serie A — **UCL and UEL have no live xG source at all**, always seeded demo data. |
| **Real per-90 stats provider (e.g. FootyStats)** | ❌ Not integrated | `calculate_attacking_pressure()` is written to accept real shots-on-target/corners data as a drop-in, but nothing currently supplies it — it's fed simulated values via `understat_service._seeded_xg`. |
| **Real standings feed** | ❌ Not integrated | `standings_service.py` is 100% seeded (deterministic hash-based fake table positions/points). No live league-table API (e.g. football-data.org, API-Football) is wired in, so the relegation-desperation flag never reflects real standings. |
| **Real BTTS-rate history** | ❌ Not integrated | Also seeded in `standings_service.get_btts_rate()`; needs either a stats provider or our own settled-match rollup. |
| **Real 30-day tipster accuracy** | ❌ Seeded | `performance_service._PERFORMANCE_SEED` is a hardcoded dict, explicitly commented "replace with Supabase queries in production." Nothing currently rolls up actual settled predictions into real accuracy numbers — the leaderboard, the chat's `query_tipster_accuracy` tool, and the Bayesian consensus weighting are all reading fake numbers today. |
| **Scraper targets (Forebet, PredictZ, WinDrawWin, Betimate, FootballWhispers)** | ⚠️ Built but unverified live | Real HTML-scraping code paths exist per site with CSS selectors, but selectors are inherently fragile (sites change DOM) and `USE_DEMO_DATA=true` is the default, so these paths are largely untested against live traffic. No CAPTCHA-solving or proxy rotation — a hard block just falls back to demo data silently. |
| **Playwright** | ⚠️ Installed, unused | Listed in `requirements.txt` but no scraper currently uses it (all use `httpx` + BeautifulSoup) — likely provisioned for a JS-rendered site that isn't scraped yet. |
| **Supabase** | ⚠️ Optional | Entire persistence layer (snapshots, consensus runs, predictions, bet journal, bet-memory vectors) requires `SUPABASE_URL` + `SUPABASE_SERVICE_KEY` server-side and `NEXT_PUBLIC_SUPABASE_URL` + anon key client-side. Without it: bet journal falls back to browser `localStorage`, and RAG search / embedding backfill are no-ops. |
| **Auth** | ⚠️ Partial | Frontend uses anonymous Supabase auth or a normal signed-in session for the bet journal; no full user-account/profile system (settings, multi-bankroll, etc.) beyond that. |
| **Admin auth** | ⚠️ Weak by default | `X-Admin-Token` check on admin routes is a no-op (open access) when `ADMIN_API_TOKEN` isn't set — fine for local dev, not for a public deployment. |

---

## 4. Backend REST surface (`/api/v1`, all implemented)

| Method | Path | Purpose |
|---|---|---|
| GET | `/matches` | Live match feed (consensus %, EV%, Kelly%; filters: `league`, `positive_ev_only`, `bankroll`) |
| GET | `/leagues` | League metadata list |
| GET | `/matches/{id}` | Single match card |
| GET | `/matches/{id}/odds-history` | Opening vs. current line movement, EV shift |
| GET | `/predictions/matrix` | Per-source picks vs. consensus |
| POST | `/calculator` | Ad-hoc EV / Kelly calculation |
| GET | `/performance` | Per-league source accuracy |
| GET | `/performance/leaderboard` | Global 30-day accuracy ranking |
| POST | `/chat` | SSE-streamed AI chat agent |
| POST | `/admin/sync` (+ `/sync/status`) | Manual scraper refresh |
| POST | `/admin/embed-bet-memory` (+ `/status`) | Manual bet-memory embedding backfill |
| GET | `/health` | Liveness check |

Leagues covered: UEFA Champions League, Premier League, La Liga, Bundesliga, Serie A, Europa League.

---

## 5. Next steps

Roughly in priority order — the codebase's own comments already flag most of these as known
gaps ("replace with Supabase queries in production", "real per-90 stats feed", etc.):

1. **Replace seeded performance data with real rollups.** `performance_service.py`'s hardcoded
   accuracy dict is the single biggest gap — it silently feeds fake numbers into the
   Bayesian consensus weighting, the `/performance` UI, and the chat agent's tipster-accuracy
   tool. Needs a job that scores each source's predictions against settled match results and
   writes real 30-day rolling accuracy/Brier/EV-captured to Supabase.
2. **Wire a real standings + BTTS-rate source**, or build our own rollup from settled matches,
   so the relegation-desperation and BTTS "lucky not good" strategy flags reflect reality
   instead of a deterministic hash.
3. **Verify the 5 tipster scrapers against live traffic** (currently demo-mode by default) —
   confirm selectors still match each site's current DOM, add basic monitoring/alerting for
   silent scraper breakage (since failures degrade gracefully and could go unnoticed).
4. **Decide on a real per-90 stats provider** (FootyStats or similar) to replace the seeded
   shots-on-target/corners feeding `calculate_attacking_pressure`, and get an xG source for
   UCL/UEL (Understat doesn't cover cup competitions at all).
5. **Turn on The Odds API and OpenAI in a staging environment** to validate the full live
   pipeline end-to-end (odds fetch, chat streaming, embeddings) rather than only against demo
   fixtures — check API cost/rate-limit budgets for both.
6. **Harden admin auth** before any public deployment — set `ADMIN_API_TOKEN` and consider
   moving off a single shared header token.
7. **Add automated settlement** for `bet_journal` (currently the "settled" `result` field
   presumably needs manual/other update) so the embedding backfill and performance rollups
   have fresh data to work from.
8. **Expand test coverage** to the newer services (`understat_service`, `standings_service`,
   `chat_tools`, `embedding_service`, `rag_service`) — currently only `math_engine` and the
   sync pipeline have tests.
9. **Frontend polish**: multi-bankroll support, richer bet-journal filtering/analytics, surface
   the odds-history line-movement chart more prominently, chat history persistence across
   sessions.
