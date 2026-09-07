"""Aggregator matrix & prediction endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.models.schemas import LeagueKey
from app.services.consensus_service import aggregator_matrix_row, get_live_matches

router = APIRouter()


@router.get("/predictions/matrix")
async def prediction_matrix(
    league: LeagueKey | None = Query(default=None),
) -> list[dict]:
    """
    Side-by-side comparison of Forebet, PredictZ, WinDrawWin, Betimate,
    FootballWhispers and the master aggregated consensus score.
    """
    cards = await get_live_matches(league=league)
    return [aggregator_matrix_row(card) for card in cards]
