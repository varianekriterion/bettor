"""Interactive +EV / Kelly calculator endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.math_engine import expected_value, kelly_criterion
from app.models.schemas import CalculatorRequest, CalculatorResponse

router = APIRouter()


@router.post("/calculator", response_model=CalculatorResponse)
async def calculate_ev_kelly(body: CalculatorRequest) -> CalculatorResponse:
    """
    Real-time calculator: bankroll + decimal odds + win probability
    → EV%, fractional Kelly stake, and expected return.
    """
    ev = expected_value(body.win_probability, body.decimal_odds)
    kelly = kelly_criterion(
        probability=body.win_probability,
        decimal_odds=body.decimal_odds,
        fraction=body.kelly_fraction,
        bankroll=body.bankroll,
    )
    stake = kelly.recommended_stake_amount or 0.0
    # Expected return on recommended stake (profit, not payout)
    expected_return = stake * ev.ev_decimal

    return CalculatorResponse(
        ev_pct=ev.ev_pct,
        ev_decimal=ev.ev_decimal,
        is_positive_ev=ev.is_positive,
        fair_odds=ev.fair_odds,
        full_kelly_pct=round(kelly.full_kelly * 100, 4),
        fractional_kelly_pct=kelly.recommended_stake_pct,
        recommended_stake=stake,
        expected_return=round(expected_return, 2),
        edge=kelly.edge,
        kelly_fraction_used=kelly.fraction_used,
    )
