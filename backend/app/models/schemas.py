"""Pydantic domain models for BetConsensus Engine."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

LeagueKey = Literal[
    "ucl",
    "epl",
    "laliga",
    "bundesliga",
    "seriea",
    "uel",
]

Outcome = Literal["home", "draw", "away"]
PredictionSource = Literal[
    "forebet",
    "predictz",
    "windrawwin",
    "betimate",
    "footballwhispers",
]


LEAGUE_META: dict[str, dict[str, str]] = {
    "ucl": {
        "name": "UEFA Champions League",
        "odds_api_key": "soccer_uefa_champs_league",
        "short": "UCL",
    },
    "epl": {
        "name": "Premier League",
        "odds_api_key": "soccer_epl",
        "short": "EPL",
    },
    "laliga": {
        "name": "La Liga",
        "odds_api_key": "soccer_spain_la_liga",
        "short": "LaLiga",
    },
    "bundesliga": {
        "name": "Bundesliga",
        "odds_api_key": "soccer_germany_bundesliga",
        "short": "Bundesliga",
    },
    "seriea": {
        "name": "Serie A",
        "odds_api_key": "soccer_italy_serie_a",
        "short": "Serie A",
    },
    "uel": {
        "name": "Europa League",
        "odds_api_key": "soccer_uefa_europa_league",
        "short": "UEL",
    },
}


class SourcePrediction(BaseModel):
    source: PredictionSource
    home_prob: float = Field(ge=0, le=1)
    draw_prob: float = Field(ge=0, le=1)
    away_prob: float = Field(ge=0, le=1)
    pick: Outcome
    confidence: float | None = None
    scraped_at: datetime | None = None

    @field_validator("home_prob", "draw_prob", "away_prob")
    @classmethod
    def round_prob(cls, v: float) -> float:
        return round(v, 6)


class TotalsLine(BaseModel):
    """Over/under market at a fixed total goals line (typically 2.5)."""

    line: float = Field(default=2.5, gt=0)
    over: float = Field(gt=1.0)
    under: float = Field(gt=1.0)


class BookmakerOdds(BaseModel):
    bookmaker: str
    home: float = Field(gt=1.0)
    draw: float = Field(gt=1.0)
    away: float = Field(gt=1.0)
    last_update: datetime | None = None
    totals: TotalsLine | None = None


class MatchOdds(BaseModel):
    best_home: float
    best_draw: float
    best_away: float
    bookmakers: list[BookmakerOdds] = Field(default_factory=list)
    totals_line: float | None = None
    best_over: float | None = None
    best_under: float | None = None


class OddsHistoryPoint(BaseModel):
    """Single timestamped snapshot comparing bookie line vs Bayesian consensus."""

    captured_at: datetime
    outcome: Outcome
    bookie_odds: float
    bookie_implied_prob: float
    consensus_prob: float
    consensus_true_odds: float
    delta_prob: float = Field(
        description="consensus_prob − bookie_implied_prob (positive = +EV territory)"
    )
    ev_pct: float
    is_positive_ev: bool
    market: Literal["h2h", "totals"] = "h2h"
    line: float | None = None
    side: Literal["over", "under"] | None = None


class OddsHistoryResponse(BaseModel):
    match_id: str
    home_team: str
    away_team: str
    league: LeagueKey
    league_name: str
    outcome: Outcome
    market: Literal["h2h", "totals"] = "h2h"
    opening: OddsHistoryPoint | None = None
    current: OddsHistoryPoint | None = None
    points: list[OddsHistoryPoint] = Field(default_factory=list)
    value_shift_ev: float = Field(
        default=0.0,
        description="Current EV% minus opening EV% (positive = moved further into +EV)",
    )
    into_positive_ev: bool = False
    source: Literal["supabase", "memory", "synthetic"] = "synthetic"


class ConsensusScore(BaseModel):
    home: float
    draw: float
    away: float
    pick: Outcome
    confidence: float
    source_weights: dict[str, float] = Field(default_factory=dict)


class EdgeMetrics(BaseModel):
    outcome: Outcome
    probability: float
    odds: float
    fair_prob: float
    ev_pct: float
    kelly_pct: float
    is_positive_ev: bool


class MatchCard(BaseModel):
    id: str
    league: LeagueKey
    league_name: str
    commence_time: datetime
    home_team: str
    away_team: str
    odds: MatchOdds
    predictions: list[SourcePrediction]
    consensus: ConsensusScore
    best_edge: EdgeMetrics
    edges: list[EdgeMetrics]


class CalculatorRequest(BaseModel):
    bankroll: float = Field(gt=0, description="Current bankroll in currency units")
    decimal_odds: float = Field(gt=1.0)
    win_probability: float = Field(ge=0, le=1)
    kelly_fraction: float = Field(default=0.25, gt=0, le=1)


class CalculatorResponse(BaseModel):
    ev_pct: float
    ev_decimal: float
    is_positive_ev: bool
    fair_odds: float
    full_kelly_pct: float
    fractional_kelly_pct: float
    recommended_stake: float
    expected_return: float
    edge: float
    kelly_fraction_used: float


class SourcePerformance(BaseModel):
    source: PredictionSource | str
    league: LeagueKey | str
    total_predictions: int
    correct: int
    accuracy: float
    brier_score: float
    avg_ev_captured: float
    last_30_days_accuracy: float
    rank: int | None = None


class LeaguePerformanceSummary(BaseModel):
    league: LeagueKey
    league_name: str
    sources: list[SourcePerformance]
    best_source: str
    consensus_accuracy: float
