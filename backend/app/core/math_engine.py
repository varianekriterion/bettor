"""
Core quantitative engine for BetConsensus.

Implements:
- Multiplicative (proportional) and power (Shin-style) odds devigging
- Performance-weighted Bayesian consensus
- Expected Value (+EV)
- Fractional Kelly Criterion staking
"""

from __future__ import annotations

import math
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
    *,
    btts_penalty_outcomes: set[Outcome] | None = None,
) -> dict:
    """
    Full pipeline: consensus vs bookie odds → EV + Kelly per outcome.

    `btts_penalty_outcomes` (Phase 4 strategy rule) — the set of outcomes
    ("home" and/or "away") whose backing team is flagged
    `is_btts_lucky_not_good()`: high BTTS rate but low xG, i.e. probably
    riding finishing variance rather than real attacking quality. Kelly for
    those outcomes only is halved via `apply_strategy_penalties`; draw and
    unflagged outcomes are untouched.
    """
    home_o = bookie_odds["home"]
    draw_o = bookie_odds["draw"]
    away_o = bookie_odds["away"]
    fair = devig_odds(home_o, draw_o, away_o, method=devig_method)
    penalized_outcomes = btts_penalty_outcomes or set()

    edges: dict[str, dict] = {}
    for outcome in ("home", "draw", "away"):
        p = consensus.probability(outcome)  # type: ignore[arg-type]
        odds = bookie_odds[outcome]  # type: ignore[index]
        ev = expected_value(p, odds)
        kelly = kelly_criterion(p, odds, fraction=kelly_fraction, bankroll=bankroll)
        penalized = outcome in penalized_outcomes
        if penalized:
            kelly = apply_strategy_penalties(kelly, btts_lucky_not_good=True)
        edges[outcome] = {
            "probability": round(p, 6),
            "odds": odds,
            "fair_prob": fair.probability(outcome),  # type: ignore[arg-type]
            "ev": ev.as_dict(),
            "kelly": kelly.as_dict(),
            "btts_penalty_applied": penalized,
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


# ---------------------------------------------------------------------------
# Phase 2 — attacking-pressure & motivation signals
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AttackingPressure:
    """Composite attacking-pressure score from shot & set-piece volume."""

    team: str
    pressure_score: float
    avg_shots_on_target: float
    avg_corners: float
    components: dict[str, float]

    def as_dict(self) -> dict:
        return {
            "team": self.team,
            "pressure_score": self.pressure_score,
            "avg_shots_on_target": self.avg_shots_on_target,
            "avg_corners": self.avg_corners,
            "components": self.components,
        }


def calculate_attacking_pressure(
    avg_shots_on_target: float,
    avg_corners: float,
    *,
    team: str = "",
    shots_on_target_weight: float = 0.65,
    corners_weight: float = 0.35,
    shots_on_target_baseline: float = 4.5,
    corners_baseline: float = 5.0,
) -> AttackingPressure:
    """
    Composite "attacking pressure" score from shot & set-piece volume.

    Currently fed simulated per-fixture data (see
    `app.services.understat_service._seeded_xg`, which already generates a
    plausible shots-on-target/corners pair per fixture in demo mode) — it's
    written to take a real per-90 trailing-average payload from a stats
    provider (e.g. FootyStats) as a drop-in replacement for the two inputs;
    nothing else about the call site needs to change.

    Each input is expressed as a percentage of a league-average baseline
    (`*_baseline`, tune per league/season), weighted, and summed — so 100 =
    exactly average attacking pressure, >100 = above average, <100 = below.
    """
    if avg_shots_on_target < 0 or avg_corners < 0:
        raise ValueError("avg_shots_on_target and avg_corners must be non-negative")
    if shots_on_target_baseline <= 0 or corners_baseline <= 0:
        raise ValueError("baselines must be positive")
    if abs((shots_on_target_weight + corners_weight) - 1.0) > 1e-9:
        raise ValueError("shots_on_target_weight + corners_weight must sum to 1.0")

    sot_index = (avg_shots_on_target / shots_on_target_baseline) * 100.0
    corners_index = (avg_corners / corners_baseline) * 100.0
    pressure_score = shots_on_target_weight * sot_index + corners_weight * corners_index

    return AttackingPressure(
        team=team,
        pressure_score=round(pressure_score, 2),
        avg_shots_on_target=round(avg_shots_on_target, 2),
        avg_corners=round(avg_corners, 2),
        components={
            "shots_on_target_index": round(sot_index, 2),
            "corners_index": round(corners_index, 2),
        },
    )


def flag_relegation_desperation(
    team_points: int,
    relegation_zone_points: int,
    matches_played: int,
    total_matches_in_season: int,
) -> bool:
    """
    "Motivation / desperation" flag: True when a team sits at most 5 points
    above the relegation-zone cutoff AND the season is more than 65% played
    (late enough that survival pressure is real, without requiring the
    season to already be over).

    `relegation_zone_points` should be the points total of the last
    non-relegation ("safe") table position — pass whatever your standings
    source uses consistently (see `app.services.standings_service`).
    """
    if total_matches_in_season <= 0:
        raise ValueError("total_matches_in_season must be positive")
    if matches_played < 0:
        raise ValueError("matches_played must be non-negative")

    season_pct_complete = matches_played / total_matches_in_season
    points_above_zone = team_points - relegation_zone_points
    return points_above_zone <= 5 and season_pct_complete > 0.65


def resolve_away_xga(
    away_overall_xga: float,
    away_isolated_xga: float,
    *,
    home_desperation_flag: bool,
) -> float:
    """
    Phase 4 strategy rule: when the home side is relegation-desperate
    (`flag_relegation_desperation` is True for them), a desperate home team
    is argued to raise its press/attacking intensity specifically at home —
    so the away team's blended overall-form xGA is a weaker signal here
    than how they specifically perform *away*. In that case, ignore overall
    form and use only the away-venue-isolated xGA; otherwise use overall.
    """
    return away_isolated_xga if home_desperation_flag else away_overall_xga


def xg_implied_probabilities(
    home_xg: float,
    home_xga: float,
    away_xg: float,
    away_xga: float,
    *,
    home_advantage: float = 1.1,
    max_goals: int = 8,
) -> dict[Outcome, float]:
    """
    Lightweight independent-Poisson W/D/L distribution from expected goals.

    This is a weak *additional* signal meant to be blended into
    `bayesian_consensus`'s `source_probs` alongside tipster sources (e.g.
    under a synthetic source key like "xg_model") — not a replacement for
    the tipster/market consensus.

    `away_xga` is whatever `resolve_away_xga()` decided to use for this
    fixture (overall vs. isolated-away, per the motivation-flag rule).
    """
    if home_xg < 0 or home_xga < 0 or away_xg < 0 or away_xga < 0:
        raise ValueError("xG/xGA inputs must be non-negative")
    if max_goals < 1:
        raise ValueError("max_goals must be >= 1")

    # Each side's expected goals = average of their own attack and the
    # opponent's defensive leakiness, with a home-advantage multiplier.
    home_expected = ((home_xg + away_xga) / 2.0) * home_advantage
    away_expected = (away_xg + home_xga) / 2.0
    home_expected = max(home_expected, 1e-6)
    away_expected = max(away_expected, 1e-6)

    goals = np.arange(0, max_goals + 1)
    factorials = np.array([math.factorial(int(g)) for g in goals], dtype=float)
    home_pmf = np.exp(-home_expected) * home_expected**goals / factorials
    away_pmf = np.exp(-away_expected) * away_expected**goals / factorials

    score_matrix = np.outer(home_pmf, away_pmf)  # [home_goals, away_goals]
    p_home = float(np.tril(score_matrix, k=-1).sum())
    p_draw = float(np.trace(score_matrix))
    p_away = float(np.triu(score_matrix, k=1).sum())

    total = p_home + p_draw + p_away
    if total <= 0:
        return {"home": 1 / 3, "draw": 1 / 3, "away": 1 / 3}
    return {"home": p_home / total, "draw": p_draw / total, "away": p_away / total}


def is_btts_lucky_not_good(
    btts_rate: float,
    xg: float,
    *,
    btts_threshold: float = 0.60,
    xg_threshold: float = 1.0,
) -> bool:
    """
    Phase 4 strategy rule: True when a team's BTTS (both-teams-to-score)
    rate is high (>60%) despite low underlying xG (<1.0) — a sign the goals
    they're involved in are driven by finishing/defensive variance rather
    than real attacking or defensive quality, i.e. "lucky, not good".
    """
    if not 0.0 <= btts_rate <= 1.0:
        raise ValueError("btts_rate must be in [0, 1]")
    if xg < 0:
        raise ValueError("xg must be non-negative")
    return btts_rate > btts_threshold and xg < xg_threshold


def apply_strategy_penalties(
    kelly: KellyResult,
    *,
    btts_lucky_not_good: bool = False,
    penalty_multiplier: float = 0.5,
) -> KellyResult:
    """
    Apply Phase 4 strategy penalty modifiers to an already-computed Kelly
    stake. Returns a new (frozen) KellyResult rather than mutating `kelly`.

    Currently implements the BTTS-lucky-not-good penalty
    (`is_btts_lucky_not_good`): halves the recommended stake. `full_kelly`
    and `edge` are left as-is (they describe the raw mathematical edge);
    only the *recommended* stake fields are scaled, so the penalty is
    visibly a staking-discipline override, not a claim that the edge itself
    changed.
    """
    if not btts_lucky_not_good:
        return kelly
    if not 0.0 < penalty_multiplier <= 1.0:
        raise ValueError("penalty_multiplier must be in (0, 1]")

    frac = kelly.fractional_kelly * penalty_multiplier
    stake_amount = (
        round(kelly.recommended_stake_amount * penalty_multiplier, 2)
        if kelly.recommended_stake_amount is not None
        else None
    )
    return KellyResult(
        full_kelly=kelly.full_kelly,
        fractional_kelly=round(frac, 6),
        fraction_used=kelly.fraction_used,
        edge=kelly.edge,
        recommended_stake_pct=round(frac * 100.0, 4),
        recommended_stake_amount=stake_amount,
    )
