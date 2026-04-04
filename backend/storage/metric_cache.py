"""Persistent disk-backed cache for metric payloads.

This cache is used to reduce repeated fetches for low-frequency monthly metrics
without changing the API response format.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("btc_macro.storage.metric_cache")

_CACHE_DIR = Path(__file__).parent.parent / "storage" / "metric_cache"
_CACHE_FILE = _CACHE_DIR / "metrics.json"
_LOCK = threading.Lock()


def _cache_key(metric_key: str, timeframe: str) -> str:
    return f"{timeframe}:{metric_key}"


def _read_store_unlocked() -> Dict[str, Any]:
    if not _CACHE_FILE.exists():
        return {}
    try:
        parsed = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        if isinstance(parsed, dict):
            return parsed
    except Exception as e:
        logger.warning("Metric cache read failed; treating as empty: %s", e)
    return {}


def _write_store_unlocked(store: Dict[str, Any]) -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _CACHE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(store, ensure_ascii=True, separators=(",", ":")), encoding="utf-8")
    tmp.replace(_CACHE_FILE)


def get_cached_metric(metric_key: str, timeframe: str, *, max_age_seconds: int) -> Optional[Dict[str, Any]]:
    """Return cached payload if available and not older than max_age_seconds."""
    if max_age_seconds <= 0:
        return None
    key = _cache_key(metric_key, timeframe)
    now = time.time()
    with _LOCK:
        store = _read_store_unlocked()
        row = store.get(key)
        if not isinstance(row, dict):
            return None

        saved_at = row.get("saved_at_epoch")
        payload = row.get("payload")
        if not isinstance(saved_at, (int, float)) or not isinstance(payload, dict):
            return None

        age = now - float(saved_at)
        if age < 0:
            age = 0
        if age > max_age_seconds:
            return None

        return dict(payload)


def put_cached_metric(metric_key: str, timeframe: str, payload: Dict[str, Any]) -> None:
    """Write/replace a metric payload in the persistent cache."""
    if not isinstance(payload, dict):
        return
    key = _cache_key(metric_key, timeframe)
    with _LOCK:
        store = _read_store_unlocked()
        store[key] = {
            "saved_at_epoch": time.time(),
            "metric_key": metric_key,
            "timeframe": timeframe,
            "payload": payload,
        }
        _write_store_unlocked(store)


def clear_cached_metric(*, metric_key: Optional[str] = None, timeframe: Optional[str] = None) -> None:
    """Clear cache entries by key/timeframe filter, or all entries when filters are omitted."""
    with _LOCK:
        store = _read_store_unlocked()
        if not store:
            return

        if metric_key is None and timeframe is None:
            store = {}
        else:
            keys_to_remove = []
            for key, row in store.items():
                if not isinstance(row, dict):
                    keys_to_remove.append(key)
                    continue
                row_metric = row.get("metric_key")
                row_timeframe = row.get("timeframe")
                metric_match = metric_key is None or row_metric == metric_key
                timeframe_match = timeframe is None or row_timeframe == timeframe
                if metric_match and timeframe_match:
                    keys_to_remove.append(key)
            for key in keys_to_remove:
                store.pop(key, None)

        _write_store_unlocked(store)
