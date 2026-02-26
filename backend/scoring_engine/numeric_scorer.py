"""
Deterministic numeric scoring engine.

ALL scoring is threshold-based or z-score-based.
NO LLM involvement. NO randomness.
All weights and thresholds loaded from config/scoring_weights.json.
"""
import json
from pathlib import Path
from typing import Dict, Any, Tuple, Optional


def _load_config() -> Dict:
    config_path = Path(__file__).parent.parent / "config" / "scoring_weights.json"
    with open(config_path, "r") as f:
        return json.load(f)


CONFIG = _load_config()


def score_inflation(cpi_mom_change: float, pce_mom_change: Optional[float], oil_change: Optional[float]) -> Tuple[int, str]:
    """
    Score inflation section deterministically.
    
    Args:
        cpi_mom_change: CPI month-over-month percentage change
        pce_mom_change: PCE month-over-month percentage change (optional)
        oil_change: Oil price percentage change over comparison period (optional)
    
    Returns:
        (score 0-100, reasoning string)
    """
    cfg = CONFIG["inflation_thresholds"]
    
    # Guard: treat None as 0 (neutral)
    if cpi_mom_change is None:
        cpi_mom_change = 0.0
    
    # Score CPI
    cpi_score = _threshold_score(cpi_mom_change, [
        (cfg["cpi_mom_falling_fast"]["threshold"], cfg["cpi_mom_falling_fast"]["score"]),
        (cfg["cpi_mom_falling"]["threshold"],      cfg["cpi_mom_falling"]["score"]),
        (cfg["cpi_mom_flat"]["threshold"],          cfg["cpi_mom_flat"]["score"]),
        (cfg["cpi_mom_rising"]["threshold"],        cfg["cpi_mom_rising"]["score"]),
        (cfg["cpi_mom_rising_fast"]["threshold"],   cfg["cpi_mom_rising_fast"]["score"]),
    ])
    
    # Score PCE (same brackets as CPI if available)
    pce_score = cpi_score  # default to CPI if missing
    if pce_mom_change is not None:
        pce_score = _threshold_score(pce_mom_change, [
            (cfg["cpi_mom_falling_fast"]["threshold"], cfg["cpi_mom_falling_fast"]["score"]),
            (cfg["cpi_mom_falling"]["threshold"],      cfg["cpi_mom_falling"]["score"]),
            (cfg["cpi_mom_flat"]["threshold"],          cfg["cpi_mom_flat"]["score"]),
            (cfg["cpi_mom_rising"]["threshold"],        cfg["cpi_mom_rising"]["score"]),
            (cfg["cpi_mom_rising_fast"]["threshold"],   cfg["cpi_mom_rising_fast"]["score"]),
        ])
    
    # Score Oil
    oil_score = cfg["oil_neutral_score"]  # default
    if oil_change is not None:
        if oil_change <= cfg["oil_change_bullish_threshold"]:
            oil_score = cfg["oil_bullish_score"]
        elif oil_change >= cfg["oil_change_bearish_threshold"]:
            oil_score = cfg["oil_bearish_score"]
        else:
            oil_score = cfg["oil_neutral_score"]
    
    # Weighted combination
    final = (
        cpi_score * cfg["cpi_weight"] +
        pce_score * cfg["pce_weight"] +
        oil_score * cfg["oil_weight"]
    )
    final = int(round(max(0, min(100, final))))
    
    _cpi_str = f"{cpi_mom_change:+.2f}%" if cpi_mom_change is not None else "N/A"
    _pce_str = f"{pce_mom_change:+.2f}%" if pce_mom_change is not None else "N/A"
    _oil_str = f"{oil_change:+.2f}%" if oil_change is not None else "N/A"
    reasoning = (
        f"CPI MoM: {_cpi_str} -> score {cpi_score} | "
        f"PCE MoM: {_pce_str} -> score {pce_score} | "
        f"Oil Δ: {_oil_str} -> score {oil_score} | "
        f"Weighted: {final}"
    )
    
    return final, reasoning


def score_fed_policy(dovish_count: int, hawkish_count: int, pivot_count: int) -> Tuple[int, str]:
    """
    Score Fed policy section deterministically from keyword counts.
    
    Args:
        dovish_count: Number of dovish keywords found in headlines
        hawkish_count: Number of hawkish keywords found in headlines
        pivot_count: Number of pivot keywords found
    
    Returns:
        (score 0-100, reasoning string)
    """
    cfg = CONFIG["fed_policy_thresholds"]
    
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
    
    # Pivot bonus (capped)
    pivot_bonus = min(pivot_count * cfg["pivot_keyword_bonus"], cfg["max_pivot_bonus"])
    score = int(round(max(0, min(100, score + pivot_bonus))))
    
    reasoning = (
        f"Dovish kw: {dovish_count}, Hawkish kw: {hawkish_count}, Pivot kw: {pivot_count} -> "
        f"base + pivot_bonus({pivot_bonus}) = {score}"
    )
    
    return score, reasoning


def score_liquidity(
    yield_10y: Optional[float],
    yield_curve_spread: Optional[float],
    balance_sheet_trend: str
) -> Tuple[int, str]:
    """
    Score liquidity section deterministically.
    
    Args:
        yield_10y: Current 10-year Treasury yield (percentage)
        yield_curve_spread: 10Y - 2Y spread (percentage points)
        balance_sheet_trend: "expanding", "contracting", or "stable"
    
    Returns:
        (score 0-100, reasoning string)
    """
    cfg = CONFIG["liquidity_thresholds"]
    
    # Score 10Y yield
    yield_score = 50  # default
    if yield_10y is not None:
        yield_score = _threshold_score(yield_10y, [
            (cfg["yield_10y_low"]["threshold"],       cfg["yield_10y_low"]["score"]),
            (cfg["yield_10y_moderate"]["threshold"],   cfg["yield_10y_moderate"]["score"]),
            (cfg["yield_10y_high"]["threshold"],       cfg["yield_10y_high"]["score"]),
            (cfg["yield_10y_very_high"]["threshold"],  cfg["yield_10y_very_high"]["score"]),
        ])
    
    # Yield curve adjustment
    curve_adj = 0
    if yield_curve_spread is not None:
        if yield_curve_spread < 0:
            curve_adj = cfg["yield_curve_inverted_penalty"]
        elif yield_curve_spread > 0.5:
            curve_adj = cfg["yield_curve_steepening_bonus"]
    
    # Balance sheet adjustment
    bs_adj = 0
    if balance_sheet_trend == "expanding":
        bs_adj = cfg["balance_sheet_expanding_bonus"]
    elif balance_sheet_trend == "contracting":
        bs_adj = cfg["balance_sheet_contracting_penalty"]
    
    # Weighted combination
    final = (
        yield_score * cfg["yield_10y_weight"] +
        (50 + curve_adj) * cfg["yield_curve_weight"] +
        (50 + bs_adj) * cfg["balance_sheet_weight"]
    )
    final = int(round(max(0, min(100, final))))
    
    reasoning = (
        f"10Y: {yield_10y}% -> {yield_score} | "
        f"Curve spread: {yield_curve_spread} -> adj {curve_adj} | "
        f"Balance sheet: {balance_sheet_trend} -> adj {bs_adj} | "
        f"Weighted: {final}"
    )
    
    return final, reasoning


def score_dxy(dxy_change_7d: float, dxy_level: Optional[float] = None) -> Tuple[int, str]:
    """
    Score DXY section deterministically using both momentum and absolute level.

    Args:
        dxy_change_7d: DXY percentage change over comparison period
        dxy_level: Current DXY absolute value (e.g. 104.2). If None, only change is used.

    Returns:
        (score 0-100, reasoning string)
    """
    cfg = CONFIG["dxy_thresholds"]

    # Momentum score from 7-day change
    change_score = _threshold_score(dxy_change_7d, [
        (cfg["dxy_falling_fast"]["threshold"],  cfg["dxy_falling_fast"]["score"]),
        (cfg["dxy_falling"]["threshold"],        cfg["dxy_falling"]["score"]),
        (cfg["dxy_flat"]["threshold"],            cfg["dxy_flat"]["score"]),
        (cfg["dxy_rising"]["threshold"],          cfg["dxy_rising"]["score"]),
        (cfg["dxy_rising_fast"]["threshold"],     cfg["dxy_rising_fast"]["score"]),
    ])

    if dxy_level is None:
        reasoning = f"DXY 7D change: {dxy_change_7d:+.2f}% -> score {change_score} (no level data)"
        return change_score, reasoning

    # Level adjustment: higher DXY = stronger dollar = worse for BTC
    level_adj = cfg["dxy_level_very_strong"]["adjustment"]  # default: very strong
    level_brackets = [
        (cfg["dxy_level_very_weak"]["threshold"],   cfg["dxy_level_very_weak"]["adjustment"]),
        (cfg["dxy_level_weak"]["threshold"],         cfg["dxy_level_weak"]["adjustment"]),
        (cfg["dxy_level_neutral_low"]["threshold"],  cfg["dxy_level_neutral_low"]["adjustment"]),
        (cfg["dxy_level_neutral"]["threshold"],      cfg["dxy_level_neutral"]["adjustment"]),
        (cfg["dxy_level_strong"]["threshold"],       cfg["dxy_level_strong"]["adjustment"]),
        (cfg["dxy_level_very_strong"]["threshold"],  cfg["dxy_level_very_strong"]["adjustment"]),
    ]
    for threshold, adj in level_brackets:
        if dxy_level <= threshold:
            level_adj = adj
            break

    # Weighted blend of change score and level-adjusted score
    change_weight = cfg.get("change_weight", 0.6)
    level_weight = cfg.get("level_weight", 0.4)
    level_score = max(0, min(100, 50 + level_adj))
    final = int(round(change_score * change_weight + level_score * level_weight))
    final = max(0, min(100, final))

    reasoning = (
        f"DXY level: {dxy_level:.1f} -> level_adj {level_adj:+d} (level_score={level_score}) | "
        f"7D change: {dxy_change_7d:+.2f}% -> change_score={change_score} | "
        f"Weighted ({change_weight:.0%}/{level_weight:.0%}): {final}"
    )
    return final, reasoning


def score_risk_sentiment(
    vix: Optional[float],
    sp500_change: Optional[float],
    gold_change: Optional[float]
) -> Tuple[int, str]:
    """
    Score risk sentiment section deterministically.
    
    Args:
        vix: Current VIX value
        sp500_change: S&P 500 percentage change over comparison period
        gold_change: Gold percentage change over comparison period
    
    Returns:
        (score 0-100, reasoning string)
    """
    cfg = CONFIG["risk_sentiment_thresholds"]
    
    # VIX score
    vix_score = 50  # default
    if vix is not None:
        vix_score = _threshold_score(vix, [
            (cfg["vix_very_low"]["threshold"],  cfg["vix_very_low"]["score"]),
            (cfg["vix_low"]["threshold"],        cfg["vix_low"]["score"]),
            (cfg["vix_moderate"]["threshold"],    cfg["vix_moderate"]["score"]),
            (cfg["vix_high"]["threshold"],        cfg["vix_high"]["score"]),
            (cfg["vix_extreme"]["threshold"],     cfg["vix_extreme"]["score"]),
        ])
    
    # S&P 500 adjustment
    sp500_adj = 0
    if sp500_change is not None:
        if sp500_change > cfg["sp500_change_threshold"]:
            sp500_adj = cfg["sp500_rising_bonus"]
        elif sp500_change < -cfg["sp500_change_threshold"]:
            sp500_adj = cfg["sp500_falling_penalty"]
    
    # Gold safe-haven adjustment
    gold_adj = 0
    if gold_change is not None:
        if gold_change > cfg["gold_change_threshold"]:
            gold_adj = cfg["gold_safe_haven_penalty"]
    
    # Weighted
    final = (
        vix_score * cfg["vix_weight"] +
        (50 + sp500_adj) * cfg["sp500_weight"] +
        (50 + gold_adj) * cfg["gold_weight"]
    )
    final = int(round(max(0, min(100, final))))
    
    reasoning = (
        f"VIX: {vix} -> {vix_score} | "
        f"S&P500 Δ: {sp500_change}% -> adj {sp500_adj} | "
        f"Gold Δ: {gold_change}% -> adj {gold_adj} | "
        f"Weighted: {final}"
    )
    
    return final, reasoning


def compute_weighted_total(section_scores: Dict[str, int]) -> Tuple[int, Dict[str, float]]:
    """
    Compute the final weighted numeric score.
    
    Args:
        section_scores: Dict mapping section key to its 0-100 score.
            Keys: "inflation", "fed_policy", "liquidity", "dxy", "risk_sentiment"
    
    Returns:
        (final_score 0-100, breakdown dict showing each contribution)
    """
    weights = CONFIG["section_weights"]
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


def _threshold_score(value: float, brackets: list) -> int:
    """
    Given a value and ascending brackets [(threshold, score), ...],
    return the score for the first bracket where value <= threshold.
    """
    for threshold, score in brackets:
        if value <= threshold:
            return score
    return brackets[-1][1]
