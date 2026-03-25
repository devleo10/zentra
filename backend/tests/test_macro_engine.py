"""Tests for macro engine hardening (freshness, scoring, coherence, narrative guard)."""
from __future__ import annotations

import os
import sys

import pytest

# Repo root: backend/tests -> backend
_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from run_analysis import MONETARY_EXPLICIT_CONFIDENCE_BOOST_TYPES

from scoring_engine.coherence import compute_coherence_adjustment
from scoring_engine.freshness import validate_data_freshness
from scoring_engine.narrative_generator import (
    _augment_with_event_context,
    _narrative_matches_bias,
)
from scoring_engine.numeric_scorer import (
    compute_weighted_total_with_freshness,
    score_inflation,
)


def test_score_inflation_pce_uses_separate_brackets():
    """PCE MoM uses tighter bands than CPI when pce_mom_change is present."""
    s_cpi_only, _ = score_inflation(0.08, None, None)
    s_with_pce, reason = score_inflation(0.08, 0.08, None)
    assert "PCE MoM: +0.08%" in reason
    # CPI 0.08 is flat (<=0.1); PCE 0.08 exceeds pce flat (0.05) -> higher inflation score drops
    assert s_with_pce < s_cpi_only


def test_compute_weighted_total_with_freshness_downweights_stale_section():
    """Stale CPI halves inflation section weight and renormalizes."""
    section_scores = {
        "inflation": 100,
        "economy": 0,
        "fed_policy": 0,
        "liquidity": 0,
        "dxy": 0,
        "risk_sentiment": 0,
    }
    checks_all_fresh = [
        {"name": "CPI", "status": "FRESH"},
        {"name": "PCE", "status": "FRESH"},
        {"name": "Unemployment Rate", "status": "FRESH"},
        {"name": "GDP", "status": "FRESH"},
        {"name": "PMI", "status": "FRESH"},
        {"name": "Fed Funds Rate", "status": "FRESH"},
        {"name": "10Y Yield", "status": "FRESH"},
        {"name": "M2 Money Supply", "status": "FRESH"},
        {"name": "Fed Balance Sheet", "status": "FRESH"},
        {"name": "DXY", "status": "FRESH"},
        {"name": "VIX", "status": "FRESH"},
        {"name": "S&P 500", "status": "FRESH"},
        {"name": "Gold", "status": "FRESH"},
        {"name": "HY OAS", "status": "FRESH"},
    ]
    stale_cpi = [{**c, "status": "STALE"} if c["name"] == "CPI" else c for c in checks_all_fresh]
    s_stale, _ = compute_weighted_total_with_freshness(section_scores, {"checks": stale_cpi})
    s_fresh, _ = compute_weighted_total_with_freshness(section_scores, {"checks": checks_all_fresh})
    # Only inflation is non-zero; weighted mean equals inflation_weight * 100 (e.g. 0.15 -> 15).
    assert s_fresh == 15
    assert s_stale < s_fresh


def test_coherence_penalizes_high_vix_with_high_risk_score():
    sections = {
        "inflation": 50,
        "economy": 50,
        "fed_policy": 50,
        "liquidity": 50,
        "dxy": 50,
        "risk_sentiment": 55,
    }
    raw = {"vix": {"current_value": 32.0}}
    adj, reason = compute_coherence_adjustment(sections, raw)
    assert adj < 0
    assert "VIX" in reason


def test_validate_data_freshness_includes_oil_and_fed_and_hy():
    data = {
        "cpi": {"latest_date": "2026-01-01"},
        "pce": {"latest_date": "2026-01-01"},
        "yields": {"yield_10y": {"date": "2026-03-24"}},
        "dxy": {"date": "2026-03-24"},
        "vix": {"date": "2026-03-24"},
        "sp500": {"date": "2026-03-24"},
        "gold": {"date": "2026-03-24"},
        "oil": {"latest_date": "2026-03-24"},
        "fed_rate": {"latest_date": "2026-03-20"},
        "btc": {"date": "2026-03-25"},
        "balance_sheet": {"latest_date": "2026-03-20"},
        "jobs": {"unemployment_date": "2026-02-01"},
        "gdp": {"latest_date": "2025-10-01"},
        "pmi": {"latest_date": "2026-02-01"},
        "m2": {"latest_date": "2026-02-01"},
        "financial_stress": {"latest_date": "2026-03-20"},
    }
    r = validate_data_freshness(data)
    names = {c["name"] for c in r.checks}
    assert "Oil" in names
    assert "Fed Funds Rate" in names
    assert "HY OAS" in names


def test_headline_confidence_boost_types_exclude_shutdown():
    assert "gov_shutdown" not in MONETARY_EXPLICIT_CONFIDENCE_BOOST_TYPES
    assert "rate_hold" in MONETARY_EXPLICIT_CONFIDENCE_BOOST_TYPES


def test_augment_geo_without_risk_off_avoids_risk_off_wording():
    out = _augment_with_event_context(
        "Base narrative.",
        [
            {
                "_headline_title": "Tensions in Middle East pipeline",
                "risk_impact": "neutral",
            }
        ],
    )
    assert "risk-off" not in out.lower()
    assert "uncertainty" in out.lower() or "headline-driven" in out.lower()


def test_narrative_matches_bias_extremes():
    assert _narrative_matches_bias(
        "The setup remains bearish for risk assets.", "Neutral", 72
    ) is False
    assert _narrative_matches_bias(
        "Conditions look bullish for BTC.", "Neutral", 28
    ) is False
    assert _narrative_matches_bias(
        "Mixed signals with elevated VIX.", "Neutral (Downside Bias)", 45
    ) is True
