"""
Shared hawkish/dovish keyword config and word-boundary matching.

Single source of truth: backend/config/hawkish_dovish_keywords.json
Used by headline_engine.classifier, data_fetchers.news_data, and run_analysis.
"""
import re
import json
from pathlib import Path
from typing import Dict, List

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "hawkish_dovish_keywords.json"


def _load_keywords() -> Dict[str, List[str]]:
    with open(_CONFIG_PATH, "r") as f:
        return json.load(f)


def get_keyword_lists() -> Dict[str, List[str]]:
    """Return { 'hawkish': [...], 'dovish': [...] } from config."""
    return _load_keywords()


def get_matched_keywords(text: str) -> Dict[str, List[str]]:
    """
    Match hawkish/dovish phrases in text using word boundaries.
    Returns { 'hawkish': [matched phrases], 'dovish': [matched phrases] }.
    """
    if not text or not text.strip():
        return {"hawkish": [], "dovish": []}
    raw = _load_keywords()
    normalized = (text or "").lower().strip()
    out: Dict[str, List[str]] = {"hawkish": [], "dovish": []}
    for key in ("hawkish", "dovish"):
        for phrase in raw.get(key, []):
            # Word-boundary regex: \b escapes the phrase so special chars are safe
            pattern = r"\b" + re.escape(phrase.lower()) + r"\b"
            if re.search(pattern, normalized):
                out[key].append(phrase)
    return out
