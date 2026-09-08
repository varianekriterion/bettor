"""Tests for API-Football stats service and live scraper gating."""

from __future__ import annotations

import pytest

from app.services import stats_service
from app.services.stats_service import (
    TeamMatchStats,
    _parse_team_statistics,
    get_team_stats,
)


def test_parse_team_statistics_per_match_averages():
    payload = {
        "response": [
            {
                "team": {"id": 42, "name": "Arsenal"},
                "fixtures": {"played": {"total": 20}},
                "shots": {"on": {"total": 90}},
                "corners": {"total": 110},
            }
        ]
    }
    stats = _parse_team_statistics("Arsenal", "epl", payload)
    assert stats is not None
    assert stats.shots_on_target_per_match == pytest.approx(4.5)
    assert stats.corners_per_match == pytest.approx(5.5)
    assert stats.matches_played == 20
    assert stats.source == "api_football"


def test_parse_team_statistics_uses_baseline_when_corners_missing():
    payload = {
        "response": [
            {
                "team": {"id": 42, "name": "Arsenal"},
                "fixtures": {"played": {"total": 10}},
                "shots": {"on": {"total": 45}},
            }
        ]
    }
    stats = _parse_team_statistics("Arsenal", "epl", payload)
    assert stats is not None
    assert stats.shots_on_target_per_match == pytest.approx(4.5)
    assert stats.corners_per_match == pytest.approx(5.0)


@pytest.mark.asyncio
async def test_get_team_stats_baseline_without_api_key(monkeypatch):
    monkeypatch.setattr("app.services.stats_service.settings.api_football_key", "")
    stats = await get_team_stats("Arsenal", league="epl")
    assert stats.source == "baseline"
    assert stats.shots_on_target_per_match == 4.5
    assert stats.corners_per_match == 5.0


@pytest.mark.asyncio
async def test_get_team_stats_uses_cache(monkeypatch):
    monkeypatch.setattr("app.services.stats_service.settings.api_football_key", "")
    stats_service._stats_cache.clear()

    first = await get_team_stats("Chelsea", league="epl")
    assert first.source == "baseline"

    # Simulate a cached API result without hitting the network.
    stats_service._cache_set(
        stats_service._stats_cache,
        "stats:epl:2025:chelsea",
        TeamMatchStats(
            team="Chelsea",
            league="epl",
            shots_on_target_per_match=5.1,
            corners_per_match=6.2,
            matches_played=18,
            source="api_football",
            team_id=49,
        ),
    )
    cached = await get_team_stats("Chelsea", league="epl")
    assert cached.source == "cache"
    assert cached.shots_on_target_per_match == 5.1


@pytest.mark.asyncio
async def test_scrape_all_sources_runs_when_live_scrapers_enabled(monkeypatch):
    from app.scrapers.prediction_sites import scrape_all_sources

    monkeypatch.setattr("app.scrapers.prediction_sites.settings.use_demo_data", False)
    monkeypatch.setattr("app.scrapers.prediction_sites.settings.use_live_scrapers", True)

    calls = 0

    async def _fake_safe_scrape(self, home, away, league):  # noqa: ANN001
        nonlocal calls
        calls += 1
        return None

    monkeypatch.setattr(
        "app.scrapers.prediction_sites.BasePredictionScraper.safe_scrape",
        _fake_safe_scrape,
    )

    result = await scrape_all_sources("Arsenal", "Chelsea", "epl")
    assert result == []
    assert calls == 5


@pytest.mark.asyncio
async def test_scrape_all_sources_skipped_when_live_disabled(monkeypatch):
    from app.scrapers.prediction_sites import scrape_all_sources

    monkeypatch.setattr("app.scrapers.prediction_sites.settings.use_demo_data", False)
    monkeypatch.setattr("app.scrapers.prediction_sites.settings.use_live_scrapers", False)

    result = await scrape_all_sources("Arsenal", "Chelsea", "epl")
    assert result == []
