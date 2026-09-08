"""Bet journal endpoints — slip OCR via OpenAI Vision."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from app.core.config import get_settings
from app.models.schemas import BetJournalRow, ParseSlipRequest
from app.services import journal_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/journal/status")
async def journal_status() -> dict[str, bool]:
    """Report whether slip OCR (OpenAI) and Supabase persistence are ready."""
    from app.services.supabase_store import is_supabase_configured

    return {
        "ocr_ready": bool(get_settings().openai_api_key),
        "supabase_ready": is_supabase_configured(),
    }


def _require_openai() -> None:
    if not get_settings().openai_api_key:
        raise HTTPException(
            status_code=503,
            detail="OPENAI_API_KEY is not configured — slip OCR is unavailable.",
        )


@router.post("/journal/parse-slip", response_model=BetJournalRow)
async def parse_slip(body: ParseSlipRequest) -> BetJournalRow:
    """
    Accept a bet slip screenshot (base64), extract fields via gpt-4o-mini vision,
    persist to Supabase bet_journal with result=pending, and return the saved row.
    """
    _require_openai()
    try:
        parsed = await journal_service.parse_slip_image(body.image_base64)
        row = journal_service.persist_parsed_slip(parsed, body.user_id)
        return BetJournalRow(**row)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("parse-slip failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Slip OCR failed: {exc}") from exc
