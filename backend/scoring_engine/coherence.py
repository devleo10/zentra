"""
Deterministic cross-signal coherence adjustments (before headline / LLM layers).
"""
from __future__ import annotations

from typing import Any, Dict, Tuple

from scoring_engine.config_loader import get_scoring_config


def compute_coherence_adjustment(
    section_scores: Dict[str, int],
    raw_data: Dict[str, Any],
) -> Tuple[int, str]:
    """
    Returns (adjustment, reasoning). Adjustment is applied to weighted numeric score
    (after stale downweight), clamped to [-max_adjustment, +max_adjustment].
    """
    cfg = get_scoring_config().get("coherence_rules", {})
    max_adj = int(cfg.get("max_adjustment", 8))
    adj = 0
    parts = []

    vix = raw_data.get("vix", {}).get("current_value")
    try:
        vix_f = float(vix) if vix is not None else None
    except (TypeError, ValueError):
        vix_f = None

    rs = int(section_scores.get("risk_sentiment", 50))
    vix_thr = float(cfg.get("vix_extreme_threshold", 30))
    rs_cap = int(cfg.get("vix_risk_score_cap", 38))

    if vix_f is not None and vix_f > vix_thr and rs > rs_cap:
        delta = min(max_adj, max(1, (rs - rs_cap + 2) // 3))
        adj -= delta
        parts.append(f"VIX>{vix_thr:g} with risk_sentiment={rs} (cap {rs_cap}) -> {-delta}")

    inf = int(section_scores.get("inflation", 50))
    fed = int(section_scores.get("fed_policy", 50))
    div_thr = int(cfg.get("inflation_fed_divergence_threshold", 50))
    div_pen = int(cfg.get("inflation_fed_divergence_penalty", 5))
    if abs(inf - fed) > div_thr:
        rem = max_adj - abs(adj)
        if rem > 0:
            p = min(div_pen, rem)
            adj -= p
            parts.append(f"|inflation-fed|>{div_thr} -> {-p}")

    adj = max(-max_adj, min(max_adj, adj))
    return adj, "; ".join(parts) if parts else "none"
