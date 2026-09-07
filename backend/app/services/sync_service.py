"""Scheduled multi-source scraper sync pipeline."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.core.cache import cache_clear_prefix
from app.models.schemas import LeagueKey, MatchCard
from app.services.consensus_service import build_match_card
from app.services.odds_history_service import record_match_snapshot
from app.services.odds_service import odds_client
from app.services.supabase_store import is_supabase_configured, persist_match_card

logger = logging.getLogger(__name__)

ACTIVE_LEAGUES: list[LeagueKey] = [
    "epl",
    "laliga",
    "bundesliga",
    "seriea",
    "ucl",
    "uel",
]


@dataclass
class LeagueSyncResult:
    league: str
    matches: int = 0
    predictions: int = 0
    persisted: int = 0
    persist_failures: int = 0
    skipped_sources: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class SyncResult:
    started_at: str
    finished_at: str | None = None
    leagues: list[LeagueSyncResult] = field(default_factory=list)
    supabase_configured: bool = False
    trigger: str = "scheduler"
    ok: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "supabase_configured": self.supabase_configured,
            "trigger": self.trigger,
            "ok": self.ok,
            "leagues": [asdict(lg) for lg in self.leagues],
            "totals": {
                "matches": sum(lg.matches for lg in self.leagues),
                "predictions": sum(lg.predictions for lg in self.leagues),
                "persisted": sum(lg.persisted for lg in self.leagues),
                "persist_failures": sum(lg.persist_failures for lg in self.leagues),
                "errors": sum(len(lg.errors) for lg in self.leagues),
            },
        }


_last_sync: SyncResult | None = None
_sync_running = False


def get_last_sync() -> SyncResult | None:
    return _last_sync


def is_sync_running() -> bool:
    return _sync_running


async def sync_league_predictions(
    leagues: list[LeagueKey] | None = None,
    *,
    trigger: str = "scheduler",
) -> SyncResult:
    """
    Periodic job: scrape all active sources per fixture, recompute Bayesian
    consensus from remaining sources when individual scrapers fail, and store
    matches + odds_snapshots + predictions + consensus_runs in Supabase.
    """
    global _last_sync, _sync_running

    if _sync_running:
        logger.info("Sync already running — skipping overlapping trigger=%s", trigger)
        if _last_sync:
            return _last_sync
        return SyncResult(
            started_at=datetime.now(timezone.utc).isoformat(),
            trigger=trigger,
            ok=False,
        )

    _sync_running = True
    target = leagues or ACTIVE_LEAGUES
    result = SyncResult(
        started_at=datetime.now(timezone.utc).isoformat(),
        supabase_configured=is_supabase_configured(),
        trigger=trigger,
    )

    try:
        if not result.supabase_configured:
            logger.warning(
                "sync_league_predictions running WITHOUT Supabase — "
                "predictions/odds/consensus will NOT be persisted to the database"
            )

        logger.info(
            "sync_league_predictions start trigger=%s leagues=%s supabase=%s",
            trigger,
            target,
            result.supabase_configured,
        )

        for league in target:
            league_result = LeagueSyncResult(league=league)
            try:
                events = await odds_client.fetch_league_odds(league)
                for event in events:
                    try:
                        card = await build_match_card(event, league)
                        league_result.matches += 1
                        league_result.predictions += len(card.predictions)
                        # 5 scrapers max; gap = skipped/failed sources
                        league_result.skipped_sources += max(0, 5 - len(card.predictions))

                        record_match_snapshot(card, force=True)
                        persist_info = persist_match_card(card)
                        if persist_info.get("persisted"):
                            league_result.persisted += 1
                        else:
                            league_result.persist_failures += 1
                            reason = persist_info.get("reason", "unknown")
                            # Only treat as hard sync error when Supabase is expected to work.
                            if result.supabase_configured and reason != "supabase_not_configured":
                                msg = (
                                    f"persist failed {event.get('home_team')} vs "
                                    f"{event.get('away_team')}: {reason}"
                                )
                                logger.error(msg)
                                league_result.errors.append(msg)
                    except Exception as exc:  # noqa: BLE001
                        msg = f"{event.get('home_team')} vs {event.get('away_team')}: {exc}"
                        logger.exception("Match sync failed: %s", msg)
                        league_result.errors.append(msg)
            except Exception as exc:  # noqa: BLE001
                logger.exception("League sync failed for %s: %s", league, exc)
                league_result.errors.append(str(exc))

            result.leagues.append(league_result)
            logger.info(
                "Synced %s: matches=%d predictions=%d persisted=%d persist_failures=%d errors=%d",
                league,
                league_result.matches,
                league_result.predictions,
                league_result.persisted,
                league_result.persist_failures,
                len(league_result.errors),
            )

        # Invalidate odds/match caches so next API read picks up fresh scrape path
        cache_clear_prefix("odds:")

        result.finished_at = datetime.now(timezone.utc).isoformat()
        result.ok = all(len(lg.errors) == 0 for lg in result.leagues)
        _last_sync = result
        logger.info(
            "sync_league_predictions finished ok=%s persisted=%s failures=%s",
            result.ok,
            result.to_dict()["totals"]["persisted"],
            result.to_dict()["totals"]["persist_failures"],
        )
        return result
    finally:
        _sync_running = False


async def sync_single_match_card(card: MatchCard) -> dict[str, Any]:
    """Helper used by tests / ad-hoc persistence."""
    return persist_match_card(card)
