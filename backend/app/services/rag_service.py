"""
Query-side RAG helpers over `bet_journal_vectors` (see migration 004).

This module covers embedding a query and retrieving similar past bets via
the `match_bet_journal_vectors` Supabase RPC. The write side — embedding
every newly-settled bet and upserting it — is a separate background job
(Phase 1 item 3, tracked as a follow-up; see PROJECT_OVERVIEW notes) and
intentionally isn't in this file.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import get_settings
from app.services.supabase_store import get_supabase_client

logger = logging.getLogger(__name__)


def get_openai_client():
    """Return an AsyncOpenAI client, or None if no API key is configured."""
    key = get_settings().openai_api_key
    if not key:
        return None
    try:
        from openai import AsyncOpenAI

        return AsyncOpenAI(api_key=key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to init OpenAI client: %s", exc)
        return None


async def embed_text(text: str) -> list[float] | None:
    """Embed `text` with text-embedding-3-small. Returns None if unavailable."""
    client = get_openai_client()
    if client is None:
        logger.warning("OPENAI_API_KEY not set — cannot embed text")
        return None
    try:
        resp = await client.embeddings.create(
            model=get_settings().openai_embedding_model,
            input=text,
            dimensions=get_settings().openai_embedding_dims,
        )
        return resp.data[0].embedding
    except Exception as exc:  # noqa: BLE001
        logger.warning("OpenAI embedding call failed: %s", exc)
        return None


async def search_past_bet_mistakes(
    query: str,
    user_id: str,
    match_count: int = 5,
    min_similarity: float = 0.0,
) -> list[dict[str, Any]]:
    """
    Semantic search over the user's settled-bet memory.

    Returns [] (never raises) when OpenAI/Supabase aren't configured, or on
    any lookup failure — callers (the chat tool) should treat that as "no
    memory available yet" rather than an error.
    """
    embedding = await embed_text(query)
    if embedding is None:
        return []

    client = get_supabase_client()
    if client is None:
        logger.warning("Supabase not configured — cannot search bet memory")
        return []

    try:
        resp = client.rpc(
            "match_bet_journal_vectors",
            {
                "query_embedding": embedding,
                "match_user_id": user_id,
                "match_count": match_count,
                "min_similarity": min_similarity,
            },
        ).execute()
        return list(resp.data or [])
    except Exception as exc:  # noqa: BLE001
        logger.warning("match_bet_journal_vectors RPC failed: %s", exc)
        return []
