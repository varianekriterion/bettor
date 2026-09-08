"""Unit tests for quantitative engine."""

from __future__ import annotations

import math

import pytest

from app.core.math_engine import (
    adaptive_prior_strength,
    bayesian_consensus,
    compute_match_edges,
    expected_value,
    implied_probability,
    kelly_criterion,
    multiplicative_devig,
    power_devig,
    qualifies_for_positive_ev,
)


def test_implied_probability():
    assert implied_probability(2.0) == pytest.approx(0.5)
    assert implied_probability(1.5) == pytest.approx(2 / 3)


def test_multiplicative_devig_sums_to_one():
    result = multiplicative_devig(2.10, 3.40, 3.50)
    assert result.home + result.draw + result.away == pytest.approx(1.0)
    assert result.overround > 0
    assert result.method == "multiplicative"


def test_power_devig_sums_to_one():
    result = power_devig(1.80, 3.60, 4.50)
    assert result.home + result.draw + result.away == pytest.approx(1.0, abs=1e-6)
    assert result.method == "power"


def test_positive_ev():
    # p=0.55 at odds 2.00 → EV = 10%
    ev = expected_value(0.55, 2.0)
    assert ev.ev_pct == pytest.approx(10.0)
    assert ev.is_positive is True


def test_negative_ev():
    ev = expected_value(0.40, 2.0)
    assert ev.ev_pct == pytest.approx(-20.0)
    assert ev.is_positive is False


def test_kelly_quarter():
    # Classic: p=0.6, odds=2.0 → full Kelly = 0.2, quarter = 0.05
    k = kelly_criterion(0.6, 2.0, fraction=0.25, bankroll=1000)
    assert k.full_kelly == pytest.approx(0.2)
    assert k.fractional_kelly == pytest.approx(0.05)
    assert k.recommended_stake_amount == pytest.approx(50.0)


def test_kelly_no_edge_zero_stake():
    k = kelly_criterion(0.40, 2.0, fraction=0.25)
    assert k.full_kelly == 0.0
    assert k.recommended_stake_pct == 0.0


def test_bayesian_consensus_pick():
    sources = {
        "forebet": {"home": 0.55, "draw": 0.25, "away": 0.20},
        "betimate": {"home": 0.50, "draw": 0.28, "away": 0.22},
        "predictz": {"home": 0.48, "draw": 0.27, "away": 0.25},
    }
    acc = {"forebet": 0.56, "betimate": 0.57, "predictz": 0.51}
    result = bayesian_consensus(sources, acc)
    assert result.pick == "home"
    assert math.isclose(result.home + result.draw + result.away, 1.0, abs_tol=1e-6)
    assert abs(sum(result.source_weights.values()) - 1.0) < 1e-6


def test_longshot_ev_guardrails_reject_unrealistic_edge():
    # Noisy 14% on a 25.00 longshot → raw EV ~250%, not actionable
    ev = expected_value(0.14, 25.0)
    assert ev.raw_ev_pct == pytest.approx(250.0)
    assert ev.ev_pct == pytest.approx(25.0)
    assert ev.is_anomaly is True
    assert ev.is_positive is False
    assert ev.anomaly_reason == "High-Variance Outlier / Anomaly"


def test_longshot_odds_and_probability_filters():
    assert qualifies_for_positive_ev(0.15, 8.0, 5.0) is False  # odds > 7.50
    assert qualifies_for_positive_ev(0.10, 6.0, 5.0) is False  # prob < 0.12
    assert qualifies_for_positive_ev(0.20, 5.0, 10.0) is True


def test_adaptive_prior_shrinkage_on_extreme_longshot():
    market_prior = {"home": 0.70, "draw": 0.20, "away": 0.04}
    strengths = adaptive_prior_strength(market_prior)
    assert strengths["away"] > strengths["home"]

    noisy_sources = {
        "tipster_a": {"home": 0.30, "draw": 0.20, "away": 0.50},
        "tipster_b": {"home": 0.25, "draw": 0.20, "away": 0.55},
    }
    flat = bayesian_consensus(
        noisy_sources,
        prior=market_prior,
        prior_strength=1.5,
    )
    shrunk = bayesian_consensus(
        noisy_sources,
        prior=market_prior,
        prior_strength=adaptive_prior_strength(market_prior),
    )
    assert shrunk.away < flat.away
    assert shrunk.away < 0.14


def test_kelly_high_odds_uses_eighth_kelly_and_cap():
    # p=0.25, odds=6.0 → full Kelly = (5*0.25 - 0.75)/5 = 0.1, eighth = 0.0125
    k = kelly_criterion(0.25, 6.0, fraction=0.25, bankroll=1000)
    assert k.fraction_used == pytest.approx(0.125)
    # 1.25% stake exceeds the 0.5% longshot cap
    assert k.recommended_stake_pct == pytest.approx(0.5)
    assert k.fractional_kelly == pytest.approx(0.005)

    # Very large edge at high odds should still cap at 0.5%
    k_cap = kelly_criterion(0.40, 10.0, fraction=0.25, bankroll=1000)
    assert k_cap.recommended_stake_pct == pytest.approx(0.5)


def test_compute_match_edges_prefers_actionable_best_bet():
    consensus = bayesian_consensus(
        {"src": {"home": 0.55, "draw": 0.25, "away": 0.20}},
        prior={"home": 0.45, "draw": 0.28, "away": 0.27},
        prior_strength=1.5,
    )
    pipeline = compute_match_edges(
        consensus=consensus,
        bookie_odds={"home": 2.10, "draw": 3.40, "away": 25.0},
    )
    assert pipeline["best_bet"]["outcome"] == "home"
    assert pipeline["edges"]["away"]["ev"]["is_positive"] is False
