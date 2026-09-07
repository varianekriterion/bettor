"""
Phase 1 background job: embed every newly-settled bet into
`bet_journal_vectors` (migration 004) — the AI's long-term memory.

For each settled `bet_journal` row without a memory row yet, this pulls the
match, every tipster's prediction on it, and the user's logged
outcome/EV/Kelly, builds one plain-text summary + structured metadata, and
upserts an OpenAI embedding of it via `rag_service.embed_text`. The
query-side counterpart (`search_past_bet_mistakes`) lives in
`rag_service.py` / `chat_tools.py`.

Same dataclass-result + module-level last-run/running-guard shape as
`sync_service.py`, so `core/scheduler.py` and `api/routes/admin.py` can
follow the exact same pattern as the existing scraper sync job.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.services.rag_service import embed_text
from app.services.supabase_store import get_supabase_client, is_supabase_configured

logger = logging.getLogger(__name__)

SETTLED_RESULTS = ("win", "loss", "push")


@dataclass
class EmbedRunResult:
    started_at: str
    finished_at: str | None = None
    trigger: str = "scheduler"
    candidates: int = 0
    embedded: int = 0
    skipped_no_embedding: int = 0
    errors: list[str] = field(default_factory=list)
    ok: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_last_run: EmbedRunResult | None = None
_running = False


def get_last_embed_run() -> EmbedRunResult | None:
    return _last_run


def is_embed_running() -> bool:
    return _running


def _already_embedded_bet_ids(client: Any, bet_ids: list[str]) -> set[str]:
    if not bet_ids:
        return set()
    try:
        resp = client.table("bet_journal_vectors").select("bet_id").in_("bet_id", bet_ids).execute()
        return {row["bet_id"] for row in (resp.data or [])}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to check existing bet_journal_vectors: %s", exc)
        return set()


def _fetch_settled_bets(client: Any, limit: int) -> list[dict[str, Any]]:
    try:
        resp = (
            client.table("bet_journal")
            .select("*")
            .in_("result", list(SETTLED_RESULTS))
            .order("placed_at", desc=True)
            .limit(limit)
            .execute()
        )
        return list(resp.data or [])
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to fetch settled bets: %s", exc)
        return []


def _fetch_match(client: Any, match_id: str | None) -> dict[str, Any] | None:
    if not match_id:
        return None
    try:
        resp = client.table("matches").select("*").eq("id", match_id).limit(1).execute()
        rows = resp.data or []
        return rows[0] if rows else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to fetch match %s: %s", match_id, exc)
        return None


def _fetch_predictions(client: Any, match_id: str | None) -> list[dict[str, Any]]:
    if not match_id:
        return []
    try:
        resp = (
            client.table("predictions")
            .select("*")
            .eq("match_id", match_id)
            .order("scraped_at", desc=True)
            .execute()
        )
        return list(resp.data or [])
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to fetch predictions for %s: %s", match_id, exc)
        return []


def _build_memory_text(
    bet: dict[str, Any],
    match: dict[str, Any] | None,
    preds: list[dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    """Build the embedded summary text + structured metadata for one settled bet."""
    label = bet.get("match_label") or (
        f"{match['home_team']} vs {match['away_team']}" if match else "Unknown fixture"
    )
    league = match.get("league_key") if match else "unknown"

    tipster_lines = [
        f"{p['source']} picked {p['pick']} "
        f"(H {p['home_prob']:.0%} / D {p['draw_prob']:.0%} / A {p['away_prob']:.0%})"
        for p in preds
    ]
    tipster_summary = "; ".join(tipster_lines) if tipster_lines else "no tipster predictions on record"

    ev_pct = float(bet.get("ev_pct") or 0.0)
    kelly_pct = float(bet.get("kelly_pct") or 0.0)
    consensus_prob = float(bet.get("consensus_prob") or 0.0)
    stake = float(bet.get("stake") or 0.0)
    odds = float(bet.get("odds") or 0.0)
    outcome = bet.get("outcome")
    result = bet.get("result")
    profit = bet.get("profit")

    # A "mistake" in the process sense (bet had no real edge when logged,
    # regardless of how it turned out) vs. the outcome sense (it lost).
    # Both are useful, different signals for the chat agent to retrieve on.
    process_mistake = ev_pct <= 0
    outcome_mistake = result == "loss"

    content = (
        f"{label} ({league}). Tipsters: {tipster_summary}. "
        f"Our consensus gave {outcome} a {consensus_prob:.0%} probability "
        f"({ev_pct:+.1f}% EV, {kelly_pct:.1f}% Kelly stake). "
        f"User bet {stake:g} on {outcome} @ {odds:.2f}. "
        f"Result: {result}" + (f" (profit {float(profit):+.2f})." if profit is not None else ".")
        + (" This was a negative-EV bet regardless of outcome." if process_mistake else "")
    )

    metadata = {
        "outcome": outcome,
        "odds": odds,
        "stake": stake,
        "consensus_prob": consensus_prob,
        "ev_pct": ev_pct,
        "kelly_pct": kelly_pct,
        "result": result,
        "profit": profit,
        "process_mistake": process_mistake,
        "outcome_mistake": outcome_mistake,
        "tipster_sources": [p["source"] for p in preds],
    }
    return content, metadata


async def embed_settled_bet(client: Any, bet: dict[str, Any]) -> bool:
    """Embed + upsert a single settled bet into bet_journal_vectors. Returns True on success."""
    match = _fetch_match(client, bet.get("match_id"))
    preds = _fetch_predictions(client, bet.get("match_id"))
    content, metadata = _build_memory_text(bet, match, preds)

    embedding = await embed_text(content)
    if embedding is None:
        return False

    top_source = preds[0]["source"] if preds else None
    row = {
        "bet_id": bet["id"],
        "match_id": bet.get("match_id"),
        "user_id": bet["user_id"],
        "source": top_source,
        "content": content,
        "metadata": metadata,
        "embedding": embedding,
    }
    client.table("bet_journal_vectors").upsert(row, on_conflict="bet_id").execute()
    return True


async def backfill_bet_memory(limit: int | None = None, *, trigger: str = "scheduler") -> EmbedRunResult:
    """
    Embed every settled `bet_journal` row that doesn't have a
    `bet_journal_vectors` row yet, up to `limit` per run (defaults to
    `settings.bet_memory_batch_size`) so OpenAI cost/latency per tick is
    bounded — a backlog drains over several scheduler cycles rather than in
    one big burst.
    """
    global _last_run, _running

    from app.core.config import settings

    limit = limit or settings.bet_memory_batch_size
    result = EmbedRunResult(started_at=datetime.now(timezone.utc).isoformat(), trigger=trigger)

    if _running:
        logger.info("Bet-memory embed already running — skipping trigger=%s", trigger)
        result.ok = False
        result.errors.append("already_running")
        return result

    if not is_supabase_configured():
        result.ok = False
        result.errors.append("supabase_not_configured")
        result.finished_at = datetime.now(timezone.utc).isoformat()
        _last_run = result
        return result

    client = get_supabase_client()
    if client is None:
        result.ok = False
        result.errors.append("supabase_client_init_failed")
        result.finished_at = datetime.now(timezone.utc).isoformat()
        _last_run = result
        return result

    _running = True
    try:
        # Over-fetch: many recent settled bets may already be embedded.
        settled = _fetch_settled_bets(client, limit=limit * 3)
        already = _already_embedded_bet_ids(client, [b["id"] for b in settled])
        pending = [b for b in settled if b["id"] not in already][:limit]
        result.candidates = len(pending)

        for bet in pending:
            try:
                ok = await embed_settled_bet(client, bet)
                if ok:
                    result.embedded += 1
                else:
                    result.skipped_no_embedding += 1
            except Exception as exc:  # noqa: BLE001 — one bad row shouldn't abort the batch
                logger.exception("Failed to embed bet %s: %s", bet.get("id"), exc)
                result.errors.append(f"{bet.get('id')}: {exc}")

        result.ok = len(result.errors) == 0
        result.finished_at = datetime.now(timezone.utc).isoformat()
        _last_run = result
        logger.info(
            "backfill_bet_memory finished trigger=%s candidates=%d embedded=%d skipped=%d errors=%d",
            trigger,
            result.candidates,
            result.embedded,
            result.skipped_no_embedding,
            len(result.errors),
        )
        return result
    finally:
        _running = False
