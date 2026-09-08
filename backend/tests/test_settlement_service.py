"""Tests for prediction settlement helpers and performance fallbacks."""

from __future__ import annotations

import pytest

from app.services.performance_service import (
    DEFAULT_ACCURACY_PRIOR,
    get_source_accuracies,
    invalidate_performance_cache,
)
from app.services.settlement_service import (
    _dedupe_predictions,
    _match_fd_to_db,
    _multiclass_brier,
    _parse_fd_outcome,
    _score_pick,
    _teams_match,
)


def test_parse_fd_outcome_home_win():
    match = {
        "status": "FINISHED",
        "score": {"winner": "HOME_TEAM", "fullTime": {"home": 2, "away": 1}},
    }
    assert _parse_fd_outcome(match) == "home"


def test_parse_fd_outcome_draw_from_score():
    match = {
        "status": "FINISHED",
        "score": {"winner": None, "fullTime": {"home": 1, "away": 1}},
    }
    assert _parse_fd_outcome(match) == "draw"


def test_parse_fd_outcome_void_status():
    match = {"status": "POSTPONED", "score": {}}
    assert _parse_fd_outcome(match) is None


def test_score_pick():
    assert _score_pick("home", "home") == "WON"
    assert _score_pick("away", "home") == "LOST"


def test_multiclass_brier_perfect_home_call():
    score = _multiclass_brier(0.7, 0.2, 0.1, "home")
    assert score == pytest.approx(0.14)


def test_teams_match_fuzzy():
    assert _teams_match("Arsenal FC", "Arsenal")
    assert _teams_match("Manchester United FC", "Man United") is False


def test_match_fd_to_db_by_teams_and_date():
    fd_match = {
        "homeTeam": {"name": "Arsenal FC"},
        "awayTeam": {"name": "Chelsea FC"},
        "utcDate": "2026-01-15T15:00:00Z",
        "status": "FINISHED",
        "score": {"winner": "HOME_TEAM", "fullTime": {"home": 1, "away": 0}},
    }
    db_matches = [
        {
            "id": "evt-1",
            "home_team": "Arsenal",
            "away_team": "Chelsea",
            "commence_time": "2026-01-15T14:00:00+00:00",
        }
    ]
    matched = _match_fd_to_db(fd_match, db_matches)
    assert matched is not None
    assert matched["id"] == "evt-1"


def test_dedupe_predictions_keeps_latest_pre_kickoff():
    commence = "2026-01-15T15:00:00+00:00"
    predictions = [
        {
            "id": "a",
            "match_id": "m1",
            "source": "forebet",
            "scraped_at": "2026-01-14T10:00:00+00:00",
            "pick": "home",
        },
        {
            "id": "b",
            "match_id": "m1",
            "source": "forebet",
            "scraped_at": "2026-01-15T08:00:00+00:00",
            "pick": "draw",
        },
        {
            "id": "c",
            "match_id": "m1",
            "source": "forebet",
            "scraped_at": "2026-01-15T16:00:00+00:00",
            "pick": "away",
        },
    ]
    deduped = _dedupe_predictions(predictions, {"m1": commence})
    assert len(deduped) == 1
    assert deduped[0]["id"] == "b"


def test_get_source_accuracies_empty_without_supabase(monkeypatch):
    monkeypatch.setattr("app.services.performance_service.is_supabase_configured", lambda: False)
    invalidate_performance_cache()
    accuracies = get_source_accuracies("epl")
    assert accuracies == {}


def test_default_accuracy_prior_is_conservative():
    assert DEFAULT_ACCURACY_PRIOR == 0.50


@pytest.mark.asyncio
async def test_run_settlement_without_supabase(monkeypatch):
    from app.services.settlement_service import run_prediction_settlement

    monkeypatch.setattr("app.services.settlement_service.is_supabase_configured", lambda: False)
    result = await run_prediction_settlement(trigger="test")
    assert result.trigger == "test"
    assert result.ok is False
    assert "supabase_not_configured" in result.errors
