"""Tests for strict no-demo mode and quantitative consensus fallback."""

from __future__ import annotations

import pytest

from app.core.math_engine import multiplicative_devig
from app.services.consensus_service import _consensus_from_prior
from app.services.understat_service import get_fixture_xg


@pytest.mark.asyncio
async def test_get_fixture_xg_strict_mode_no_seeded_fallback(monkeypatch):
    monkeypatch.setattr("app.services.understat_service.settings.use_demo_data", False)
    monkeypatch.setattr("app.services.understat_service.cache_get", lambda _k: None)

    async def _no_live(*_a, **_k):
        return None

    monkeypatch.setattr("app.services.understat_service._fetch_live", _no_live)

    result = await get_fixture_xg("Arsenal", "Chelsea", "epl")
    assert result is None


@pytest.mark.asyncio
async def test_get_fixture_xg_demo_mode_seeded_fallback(monkeypatch):
    monkeypatch.setattr("app.services.understat_service.settings.use_demo_data", True)
    monkeypatch.setattr("app.services.understat_service.cache_get", lambda _k: None)

    async def _no_live(*_a, **_k):
        return None

    monkeypatch.setattr("app.services.understat_service._fetch_live", _no_live)

    result = await get_fixture_xg("Arsenal", "Chelsea", "epl")
    assert result is not None
    assert result.home.source == "demo"


def test_parse_match_odds_strict_raises_without_bookmakers(monkeypatch):
    from app.services.odds_service import odds_client

    monkeypatch.setattr("app.services.odds_service.settings.use_demo_data", False)
    event = {"home_team": "Arsenal", "away_team": "Chelsea", "bookmakers": []}
    with pytest.raises(ValueError, match="strict no-demo"):
        odds_client.parse_match_odds(event)


def test_consensus_from_prior_sums_to_one():
    prior = multiplicative_devig(2.10, 3.40, 3.50)
    consensus = _consensus_from_prior(
        {"home": prior.home, "draw": prior.draw, "away": prior.away}
    )
    assert consensus.home + consensus.draw + consensus.away == pytest.approx(1.0)
    assert consensus.source_weights == {"market_prior": 1.0}
