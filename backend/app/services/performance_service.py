"""Historical model performance tracking (30-day rolling accuracy)."""

from __future__ import annotations

import logging
import time

from app.models.schemas import (
    LEAGUE_META,
    LeagueKey,
    LeaguePerformanceSummary,
    SourcePerformance,
)
from app.services.supabase_store import get_supabase_client, is_supabase_configured

logger = logging.getLogger(__name__)

DEFAULT_ACCURACY_PRIOR = 0.50
DEFAULT_BRIER_PRIOR = 0.25
_ACTIVE_LEAGUES: list[str] = list(LEAGUE_META.keys())

_perf_cache: dict[str, dict[str, dict[str, float | int]]] | None = None
_perf_cache_at: float = 0.0
_PERF_CACHE_TTL_SECONDS = 300


def invalidate_performance_cache() -> None:
    global _perf_cache, _perf_cache_at
    _perf_cache = None
    _perf_cache_at = 0.0


def _empty_league_stats() -> dict[str, dict[str, float | int]]:
    return {}


def _load_tipster_performance() -> dict[str, dict[str, dict[str, float | int]]]:
    """Return {league: {source: {total, won, win_rate, brier}}}."""
    global _perf_cache, _perf_cache_at

    now = time.monotonic()
    if _perf_cache is not None and (now - _perf_cache_at) < _PERF_CACHE_TTL_SECONDS:
        return _perf_cache

    by_league: dict[str, dict[str, dict[str, float | int]]] = {
        league: _empty_league_stats() for league in _ACTIVE_LEAGUES
    }

    if not is_supabase_configured():
        _perf_cache = by_league
        _perf_cache_at = now
        return by_league

    client = get_supabase_client()
    if client is None:
        _perf_cache = by_league
        _perf_cache_at = now
        return by_league

    try:
        resp = client.table("tipster_performance").select("*").execute()
        for row in resp.data or []:
            league = row.get("league")
            source = row.get("source")
            if not league or not source:
                continue
            bucket = by_league.setdefault(league, _empty_league_stats())
            total = int(row.get("total_picks") or 0)
            won = int(row.get("won_picks") or 0)
            bucket[source] = {
                "total": total,
                "won": won,
                "d30": float(row.get("win_rate") or DEFAULT_ACCURACY_PRIOR),
                "brier": float(row.get("brier_score") or DEFAULT_BRIER_PRIOR),
                "ev": 0.0,
            }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to load tipster_performance: %s", exc)

    _perf_cache = by_league
    _perf_cache_at = now
    return by_league


def _consensus_stats_from_db(league: LeagueKey) -> dict[str, float | int] | None:
    """Best-effort consensus rollup from settled consensus_runs (last 30 days)."""
    if not is_supabase_configured():
        return None

    client = get_supabase_client()
    if client is None:
        return None

    from datetime import datetime, timedelta, timezone

    since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    try:
        resp = (
            client.table("consensus_runs")
            .select("pick, matches!inner(league_key, result_outcome, commence_time, status)")
            .eq("matches.league_key", league)
            .eq("matches.status", "finished")
            .gte("matches.commence_time", since)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("consensus rollup unavailable for %s: %s", league, exc)
        return None

    rows = resp.data or []
    if not rows:
        return None

    total = 0
    correct = 0
    for row in rows:
        match = row.get("matches") or {}
        outcome = match.get("result_outcome")
        if not outcome:
            continue
        total += 1
        if row.get("pick") == outcome:
            correct += 1

    if total == 0:
        return None

    accuracy = correct / total
    return {
        "total": total,
        "correct": correct,
        "brier": DEFAULT_BRIER_PRIOR,
        "ev": 0.0,
        "d30": round(accuracy, 4),
    }


def get_source_accuracies(league: LeagueKey) -> dict[str, float]:
    """Return last-30-day accuracy weights for Bayesian consensus."""
    league_data = _load_tipster_performance().get(league, {})
    if not league_data:
        return {}

    return {
        source: float(stats.get("d30", DEFAULT_ACCURACY_PRIOR))
        for source, stats in league_data.items()
        if source != "consensus"
    }


def _stats_for_source(
    league: str,
    source: str,
    stats: dict[str, float | int] | None,
) -> dict[str, float | int]:
    if stats:
        return stats
    return {
        "total": 0,
        "won": 0,
        "d30": DEFAULT_ACCURACY_PRIOR,
        "brier": DEFAULT_BRIER_PRIOR,
        "ev": 0.0,
    }


def _to_source_performance(
    source: str,
    league: str,
    stats: dict[str, float | int],
    rank: int | None = None,
) -> SourcePerformance:
    total = int(stats.get("total", 0))
    won = int(stats.get("won", stats.get("correct", 0)))
    accuracy = won / total if total else DEFAULT_ACCURACY_PRIOR
    return SourcePerformance(
        source=source,
        league=league,
        total_predictions=total,
        correct=won,
        accuracy=round(accuracy, 4),
        brier_score=float(stats.get("brier", DEFAULT_BRIER_PRIOR)),
        avg_ev_captured=float(stats.get("ev", 0.0)),
        last_30_days_accuracy=float(stats.get("d30", DEFAULT_ACCURACY_PRIOR)),
        rank=rank,
    )


def get_league_performance(league: LeagueKey | None = None) -> list[LeaguePerformanceSummary]:
    performance = _load_tipster_performance()
    leagues: list[str] = [league] if league else list(_ACTIVE_LEAGUES)
    summaries: list[LeaguePerformanceSummary] = []

    for lg in leagues:
        data = performance.get(lg, {})
        source_rows = [
            _to_source_performance(src, lg, stats)
            for src, stats in data.items()
            if src != "consensus"
        ]
        source_rows.sort(key=lambda s: s.last_30_days_accuracy, reverse=True)
        for i, row in enumerate(source_rows, start=1):
            row.rank = i

        consensus_stats = data.get("consensus") or _consensus_stats_from_db(lg)  # type: ignore[arg-type]
        if consensus_stats:
            consensus_acc = float(consensus_stats.get("d30", DEFAULT_ACCURACY_PRIOR))
        elif source_rows:
            consensus_acc = round(
                sum(r.last_30_days_accuracy for r in source_rows) / len(source_rows),
                4,
            )
        else:
            consensus_acc = DEFAULT_ACCURACY_PRIOR

        best = source_rows[0].source if source_rows else "n/a"

        summaries.append(
            LeaguePerformanceSummary(
                league=lg,  # type: ignore[arg-type]
                league_name=LEAGUE_META.get(lg, {}).get("name", lg),
                sources=source_rows,
                best_source=str(best),
                consensus_accuracy=consensus_acc,
            )
        )
    return summaries


def get_global_leaderboard() -> list[SourcePerformance]:
    """Aggregate accuracy across all leagues for a global source ranking."""
    performance = _load_tipster_performance()
    aggregates: dict[str, dict[str, float]] = {}

    for league, sources in performance.items():
        for source, stats in sources.items():
            if source == "consensus":
                continue
            bucket = aggregates.setdefault(
                source,
                {"total": 0, "won": 0, "brier": 0.0, "ev": 0.0, "d30": 0.0, "n": 0},
            )
            total = int(stats.get("total", 0))
            won = int(stats.get("won", 0))
            bucket["total"] += total
            bucket["won"] += won
            if total > 0:
                bucket["brier"] += float(stats.get("brier", DEFAULT_BRIER_PRIOR))
                bucket["ev"] += float(stats.get("ev", 0.0))
                bucket["d30"] += float(stats.get("d30", DEFAULT_ACCURACY_PRIOR))
                bucket["n"] += 1

    rows: list[SourcePerformance] = []
    for source, agg in aggregates.items():
        n = max(agg["n"], 1)
        total = int(agg["total"])
        won = int(agg["won"])
        rows.append(
            SourcePerformance(
                source=source,
                league="all",
                total_predictions=total,
                correct=won,
                accuracy=round(won / total, 4) if total else DEFAULT_ACCURACY_PRIOR,
                brier_score=round(agg["brier"] / n, 4) if agg["n"] else DEFAULT_BRIER_PRIOR,
                avg_ev_captured=round(agg["ev"] / n, 2) if agg["n"] else 0.0,
                last_30_days_accuracy=round(agg["d30"] / n, 4) if agg["n"] else DEFAULT_ACCURACY_PRIOR,
            )
        )

    if not rows:
        return []

    rows.sort(key=lambda r: r.last_30_days_accuracy, reverse=True)
    for i, row in enumerate(rows, start=1):
        row.rank = i
    return rows
