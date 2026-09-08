"""Aggregator matrix & prediction endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.models.schemas import LeagueKey
from app.services.consensus_service import aggregator_matrix_row, get_live_matches

router = APIRouter()


@router.get("/predictions/matrix")
async def prediction_matrix(
    league: LeagueKey | None = Query(default=None),
    days_ahead: int = Query(default=0, ge=0, le=30),
) -> list[dict]:
    """
    Side-by-side comparison of Forebet, PredictZ, WinDrawWin, Betimate,
    FootballWhispers and the master aggregated consensus score.
    """
    window = days_ahead if days_ahead > 0 else None
    cards = await get_live_matches(league=league, days_ahead=window)
    return [aggregator_matrix_row(card) for card in cards]
