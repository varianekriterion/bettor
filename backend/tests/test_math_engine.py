"""Unit tests for quantitative engine."""

from __future__ import annotations

import math

import pytest

from app.core.math_engine import (
    bayesian_consensus,
    expected_value,
    implied_probability,
    kelly_criterion,
    multiplicative_devig,
    power_devig,
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
