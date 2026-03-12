"""
Final verdict computation.

Combines numeric score + headline adjustment into a deterministic verdict.
All thresholds from config. Zero randomness.
"""
import json
from pathlib import Path
from typing import Dict, Any, Tuple, List


def _load_config() -> Dict:
    config_path = Path(__file__).parent.parent / "config" / "scoring_weights.json"
    with open(config_path, "r") as f:
        return json.load(f)


CONFIG = _load_config()


def compute_final_verdict(
    weighted_numeric_score: int,
    headline_adjustment: int,
    section_scores: Dict[str, int],
    headline_confidence: float,
    cross_signal_adjustment: int = 0,
    data_freshness_info: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    Compute final verdict deterministically.
    
    final_score = weighted_numeric_score + headline_adjustment + cross_signal_adjustment
    
    Args:
        weighted_numeric_score: 0-100 from numeric engine
        headline_adjustment: -10 to +10 from headline engine
        section_scores: Dict of section key -> score (for agreement calc)
        headline_confidence: Average confidence from headline classification (0-1)
        cross_signal_adjustment: -5 to +5 from LLM cross-signal review
    
    Returns:
        Dict with: final_score, bias, action, confidence, confidence_pct, reasoning
    """
    cfg_bias = CONFIG["bias_thresholds"]
    cfg_conf = CONFIG["confidence_formula"]
    
    # 1. Final score
    final_score = max(0, min(100, weighted_numeric_score + headline_adjustment + cross_signal_adjustment))
    
    # 2. Bias classification (7 granular thresholds)
    if final_score >= cfg_bias["strong_bull"]["min"]:
        bias = "Strong Bull"
        action = "Aggressive BTC accumulation"
    elif final_score >= cfg_bias["bullish"]["min"]:
        bias = "Bullish"
        action = "Hold + add on dips"
    elif final_score >= cfg_bias["cautiously_bullish"]["min"]:
        bias = "Cautiously Bullish"
        action = "Small longs, tight stops"
    elif final_score >= cfg_bias["neutral_upside"]["min"]:
        bias = "Neutral (Upside Bias)"
        action = "Watch for breakout, hold core"
    elif final_score >= cfg_bias["neutral_downside"]["min"]:
        bias = "Neutral (Downside Bias)"
        action = "Reduce exposure, await clarity"
    elif final_score >= cfg_bias["bearish"]["min"]:
        bias = "Bearish"
        action = "Capital protection"
    else:
        bias = "High Risk"
        action = "Stay out / hedge"
    
    # 3. Confidence calculation (deterministic)
    scores = list(section_scores.values())
    
    # 3a. Section agreement: what % of sections agree on direction?
    if scores:
        bullish_count = sum(1 for s in scores if s > 60)
        bearish_count = sum(1 for s in scores if s < 40)
        max_aligned = max(bullish_count, bearish_count)
        agreement_pct = (max_aligned / len(scores)) * 100
    else:
        agreement_pct = 50.0
    
    # 3b. Distance from 50 (higher distance = more conviction)
    distance = abs(final_score - 50)
    max_distance = cfg_conf["max_distance_score"]
    distance_score = min(100, (distance / max_distance) * 100)
    
    # 3c. Headline confidence (0-1 scaled to 0-100)
    headline_conf_score = headline_confidence * 100
    
    # Weighted confidence (base)
    confidence_pct = (
        agreement_pct * cfg_conf["section_agreement_weight"] +
        distance_score * cfg_conf["distance_weight"] +
        headline_conf_score * cfg_conf["headline_confidence_weight"]
    )

    # 3d. Freshness adjustment (penalty-only)
    freshness_score = _compute_freshness_score(data_freshness_info)
    freshness_penalty = _freshness_penalty_from_score(freshness_score)
    confidence_pct -= freshness_penalty
    confidence_pct = round(max(0, min(100, confidence_pct)), 1)
    
    # Confidence label
    if confidence_pct >= 75:
        confidence_label = "High"
    elif confidence_pct >= 50:
        confidence_label = "Medium"
    else:
        confidence_label = "Low"
    
    cross_part = f" + CrossSignal: {cross_signal_adjustment:+d}" if cross_signal_adjustment else ""
    reasoning = (
        f"Numeric: {weighted_numeric_score} + Headlines: {headline_adjustment:+d}"
        f"{cross_part} = {final_score}. "
        f"Bias: {bias}. "
        f"Confidence: {confidence_pct}% ({confidence_label}) "
        f"[agreement={agreement_pct:.0f}%, distance={distance_score:.0f}%, "
        f"headline_conf={headline_conf_score:.0f}%, freshness={freshness_score:.0f}%, "
        f"freshness_penalty={freshness_penalty:.0f}]"
    )
    
    return {
        "final_score": final_score,
        "bias": bias,
        "action": action,
        "confidence_pct": confidence_pct,
        "confidence_label": confidence_label,
        "reasoning": reasoning,
        "components": {
            "weighted_numeric_score": weighted_numeric_score,
            "headline_adjustment": headline_adjustment,
            "cross_signal_adjustment": cross_signal_adjustment,
            "agreement_pct": round(agreement_pct, 1),
            "distance_score": round(distance_score, 1),
            "headline_conf_score": round(headline_conf_score, 1),
            "freshness_score": round(freshness_score, 1),
            "freshness_penalty": round(freshness_penalty, 1),
        }
    }


def _compute_freshness_score(data_freshness_info: Dict[str, Any] | None) -> float:
    """Convert freshness checks into a 0-100 score."""
    if not data_freshness_info:
        return 50.0

    checks = data_freshness_info.get("checks", [])
    if not checks:
        return 50.0

    weighted_sum = 0.0
    weight_total = 0.0
    for chk in checks:
        status = (chk.get("status") or "").upper()
        is_critical = bool(chk.get("is_critical", False))
        weight = 2.0 if is_critical else 1.0
        if status == "FRESH":
            score = 100.0
        elif status == "STALE":
            score = 45.0
        else:  # MISSING / unknown
            score = 0.0
        weighted_sum += score * weight
        weight_total += weight

    return (weighted_sum / weight_total) if weight_total else 50.0


def _freshness_penalty_from_score(freshness_score: float) -> float:
    """Penalty bands to reduce overconfident outputs on stale data."""
    if freshness_score < 40:
        return 20.0
    if freshness_score < 60:
        return 12.0
    if freshness_score < 75:
        return 6.0
    return 0.0
