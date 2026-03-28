"""
Final verdict computation.

Combines numeric score + headline adjustment into a deterministic verdict.
All thresholds from config. Zero randomness.
"""
from typing import Dict, Any

from scoring_engine.config_loader import get_scoring_config


def compute_final_verdict(
    weighted_numeric_score: int,
    headline_adjustment: int,
    section_scores: Dict[str, int],
    headline_confidence: float,
    cross_signal_adjustment: int = 0,
    data_freshness_info: Dict[str, Any] | None = None,
    contradiction_flags: list[str] | None = None,
    sanity_flags: list[str] | None = None,
    downweighted_sections_count: int = 0,
) -> Dict[str, Any]:
    cfg = get_scoring_config()
    cfg_bias = cfg["bias_thresholds"]
    cfg_conf = cfg["confidence_formula"]
    contradiction_flags = contradiction_flags or []
    sanity_flags = sanity_flags or []

    final_score = max(0, min(100, weighted_numeric_score + headline_adjustment + cross_signal_adjustment))

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

    scores = list(section_scores.values())
    if scores:
        bullish_count = sum(1 for s in scores if s > 60)
        bearish_count = sum(1 for s in scores if s < 40)
        max_aligned = max(bullish_count, bearish_count)
        agreement_pct = (max_aligned / len(scores)) * 100
    else:
        agreement_pct = 50.0

    headline_conf_score = headline_confidence * 100
    freshness_score = _compute_freshness_score(data_freshness_info)
    data_quality_score = _compute_data_quality_score(data_freshness_info)
    model_stability_score = _compute_model_stability_score(
        contradiction_flags,
        sanity_flags,
        downweighted_sections_count,
    )

    confidence_pct = (
        freshness_score * cfg_conf.get("freshness_weight", 0.30) +
        agreement_pct * cfg_conf.get("section_agreement_weight", 0.25) +
        data_quality_score * cfg_conf.get("data_quality_weight", 0.20) +
        headline_conf_score * cfg_conf.get("headline_confidence_weight", 0.15) +
        model_stability_score * cfg_conf.get("model_stability_weight", 0.10)
    )

    freshness_penalty = _freshness_penalty_from_score(freshness_score)
    confidence_pct -= freshness_penalty
    dq_penalty = _data_quality_stale_penalty(cfg, data_freshness_info)
    confidence_pct -= dq_penalty
    critical_metric_penalty = _critical_metric_penalty(cfg_conf, data_freshness_info)
    confidence_pct -= critical_metric_penalty
    contradiction_multiplier = 1.0
    if contradiction_flags:
        contradiction_multiplier = float(cfg_conf.get("contradiction_multiplier", 0.8))
        confidence_pct *= contradiction_multiplier
    confidence_pct = round(max(0, min(100, confidence_pct)), 1)

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
        f"[freshness={freshness_score:.0f}%, agreement={agreement_pct:.0f}%, data_quality={data_quality_score:.0f}%, "
        f"headline_conf={headline_conf_score:.0f}%, model_stability={model_stability_score:.0f}%, "
        f"freshness_penalty={freshness_penalty:.0f}, dq_penalty={dq_penalty:.0f}, critical_penalty={critical_metric_penalty:.0f}, "
        f"contradiction_multiplier={contradiction_multiplier:.2f}]"
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
            "data_quality_score": round(data_quality_score, 1),
            "headline_conf_score": round(headline_conf_score, 1),
            "freshness_score": round(freshness_score, 1),
            "model_stability_score": round(model_stability_score, 1),
            "freshness_penalty": round(freshness_penalty, 1),
            "data_quality_stale_penalty": round(dq_penalty, 1),
            "critical_metric_penalty": round(critical_metric_penalty, 1),
            "contradiction_multiplier": round(contradiction_multiplier, 2),
        }
    }


def _compute_freshness_score(data_freshness_info: Dict[str, Any] | None) -> float:
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
        else:
            score = 0.0
        weighted_sum += score * weight
        weight_total += weight
    return (weighted_sum / weight_total) if weight_total else 50.0


def _compute_data_quality_score(data_freshness_info: Dict[str, Any] | None) -> float:
    if not data_freshness_info:
        return 50.0
    dq = data_freshness_info.get("data_quality") or {}
    try:
        return float(dq.get("score", 50.0))
    except (TypeError, ValueError):
        return 50.0


def _freshness_penalty_from_score(freshness_score: float) -> float:
    if freshness_score < 40:
        return 20.0
    if freshness_score < 60:
        return 12.0
    if freshness_score < 75:
        return 6.0
    return 0.0


def _data_quality_stale_penalty(cfg: Dict[str, Any], data_freshness_info: Dict[str, Any] | None) -> float:
    dq_cfg = cfg.get("data_quality_confidence") or {}
    if not data_freshness_info:
        return 0.0
    dq = data_freshness_info.get("data_quality") or {}
    try:
        sr = float(dq.get("stale_ratio") or 0.0)
    except (TypeError, ValueError):
        sr = 0.0
    hard_thr = float(dq_cfg.get("stale_ratio_hard", 0.5))
    soft_thr = float(dq_cfg.get("stale_ratio_soft", 0.35))
    hard_pen = float(dq_cfg.get("penalty_hard", 15.0))
    soft_pen = float(dq_cfg.get("penalty_soft", 8.0))
    if sr >= hard_thr:
        return hard_pen
    if sr >= soft_thr:
        return soft_pen
    return 0.0


def _critical_metric_penalty(cfg_conf: Dict[str, Any], data_freshness_info: Dict[str, Any] | None) -> float:
    if not data_freshness_info:
        return 0.0
    penalties = cfg_conf.get("critical_metric_penalties") or {}
    checks = data_freshness_info.get("checks") or []
    total = 0.0
    for chk in checks:
        if chk.get("status") == "MISSING":
            total += float(penalties.get(chk.get("name"), 0.0) or 0.0)
    return total


def _compute_model_stability_score(
    contradiction_flags: list[str],
    sanity_flags: list[str],
    downweighted_sections_count: int,
) -> float:
    score = 100.0
    score -= len(contradiction_flags) * 20.0
    score -= len(sanity_flags) * 15.0
    score -= max(0, downweighted_sections_count) * 5.0
    return max(0.0, min(100.0, score))
