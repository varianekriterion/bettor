"""
Core quantitative engine for BetConsensus.

Implements:
- Multiplicative (proportional) and power (Shin-style) odds devigging
- Performance-weighted Bayesian consensus
- Expected Value (+EV)
- Fractional Kelly Criterion staking
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

Outcome = Literal["home", "draw", "away"]
DevigMethod = Literal["multiplicative", "power"]


@dataclass(frozen=True)
class DeviggedOdds:
    """True probabilities after removing bookmaker overround."""

    home: float
    draw: float
    away: float
    overround: float
    method: DevigMethod

    def as_dict(self) -> dict[str, float | str]:
        return {
            "home": self.home,
            "draw": self.draw,
            "away": self.away,
            "overround": self.overround,
            "method": self.method,
        }

    def probability(self, outcome: Outcome) -> float:
        return getattr(self, outcome)


@dataclass(frozen=True)
class ConsensusResult:
    """Weighted consensus probabilities across prediction sources."""

    home: float
    draw: float
    away: float
    pick: Outcome
    confidence: float
    source_weights: dict[str, float]

    def as_dict(self) -> dict:
        return {
            "home": self.home,
            "draw": self.draw,
            "away": self.away,
            "pick": self.pick,
            "confidence": self.confidence,
            "source_weights": self.source_weights,
        }

    def probability(self, outcome: Outcome) -> float:
        return getattr(self, outcome)


@dataclass(frozen=True)
class KellyResult:
    """Kelly Criterion stake recommendation."""

    full_kelly: float
    fractional_kelly: float
    fraction_used: float
    edge: float
    recommended_stake_pct: float
    recommended_stake_amount: float | None

    def as_dict(self) -> dict:
        return {
            "full_kelly": self.full_kelly,
            "fractional_kelly": self.fractional_kelly,
            "fraction_used": self.fraction_used,
            "edge": self.edge,
            "recommended_stake_pct": self.recommended_stake_pct,
            "recommended_stake_amount": self.recommended_stake_amount,
        }


@dataclass(frozen=True)
class EVResult:
    """Expected value for a single selection."""

    ev_pct: float
    ev_decimal: float
    is_positive: bool
    fair_odds: float

    def as_dict(self) -> dict:
        return {
            "ev_pct": self.ev_pct,
            "ev_decimal": self.ev_decimal,
            "is_positive": self.is_positive,
            "fair_odds": self.fair_odds,
        }


def implied_probability(decimal_odds: float) -> float:
    """Convert decimal odds to raw implied probability (includes vig)."""
    if decimal_odds <= 1.0:
        raise ValueError("Decimal odds must be greater than 1.0")
    return 1.0 / decimal_odds


def multiplicative_devig(home: float, draw: float, away: float) -> DeviggedOdds:
    """
    Proportional (multiplicative) devigging.

    Scales each implied probability by 1 / sum(implied) so probabilities sum to 1.
    """
    raw = np.array(
        [implied_probability(home), implied_probability(draw), implied_probability(away)],
        dtype=float,
    )
    overround = float(raw.sum() - 1.0)
    if raw.sum() <= 0:
        raise ValueError("Invalid odds — implied probabilities sum to zero")
    true = raw / raw.sum()
    return DeviggedOdds(
        home=float(true[0]),
        draw=float(true[1]),
        away=float(true[2]),
        overround=overround,
        method="multiplicative",
    )


def power_devig(home: float, draw: float, away: float, tol: float = 1e-10) -> DeviggedOdds:
    """
    Power (Shin-adjacent) method: find exponent k such that sum(p_i^k) = 1
    where p_i are raw implied probabilities. More accurate for favourite-longshot bias.
    """
    raw = np.array(
        [implied_probability(home), implied_probability(draw), implied_probability(away)],
        dtype=float,
    )
    overround = float(raw.sum() - 1.0)

    # Binary search for power k where sum(raw^k) == 1
    lo, hi = 0.01, 10.0
    for _ in range(80):
        mid = (lo + hi) / 2.0
        s = float(np.sum(raw**mid))
        if abs(s - 1.0) < tol:
            break
        if s > 1.0:
            lo = mid
        else:
            hi = mid
    k = (lo + hi) / 2.0
    powered = raw**k
    true = powered / powered.sum()
    return DeviggedOdds(
        home=float(true[0]),
        draw=float(true[1]),
        away=float(true[2]),
        overround=overround,
        method="power",
    )


def devig_odds(
    home: float,
    draw: float,
    away: float,
    method: DevigMethod = "multiplicative",
) -> DeviggedOdds:
    if method == "power":
        return power_devig(home, draw, away)
    return multiplicative_devig(home, draw, away)


def bayesian_consensus(
    source_probs: dict[str, dict[Outcome, float]],
    source_accuracies: dict[str, float] | None = None,
    prior: dict[Outcome, float] | None = None,
    prior_strength: float = 1.0,
) -> ConsensusResult:
    """
    Performance-weighted consensus with optional Dirichlet-style prior.

    Each source contributes probabilities weighted by its rolling accuracy
    (default equal weights). A weak prior (market or flat) stabilizes sparse data.
    """
    if not source_probs:
        raise ValueError("At least one prediction source is required")

    outcomes: list[Outcome] = ["home", "draw", "away"]
    prior = prior or {"home": 1 / 3, "draw": 1 / 3, "away": 1 / 3}

    # Normalize accuracy weights; floor at 0.05 so weak sources still contribute
    weights: dict[str, float] = {}
    for source in source_probs:
        acc = (source_accuracies or {}).get(source, 0.33)
        weights[source] = max(float(acc), 0.05)

    weight_sum = sum(weights.values())
    norm_weights = {s: w / weight_sum for s, w in weights.items()}

    # Weighted average of source probabilities
    avg = {o: 0.0 for o in outcomes}
    for source, probs in source_probs.items():
        w = norm_weights[source]
        total = sum(probs.get(o, 0.0) for o in outcomes)
        if total <= 0:
            continue
        for o in outcomes:
            avg[o] += w * (probs.get(o, 0.0) / total)

    # Blend with prior: posterior ∝ prior_strength * prior + weight_sum * avg
    blended = {
        o: (prior_strength * prior[o] + weight_sum * avg[o]) / (prior_strength + weight_sum)
        for o in outcomes
    }
    blend_sum = sum(blended.values())
    consensus = {o: blended[o] / blend_sum for o in outcomes}

    pick: Outcome = max(outcomes, key=lambda o: consensus[o])
    # Confidence = margin of top pick over second
    sorted_p = sorted(consensus.values(), reverse=True)
    confidence = float(sorted_p[0] - sorted_p[1])

    return ConsensusResult(
        home=float(consensus["home"]),
        draw=float(consensus["draw"]),
        away=float(consensus["away"]),
        pick=pick,
        confidence=confidence,
        source_weights=norm_weights,
    )


def expected_value(probability: float, decimal_odds: float) -> EVResult:
    """
    EV% = (p * (odds - 1) - (1 - p)) * 100

    Equivalent to: (p * odds - 1) * 100
    """
    if not 0.0 <= probability <= 1.0:
        raise ValueError("Probability must be in [0, 1]")
    if decimal_odds <= 1.0:
        raise ValueError("Decimal odds must be greater than 1.0")

    p = probability
    b = decimal_odds - 1.0
    q = 1.0 - p
    ev_decimal = p * b - q
    ev_pct = ev_decimal * 100.0
    fair_odds = (1.0 / p) if p > 0 else float("inf")

    return EVResult(
        ev_pct=round(ev_pct, 4),
        ev_decimal=round(ev_decimal, 6),
        is_positive=ev_pct > 0,
        fair_odds=round(fair_odds, 4),
    )


def kelly_criterion(
    probability: float,
    decimal_odds: float,
    fraction: float = 0.25,
    bankroll: float | None = None,
) -> KellyResult:
    """
    Exact Kelly for a single bet: f* = (b*p - q) / b
    where b = decimal_odds - 1, q = 1 - p.

    Applies fractional Kelly (default Quarter-Kelly) as a drawdown safeguard.
    Negative edge yields zero stake.
    """
    if not 0.0 <= probability <= 1.0:
        raise ValueError("Probability must be in [0, 1]")
    if decimal_odds <= 1.0:
        raise ValueError("Decimal odds must be greater than 1.0")
    if not 0.0 < fraction <= 1.0:
        raise ValueError("Kelly fraction must be in (0, 1]")

    p = probability
    q = 1.0 - p
    b = decimal_odds - 1.0
    edge = b * p - q
    full = edge / b if b > 0 else 0.0
    full = max(0.0, full)  # never recommend a negative stake
    frac = full * fraction
    stake_amount = (bankroll * frac) if bankroll is not None and bankroll > 0 else None

    return KellyResult(
        full_kelly=round(full, 6),
        fractional_kelly=round(frac, 6),
        fraction_used=fraction,
        edge=round(edge, 6),
        recommended_stake_pct=round(frac * 100.0, 4),
        recommended_stake_amount=round(stake_amount, 2) if stake_amount is not None else None,
    )


def compute_match_edges(
    consensus: ConsensusResult,
    bookie_odds: dict[Outcome, float],
    kelly_fraction: float = 0.25,
    bankroll: float | None = None,
    devig_method: DevigMethod = "multiplicative",
) -> dict:
    """Full pipeline: consensus vs bookie odds → EV + Kelly per outcome."""
    home_o = bookie_odds["home"]
    draw_o = bookie_odds["draw"]
    away_o = bookie_odds["away"]
    fair = devig_odds(home_o, draw_o, away_o, method=devig_method)

    edges: dict[str, dict] = {}
    for outcome in ("home", "draw", "away"):
        p = consensus.probability(outcome)  # type: ignore[arg-type]
        odds = bookie_odds[outcome]  # type: ignore[index]
        ev = expected_value(p, odds)
        kelly = kelly_criterion(p, odds, fraction=kelly_fraction, bankroll=bankroll)
        edges[outcome] = {
            "probability": round(p, 6),
            "odds": odds,
            "fair_prob": fair.probability(outcome),  # type: ignore[arg-type]
            "ev": ev.as_dict(),
            "kelly": kelly.as_dict(),
        }

    best = max(edges.items(), key=lambda kv: kv[1]["ev"]["ev_pct"])
    return {
        "consensus": consensus.as_dict(),
        "devigged": fair.as_dict(),
        "edges": edges,
        "best_bet": {
            "outcome": best[0],
            **best[1],
        },
    }
