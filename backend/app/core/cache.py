"""In-memory TTL cache for scraped predictions and odds."""

from __future__ import annotations

from typing import Any

from cachetools import TTLCache

from app.core.config import settings

_cache: TTLCache[str, Any] | None = None
# Survives TTL expiry — used when live fetches fail or return empty.
_last_good: dict[str, Any] = {}


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
    if not _is_cacheable(value):
        return
    get_cache()[key] = value
    _last_good[key] = value


def cache_get_nonempty(key: str) -> Any | None:
    """Like cache_get but ignores cached empty lists."""
    value = cache_get(key)
    if isinstance(value, list) and len(value) == 0:
        return None
    return value


def cache_get_last_good(key: str) -> Any | None:
    """Return the most recent non-empty snapshot even if TTL cache expired."""
    return _last_good.get(key)


def _is_cacheable(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, list) and len(value) == 0:
        return False
    return True


def cache_clear_prefix(prefix: str) -> int:
    """Remove all cache keys starting with prefix. Returns count removed."""
    cache = get_cache()
    keys = [k for k in list(cache.keys()) if str(k).startswith(prefix)]
    for key in keys:
        cache.pop(key, None)
    return len(keys)
