from __future__ import annotations

import json
import os
import sys
import time

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from storage import metric_cache


def _patch_cache_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(metric_cache, "_CACHE_DIR", tmp_path)
    monkeypatch.setattr(metric_cache, "_CACHE_FILE", tmp_path / "metrics.json")


def test_metric_cache_round_trip(tmp_path, monkeypatch):
    _patch_cache_paths(tmp_path, monkeypatch)

    payload = {"latest_value": 3.2, "trend": "rising"}
    metric_cache.put_cached_metric("cpi", "month", payload)

    out = metric_cache.get_cached_metric("cpi", "month", max_age_seconds=300)
    assert out is not None
    assert out["latest_value"] == 3.2
    assert out["trend"] == "rising"


def test_metric_cache_respects_expiry(tmp_path, monkeypatch):
    _patch_cache_paths(tmp_path, monkeypatch)

    metric_cache.put_cached_metric("pce", "month", {"latest_value": 2.1})

    path = tmp_path / "metrics.json"
    store = json.loads(path.read_text(encoding="utf-8"))
    store["month:pce"]["saved_at_epoch"] = time.time() - 999
    path.write_text(json.dumps(store), encoding="utf-8")

    out = metric_cache.get_cached_metric("pce", "month", max_age_seconds=60)
    assert out is None


def test_metric_cache_clear_by_timeframe(tmp_path, monkeypatch):
    _patch_cache_paths(tmp_path, monkeypatch)

    metric_cache.put_cached_metric("cpi", "month", {"latest_value": 3.2})
    metric_cache.put_cached_metric("cpi", "week", {"latest_value": 3.1})

    metric_cache.clear_cached_metric(timeframe="month")

    month_out = metric_cache.get_cached_metric("cpi", "month", max_age_seconds=300)
    week_out = metric_cache.get_cached_metric("cpi", "week", max_age_seconds=300)
    assert month_out is None
    assert week_out is not None
