"""Tests for macro engine hardening (freshness, scoring, coherence, narrative guard)."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta

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
from scoring_engine.headline_adjuster import compute_headline_adjustment
from scoring_engine.narrative_generator import (
    _augment_with_event_context,
    _narrative_matches_bias,
)
from scoring_engine.numeric_scorer import (
    compute_weighted_total_with_freshness,
    score_economy,
    score_inflation,
)
from scoring_engine.signal_quality import detect_regime, evaluate_signal_quality
from scoring_engine.verdict import compute_final_verdict
from data_fetchers import fred_data, yahoo_data


def test_score_inflation_forward_divergence_reduces_confidence():
    score, reason, details = score_inflation(2.4, 2.5, 14.0, 2.7)
    assert score >= 0
    assert details["divergence_flag"] is True
    assert details["confidence_haircut"] > 0
    assert "Divergence: yes" in reason


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


def test_bls_three_month_average_skips_dirty_rows_and_still_computes_prior():
    rows = [
        {"period": "M02", "value": "327.460", "calculations": {"pct_changes": {"1": "0.50"}}},
        {"period": "M01", "value": "326.588", "calculations": {"pct_changes": {"1": "0.40"}}},
        {"period": "M12", "value": "326.031", "calculations": {"pct_changes": {"1": "0.30"}}},
        {"period": "M11", "value": "-"},
        {"period": "M10", "value": "-"},
        {"period": "M09", "value": "324.888", "calculations": {"pct_changes": {"1": "0.20"}}},
        {"period": "M08", "value": "324.500", "calculations": {"pct_changes": {"1": "0.10"}}},
        {"period": "M07", "value": "324.100", "calculations": {"pct_changes": {"1": "0.00"}}},
    ]

    stats = fred_data._three_month_mom_stats_from_bls_rows(rows, "cpi")

    assert stats["cpi_mom_avg_3m"] == 0.4
    assert stats["cpi_mom_avg_3m_prior"] == 0.1


def test_bls_cpi_three_month_value_average_exposes_value_avg_fields():
    headline = [
        {"value": "327.460"},
        {"value": "326.588"},
        {"value": "326.031"},
        {"value": "325.063"},
        {"value": "324.888"},
        {"value": "324.500"},
    ]

    stats = fred_data._three_month_value_stats_from_bls_rows(headline, "cpi")

    assert stats["cpi_value_avg_3m"] == round((327.460 + 326.588 + 326.031) / 3.0, 3)
    assert stats["cpi_value_avg_3m_prior"] == round((325.063 + 324.888 + 324.500) / 3.0, 3)


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
    assert out["pce_value_avg_3m"] is not None


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


def test_treasury_month_uses_calendar_month_anchor(monkeypatch):
    df_2y = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-31", "2026-02-28", "2026-03-31"]),
            "value": [4.05, 4.15, 4.30],
        }
    )
    df_10y = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-31", "2026-02-28", "2026-03-31"]),
            "value": [4.20, 4.28, 4.40],
        }
    )

    def _mock_get_fred_data(series_id, *args, **kwargs):
        if series_id == "DGS2":
            return df_2y
        if series_id == "DGS10":
            return df_10y
        return pd.DataFrame()

    monkeypatch.setattr(fred_data, "get_fred_data", _mock_get_fred_data)

    out = fred_data.get_treasury_yields("month")

    assert out["yield_2y"]["date"] == "2026-03-31"
    assert out["yield_2y"]["change"] == round(4.30 - 4.15, 2)
    assert out["yield_10y"]["date"] == "2026-03-31"
    assert out["yield_10y"]["change"] == round(4.40 - 4.28, 2)


def test_trusted_quote_payload_uses_timeframe_snapshot_baseline(monkeypatch):
    now = datetime.now()
    rows = [
        {"timestamp": now.isoformat(), "sp500_price": 5000.0},
        {"timestamp": (now - timedelta(days=7)).isoformat(), "sp500_price": 4950.0},
        {"timestamp": (now - timedelta(days=35)).isoformat(), "sp500_price": 4700.0},
    ]

    monkeypatch.setattr("storage.db.get_latest_snapshots", lambda limit=10: rows)

    out = yahoo_data._trusted_quote_metric_payload(
        {
            "price": 4800.0,
            "source": "FMP:^GSPC",
            "date": now.strftime("%Y-%m-%d"),
        },
        timeframe="month",
        response_key="current_price",
        change_unit="percent",
        baseline_snapshot_field="sp500_price",
    )

    assert out is not None
    assert out["comparison_date"] is not None
    assert out["change"] == round(((4800.0 - 4700.0) / 4700.0) * 100.0, 2)


def test_pmi_requires_official_napm_series(monkeypatch):
    monkeypatch.setattr(fred_data, "trusted_market_apis", None)
    monkeypatch.setattr(fred_data, "get_fred_data", lambda *args, **kwargs: pd.DataFrame())
    monkeypatch.setattr(fred_data, "_get_pmi_from_calendar_trigger", lambda timeframe: None)
    monkeypatch.setattr(fred_data, "_get_pmi_from_tradingeconomics_page", lambda timeframe: None)
    monkeypatch.setattr(fred_data, "_get_pmi_from_investing_page", lambda timeframe: None)
    monkeypatch.setattr(fred_data, "_get_pmi_from_alphavantage", lambda timeframe: None)
    monkeypatch.setattr(fred_data, "_get_pmi_from_tradingview", lambda timeframe: None)
    monkeypatch.setattr(fred_data, "_get_pmi_from_ism_scrape", lambda timeframe: None)

    out = fred_data.get_pmi_data("month")

    assert out["error"] == "ISM Manufacturing PMI unavailable from configured sources"
    assert out["source"] == "unavailable"
    assert "pmi_value" not in out


def test_pmi_week_uses_latest_official_monthly_print(monkeypatch):
    monkeypatch.setattr(fred_data, "trusted_market_apis", None)
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-12-01", "2026-01-01", "2026-02-01"]),
            "value": [49.5, 50.4, 51.2],
        }
    )
    monkeypatch.setattr(fred_data, "get_fred_data", lambda *args, **kwargs: df)
    monkeypatch.setattr(fred_data, "_get_pmi_from_calendar_trigger", lambda timeframe: None)
    monkeypatch.setattr(fred_data, "_get_pmi_from_ism_scrape", lambda timeframe: None)
    monkeypatch.setattr(fred_data, "_get_pmi_from_tradingeconomics_page", lambda timeframe: None)

    out = fred_data.get_pmi_data("week")

    assert out["pmi_value"] == 51.2
    assert out["pmi_status"] == "expansion"
    assert out["pmi_trend"] == "rising"
    assert out["source"] == "FRED:NAPM"


def test_pmi_uses_tradingview_fallback_when_official_series_missing(monkeypatch):
    monkeypatch.setattr(fred_data, "trusted_market_apis", None)
    monkeypatch.setattr(fred_data, "get_fred_data", lambda *args, **kwargs: pd.DataFrame())
    monkeypatch.setattr(fred_data, "_get_pmi_from_calendar_trigger", lambda timeframe: None)
    monkeypatch.setattr(fred_data, "_get_pmi_from_tradingeconomics_page", lambda timeframe: None)
    monkeypatch.setattr(fred_data, "_get_pmi_from_investing_page", lambda timeframe: None)
    monkeypatch.setattr(fred_data, "_get_pmi_from_alphavantage", lambda timeframe: None)
    monkeypatch.setattr(fred_data, "_get_pmi_from_ism_scrape", lambda timeframe: None)
    monkeypatch.setattr(
        fred_data,
        "_get_pmi_from_tradingview",
        lambda timeframe: {
            "pmi_value": 50.7,
            "pmi_trend": "rising",
            "pmi_status": "expansion",
            "latest_date": "2026-03-01",
            "source": "TradingView:ECONOMICS:USPMI",
            "data_as_of": "2026-03-01",
            "timeframe": timeframe,
            "_proxy_note": "Unofficial TradingView macro feed",
        },
    )

    out = fred_data.get_pmi_data("week")

    assert out["pmi_value"] == 50.7
    assert out["source"] == "TradingView:ECONOMICS:USPMI"


def test_pmi_prefers_calendar_trigger_over_delayed_series(monkeypatch):
    monkeypatch.setattr(fred_data, "trusted_market_apis", None)
    monkeypatch.setattr(
        fred_data,
        "_get_pmi_from_calendar_trigger",
        lambda timeframe: {
            "pmi_value": 52.4,
            "pmi_trend": "rising",
            "pmi_status": "expansion",
            "latest_date": "2026-03-01",
            "source": "TradingEconomics:calendar:US:Manufacturing PMI",
            "data_as_of": "2026-03-01",
            "timeframe": timeframe,
            "release_trigger": "economic_calendar",
        },
    )
    monkeypatch.setattr(
        fred_data,
        "get_fred_data",
        lambda *args, **kwargs: pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-01-01", "2026-02-01"]),
                "value": [49.8, 50.2],
            }
        ),
    )

    out = fred_data.get_pmi_data("current")

    assert out["source"] == "TradingEconomics:calendar:US:Manufacturing PMI"
    assert out["pmi_value"] == 52.4


def test_move_prefers_yahoo_before_trusted_fallback(monkeypatch):
    calls = {"trusted": 0}

    monkeypatch.setattr(
        yahoo_data,
        "_yahoo_pct_change_series",
        lambda symbol, timeframe: {
            "current_price": 121.2,
            "change": 0.8,
            "trend": "rising",
            "source": symbol,
            "timeframe": timeframe,
        }
        if symbol == "^MOVE"
        else {"error": "missing"},
    )

    def _trusted(timeframe):
        calls["trusted"] += 1
        return {
            "current_price": 119.8,
            "change": -0.2,
            "trend": "falling",
            "source": "FMP:^MOVE",
            "timeframe": timeframe,
        }

    monkeypatch.setattr(yahoo_data, "_trusted_move_fallback", _trusted)

    out = yahoo_data.get_move_index_data("current")

    assert out["source"] == "^MOVE"
    assert calls["trusted"] == 0


def test_strict_mode_accepts_lbma_gold_source():
    assert run_analysis._is_source_official("gold", {"source": "LBMA:today.json"}) is True


def test_strict_mode_accepts_ecb_dxy_structure_source():
    assert run_analysis._is_source_official("dxy_structure", {"source": "ECB:EXR_fx_basket"}) is True


def test_strict_mode_accepts_tradingview_move_source():
    assert run_analysis._is_source_official("move_index", {"source": "TradingView:INDEX:MOVE"}) is True


def test_strict_mode_accepts_fmp_move_source():
    assert run_analysis._is_source_official("move_index", {"source": "FMP:^MOVE"}) is True


def test_strict_mode_accepts_tradingeconomics_pmi_source():
    assert run_analysis._is_source_official("pmi", {"source": "TradingEconomics:US:Manufacturing PMI"}) is True


def test_strict_mode_accepts_investing_pmi_source():
    assert run_analysis._is_source_official("pmi", {"source": "Investing:ISM_PMI_event_173"}) is True


def test_strict_mode_accepts_eem_source():
    assert run_analysis._is_source_official("eem", {"source": "EEM"}) is True


def test_strict_mode_accepts_cboe_tyvix_move_proxy_source():
    assert run_analysis._is_source_official("move_index", {"source": "CBOE:TYVIX_proxy"}) is True


def test_strict_mode_accepts_tradingeconomics_vix_source():
    assert run_analysis._is_source_official("vix", {"source": "TradingEconomics:VIX:IND"}) is True


def test_strict_mode_accepts_fmp_btc_etf_source():
    assert run_analysis._is_source_official("btc_etf", {"source": "FMP:batch-quote"}) is True


def test_score_economy_marks_missing_inputs_excluded_in_reasoning():
    score, reason, details = score_economy(
        unemployment_rate=4.4,
        unemployment_trend="falling",
        unemployment_trend_3m="falling",
        nfp_change=-92,
        gdp_growth=0.7,
        pmi_value=None,
        regime="neutral",
    )

    assert score > 0
    assert "PMI: N/A -> excluded" in reason
    assert details["nfp_score"] == 35


def test_score_economy_blends_short_and_medium_unemployment_trends():
    score, reason, details = score_economy(
        unemployment_rate=4.2,
        unemployment_trend="rising",
        unemployment_trend_3m="falling",
        nfp_change=25,
        gdp_growth=1.8,
        pmi_value=51.0,
        regime="neutral",
    )
    assert score >= 0
    assert details["unemployment_short_trend_component"] == -15
    assert details["unemployment_medium_trend_component"] == 5
    assert details["unemployment_trend_blend"] == -9.0
    assert "blend=-9.0" in reason


def test_detect_regime_risk_off_when_vix_high():
    regime, reasoning, multipliers = detect_regime(
        {
            "vix": {"current_value": 31.0},
            "financial_stress": {"hy_oas": 3.2},
            "balance_sheet": {"trend": "stable"},
            "m2": {"m2_trend": "stable"},
        }
    )
    assert regime == "risk_off"
    assert multipliers["dxy"] > 1.0


def test_evaluate_signal_quality_flags_economy_mismatch():
    quality = evaluate_signal_quality(
        {
            "jobs": {"nfp_change": -92, "unemployment_rate": 3.9, "unemployment_trend": "rising"},
            "cpi": {"yoy_rate": 2.4, "core_yoy_rate": 2.5},
            "oil": {"change": 12.0},
            "breakeven_10y": {"value": 2.6},
        },
        {"economy": 65, "inflation": 55, "fed_policy": 50, "liquidity": 50, "dxy": 50, "risk_sentiment": 50},
        "risk_off",
    )
    assert quality["contradiction_flags"]
    assert quality["sanity_flags"]
    assert quality["section_confidence_multipliers"]["economy"] < 1.0


def test_headline_adjustment_applies_source_weights():
    classified = [
        {"event_bias": "hawkish", "risk_impact": "risk_off", "confidence": 1.0, "reason": "x", "source": "Reuters"},
        {"event_bias": "hawkish", "risk_impact": "risk_off", "confidence": 1.0, "reason": "x", "source": "Others"},
    ]
    adj, reasoning = compute_headline_adjustment(classified)
    assert adj < 0
    assert "src=Reuters" in reasoning


def test_compute_final_verdict_includes_new_confidence_breakdown():
    verdict = compute_final_verdict(
        weighted_numeric_score=50,
        headline_adjustment=0,
        section_scores={"inflation": 50, "economy": 20, "fed_policy": 50, "liquidity": 50, "dxy": 50, "risk_sentiment": 20},
        headline_confidence=0.8,
        cross_signal_adjustment=0,
        data_freshness_info={"checks": [{"name": "CPI", "status": "MISSING", "is_critical": True}], "data_quality": {"score": 50.0, "stale_ratio": 0.0}},
        contradiction_flags=["x"],
        sanity_flags=["y"],
        downweighted_sections_count=2,
    )
    assert "data_quality_score" in verdict["components"]
    assert verdict["components"]["critical_metric_penalty"] > 0
    assert verdict["components"]["contradiction_multiplier"] < 1.0


def test_compute_final_verdict_missing_pmi_has_no_critical_penalty():
    verdict = compute_final_verdict(
        weighted_numeric_score=50,
        headline_adjustment=0,
        section_scores={"inflation": 50, "economy": 50, "fed_policy": 50, "liquidity": 50, "dxy": 50, "risk_sentiment": 50},
        headline_confidence=0.8,
        cross_signal_adjustment=0,
        data_freshness_info={"checks": [{"name": "PMI", "status": "MISSING", "is_critical": False}], "data_quality": {"score": 50.0, "stale_ratio": 0.0}},
        contradiction_flags=[],
        sanity_flags=[],
        downweighted_sections_count=0,
    )
    assert verdict["components"]["critical_metric_penalty"] == 0


def test_compute_final_verdict_missing_btc_etf_has_no_critical_penalty():
    verdict = compute_final_verdict(
        weighted_numeric_score=50,
        headline_adjustment=0,
        section_scores={"inflation": 50, "economy": 50, "fed_policy": 50, "liquidity": 50, "dxy": 50, "risk_sentiment": 50},
        headline_confidence=0.8,
        cross_signal_adjustment=0,
        data_freshness_info={"checks": [{"name": "BTC ETF Volume", "status": "MISSING", "is_critical": False}], "data_quality": {"score": 50.0, "stale_ratio": 0.0}},
        contradiction_flags=[],
        sanity_flags=[],
        downweighted_sections_count=0,
    )
    assert verdict["components"]["critical_metric_penalty"] == 0


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


def test_compute_weighted_total_with_freshness_ignores_missing_pmi_check():
    section_scores = {
        "inflation": 20,
        "economy": 80,
        "fed_policy": 50,
        "liquidity": 50,
        "dxy": 50,
        "risk_sentiment": 50,
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
    checks_missing_pmi = [{**c, "status": "MISSING"} if c["name"] == "PMI" else c for c in checks_all_fresh]

    score_fresh, _ = compute_weighted_total_with_freshness(section_scores, {"checks": checks_all_fresh})
    score_missing_pmi, _ = compute_weighted_total_with_freshness(section_scores, {"checks": checks_missing_pmi})

    assert score_missing_pmi == score_fresh


def test_compute_weighted_total_with_freshness_ignores_missing_btc_etf_check():
    section_scores = {
        "inflation": 20,
        "economy": 80,
        "fed_policy": 50,
        "liquidity": 50,
        "dxy": 50,
        "risk_sentiment": 50,
    }
    checks = [
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
    checks_with_missing_etf = checks + [{"name": "BTC ETF Volume", "status": "MISSING"}]

    score_base, _ = compute_weighted_total_with_freshness(section_scores, {"checks": checks})
    score_missing_etf, _ = compute_weighted_total_with_freshness(section_scores, {"checks": checks_with_missing_etf})

    assert score_missing_etf == score_base


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
