"""Tests for scraper resilience and sync pipeline."""

from __future__ import annotations

import pytest

from app.scrapers.base import BasePredictionScraper
from app.scrapers.errors import ScraperBlockedError
from app.scrapers.prediction_sites import SCRAPERS, scrape_all_sources
from app.services.sync_service import ACTIVE_LEAGUES, sync_league_predictions


class _FailingScraper(BasePredictionScraper):
    source_name = "forebet"
    base_url = "https://example.invalid"

    async def scrape_match(self, home_team: str, away_team: str, league: str):
        raise ScraperBlockedError(self.source_name, status_code=403, detail="CAPTCHA")


@pytest.mark.asyncio
async def test_safe_scrape_skips_blocked_source():
    scraper = _FailingScraper()
    result = await scraper.safe_scrape("Arsenal", "Chelsea", "epl")
    assert result is None


@pytest.mark.asyncio
async def test_scrape_all_sources_demo_returns_predictions(monkeypatch):
    monkeypatch.setattr("app.scrapers.prediction_sites.settings.use_demo_data", True)
    preds = await scrape_all_sources("Arsenal", "Chelsea", "epl")
    assert len(preds) == len(SCRAPERS)
    assert {p.source for p in preds} == {s.source_name for s in SCRAPERS}


@pytest.mark.asyncio
async def test_sync_league_predictions_demo(monkeypatch):
    monkeypatch.setattr("app.services.sync_service.is_supabase_configured", lambda: False)
    result = await sync_league_predictions(leagues=["epl"], trigger="test")
    assert result.trigger == "test"
    assert len(result.leagues) == 1
    assert result.leagues[0].league == "epl"
    assert result.leagues[0].matches > 0
    assert result.leagues[0].predictions > 0
    assert result.supabase_configured is False


def test_active_leagues_cover_targets():
    assert set(ACTIVE_LEAGUES) == {
        "epl",
        "laliga",
        "bundesliga",
        "seriea",
        "ucl",
        "uel",
    }
