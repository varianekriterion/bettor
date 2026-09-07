# BetConsensus Engine

Production-oriented stack for aggregating European football predictions, computing a Bayesian consensus probability, comparing against vig-free bookmaker odds, and sizing stakes with fractional Kelly.

## Stack

| Layer | Tech |
|-------|------|
| Frontend | Next.js 14 (App Router), TypeScript, Tailwind, Radix/Shadcn-style UI, Recharts |
| Backend | Python FastAPI, httpx, BeautifulSoup, Pandas/NumPy |
| Data | The-Odds-API + scrapers (Forebet, PredictZ, WinDrawWin, Betimate, FootballWhispers) |
| DB / Auth | Supabase (Postgres + RLS + Auth) |

## Core math

- **Devigging** — multiplicative (proportional) and power methods
- **Consensus** — performance-weighted Bayesian blend with market prior (30-day source accuracy)
- **EV%** — `(p · (odds − 1) − (1 − p)) × 100`
- **Kelly** — `f* = (b·p − q) / b` with default **0.25× (Quarter-Kelly)**

## Project layout

```
Bettor/
├── frontend/          # Next.js UI
├── backend/           # FastAPI engine + scrapers
└── supabase/          # SQL migrations
```

## Quick start

### 1. Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python run.py
```

API docs: http://127.0.0.1:8000/docs  
Health: http://127.0.0.1:8000/health

`USE_DEMO_DATA=true` (default) serves deterministic fixtures so the UI works without live scrape/API keys.

### 2. Frontend

```bash
cd frontend
cp .env.local.example .env.local
npm install
npm run dev
```

Open http://localhost:3000

The UI uses TanStack Query against FastAPI (`/api/v1/matches`, `/calculator`, `/performance/leaderboard`, matrix). League filters update query params live. Bet Journal writes to Supabase `bet_journal` when `NEXT_PUBLIC_SUPABASE_URL` + `NEXT_PUBLIC_SUPABASE_ANON_KEY` are set (anonymous auth or signed-in user); otherwise it stores in the browser.

### 3. Supabase (optional)

Apply `supabase/migrations/001_initial_schema.sql` in the Supabase SQL editor. Set `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` in `backend/.env` when you persist snapshots. For the frontend journal, also enable Anonymous Sign-Ins under Authentication → Providers (or use a normal auth session).

### 4. Live odds

Set `ODDS_API_KEY` from [The Odds API](https://the-odds-api.com) and `USE_DEMO_DATA=false`.

## API surface

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/v1/matches` | Live feed with consensus, EV%, Kelly% |
| GET | `/api/v1/predictions/matrix` | Aggregator matrix |
| POST | `/api/v1/calculator` | +EV / Kelly calculator |
| GET | `/api/v1/performance` | Per-league source accuracy |
| GET | `/api/v1/performance/leaderboard` | Global 30-day ranking |
| POST | `/api/v1/admin/sync` | Manual scraper refresh (optional `X-Admin-Token`) |
| GET | `/api/v1/admin/sync/status` | Last sync + scheduler status |

Query params on matches: `league`, `positive_ev_only`, `bankroll`.

Background sync: APScheduler runs `sync_league_predictions` every 30 minutes for EPL, La Liga, Bundesliga, Serie A, UCL, and UEL. Failed / 403 / CAPTCHA sources are skipped and consensus is recomputed from remaining scrapers. Results are written to Supabase `predictions` and `consensus_runs` when `SUPABASE_URL` + `SUPABASE_SERVICE_KEY` are set.

## UI routes

- `/` — Dashboard (league filters, +EV toggle)
- `/matrix` — Source comparison vs master consensus
- `/calculator` — Interactive bankroll / odds / probability widget
- `/performance` — Accuracy charts and leaderboards

## Tests

```bash
cd backend
source .venv/bin/activate
pytest -q
```

## Leagues

UEFA Champions League · Premier League · La Liga · Bundesliga · Serie A · Europa League

## Notes

Scrapers fail soft: rate-limited, retried, and fall back to seeded demo predictions so the consensus pipeline never hard-crashes. Replace demo accuracy seeds in `performance_service.py` with Supabase rollups once match results are settled.
# bettor
