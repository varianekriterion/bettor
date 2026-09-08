"""
League-standings + team-form context for Phase 2/4 strategy rules
(relegation-desperation flag, BTTS-rate penalty).

Standings are fetched live from football-data.org v4 when
``settings.football_data_api_key`` is set; otherwise the desperation
flag falls back to neutral defaults. BTTS rates remain seeded until a
real rollup source is wired (Step 4).
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, Optional

import httpx

from app.core.config import settings
from app.core.math_engine import flag_relegation_desperation
from app.models.schemas import LeagueKey

# Mapping Bettor internal league codes to Football-Data.org codes
LEAGUE_CODE_MAP: dict[str, str] = {
    "epl": "PL",
    "laliga": "PD",
    "bundesliga": "BL1",
    "seriea": "SA",
    "ucl": "CL",
    "uel": "EL",
}

# In-memory cache so we never spam the free tier rate limit
_STANDINGS_CACHE: Dict[str, Dict[str, Any]] = {}


async def get_real_league_standings(league_code: str) -> Optional[Dict[str, Any]]:
    """
    Fetches real standings from football-data.org v4.
    Caches in-memory to prevent rate-limit throttling (10 requests/min).
    """
    api_code = LEAGUE_CODE_MAP.get(league_code.lower())
    if not api_code:
        return None

    if api_code in _STANDINGS_CACHE:
        return _STANDINGS_CACHE[api_code]

    if not settings.football_data_api_key:
        return None

    url = f"https://api.football-data.org/v4/competitions/{api_code}/standings"
    headers = {"X-Auth-Token": settings.football_data_api_key}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                _STANDINGS_CACHE[api_code] = data
                return data
            print(f"[StandingsService] Error {resp.status_code}: {resp.text}")
            return None
    except Exception as e:
        print(f"[StandingsService] Failed to fetch live standings: {e}")
        return None


async def get_team_table_context(league_code: str, team_name: str) -> Dict[str, Any]:
    """
    Returns points, position, relegation line delta, and matches played
    to accurately feed the Desperation / Motivation factor in math_engine.py.
    """
    data = await get_real_league_standings(league_code)
    if not data or "standings" not in data:
        return {
            "position": 10,
            "points": 40,
            "points_to_relegation": 15,
            "season_completion": 0.5,
        }

    table = data["standings"][0]["table"]
    total_teams = len(table)
    relegation_cutoff_idx = total_teams - 3
    relegation_threshold_points = table[relegation_cutoff_idx]["points"]
    total_season_games = (total_teams - 1) * 2

    for row in table:
        if team_name.lower() in row["team"]["name"].lower():
            points = row["points"]
            played = row["playedGames"]
            season_completion = played / total_season_games if total_season_games else 0.5

            return {
                "position": row["position"],
                "points": points,
                "points_to_relegation": points - relegation_threshold_points,
                "season_completion": season_completion,
                "goal_difference": row["goalDifference"],
                "matches_played": played,
                "total_matches_in_season": total_season_games,
            }

    return {
        "position": 10,
        "points": 40,
        "points_to_relegation": 15,
        "season_completion": 0.5,
    }


async def get_relegation_desperation_flag(team: str, league: LeagueKey | str) -> bool:
    """Wraps ``math_engine.flag_relegation_desperation`` with live standings."""
    league_str = str(league)
    if league_str in ("ucl", "uel"):
        return False

    ctx = await get_team_table_context(league_str, team)
    relegation_zone_points = ctx["points"] - ctx["points_to_relegation"]
    matches_played = ctx.get("matches_played")
    total_matches = ctx.get("total_matches_in_season")

    if matches_played is None or total_matches is None:
        total_matches = 38
        matches_played = round(ctx["season_completion"] * total_matches)

    return flag_relegation_desperation(
        team_points=ctx["points"],
        relegation_zone_points=relegation_zone_points,
        matches_played=matches_played,
        total_matches_in_season=total_matches,
    )


def _seeded_btts_rate(team: str, league: str) -> float:
    digest = hashlib.sha256(f"btts|{league}|{team}".encode()).hexdigest()
    return round(0.35 + (int(digest[0:2], 16) / 255.0) * 0.45, 3)


def get_btts_rate(team: str, league: LeagueKey | str) -> float:
    """
    Seeded both-teams-to-score rate for ``is_btts_lucky_not_good()``.
    Replace with a real rollup once available — same seed-then-swap pattern
    as ``performance_service._PERFORMANCE_SEED``.
    """
    return _seeded_btts_rate(team, str(league))
