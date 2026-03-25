"""Reload scoring_weights.json when the file mtime changes."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "scoring_weights.json"
_mtime: float = 0.0
_cache: Dict[str, Any] = {}


def get_scoring_config() -> Dict[str, Any]:
    global _mtime, _cache
    m = _CONFIG_PATH.stat().st_mtime
    if m != _mtime or not _cache:
        _cache = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        _mtime = m
    return _cache
