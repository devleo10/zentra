"""
Deterministic numeric scoring engine.

ALL scoring is threshold-based or z-score-based.
NO LLM involvement. NO randomness.
All weights and thresholds loaded from config/scoring_weights.json (via get_scoring_config).
"""
from typing import Dict, Any, Tuple, Optional, List

from scoring_engine.config_loader import get_scoring_config


def score_inflation(
    cpi_yoy_rate: Optional[float],
    core_cpi_yoy_rate: Optional[float],
    oil_change: Optional[float],
    breakeven_10y: Optional[float] = None,
) -> Tuple[int, str, Dict[str, Any]]:
    cfg = get_scoring_config()["inflation_thresholds"]

    cpi_score = 50
    if cpi_yoy_rate is not None:
        cpi_score = _threshold_score(
            cpi_yoy_rate,
            [(b["threshold"], b["score"]) for b in cfg.get("cpi_yoy_brackets", [])],
        )

    core_score = cpi_score
    if core_cpi_yoy_rate is not None:
        core_score = _threshold_score(
            core_cpi_yoy_rate,
            [(b["threshold"], b["score"]) for b in cfg.get("core_cpi_yoy_brackets", [])],
        )

    oil_score = cfg["oil_neutral_score"]
    if oil_change is not None:
        if oil_change <= cfg["oil_change_bullish_threshold"]:
            oil_score = cfg["oil_bullish_score"]
        elif oil_change >= cfg["oil_change_bearish_threshold"]:
            oil_score = cfg["oil_bearish_score"]
        else:
            oil_score = cfg["oil_neutral_score"]

    breakeven_score = 50
    if breakeven_10y is not None:
        low_thr = float(cfg.get("breakeven_low_threshold", 2.0))
        hi_thr = float(cfg.get("breakeven_high_threshold", 2.5))
        if breakeven_10y <= low_thr:
            breakeven_score = 80
        elif breakeven_10y < hi_thr:
            breakeven_score = 50
        else:
            breakeven_score = 20

    forward_score = (
        oil_score * float(cfg.get("forward_weight_oil", 0.5)) +
        breakeven_score * float(cfg.get("forward_weight_breakeven", 0.5))
    )
    final = (
        cpi_score * cfg["cpi_weight"] +
        core_score * cfg["core_cpi_weight"] +
        forward_score * cfg["forward_weight"]
    )
    final = int(round(max(0, min(100, final))))

    divergence = bool(
        cpi_yoy_rate is not None
        and core_cpi_yoy_rate is not None
        and cpi_yoy_rate <= float(cfg.get("controlled_cpi_threshold", 2.7))
        and core_cpi_yoy_rate <= float(cfg.get("controlled_core_threshold", 2.8))
        and (
            (oil_change is not None and oil_change >= float(cfg.get("divergence_oil_threshold", 10.0)))
            or (breakeven_10y is not None and breakeven_10y >= float(cfg.get("divergence_breakeven_threshold", 2.5)))
        )
    )
    details = {
        "cpi_score": int(round(cpi_score)),
        "core_cpi_score": int(round(core_score)),
        "forward_inflation_score": int(round(forward_score)),
        "oil_score": int(round(oil_score)),
        "breakeven_score": int(round(breakeven_score)),
        "divergence_flag": divergence,
        "confidence_haircut": float(cfg.get("divergence_confidence_haircut", 0.2)) if divergence else 0.0,
    }

    _cpi_str = f"{cpi_yoy_rate:.2f}%" if cpi_yoy_rate is not None else "N/A"
    _core_str = f"{core_cpi_yoy_rate:.2f}%" if core_cpi_yoy_rate is not None else "N/A"
    _oil_str = f"{oil_change:+.2f}%" if oil_change is not None else "N/A"
    _be_str = f"{breakeven_10y:.2f}%" if breakeven_10y is not None else "N/A"
    reasoning = (
        f"CPI YoY: {_cpi_str} -> {cpi_score} | "
        f"Core CPI YoY: {_core_str} -> {core_score} | "
        f"Forward inflation: oil {_oil_str} -> {oil_score}, breakeven {_be_str} -> {breakeven_score}, blended {forward_score:.0f} | "
        f"Divergence: {'yes' if divergence else 'no'}"
        f"{f' (-{int(details['confidence_haircut'] * 100)}% conf)' if divergence else ''} | "
        f"Weighted: {final}"
    )

    return final, reasoning, details


def score_fed_policy(
    dovish_count: int,
    hawkish_count: int,
    pivot_count: int,
    fed_rate: Optional[float] = None,
    rate_trend: str = "stable",
) -> Tuple[int, str]:
    cfg = get_scoring_config()["fed_policy_thresholds"]

    if dovish_count >= 4 and hawkish_count <= 1:
        score = cfg["dovish_strong"]["score"]
    elif dovish_count >= 2 and hawkish_count <= 1:
        score = cfg["dovish"]["score"]
    elif hawkish_count >= 4 and dovish_count <= 1:
        score = cfg["hawkish_strong"]["score"]
    elif hawkish_count >= 2 and dovish_count <= 1:
        score = cfg["hawkish"]["score"]
    else:
        score = cfg["neutral"]["score"]

    pivot_bonus = min(pivot_count * cfg["pivot_keyword_bonus"], cfg["max_pivot_bonus"])
    score += pivot_bonus

    rate_adj = 0
    rate_note = "n/a"
    if fed_rate is not None:
        if fed_rate <= cfg.get("fed_rate_very_low_threshold", 1.0):
            rate_level_adj = cfg.get("fed_rate_very_low_adj", 20)
            rate_note = f"{fed_rate:.2f}% (ultra-low)"
        elif fed_rate <= cfg.get("fed_rate_low_threshold", 2.5):
            rate_level_adj = cfg.get("fed_rate_low_adj", 10)
            rate_note = f"{fed_rate:.2f}% (low)"
        elif fed_rate <= cfg.get("fed_rate_neutral_threshold", 4.0):
            rate_level_adj = cfg.get("fed_rate_neutral_adj", 0)
            rate_note = f"{fed_rate:.2f}% (neutral)"
        elif fed_rate <= cfg.get("fed_rate_high_threshold", 5.5):
            rate_level_adj = cfg.get("fed_rate_high_adj", -10)
            rate_note = f"{fed_rate:.2f}% (restrictive)"
        else:
            rate_level_adj = cfg.get("fed_rate_very_high_adj", -20)
            rate_note = f"{fed_rate:.2f}% (deeply restrictive)"

        if rate_trend == "falling":
            rate_dir_adj = cfg.get("fed_rate_falling_bonus", 10)
        elif rate_trend == "rising":
            rate_dir_adj = cfg.get("fed_rate_rising_penalty", -10)
        else:
            rate_dir_adj = 0

        rate_adj = max(
            cfg.get("fed_rate_min_total_adj", -25),
            min(cfg.get("fed_rate_max_total_adj", 25), rate_level_adj + rate_dir_adj),
        )
        score += rate_adj

    score = int(round(max(0, min(100, score))))

    reasoning = (
        f"Dovish kw: {dovish_count}, Hawkish kw: {hawkish_count}, Pivot kw: {pivot_count} -> "
        f"pivot_bonus={pivot_bonus} | Rate: {rate_note} trend={rate_trend} -> rate_adj={rate_adj:+d} | "
        f"Final: {score}"
    )

    return score, reasoning


def score_liquidity(
    yield_10y: Optional[float],
    yield_curve_spread: Optional[float],
    balance_sheet_trend: str,
    m2_trend: str = "stable",
    *,
    real_yield_10y: Optional[float] = None,
    m2_yoy_change: Optional[float] = None,
) -> Tuple[int, str]:
    cfg = get_scoring_config()["liquidity_thresholds"]

    yield_score = 50
    if yield_10y is not None:
        yield_score = _threshold_score(yield_10y, [
            (cfg["yield_10y_low"]["threshold"], cfg["yield_10y_low"]["score"]),
            (cfg["yield_10y_moderate"]["threshold"], cfg["yield_10y_moderate"]["score"]),
            (cfg["yield_10y_high"]["threshold"], cfg["yield_10y_high"]["score"]),
            (cfg["yield_10y_very_high"]["threshold"], cfg["yield_10y_very_high"]["score"]),
        ])

    curve_adj = 0
    if yield_curve_spread is not None:
        if yield_curve_spread < 0:
            curve_adj = cfg["yield_curve_inverted_penalty"]
        elif yield_curve_spread > 0.5:
            curve_adj = cfg["yield_curve_steepening_bonus"]

    bs_adj = 0
    if balance_sheet_trend == "expanding":
        bs_adj = cfg["balance_sheet_expanding_bonus"]
    elif balance_sheet_trend == "contracting":
        bs_adj = cfg["balance_sheet_contracting_penalty"]

    m2_adj = 0
    if m2_trend in ("expanding", "slight expansion"):
        m2_adj = cfg.get("m2_expanding_bonus", 10)
    elif m2_trend in ("contracting", "slight contraction"):
        m2_adj = cfg.get("m2_contracting_penalty", -10)

    if m2_yoy_change is not None:
        cap = float(cfg.get("m2_yoy_adj_cap", 6))
        scale = float(cfg.get("m2_yoy_scale", 1.5))
        extra = max(-cap, min(cap, float(m2_yoy_change) * scale))
        m2_adj += int(round(extra))

    real_component = 50.0
    real_note = "n/a"
    if real_yield_10y is not None:
        anchor = float(cfg.get("real_yield_neutral_anchor", 1.0))
        ppm = float(cfg.get("real_yield_points_per_pp", 6))
        cap = float(cfg.get("real_yield_adj_cap", 12))
        delta = (anchor - float(real_yield_10y)) * ppm
        delta = max(-cap, min(cap, delta))
        real_component = 50.0 + delta
        real_note = f"{float(real_yield_10y):.2f}%"

    m2_weight = cfg.get("m2_weight", 0.14)
    ry_w = cfg.get("real_yield_weight", 0.10)
    y_w = cfg.get("yield_10y_weight", 0.32)
    c_w = cfg.get("yield_curve_weight", 0.22)
    b_w = cfg.get("balance_sheet_weight", 0.22)

    wsum = y_w + c_w + b_w + m2_weight + ry_w
    if wsum <= 0:
        wsum = 1.0

    final = (
        yield_score * y_w +
        (50 + curve_adj) * c_w +
        (50 + bs_adj) * b_w +
        (50 + m2_adj) * m2_weight +
        real_component * ry_w
    ) / wsum
    final = int(round(max(0, min(100, final))))

    reasoning = (
        f"10Y: {yield_10y}% -> {yield_score} | "
        f"Curve spread: {yield_curve_spread} -> adj {curve_adj} | "
        f"Balance sheet: {balance_sheet_trend} -> adj {bs_adj} | "
        f"M2: {m2_trend} (yoy_extra) -> adj {m2_adj} | "
        f"Real yield: {real_note} -> component ~{real_component:.0f} | "
        f"Weighted: {final}"
    )

    return final, reasoning


def score_dxy(dxy_change_7d: float, dxy_level: Optional[float] = None) -> Tuple[int, str]:
    cfg = get_scoring_config()["dxy_thresholds"]

    change_score = _threshold_score(dxy_change_7d, [
        (cfg["dxy_falling_fast"]["threshold"], cfg["dxy_falling_fast"]["score"]),
        (cfg["dxy_falling"]["threshold"], cfg["dxy_falling"]["score"]),
        (cfg["dxy_flat"]["threshold"], cfg["dxy_flat"]["score"]),
        (cfg["dxy_rising"]["threshold"], cfg["dxy_rising"]["score"]),
        (cfg["dxy_rising_fast"]["threshold"], cfg["dxy_rising_fast"]["score"]),
    ])

    if dxy_level is None:
        reasoning = f"DXY window change: {dxy_change_7d:+.2f}% -> score {change_score} (no level data)"
        return change_score, reasoning

    level_adj = cfg["dxy_level_very_strong"]["adjustment"]
    level_brackets = [
        (cfg["dxy_level_very_weak"]["threshold"], cfg["dxy_level_very_weak"]["adjustment"]),
        (cfg["dxy_level_weak"]["threshold"], cfg["dxy_level_weak"]["adjustment"]),
        (cfg["dxy_level_neutral_low"]["threshold"], cfg["dxy_level_neutral_low"]["adjustment"]),
        (cfg["dxy_level_neutral"]["threshold"], cfg["dxy_level_neutral"]["adjustment"]),
        (cfg["dxy_level_strong"]["threshold"], cfg["dxy_level_strong"]["adjustment"]),
        (cfg["dxy_level_very_strong"]["threshold"], cfg["dxy_level_very_strong"]["adjustment"]),
    ]
    for threshold, adj in level_brackets:
        if dxy_level <= threshold:
            level_adj = adj
            break

    change_weight = cfg.get("change_weight", 0.6)
    level_weight = cfg.get("level_weight", 0.4)
    level_score = max(0, min(100, 50 + level_adj))
    final = int(round(change_score * change_weight + level_score * level_weight))
    final = max(0, min(100, final))

    reasoning = (
        f"DXY level: {dxy_level:.1f} -> level_adj {level_adj:+d} (level_score={level_score}) | "
        f"Window change: {dxy_change_7d:+.2f}% -> change_score={change_score} | "
        f"Weighted ({change_weight:.0%}/{level_weight:.0%}): {final}"
    )
    return final, reasoning


def score_risk_sentiment(
    vix: Optional[float],
    sp500_change: Optional[float],
    gold_change: Optional[float],
    hy_oas: Optional[float] = None,
) -> Tuple[int, str]:
    cfg = get_scoring_config()["risk_sentiment_thresholds"]

    vix_score = 50
    if vix is not None:
        vix_score = _threshold_score(vix, [
            (cfg["vix_very_low"]["threshold"], cfg["vix_very_low"]["score"]),
            (cfg["vix_low"]["threshold"], cfg["vix_low"]["score"]),
            (cfg["vix_moderate"]["threshold"], cfg["vix_moderate"]["score"]),
            (cfg["vix_high"]["threshold"], cfg["vix_high"]["score"]),
            (cfg["vix_extreme"]["threshold"], cfg["vix_extreme"]["score"]),
        ])

    sp500_adj = 0
    if sp500_change is not None:
        if sp500_change > cfg["sp500_change_threshold"]:
            sp500_adj = cfg["sp500_rising_bonus"]
        elif sp500_change < -cfg["sp500_change_threshold"]:
            sp500_adj = cfg["sp500_falling_penalty"]

    gold_adj = 0
    if gold_change is not None and gold_change > cfg["gold_change_threshold"]:
        vix_hi = float(cfg.get("gold_penalty_vix_elevated_above", 25))
        if vix is not None and vix > vix_hi:
            gold_adj = cfg["gold_safe_haven_penalty"]
        else:
            gold_adj = int(cfg.get("gold_penalty_mild_if_vix_calm", -2))

    hy_score = 50
    if hy_oas is not None:
        hy_score = _threshold_score(hy_oas, [
            (cfg["hy_oas_calm"]["threshold"], cfg["hy_oas_calm"]["score"]),
            (cfg["hy_oas_moderate"]["threshold"], cfg["hy_oas_moderate"]["score"]),
            (cfg["hy_oas_stressed"]["threshold"], cfg["hy_oas_stressed"]["score"]),
            (cfg["hy_oas_extreme"]["threshold"], cfg["hy_oas_extreme"]["score"]),
        ])

    vw = cfg.get("vix_weight", 0.42)
    sw = cfg.get("sp500_weight", 0.26)
    gw = cfg.get("gold_weight", 0.17)
    hw = cfg.get("hy_oas_weight", 0.15)
    wsum = vw + sw + gw + hw
    if wsum <= 0:
        wsum = 1.0

    final = (
        vix_score * vw +
        (50 + sp500_adj) * sw +
        (50 + gold_adj) * gw +
        hy_score * hw
    ) / wsum
    final = int(round(max(0, min(100, final))))

    reasoning = (
        f"VIX: {vix} -> {vix_score} | "
        f"S&P500 window change: {sp500_change}% -> adj {sp500_adj} | "
        f"Gold window change: {gold_change}% -> adj {gold_adj} | "
        f"HY OAS: {hy_oas} -> {hy_score} | "
        f"Weighted: {final}"
    )

    return final, reasoning


def score_economy(
    unemployment_rate: Optional[float],
    unemployment_trend: str = "stable",
    unemployment_trend_3m: str = "stable",
    nfp_change: Optional[float] = None,
    gdp_growth: Optional[float] = None,
    pmi_value: Optional[float] = None,
    regime: str = "neutral",
) -> Tuple[int, str, Dict[str, Any]]:
    cfg = get_scoring_config().get("economy_thresholds", {})

    ur_score = 50
    if unemployment_rate is not None:
        ur_brackets = cfg.get("unemployment_brackets", [
            {"threshold": 3.5, "score": 20},
            {"threshold": 4.0, "score": 35},
            {"threshold": 4.5, "score": 50},
            {"threshold": 5.0, "score": 65},
            {"threshold": 6.0, "score": 80},
            {"threshold": 999, "score": 90},
        ])
        ur_score = _threshold_score(unemployment_rate, [(b["threshold"], b["score"]) for b in ur_brackets])

        short_component = 0.0
        medium_component = 0.0
        if unemployment_trend == "rising":
            short_component = float(cfg.get("unemployment_trend_short_rising_penalty", -15))
        elif unemployment_trend == "falling":
            short_component = float(cfg.get("unemployment_trend_short_falling_bonus", 10))
        if unemployment_trend_3m == "rising":
            medium_component = float(cfg.get("unemployment_trend_medium_rising_penalty", -10))
        elif unemployment_trend_3m == "falling":
            medium_component = float(cfg.get("unemployment_trend_medium_falling_bonus", 5))
        trend_adj = (0.7 * short_component) + (0.3 * medium_component)
        ur_score = max(0, min(100, ur_score + trend_adj))
    else:
        short_component = 0.0
        medium_component = 0.0
        trend_adj = 0.0

    gdp_score = 50
    if gdp_growth is not None:
        gdp_brackets = cfg.get("gdp_brackets", [
            {"threshold": -1.0, "score": 85},
            {"threshold": 0.0, "score": 75},
            {"threshold": 1.0, "score": 60},
            {"threshold": 2.0, "score": 45},
            {"threshold": 3.0, "score": 30},
            {"threshold": 999, "score": 15},
        ])
        gdp_score = _threshold_score(gdp_growth, [(b["threshold"], b["score"]) for b in gdp_brackets])

    pmi_score = 50
    if pmi_value is not None:
        pmi_brackets = cfg.get("pmi_brackets", [
            {"threshold": 45.0, "score": 85},
            {"threshold": 48.0, "score": 70},
            {"threshold": 50.0, "score": 58},
            {"threshold": 52.0, "score": 42},
            {"threshold": 55.0, "score": 28},
            {"threshold": 999, "score": 15},
        ])
        pmi_score = _threshold_score(pmi_value, [(b["threshold"], b["score"]) for b in pmi_brackets])

    nfp_score = 50
    if nfp_change is not None:
        nfp_brackets = cfg.get("nfp_brackets", [
            {"threshold": -200, "score": 90},
            {"threshold": -50, "score": 75},
            {"threshold": 50, "score": 55},
            {"threshold": 200, "score": 35},
            {"threshold": 999, "score": 20},
        ])
        nfp_score = _threshold_score(nfp_change, [(b["threshold"], b["score"]) for b in nfp_brackets])

    regime_adj = 0
    weak_growth = bool(
        (nfp_change is not None and nfp_change < 0) or
        unemployment_trend == "rising" or
        (gdp_growth is not None and gdp_growth < 1.0)
    )
    if regime == "risk_off" and weak_growth:
        regime_adj = int(cfg.get("regime_adjustments", {}).get("risk_off_weak_growth_penalty", -8))
    elif regime == "liquidity_driven" and weak_growth:
        regime_adj = int(cfg.get("regime_adjustments", {}).get("liquidity_driven_weak_growth_relief", 8))

    ur_w = cfg.get("unemployment_weight", 0.28)
    gdp_w = cfg.get("gdp_weight", 0.22)
    pmi_w = cfg.get("pmi_weight", 0.28)
    nfp_w = cfg.get("nfp_weight", 0.22)

    parts: List[Tuple[float, float]] = []
    if unemployment_rate is not None:
        parts.append((ur_score, ur_w))
    if gdp_growth is not None:
        parts.append((gdp_score, gdp_w))
    if pmi_value is not None:
        parts.append((pmi_score, pmi_w))
    if nfp_change is not None:
        parts.append((nfp_score, nfp_w))

    if not parts:
        final = 50
    else:
        tw = sum(w for _, w in parts)
        final = sum(s * w for s, w in parts) / tw

    final = int(round(max(0, min(100, final + regime_adj))))

    ur_str = (
        f"{unemployment_rate:.1f}% (1m={unemployment_trend}, 3m={unemployment_trend_3m})"
        if unemployment_rate is not None
        else "N/A"
    )
    gdp_str = f"{gdp_growth:+.1f}%" if gdp_growth is not None else "N/A"
    pmi_str = f"{pmi_value:.1f}" if pmi_value is not None else "N/A"
    nfp_str = f"{nfp_change:+.0f}k" if nfp_change is not None else "N/A"
    ur_score_str = str(ur_score) if unemployment_rate is not None else "excluded"
    gdp_score_str = str(gdp_score) if gdp_growth is not None else "excluded"
    pmi_score_str = str(pmi_score) if pmi_value is not None else "excluded"
    nfp_score_str = str(nfp_score) if nfp_change is not None else "excluded"
    reasoning = (
        f"Unemployment: {ur_str} -> {ur_score_str} "
        f"[lvl/trend_short/trend_3m={short_component:+.0f}/{medium_component:+.0f}, blend={trend_adj:+.1f}] | "
        f"GDP: {gdp_str} -> {gdp_score_str} | "
        f"PMI: {pmi_str} -> {pmi_score_str} | "
        f"NFP: {nfp_str} -> {nfp_score_str} | "
        f"Regime({regime}) adj: {regime_adj:+d} | "
        f"Weighted: {final}"
    )

    details = {
        "unemployment_level_score": ur_score if unemployment_rate is not None else None,
        "unemployment_short_trend_component": round(short_component, 2),
        "unemployment_medium_trend_component": round(medium_component, 2),
        "unemployment_trend_blend": round(trend_adj, 2),
        "nfp_score": nfp_score if nfp_change is not None else None,
        "gdp_score": gdp_score if gdp_growth is not None else None,
        "pmi_score": pmi_score if pmi_value is not None else None,
        "regime_adjustment": regime_adj,
    }

    return final, reasoning, details


def compute_weighted_total(section_scores: Dict[str, int]) -> Tuple[int, Dict[str, float]]:
    weights = get_scoring_config()["section_weights"]
    breakdown = {}
    total = 0.0
    total_weight = 0.0

    for key, weight in weights.items():
        if key in section_scores:
            contribution = section_scores[key] * weight
            breakdown[key] = round(contribution, 2)
            total += contribution
            total_weight += weight

    if total_weight == 0:
        return 50, breakdown

    final = int(round(total / total_weight))
    final = max(0, min(100, final))
    return final, breakdown


def compute_weighted_total_with_freshness(
    section_scores: Dict[str, int],
    freshness_info: Optional[Dict[str, Any]],
    dynamic_weights: Optional[Dict[str, float]] = None,
) -> Tuple[int, Dict[str, float]]:
    """
    Downweight sections when linked freshness checks are STALE or MISSING.
    """
    cfg = get_scoring_config()
    weights = dict(dynamic_weights or cfg["section_weights"])
    down = cfg.get("stale_section_downweight", {})
    factor = float(down.get("factor", 0.5))
    mapping = down.get("section_freshness_checks", {})

    status_by_name: Dict[str, str] = {}
    if freshness_info:
        for chk in freshness_info.get("checks", []) or []:
            name = chk.get("name") or ""
            status_by_name[name] = str(chk.get("status", "")).upper()

    for section, check_names in mapping.items():
        if section not in section_scores:
            continue
        statuses = [status_by_name.get(cn, "MISSING") for cn in check_names]
        if any(status == "MISSING" for status in statuses):
            weights[section] = 0.0
        elif any(status == "STALE" for status in statuses):
            weights[section] = weights.get(section, 0) * factor

    breakdown = {}
    total = 0.0
    total_weight = 0.0
    for key, weight in weights.items():
        if key in section_scores and weight > 0:
            contribution = section_scores[key] * weight
            breakdown[key] = round(contribution, 2)
            total += contribution
            total_weight += weight

    if total_weight == 0:
        return 50, breakdown

    final = int(round(total / total_weight))
    final = max(0, min(100, final))
    return final, breakdown


def _threshold_score(value: float, brackets: list) -> int:
    for threshold, score in brackets:
        if value <= threshold:
            return score
    return brackets[-1][1]
