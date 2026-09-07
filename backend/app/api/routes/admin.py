"""Admin endpoints for manual scraper refreshes."""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.config import settings
from app.models.schemas import LeagueKey
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
