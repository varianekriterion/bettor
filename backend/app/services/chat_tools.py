"""
LangChain tool definitions for the /api/v1/chat agent (Phase 3).

Tools are built per-request via `build_chat_tools()` rather than as module-
level singletons, since `search_past_bet_mistakes` must be scoped to the
requesting user's `bet_journal_vectors` rows (RLS-equivalent scoping done
server-side because the RPC call uses the service-role key).
"""

from __future__ import annotations

import logging

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.core.math_engine import calculate_attacking_pressure
from app.services import performance_service, rag_service, understat_service

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# query_xg_stats
# ---------------------------------------------------------------------------


class QueryXGStatsArgs(BaseModel):
    home_team: str = Field(description="Home team name, e.g. 'Girona'")
    away_team: str = Field(description="Away team name, e.g. 'Real Betis'")
    league: str = Field(
        description="League key: epl, laliga, bundesliga, seriea, ucl, or uel"
    )
    season: str | None = Field(
        default=None, description="Season start year, e.g. '2025'. Defaults to current season."
    )


async def _query_xg_stats(
    home_team: str, away_team: str, league: str, season: str | None = None
) -> str:
    stats = await understat_service.get_fixture_xg(home_team, away_team, league, season)
    caveat = (
        ""
        if stats.home.source == "understat"
        else (
            " (NOTE: this is seeded/simulated demo data, not a live Understat lookup — "
            "say so if you use it. Understat doesn't cover UCL/UEL fixtures.)"
        )
    )
    home_pressure = (
        calculate_attacking_pressure(
            stats.home.shots_on_target or 0.0, stats.home.corners or 0.0, team=home_team
        )
        if stats.home.shots_on_target is not None and stats.home.corners is not None
        else None
    )
    away_pressure = (
        calculate_attacking_pressure(
            stats.away.shots_on_target or 0.0, stats.away.corners or 0.0, team=away_team
        )
        if stats.away.shots_on_target is not None and stats.away.corners is not None
        else None
    )

    return (
        f"xG stats for {home_team} vs {away_team} ({league}, {season or 'current season'}):\n"
        f"| Team | xG (for) | xGA (against) | Shots on Target | Corners | Attacking Pressure |\n"
        f"|---|---|---|---|---|---|\n"
        f"| {home_team} (home) | {stats.home.xg} | {stats.home.xga} | "
        f"{stats.home.shots_on_target or 'n/a'} | {stats.home.corners or 'n/a'} | "
        f"{home_pressure.pressure_score if home_pressure else 'n/a'} |\n"
        f"| {away_team} (away) | {stats.away.xg} | {stats.away.xga} | "
        f"{stats.away.shots_on_target or 'n/a'} | {stats.away.corners or 'n/a'} | "
        f"{away_pressure.pressure_score if away_pressure else 'n/a'} |\n"
        "Attacking Pressure: 100 = league-average shot/corner volume; simulated inputs "
        "until a real per-90 stats feed (e.g. FootyStats) is wired in.\n"
        f"{caveat}"
    )


def _make_query_xg_stats_tool() -> StructuredTool:
    return StructuredTool.from_function(
        coroutine=_query_xg_stats,
        name="query_xg_stats",
        description=(
            "Look up Expected Goals (xG) and Expected Goals Against (xGA) for both "
            "teams in a fixture, plus simulated shots-on-target/corners pressure "
            "inputs. Use this whenever a user asks about attacking quality, form, "
            "or 'is this team actually good vs just lucky'."
        ),
        args_schema=QueryXGStatsArgs,
    )


# ---------------------------------------------------------------------------
# query_tipster_accuracy
# ---------------------------------------------------------------------------


class QueryTipsterAccuracyArgs(BaseModel):
    league: str | None = Field(
        default=None,
        description="League key to scope to (epl, laliga, bundesliga, seriea, ucl, uel). "
        "Omit for a global 30-day leaderboard across all leagues.",
    )
    source: str | None = Field(
        default=None,
        description="Restrict to one tipster source, e.g. 'forebet'. Omit for all sources.",
    )


def _query_tipster_accuracy(league: str | None = None, source: str | None = None) -> str:
    if league:
        summaries = performance_service.get_league_performance(league)  # type: ignore[arg-type]
        rows = summaries[0].sources if summaries else []
        header = f"30-day source accuracy — {league}:\n"
    else:
        rows = performance_service.get_global_leaderboard()
        header = "30-day global source accuracy leaderboard:\n"

    if source:
        rows = [r for r in rows if r.source == source]
        if not rows:
            return f"No performance data found for source '{source}'" + (f" in {league}." if league else ".")

    lines = [header, "| Source | Accuracy | Brier | Avg EV Captured | Rank |", "|---|---|---|---|---|"]
    for r in rows:
        lines.append(
            f"| {r.source} | {r.accuracy:.1%} | {r.brier_score:.3f} | {r.avg_ev_captured:+.2f}% | {r.rank or '-'} |"
        )
    return "\n".join(lines)


def _make_query_tipster_accuracy_tool() -> StructuredTool:
    return StructuredTool.from_function(
        func=_query_tipster_accuracy,
        name="query_tipster_accuracy",
        description=(
            "Look up a prediction source's (tipster's) rolling 30-day accuracy, "
            "Brier score, and average EV captured — per league or globally. Use "
            "this to answer 'is this tipster actually reliable' questions."
        ),
        args_schema=QueryTipsterAccuracyArgs,
    )


# ---------------------------------------------------------------------------
# search_past_bet_mistakes
# ---------------------------------------------------------------------------


class SearchPastBetMistakesArgs(BaseModel):
    query: str = Field(
        description="Natural-language description of the situation to search for, "
        "e.g. 'backing BTTS on a team with low xG' or 'following forebet on an away favourite'."
    )
    match_count: int = Field(default=5, ge=1, le=20)


def _make_search_past_bet_mistakes_tool(user_id: str | None) -> StructuredTool:
    async def _search(query: str, match_count: int = 5) -> str:
        if not user_id:
            return (
                "No signed-in user context, so I can't search bet journal history "
                "for this session — treat any 'past mistakes' claim as unverified."
            )
        rows = await rag_service.search_past_bet_mistakes(query, user_id=user_id, match_count=match_count)
        if not rows:
            return "No similar past bets found in the journal (or the memory index is empty)."
        lines = [f"Past bets similar to: \"{query}\"", "| Similarity | Summary |", "|---|---|"]
        for row in rows:
            similarity = row.get("similarity", 0.0)
            content = str(row.get("content", "")).replace("\n", " ").replace("|", "/")
            lines.append(f"| {similarity:.0%} | {content} |")
        return "\n".join(lines)

    return StructuredTool.from_function(
        coroutine=_search,
        name="search_past_bet_mistakes",
        description=(
            "Semantic search over the user's own settled-bet history (pgvector) to "
            "find similar past situations and what actually happened. Use this "
            "before endorsing a bet pattern the user has tried before."
        ),
        args_schema=SearchPastBetMistakesArgs,
    )


# ---------------------------------------------------------------------------


def build_chat_tools(user_id: str | None = None) -> list[StructuredTool]:
    """Assemble the per-request tool list for the chat agent."""
    return [
        _make_query_xg_stats_tool(),
        _make_query_tipster_accuracy_tool(),
        _make_search_past_bet_mistakes_tool(user_id),
    ]
