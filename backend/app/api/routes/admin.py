"""Admin endpoints for manual scraper refreshes."""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.config import settings
from app.models.schemas import LeagueKey
from app.services.embedding_service import backfill_bet_memory, get_last_embed_run, is_embed_running
from app.services.settlement_service import (
    get_last_settlement_run,
    is_settlement_running,
    run_prediction_settlement,
)
from app.services.sync_service import (
    ACTIVE_LEAGUES,
    get_last_sync,
    is_sync_running,
    sync_league_predictions,
)

router = APIRouter(prefix="/admin", tags=["admin"])


class SyncRequest(BaseModel):
    leagues: list[LeagueKey] | None = Field(
        default=None,
        description="Subset of leagues to sync; defaults to all active target leagues",
    )


def _authorize(x_admin_token: str | None) -> None:
    expected = settings.admin_api_token.strip()
    if not expected:
        # Open in local/dev when token unset
        return
    if not x_admin_token or x_admin_token != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Admin-Token")


@router.post("/sync")
async def trigger_sync(
    body: SyncRequest | None = None,
    league: LeagueKey | None = Query(
        default=None,
        description="Optional single-league shortcut (ignored if body.leagues set)",
    ),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    """
    Manually trigger scraper refresh for active leagues.
    Recomputes Bayesian consensus from remaining sources when individual sites fail.
    """
    _authorize(x_admin_token)

    if is_sync_running():
        last = get_last_sync()
        return {
            "status": "already_running",
            "last_sync": last.to_dict() if last else None,
        }

    leagues: list[LeagueKey] | None = None
    if body and body.leagues:
        leagues = body.leagues
    elif league:
        leagues = [league]

    result = await sync_league_predictions(leagues=leagues, trigger="admin")
    return {"status": "completed", "result": result.to_dict()}


@router.get("/sync/status")
async def sync_status(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    _authorize(x_admin_token)
    last = get_last_sync()
    return {
        "running": is_sync_running(),
        "active_leagues": ACTIVE_LEAGUES,
        "interval_minutes": settings.sync_interval_minutes,
        "scheduler_enabled": settings.scheduler_enabled,
        "last_sync": last.to_dict() if last else None,
    }


class EmbedBetMemoryRequest(BaseModel):
    limit: int | None = Field(
        default=None,
        gt=0,
        description="Max settled bets to embed this run; defaults to BET_MEMORY_BATCH_SIZE",
    )


@router.post("/embed-bet-memory")
async def trigger_embed_bet_memory(
    body: EmbedBetMemoryRequest | None = None,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    """
    Manually trigger the Phase 1 bet-memory embedding backfill (also runs
    on a schedule — see BET_MEMORY_EMBED_INTERVAL_MINUTES).
    """
    _authorize(x_admin_token)

    if is_embed_running():
        last = get_last_embed_run()
        return {
            "status": "already_running",
            "last_run": last.to_dict() if last else None,
        }

    limit = body.limit if body else None
    result = await backfill_bet_memory(limit=limit, trigger="admin")
    return {"status": "completed", "result": result.to_dict()}


@router.get("/embed-bet-memory/status")
async def embed_bet_memory_status(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    _authorize(x_admin_token)
    last = get_last_embed_run()
    return {
        "running": is_embed_running(),
        "interval_minutes": settings.bet_memory_embed_interval_minutes,
        "batch_size": settings.bet_memory_batch_size,
        "scheduler_enabled": settings.scheduler_enabled,
        "last_run": last.to_dict() if last else None,
    }


class SettleRequest(BaseModel):
    lookback_days: int | None = Field(
        default=None,
        gt=0,
        le=90,
        description="Days of finished matches to fetch from football-data.org",
    )
    rollup_window_days: int | None = Field(
        default=None,
        gt=0,
        le=90,
        description="Rolling window for tipster_performance aggregates",
    )


@router.post("/settle")
async def trigger_settlement(
    body: SettleRequest | None = None,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    """
    Manually settle predictions against football-data.org finished matches
    and refresh 30-day tipster accuracy rollups.
    """
    _authorize(x_admin_token)

    if is_settlement_running():
        last = get_last_settlement_run()
        return {
            "status": "already_running",
            "last_run": last.to_dict() if last else None,
        }

    lookback = body.lookback_days if body else None
    rollup = body.rollup_window_days if body else None
    result = await run_prediction_settlement(
        trigger="admin",
        lookback_days=lookback,
        rollup_window_days=rollup,
    )
    return {"status": "completed", "result": result.to_dict()}


@router.get("/settle/status")
async def settlement_status(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    _authorize(x_admin_token)
    last = get_last_settlement_run()
    return {
        "running": is_settlement_running(),
        "scheduler_enabled": settings.scheduler_enabled,
        "settlement_enabled": settings.settlement_enabled,
        "rollup_window_days": settings.settlement_rollup_days,
        "lookback_days": settings.settlement_lookback_days,
        "cron_utc": f"{settings.settlement_cron_hour:02d}:{settings.settlement_cron_minute:02d}",
        "last_run": last.to_dict() if last else None,
    }


@router.get("/stats/team")
async def stats_team_dry_run(
    name: str = Query(..., description="Team name, e.g. Arsenal"),
    league: LeagueKey = Query(default="epl"),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    """Dry-run API-Football team statistics lookup (cached 7 days)."""
    from app.services.stats_service import get_quota_status, get_team_stats

    _authorize(x_admin_token)
    stats = await get_team_stats(name, league=league)
    return {
        "team": stats.team,
        "league": stats.league,
        "shots_on_target_per_match": stats.shots_on_target_per_match,
        "corners_per_match": stats.corners_per_match,
        "matches_played": stats.matches_played,
        "source": stats.source,
        "team_id": stats.team_id,
        "quota": get_quota_status(),
    }
