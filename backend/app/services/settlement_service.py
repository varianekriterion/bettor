"""
Prediction settlement + 30-day tipster accuracy rollup.

Fetches finished match results from football-data.org, reconciles them
against stored predictions, updates prediction status (WON/LOST/VOID),
and upserts rolling aggregates into ``tipster_performance``.

Same dataclass-result + module-level last-run/running-guard shape as
``sync_service.py`` / ``embedding_service.py``.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.core.config import settings
from app.models.schemas import LEAGUE_META, LeagueKey, Outcome
from app.services.standings_service import LEAGUE_CODE_MAP
from app.services.supabase_store import get_supabase_client, is_supabase_configured

logger = logging.getLogger(__name__)

FOOTBALL_DATA_BASE = "https://api.football-data.org/v4"
VOID_MATCH_STATUSES = frozenset({"POSTPONED", "CANCELLED", "SUSPENDED", "AWARDED"})
ACTIVE_LEAGUES: list[LeagueKey] = list(LEAGUE_META.keys())  # type: ignore[assignment]


@dataclass
class SettlementResult:
    started_at: str
    finished_at: str | None = None
    trigger: str = "scheduler"
    supabase_configured: bool = False
    api_configured: bool = False
    matches_updated: int = 0
    predictions_scored: int = 0
    performance_rows_upserted: int = 0
    errors: list[str] = field(default_factory=list)
    ok: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_last_run: SettlementResult | None = None
_running = False


def get_last_settlement_run() -> SettlementResult | None:
    return _last_run


def is_settlement_running() -> bool:
    return _running


def _normalize_team(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _teams_match(api_name: str, db_name: str) -> bool:
    a = _normalize_team(api_name)
    b = _normalize_team(db_name)
    if not a or not b:
        return False
    return a in b or b in a


def _parse_fd_outcome(match: dict[str, Any]) -> Outcome | None:
    """Map a football-data.org finished match to home/draw/away."""
    status = (match.get("status") or "").upper()
    if status in VOID_MATCH_STATUSES:
        return None

    score = match.get("score") or {}
    winner = (score.get("winner") or "").upper()
    if winner == "HOME_TEAM":
        return "home"
    if winner == "AWAY_TEAM":
        return "away"
    if winner == "DRAW":
        return "draw"

    full_time = score.get("fullTime") or {}
    home_goals = full_time.get("home")
    away_goals = full_time.get("away")
    if home_goals is None or away_goals is None:
        return None
    if home_goals > away_goals:
        return "home"
    if away_goals > home_goals:
        return "away"
    return "draw"


def _is_void_match(match: dict[str, Any]) -> bool:
    return (match.get("status") or "").upper() in VOID_MATCH_STATUSES


def _same_kickoff_day(api_utc: str, db_commence: str) -> bool:
    try:
        api_dt = datetime.fromisoformat(api_utc.replace("Z", "+00:00")).astimezone(timezone.utc)
        db_dt = datetime.fromisoformat(db_commence.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return False
    return api_dt.date() == db_dt.date()


def _score_pick(pick: str, outcome: Outcome) -> str:
    return "WON" if pick == outcome else "LOST"


def _multiclass_brier(
    home_prob: float,
    draw_prob: float,
    away_prob: float,
    actual: Outcome,
) -> float:
    actuals = {"home": 0.0, "draw": 0.0, "away": 0.0}
    actuals[actual] = 1.0
    return (
        (home_prob - actuals["home"]) ** 2
        + (draw_prob - actuals["draw"]) ** 2
        + (away_prob - actuals["away"]) ** 2
    )


async def _fetch_finished_matches(
    league: LeagueKey,
    date_from: datetime,
    date_to: datetime,
) -> list[dict[str, Any]]:
    api_code = LEAGUE_CODE_MAP.get(league)
    if not api_code or not settings.football_data_api_key:
        return []

    url = f"{FOOTBALL_DATA_BASE}/competitions/{api_code}/matches"
    params = {
        "status": "FINISHED",
        "dateFrom": date_from.strftime("%Y-%m-%d"),
        "dateTo": date_to.strftime("%Y-%m-%d"),
    }
    headers = {"X-Auth-Token": settings.football_data_api_key}

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(url, headers=headers, params=params)
            if resp.status_code != 200:
                logger.warning(
                    "[Settlement] football-data %s returned %s: %s",
                    api_code,
                    resp.status_code,
                    resp.text[:200],
                )
                return []
            payload = resp.json()
            return list(payload.get("matches") or [])
    except Exception as exc:  # noqa: BLE001
        logger.warning("[Settlement] football-data fetch failed for %s: %s", league, exc)
        return []


def _fetch_unsettled_matches(client: Any, league: LeagueKey, since: datetime) -> list[dict[str, Any]]:
    try:
        resp = (
            client.table("matches")
            .select("id, league_key, home_team, away_team, commence_time, status, result_outcome")
            .eq("league_key", league)
            .lt("commence_time", datetime.now(timezone.utc).isoformat())
            .gte("commence_time", since.isoformat())
            .neq("status", "finished")
            .execute()
        )
        return list(resp.data or [])
    except Exception as exc:  # noqa: BLE001
        logger.warning("[Settlement] failed to load unsettled matches for %s: %s", league, exc)
        return []


def _match_fd_to_db(fd_match: dict[str, Any], db_matches: list[dict[str, Any]]) -> dict[str, Any] | None:
    home_api = (fd_match.get("homeTeam") or {}).get("name", "")
    away_api = (fd_match.get("awayTeam") or {}).get("name", "")
    utc_date = fd_match.get("utcDate") or ""

    for row in db_matches:
        if not _teams_match(home_api, row.get("home_team", "")):
            continue
        if not _teams_match(away_api, row.get("away_team", "")):
            continue
        if utc_date and row.get("commence_time") and not _same_kickoff_day(utc_date, row["commence_time"]):
            continue
        return row
    return None


def _update_match_result(
    client: Any,
    match_id: str,
    *,
    outcome: Outcome | None,
    voided: bool,
) -> None:
    now_iso = datetime.now(timezone.utc).isoformat()
    payload: dict[str, Any] = {
        "status": "void" if voided else "finished",
        "updated_at": now_iso,
    }
    if outcome is not None:
        payload["result_outcome"] = outcome
    client.table("matches").update(payload).eq("id", match_id).execute()


def _fetch_unscored_predictions(client: Any, match_ids: list[str]) -> list[dict[str, Any]]:
    if not match_ids:
        return []
    try:
        resp = (
            client.table("predictions")
            .select("id, match_id, source, pick, home_prob, draw_prob, away_prob, scraped_at, status")
            .in_("match_id", match_ids)
            .is_("status", "null")
            .execute()
        )
        return list(resp.data or [])
    except Exception as exc:  # noqa: BLE001
        logger.warning("[Settlement] failed to load unscored predictions: %s", exc)
        return []


def _fetch_match_commence_times(client: Any, match_ids: list[str]) -> dict[str, str]:
    if not match_ids:
        return {}
    try:
        resp = (
            client.table("matches")
            .select("id, commence_time")
            .in_("id", match_ids)
            .execute()
        )
        return {row["id"]: row["commence_time"] for row in (resp.data or [])}
    except Exception as exc:  # noqa: BLE001
        logger.warning("[Settlement] failed to load match kickoffs: %s", exc)
        return {}


def _dedupe_predictions(
    predictions: list[dict[str, Any]],
    commence_by_match: dict[str, str],
) -> list[dict[str, Any]]:
    """Keep one row per (match_id, source): latest scrape at or before kickoff."""
    buckets: dict[tuple[str, str], dict[str, Any]] = {}

    for pred in predictions:
        key = (pred["match_id"], pred["source"])
        commence_raw = commence_by_match.get(pred["match_id"])
        scraped_raw = pred.get("scraped_at")
        if not commence_raw or not scraped_raw:
            chosen = buckets.get(key)
            if chosen is None:
                buckets[key] = pred
            continue

        commence = datetime.fromisoformat(commence_raw.replace("Z", "+00:00"))
        scraped = datetime.fromisoformat(scraped_raw.replace("Z", "+00:00"))
        if scraped > commence:
            continue

        existing = buckets.get(key)
        if existing is None:
            buckets[key] = pred
            continue
        existing_scraped = datetime.fromisoformat(existing["scraped_at"].replace("Z", "+00:00"))
        if scraped > existing_scraped:
            buckets[key] = pred

    return list(buckets.values())


def _score_predictions(
    client: Any,
    predictions: list[dict[str, Any]],
    outcomes_by_match: dict[str, Outcome | None],
    voided_matches: set[str],
) -> int:
    scored = 0
    for pred in predictions:
        match_id = pred["match_id"]
        if match_id in voided_matches:
            status = "VOID"
        else:
            outcome = outcomes_by_match.get(match_id)
            if outcome is None:
                continue
            status = _score_pick(pred["pick"], outcome)

        try:
            client.table("predictions").update({"status": status}).eq("id", pred["id"]).execute()
            scored += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("[Settlement] failed to update prediction %s: %s", pred["id"], exc)
    return scored


def _rollup_tipster_performance(client: Any, window_days: int) -> int:
    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    try:
        resp = (
            client.table("predictions")
            .select(
                "source, pick, home_prob, draw_prob, away_prob, status, "
                "matches!inner(league_key, result_outcome, commence_time, status)"
            )
            .in_("status", ["WON", "LOST"])
            .gte("matches.commence_time", since.isoformat())
            .eq("matches.status", "finished")
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[Settlement] rollup query failed: %s", exc)
        return 0

    rows = resp.data or []
    aggregates: dict[tuple[str, str], dict[str, float | int]] = {}

    for row in rows:
        match = row.get("matches") or {}
        league = match.get("league_key")
        outcome = match.get("result_outcome")
        if not league or not outcome:
            continue

        source = row["source"]
        key = (source, league)
        bucket = aggregates.setdefault(
            key,
            {"total": 0, "won": 0, "brier_sum": 0.0},
        )
        bucket["total"] = int(bucket["total"]) + 1
        if row.get("status") == "WON":
            bucket["won"] = int(bucket["won"]) + 1
        bucket["brier_sum"] = float(bucket["brier_sum"]) + _multiclass_brier(
            float(row["home_prob"]),
            float(row["draw_prob"]),
            float(row["away_prob"]),
            outcome,  # type: ignore[arg-type]
        )

    now_iso = datetime.now(timezone.utc).isoformat()
    upserted = 0
    for (source, league), stats in aggregates.items():
        total = int(stats["total"])
        won = int(stats["won"])
        win_rate = round(won / total, 4) if total else 0.0
        brier = round(float(stats["brier_sum"]) / total, 6) if total else 0.25
        payload = {
            "source": source,
            "league": league,
            "total_picks": total,
            "won_picks": won,
            "win_rate": win_rate,
            "brier_score": brier,
            "updated_at": now_iso,
        }
        try:
            client.table("tipster_performance").upsert(payload, on_conflict="source,league").execute()
            upserted += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[Settlement] failed to upsert tipster_performance %s/%s: %s",
                source,
                league,
                exc,
            )
    return upserted


async def run_prediction_settlement(
    *,
    trigger: str = "scheduler",
    lookback_days: int | None = None,
    rollup_window_days: int | None = None,
) -> SettlementResult:
    """Settle predictions against football-data.org results and refresh rollups."""
    global _last_run, _running

    if _running:
        logger.info("Settlement already running — skipping overlapping trigger=%s", trigger)
        if _last_run:
            return _last_run
        return SettlementResult(
            started_at=datetime.now(timezone.utc).isoformat(),
            trigger=trigger,
            ok=False,
        )

    _running = True
    lookback = lookback_days if lookback_days is not None else settings.settlement_lookback_days
    rollup_window = rollup_window_days if rollup_window_days is not None else settings.settlement_rollup_days

    result = SettlementResult(
        started_at=datetime.now(timezone.utc).isoformat(),
        trigger=trigger,
        supabase_configured=is_supabase_configured(),
        api_configured=bool(settings.football_data_api_key),
    )

    try:
        if not result.supabase_configured:
            result.ok = False
            result.errors.append("supabase_not_configured")
            logger.warning("run_prediction_settlement: Supabase not configured")
            return result

        if not result.api_configured:
            result.ok = False
            result.errors.append("football_data_api_key_missing")
            logger.warning("run_prediction_settlement: FOOTBALL_DATA_API_KEY not set")
            return result

        client = get_supabase_client()
        if client is None:
            result.ok = False
            result.errors.append("supabase_client_unavailable")
            return result

        now = datetime.now(timezone.utc)
        date_from = now - timedelta(days=lookback)
        outcomes_by_match: dict[str, Outcome | None] = {}
        voided_matches: set[str] = set()
        updated_match_ids: list[str] = []

        for league in ACTIVE_LEAGUES:
            fd_matches = await _fetch_finished_matches(league, date_from, now)
            db_matches = _fetch_unsettled_matches(client, league, date_from)

            for fd_match in fd_matches:
                db_row = _match_fd_to_db(fd_match, db_matches)
                if db_row is None:
                    continue

                match_id = db_row["id"]
                if _is_void_match(fd_match):
                    voided_matches.add(match_id)
                    outcomes_by_match[match_id] = None
                    _update_match_result(client, match_id, outcome=None, voided=True)
                else:
                    outcome = _parse_fd_outcome(fd_match)
                    if outcome is None:
                        continue
                    outcomes_by_match[match_id] = outcome
                    _update_match_result(client, match_id, outcome=outcome, voided=False)

                updated_match_ids.append(match_id)
                result.matches_updated += 1

        match_ids = list(dict.fromkeys(updated_match_ids))
        unscored = _fetch_unscored_predictions(client, match_ids)
        commence_by_match = _fetch_match_commence_times(client, match_ids)
        deduped = _dedupe_predictions(unscored, commence_by_match)
        result.predictions_scored = _score_predictions(
            client,
            deduped,
            outcomes_by_match,
            voided_matches,
        )

        result.performance_rows_upserted = _rollup_tipster_performance(client, rollup_window)

        from app.services.performance_service import invalidate_performance_cache

        invalidate_performance_cache()

        logger.info(
            "Settlement complete trigger=%s matches=%d predictions=%d performance_rows=%d",
            trigger,
            result.matches_updated,
            result.predictions_scored,
            result.performance_rows_upserted,
        )
    except Exception as exc:  # noqa: BLE001
        result.ok = False
        result.errors.append(str(exc))
        logger.exception("run_prediction_settlement crashed")
    finally:
        result.finished_at = datetime.now(timezone.utc).isoformat()
        _last_run = result
        _running = False

    return result
