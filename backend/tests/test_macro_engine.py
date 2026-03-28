"""Tests for macro engine hardening (freshness, scoring, coherence, narrative guard)."""
from __future__ import annotations

import os
import sys

import pytest
import pandas as pd

# Repo root: backend/tests -> backend
_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

import run_analysis
from run_analysis import MONETARY_EXPLICIT_CONFIDENCE_BOOST_TYPES

from scoring_engine.coherence import compute_coherence_adjustment
from scoring_engine.freshness import validate_data_freshness
from scoring_engine.narrative_generator import (
    _augment_with_event_context,
    _narrative_matches_bias,
)
from scoring_engine.numeric_scorer import (
    compute_weighted_total_with_freshness,
    score_economy,
    score_inflation,
)
from data_fetchers import fred_data


def test_score_inflation_pce_uses_separate_brackets():
    """PCE MoM uses tighter bands than CPI when pce_mom_change is present."""
    s_cpi_only, _ = score_inflation(0.08, None, None)
    s_with_pce, reason = score_inflation(0.08, 0.08, None)
    assert "PCE MoM: +0.08%" in reason
    # CPI 0.08 is flat (<=0.1); PCE 0.08 exceeds pce flat (0.05) -> higher inflation score drops
    assert s_with_pce < s_cpi_only


def test_bls_cpi_three_month_average_prefers_published_mom_changes():
    headline = [
        {"value": "320.0", "calculations": {"pct_changes": {"1": "0.50"}}},
        {"value": "318.5", "calculations": {"pct_changes": {"1": "0.40"}}},
        {"value": "317.1", "calculations": {"pct_changes": {"1": "0.30"}}},
        {"value": "316.2", "calculations": {"pct_changes": {"1": "0.20"}}},
        {"value": "315.5", "calculations": {"pct_changes": {"1": "0.10"}}},
        {"value": "315.2", "calculations": {"pct_changes": {"1": "0.00"}}},
    ]

    stats = fred_data._cpi_three_month_mom_stats_from_bls_headline(headline)

    assert stats["cpi_mom_avg_3m"] == 0.4
    assert stats["cpi_mom_avg_3m_prior"] == 0.1
    assert stats["cpi_mom_avg_3m_trend"] == "rising"


def test_bls_core_cpi_three_month_average_uses_published_mom_changes():
    core_rows = [
        {"value": "325.0", "calculations": {"pct_changes": {"1": "0.40"}}},
        {"value": "323.6", "calculations": {"pct_changes": {"1": "0.30"}}},
        {"value": "322.6", "calculations": {"pct_changes": {"1": "0.20"}}},
        {"value": "321.9", "calculations": {"pct_changes": {"1": "0.10"}}},
        {"value": "321.6", "calculations": {"pct_changes": {"1": "0.00"}}},
        {"value": "321.6", "calculations": {"pct_changes": {"1": "-0.10"}}},
    ]

    stats = fred_data._three_month_mom_stats_from_bls_rows(core_rows, "core_cpi")

    assert stats["core_cpi_mom_avg_3m"] == 0.3
    assert stats["core_cpi_mom_avg_3m_prior"] == 0.0
    assert stats["core_cpi_mom_avg_3m_trend"] == "rising"


def test_pce_week_change_uses_latest_mom_print(monkeypatch):
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-12-01", "2026-01-01", "2026-02-01", "2026-03-01"]),
            "value": [118.0, 119.18, 120.37, 121.57],
        }
    )
    monkeypatch.setattr(fred_data, "get_fred_data", lambda *args, **kwargs: df)

    out = fred_data.get_pce_data("week")

    assert out["mom_change"] == 1.0
    assert out["change"] == 1.0
    assert out["comparison_date"] == "2026-02-01"
    assert "wow_change" not in out


def test_pce_exposes_three_month_average(monkeypatch):
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-07-01", "2025-08-01", "2025-09-01", "2025-10-01", "2025-11-01", "2025-12-01", "2026-01-01", "2026-02-01", "2026-03-01"]),
            "value": [116.4, 116.8, 117.1, 117.5, 118.09, 118.44, 118.80, 119.27, 119.63],
        }
    )
    monkeypatch.setattr(fred_data, "get_fred_data", lambda *args, **kwargs: df)

    out = fred_data.get_pce_data("month")

    assert out["pce_mom_avg_3m"] is not None
    assert out["pce_mom_avg_3m_prior"] is not None


def test_fed_balance_sheet_week_uses_calendar_anchor(monkeypatch):
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-03-06", "2026-03-13", "2026-03-20", "2026-03-27"]),
            "value": [6900.0, 7000.0, 7100.0, 7200.0],
        }
    )
    monkeypatch.setattr(fred_data, "get_fred_data", lambda *args, **kwargs: df)

    out = fred_data.get_fed_balance_sheet("week")

    assert out["comparison_date"] == "2026-03-20"
    assert out["change"] == round((7200.0 - 7100.0) / 7100.0 * 100, 2)


def test_pmi_requires_official_napm_series(monkeypatch):
    monkeypatch.setattr(fred_data, "get_fred_data", lambda *args, **kwargs: pd.DataFrame())

    out = fred_data.get_pmi_data("month")

    assert out["error"] == "Official ISM Manufacturing PMI (NAPM) unavailable"
    assert out["source"] == "FRED:NAPM"
    assert "pmi_value" not in out


def test_pmi_week_uses_latest_official_monthly_print(monkeypatch):
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-12-01", "2026-01-01", "2026-02-01"]),
            "value": [49.5, 50.4, 51.2],
        }
    )
    monkeypatch.setattr(fred_data, "get_fred_data", lambda *args, **kwargs: df)

    out = fred_data.get_pmi_data("week")

    assert out["pmi_value"] == 51.2
    assert out["pmi_status"] == "expansion"
    assert out["pmi_trend"] == "rising"
    assert out["source"] == "FRED:NAPM"


def test_strict_mode_accepts_lbma_gold_source():
    assert run_analysis._is_source_official("gold", {"source": "LBMA:today.json"}) is True


def test_strict_mode_accepts_ecb_dxy_structure_source():
    assert run_analysis._is_source_official("dxy_structure", {"source": "ECB:EXR_fx_basket"}) is True


def test_score_economy_marks_missing_inputs_excluded_in_reasoning():
    score, reason = score_economy(
        unemployment_rate=4.4,
        unemployment_trend="falling",
        nfp_change=-92,
        gdp_growth=0.7,
        pmi_value=None,
    )

    assert score > 0
    assert "PMI: N/A -> excluded" in reason


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


def test_compute_weighted_total_with_freshness_excludes_missing_section():
    section_scores = {
        "inflation": 100,
        "economy": 0,
        "fed_policy": 0,
        "liquidity": 0,
        "dxy": 0,
        "risk_sentiment": 0,
    }
    checks_missing_cpi = [
        {"name": "CPI", "status": "MISSING"},
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

    score, breakdown = compute_weighted_total_with_freshness(
        section_scores, {"checks": checks_missing_cpi}
    )

    assert score == 0
    assert breakdown.get("inflation") is None


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


def test_validate_data_freshness_macro_fetched_at_makes_old_observation_fresh():
    """Batch fetch stamp: observation month can be old if we just pulled from APIs."""
    from datetime import datetime, timedelta

    now = datetime.now().isoformat()
    today = datetime.now().strftime("%Y-%m-%d")
    recent = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    data = {
        "cpi": {"latest_date": "2020-01-01", "fetched_at": now},
        "pce": {"latest_date": "2020-01-01", "fetched_at": now},
        "yields": {"yield_10y": {"date": recent}, "fetched_at": now},
        "dxy": {"date": recent},
        "vix": {"date": recent},
        "sp500": {"date": recent},
        "gold": {"date": recent},
        "oil": {"latest_date": recent, "fetched_at": now},
        "fed_rate": {"latest_date": recent, "fetched_at": now},
        "btc": {"date": today},
        "balance_sheet": {"latest_date": recent, "fetched_at": now},
        "jobs": {"unemployment_date": "2020-02-01", "fetched_at": now},
        "gdp": {"latest_date": "2019-10-01", "fetched_at": now},
        "pmi": {"latest_date": "2020-02-01", "fetched_at": now},
        "m2": {"latest_date": "2020-02-01", "fetched_at": now},
        "financial_stress": {"latest_date": recent, "fetched_at": now},
    }
    r = validate_data_freshness(data)
    for c in r.checks:
        assert c["status"] == "FRESH", (c["name"], c)
    dq = r.to_dict()["data_quality"]
    assert dq["stale_ratio"] == 0.0
    assert dq["score"] == 100.0


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
