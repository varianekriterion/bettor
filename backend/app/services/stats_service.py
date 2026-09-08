"""
API-Football per-team season statistics for attacking-pressure inputs.

Free tier: 100 requests/day — cache each team+league+season lookup for 7 days
and track daily request count in memory so we never re-fetch the same team
within a week.
"""

from __future__ import annotations

import difflib
import logging
import time
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

API_FOOTBALL_BASE = "https://v3.football.api-sports.io"

# API-Football league IDs (v3)
LEAGUE_ID_MAP: dict[str, int] = {
    "epl": 39,
    "laliga": 140,
    "bundesliga": 78,
    "seriea": 135,
    "ucl": 2,
    "uel": 3,
}

# League-average per-match baselines when API data is missing or quota is hit.
LEAGUE_BASELINES: dict[str, dict[str, float]] = {
    "epl": {"shots_on_target": 4.5, "corners": 5.0},
    "laliga": {"shots_on_target": 4.3, "corners": 4.8},
    "bundesliga": {"shots_on_target": 4.6, "corners": 5.1},
    "seriea": {"shots_on_target": 4.2, "corners": 4.9},
    "ucl": {"shots_on_target": 4.8, "corners": 5.2},
    "uel": {"shots_on_target": 4.4, "corners": 4.9},
}
DEFAULT_BASELINE = {"shots_on_target": 4.5, "corners": 5.0}

TEAM_NAME_ALIASES: dict[str, str] = {
    "man united": "Manchester United",
    "man utd": "Manchester United",
    "man city": "Manchester City",
    "spurs": "Tottenham",
    "tottenham hotspur": "Tottenham",
    "wolves": "Wolverhampton Wanderers",
    "newcastle": "Newcastle",
    "newcastle united": "Newcastle",
    "brighton and hove albion": "Brighton",
    "atletico madrid": "Atletico Madrid",
    "athletic bilbao": "Athletic Club",
    "bayern munich": "Bayern München",
    "inter milan": "Inter",
    "ac milan": "AC Milan",
    "psg": "Paris Saint Germain",
    "paris saint germain": "Paris Saint Germain",
}

StatsSource = Literal["api_football", "baseline", "cache"]


@dataclass(frozen=True)
class TeamMatchStats:
    team: str
    league: str
    shots_on_target_per_match: float
    corners_per_match: float
    matches_played: int
    source: StatsSource
    team_id: int | None = None


# 7-day TTL cache: key -> (expires_monotonic, TeamMatchStats)
_stats_cache: dict[str, tuple[float, TeamMatchStats]] = {}
# team search ID cache: key -> (expires_monotonic, team_id)
_team_id_cache: dict[str, tuple[float, int]] = {}
# Daily request timestamps (UTC epoch seconds)
_request_log: list[float] = []


def _cache_ttl_seconds() -> int:
    return settings.stats_cache_ttl_days * 24 * 3600


def _baseline_for_league(league: str | None) -> dict[str, float]:
    if league and league in LEAGUE_BASELINES:
        return LEAGUE_BASELINES[league]
    return DEFAULT_BASELINE


def _baseline_stats(team: str, league: str) -> TeamMatchStats:
    base = _baseline_for_league(league)
    return TeamMatchStats(
        team=team,
        league=league,
        shots_on_target_per_match=base["shots_on_target"],
        corners_per_match=base["corners"],
        matches_played=0,
        source="baseline",
    )


def _cache_get(cache: dict[str, tuple[float, Any]], key: str) -> Any | None:
    entry = cache.get(key)
    if entry is None:
        return None
    expires_at, value = entry
    if time.monotonic() > expires_at:
        cache.pop(key, None)
        return None
    return value


def _cache_set(cache: dict[str, tuple[float, Any]], key: str, value: Any) -> None:
    cache[key] = (time.monotonic() + _cache_ttl_seconds(), value)


def _can_make_request() -> bool:
    now = time.time()
    cutoff = now - 86400
    global _request_log
    _request_log = [t for t in _request_log if t >= cutoff]
    return len(_request_log) < settings.api_football_daily_limit


def _record_request() -> None:
    _request_log.append(time.time())


def _headers() -> dict[str, str]:
    return {"x-apisports-key": settings.api_football_key}


def _resolve_league(league: str | None) -> str:
    return league or "epl"


def _normalize_search_name(team_name: str) -> str:
    return TEAM_NAME_ALIASES.get(team_name.strip().lower(), team_name.strip())


async def _api_get(path: str, params: dict[str, Any]) -> dict[str, Any] | None:
    if not settings.api_football_key:
        return None
    if not _can_make_request():
        logger.warning("[StatsService] API-Football daily quota reached — using baselines")
        return None

    url = f"{API_FOOTBALL_BASE}{path}"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=_headers(), params=params)
            _record_request()
            if resp.status_code == 429:
                logger.warning("[StatsService] API-Football rate limited (429)")
                return None
            if resp.status_code != 200:
                logger.warning(
                    "[StatsService] API-Football %s returned %s: %s",
                    path,
                    resp.status_code,
                    resp.text[:200],
                )
                return None
            payload = resp.json()
            errors = payload.get("errors")
            if errors:
                logger.warning("[StatsService] API-Football errors: %s", errors)
                return None
            return payload
    except Exception as exc:  # noqa: BLE001
        logger.warning("[StatsService] API-Football request failed: %s", exc)
        return None


def _pick_team_id(search_name: str, candidates: list[dict[str, Any]]) -> int | None:
    names = [c.get("team", {}).get("name", "") for c in candidates]
    match = difflib.get_close_matches(search_name, names, n=1, cutoff=0.55)
    if not match:
        return None
    chosen = match[0]
    for row in candidates:
        if row.get("team", {}).get("name") == chosen:
            return int(row["team"]["id"])
    return None


async def _resolve_team_id(team_name: str, league: str, season: int) -> int | None:
    league_id = LEAGUE_ID_MAP.get(league)
    if league_id is None:
        return None

    search_name = _normalize_search_name(team_name)
    cache_key = f"team_id:{league}:{season}:{search_name.lower()}"
    cached = _cache_get(_team_id_cache, cache_key)
    if cached is not None:
        return cached

    payload = await _api_get(
        "/teams",
        {"search": search_name, "league": league_id, "season": season},
    )
    if not payload:
        return None

    team_id = _pick_team_id(search_name, payload.get("response") or [])
    if team_id is not None:
        _cache_set(_team_id_cache, cache_key, team_id)
    return team_id


def _per_match(total: Any, played: int) -> float | None:
    try:
        if played <= 0:
            return None
        return float(total) / played
    except (TypeError, ValueError):
        return None


def _parse_team_statistics(
    team_name: str,
    league: str,
    payload: dict[str, Any],
) -> TeamMatchStats | None:
    rows = payload.get("response") or []
    if not rows:
        return None

    row = rows[0]
    fixtures = row.get("fixtures") or {}
    played_block = fixtures.get("played") or {}
    matches_played = int(played_block.get("total") or 0)

    shots = row.get("shots") or {}
    on_target_block = shots.get("on") or {}
    sot_total = on_target_block.get("total")
    sot_per_match = _per_match(sot_total, matches_played)

    corners_block = row.get("corners") or row.get("corner_kicks") or {}
    corners_total = corners_block.get("total")
    if corners_total is None and isinstance(corners_block, dict):
        corners_total = corners_block.get("won")
    corners_per_match = _per_match(corners_total, matches_played)

    base = _baseline_for_league(league)
    if sot_per_match is None:
        sot_per_match = base["shots_on_target"]
    if corners_per_match is None:
        corners_per_match = base["corners"]

    team_id = (row.get("team") or {}).get("id")
    return TeamMatchStats(
        team=team_name,
        league=league,
        shots_on_target_per_match=round(sot_per_match, 2),
        corners_per_match=round(corners_per_match, 2),
        matches_played=matches_played,
        source="api_football",
        team_id=int(team_id) if team_id is not None else None,
    )


async def get_team_stats(
    team_name: str,
    league: str | None = None,
    *,
    season: int | None = None,
) -> TeamMatchStats:
    """
    Return per-match shots-on-target and corners for a team in the current season.

    Falls back to league-average baselines when the API key is missing, quota is
    exhausted, or the lookup fails — never raises.
    """
    league_key = _resolve_league(league)
    season_year = season if season is not None else int(settings.api_football_season)

    cache_key = f"stats:{league_key}:{season_year}:{team_name.strip().lower()}"
    cached = _cache_get(_stats_cache, cache_key)
    if cached is not None:
        return TeamMatchStats(
            team=cached.team,
            league=cached.league,
            shots_on_target_per_match=cached.shots_on_target_per_match,
            corners_per_match=cached.corners_per_match,
            matches_played=cached.matches_played,
            source="cache",
            team_id=cached.team_id,
        )

    if not settings.api_football_key:
        return _baseline_stats(team_name, league_key)

    league_id = LEAGUE_ID_MAP.get(league_key)
    if league_id is None:
        return _baseline_stats(team_name, league_key)

    team_id = await _resolve_team_id(team_name, league_key, season_year)
    if team_id is None:
        logger.info("[StatsService] No API-Football match for %s (%s)", team_name, league_key)
        return _baseline_stats(team_name, league_key)

    payload = await _api_get(
        "/teams/statistics",
        {"team": team_id, "league": league_id, "season": season_year},
    )
    if not payload:
        return _baseline_stats(team_name, league_key)

    parsed = _parse_team_statistics(team_name, league_key, payload)
    if parsed is None:
        return _baseline_stats(team_name, league_key)

    _cache_set(_stats_cache, cache_key, parsed)
    return parsed


def get_quota_status() -> dict[str, int | bool]:
    """Expose cache/quota state for admin diagnostics."""
    now = time.time()
    cutoff = now - 86400
    used = len([t for t in _request_log if t >= cutoff])
    return {
        "daily_limit": settings.api_football_daily_limit,
        "requests_used_today": used,
        "requests_remaining": max(settings.api_football_daily_limit - used, 0),
        "cache_entries": len(_stats_cache),
        "api_configured": bool(settings.api_football_key),
    }
