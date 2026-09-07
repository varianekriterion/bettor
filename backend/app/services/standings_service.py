"""
Seeded league-standings + team-form context for the Phase 2/4 strategy
rules (relegation-desperation flag, BTTS-rate penalty). Same "demo seed,
replace with real rollups later" philosophy as
`app.services.performance_service` — see its module docstring note about
replacing seeds with Supabase rollups once match results are settled.

Cup competitions (UCL/UEL) aren't a relegation format, so standings context
is always None / the desperation flag is always False for them.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from app.core.math_engine import flag_relegation_desperation
from app.models.schemas import LeagueKey

# Total league matches per season — used to compute "season % complete".
# 0 marks a non-relegation (cup) competition.
TOTAL_MATCHES_IN_SEASON: dict[str, int] = {
    "epl": 38,
    "laliga": 38,
    "seriea": 38,
    "bundesliga": 34,
    "ucl": 0,
    "uel": 0,
}

# Points total of the last "safe" (non-relegation-zone) table position —
# the cutoff each team's points are compared against.
RELEGATION_CUTOFF_SEED: dict[str, int] = {
    "epl": 34,
    "laliga": 36,
    "seriea": 34,
    "bundesliga": 30,
}


@dataclass(frozen=True)
class StandingsContext:
    team: str
    league: str
    points: int
    matches_played: int
    relegation_zone_points: int
    total_matches_in_season: int


def _seeded_standings(team: str, league: str) -> StandingsContext:
    """Deterministic pseudo-standings, stable across restarts."""
    digest = hashlib.sha256(f"standings|{league}|{team}".encode()).hexdigest()
    total = TOTAL_MATCHES_IN_SEASON.get(league, 38)
    # ~68-98% of the season played — biased late so the flag is exercisable in demo mode.
    played_frac = 0.68 + (int(digest[0:2], 16) / 255.0) * 0.30
    matches_played = min(round(total * played_frac), total)

    cutoff = RELEGATION_CUTOFF_SEED.get(league, 34)
    # Spread points from ~6 below to ~18 above the cutoff, so the seed mixes
    # comfortably-safe / borderline / genuinely-battling teams.
    points_delta = round((int(digest[2:4], 16) / 255.0) * 24 - 6)
    points = max(0, cutoff + points_delta)

    return StandingsContext(
        team=team,
        league=league,
        points=points,
        matches_played=matches_played,
        relegation_zone_points=cutoff,
        total_matches_in_season=total,
    )


def get_standings_context(team: str, league: LeagueKey | str) -> StandingsContext | None:
    """None for cup competitions (ucl/uel), where relegation doesn't apply."""
    league_str = str(league)
    if TOTAL_MATCHES_IN_SEASON.get(league_str, 0) <= 0:
        return None
    return _seeded_standings(team, league_str)


def get_relegation_desperation_flag(team: str, league: LeagueKey | str) -> bool:
    """Wraps `math_engine.flag_relegation_desperation` with seeded standings."""
    ctx = get_standings_context(team, league)
    if ctx is None:
        return False
    return flag_relegation_desperation(
        team_points=ctx.points,
        relegation_zone_points=ctx.relegation_zone_points,
        matches_played=ctx.matches_played,
        total_matches_in_season=ctx.total_matches_in_season,
    )


def _seeded_btts_rate(team: str, league: str) -> float:
    digest = hashlib.sha256(f"btts|{league}|{team}".encode()).hexdigest()
    return round(0.35 + (int(digest[0:2], 16) / 255.0) * 0.45, 3)  # ~0.35-0.80


def get_btts_rate(team: str, league: LeagueKey | str) -> float:
    """
    Seeded both-teams-to-score rate for `is_btts_lucky_not_good()`.
    Replace with a real rollup (e.g. FootyStats, or our own settled-match
    history) once available — same seed-then-swap pattern as
    `performance_service._PERFORMANCE_SEED`.
    """
    return _seeded_btts_rate(team, str(league))
