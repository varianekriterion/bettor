"""Odds snapshot persistence and line-movement history vs Bayesian consensus."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from app.core.math_engine import expected_value
from app.models.schemas import (
    LEAGUE_META,
    LeagueKey,
    MatchCard,
    OddsHistoryPoint,
    OddsHistoryResponse,
    Outcome,
)
from app.services.supabase_store import fetch_consensus_runs, fetch_odds_snapshots, get_supabase_client

logger = logging.getLogger(__name__)

MAX_MEMORY_POINTS = 180
# Minimum gap between in-memory snapshot writes for the same match.
SNAPSHOT_THROTTLE_SECONDS = 90

_memory_h2h: dict[str, list[dict[str, Any]]] = defaultdict(list)
_memory_consensus: dict[str, list[dict[str, Any]]] = defaultdict(list)
_memory_meta: dict[str, dict[str, Any]] = {}
_last_record_at: dict[str, datetime] = {}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return _utcnow()


def _outcome_odds(home: float, draw: float, away: float, outcome: Outcome) -> float:
    return {"home": home, "draw": draw, "away": away}[outcome]


def _outcome_prob(home: float, draw: float, away: float, outcome: Outcome) -> float:
    return {"home": home, "draw": draw, "away": away}[outcome]


def _build_point(
    *,
    captured_at: datetime,
    outcome: Outcome,
    bookie_odds: float,
    consensus_prob: float,
    market: Literal["h2h", "totals"] = "h2h",
    line: float | None = None,
    side: Literal["over", "under"] | None = None,
) -> OddsHistoryPoint:
    bookie_implied = 1.0 / bookie_odds if bookie_odds > 1 else 0.0
    consensus_true_odds = (1.0 / consensus_prob) if consensus_prob > 0 else 0.0
    delta = consensus_prob - bookie_implied
    ev = expected_value(consensus_prob, bookie_odds)
    return OddsHistoryPoint(
        captured_at=captured_at,
        outcome=outcome,
        bookie_odds=round(bookie_odds, 3),
        bookie_implied_prob=round(bookie_implied, 6),
        consensus_prob=round(consensus_prob, 6),
        consensus_true_odds=round(consensus_true_odds, 4),
        delta_prob=round(delta, 6),
        ev_pct=ev.ev_pct,
        is_positive_ev=ev.is_positive,
        market=market,
        line=line,
        side=side,
    )


def record_match_snapshot(card: MatchCard, *, force: bool = False) -> None:
    """
    Append an in-memory odds + consensus snapshot for line-movement charts.
    Throttled so live feed polling does not explode memory.
    """
    now = _utcnow()
    last = _last_record_at.get(card.id)
    if not force and last and (now - last).total_seconds() < SNAPSHOT_THROTTLE_SECONDS:
        return

    captured = now
    # Prefer freshest bookmaker last_update when available.
    updates = [b.last_update for b in card.odds.bookmakers if b.last_update]
    if updates:
        captured = max(_parse_ts(u) for u in updates)

    _memory_meta[card.id] = {
        "home_team": card.home_team,
        "away_team": card.away_team,
        "league": card.league,
        "league_name": card.league_name,
    }
    _memory_h2h[card.id].append(
        {
            "captured_at": captured.isoformat(),
            "home_odds": card.odds.best_home,
            "draw_odds": card.odds.best_draw,
            "away_odds": card.odds.best_away,
            "over_odds": card.odds.best_over,
            "under_odds": card.odds.best_under,
            "line": card.odds.totals_line,
            "market_type": "h2h",
        }
    )
    _memory_consensus[card.id].append(
        {
            "created_at": captured.isoformat(),
            "home_prob": card.consensus.home,
            "draw_prob": card.consensus.draw,
            "away_prob": card.consensus.away,
            "pick": card.consensus.pick,
        }
    )
    # Cap ring buffers
    if len(_memory_h2h[card.id]) > MAX_MEMORY_POINTS:
        _memory_h2h[card.id] = _memory_h2h[card.id][-MAX_MEMORY_POINTS:]
    if len(_memory_consensus[card.id]) > MAX_MEMORY_POINTS:
        _memory_consensus[card.id] = _memory_consensus[card.id][-MAX_MEMORY_POINTS:]

    _last_record_at[card.id] = now


def _aggregate_best_h2h(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse per-bookmaker rows into best-price buckets by capture minute."""
    buckets: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("market_type", "h2h") not in (None, "h2h"):
            continue
        if row.get("home_odds") is None:
            continue
        ts = _parse_ts(row.get("captured_at"))
        key = ts.replace(second=0, microsecond=0).isoformat()
        bucket = buckets.get(key)
        home = float(row["home_odds"])
        draw = float(row["draw_odds"])
        away = float(row["away_odds"])
        if bucket is None:
            buckets[key] = {
                "captured_at": ts,
                "home_odds": home,
                "draw_odds": draw,
                "away_odds": away,
            }
        else:
            bucket["home_odds"] = max(bucket["home_odds"], home)
            bucket["draw_odds"] = max(bucket["draw_odds"], draw)
            bucket["away_odds"] = max(bucket["away_odds"], away)
            if ts > bucket["captured_at"]:
                bucket["captured_at"] = ts
    return sorted(buckets.values(), key=lambda b: b["captured_at"])


def _nearest_consensus(
    consensus_rows: list[dict[str, Any]],
    target: datetime,
) -> dict[str, Any] | None:
    if not consensus_rows:
        return None
    best = None
    best_dist = None
    for row in consensus_rows:
        ts = _parse_ts(row.get("created_at") or row.get("captured_at"))
        dist = abs((ts - target).total_seconds())
        if best_dist is None or dist < best_dist:
            best = row
            best_dist = dist
    return best


def _points_from_rows(
    odds_rows: list[dict[str, Any]],
    consensus_rows: list[dict[str, Any]],
    outcome: Outcome,
) -> list[OddsHistoryPoint]:
    aggregated = _aggregate_best_h2h(odds_rows)
    points: list[OddsHistoryPoint] = []
    for row in aggregated:
        cons = _nearest_consensus(consensus_rows, row["captured_at"])
        if cons is None:
            continue
        bookie = _outcome_odds(row["home_odds"], row["draw_odds"], row["away_odds"], outcome)
        c_prob = _outcome_prob(
            float(cons["home_prob"]),
            float(cons["draw_prob"]),
            float(cons["away_prob"]),
            outcome,
        )
        points.append(
            _build_point(
                captured_at=row["captured_at"],
                outcome=outcome,
                bookie_odds=bookie,
                consensus_prob=c_prob,
            )
        )
    return points


def _synthetic_history(card: MatchCard, outcome: Outcome) -> list[OddsHistoryPoint]:
    """
    When no historical snapshots exist yet, synthesize a short opening→current
    path so the UI can still render line movement (demo / cold start).
    """
    now = _utcnow()
    current_odds = _outcome_odds(
        card.odds.best_home, card.odds.best_draw, card.odds.best_away, outcome
    )
    current_prob = _outcome_prob(
        card.consensus.home, card.consensus.draw, card.consensus.away, outcome
    )
    # Opening: slightly shorter prices / softer consensus → moves toward current.
    opening_odds = round(max(1.05, current_odds * 0.94), 3)
    opening_prob = min(0.95, max(0.05, current_prob * 0.92))

    steps = 8
    points: list[OddsHistoryPoint] = []
    for i in range(steps):
        t = i / (steps - 1)
        odds = opening_odds + (current_odds - opening_odds) * t
        # Mild mid-path wiggle so the chart isn't a perfect line.
        wiggle = 0.015 * (1 if i % 2 == 0 else -1) * (1 - abs(2 * t - 1))
        odds = max(1.05, odds * (1 + wiggle * 0.15))
        prob = opening_prob + (current_prob - opening_prob) * t
        captured = now - timedelta(hours=(steps - 1 - i) * 3)
        points.append(
            _build_point(
                captured_at=captured,
                outcome=outcome,
                bookie_odds=odds,
                consensus_prob=prob,
            )
        )
    return points


def _finalize(
    *,
    match_id: str,
    home_team: str,
    away_team: str,
    league: LeagueKey,
    outcome: Outcome,
    points: list[OddsHistoryPoint],
    source: Literal["supabase", "memory", "synthetic"],
) -> OddsHistoryResponse:
    opening = points[0] if points else None
    current = points[-1] if points else None
    value_shift = 0.0
    into_pos = False
    if opening and current:
        value_shift = round(current.ev_pct - opening.ev_pct, 4)
        into_pos = (not opening.is_positive_ev and current.is_positive_ev) or (
            current.is_positive_ev and value_shift > 0
        )
    return OddsHistoryResponse(
        match_id=match_id,
        home_team=home_team,
        away_team=away_team,
        league=league,
        league_name=LEAGUE_META.get(league, {}).get("name", league),
        outcome=outcome,
        market="h2h",
        opening=opening,
        current=current,
        points=points,
        value_shift_ev=value_shift,
        into_positive_ev=into_pos,
        source=source,
    )


async def get_odds_history(
    match_id: str,
    *,
    outcome: Outcome | None = None,
    live_card: MatchCard | None = None,
) -> OddsHistoryResponse | None:
    """
    Build timestamped line movements with delta vs Bayesian consensus true odds.
    Prefers Supabase snapshots → in-memory ring → synthetic from live card.
    """
    tracked: Outcome | None = outcome
    if live_card is not None and tracked is None:
        tracked = live_card.best_edge.outcome

    # 1) Supabase
    if get_supabase_client() is not None:
        odds_rows = fetch_odds_snapshots(match_id)
        cons_rows = fetch_consensus_runs(match_id)
        if odds_rows and cons_rows:
            if tracked is None:
                # Infer from latest consensus pick
                tracked = cons_rows[-1].get("pick") or "home"  # type: ignore[assignment]
            assert tracked is not None
            points = _points_from_rows(odds_rows, cons_rows, tracked)
            if points:
                meta = _memory_meta.get(match_id, {})
                home = (live_card.home_team if live_card else None) or meta.get("home_team") or "Home"
                away = (live_card.away_team if live_card else None) or meta.get("away_team") or "Away"
                league = (live_card.league if live_card else None) or meta.get("league") or "epl"
                return _finalize(
                    match_id=match_id,
                    home_team=home,
                    away_team=away,
                    league=league,  # type: ignore[arg-type]
                    outcome=tracked,
                    points=points,
                    source="supabase",
                )

    # 2) In-memory
    mem_odds = _memory_h2h.get(match_id, [])
    mem_cons = _memory_consensus.get(match_id, [])
    if mem_odds and mem_cons and tracked is not None:
        points = _points_from_rows(mem_odds, mem_cons, tracked)
        if len(points) >= 2:
            meta = _memory_meta.get(match_id, {})
            home = (live_card.home_team if live_card else None) or meta.get("home_team") or "Home"
            away = (live_card.away_team if live_card else None) or meta.get("away_team") or "Away"
            league = (live_card.league if live_card else None) or meta.get("league") or "epl"
            return _finalize(
                match_id=match_id,
                home_team=home,
                away_team=away,
                league=league,  # type: ignore[arg-type]
                outcome=tracked,
                points=points,
                source="memory",
            )

    # 3) Synthetic from live card
    if live_card is not None:
        tracked = tracked or live_card.best_edge.outcome
        points = _synthetic_history(live_card, tracked)
        return _finalize(
            match_id=match_id,
            home_team=live_card.home_team,
            away_team=live_card.away_team,
            league=live_card.league,
            outcome=tracked,
            points=points,
            source="synthetic",
        )

    return None
