"""Match feed endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.models.schemas import LeagueKey, MatchCard, OddsHistoryResponse, Outcome
from app.services.consensus_service import get_live_matches
from app.services.odds_history_service import get_odds_history

router = APIRouter()


@router.get("/matches", response_model=list[MatchCard])
async def list_matches(
    league: LeagueKey | None = Query(default=None),
    positive_ev_only: bool = Query(default=False),
    bankroll: float | None = Query(default=None, gt=0),
) -> list[MatchCard]:
    """Live match feed with consensus picks, EV%, and Kelly stake suggestions."""
    return await get_live_matches(
        league=league,
        positive_ev_only=positive_ev_only,
        bankroll=bankroll,
    )


@router.get("/leagues")
async def list_leagues() -> list[dict[str, str]]:
    from app.models.schemas import LEAGUE_META

    return [
        {"key": key, "name": meta["name"], "short": meta["short"]}
        for key, meta in LEAGUE_META.items()
    ]


@router.get("/matches/{match_id}", response_model=MatchCard)
async def get_match(match_id: str) -> MatchCard:
    cards = await get_live_matches()
    for card in cards:
        if card.id == match_id:
            return card
    raise HTTPException(status_code=404, detail="Match not found")


@router.get("/matches/{match_id}/odds-history", response_model=OddsHistoryResponse)
async def match_odds_history(
    match_id: str,
    outcome: Outcome | None = Query(
        default=None,
        description="Tracked outcome for line movement (defaults to best-edge pick)",
    ),
) -> OddsHistoryResponse:
    """
    Timestamped bookmaker line movements vs Bayesian consensus true odds.

    Returns opening/current snapshots, per-point implied probability deltas,
    and EV shift so the frontend can chart Opening → Current value drift.
    """
    cards = await get_live_matches()
    live = next((c for c in cards if c.id == match_id), None)
    history = await get_odds_history(match_id, outcome=outcome, live_card=live)
    if history is None:
        raise HTTPException(status_code=404, detail="Odds history not found for match")
    return history
