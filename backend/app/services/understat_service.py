"""
Understat xG / xGA integration (Phase 2).

Uses the `understat` PyPI package (import name `understat`, published by
amosbastian) — an async wrapper around understat.com's match JSON. Note the
naming: there is no package literally called "understat-api" on PyPI; the
two real options are `understat` (async, aiohttp) and `understatapi`
(sync, requests). This service uses the async one since it fits FastAPI +
the rest of this codebase's async I/O. Swap the transport in `_fetch_live`
if you specifically need `understatapi` instead.

Understat only tracks EPL, La Liga, Bundesliga, Serie A, Ligue 1, and RFPL —
it does NOT have Champions League / Europa League fixture data. For "ucl"
and "uel" this service always returns seeded demo data; that's a real data
gap, not a bug, and `compute_match_edges` / the chat tools should treat
`XGStats.source == "demo"` accordingly.

Design note — trailing form, not the fixture's own result: for an upcoming
match there is by definition no post-match xG yet, so this pulls each
team's TRAILING AVERAGE xG (attack) / xGA (defense) over their last
`DEFAULT_XG_LOOKBACK` completed matches, not a lookup of this specific
fixture. It also separately computes the away side's away-venue-only
trailing xGA (`XGStats.isolated_away_xga`), which feeds the Phase 4
"motivation flag" rule in `math_engine.resolve_away_xga`.

Understat's raw match JSON isn't formally documented — `_extract_row_xg`
targets the widely-observed `{h, a, xG: {h, a}, goals: {h, a}, ...}` shape
returned by `get_team_results`. If understat.com changes its payload shape,
parsing raises / rows fail `_row_is_completed` and this service fails soft
to demo data rather than crashing the pipeline (same philosophy as
`app/scrapers/base.py`).
"""

from __future__ import annotations

import difflib
import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

from app.core.cache import cache_get, cache_set
from app.core.config import settings
from app.models.schemas import FixtureXGStats, LeagueKey, XGStats

logger = logging.getLogger(__name__)

# Leagues Understat actually covers, mapped to its URL slug.
UNDERSTAT_LEAGUE_SLUGS: dict[str, str] = {
    "epl": "EPL",
    "laliga": "La_liga",
    "bundesliga": "Bundesliga",
    "seriea": "Serie_A",
}

DEFAULT_XG_LOOKBACK = 6  # trailing completed matches to average over

# Understat's team titles occasionally diverge from The-Odds-API's; extend
# as mismatches surface in logs (`fuzzy match failed` warnings).
TEAM_NAME_ALIASES: dict[str, str] = {
    "man united": "Manchester United",
    "man utd": "Manchester United",
    "man city": "Manchester City",
    "spurs": "Tottenham",
    "wolves": "Wolverhampton Wanderers",
    "newcastle": "Newcastle United",
    "nottingham forest": "Nottingham Forest",
    "brighton": "Brighton",
    "atletico madrid": "Atletico Madrid",
    "real sociedad": "Real Sociedad",
    "bayern munich": "Bayern Munich",
    "borussia dortmund": "Borussia Dortmund",
    "inter": "Inter",
    "ac milan": "Milan",
}


def _seeded_xg(team: str, opponent: str, league: str, *, is_away: bool = False) -> XGStats:
    """
    Deterministic pseudo-xG for demo mode, unsupported leagues (UCL/UEL), or
    when a live Understat lookup fails/can't be matched. Stable across
    restarts, same spirit as `app.scrapers.prediction_sites._seeded_probs`.
    """
    digest = hashlib.sha256(f"xg|{league}|{team}|{opponent}".encode()).hexdigest()
    xg = 0.9 + (int(digest[0:2], 16) / 255.0) * 1.6       # ~0.9-2.5
    xga = 0.7 + (int(digest[2:4], 16) / 255.0) * 1.5      # ~0.7-2.2
    sot = 2.5 + (int(digest[4:6], 16) / 255.0) * 4.0      # ~2.5-6.5
    corners = 3.0 + (int(digest[6:8], 16) / 255.0) * 5.0  # ~3.0-8.0
    isolated_away_xga = None
    if is_away:
        # A correlated-but-distinct seed so it isn't identical to overall xga.
        away_digest = hashlib.sha256(f"xga-away|{league}|{team}|{opponent}".encode()).hexdigest()
        isolated_away_xga = round(0.6 + (int(away_digest[0:2], 16) / 255.0) * 1.8, 2)  # ~0.6-2.4
    return XGStats(
        team=team,
        xg=round(xg, 2),
        xga=round(xga, 2),
        shots_on_target=round(sot, 1),
        corners=round(corners, 1),
        isolated_away_xga=isolated_away_xga,
        matches_sampled=1,
        source="demo",
    )


def _best_team_match(target: str, candidates: list[str]) -> str | None:
    normalized = TEAM_NAME_ALIASES.get(target.strip().lower(), target)
    matches = difflib.get_close_matches(normalized, candidates, n=1, cutoff=0.6)
    return matches[0] if matches else None


def _extract_row_xg(row: dict[str, Any], team_is_home: bool) -> tuple[float, float]:
    """
    Pull (xG_for, xG_against) out of one `get_team_results` match row.

    Targets the commonly-observed understat.com shape:
        {"h": {"title": "..."}, "a": {"title": "..."},
         "xG": {"h": "1.234", "a": "0.987"}, "goals": {"h": "2", "a": "1"}, ...}
    """
    xg_block = row.get("xG") or row.get("xg") or {}
    side_for = "h" if team_is_home else "a"
    side_against = "a" if team_is_home else "h"
    xg_for = float(xg_block[side_for])
    xg_against = float(xg_block[side_against])
    return xg_for, xg_against


def _row_is_completed(row: dict[str, Any]) -> bool:
    """A finished match row has parseable numeric xG for both sides; a future fixture doesn't."""
    xg_block = row.get("xG") or row.get("xg") or {}
    try:
        float(xg_block.get("h"))
        float(xg_block.get("a"))
        return True
    except (TypeError, ValueError):
        return False


def _average_form(
    rows: list[dict[str, Any]],
    team_title: str,
    lookback: int,
) -> tuple[float, float] | None:
    """Average (xG_for, xG_against) over the most recent `lookback` rows. None if `rows` is empty."""
    if not rows:
        return None
    recent = rows[-lookback:]  # get_team_results is chronological; tail = most recent
    xg_for_total = 0.0
    xga_total = 0.0
    n = 0
    for row in recent:
        try:
            team_is_home = row.get("h", {}).get("title") == team_title
            xg_for, xg_against = _extract_row_xg(row, team_is_home=team_is_home)
        except (KeyError, TypeError, ValueError):
            continue
        xg_for_total += xg_for
        xga_total += xg_against
        n += 1
    if n == 0:
        return None
    return xg_for_total / n, xga_total / n


async def _fetch_live(
    home_team: str,
    away_team: str,
    league: LeagueKey | str,
    understat_league: str,
    season: str,
    lookback: int = DEFAULT_XG_LOOKBACK,
) -> FixtureXGStats | None:
    """Live Understat trailing-form lookup. Returns None (never raises) on any failure."""
    try:
        import aiohttp
        from understat import Understat
    except ImportError:
        logger.warning("`understat` package not installed — falling back to demo xG")
        return None

    try:
        async with aiohttp.ClientSession() as session:
            client = Understat(session)
            teams = await client.get_teams(understat_league, season)
            titles = [t.get("title", "") for t in teams if t.get("title")]

            home_match = _best_team_match(home_team, titles)
            away_match = _best_team_match(away_team, titles)
            if home_match is None or away_match is None:
                logger.warning(
                    "Understat: no fuzzy match for %s (home=%s, away=%s) in %s %s",
                    home_team if home_match is None else away_team,
                    home_match,
                    away_match,
                    understat_league,
                    season,
                )
                return None

            home_rows = [r for r in await client.get_team_results(home_match, season) if _row_is_completed(r)]
            away_rows = [r for r in await client.get_team_results(away_match, season) if _row_is_completed(r)]

            home_form = _average_form(home_rows, home_match, lookback)
            away_form = _average_form(away_rows, away_match, lookback)
            if home_form is None or away_form is None:
                logger.info(
                    "Understat: no completed matches yet for %s vs %s (%s %s) — too early in season",
                    home_team,
                    away_team,
                    understat_league,
                    season,
                )
                return None

            away_venue_rows = [r for r in away_rows if r.get("a", {}).get("title") == away_match]
            away_venue_form = _average_form(away_venue_rows, away_match, lookback)

            home_xg, home_xga = home_form
            away_xg, away_xga = away_form
            isolated_away_xga = away_venue_form[1] if away_venue_form is not None else away_xga

            return FixtureXGStats(
                home=XGStats(
                    team=home_team,
                    xg=round(home_xg, 2),
                    xga=round(home_xga, 2),
                    matches_sampled=min(len(home_rows), lookback) or 1,
                    source="understat",
                ),
                away=XGStats(
                    team=away_team,
                    xg=round(away_xg, 2),
                    xga=round(away_xga, 2),
                    isolated_away_xga=round(isolated_away_xga, 2),
                    matches_sampled=min(len(away_rows), lookback) or 1,
                    source="understat",
                ),
                league=league,  # type: ignore[arg-type]
                season=season,
                fetched_at=datetime.now(timezone.utc),
            )
    except Exception as exc:  # noqa: BLE001 — never crash the pipeline on a scrape/parse failure
        logger.warning(
            "Understat lookup failed for %s vs %s (%s %s): %s",
            home_team,
            away_team,
            understat_league,
            season,
            exc,
        )
        return None


async def get_fixture_xg(
    home_team: str,
    away_team: str,
    league: LeagueKey | str,
    season: str | None = None,
) -> FixtureXGStats:
    """
    Return home/away trailing-form xG + xGA ahead of one fixture (plus the
    away side's away-venue-only trailing xGA, for the motivation-flag rule).

    Falls back to deterministic seeded data when: demo mode is on, the
    league isn't tracked by Understat (ucl/uel), or the live lookup/match
    fails for any reason — this function itself never raises.
    """
    season = season or settings.understat_season
    cache_key = f"understat:{league}:{home_team}:{away_team}:{season}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    understat_league = UNDERSTAT_LEAGUE_SLUGS.get(str(league))
    result: FixtureXGStats | None = None

    if understat_league and not settings.use_demo_data:
        result = await _fetch_live(home_team, away_team, league, understat_league, season)

    if result is None:
        result = FixtureXGStats(
            home=_seeded_xg(home_team, away_team, str(league)),
            away=_seeded_xg(away_team, home_team, str(league), is_away=True),
            league=league,  # type: ignore[arg-type]
            season=season,
            fetched_at=datetime.now(timezone.utc),
        )

    cache_set(cache_key, result)
    return result
