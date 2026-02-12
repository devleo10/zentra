"""
Deterministic headline adjustment engine.

Takes classified headline events and computes a bounded score adjustment.
The adjustment is CAPPED (max ±10) and CANNOT override the numeric engine.
"""
import json
from pathlib import Path
from typing import List, Dict, Any, Tuple


def _load_config() -> Dict:
    config_path = Path(__file__).parent.parent / "config" / "scoring_weights.json"
    with open(config_path, "r") as f:
        return json.load(f)


CONFIG = _load_config()


def compute_headline_adjustment(classified_headlines: List[Dict[str, Any]]) -> Tuple[int, str]:
    """
    Compute a deterministic score adjustment from classified headlines.
    
    Each headline is a dict with:
        - event_bias: "hawkish" | "dovish" | "neutral"
        - risk_impact: "risk_on" | "risk_off" | "neutral"
        - confidence: float 0.0-1.0
        - reason: str
    
    Rules (from config):
        dovish + risk_on  → +7  (scaled by confidence)
        dovish + neutral  → +4
        dovish + risk_off → +0
        hawkish + risk_off → -7
        hawkish + neutral  → -4
        hawkish + risk_on  → +0
        neutral → 0
    
    Final adjustment is average of per-headline adjustments, capped at ±10.
    Headlines with confidence < min_confidence_to_apply are ignored.
    
    Args:
        classified_headlines: List of classification dicts from LLM
    
    Returns:
        (adjustment integer, reasoning string)
    """
    cfg = CONFIG["headline_adjustment"]
    min_conf = cfg["min_confidence_to_apply"]
    max_pos = cfg["max_positive_adjustment"]
    max_neg = cfg["max_negative_adjustment"]
    use_scaling = cfg.get("confidence_scaling", True)
    
    adjustments = []
    reasons = []
    
    for h in classified_headlines:
        conf = h.get("confidence", 0)
        if conf < min_conf:
            reasons.append(f"[SKIPPED conf={conf:.2f}] {h.get('reason', 'n/a')}")
            continue
        
        bias = h.get("event_bias", "neutral")
        impact = h.get("risk_impact", "neutral")
        
        # Determine raw adjustment from lookup table
        raw_adj = _lookup_adjustment(bias, impact, cfg)
        
        # Scale by confidence if enabled
        if use_scaling:
            raw_adj = raw_adj * conf
        
        adjustments.append(raw_adj)
        reasons.append(f"[{bias}/{impact} conf={conf:.2f}] adj={raw_adj:+.1f}: {h.get('reason', '')}")
    
    if not adjustments:
        return 0, "No qualifying headlines (all below confidence threshold or none provided)"
    
    # Average then cap
    avg_adj = sum(adjustments) / len(adjustments)
    capped = int(round(max(max_neg, min(max_pos, avg_adj))))
    
    reasoning = (
        f"Headlines analyzed: {len(classified_headlines)}, "
        f"qualified: {len(adjustments)}, "
        f"avg_raw: {avg_adj:+.2f}, "
        f"capped: {capped:+d} (bounds [{max_neg}, +{max_pos}]). "
        f"Details: {'; '.join(reasons[:3])}"  # Top 3 for brevity
    )
    
    return capped, reasoning


def _lookup_adjustment(bias: str, impact: str, cfg: Dict) -> float:
    """Deterministic lookup for base adjustment."""
    if bias == "dovish":
        if impact == "risk_on":
            return cfg["dovish_risk_on"]
        elif impact == "risk_off":
            return cfg["dovish_risk_off"]
        else:
            return cfg["dovish_neutral"]
    elif bias == "hawkish":
        if impact == "risk_off":
            return cfg["hawkish_risk_off"]
        elif impact == "risk_on":
            return cfg["hawkish_risk_on"]
        else:
            return cfg["hawkish_neutral"]
    else:
        return cfg["neutral_adjustment"]
