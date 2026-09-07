"""APScheduler background jobs for scraper pipelines."""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import settings

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler | None:
    return _scheduler


async def _run_scheduled_sync() -> None:
    from app.services.sync_service import sync_league_predictions

    try:
        result = await sync_league_predictions(trigger="scheduler")
        totals = result.to_dict()["totals"]
        logger.info(
            "Scheduled sync complete: matches=%s persisted=%s persist_failures=%s ok=%s",
            totals["matches"],
            totals["persisted"],
            totals["persist_failures"],
            result.ok,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Scheduled sync_league_predictions crashed")


async def _run_scheduled_bet_memory_embed() -> None:
    from app.services.embedding_service import backfill_bet_memory

    try:
        result = await backfill_bet_memory(trigger="scheduler")
        logger.info(
            "Scheduled bet-memory embed complete: candidates=%d embedded=%d ok=%s",
            result.candidates,
            result.embedded,
            result.ok,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Scheduled backfill_bet_memory crashed")


def start_scheduler() -> AsyncIOScheduler | None:
    """Start the 30-minute sync_league_predictions job."""
    global _scheduler

    if not settings.scheduler_enabled:
        logger.info("Scheduler disabled (SCHEDULER_ENABLED=false)")
        return None

    if _scheduler is not None and _scheduler.running:
        return _scheduler

    _scheduler = AsyncIOScheduler(timezone="UTC")
    _scheduler.add_job(
        _run_scheduled_sync,
        trigger=IntervalTrigger(minutes=settings.sync_interval_minutes),
        id="sync_league_predictions",
        name="sync_league_predictions",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=120,
    )
    _scheduler.add_job(
        _run_scheduled_bet_memory_embed,
        trigger=IntervalTrigger(minutes=settings.bet_memory_embed_interval_minutes),
        id="backfill_bet_memory",
        name="backfill_bet_memory",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=120,
    )

    _scheduler.start()
    logger.info(
        "APScheduler started — sync_league_predictions every %d minutes, "
        "backfill_bet_memory every %d minutes",
        settings.sync_interval_minutes,
        settings.bet_memory_embed_interval_minutes,
    )

    if settings.sync_on_startup:
        _scheduler.add_job(
            _run_scheduled_sync,
            id="sync_league_predictions_startup",
            name="sync_league_predictions_startup",
            replace_existing=True,
        )

    return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("APScheduler stopped")
    _scheduler = None
