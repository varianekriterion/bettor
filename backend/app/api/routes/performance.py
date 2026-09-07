"""Model performance leaderboard endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.models.schemas import LeagueKey, LeaguePerformanceSummary, SourcePerformance
from app.services.performance_service import get_global_leaderboard, get_league_performance

router = APIRouter()


@router.get("/performance", response_model=list[LeaguePerformanceSummary])
async def league_performance(
    league: LeagueKey | None = Query(default=None),
) -> list[LeaguePerformanceSummary]:
    """Historical accuracy leaderboard per source and competition."""
    return get_league_performance(league)


@router.get("/performance/leaderboard", response_model=list[SourcePerformance])
async def global_leaderboard() -> list[SourcePerformance]:
    """Cross-league source ranking by 30-day accuracy."""
    return get_global_leaderboard()
