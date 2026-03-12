"""
Simple in-memory TTL cache for data fetchers.

Prevents back-to-back analysis runs from hitting external APIs twice and
receiving different data, which is the primary cause of score instability.

Default TTL is 30 minutes — long enough to stabilise consecutive runs,
short enough to pick up genuine market moves for the next scheduled run.
"""
import time
import logging
from typing import Any, Optional

logger = logging.getLogger("btc_macro.cache")

DEFAULT_TTL_SECONDS = 30 * 60  # 30 minutes

_store: dict[str, tuple[float, Any]] = {}


def get(key: str) -> Optional[Any]:
    """Return cached value if it exists and hasn't expired, else None."""
    entry = _store.get(key)
    if entry is None:
        return None
    expires_at, value = entry
    if time.time() > expires_at:
        del _store[key]
        logger.debug("Cache MISS (expired): %s", key)
        return None
    logger.debug("Cache HIT: %s", key)
    return value


def put(key: str, value: Any, ttl: int = DEFAULT_TTL_SECONDS) -> None:
    """Store a value with the given TTL (seconds)."""
    _store[key] = (time.time() + ttl, value)


def invalidate(key: str) -> None:
    """Remove a single key."""
    _store.pop(key, None)


def clear() -> None:
    """Flush the entire cache (useful between test runs)."""
    _store.clear()
    logger.info("Cache cleared")
