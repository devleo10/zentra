"""Run analysis and cross-check metrics against external references.

Usage (from backend/):
    python scripts/tradingview_crosscheck_report.py --timeframe month --fresh
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from run_analysis import run_analysis
from data_fetchers import coingecko_data, fred_data, trusted_market_apis, yahoo_data

LOG_DIR = BACKEND_ROOT / "logs"

MARKET_REL_MATCH_PCT = 1.5
MARKET_REL_WARN_PCT = 4.0
PMI_ABS_MATCH = 0.30
PMI_ABS_WARN = 1.00
MACRO_REL_MATCH_PCT = 2.5
MACRO_REL_WARN_PCT = 7.5

TRADINGVIEW_SCANNER_URL = "https://scanner.tradingview.com/america/scan"

TV_MARKET_METRICS = [
    {"metric": "DXY", "snapshot_field": "dxy_value", "ticker": "TVC:DXY", "url": "https://www.tradingview.com/symbols/TVC-DXY/"},
    {"metric": "VIX", "snapshot_field": "vix", "ticker": "CBOE:VIX", "url": "https://www.tradingview.com/symbols/CBOE-VIX/"},
    {"metric": "S&P 500", "snapshot_field": "sp500_price", "ticker": "SP:SPX", "url": "https://www.tradingview.com/symbols/SP-SPX/"},
    {"metric": "Gold", "snapshot_field": "gold_price", "ticker": "TVC:GOLD", "url": "https://www.tradingview.com/symbols/TVC-GOLD/"},
    {"metric": "WTI Oil", "snapshot_field": "oil_price", "ticker": "TVC:USOIL", "url": "https://www.tradingview.com/symbols/TVC-USOIL/"},
    {"metric": "Natural Gas", "snapshot_field": "natgas_price", "ticker": "NYMEX:NG1!", "url": "https://www.tradingview.com/symbols/NYMEX-NG1!/"},
    {"metric": "MOVE", "snapshot_field": "move_index_value", "ticker": "INDEX:MOVE", "url": "https://www.tradingview.com/symbols/INDEX-MOVE/"},
    {"metric": "EEM", "snapshot_field": "eem_price", "ticker": "AMEX:EEM", "url": "https://www.tradingview.com/symbols/AMEX-EEM/"},
    {"metric": "BTC", "snapshot_field": "btc_price", "ticker": "BINANCE:BTCUSDT", "url": "https://www.tradingview.com/symbols/BINANCE-BTCUSDT/"},
]

# Snapshot field -> TradingView ticker candidates and comparison type.
# The first ticker that resolves from TradingView scanner is used.
TV_SNAPSHOT_FIELD_REFERENCES: Dict[str, Dict[str, Any]] = {
    "dxy_value": {
        "name": "DXY",
        "tickers": ["TVC:DXY", "ICEUS:DX1!"],
        "type": "market_rel",
    },
    "vix": {
        "name": "VIX",
        "tickers": ["CBOE:VIX"],
        "type": "market_rel",
    },
    "sp500_price": {
        "name": "S&P 500",
        "tickers": ["SP:SPX", "TVC:SPX"],
        "type": "market_rel",
    },
    "gold_price": {
        "name": "Gold",
        "tickers": ["TVC:GOLD", "OANDA:XAUUSD"],
        "type": "market_rel",
    },
    "oil_price": {
        "name": "WTI Oil",
        "tickers": ["TVC:USOIL", "NYMEX:CL1!"],
        "type": "market_rel",
    },
    "natgas_price": {
        "name": "Natural Gas",
        "tickers": ["NYMEX:NG1!", "TVC:NATGAS"],
        "type": "market_rel",
    },
    "move_index_value": {
        "name": "MOVE",
        "tickers": ["INDEX:MOVE", "CBOE:TYVIX"],
        "type": "market_rel",
    },
    "eem_price": {
        "name": "EEM",
        "tickers": ["AMEX:EEM"],
        "type": "market_rel",
    },
    "btc_price": {
        "name": "BTC",
        "tickers": ["BINANCE:BTCUSDT", "COINBASE:BTCUSD"],
        "type": "market_rel",
    },
    "btc_dominance": {
        "name": "BTC Dominance",
        "tickers": ["CRYPTOCAP:BTC.D"],
        "type": "market_rel",
    },
    "stablecoin_dominance": {
        "name": "Stablecoin Dominance",
        "tickers": ["CRYPTOCAP:USDT.D", "CRYPTOCAP:USDC.D"],
        "type": "market_rel",
    },
    "pmi_value": {
        "name": "PMI",
        "tickers": ["ECONOMICS:USPMI"],
        "type": "pmi_abs",
    },
    "cpi_yoy_rate": {
        "name": "CPI YoY",
        "tickers": ["ECONOMICS:USIRYY"],
        "type": "macro_rel",
    },
    "cpi_value": {
        "name": "CPI Index",
        "tickers": [],
        "type": "macro_rel",
    },
    "core_cpi_value": {
        "name": "Core CPI Index",
        "tickers": [],
        "type": "macro_rel",
    },
    "cpi_core_yoy_rate": {
        "name": "Core CPI YoY",
        "tickers": [],
        "type": "macro_rel",
    },
    "fed_funds_rate": {
        "name": "Fed Funds Rate",
        "tickers": ["ECONOMICS:USINTR"],
        "type": "macro_rel",
    },
    "unemployment_rate": {
        "name": "Unemployment Rate",
        "tickers": ["ECONOMICS:USURTOT"],
        "type": "macro_rel",
    },
    "gdp_growth_rate": {
        "name": "GDP Growth",
        "tickers": ["ECONOMICS:USGDPYY"],
        "type": "macro_rel",
    },
    "pce_value": {
        "name": "PCE Index",
        "tickers": [],
        "type": "macro_rel",
    },
    "m2_yoy_change": {
        "name": "M2 YoY Change",
        "tickers": [],
        "type": "macro_rel",
    },
    "nfp_change": {
        "name": "NFP Change",
        "tickers": [],
        "type": "macro_rel",
    },
    "financial_stress_index": {
        "name": "Financial Stress Index",
        "tickers": [],
        "type": "macro_rel",
    },
    "hy_oas": {
        "name": "High Yield OAS",
        "tickers": [],
        "type": "macro_rel",
    },
    "real_yield_10y": {
        "name": "US 10Y Real Yield",
        "tickers": [],
        "type": "macro_rel",
    },
    "ten_year_yield": {
        "name": "US 10Y Yield",
        "tickers": ["TVC:US10Y", "CBOE:TNX"],
        "type": "market_rel",
    },
    "two_year_yield": {
        "name": "US 2Y Yield",
        "tickers": ["TVC:US02Y"],
        "type": "market_rel",
    },
    "ten_year_breakeven": {
        "name": "US 10Y Breakeven",
        "tickers": ["FRED:T10YIE"],
        "type": "macro_rel",
    },
}

_RELIABLE_FETCH_CACHE: Dict[str, Dict[str, Any]] = {}


def _safe_float(value: Any) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(out):
        return None
    return out


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _delta(local_value: Optional[float], external_value: Optional[float]) -> Tuple[Optional[float], Optional[float]]:
    if local_value is None or external_value is None:
        return None, None
    abs_delta = abs(local_value - external_value)
    rel_delta_pct = abs_delta / abs(external_value) * 100.0 if external_value != 0 else None
    return abs_delta, rel_delta_pct


def _status_market(abs_delta: Optional[float], rel_delta_pct: Optional[float]) -> Tuple[str, str]:
    if abs_delta is None:
        return "no_reference", "Missing local or external value"
    if rel_delta_pct is None:
        return "warning", "Relative delta unavailable"
    if rel_delta_pct <= MARKET_REL_MATCH_PCT:
        return "match", f"rel delta <= {MARKET_REL_MATCH_PCT:.1f}%"
    if rel_delta_pct <= MARKET_REL_WARN_PCT:
        return "warning", f"rel delta <= {MARKET_REL_WARN_PCT:.1f}%"
    return "mismatch", f"rel delta > {MARKET_REL_WARN_PCT:.1f}%"


def _status_macro(abs_delta: Optional[float], rel_delta_pct: Optional[float]) -> Tuple[str, str]:
    if abs_delta is None:
        return "no_reference", "Missing local or external value"
    if rel_delta_pct is None:
        return "warning", "Relative delta unavailable"
    if rel_delta_pct <= MACRO_REL_MATCH_PCT:
        return "match", f"rel delta <= {MACRO_REL_MATCH_PCT:.1f}%"
    if rel_delta_pct <= MACRO_REL_WARN_PCT:
        return "warning", f"rel delta <= {MACRO_REL_WARN_PCT:.1f}%"
    return "mismatch", f"rel delta > {MACRO_REL_WARN_PCT:.1f}%"


def _status_pmi(abs_delta: Optional[float]) -> Tuple[str, str]:
    if abs_delta is None:
        return "no_reference", "Missing local or external PMI"
    if abs_delta <= PMI_ABS_MATCH:
        return "match", f"|delta| <= {PMI_ABS_MATCH:.2f}"
    if abs_delta <= PMI_ABS_WARN:
        return "warning", f"|delta| <= {PMI_ABS_WARN:.2f}"
    return "mismatch", f"|delta| > {PMI_ABS_WARN:.2f}"


def _fmt(value: Optional[float], digits: int = 2) -> str:
    if value is None:
        return "n/a"
    numeric = _safe_float(value)
    if numeric is not None:
        return f"{numeric:.{digits}f}"
    return str(value)


def _escape_md(value: Any) -> str:
    text = str(value) if value is not None else "n/a"
    return text.replace("|", "\\|")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def _tradingview_scan_latest_close_direct(ticker: str) -> Optional[float]:
    payload = {
        "symbols": {"tickers": [ticker], "query": {"types": []}},
        "columns": ["close"],
    }
    try:
        resp = requests.post(TRADINGVIEW_SCANNER_URL, json=payload, timeout=15)
        resp.raise_for_status()
        data = (resp.json() or {}).get("data") or []
        if not data:
            return None
        row = data[0]
        if isinstance(row, dict):
            vals = row.get("d")
            if isinstance(vals, list) and vals:
                return _safe_float(vals[0])
        return None
    except Exception:
        return None


def _resolve_tradingview_value(tickers: List[str]) -> Tuple[Optional[float], Optional[str]]:
    for ticker in tickers:
        value = _safe_float(yahoo_data._tradingview_scan_latest_close(ticker))
        if value is None:
            value = _tradingview_scan_latest_close_direct(ticker)
        if value is not None:
            return value, ticker
    return None, None


def _resolve_reliable_source_value(snapshot_field: str, timeframe: str) -> Tuple[Optional[float], Optional[str], Optional[str], Optional[str]]:
    def _cached_reliable(cache_key: str, loader) -> Dict[str, Any]:
        if cache_key not in _RELIABLE_FETCH_CACHE:
            try:
                loaded = loader()
            except Exception:
                loaded = {}
            _RELIABLE_FETCH_CACHE[cache_key] = loaded if isinstance(loaded, dict) else {}
        return _RELIABLE_FETCH_CACHE.get(cache_key, {})

    def _as_date(value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text[:10] if text else None

    try:
        if snapshot_field == "btc_price":
            for fn, url in [
                (coingecko_data.get_btc_spot_binance, "https://api.binance.com/api/v3/klines"),
                (coingecko_data.get_btc_spot_coinbase, "https://api.exchange.coinbase.com/products/BTC-USD/candles"),
                (coingecko_data.get_btc_spot_kraken, "https://api.kraken.com/0/public/OHLC"),
                (coingecko_data.get_btc_price, "https://api.coingecko.com/api/v3/simple/price"),
            ]:
                row = fn(timeframe)
                if not isinstance(row, dict) or row.get("error"):
                    continue
                price = _safe_float(row.get("price_usd"))
                if price is not None:
                    return price, str(row.get("_source") or row.get("source") or fn.__name__), _as_date(row.get("date")), url

        if snapshot_field == "pmi_value":
            cal = _cached_reliable(
                f"te_pmi_calendar:{timeframe}",
                lambda: trusted_market_apis.get_tradingeconomics_us_pmi_calendar_event(),
            )
            cal_val = _safe_float((cal or {}).get("actual_value"))
            if cal_val is not None:
                return (
                    cal_val,
                    str((cal or {}).get("source") or "TradingEconomics:calendar:US:Manufacturing PMI"),
                    _as_date((cal or {}).get("date")),
                    "https://api.tradingeconomics.com/calendar/country/united%20states",
                )

            te = _cached_reliable(
                f"te_pmi_indicator:{timeframe}",
                lambda: trusted_market_apis.get_tradingeconomics_us_manufacturing_pmi(),
            )
            te_val = _safe_float((te or {}).get("pmi_value"))
            if te_val is not None:
                return (
                    te_val,
                    str((te or {}).get("source") or "TradingEconomics:US:Manufacturing PMI"),
                    _as_date((te or {}).get("date")),
                    "https://api.tradingeconomics.com/historical/country/united%20states/indicator/manufacturing%20pmi",
                )

            te_web = _cached_reliable(
                f"te_pmi_web:{timeframe}",
                lambda: fred_data._get_pmi_from_tradingeconomics_page(timeframe),
            )
            web_val = _safe_float((te_web or {}).get("pmi_value"))
            if web_val is not None:
                return (
                    web_val,
                    str((te_web or {}).get("source") or "TradingEconomics:web"),
                    _as_date((te_web or {}).get("latest_date")),
                    fred_data.TRADINGECONOMICS_US_PMI_PAGE,
                )

        if snapshot_field == "dxy_value":
            te = _cached_reliable(
                f"te_dxy:{timeframe}",
                lambda: trusted_market_apis.get_tradingeconomics_quote_from_search(
                "US Dollar Index",
                preferred_ticker="DXY",
                ),
            )
            te_val = _safe_float((te or {}).get("price"))
            if te_val is not None:
                return te_val, str((te or {}).get("source") or "TradingEconomics:DXY"), _as_date((te or {}).get("date")), "https://api.tradingeconomics.com/markets/search/dollar%20index"

            dxy = _cached_reliable(
                f"fred_dxy_tw:{timeframe}",
                lambda: fred_data.get_dxy_from_fred_trade_weighted(timeframe),
            )
            dxy_val = _safe_float((dxy or {}).get("current_price"))
            if dxy_val is not None:
                return dxy_val, str((dxy or {}).get("source") or "FRED_DTWEXBGS"), _as_date((dxy or {}).get("date") or (dxy or {}).get("data_as_of")), "https://fred.stlouisfed.org/series/DTWEXBGS"

        if snapshot_field == "vix":
            for ref in [
                trusted_market_apis.get_fmp_quote("^VIX"),
                trusted_market_apis.get_eodhd_quote_from_search("VIX", asset_type="index"),
            ]:
                val = _safe_float((ref or {}).get("price"))
                if val is not None:
                    return val, str((ref or {}).get("source") or "trusted_provider"), _as_date((ref or {}).get("date")), "https://financialmodelingprep.com/stable/quote"

            vix_fred = fred_data.get_fred_series("VIXCLS", timeframe)
            vix_val = _safe_float((vix_fred or {}).get("value"))
            if vix_val is not None:
                return vix_val, str((vix_fred or {}).get("_source") or "FRED:VIXCLS"), _as_date((vix_fred or {}).get("date")), "https://fred.stlouisfed.org/series/VIXCLS"

        if snapshot_field == "sp500_price":
            for ref in [
                trusted_market_apis.get_fmp_quote("^GSPC"),
                trusted_market_apis.get_tradingeconomics_quote_from_search("s&p 500", preferred_symbol="SPX:IND"),
                trusted_market_apis.get_eodhd_quote_from_search("SPX", asset_type="index"),
            ]:
                val = _safe_float((ref or {}).get("price"))
                if val is not None:
                    return val, str((ref or {}).get("source") or "trusted_provider"), _as_date((ref or {}).get("date")), "https://financialmodelingprep.com/stable/quote"

            spx_fred = fred_data.get_fred_series("SP500", timeframe)
            spx_val = _safe_float((spx_fred or {}).get("value"))
            if spx_val is not None:
                return spx_val, str((spx_fred or {}).get("_source") or "FRED:SP500"), _as_date((spx_fred or {}).get("date")), "https://fred.stlouisfed.org/series/SP500"

        if snapshot_field == "gold_price":
            gold_fred = _cached_reliable(
                f"fred_gold:{timeframe}",
                lambda: fred_data.get_fred_series("GOLDAMGBD228NLBM", timeframe),
            )
            gold_val = _safe_float((gold_fred or {}).get("value"))
            if gold_val is not None:
                return gold_val, str((gold_fred or {}).get("_source") or "FRED:GOLDAMGBD228NLBM"), _as_date((gold_fred or {}).get("date")), "https://fred.stlouisfed.org/series/GOLDAMGBD228NLBM"

            gold_lbma = _cached_reliable(
                f"gold_lbma:{timeframe}",
                lambda: yahoo_data.get_gold_data(timeframe),
            )
            gold_lbma_val = _safe_float((gold_lbma or {}).get("current_price"))
            if gold_lbma_val is not None:
                return gold_lbma_val, str((gold_lbma or {}).get("source") or "LBMA"), _as_date((gold_lbma or {}).get("date") or (gold_lbma or {}).get("data_as_of")), "https://prices.lbma.org.uk/json/today.json"

        if snapshot_field == "oil_price":
            oil = _cached_reliable(
                f"fred_oil:{timeframe}",
                lambda: fred_data.get_oil_data(timeframe),
            )
            oil_val = _safe_float((oil or {}).get("current_price"))
            if oil_val is not None:
                return oil_val, str((oil or {}).get("source") or "FRED:DCOILWTICO"), _as_date((oil or {}).get("latest_date") or (oil or {}).get("data_as_of")), "https://fred.stlouisfed.org/series/DCOILWTICO"

        if snapshot_field == "natgas_price":
            ng = _cached_reliable(
                f"fred_natgas:{timeframe}",
                lambda: fred_data.get_fred_series("DHHNGSP", timeframe),
            )
            ng_val = _safe_float((ng or {}).get("value"))
            if ng_val is not None:
                return ng_val, str((ng or {}).get("_source") or "FRED:DHHNGSP"), _as_date((ng or {}).get("date")), "https://fred.stlouisfed.org/series/DHHNGSP"

        if snapshot_field == "move_index_value":
            for ref in [
                trusted_market_apis.get_fmp_quote("^MOVE"),
                trusted_market_apis.get_eodhd_quote_from_search("MOVE", asset_type="index"),
            ]:
                val = _safe_float((ref or {}).get("price"))
                if val is not None:
                    return val, str((ref or {}).get("source") or "trusted_provider"), _as_date((ref or {}).get("date")), "https://financialmodelingprep.com/stable/quote"

            move_yahoo = _cached_reliable(
                f"move_yahoo:{timeframe}",
                lambda: yahoo_data.get_move_index_data(timeframe),
            )
            move_val = _safe_float((move_yahoo or {}).get("current_price"))
            if move_val is not None:
                return move_val, str((move_yahoo or {}).get("source") or "Yahoo:^MOVE"), _as_date((move_yahoo or {}).get("date")), "https://query1.finance.yahoo.com/v8/finance/chart/%5EMOVE"

        if snapshot_field == "eem_price":
            for ref in [
                trusted_market_apis.get_fmp_quote("EEM"),
                trusted_market_apis.get_eodhd_quote_from_search("EEM", asset_type="etf"),
            ]:
                val = _safe_float((ref or {}).get("price"))
                if val is not None:
                    return val, str((ref or {}).get("source") or "trusted_provider"), _as_date((ref or {}).get("date")), "https://financialmodelingprep.com/stable/quote"

        if snapshot_field == "btc_dominance":
            dom = _cached_reliable(
                f"cg_btc_dom:{timeframe}",
                lambda: coingecko_data.get_btc_dominance(timeframe),
            )
            dom_val = _safe_float((dom or {}).get("btc_dominance"))
            if dom_val is not None:
                return dom_val, str((dom or {}).get("source") or "CoinGecko"), _as_date((dom or {}).get("date")), "https://api.coingecko.com/api/v3/global"

        if snapshot_field == "stablecoin_dominance":
            stable = _cached_reliable(
                f"cg_stable_dom:{timeframe}",
                lambda: coingecko_data.get_stablecoin_data(timeframe),
            )
            stable_val = _safe_float((stable or {}).get("total_stablecoin_dominance"))
            if stable_val is not None:
                return stable_val, str((stable or {}).get("source") or "CoinGecko"), _as_date((stable or {}).get("date")), "https://api.coingecko.com/api/v3/global"

        if snapshot_field in {"cpi_yoy_rate", "cpi_value", "core_cpi_value", "cpi_core_yoy_rate"}:
            cpi = _cached_reliable(
                f"fred_cpi:{timeframe}",
                lambda: fred_data.get_cpi_data(timeframe),
            )
            if snapshot_field == "cpi_value":
                val = _safe_float((cpi or {}).get("latest_value"))
            elif snapshot_field == "core_cpi_value":
                val = _safe_float((cpi or {}).get("core_latest_value"))
            elif snapshot_field == "cpi_core_yoy_rate":
                val = _safe_float((cpi or {}).get("core_yoy_rate"))
            else:
                val = _safe_float((cpi or {}).get("yoy_rate"))
            if val is not None:
                return val, str((cpi or {}).get("source") or "BLS/FRED"), _as_date((cpi or {}).get("latest_date")), "https://api.bls.gov/publicAPI/v2/timeseries/data/"

        if snapshot_field == "pce_value":
            pce = _cached_reliable(
                f"fred_pce:{timeframe}",
                lambda: fred_data.get_pce_data(timeframe),
            )
            pce_val = _safe_float((pce or {}).get("latest_value"))
            if pce_val is not None:
                return pce_val, str((pce or {}).get("source") or "FRED"), _as_date((pce or {}).get("latest_date")), "https://fred.stlouisfed.org/series/PCEPI"

        if snapshot_field == "m2_yoy_change":
            m2 = _cached_reliable(
                f"fred_m2:{timeframe}",
                lambda: fred_data.get_m2_money_supply(timeframe),
            )
            m2_val = _safe_float((m2 or {}).get("m2_yoy_change"))
            if m2_val is not None:
                return m2_val, str((m2 or {}).get("source") or "FRED"), _as_date((m2 or {}).get("latest_date")), "https://fred.stlouisfed.org/series/M2SL"

        if snapshot_field in {"financial_stress_index", "hy_oas"}:
            stress = _cached_reliable(
                f"fred_stress:{timeframe}",
                lambda: fred_data.get_financial_stress(timeframe),
            )
            if snapshot_field == "financial_stress_index":
                stress_val = _safe_float((stress or {}).get("stress_index"))
                if stress_val is not None:
                    return stress_val, str((stress or {}).get("source") or "FRED"), _as_date((stress or {}).get("latest_date")), "https://fred.stlouisfed.org/series/STLFSI4"
            else:
                hy_val = _safe_float((stress or {}).get("hy_oas"))
                if hy_val is not None:
                    return hy_val, str((stress or {}).get("source") or "FRED"), _as_date((stress or {}).get("latest_date")), "https://fred.stlouisfed.org/series/BAMLH0A0HYM2"

        if snapshot_field == "nfp_change":
            jobs = _cached_reliable(
                f"fred_jobs:{timeframe}",
                lambda: fred_data.get_jobs_data(timeframe),
            )
            nfp_val = _safe_float((jobs or {}).get("nfp_change"))
            if nfp_val is not None:
                return nfp_val, str((jobs or {}).get("source") or "FRED"), _as_date((jobs or {}).get("nfp_date")), "https://fred.stlouisfed.org/series/PAYEMS"

        if snapshot_field == "real_yield_10y":
            yields = _cached_reliable(
                f"fred_yields:{timeframe}",
                lambda: fred_data.get_treasury_yields(timeframe),
            )
            breakeven = _cached_reliable(
                f"fred_breakeven:{timeframe}",
                lambda: fred_data.get_10y_breakeven_expectation(timeframe),
            )
            nominal = _safe_float(((yields or {}).get("yield_10y") or {}).get("value"))
            be = _safe_float((breakeven or {}).get("value"))
            if nominal is not None and be is not None:
                return nominal - be, "FRED:computed_real_yield_10y", _as_date((breakeven or {}).get("latest_date") or ((yields or {}).get("yield_10y") or {}).get("date")), "https://fred.stlouisfed.org/series/DGS10"

        if snapshot_field == "cpi_yoy_rate":
            cpi = _cached_reliable(
                f"fred_cpi:{timeframe}",
                lambda: fred_data.get_cpi_data(timeframe),
            )
            val = _safe_float((cpi or {}).get("yoy_rate"))
            if val is not None:
                return val, str((cpi or {}).get("source") or "BLS/FRED"), _as_date((cpi or {}).get("latest_date")), "https://api.bls.gov/publicAPI/v2/timeseries/data/"

        if snapshot_field == "fed_funds_rate":
            fed = _cached_reliable(
                f"fred_fedrate:{timeframe}",
                lambda: fred_data.get_fed_funds_rate(timeframe),
            )
            val = _safe_float((fed or {}).get("current_rate"))
            if val is not None:
                return val, str((fed or {}).get("source") or "FRED"), _as_date((fed or {}).get("latest_date")), "https://fred.stlouisfed.org/series/DFEDTARU"

        if snapshot_field == "unemployment_rate":
            jobs = _cached_reliable(
                f"fred_jobs:{timeframe}",
                lambda: fred_data.get_jobs_data(timeframe),
            )
            val = _safe_float((jobs or {}).get("unemployment_rate"))
            if val is not None:
                return val, str((jobs or {}).get("source") or "FRED"), _as_date((jobs or {}).get("unemployment_date")), "https://fred.stlouisfed.org/series/UNRATE"

        if snapshot_field == "gdp_growth_rate":
            gdp = _cached_reliable(
                f"fred_gdp:{timeframe}",
                lambda: fred_data.get_gdp_data(timeframe),
            )
            val = _safe_float((gdp or {}).get("gdp_growth_rate"))
            if val is not None:
                return val, str((gdp or {}).get("source") or "FRED"), _as_date((gdp or {}).get("latest_date")), "https://fred.stlouisfed.org/series/A191RL1Q225SBEA"

        if snapshot_field == "ten_year_yield":
            yields = _cached_reliable(
                f"fred_yields:{timeframe}",
                lambda: fred_data.get_treasury_yields(timeframe),
            )
            val = _safe_float(((yields or {}).get("yield_10y") or {}).get("value"))
            if val is not None:
                return val, str(((yields or {}).get("yield_10y") or {}).get("source") or "FRED"), _as_date(((yields or {}).get("yield_10y") or {}).get("date")), "https://fred.stlouisfed.org/series/DGS10"

        if snapshot_field == "two_year_yield":
            yields = _cached_reliable(
                f"fred_yields:{timeframe}",
                lambda: fred_data.get_treasury_yields(timeframe),
            )
            val = _safe_float(((yields or {}).get("yield_2y") or {}).get("value"))
            if val is not None:
                return val, str(((yields or {}).get("yield_2y") or {}).get("source") or "FRED"), _as_date(((yields or {}).get("yield_2y") or {}).get("date")), "https://fred.stlouisfed.org/series/DGS2"

        if snapshot_field == "ten_year_breakeven":
            be = _cached_reliable(
                f"fred_breakeven:{timeframe}",
                lambda: fred_data.get_10y_breakeven_expectation(timeframe),
            )
            val = _safe_float((be or {}).get("value"))
            if val is not None:
                return val, str((be or {}).get("source") or "FRED"), _as_date((be or {}).get("latest_date")), "https://fred.stlouisfed.org/series/T10YIE"
    except Exception:
        return None, None, None, None

    return None, None, None, None


def _crosscheck_snapshot_field(snapshot_field: str, local_value: Any, timeframe: str) -> Dict[str, Any]:
    reference_cfg = TV_SNAPSHOT_FIELD_REFERENCES.get(snapshot_field)
    local_num = _safe_float(local_value)

    if local_num is None:
        return {
            "metric": snapshot_field,
            "snapshot_field": snapshot_field,
            "local_value": local_value,
            "external_value": None,
            "external_source": None,
            "external_date": None,
            "delta_abs": None,
            "delta_rel_pct": None,
            "status": "skipped_non_numeric",
            "notes": "Snapshot field is non-numeric or null",
            "url": None,
        }

    if not reference_cfg:
        return {
            "metric": snapshot_field,
            "snapshot_field": snapshot_field,
            "local_value": local_num,
            "external_value": None,
            "external_source": None,
            "external_date": None,
            "delta_abs": None,
            "delta_rel_pct": None,
            "status": "no_reference",
            "notes": "No external mapping configured for this snapshot field",
            "url": None,
        }

    external_value, ticker = _resolve_tradingview_value(reference_cfg.get("tickers", []))
    external_source = f"TradingView:{ticker}" if ticker else None
    external_date = datetime.now().strftime("%Y-%m-%d") if external_value is not None else None
    external_url = "https://scanner.tradingview.com/america/scan" if ticker else None

    if external_value is None:
        ext_value, ext_source, ext_date, ext_url = _resolve_reliable_source_value(snapshot_field, timeframe)
        if ext_value is not None:
            external_value = ext_value
            external_source = ext_source
            external_date = ext_date
            external_url = ext_url

    abs_delta, rel_delta_pct = _delta(local_num, external_value)
    comparison_type = reference_cfg.get("type", "market_rel")
    if comparison_type == "pmi_abs":
        status, notes = _status_pmi(abs_delta)
    elif comparison_type == "macro_rel":
        status, notes = _status_macro(abs_delta, rel_delta_pct)
    else:
        status, notes = _status_market(abs_delta, rel_delta_pct)

    if external_source is None:
        notes = "Mapped TradingView and reliable-source lookups unavailable"

    return {
        "metric": reference_cfg.get("name", snapshot_field),
        "snapshot_field": snapshot_field,
        "local_value": local_num,
        "external_value": external_value,
        "external_source": external_source,
        "external_date": external_date,
        "delta_abs": abs_delta,
        "delta_rel_pct": rel_delta_pct,
        "status": status,
        "notes": notes,
        "url": external_url,
    }


def _crosscheck_market_metric(snapshot: Dict[str, Any], metric_cfg: Dict[str, str]) -> Dict[str, Any]:
    metric = metric_cfg["metric"]
    local_value = _safe_float(snapshot.get(metric_cfg["snapshot_field"]))
    external_value = _safe_float(yahoo_data._tradingview_scan_latest_close(metric_cfg["ticker"]))
    abs_delta, rel_delta_pct = _delta(local_value, external_value)
    status, notes = _status_market(abs_delta, rel_delta_pct)
    return {
        "metric": metric,
        "local_value": local_value,
        "external_value": external_value,
        "external_source": f"TradingView:{metric_cfg['ticker']}",
        "external_date": datetime.now().strftime("%Y-%m-%d") if external_value is not None else None,
        "delta_abs": abs_delta,
        "delta_rel_pct": rel_delta_pct,
        "status": status,
        "notes": notes,
        "url": metric_cfg["url"],
    }


def _crosscheck_pmi(snapshot: Dict[str, Any], timeframe: str) -> Dict[str, Any]:
    local_value = _safe_float(snapshot.get("pmi_value"))
    tv = fred_data._get_pmi_from_tradingview(timeframe)
    external_value = _safe_float((tv or {}).get("pmi_value"))
    abs_delta, rel_delta_pct = _delta(local_value, external_value)
    status, notes = _status_pmi(abs_delta)
    return {
        "metric": "PMI",
        "local_value": local_value,
        "external_value": external_value,
        "external_source": "TradingView:ECONOMICS:USPMI",
        "external_date": (tv or {}).get("latest_date"),
        "delta_abs": abs_delta,
        "delta_rel_pct": rel_delta_pct,
        "status": status,
        "notes": notes,
        "url": "https://scanner.tradingview.com/america/scan",
    }


def _build_markdown(
    *,
    timeframe: str,
    run_started_at: str,
    run_finished_at: str,
    snapshot: Dict[str, Any],
    comparisons: List[Dict[str, Any]],
) -> str:
    mismatch_count = sum(1 for row in comparisons if row["status"] == "mismatch")
    warning_count = sum(1 for row in comparisons if row["status"] == "warning")
    match_count = sum(1 for row in comparisons if row["status"] == "match")
    no_reference_count = sum(1 for row in comparisons if row["status"] == "no_reference")
    skipped_count = sum(1 for row in comparisons if row["status"] == "skipped_non_numeric")

    lines: List[str] = []
    lines.append("# External Cross-Check Report")
    lines.append("")
    lines.append(f"- generated_at_utc: {run_finished_at}")
    lines.append(f"- timeframe: {timeframe}")
    lines.append(f"- run_started_at_utc: {run_started_at}")
    lines.append(f"- run_finished_at_utc: {run_finished_at}")
    lines.append("")
    lines.append("## Local Run Summary")
    lines.append("")
    lines.append(f"- final_score: {snapshot.get('final_score')}")
    lines.append(f"- bias: {snapshot.get('bias')}")
    lines.append(f"- confidence_pct: {snapshot.get('confidence_pct')}")
    lines.append("")
    lines.append("## Metric Comparison")
    lines.append("")
    lines.append("| Metric | Snapshot Field | Local Value | External Value | External Source | External Date | Delta Abs | Delta Rel % | Status | Notes | URL |")
    lines.append("|---|---|---:|---:|---|---|---:|---:|---|---|---|")

    for row in comparisons:
        lines.append(
            "| "
            + f"{row['metric']} | "
            + f"{_escape_md(row.get('snapshot_field'))} | "
            + f"{_fmt(row['local_value'])} | "
            + f"{_fmt(row['external_value'])} | "
            + f"{_escape_md(row['external_source'])} | "
            + f"{_escape_md(row['external_date'])} | "
            + f"{_fmt(row['delta_abs'])} | "
            + f"{_fmt(row['delta_rel_pct'])} | "
            + f"{_escape_md(row['status'])} | "
            + f"{_escape_md(row['notes'])} | "
            + f"{_escape_md(row['url'])} |"
        )

    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- matches: {match_count}")
    lines.append(f"- warnings: {warning_count}")
    lines.append(f"- mismatches: {mismatch_count}")
    lines.append(f"- no_reference: {no_reference_count}")
    lines.append(f"- skipped_non_numeric: {skipped_count}")
    lines.append(f"- total_snapshot_fields: {len(comparisons)}")
    return "\n".join(lines)


def _write_reports(timeframe: str, report: Dict[str, Any], markdown: str) -> Tuple[Path, Path]:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = LOG_DIR / f"tradingview_crosscheck_{timeframe}_{stamp}.json"
    md_path = LOG_DIR / f"tradingview_crosscheck_{timeframe}_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    md_path.write_text(markdown, encoding="utf-8")
    return json_path, md_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Cross-check local metrics against external sources")
    parser.add_argument("--timeframe", choices=["current", "week", "month"], default="month")
    parser.add_argument("--fresh", action="store_true", help="Force fresh analysis before cross-check")
    args = parser.parse_args()

    run_started_at = _iso_now()
    snapshot = run_analysis(timeframe=args.timeframe, fresh=args.fresh)

    comparisons: List[Dict[str, Any]] = []
    for snapshot_field in sorted(snapshot.keys()):
        comparisons.append(
            _crosscheck_snapshot_field(
                snapshot_field=snapshot_field,
                local_value=snapshot.get(snapshot_field),
                timeframe=args.timeframe,
            )
        )

    run_finished_at = _iso_now()
    report = {
        "generated_at_utc": run_finished_at,
        "timeframe": args.timeframe,
        "reference_policy": "TradingView first; reliable-source fallback (FRED/BLS/TradingEconomics/FMP/EODHD/CoinGecko/exchange APIs)",
        "run_started_at_utc": run_started_at,
        "run_finished_at_utc": run_finished_at,
        "local_snapshot": {
            "final_score": snapshot.get("final_score"),
            "bias": snapshot.get("bias"),
            "confidence_pct": snapshot.get("confidence_pct"),
        },
        "comparisons": comparisons,
        "thresholds": {
            "market_rel_match_pct": MARKET_REL_MATCH_PCT,
            "market_rel_warn_pct": MARKET_REL_WARN_PCT,
            "macro_rel_match_pct": MACRO_REL_MATCH_PCT,
            "macro_rel_warn_pct": MACRO_REL_WARN_PCT,
            "pmi_abs_match": PMI_ABS_MATCH,
            "pmi_abs_warn": PMI_ABS_WARN,
        },
    }

    markdown = _build_markdown(
        timeframe=args.timeframe,
        run_started_at=run_started_at,
        run_finished_at=run_finished_at,
        snapshot=snapshot,
        comparisons=comparisons,
    )

    json_path, md_path = _write_reports(args.timeframe, report, markdown)

    mismatches = sum(1 for row in comparisons if row["status"] == "mismatch")
    warnings = sum(1 for row in comparisons if row["status"] == "warning")
    matches = sum(1 for row in comparisons if row["status"] == "match")
    no_reference = sum(1 for row in comparisons if row["status"] == "no_reference")
    skipped = sum(1 for row in comparisons if row["status"] == "skipped_non_numeric")

    print("External cross-check complete")
    print(
        "timeframe="
        f"{args.timeframe} matches={matches} warnings={warnings} mismatches={mismatches} "
        f"no_reference={no_reference} skipped_non_numeric={skipped} total={len(comparisons)}"
    )
    print(f"json_report={json_path}")
    print(f"markdown_report={md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
