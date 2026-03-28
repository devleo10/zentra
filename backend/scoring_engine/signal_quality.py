from __future__ import annotations

from typing import Any, Dict, List, Tuple

from scoring_engine.config_loader import get_scoring_config


def detect_regime(raw_data: Dict[str, Any]) -> Tuple[str, str, Dict[str, float]]:
    cfg = get_scoring_config().get("regime_detection", {})
    vix = _num(raw_data.get("vix", {}).get("current_value"))
    hy_oas = _num(raw_data.get("financial_stress", {}).get("hy_oas"))
    bs_trend = str(raw_data.get("balance_sheet", {}).get("trend", "stable"))
    m2_trend = str(raw_data.get("m2", {}).get("m2_trend", "stable"))
    liquidity_trends = set(cfg.get("liquidity_trends", ["expanding", "slight expansion"]))

    if (vix is not None and vix > float(cfg.get("risk_off_vix_threshold", 25.0))) or (
        hy_oas is not None and hy_oas >= float(cfg.get("risk_off_hy_oas_threshold", 5.0))
    ):
        return "risk_off", f"VIX={vix} HY_OAS={hy_oas} -> risk_off", dict(cfg.get("risk_off_weight_multipliers", {}))
    if bs_trend in liquidity_trends or m2_trend in liquidity_trends:
        return (
            "liquidity_driven",
            f"BalanceSheet={bs_trend} M2={m2_trend} with calm risk backdrop",
            dict(cfg.get("liquidity_driven_weight_multipliers", {})),
        )
    return "neutral", "No elevated risk stress or liquidity impulse detected", dict(cfg.get("neutral_weight_multipliers", {}))


def evaluate_signal_quality(
    raw_data: Dict[str, Any],
    section_scores: Dict[str, int],
    regime: str,
) -> Dict[str, Any]:
    contradictions: List[str] = []
    sanity_flags: List[str] = []
    section_conf = {k: 1.0 for k in section_scores}
    section_weight = {k: 1.0 for k in section_scores}
    additive_adjustment = 0

    nfp = _num(raw_data.get("jobs", {}).get("nfp_change"))
    unemployment_rate = _num(raw_data.get("jobs", {}).get("unemployment_rate"))
    short_trend = str(raw_data.get("jobs", {}).get("unemployment_trend", "stable"))
    cpi_yoy = _num(raw_data.get("cpi", {}).get("yoy_rate"))
    core_cpi = _num(raw_data.get("cpi", {}).get("core_yoy_rate"))
    oil_change = _num(raw_data.get("oil", {}).get("change"))
    breakeven = _num(raw_data.get("breakeven_10y", {}).get("value"))
    economy_score = int(section_scores.get("economy", 50))

    if nfp is not None and nfp < 0 and unemployment_rate is not None and unemployment_rate <= 4.0:
        contradictions.append("Negative NFP conflicts with still-strong unemployment level")
        section_conf["economy"] *= 0.8
        section_weight["economy"] *= 0.85
        additive_adjustment -= 1

    if (
        cpi_yoy is not None and core_cpi is not None and cpi_yoy <= 2.7 and core_cpi <= 2.8
        and ((oil_change is not None and oil_change >= 10.0) or (breakeven is not None and breakeven >= 2.5))
    ):
        contradictions.append("Realized inflation is calm while forward inflation proxies are rising")
        section_conf["inflation"] *= 0.8
        section_weight["inflation"] *= 0.9
        additive_adjustment -= 1

    if economy_score > 60 and nfp is not None and nfp < 0 and short_trend == "rising":
        sanity_flags.append("Economy scoring mismatch: bullish economy despite negative NFP and rising unemployment")
        section_conf["economy"] *= 0.75
        section_weight["economy"] *= 0.85
        additive_adjustment -= 1

    if regime == "risk_off" and economy_score > 60 and short_trend == "rising":
        contradictions.append("Risk-off regime conflicts with highly bullish economy score")
        section_conf["economy"] *= 0.85
        section_weight["economy"] *= 0.9

    return {
        "contradiction_flags": contradictions,
        "sanity_flags": sanity_flags,
        "section_confidence_multipliers": {k: round(v, 3) for k, v in section_conf.items()},
        "section_weight_multipliers": {k: round(v, 3) for k, v in section_weight.items()},
        "additive_adjustment": max(-3, min(0, additive_adjustment)),
        "affected_sections": sorted({k for k, v in section_conf.items() if v != 1.0} | {k for k, v in section_weight.items() if v != 1.0}),
    }


def apply_weight_multipliers(base_weights: Dict[str, float], multipliers: Dict[str, float]) -> Dict[str, float]:
    out = {}
    for key, weight in base_weights.items():
        out[key] = float(weight) * float(multipliers.get(key, 1.0))
    return out


def _num(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
