"""Supabase persistence for matches, predictions, and consensus runs."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from app.core.config import settings
from app.models.schemas import MatchCard

logger = logging.getLogger(__name__)


@lru_cache
def get_supabase_client():
    """Return a service-role Supabase client, or None if not configured."""
    if not settings.supabase_url or not settings.supabase_service_key:
        return None
    try:
        from supabase import create_client

        return create_client(settings.supabase_url, settings.supabase_service_key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to init Supabase client: %s", exc)
        return None


def is_supabase_configured() -> bool:
    return bool(settings.supabase_url and settings.supabase_service_key)


def _insert_odds_snapshot(client: Any, row: dict[str, Any], *, market: str) -> None:
    """Insert an odds snapshot; tolerate pre-migration schemas for totals/h2h."""
    try:
        client.table("odds_snapshots").insert(row).execute()
    except Exception as exc:  # noqa: BLE001
        if market == "h2h" and "market_type" in row:
            legacy = {k: v for k, v in row.items() if k != "market_type"}
            logger.warning(
                "odds_snapshots h2h insert with market_type failed (%s) — retrying legacy columns",
                exc,
            )
            client.table("odds_snapshots").insert(legacy).execute()
            return
        if market == "totals":
            logger.warning(
                "Skipping totals odds snapshot (apply migration 002): %s",
                exc,
            )
            return
        raise


def persist_match_card(card: MatchCard) -> dict[str, Any]:
    """
    Upsert match + insert odds_snapshots, predictions, and consensus_runs.

    Called by APScheduler / admin sync for every fixture. Uses the service-role
    key so RLS on market tables does not block background writes.
    Logs and returns persisted=False when Supabase is not configured.
    """
    client = get_supabase_client()
    if client is None:
        logger.warning(
            "Supabase not configured — skipping persist for match %s "
            "(set SUPABASE_URL + SUPABASE_SERVICE_KEY)",
            card.id,
        )
        return {"persisted": False, "reason": "supabase_not_configured", "match_id": card.id}

    odds_written = 0
    preds_written = 0
    try:
        now_iso = datetime.now(timezone.utc).isoformat()
        client.table("matches").upsert(
            {
                "id": card.id,
                "league_key": card.league,
                "home_team": card.home_team,
                "away_team": card.away_team,
                "commence_time": card.commence_time.isoformat(),
                "status": "scheduled",
                "updated_at": now_iso,
            }
        ).execute()

        for book in card.odds.bookmakers:
            captured = book.last_update.isoformat() if book.last_update is not None else None
            h2h_row: dict[str, Any] = {
                "match_id": card.id,
                "bookmaker": book.bookmaker,
                "market_type": "h2h",
                "home_odds": book.home,
                "draw_odds": book.draw,
                "away_odds": book.away,
            }
            if captured:
                h2h_row["captured_at"] = captured
            _insert_odds_snapshot(client, h2h_row, market="h2h")
            odds_written += 1

            if book.totals is not None:
                totals_row: dict[str, Any] = {
                    "match_id": card.id,
                    "bookmaker": book.bookmaker,
                    "market_type": "totals",
                    "line": book.totals.line,
                    "over_odds": book.totals.over,
                    "under_odds": book.totals.under,
                }
                if captured:
                    totals_row["captured_at"] = captured
                _insert_odds_snapshot(client, totals_row, market="totals")
                odds_written += 1

        for pred in card.predictions:
            client.table("predictions").insert(
                {
                    "match_id": card.id,
                    "source": pred.source,
                    "home_prob": pred.home_prob,
                    "draw_prob": pred.draw_prob,
                    "away_prob": pred.away_prob,
                    "pick": pred.pick,
                    "scraped_at": (pred.scraped_at or card.commence_time).isoformat(),
                }
            ).execute()
            preds_written += 1

        client.table("consensus_runs").insert(
            {
                "match_id": card.id,
                "home_prob": card.consensus.home,
                "draw_prob": card.consensus.draw,
                "away_prob": card.consensus.away,
                "pick": card.consensus.pick,
                "confidence": card.consensus.confidence,
                "source_weights": card.consensus.source_weights,
                "best_outcome": card.best_edge.outcome,
                "best_odds": card.best_edge.odds,
                "ev_pct": card.best_edge.ev_pct,
                "kelly_pct": card.best_edge.kelly_pct,
            }
        ).execute()

        logger.info(
            "Persisted match %s → odds_snapshots=%d predictions=%d consensus_runs=1",
            card.id,
            odds_written,
            preds_written,
        )
        return {
            "persisted": True,
            "match_id": card.id,
            "predictions": preds_written,
            "odds_snapshots": odds_written,
            "consensus_runs": 1,
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception("Supabase persist failed for %s: %s", card.id, exc)
        return {
            "persisted": False,
            "reason": str(exc),
            "match_id": card.id,
            "predictions": preds_written,
            "odds_snapshots": odds_written,
        }


def fetch_odds_snapshots(match_id: str, limit: int = 500) -> list[dict[str, Any]]:
    """Return odds snapshots for a match ordered oldest→newest."""
    client = get_supabase_client()
    if client is None:
        return []
    try:
        resp = (
            client.table("odds_snapshots")
            .select("*")
            .eq("match_id", match_id)
            .order("captured_at", desc=False)
            .limit(limit)
            .execute()
        )
        return list(resp.data or [])
    except Exception as exc:  # noqa: BLE001
        logger.warning("fetch_odds_snapshots failed for %s: %s", match_id, exc)
        return []


def fetch_consensus_runs(match_id: str, limit: int = 500) -> list[dict[str, Any]]:
    """Return consensus runs for a match ordered oldest→newest."""
    client = get_supabase_client()
    if client is None:
        return []
    try:
        resp = (
            client.table("consensus_runs")
            .select("*")
            .eq("match_id", match_id)
            .order("created_at", desc=False)
            .limit(limit)
            .execute()
        )
        return list(resp.data or [])
    except Exception as exc:  # noqa: BLE001
        logger.warning("fetch_consensus_runs failed for %s: %s", match_id, exc)
        return []
