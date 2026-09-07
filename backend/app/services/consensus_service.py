"""Consensus orchestration: scrape → weight → EV/Kelly."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.core.config import settings
from app.core.math_engine import (
    bayesian_consensus,
    compute_match_edges,
)
from app.models.schemas import (
    LEAGUE_META,
    ConsensusScore,
    EdgeMetrics,
    LeagueKey,
    MatchCard,
    MatchOdds,
    Outcome,
    SourcePrediction,
)
from app.scrapers.prediction_sites import scrape_all_sources
from app.services.odds_history_service import record_match_snapshot
from app.services.odds_service import odds_client
from app.services.performance_service import get_source_accuracies

logger = logging.getLogger(__name__)


async def build_match_card(event: dict, league: LeagueKey, bankroll: float | None = None) -> MatchCard:
    home = event["home_team"]
    away = event["away_team"]
    odds: MatchOdds = odds_client.parse_match_odds(event)

    predictions = await scrape_all_sources(home, away, league)
    accuracies = get_source_accuracies(league)

    source_probs: dict[str, dict[Outcome, float]] = {}
    for pred in predictions:
        source_probs[pred.source] = {
            "home": pred.home_prob,
            "draw": pred.draw_prob,
            "away": pred.away_prob,
        }

    # Use multiplicative-devigged market as weak Bayesian prior
    from app.core.math_engine import multiplicative_devig

    prior_devig = multiplicative_devig(odds.best_home, odds.best_draw, odds.best_away)
    prior = {"home": prior_devig.home, "draw": prior_devig.draw, "away": prior_devig.away}

    if not source_probs:
        # All scrapers blocked/failed — degrade to market-implied probabilities only
        logger.warning(
            "No active prediction sources for %s vs %s (%s); using market prior alone",
            home,
            away,
            league,
        )
        from app.core.math_engine import ConsensusResult

        consensus = ConsensusResult(
            home=prior["home"],
            draw=prior["draw"],
            away=prior["away"],
            pick=max(prior, key=prior.get),  # type: ignore[arg-type]
            confidence=0.0,
            source_weights={},
        )
    else:
        consensus = bayesian_consensus(
            source_probs=source_probs,
            source_accuracies={s: accuracies.get(s, 0.33) for s in source_probs},
            prior=prior,
            prior_strength=1.5,
        )

    pipeline = compute_match_edges(
        consensus=consensus,
        bookie_odds={
            "home": odds.best_home,
            "draw": odds.best_draw,
            "away": odds.best_away,
        },
        kelly_fraction=settings.default_kelly_fraction,
        bankroll=bankroll,
        devig_method="multiplicative",
    )

    edges: list[EdgeMetrics] = []
    for outcome, data in pipeline["edges"].items():
        edges.append(
            EdgeMetrics(
                outcome=outcome,  # type: ignore[arg-type]
                probability=data["probability"],
                odds=data["odds"],
                fair_prob=data["fair_prob"],
                ev_pct=data["ev"]["ev_pct"],
                kelly_pct=data["kelly"]["recommended_stake_pct"],
                is_positive_ev=data["ev"]["is_positive"],
            )
        )

    best = pipeline["best_bet"]
    best_edge = EdgeMetrics(
        outcome=best["outcome"],
        probability=best["probability"],
        odds=best["odds"],
        fair_prob=best["fair_prob"],
        ev_pct=best["ev"]["ev_pct"],
        kelly_pct=best["kelly"]["recommended_stake_pct"],
        is_positive_ev=best["ev"]["is_positive"],
    )

    commence = event.get("commence_time")
    if isinstance(commence, str):
        commence_dt = datetime.fromisoformat(commence.replace("Z", "+00:00"))
    else:
        commence_dt = datetime.now(timezone.utc)

    return MatchCard(
        id=event.get("id", f"{league}-{home}-{away}"),
        league=league,
        league_name=LEAGUE_META[league]["name"],
        commence_time=commence_dt,
        home_team=home,
        away_team=away,
        odds=odds,
        predictions=predictions,
        consensus=ConsensusScore(**pipeline["consensus"]),
        best_edge=best_edge,
        edges=edges,
    )


async def get_live_matches(
    league: LeagueKey | None = None,
    positive_ev_only: bool = False,
    bankroll: float | None = None,
) -> list[MatchCard]:
    leagues: list[LeagueKey] = (
        [league]
        if league
        else ["epl", "laliga", "bundesliga", "seriea", "ucl", "uel"]  # type: ignore[list-item]
    )
    cards: list[MatchCard] = []
    for lg in leagues:
        events = await odds_client.fetch_league_odds(lg)
        for event in events:
            try:
                card = await build_match_card(event, lg, bankroll=bankroll)
                record_match_snapshot(card)
                if positive_ev_only and not card.best_edge.is_positive_ev:
                    continue
                cards.append(card)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Failed to build match card: %s", exc)

    cards.sort(key=lambda c: (-c.best_edge.ev_pct, c.commence_time))
    return cards


def aggregator_matrix_row(card: MatchCard) -> dict:
    """Flatten a match into an aggregator-matrix friendly structure."""
    by_source = {p.source: p for p in card.predictions}
    sources = ["forebet", "predictz", "windrawwin", "betimate", "footballwhispers"]
    matrix: dict = {
        "match_id": card.id,
        "league": card.league,
        "home_team": card.home_team,
        "away_team": card.away_team,
        "commence_time": card.commence_time.isoformat(),
        "consensus": card.consensus.model_dump(),
        "best_edge": card.best_edge.model_dump(),
        "odds": {
            "home": card.odds.best_home,
            "draw": card.odds.best_draw,
            "away": card.odds.best_away,
        },
        "sources": {},
    }
    for s in sources:
        pred = by_source.get(s)
        if pred:
            matrix["sources"][s] = {
                "home": pred.home_prob,
                "draw": pred.draw_prob,
                "away": pred.away_prob,
                "pick": pred.pick,
            }
        else:
            matrix["sources"][s] = None
    return matrix
