"""Trusted market data provider adapters.

This module provides thin, optional wrappers around paid APIs so fetchers can
use deterministic fallbacks without hard-coding provider-specific JSON in many
places.

Providers currently supported:
- Financial Modeling Prep (FMP)
- EODHD
- TradingEconomics

All functions are best-effort and return ``None`` / empty structures when keys
are missing or providers fail.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, Optional, Sequence
from urllib.parse import quote

import requests

logger = logging.getLogger("btc_macro.data_fetchers.trusted_apis")

_FMP_BASE_URL = "https://financialmodelingprep.com/stable"
_EODHD_BASE_URL = "https://eodhd.com/api"
_TE_BASE_URL = "https://api.tradingeconomics.com"

_DEFAULT_TIMEOUT = 15
_HEADERS = {
    "User-Agent": "ZentraMacro/1.0",
    "Accept": "application/json",
}


def _safe_float(value: Any) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out:  # NaN guard
        return None
    return out


def _date_from_epoch(value: Any) -> Optional[str]:
    ts = _safe_float(value)
    if ts is None or ts <= 0:
        return None
    try:
        return datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")
    except Exception:
        return None


def _date_from_any(value: Any) -> Optional[str]:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None

    # TradingEconomics can return /Date(1714502400000)/
    ms_match = re.search(r"/Date\((\d+)\)/", raw)
    if ms_match:
        try:
            return datetime.utcfromtimestamp(int(ms_match.group(1)) / 1000.0).strftime("%Y-%m-%d")
        except Exception:
            pass

    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).strftime("%Y-%m-%d")
    except Exception:
        pass

    # Fallback for strings that begin with YYYY-MM-DD
    return raw[:10]


def _request_json(url: str, *, params: Optional[Dict[str, Any]] = None, timeout: int = _DEFAULT_TIMEOUT) -> Any:
    resp = requests.get(url, params=params, timeout=timeout, headers=_HEADERS)
    resp.raise_for_status()
    return resp.json()


def _fmp_key() -> str:
    return (os.getenv("FMP_API_KEY") or "").strip()


def _eodhd_token() -> str:
    return (os.getenv("EODHD_API_TOKEN") or "").strip()


def _te_credential() -> str:
    # TradingEconomics credential format is typically "user:password".
    # Guest is kept as a convenience fallback for limited access endpoints.
    return (os.getenv("TRADINGECONOMICS_API_KEY") or "guest:guest").strip()


def get_fmp_quote(symbol: str) -> Optional[Dict[str, Any]]:
    key = _fmp_key()
    if not key:
        return None
    try:
        data = _request_json(
            f"{_FMP_BASE_URL}/quote",
            params={"symbol": symbol, "apikey": key},
        )
        row = data[0] if isinstance(data, list) and data else None
        if not isinstance(row, dict):
            return None

        price = _safe_float(row.get("price"))
        if price is None:
            return None

        # FMP returns changePercentage as percentage points (e.g., 0.11354).
        change_pct = _safe_float(row.get("changePercentage"))
        change_pts = _safe_float(row.get("change"))
        volume = _safe_float(row.get("volume"))
        dt = _date_from_epoch(row.get("timestamp")) or datetime.utcnow().strftime("%Y-%m-%d")

        return {
            "symbol": str(row.get("symbol") or symbol),
            "price": price,
            "change_percent": change_pct,
            "change_points": change_pts,
            "volume": int(volume) if volume is not None else None,
            "date": dt,
            "source": f"FMP:{str(row.get('symbol') or symbol)}",
        }
    except Exception as e:
        logger.debug("FMP quote failed for %s: %s", symbol, e)
        return None


def get_fmp_batch_quotes(symbols: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    key = _fmp_key()
    if not key:
        return {}
    cleaned = [str(s).strip() for s in symbols if str(s).strip()]
    if not cleaned:
        return {}

    try:
        data = _request_json(
            f"{_FMP_BASE_URL}/batch-quote",
            params={"symbols": ",".join(cleaned), "apikey": key},
        )
        if not isinstance(data, list):
            return {}

        out: Dict[str, Dict[str, Any]] = {}
        for row in data:
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("symbol") or "").strip()
            if not symbol:
                continue
            price = _safe_float(row.get("price"))
            volume = _safe_float(row.get("volume"))
            if price is None and volume is None:
                continue
            out[symbol.upper()] = {
                "symbol": symbol,
                "price": price,
                "change_percent": _safe_float(row.get("changePercentage")),
                "change_points": _safe_float(row.get("change")),
                "volume": int(volume) if volume is not None else None,
                "date": _date_from_epoch(row.get("timestamp")) or datetime.utcnow().strftime("%Y-%m-%d"),
                "source": f"FMP:{symbol}",
            }
        return out
    except Exception as e:
        logger.debug("FMP batch quote failed: %s", e)
        return {}


def get_tradingeconomics_quote_from_search(
    query: str,
    *,
    preferred_symbol: Optional[str] = None,
    preferred_ticker: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    cred = _te_credential()
    if not cred:
        return None

    url = f"{_TE_BASE_URL}/markets/search/{quote(query)}"
    try:
        rows = _request_json(url, params={"c": cred})
        if not isinstance(rows, list) or not rows:
            return None

        picked: Optional[Dict[str, Any]] = None
        preferred_symbol_up = (preferred_symbol or "").upper()
        preferred_ticker_up = (preferred_ticker or "").upper()

        for row in rows:
            if not isinstance(row, dict):
                continue
            sym = str(row.get("Symbol") or "")
            tkr = str(row.get("Ticker") or "")
            if preferred_symbol_up and sym.upper() == preferred_symbol_up:
                picked = row
                break
            if preferred_ticker_up and tkr.upper() == preferred_ticker_up:
                picked = row
                break
            if picked is None:
                picked = row

        if not isinstance(picked, dict):
            return None

        last = _safe_float(picked.get("Last"))
        if last is None:
            return None

        change_pts = _safe_float(picked.get("DailyChange"))
        change_pct = _safe_float(picked.get("DailyPercentualChange"))
        if change_pts is None:
            prev = _safe_float(picked.get("Yesterday") or picked.get("Close"))
            if prev is not None:
                change_pts = last - prev
                if change_pct is None and prev != 0:
                    change_pct = ((last - prev) / prev) * 100.0

        symbol = str(picked.get("Symbol") or preferred_symbol or query)
        date_raw = str(picked.get("Date") or "").strip()
        date = date_raw[:10] if date_raw else datetime.utcnow().strftime("%Y-%m-%d")

        return {
            "symbol": symbol,
            "price": last,
            "change_percent": change_pct,
            "change_points": change_pts,
            "volume": None,
            "date": date,
            "source": f"TradingEconomics:{symbol}",
        }
    except Exception as e:
        logger.debug("TradingEconomics search quote failed for '%s': %s", query, e)
        return None


def _eodhd_normalize_symbol(code: str, exchange: Optional[str]) -> str:
    c = (code or "").strip()
    ex = (exchange or "").strip()
    if not c:
        return ""
    if "." in c:
        return c
    if ex:
        return f"{c}.{ex}"
    return c


def get_eodhd_quote_from_search(query: str, *, asset_type: str = "index") -> Optional[Dict[str, Any]]:
    token = _eodhd_token()
    if not token:
        return None

    try:
        rows = _request_json(
            f"{_EODHD_BASE_URL}/search/{quote(query)}",
            params={
                "api_token": token,
                "fmt": "json",
                "type": asset_type,
                "limit": 10,
            },
        )
        if not isinstance(rows, list) or not rows:
            return None
    except Exception as e:
        logger.debug("EODHD search failed for '%s': %s", query, e)
        return None

    for row in rows:
        if not isinstance(row, dict):
            continue
        code = str(row.get("Code") or "").strip()
        exchange = str(row.get("Exchange") or "").strip()
        symbol = _eodhd_normalize_symbol(code, exchange)
        if not symbol:
            continue

        try:
            rt = _request_json(
                f"{_EODHD_BASE_URL}/real-time/{quote(symbol)}",
                params={"api_token": token, "fmt": "json"},
            )
            if not isinstance(rt, dict):
                continue
            price = _safe_float(rt.get("close") or rt.get("price") or rt.get("last"))
            if price is None:
                continue
            prev = _safe_float(rt.get("previousClose"))
            change_pts = _safe_float(rt.get("change"))
            change_pct = _safe_float(rt.get("change_p"))
            if change_pts is None and prev is not None:
                change_pts = price - prev
            if change_pct is None and prev not in (None, 0):
                change_pct = ((price - prev) / prev) * 100.0

            dt = _date_from_epoch(rt.get("timestamp")) or datetime.utcnow().strftime("%Y-%m-%d")
            vol = _safe_float(rt.get("volume"))
            return {
                "symbol": symbol,
                "price": price,
                "change_percent": change_pct,
                "change_points": change_pts,
                "volume": int(vol) if vol is not None else None,
                "date": dt,
                "source": f"EODHD:{symbol}",
            }
        except Exception as e:
            logger.debug("EODHD real-time fetch failed for %s: %s", symbol, e)
            continue

    return None


def get_tradingeconomics_us_manufacturing_pmi() -> Optional[Dict[str, Any]]:
    cred = _te_credential()
    if not cred:
        return None

    indicators = ("manufacturing pmi", "ism manufacturing pmi")
    for indicator in indicators:
        try:
            rows = _request_json(
                f"{_TE_BASE_URL}/historical/country/united%20states/indicator/{quote(indicator)}",
                params={"c": cred},
            )
            if not isinstance(rows, list) or not rows:
                continue

            points = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                value = _safe_float(row.get("Value") or row.get("LatestValue") or row.get("Last"))
                if value is None:
                    continue
                date = _date_from_any(row.get("DateTime") or row.get("Date") or row.get("LastUpdate"))
                previous = _safe_float(row.get("PreviousValue") or row.get("Previous"))
                points.append((date or "", value, previous))

            if not points:
                continue

            points.sort(key=lambda x: x[0])
            latest_date, latest_value, previous_value = points[-1]
            return {
                "pmi_value": latest_value,
                "previous_value": previous_value,
                "date": latest_date or datetime.utcnow().strftime("%Y-%m-%d"),
                "source": "TradingEconomics:US:Manufacturing PMI",
            }
        except Exception as e:
            logger.debug("TradingEconomics PMI failed for '%s': %s", indicator, e)
            continue

    return None


def get_eodhd_us_manufacturing_pmi() -> Optional[Dict[str, Any]]:
    token = _eodhd_token()
    if not token:
        return None

    countries = ("USA", "US")
    indicators = ("manufacturing_pmi", "ism_manufacturing_pmi", "pmi")
    for country in countries:
        for indicator in indicators:
            try:
                rows = _request_json(
                    f"{_EODHD_BASE_URL}/macro-indicator/{country}",
                    params={
                        "api_token": token,
                        "fmt": "json",
                        "indicator": indicator,
                        "limit": 20,
                    },
                )
            except Exception as e:
                logger.debug("EODHD PMI request failed (%s/%s): %s", country, indicator, e)
                continue

            entries = rows if isinstance(rows, list) else [rows] if isinstance(rows, dict) else []
            points = []
            for row in entries:
                if not isinstance(row, dict):
                    continue
                value = _safe_float(
                    row.get("Value")
                    if row.get("Value") is not None
                    else row.get("value")
                    if row.get("value") is not None
                    else row.get("close")
                )
                if value is None:
                    continue
                date = _date_from_any(row.get("Date") or row.get("date") or row.get("Timestamp"))
                previous = _safe_float(row.get("Previous") or row.get("previous") or row.get("PreviousValue"))
                points.append((date or "", value, previous))

            if not points:
                continue

            points.sort(key=lambda x: x[0])
            latest_date, latest_value, previous_value = points[-1]
            return {
                "pmi_value": latest_value,
                "previous_value": previous_value,
                "date": latest_date or datetime.utcnow().strftime("%Y-%m-%d"),
                "source": f"EODHD:{country}:{indicator}",
            }

    return None
