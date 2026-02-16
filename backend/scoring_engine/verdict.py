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
    headline_confidence: float
) -> Dict[str, Any]:
    """
    Compute final verdict deterministically.
    
    final_score = weighted_numeric_score + headline_adjustment
    
    Bias:
        >= 80 → Strong Bull
        >= 65 → Bullish
        >= 40 → Neutral
        >= 20 → Bearish
        <  20 → High Risk
    
    Confidence:
        Based on:
        - Section score agreement (40%)
        - Distance of final_score from 50 (35%)
        - Headline classification confidence (25%)
    
    Args:
        weighted_numeric_score: 0-100 from numeric engine
        headline_adjustment: -10 to +10 from headline engine
        section_scores: Dict of section key → score (for agreement calc)
        headline_confidence: Average confidence from headline classification (0-1)
    
    Returns:
        Dict with: final_score, bias, action, confidence, confidence_pct, reasoning
    """
    cfg_bias = CONFIG["bias_thresholds"]
    cfg_conf = CONFIG["confidence_formula"]
    
    # 1. Final score
    final_score = max(0, min(100, weighted_numeric_score + headline_adjustment))
    
    # 2. Bias classification
    if final_score >= cfg_bias["strong_bull"]["min"]:
        bias = "Strong Bull"
        action = "Aggressive BTC accumulation"
    elif final_score >= cfg_bias["bullish"]["min"]:
        bias = "Bullish"
        action = "Hold + add on dips"
    elif final_score >= cfg_bias["neutral"]["min"]:
        bias = "Neutral"
        action = "Small positions only"
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
    
    # Weighted confidence
    confidence_pct = (
        agreement_pct * cfg_conf["section_agreement_weight"] +
        distance_score * cfg_conf["distance_weight"] +
        headline_conf_score * cfg_conf["headline_confidence_weight"]
    )
    confidence_pct = round(max(0, min(100, confidence_pct)), 1)
    
    # Confidence label
    if confidence_pct >= 75:
        confidence_label = "High"
    elif confidence_pct >= 50:
        confidence_label = "Medium"
    else:
        confidence_label = "Low"
    
    reasoning = (
        f"Numeric: {weighted_numeric_score} + Headlines: {headline_adjustment:+d} = {final_score}. "
        f"Bias: {bias}. "
        f"Confidence: {confidence_pct}% ({confidence_label}) "
        f"[agreement={agreement_pct:.0f}%, distance={distance_score:.0f}%, headline_conf={headline_conf_score:.0f}%]"
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
            "agreement_pct": round(agreement_pct, 1),
            "distance_score": round(distance_score, 1),
            "headline_conf_score": round(headline_conf_score, 1),
        }
    }
