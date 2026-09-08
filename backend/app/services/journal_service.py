"""Bet slip vision OCR and journal persistence."""

from __future__ import annotations

import difflib
import json
import logging
import re
from typing import Any

from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.services.rag_service import get_openai_client
from app.services.supabase_store import get_supabase_client, is_supabase_configured

logger = logging.getLogger(__name__)

_PICK_MAP = {
    "HOME": "home",
    "DRAW": "draw",
    "AWAY": "away",
    "H": "home",
    "D": "draw",
    "A": "away",
    "1": "home",
    "X": "draw",
    "2": "away",
}

_SYSTEM_PROMPT = """You are a sports betting slip OCR assistant. Inspect the bet slip screenshot and return structured JSON with exactly these fields:
- match: string (e.g. "Arsenal vs Chelsea")
- pick: one of HOME, DRAW, AWAY (the selection on the slip for 1X2 / match result markets)
- market: string (e.g. "1X2", "Match Result", "Moneyline")
- odds: number (decimal odds, e.g. 1.85)
- stake: number (currency amount wagered, e.g. 50.0)
- bookmaker: string or null (e.g. "Bet365")
- notes: short string (e.g. "Extracted via OCR")

Use null for unreadable string fields. Use 0 for unreadable numeric fields. Return JSON only."""


class ParsedSlipFields(BaseModel):
    match: str | None = None
    pick: str | None = None
    market: str | None = None
    odds: float = Field(default=0, ge=0)
    stake: float = Field(default=0, ge=0)
    bookmaker: str | None = None
    notes: str | None = None


def _normalize_image_url(image_base64: str) -> str:
    trimmed = image_base64.strip()
    if trimmed.startswith("data:"):
        return trimmed
    return f"data:image/png;base64,{trimmed}"


def _normalize_pick(pick: str | None) -> str:
    if not pick:
        return "home"
    return _PICK_MAP.get(pick.strip().upper(), "home")


def _strip_bookmaker_suffix(label: str) -> str:
    return re.sub(r"\s*\([^)]*\)\s*$", "", label).strip()


def _split_match_teams(match_label: str) -> tuple[str, str] | None:
    cleaned = _strip_bookmaker_suffix(match_label)
    parts = re.split(r"\s+vs\.?\s+|\s+v\s+|\s+-\s+", cleaned, maxsplit=1, flags=re.IGNORECASE)
    if len(parts) != 2:
        return None
    home, away = parts[0].strip(), parts[1].strip()
    if not home or not away:
        return None
    return home, away


def _resolve_match_id(match_label: str) -> str | None:
    """Best-effort link OCR match text to a row in public.matches."""
    teams = _split_match_teams(match_label)
    if teams is None:
        return None
    home_q, away_q = teams
    client = get_supabase_client()
    if client is None:
        return None
    try:
        resp = (
            client.table("matches")
            .select("id,home_team,away_team")
            .order("commence_time", desc=True)
            .limit(200)
            .execute()
        )
        rows = list(resp.data or [])
    except Exception as exc:  # noqa: BLE001
        logger.debug("match lookup failed: %s", exc)
        return None

    best_id: str | None = None
    best_score = 0.0
    for row in rows:
        home = str(row.get("home_team", ""))
        away = str(row.get("away_team", ""))
        home_score = difflib.SequenceMatcher(None, home_q.lower(), home.lower()).ratio()
        away_score = difflib.SequenceMatcher(None, away_q.lower(), away.lower()).ratio()
        direct = (home_score + away_score) / 2
        flipped = (
            difflib.SequenceMatcher(None, home_q.lower(), away.lower()).ratio()
            + difflib.SequenceMatcher(None, away_q.lower(), home.lower()).ratio()
        ) / 2
        score = max(direct, flipped * 0.95)
        if score > best_score:
            best_score = score
            best_id = row.get("id")
    return best_id if best_score >= 0.55 else None


async def parse_slip_image(image_base64: str) -> ParsedSlipFields:
    """Run gpt-4o-mini vision OCR on a bet slip screenshot."""
    client = get_openai_client()
    if client is None:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    image_url = _normalize_image_url(image_base64)
    response = await client.chat.completions.create(
        model=get_settings().openai_chat_model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Extract bet slip fields as JSON."},
                    {"type": "image_url", "image_url": {"url": image_url, "detail": "low"}},
                ],
            },
        ],
        response_format={"type": "json_object"},
        temperature=0,
        max_tokens=500,
    )
    raw = response.choices[0].message.content or "{}"
    data = json.loads(raw)
    parsed = ParsedSlipFields.model_validate(data)
    logger.info(
        "OCR parsed slip: match=%s pick=%s odds=%s stake=%s",
        parsed.match,
        parsed.pick,
        parsed.odds,
        parsed.stake,
    )
    return parsed


def persist_parsed_slip(parsed: ParsedSlipFields | dict[str, Any], user_id: str) -> dict[str, Any]:
    """Insert OCR-parsed bet into Supabase bet_journal with status pending."""
    if not is_supabase_configured():
        raise RuntimeError("Supabase is not configured (SUPABASE_URL + SUPABASE_SERVICE_KEY)")

    client = get_supabase_client()
    if client is None:
        raise RuntimeError("Failed to initialize Supabase client")

    fields = parsed if isinstance(parsed, ParsedSlipFields) else ParsedSlipFields.model_validate(parsed)

    outcome = _normalize_pick(fields.pick)
    odds = float(fields.odds or 0)
    stake = float(fields.stake or 0)
    if odds <= 1.0:
        odds = 2.0
    if stake <= 0:
        stake = 10.0

    match_label = (fields.match or "Unknown match").strip()
    if fields.bookmaker:
        match_label = f"{match_label} ({fields.bookmaker})"

    notes = (fields.notes or "Extracted via OCR").strip()
    if notes and notes not in match_label:
        match_label = f"{match_label} — {notes}"

    match_id = _resolve_match_id(fields.match or match_label)

    payload: dict[str, Any] = {
        "user_id": user_id,
        "match_id": match_id,
        "match_label": match_label,
        "outcome": outcome,
        "odds": round(odds, 3),
        "stake": round(stake, 2),
        "units": round(stake, 2),
        "consensus_prob": 0.0,
        "ev_pct": 0.0,
        "kelly_pct": 0.0,
        "result": "pending",
    }

    resp = client.table("bet_journal").insert(payload).select("*").single().execute()
    row = resp.data
    if not row:
        raise RuntimeError("Supabase insert returned no row")
    row["ocr_applied"] = True
    row["ocr_market"] = fields.market
    row["ocr_bookmaker"] = fields.bookmaker
    return row
