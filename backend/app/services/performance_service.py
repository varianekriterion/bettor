"""Historical model performance tracking (30-day rolling accuracy)."""

from __future__ import annotations

from app.models.schemas import (
    LEAGUE_META,
    LeagueKey,
    LeaguePerformanceSummary,
    SourcePerformance,
)

# Seeded rolling performance — replace with Supabase queries in production
_PERFORMANCE_SEED: dict[str, dict[str, dict[str, float | int]]] = {
    "epl": {
        "forebet": {"total": 86, "correct": 48, "brier": 0.214, "ev": 2.4, "d30": 0.56},
        "predictz": {"total": 90, "correct": 46, "brier": 0.228, "ev": 1.1, "d30": 0.51},
        "windrawwin": {"total": 78, "correct": 39, "brier": 0.241, "ev": 0.4, "d30": 0.48},
        "betimate": {"total": 84, "correct": 47, "brier": 0.209, "ev": 3.1, "d30": 0.57},
        "footballwhispers": {"total": 72, "correct": 35, "brier": 0.236, "ev": 0.8, "d30": 0.49},
        "consensus": {"total": 90, "correct": 52, "brier": 0.198, "ev": 4.2, "d30": 0.59},
    },
    "laliga": {
        "forebet": {"total": 70, "correct": 39, "brier": 0.221, "ev": 1.8, "d30": 0.54},
        "predictz": {"total": 74, "correct": 38, "brier": 0.233, "ev": 0.9, "d30": 0.50},
        "windrawwin": {"total": 66, "correct": 32, "brier": 0.245, "ev": 0.2, "d30": 0.47},
        "betimate": {"total": 68, "correct": 37, "brier": 0.218, "ev": 2.2, "d30": 0.55},
        "footballwhispers": {"total": 60, "correct": 29, "brier": 0.240, "ev": 0.5, "d30": 0.48},
        "consensus": {"total": 74, "correct": 42, "brier": 0.205, "ev": 3.6, "d30": 0.57},
    },
    "bundesliga": {
        "forebet": {"total": 64, "correct": 36, "brier": 0.217, "ev": 2.0, "d30": 0.55},
        "predictz": {"total": 66, "correct": 34, "brier": 0.230, "ev": 1.0, "d30": 0.52},
        "windrawwin": {"total": 58, "correct": 28, "brier": 0.248, "ev": -0.1, "d30": 0.46},
        "betimate": {"total": 62, "correct": 35, "brier": 0.211, "ev": 2.8, "d30": 0.58},
        "footballwhispers": {"total": 54, "correct": 26, "brier": 0.239, "ev": 0.6, "d30": 0.49},
        "consensus": {"total": 66, "correct": 39, "brier": 0.201, "ev": 3.9, "d30": 0.60},
    },
    "seriea": {
        "forebet": {"total": 68, "correct": 37, "brier": 0.223, "ev": 1.6, "d30": 0.53},
        "predictz": {"total": 72, "correct": 36, "brier": 0.234, "ev": 0.7, "d30": 0.49},
        "windrawwin": {"total": 64, "correct": 31, "brier": 0.244, "ev": 0.3, "d30": 0.47},
        "betimate": {"total": 70, "correct": 39, "brier": 0.215, "ev": 2.5, "d30": 0.56},
        "footballwhispers": {"total": 58, "correct": 28, "brier": 0.237, "ev": 0.9, "d30": 0.50},
        "consensus": {"total": 72, "correct": 41, "brier": 0.207, "ev": 3.4, "d30": 0.58},
    },
    "ucl": {
        "forebet": {"total": 42, "correct": 24, "brier": 0.208, "ev": 2.9, "d30": 0.58},
        "predictz": {"total": 44, "correct": 23, "brier": 0.220, "ev": 1.4, "d30": 0.53},
        "windrawwin": {"total": 38, "correct": 19, "brier": 0.235, "ev": 0.5, "d30": 0.50},
        "betimate": {"total": 40, "correct": 23, "brier": 0.205, "ev": 3.4, "d30": 0.59},
        "footballwhispers": {"total": 36, "correct": 18, "brier": 0.229, "ev": 1.0, "d30": 0.51},
        "consensus": {"total": 44, "correct": 26, "brier": 0.192, "ev": 4.8, "d30": 0.62},
    },
    "uel": {
        "forebet": {"total": 40, "correct": 21, "brier": 0.226, "ev": 1.5, "d30": 0.52},
        "predictz": {"total": 42, "correct": 20, "brier": 0.238, "ev": 0.6, "d30": 0.48},
        "windrawwin": {"total": 36, "correct": 17, "brier": 0.249, "ev": 0.0, "d30": 0.45},
        "betimate": {"total": 38, "correct": 20, "brier": 0.222, "ev": 1.9, "d30": 0.54},
        "footballwhispers": {"total": 34, "correct": 16, "brier": 0.242, "ev": 0.4, "d30": 0.47},
        "consensus": {"total": 42, "correct": 23, "brier": 0.210, "ev": 3.1, "d30": 0.56},
    },
}


def get_source_accuracies(league: LeagueKey) -> dict[str, float]:
    """Return last-30-day accuracy weights for Bayesian consensus."""
    league_data = _PERFORMANCE_SEED.get(league, {})
    return {
        source: float(stats["d30"])
        for source, stats in league_data.items()
        if source != "consensus"
    }


def _to_source_performance(
    source: str,
    league: str,
    stats: dict[str, float | int],
    rank: int | None = None,
) -> SourcePerformance:
    total = int(stats["total"])
    correct = int(stats["correct"])
    accuracy = correct / total if total else 0.0
    return SourcePerformance(
        source=source,
        league=league,
        total_predictions=total,
        correct=correct,
        accuracy=round(accuracy, 4),
        brier_score=float(stats["brier"]),
        avg_ev_captured=float(stats["ev"]),
        last_30_days_accuracy=float(stats["d30"]),
        rank=rank,
    )


def get_league_performance(league: LeagueKey | None = None) -> list[LeaguePerformanceSummary]:
    leagues: list[str] = [league] if league else list(_PERFORMANCE_SEED.keys())
    summaries: list[LeaguePerformanceSummary] = []

    for lg in leagues:
        data = _PERFORMANCE_SEED.get(lg, {})
        source_rows = [
            _to_source_performance(src, lg, stats)
            for src, stats in data.items()
            if src != "consensus"
        ]
        source_rows.sort(key=lambda s: s.last_30_days_accuracy, reverse=True)
        for i, row in enumerate(source_rows, start=1):
            row.rank = i

        consensus_stats = data.get("consensus", {"total": 0, "correct": 0, "brier": 0.25, "ev": 0, "d30": 0.33})
        consensus_acc = float(consensus_stats["d30"])
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
    aggregates: dict[str, dict[str, float]] = {}
    for league, sources in _PERFORMANCE_SEED.items():
        for source, stats in sources.items():
            if source == "consensus":
                continue
            bucket = aggregates.setdefault(
                source,
                {"total": 0, "correct": 0, "brier": 0.0, "ev": 0.0, "d30": 0.0, "n": 0},
            )
            bucket["total"] += float(stats["total"])
            bucket["correct"] += float(stats["correct"])
            bucket["brier"] += float(stats["brier"])
            bucket["ev"] += float(stats["ev"])
            bucket["d30"] += float(stats["d30"])
            bucket["n"] += 1

    rows: list[SourcePerformance] = []
    for source, agg in aggregates.items():
        n = max(agg["n"], 1)
        rows.append(
            SourcePerformance(
                source=source,
                league="all",
                total_predictions=int(agg["total"]),
                correct=int(agg["correct"]),
                accuracy=round(agg["correct"] / agg["total"], 4) if agg["total"] else 0.0,
                brier_score=round(agg["brier"] / n, 4),
                avg_ev_captured=round(agg["ev"] / n, 2),
                last_30_days_accuracy=round(agg["d30"] / n, 4),
            )
        )
    rows.sort(key=lambda r: r.last_30_days_accuracy, reverse=True)
    for i, row in enumerate(rows, start=1):
        row.rank = i
    return rows
