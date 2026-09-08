"""Consensus orchestration: scrape → weight → EV/Kelly."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.core.cache import cache_get_last_good, cache_get_nonempty, cache_set
from app.core.config import settings
from app.core.math_engine import (
    ConsensusResult,
    Outcome as OutcomeType,
    adaptive_prior_strength,
    bayesian_consensus,
    compute_match_edges,
    is_btts_lucky_not_good,
    resolve_away_xga,
    xg_implied_probabilities,
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
from app.services.standings_service import get_btts_rate, get_relegation_desperation_flag
from app.services.understat_service import get_fixture_xg

logger = logging.getLogger(__name__)

XG_MODEL_SOURCE = "xg_model"
XG_MODEL_WEIGHT = 0.40  # flat accuracy weight for the Poisson xG signal, between a weak and average tipster


def _consensus_from_prior(prior: dict[Outcome, float]) -> ConsensusResult:
    """Pure devigged-market consensus when no tipster or xG signals are available."""
    outcomes: list[Outcome] = ["home", "draw", "away"]
    pick: Outcome = max(outcomes, key=lambda o: prior[o])
    sorted_p = sorted(prior.values(), reverse=True)
    confidence = float(sorted_p[0] - sorted_p[1])
    return ConsensusResult(
        home=float(prior["home"]),
        draw=float(prior["draw"]),
        away=float(prior["away"]),
        pick=pick,
        confidence=confidence,
        source_weights={"market_prior": 1.0},
    )


async def build_match_card(
    event: dict,
    league: LeagueKey,
    bankroll: float | None = None,
    *,
    scrape_predictions: bool = True,
) -> MatchCard:
    home = event["home_team"]
    away = event["away_team"]
    odds: MatchOdds = odds_client.parse_match_odds(event)

    if scrape_predictions:
        predictions, xg = await asyncio.gather(
            scrape_all_sources(home, away, league),
            get_fixture_xg(home, away, league),
        )
    else:
        predictions = []
        xg = await get_fixture_xg(home, away, league)
    accuracies = get_source_accuracies(league)

    source_probs: dict[str, dict[Outcome, float]] = {}
    for pred in predictions:
        source_probs[pred.source] = {
            "home": pred.home_prob,
            "draw": pred.draw_prob,
            "away": pred.away_prob,
        }

    btts_penalty_outcomes: set[OutcomeType] = set()

    # Phase 2/4: blend xG-implied signal when live Understat data exists, or in demo mode.
    # Seeded demo xG is never injected when USE_DEMO_DATA=false.
    if xg is not None and (xg.home.source == "understat" or settings.use_demo_data):
        home_desperation = await get_relegation_desperation_flag(home, league)
        away_isolated_xga = xg.away.isolated_away_xga if xg.away.isolated_away_xga is not None else xg.away.xga
        resolved_away_xga = resolve_away_xga(
            away_overall_xga=xg.away.xga,
            away_isolated_xga=away_isolated_xga,
            home_desperation_flag=home_desperation,
        )
        xg_probs = xg_implied_probabilities(
            home_xg=xg.home.xg,
            home_xga=xg.home.xga,
            away_xg=xg.away.xg,
            away_xga=resolved_away_xga,
        )
        source_probs[XG_MODEL_SOURCE] = xg_probs
        accuracies[XG_MODEL_SOURCE] = XG_MODEL_WEIGHT
        if home_desperation:
            logger.info(
                "%s vs %s (%s): home relegation-desperation flag set — away xGA input "
                "switched from overall %.2f to away-venue-isolated %.2f",
                home,
                away,
                league,
                xg.away.xga,
                resolved_away_xga,
            )
        if is_btts_lucky_not_good(get_btts_rate(home, league), xg.home.xg):
            btts_penalty_outcomes.add("home")
        if is_btts_lucky_not_good(get_btts_rate(away, league), xg.away.xg):
            btts_penalty_outcomes.add("away")

    # Use multiplicative-devigged market as weak Bayesian prior
    from app.core.math_engine import multiplicative_devig

    prior_devig = multiplicative_devig(odds.best_home, odds.best_draw, odds.best_away)
    prior = {"home": prior_devig.home, "draw": prior_devig.draw, "away": prior_devig.away}

    if not predictions:
        has_xg = XG_MODEL_SOURCE in source_probs
        if has_xg:
            logger.warning(
                "No active tipster sources for %s vs %s (%s); using xG signal + market prior",
                home,
                away,
                league,
            )
        else:
            logger.warning(
                "No active tipster sources and no live xG for %s vs %s (%s); "
                "using devigged market prior only",
                home,
                away,
                league,
            )

    if source_probs:
        consensus = bayesian_consensus(
            source_probs=source_probs,
            source_accuracies={s: accuracies.get(s, 0.50) for s in source_probs},
            prior=prior,
            prior_strength=adaptive_prior_strength(prior),
        )
    else:
        consensus = _consensus_from_prior(prior)

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
        btts_penalty_outcomes=btts_penalty_outcomes,
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
                raw_ev_pct=data["ev"].get("raw_ev_pct"),
                is_ev_anomaly=data["ev"].get("is_anomaly", False),
                ev_anomaly_reason=data["ev"].get("anomaly_reason"),
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
        raw_ev_pct=best["ev"].get("raw_ev_pct"),
        is_ev_anomaly=best["ev"].get("is_anomaly", False),
        ev_anomaly_reason=best["ev"].get("anomaly_reason"),
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


def _event_commence_utc(event: dict) -> datetime | None:
    commence = event.get("commence_time")
    if isinstance(commence, str):
        return datetime.fromisoformat(commence.replace("Z", "+00:00"))
    if isinstance(commence, datetime):
        return commence if commence.tzinfo else commence.replace(tzinfo=timezone.utc)
    return None


def _filter_upcoming_events(events: list[dict], *, days_ahead: int) -> list[dict]:
    """Keep fixtures from now through the next N days (UTC). days_ahead=0 means no limit."""
    if days_ahead <= 0:
        return events
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=days_ahead)
    kept: list[dict] = []
    for event in events:
        commence = _event_commence_utc(event)
        if commence is None:
            continue
        commence = commence.astimezone(timezone.utc)
        if now - timedelta(hours=2) <= commence <= horizon:
            kept.append(event)
    return kept


async def get_live_matches(
    league: LeagueKey | None = None,
    positive_ev_only: bool = False,
    bankroll: float | None = None,
    days_ahead: int | None = None,
) -> list[MatchCard]:
    if days_ahead is None:
        days_ahead = settings.matches_days_ahead

    leagues: list[LeagueKey] = (
        [league]
        if league
        else ["epl", "laliga", "bundesliga", "seriea", "ucl", "uel"]  # type: ignore[list-item]
    )
    league_key = ",".join(leagues)
    cache_key = f"cards:{league_key}:{positive_ev_only}:{bankroll}:{days_ahead}"
    cached = cache_get_nonempty(cache_key)
    if cached is not None:
        return cached

    league_events = await asyncio.gather(*[odds_client.fetch_league_odds(lg) for lg in leagues])

    if days_ahead > 0:
        league_events = [_filter_upcoming_events(events, days_ahead=days_ahead) for events in league_events]
        total = sum(len(e) for e in league_events)
        logger.info(
            "Upcoming filter (next %d days UTC): %d fixtures across %d leagues",
            days_ahead,
            total,
            len(leagues),
        )

    sem = asyncio.Semaphore(settings.match_build_concurrency)

    async def _build(event: dict, lg: LeagueKey) -> MatchCard | None:
        async with sem:
            try:
                # Live tipster scrapes run on the scheduler sync job only — not on
                # every dashboard poll (5 sites × N fixtures would exceed HTTP timeouts).
                card = await build_match_card(
                    event, lg, bankroll=bankroll, scrape_predictions=False
                )
                record_match_snapshot(card)
                if positive_ev_only and not card.best_edge.is_positive_ev:
                    return None
                return card
            except Exception as exc:  # noqa: BLE001
                logger.exception("Failed to build match card: %s", exc)
                return None

    tasks = [
        _build(event, lg)
        for lg, events in zip(leagues, league_events)
        for event in events
    ]
    built = await asyncio.gather(*tasks)
    cards = [c for c in built if c is not None]
    cards.sort(
        key=lambda c: (
            -int(c.best_edge.is_positive_ev),
            -c.best_edge.ev_pct,
            c.commence_time,
        )
    )
    if cards:
        cache_set(cache_key, cards)
        return cards

    stale = cache_get_last_good(cache_key)
    if stale is not None:
        logger.warning(
            "Fresh match build returned empty for %s — serving last good snapshot", cache_key
        )
        return stale

    # Avoid caching empty responses so the next poll retries live fetches.
    return []


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
