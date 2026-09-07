"""In-memory TTL cache for scraped predictions and odds."""

from __future__ import annotations

from typing import Any

from cachetools import TTLCache

from app.core.config import settings

_cache: TTLCache[str, Any] | None = None


def init_cache() -> None:
    global _cache
    _cache = TTLCache(maxsize=512, ttl=settings.cache_ttl_seconds)


def get_cache() -> TTLCache[str, Any]:
    if _cache is None:
        init_cache()
    assert _cache is not None
    return _cache


def cache_get(key: str) -> Any | None:
    return get_cache().get(key)


def cache_set(key: str, value: Any) -> None:
    get_cache()[key] = value


def cache_clear_prefix(prefix: str) -> int:
    """Remove all cache keys starting with prefix. Returns count removed."""
    cache = get_cache()
    keys = [k for k in list(cache.keys()) if str(k).startswith(prefix)]
    for key in keys:
        cache.pop(key, None)
    return len(keys)
