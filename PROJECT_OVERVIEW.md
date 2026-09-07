# What Bettor Does

**Bettor** (internally "BetConsensus Engine") is a sports-betting analytics tool for European football. It aggregates predictions from multiple tipster/prediction websites, blends them into a single **consensus probability** for each match outcome, compares that probability against real bookmaker odds to find mispriced ("+EV") bets, and tells the user how much to stake using the **Kelly Criterion**.

In short: *"Do multiple independent prediction sources agree the bookmaker's odds are wrong, and if so, how much should I bet?"*

## The pipeline

1. **Collect odds** — Live bookmaker odds (1X2 markets) come from [The Odds API](https://the-odds-api.com), or deterministic demo fixtures when no API key is configured.
2. **Collect predictions** — Scrapers pull win/draw/win probability picks for the same fixtures from five prediction sites: Forebet, PredictZ, WinDrawWin, Betimate, FootballWhispers. Each scraper fails soft — if a site blocks/CAPTCHAs/errors, it's skipped and a seeded, deterministic "demo" prediction is used instead so the pipeline never hard-crashes and results stay reproducible.
3. **Devig the bookmaker odds** — Convert odds to implied probabilities and strip the bookmaker's overround (vig) using either:
   - **Multiplicative** (proportional) devigging, or
   - **Power method** (Shin-style), which better corrects for favourite-longshot bias.
4. **Build consensus** — Blend the prediction sources into one probability per outcome (home/draw/away) using a **performance-weighted Bayesian average**: each source is weighted by its rolling 30-day accuracy (weak sources floored, not zeroed), then blended with a market-derived prior so sparse data doesn't overreact.
5. **Compute edge** — For each outcome, calculate:
   - **EV%** = `(p · (odds − 1) − (1 − p)) × 100` — expected value of the bet given the consensus probability `p` and bookmaker decimal `odds`.
   - **Kelly stake** — `f* = (b·p − q) / b` (full Kelly), scaled by a fractional multiplier (default **0.25×, Quarter-Kelly**) as a bankroll drawdown safeguard. Negative-edge bets are floored to a zero stake.
6. **Track accuracy** — As match results settle, each prediction source's historical hit rate is recomputed, which feeds back into step 4's weighting for future matches (a simple self-correcting/learning loop).
7. **Surface it** — A dashboard shows live matches with consensus %, EV%, and recommended Kelly stake; a matrix view compares each source's raw pick against the master consensus; a calculator lets a user plug in arbitrary odds/probabilities/bankroll; a performance page ranks sources by accuracy; and a bet journal lets the user log bets they actually placed.

## Stack

| Layer | Tech |
|---|---|
| Frontend | Next.js 14 (App Router) + TypeScript, Tailwind CSS, Radix/Shadcn-style components, Recharts, TanStack Query |
| Backend | Python FastAPI, httpx + BeautifulSoup (scraping), Pandas/NumPy, APScheduler (background jobs) |
| Data sources | The Odds API (bookmaker odds) + scrapers for Forebet, PredictZ, WinDrawWin, Betimate, FootballWhispers |
| DB / Auth | Supabase (Postgres, Row-Level Security, Auth) |

## Repo layout

```
bettor/
├── frontend/            Next.js UI
│   └── src/app/
│       ├── page.tsx          # "/" — Dashboard (live matches, league filter, +EV toggle)
│       ├── matrix/            # "/matrix" — per-source picks vs. consensus
│       ├── calculator/        # "/calculator" — EV / Kelly calculator widget
│       └── performance/       # "/performance" — source accuracy charts & leaderboard
├── backend/              FastAPI service
│   └── app/
│       ├── api/routes/        # matches, predictions, calculator, performance, admin
│       ├── core/
│       │   ├── math_engine.py  # devig, Bayesian consensus, EV, Kelly (the core quant logic)
│       │   ├── scheduler.py    # APScheduler: refreshes predictions every 30 min
│       │   └── config.py
│       ├── scrapers/          # per-site scrapers + deterministic demo fallbacks
│       ├── services/          # consensus, odds, performance, sync, Supabase persistence
│       └── models/schemas.py
└── supabase/
    └── migrations/         # leagues, matches, odds_snapshots, predictions, consensus_runs, bet_journal, etc.
```

## Key API endpoints (FastAPI, `/api/v1`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/matches` | Live match feed with consensus, EV%, Kelly% (filter by `league`, `positive_ev_only`, `bankroll`) |
| GET | `/predictions/matrix` | Per-source prediction matrix vs. consensus |
| POST | `/calculator` | Ad-hoc +EV / Kelly calculation |
| GET | `/performance` | Per-league source accuracy |
| GET | `/performance/leaderboard` | Global 30-day source accuracy ranking |
| POST | `/admin/sync` | Manual scraper refresh |
| GET | `/admin/sync/status` | Last sync time + scheduler status |

Leagues covered: **UEFA Champions League, Premier League, La Liga, Bundesliga, Serie A, Europa League.**

## Notable design choices

- **Fail-soft scraping** — any blocked/rate-limited source degrades gracefully to seeded demo data rather than breaking the consensus calc.
- **Demo mode by default** (`USE_DEMO_DATA=true`) — the whole app runs end-to-end with deterministic fixtures, no API keys or live scraping required, useful for development/demoing.
- **Conservative staking by default** — Quarter-Kelly rather than full Kelly, to reduce variance/drawdown risk.
- **Supabase is optional** — without it, the frontend bet journal just falls back to browser storage; with it, snapshots/consensus runs/journal entries persist server-side under RLS.
