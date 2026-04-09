"""Fetch market data from Yahoo Finance using yfinance.

This module includes lightweight validation and logging for DXY to
detect suspect values and enable fallbacks.

Unlike news/LLM steps, live market prices should remain uncached so the
client sees the most recent DXY, VIX, S&P 500, and Gold values on each
analysis run.
"""
import logging
import math
import time
import os
from io import StringIO
import yfinance as yf
import pandas as pd
import requests
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple
import json
from pathlib import Path
from utils.http_retry import get_with_retries

try:
    from . import trusted_market_apis
except Exception:
    trusted_market_apis = None

logger = logging.getLogger("btc_macro.data_fetchers.yahoo")

# Load data validation config (fallbacks, tolerances)
try:
    cfg_path = Path(__file__).parent.parent / "config" / "data_validation.json"
    _CFG = json.loads(cfg_path.read_text()) if cfg_path.exists() else {}
except Exception:
    _CFG = {}

# DXY tolerance: 0.05 = 5% relative difference. DX-Y.NYB vs UUP naturally differ ~2-4%
# because UUP is an ETF with a different NAV scale. We only flag egregious divergences.
DXY_VALIDATION_TOLERANCE_PCT = float(_CFG.get("dxy_tolerance_pct", 0.05))
FALLBACK_MAX_SNAPSHOT_AGE_HOURS = int(_CFG.get("fallback_max_snapshot_age_hours", 48))
USE_LAST_SNAPSHOT_FOR_FALLBACK = bool(_CFG.get("use_last_snapshot_for_fallback", True))
STRICT_LIVE_OFFICIAL_ONLY = os.getenv("STRICT_LIVE_OFFICIAL_ONLY", "0").strip().lower() not in {"0", "false", "no"}
ECB_API_BASE_URL = "https://data-api.ecb.europa.eu/service/data/EXR"
LBMA_TODAY_URL = "https://prices.lbma.org.uk/json/today.json"
TRADINGVIEW_SCANNER_URL = "https://scanner.tradingview.com/america/scan"
CBOE_TYVIX_CSV_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/TYVIX_History.csv"


def _safe_date_str(ts) -> str:
    """Safely convert a pandas Timestamp (possibly tz-aware) to YYYY-MM-DD string"""
    try:
        if hasattr(ts, 'strftime'):
            return ts.strftime("%Y-%m-%d")
        return str(ts)[:10]
    except Exception:
        return datetime.now().strftime("%Y-%m-%d")


def _safe_iso(ts) -> Optional[str]:
    """Return ISO-8601 string for observation timestamps (date or datetime)."""
    if ts is None:
        return None
    try:
        if hasattr(ts, "to_pydatetime"):
            return ts.to_pydatetime().isoformat()
        if hasattr(ts, "isoformat"):
            return ts.isoformat()
        return str(ts)
    except Exception:
        return None


def _with_obs_fetch(payload: Dict[str, Any], observation_ts) -> Dict[str, Any]:
    """Attach observation and fetch timestamps for auditing."""
    result = dict(payload)
    result["observed_at"] = _safe_iso(observation_ts)
    result["fetched_at"] = datetime.utcnow().isoformat()
    return result


def _get_latest_snapshot():
    """Best-effort latest snapshot fetch for fallback values."""
    try:
        from storage.db import get_latest_snapshots
        snaps = get_latest_snapshots(1)
        if snaps:
            return snaps[0]
    except Exception:
        logger.exception("Failed to fetch latest snapshot")
    return None


def _fresh_snapshot_value(field_name: str) -> Optional[Tuple[float, Optional[str]]]:
    """Recent snapshot scalar fallback for display-only metrics."""
    snap = _get_latest_snapshot()
    if not snap:
        return None
    value = snap.get(field_name)
    if value is None:
        return None
    timestamp = snap.get("timestamp")
    try:
        snap_time = datetime.fromisoformat(str(timestamp))
        age_hours = (datetime.now() - snap_time).total_seconds() / 3600.0
    except Exception:
        age_hours = float("inf")
    if age_hours > FALLBACK_MAX_SNAPSHOT_AGE_HOURS:
        return None
    try:
        return float(value), (str(timestamp) if timestamp else None)
    except (TypeError, ValueError):
        return None


def _snapshot_baseline_for_timeframe(field_name: str, timeframe: str) -> Optional[Tuple[float, Optional[str]]]:
    """Return snapshot baseline nearest to the requested timeframe window.

    This keeps fallback %/point changes aligned with current/week/month/year
    semantics instead of reusing a same-day delta for all timeframes.
    """
    days_by_timeframe = {
        "current": 1,
        "week": 7,
        "month": 30,
        "year": 365,
    }
    target_days = days_by_timeframe.get(timeframe, 1)
    try:
        from storage.db import get_latest_snapshots

        rows = get_latest_snapshots(limit=420)
    except Exception:
        logger.exception("Failed to read snapshot baseline for %s", field_name)
        return None

    if not rows:
        return None

    now = datetime.now()
    target_dt = now - timedelta(days=target_days)
    fallback_latest: Optional[Tuple[float, Optional[str]]] = None

    for row in rows:
        if not isinstance(row, dict):
            continue
        raw_value = row.get(field_name)
        raw_ts = row.get("timestamp")
        if raw_value is None or raw_ts is None:
            continue

        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value):
            continue

        ts_text = str(raw_ts)
        try:
            ts = datetime.fromisoformat(ts_text)
        except Exception:
            continue

        if fallback_latest is None:
            fallback_latest = (value, ts_text)

        if ts <= target_dt:
            return value, ts_text

    return fallback_latest


# Timeframe to period mapping for yfinance
TIMEFRAME_PERIODS = {
    "current": "1mo",
    "week": "1mo",
    "month": "3mo",
    "year": "2y"
}

# Timeframe to comparison days (calendar days — not trading sessions).
# "month" is handled separately as a rolling 1-calendar-month window.
TIMEFRAME_COMPARISON = {
    "current": 1,
    "week": 7,
    "year": 365,
}

# Human-readable label for each timeframe's change window shown in the UI.
_CHANGE_LABELS: Dict[str, str] = {
    "current": "1D",
    "week": "7D",
    "month": "1M",
    "year": "1Y",
}


def _change_label(timeframe: str) -> str:
    return _CHANGE_LABELS.get(timeframe, "")


def _normalize_hist_index(hist: pd.DataFrame) -> pd.DataFrame:
    """Timezone-naive DatetimeIndex for reliable calendar arithmetic."""
    h = hist.copy()
    idx = pd.to_datetime(hist.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    h.index = idx
    return h


def _latest_and_comparison_rows(
    hist: pd.DataFrame,
    calendar_days: int,
    *,
    months_offset: Optional[int] = None,
) -> Tuple[pd.Series, pd.Series]:
    """Pick comparison bar as last row on or before the cutoff date.

    - Default: cutoff = latest_date − calendar_days (day-based window).
    - If months_offset is set: cutoff = latest_date − that many *calendar* months
      (pandas DateOffset), aligning with common "1M" views (e.g. Google Finance)
      instead of a flat 30-day window (which skews % change by ~2 days).

    Normalizes to date-only to avoid DST hour offsets on the index.
    """
    h = _normalize_hist_index(hist)
    if h.empty:
        raise ValueError("empty history")
    latest = h.iloc[-1]
    latest_date = h.index[-1].normalize()  # midnight
    if months_offset is not None and months_offset > 0:
        cutoff_date = (latest_date - pd.DateOffset(months=int(months_offset))).normalize()
    else:
        days = max(1, int(calendar_days))
        cutoff_date = latest_date - pd.Timedelta(days=days)
    past = h[h.index.normalize() <= cutoff_date]
    if past.empty:
        comparison = h.iloc[0]
    else:
        comparison = past.iloc[-1]
    return latest, comparison


def _mtd_comparison_row(hist: pd.DataFrame) -> pd.Series:
    """Legacy helper for month-to-date anchor selection.

    The active `month` timeframe uses a rolling 1-calendar-month window instead.
    """
    h = _normalize_hist_index(hist)
    if h.empty:
        raise ValueError("empty history")
    latest_date = h.index[-1].normalize()
    # First calendar day of the current month at midnight
    month_start = latest_date.to_period("M").to_timestamp().normalize()
    this_month = h[h.index.normalize() >= month_start]
    if this_month.empty:
        return h.iloc[0]
    first_bar = this_month.iloc[0]
    # If the first bar IS the latest bar (i.e. today is the very first trading
    # day of the month), there is no MTD history yet — fall back to prior month's
    # last bar so we return a meaningful 0% change rather than dividing by itself.
    if first_bar.name == h.index[-1]:
        prev = h[h.index.normalize() < month_start]
        return prev.iloc[-1] if not prev.empty else first_bar
    return first_bar


def _dxy_rolling_1m_fields(hist: pd.DataFrame) -> Optional[Dict[str, Any]]:
    """Rolling ~1 calendar month % change (latest vs last bar on/before latest−1M).

    Aligns with common '1M' chart windows (TradingView-style rolling month),
    distinct from MTD (first session of current month).
    """
    h = _normalize_hist_index(hist)
    if len(h) < 2:
        return None
    try:
        latest, comparison = _latest_and_comparison_rows(h, 1, months_offset=1)
        cp = float(latest["Close"])
        op = float(comparison["Close"])
        if not math.isfinite(cp) or not math.isfinite(op) or op <= 0:
            return None
        chg = ((cp - op) / op) * 100.0
        return {
            "change_rolling_1m": round(chg, 2),
            "change_rolling_1m_label": "1M",
            "comparison_date_rolling_1m": _safe_date_str(comparison.name),
        }
    except Exception:
        return None


def _dxy_rolling_1m_fields_eurusd_proxy(hist: pd.DataFrame) -> Optional[Dict[str, Any]]:
    """Same window as _dxy_rolling_1m_fields using EURUSD-derived proxy level math.

    Compute percentage from proxy levels directly so displayed level and change are consistent.
    """
    h = _normalize_hist_index(hist)
    if len(h) < 2:
        return None
    try:
        latest, comparison = _latest_and_comparison_rows(h, 1, months_offset=1)
        e0 = float(latest["Close"])
        e1 = float(comparison["Close"])
        if not math.isfinite(e0) or not math.isfinite(e1):
            return None
        level_latest = max(85.0, min(115.0, 100.0 + (1.085 - e0) * 85.0))
        level_comparison = max(85.0, min(115.0, 100.0 + (1.085 - e1) * 85.0))
        if not math.isfinite(level_comparison) or level_comparison <= 0:
            return None
        dxy_chg = ((level_latest - level_comparison) / level_comparison) * 100.0
        return {
            "change_rolling_1m": round(dxy_chg, 2),
            "change_rolling_1m_label": "1M",
            "comparison_date_rolling_1m": _safe_date_str(comparison.name),
        }
    except Exception:
        return None


def _latest_and_comparison_for_timeframe(
    hist: pd.DataFrame, timeframe: str, *, default_days: int = 7
) -> Tuple[pd.Series, pd.Series]:
    """Latest row + comparison row for Yahoo %/point change helpers."""
    if len(hist) <= 1:
        row = hist.iloc[-1]
        return row, row
    if timeframe == "month":
        return _latest_and_comparison_rows(hist, 1, months_offset=1)
    days = TIMEFRAME_COMPARISON.get(timeframe, default_days)
    return _latest_and_comparison_rows(hist, days)


def _dxy_from_eurusd_proxy(timeframe: str) -> Optional[Dict]:
    """Approximate DXY change/level from EURUSD=X when DXY futures fail (e.g. cloud yfinance)."""
    try:
        ticker = yf.Ticker("EURUSD=X")
        period = TIMEFRAME_PERIODS.get(timeframe, "3mo")
        hist = ticker.history(period=period)
        if hist.empty or len(hist) < 2:
            return None
        if len(hist) > 1:
            latest, comparison = _latest_and_comparison_for_timeframe(hist, timeframe)
        else:
            latest = hist.iloc[-1]
            comparison = latest
        e0 = float(latest["Close"])
        e1 = float(comparison["Close"])
        if not math.isfinite(e0) or not math.isfinite(e1):
            return None
        level_proxy = max(85.0, min(115.0, 100.0 + (1.085 - e0) * 85.0))
        level_proxy_comparison = max(85.0, min(115.0, 100.0 + (1.085 - e1) * 85.0))
        if not math.isfinite(level_proxy_comparison) or level_proxy_comparison <= 0:
            return None
        dxy_change_proxy = ((level_proxy - level_proxy_comparison) / level_proxy_comparison) * 100.0
        out = {
            "current_price": round(level_proxy, 2),
            "date": _safe_date_str(latest.name),
            "data_as_of": _safe_date_str(latest.name),
            "comparison_date": _safe_date_str(comparison.name),
            "change": round(dxy_change_proxy, 2),
            "change_label": _change_label(timeframe),
            "change_unit": "percent",
            "trend": "weakening" if dxy_change_proxy < 0 else "strengthening" if dxy_change_proxy > 0 else "stable",
            "timeframe": timeframe,
            "source": "EURUSD=X_proxy",
            "_fallback": True,
        }
        roll = _dxy_rolling_1m_fields_eurusd_proxy(hist)
        if roll:
            out.update(roll)
        return out
    except Exception as e:
        logger.debug("EURUSD DXY proxy failed: %s", e)
        return None


def _dxy_from_fx_basket(timeframe: str) -> Optional[Dict]:
    """Exact DXY basket from the six constituent FX pairs when direct DXY symbols fail."""
    fx_symbols = {
        "eurusd": "EURUSD=X",
        "usdjpy": "JPY=X",
        "gbpusd": "GBPUSD=X",
        "usdcad": "CAD=X",
        "usdsek": "SEK=X",
        "usdchf": "CHF=X",
    }
    weights = {
        "eurusd": -0.576,
        "usdjpy": 0.136,
        "gbpusd": -0.119,
        "usdcad": 0.091,
        "usdsek": 0.042,
        "usdchf": 0.036,
    }
    base = 50.14348112

    try:
        joined: Optional[pd.DataFrame] = None
        for key, symbol in fx_symbols.items():
            ticker = yf.Ticker(symbol)
            hist = _yf_history_with_backoff(ticker, TIMEFRAME_PERIODS.get(timeframe, "3mo"), attempts=2)
            if hist is None or hist.empty:
                return None
            h = _normalize_hist_index(hist)[["Close"]].rename(columns={"Close": key})
            joined = h if joined is None else joined.join(h, how="inner")

        if joined is None or joined.empty or len(joined) < 2:
            return None

        joined = joined.dropna()
        if joined.empty:
            return None

        dxy_close = pd.Series(base, index=joined.index, dtype="float64")
        for key, weight in weights.items():
            vals = joined[key].astype(float)
            if (vals <= 0).any():
                return None
            dxy_close = dxy_close * vals.pow(weight)

        dxy_hist = pd.DataFrame({"Close": dxy_close}).dropna()
        if dxy_hist.empty:
            return None

        if len(dxy_hist) > 1:
            latest, comparison = _latest_and_comparison_for_timeframe(dxy_hist, timeframe)
        else:
            latest = dxy_hist.iloc[-1]
            comparison = latest

        current_price = float(latest["Close"])
        comparison_price = float(comparison["Close"])
        if not math.isfinite(current_price) or current_price <= 0:
            return None
        if not math.isfinite(comparison_price) or comparison_price <= 0:
            comparison_price = current_price

        change = ((current_price - comparison_price) / comparison_price) * 100 if comparison_price else 0.0
        out = {
            "current_price": round(current_price, 2),
            "date": _safe_date_str(latest.name),
            "data_as_of": _safe_date_str(latest.name),
            "comparison_date": _safe_date_str(comparison.name),
            "change": round(change, 2),
            "change_label": _change_label(timeframe),
            "change_unit": "percent",
            "trend": "weakening" if change < 0 else "strengthening" if change > 0 else "stable",
            "timeframe": timeframe,
            "source": "fx_basket_formula",
            "_fallback": True,
        }
        roll = _dxy_rolling_1m_fields(dxy_hist)
        if roll:
            out.update(roll)
        return out
    except Exception as e:
        logger.debug("FX basket DXY fallback failed: %s", e)
        return None


def _ecb_fx_series(currency: str, start_date: str) -> pd.DataFrame:
    series_key = f"D.{currency}.EUR.SP00.A"
    resp = get_with_retries(
        f"{ECB_API_BASE_URL}/{series_key}",
        params={"format": "csvdata", "startPeriod": start_date},
        headers={"Accept": "text/csv"},
        timeout=20,
    )
    df = pd.read_csv(StringIO(resp.text))
    if df.empty or "TIME_PERIOD" not in df.columns or "OBS_VALUE" not in df.columns:
        return pd.DataFrame()
    out = pd.DataFrame(
        {
            "date": pd.to_datetime(df["TIME_PERIOD"], errors="coerce"),
            currency.lower(): pd.to_numeric(df["OBS_VALUE"], errors="coerce"),
        }
    ).dropna()
    return out


def _ecb_dxy_history(timeframe: str, *, lookback_days: Optional[int] = None) -> pd.DataFrame:
    """Build a DXY-like daily history from ECB reference FX rates."""
    currencies = ("USD", "JPY", "GBP", "CAD", "SEK", "CHF")
    lookback_days = lookback_days or {"current": 45, "week": 60, "month": 120, "year": 420}.get(timeframe, 120)
    start_date = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    joined: Optional[pd.DataFrame] = None
    base = 50.14348112
    weights = {
        "eurusd": -0.576,
        "usdjpy": 0.136,
        "gbpusd": -0.119,
        "usdcad": 0.091,
        "usdsek": 0.042,
        "usdchf": 0.036,
    }
    for cur in currencies:
        df = _ecb_fx_series(cur, start_date)
        if df.empty:
            return pd.DataFrame()
        joined = df if joined is None else joined.merge(df, on="date", how="inner")
    if joined is None or joined.empty or len(joined) < 2:
        return pd.DataFrame()
    joined = joined.sort_values("date").dropna().reset_index(drop=True)
    if joined.empty:
        return pd.DataFrame()

    usd_eur = joined["usd"].astype(float)
    eurusd = usd_eur
    usdjpy = joined["jpy"].astype(float) / usd_eur
    gbpusd = usd_eur / joined["gbp"].astype(float)
    usdcad = joined["cad"].astype(float) / usd_eur
    usdsek = joined["sek"].astype(float) / usd_eur
    usdchf = joined["chf"].astype(float) / usd_eur
    dxy_close = (
        base
        * eurusd.pow(weights["eurusd"])
        * usdjpy.pow(weights["usdjpy"])
        * gbpusd.pow(weights["gbpusd"])
        * usdcad.pow(weights["usdcad"])
        * usdsek.pow(weights["usdsek"])
        * usdchf.pow(weights["usdchf"])
    )
    return pd.DataFrame({"Close": dxy_close.values}, index=pd.to_datetime(joined["date"]))


def _dxy_from_ecb_fx_basket(timeframe: str) -> Optional[Dict]:
    """Approximate official DXY from ECB daily FX reference rates."""
    try:
        dxy_hist = _ecb_dxy_history(timeframe)
        if dxy_hist.empty:
            return None
        latest, comparison = _latest_and_comparison_for_timeframe(dxy_hist, timeframe)
        current_price = float(latest["Close"])
        comparison_price = float(comparison["Close"])
        change = ((current_price - comparison_price) / comparison_price) * 100 if comparison_price else 0.0
        out = {
            "current_price": round(current_price, 2),
            "date": _safe_date_str(latest.name),
            "data_as_of": _safe_date_str(latest.name),
            "comparison_date": _safe_date_str(comparison.name),
            "change": round(change, 2),
            "change_label": _change_label(timeframe),
            "change_unit": "percent",
            "trend": "weakening" if change < 0 else "strengthening" if change > 0 else "stable",
            "timeframe": timeframe,
            "source": "ECB:EXR_fx_basket",
            "_fallback": True,
        }
        roll = _dxy_rolling_1m_fields(dxy_hist)
        if roll:
            out.update(roll)
        return out
    except Exception as e:
        logger.debug("ECB DXY basket fallback failed: %s", e)
        return None


def _lbma_gold_data(timeframe: str) -> Optional[Dict]:
    """LBMA official gold price feed."""
    try:
        resp = get_with_retries(LBMA_TODAY_URL, timeout=20)
        payload = resp.json()
        gold = payload.get("gold") or {}
        gold_leg = gold.get("pm") or gold.get("am") or {}
        current_price = float(gold_leg.get("usd"))
        date_text = str(gold_leg.get("date") or "").strip()
        date_value = datetime.now().strftime("%Y-%m-%d")
        if date_text:
            try:
                parsed = datetime.strptime(f"{date_text}/{datetime.now().year}", "%d/%m/%Y")
                date_value = parsed.strftime("%Y-%m-%d")
            except ValueError:
                pass

        comparison_price = None
        comparison_date = None
        week_values = gold.get("week") or []
        week_labels = gold.get("weekLabel") or []
        normalized_week = []
        for item in week_values:
            if isinstance(item, dict):
                val = item.get("y")
            else:
                val = item
            try:
                normalized_week.append(float(val))
            except (TypeError, ValueError):
                continue

        if timeframe == "current":
            if normalized_week:
                comparison_price = normalized_week[-1]
                if week_labels:
                    comparison_date = str(week_labels[-1])
        elif timeframe == "week":
            if len(normalized_week) >= 2:
                comparison_price = normalized_week[0]
                if week_labels:
                    comparison_date = str(week_labels[0])

        change = None
        trend = "stable"
        if comparison_price and comparison_price > 0:
            change = ((current_price - comparison_price) / comparison_price) * 100.0
            trend = "rising" if change > 0 else "falling" if change < 0 else "stable"

        return {
            "current_price": round(current_price, 2),
            "date": date_value,
            "data_as_of": date_value,
            "comparison_date": comparison_date,
            "change": round(change, 2) if change is not None else None,
            "change_label": _change_label(timeframe),
            "change_unit": "percent",
            "trend": trend,
            "timeframe": timeframe,
            "source": "LBMA:today.json",
        }
    except Exception as e:
        logger.debug("LBMA gold fetch failed: %s", e)
        return None


def _yahoo_gold_pct_change_overlay(timeframe: str) -> Optional[Dict[str, Any]]:
    """Use Yahoo spot/futures history for % change when LBMA (or other) left change unset."""
    try:
        symbol, hist = _select_same_scale_yahoo_history(("XAUUSD=X", "GC=F"), timeframe)
        if hist.empty or len(hist) < 2:
            return None
        latest, comparison = _latest_and_comparison_for_timeframe(hist, timeframe)
        c0 = float(latest["Close"])
        c1 = float(comparison["Close"])
        if not c1:
            return None
        ch = ((c0 - c1) / c1) * 100.0
        return {
            "change": round(ch, 2),
            "comparison_date": _safe_date_str(comparison.name),
            "change_label": _change_label(timeframe),
            "trend": "rising" if ch > 0.05 else "falling" if ch < -0.05 else "stable",
            "symbol": symbol,
        }
    except Exception:
        logger.debug("Yahoo gold % overlay failed", exc_info=True)
        return None


def _fred_gold_month_percent_lbma_augment() -> Optional[Dict[str, Any]]:
    """1M % from FRED LBMA series when Yahoo overlay is unavailable (LBMA spot + official history)."""
    fb = _fred_series_market_fallback(
        "GOLDAMGBD228NLBM",
        "month",
        response_key="current_price",
        change_unit="percent",
        source_name="FRED:GOLDAMGBD228NLBM",
    )
    if not fb:
        return None
    return {
        "symbol": "FRED:GOLDAMGBD228NLBM",
        "change": fb.get("change"),
        "comparison_date": fb.get("comparison_date"),
        "change_label": fb.get("change_label"),
        "trend": fb.get("trend", "stable"),
    }


def _yf_history_with_backoff(ticker: yf.Ticker, period: str, *, attempts: int = 3) -> pd.DataFrame:
    """Fetch history with retries for Yahoo Finance rate limits / transient errors."""
    last_err: Optional[Exception] = None
    for attempt in range(attempts):
        try:
            hist = ticker.history(period=period)
            if hist is not None and not hist.empty:
                return hist
        except Exception as e:
            last_err = e
        msg = str(last_err or "empty history").lower()
        is_rl = "too many requests" in msg or "rate limit" in msg or "429" in msg
        delay = (2.0 * (attempt + 1)) if is_rl else (1.0 * (attempt + 1))
        logger.warning(
            "yfinance history retry for period=%s in %.1fs (attempt %s/%s): %s",
            period,
            delay,
            attempt + 1,
            attempts,
            last_err,
        )
        if attempt < attempts - 1:
            time.sleep(delay)
    return pd.DataFrame()


def _select_same_scale_yahoo_history(
    symbols: Tuple[str, ...],
    timeframe: str,
    *,
    period: str = "3mo",
    attempts: int = 3,
) -> Tuple[Optional[str], pd.DataFrame]:
    """Return the first non-empty Yahoo history from same-scale symbols."""
    hist = pd.DataFrame()
    for symbol in symbols:
        ticker = yf.Ticker(symbol)
        hist = _yf_history_with_backoff(ticker, TIMEFRAME_PERIODS.get(timeframe, period), attempts=attempts)
        if hist is not None and not hist.empty:
            return symbol, hist
    return None, pd.DataFrame()


def _current_intraday_yahoo_metric(
    symbols: Tuple[str, ...],
    *,
    response_key: str = "current_price",
    change_unit: str = "percent",
    trend_up: str = "rising",
    trend_down: str = "falling",
    extra_fields: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Best-effort current intraday quote from Yahoo minute bars."""
    hist = pd.DataFrame()
    symbol_used: Optional[str] = None
    last_err: Optional[Exception] = None

    for symbol in symbols:
        ticker = yf.Ticker(symbol)
        for attempt in range(2):
            try:
                hist = ticker.history(period="5d", interval="1m", prepost=True)
                if hist is not None and not hist.empty:
                    symbol_used = symbol
                    break
            except Exception as e:
                last_err = e
            if attempt < 1:
                time.sleep(1.0 + attempt)
        if symbol_used:
            break

    if hist is None or hist.empty or not symbol_used:
        if last_err:
            logger.debug("Current intraday Yahoo metric failed for %s: %s", symbols, last_err)
        return None

    latest, comparison = _latest_and_comparison_for_timeframe(hist, "current", default_days=1)
    current_value = float(latest["Close"])
    comparison_value = float(comparison["Close"])
    if not math.isfinite(current_value) or current_value <= 0:
        return None
    if not math.isfinite(comparison_value) or comparison_value <= 0:
        comparison_value = current_value

    if change_unit == "points":
        change = current_value - comparison_value
        threshold = 0.1
    else:
        change = ((current_value - comparison_value) / comparison_value) * 100.0 if comparison_value else 0.0
        threshold = 0.05

    payload = {
        response_key: round(current_value, 2),
        "date": _safe_date_str(latest.name),
        "data_as_of": _safe_date_str(latest.name),
        "comparison_date": _safe_date_str(comparison.name),
        "change": round(change, 2),
        "change_label": _change_label("current"),
        "change_unit": change_unit,
        "trend": trend_up if change > threshold else trend_down if change < -threshold else "stable",
        "timeframe": "current",
        "source": symbol_used,
    }
    if extra_fields:
        payload.update(extra_fields)
    return _with_obs_fetch(payload, latest.name)


def _fred_series_market_fallback(
    series_id: str,
    timeframe: str,
    *,
    response_key: str = "current_price",
    change_unit: str = "percent",
    source_name: Optional[str] = None,
    trend_up: str = "rising",
    trend_down: str = "falling",
) -> Optional[Dict[str, Any]]:
    """Free-source fallback for display metrics using daily FRED series."""
    try:
        from data_fetchers import fred_data

        lookback_days = {"current": 45, "week": 60, "month": 120, "year": 500}.get(timeframe, 120)
        start_date = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        df = fred_data.get_fred_data(series_id, start_date=start_date, timeframe=timeframe, sort_order="asc")
        if df.empty:
            return None

        d = df.sort_values("date").reset_index(drop=True)
        latest = d.iloc[-1]
        latest_value = float(latest["value"])
        if not math.isfinite(latest_value) or latest_value <= 0:
            return None

        if timeframe == "month" and len(d) >= 2:
            comparison = fred_data._fred_observation_on_or_before_months_ago(d, 1)
        elif len(d) >= 2:
            comparison = fred_data._fred_observation_on_or_before_calendar_days_ago(
                d, TIMEFRAME_COMPARISON.get(timeframe, 1)
            )
        else:
            comparison = latest

        comparison_value = float(comparison["value"])
        if not math.isfinite(comparison_value) or comparison_value <= 0:
            comparison = latest
            comparison_value = latest_value

        if change_unit == "points":
            change = latest_value - comparison_value
        else:
            change = ((latest_value - comparison_value) / comparison_value) * 100 if comparison_value else 0.0

        def _ds(row: pd.Series) -> str:
            x = row["date"]
            return x.strftime("%Y-%m-%d") if hasattr(x, "strftime") else str(x)[:10]

        return {
            response_key: round(latest_value, 2),
            "date": _ds(latest),
            "data_as_of": _ds(latest),
            "comparison_date": _ds(comparison),
            "change": round(change, 2),
            "change_label": _change_label(timeframe),
            "change_unit": change_unit,
            "trend": trend_down if change < 0 else trend_up if change > 0 else "stable",
            "timeframe": timeframe,
            "source": source_name or f"FRED:{series_id}",
            "_fallback": True,
        }
    except Exception:
        logger.exception("FRED market fallback failed for %s", series_id)
        return None


def try_dxy_external_fallbacks(timeframe: str = "current") -> Optional[Dict]:
    """Try exact FX-basket DXY, then EUR/USD proxy, then FRED trade-weighted USD."""
    ecb = _dxy_from_ecb_fx_basket(timeframe)
    if ecb:
        return ecb
    basket = _dxy_from_fx_basket(timeframe)
    if basket:
        return basket
    eu = _dxy_from_eurusd_proxy(timeframe)
    if eu:
        return eu
    try:
        from data_fetchers import fred_data
        fr = fred_data.get_dxy_from_fred_trade_weighted(timeframe)
        if fr and not fr.get("error"):
            return fr
    except Exception:
        logger.exception("DXY FRED fallback in try_dxy_external_fallbacks")
    return None


def get_dxy_data(timeframe: str = "current") -> Dict:
    """Get US Dollar Index (DXY) data with timeframe support"""
    try:
        if STRICT_LIVE_OFFICIAL_ONLY:
            ecb = _dxy_from_ecb_fx_basket(timeframe)
            if ecb:
                return ecb
            return {"error": "Official DXY FX basket source unavailable", "timeframe": timeframe}

        if timeframe == "current":
            intraday = _current_intraday_yahoo_metric(
                ("DX-Y.NYB", "DX=F", "DXY"),
                response_key="current_price",
                change_unit="percent",
                trend_up="strengthening",
                trend_down="weakening",
            )
            if intraday:
                return intraday
            trusted = _trusted_dxy_fallback(timeframe)
            if trusted:
                return trusted

        # Try multiple DXY ticker symbols as availability varies
        # Preferred order: market DXY futures or index symbols commonly used by yfinance
        symbol, hist = _select_same_scale_yahoo_history(("DX-Y.NYB", "DX=F", "DXY"), timeframe)
        if hist.empty:
            # No live tickers returned. Attempt last-snapshot fallback if configured.
            if USE_LAST_SNAPSHOT_FOR_FALLBACK:
                try:
                    snap_value = _fresh_snapshot_value("dxy_value")
                    if snap_value is not None:
                        dxy_val, timestamp = snap_value
                        logger.warning("Using last snapshot DXY fallback")
                        return {
                            "current_price": dxy_val,
                            "date": str(timestamp)[:10] if timestamp else datetime.now().strftime("%Y-%m-%d"),
                            "data_as_of": timestamp,
                            "comparison_date": (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d"),
                            "change": 0.0,
                            "change_label": _change_label(timeframe),
                            "change_unit": "percent",
                            "trend": "stable",
                            "timeframe": timeframe,
                            "source": "last_snapshot",
                            "_fallback": True,
                            "_fallback_source": "last_snapshot",
                        }
                except Exception:
                    logger.exception("Error attempting last-snapshot fallback for DXY")

            basket = _dxy_from_fx_basket(timeframe)
            if basket:
                logger.warning("DXY: Yahoo index symbols empty; using exact FX basket fallback")
                return basket
            eu = _dxy_from_eurusd_proxy(timeframe)
            if eu:
                logger.warning("DXY: Yahoo index symbols empty; using EURUSD=X proxy")
                return eu
            try:
                from data_fetchers import fred_data
                fr = fred_data.get_dxy_from_fred_trade_weighted(timeframe)
                if fr and not fr.get("error"):
                    logger.warning("DXY: using FRED DTWEXBGS (trade-weighted USD) fallback")
                    return fr
            except Exception:
                logger.exception("FRED DXY fallback failed")

            return {"error": "No DXY tickers available and no valid snapshot fallback", "timeframe": timeframe}

        if len(hist) > 1:
            latest, comparison = _latest_and_comparison_for_timeframe(hist, timeframe)
        else:
            latest = hist.iloc[-1]
            comparison = latest
            logger.warning("DXY history has only 1 row; change will be 0 (insufficient data)")

        current_price = float(latest["Close"])
        comparison_price = float(comparison["Close"])
        if not math.isfinite(current_price) or current_price <= 0:
            raise ValueError("invalid DXY close")
        if not math.isfinite(comparison_price) or comparison_price <= 0:
            raise ValueError("invalid DXY comparison close")
        change = ((current_price - comparison_price) / comparison_price) * 100 if comparison_price else 0.0

        # Log source and value for auditing
        logger.info(f"DXY fetched from {symbol}: {current_price} (date={_safe_date_str(latest.name)})")

        # Lightweight validation: only compare same-scale DXY tickers.
        # UUP is an ETF (~28) and cannot be compared to DX-Y.NYB (~104) — different scales.
        # Only cross-validate between DX-Y.NYB and DX=F which are both the DXY index.
        SAME_SCALE_ALTS = {
            "DX-Y.NYB": ["DX=F", "DXY"],
            "DX=F": ["DX-Y.NYB", "DXY"],
            "DXY": ["DX-Y.NYB", "DX=F"],
        }
        validation = {"validated": True, "details": []}
        try:
            alts_to_check = SAME_SCALE_ALTS.get(symbol, [])
            for alt in alts_to_check:
                try:
                    alt_t = yf.Ticker(alt)
                    alt_hist = alt_t.history(period="1d")
                    if not alt_hist.empty:
                        alt_price = float(alt_hist.iloc[-1]["Close"])
                        diff_pct = abs(current_price - alt_price) / max(alt_price, 1e-9)
                        validation["details"].append({"source": alt, "price": alt_price, "diff_pct": round(diff_pct, 6)})
                        if diff_pct > DXY_VALIDATION_TOLERANCE_PCT:
                            validation["validated"] = False
                            validation["reason"] = f"Difference {diff_pct:.6f} exceeds tolerance {DXY_VALIDATION_TOLERANCE_PCT} (pct)"
                            logger.warning(
                                f"DXY validation failed vs {alt}: primary={current_price} alt={alt_price} diff_pct={diff_pct:.6f}"
                            )
                            break
                except Exception:
                    continue
        except Exception:
            logger.exception("DXY validation subsystem error")

        result = {
            "current_price": round(current_price, 2),
            "date": _safe_date_str(latest.name),
            "data_as_of": _safe_date_str(latest.name),
            "comparison_date": _safe_date_str(comparison.name),
            "change": round(change, 2),
            "change_label": _change_label(timeframe),
            "change_unit": "percent",
            "trend": "weakening" if change < 0 else "strengthening" if change > 0 else "stable",
            "timeframe": timeframe,
            "source": symbol,
            "_validation": validation,
        }
        roll = _dxy_rolling_1m_fields(hist)
        if roll:
            result.update(roll)

        # If validation failed, mark suspect but keep the primary value.
        # Do NOT replace the DXY value with DTWEXBGS — that is a different index
        # (broad trade-weighted dollar, ~120) and would show a wrong number to the client.
        # Instead, log a warning and let the primary value through with a suspect flag.
        if not validation.get("validated", True):
            result["_suspect"] = True
            result["_warning"] = "DXY cross-validation failed vs alternate ticker; using primary value"
            logger.warning(
                "DXY cross-validation failed for %s (primary=%.2f). "
                "Keeping primary value — DTWEXBGS fallback suppressed (different index scale).",
                symbol, current_price
            )

        return _with_obs_fetch(result, latest.name)
    except Exception as e:
        logger.warning("DXY primary fetch error: %s; trying proxies", e)
        basket = _dxy_from_fx_basket(timeframe)
        if basket:
            return basket
        eu = _dxy_from_eurusd_proxy(timeframe)
        if eu:
            return eu
        try:
            from data_fetchers import fred_data
            fr = fred_data.get_dxy_from_fred_trade_weighted(timeframe)
            if fr and not fr.get("error"):
                return fr
        except Exception:
            logger.exception("DXY FRED fallback after error")
        return {"error": f"DXY fetch error: {str(e)}", "timeframe": timeframe}


def get_vix_data(timeframe: str = "current") -> Dict:
    """Get VIX (Volatility Index) data with timeframe support"""
    try:
        if STRICT_LIVE_OFFICIAL_ONLY:
            trusted = _trusted_vix_fallback(timeframe)
            if trusted:
                return trusted

            fred_fallback = _fred_series_market_fallback(
                "VIXCLS",
                timeframe,
                response_key="current_value",
                change_unit="points",
                source_name="FRED:VIXCLS",
            )
            if fred_fallback:
                current_vix = float(fred_fallback["current_value"])
                fred_fallback["level"] = "high" if current_vix > 20 else "moderate" if current_vix > 15 else "low"
                return fred_fallback
            return {"error": "Official VIX source unavailable", "timeframe": timeframe}

        if timeframe == "current":
            intraday = _current_intraday_yahoo_metric(
                ("^VIX", "VIX"),
                response_key="current_value",
                change_unit="points",
            )
            if intraday:
                current_vix = float(intraday["current_value"])
                intraday["level"] = "high" if current_vix > 20 else "moderate" if current_vix > 15 else "low"
                return intraday
            trusted = _trusted_vix_fallback(timeframe)
            if trusted:
                return trusted

        symbol, hist = _select_same_scale_yahoo_history(("^VIX", "VIX"), timeframe, period="1mo", attempts=2)
        if hist.empty:
            trusted = _trusted_vix_fallback(timeframe)
            if trusted:
                return trusted

            fred_fallback = _fred_series_market_fallback(
                "VIXCLS",
                timeframe,
                response_key="current_value",
                change_unit="points",
                source_name="FRED:VIXCLS",
            )
            if fred_fallback:
                current_vix = float(fred_fallback["current_value"])
                fred_fallback["level"] = "high" if current_vix > 20 else "moderate" if current_vix > 15 else "low"
                return fred_fallback

            snap_value = _fresh_snapshot_value("vix")
            if snap_value is not None:
                value, timestamp = snap_value
                return {
                    "current_value": value,
                    "date": str(timestamp)[:10] if timestamp else datetime.now().strftime("%Y-%m-%d"),
                    "data_as_of": timestamp,
                    "comparison_date": (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"),
                    "change": 0.0,
                    "change_label": _change_label(timeframe),
                    "change_unit": "points",
                    "level": "unknown",
                    "trend": "stable",
                    "timeframe": timeframe,
                    "source": "last_snapshot",
                    "_fallback": True,
                    "_fallback_source": "last_snapshot",
                    "_warning": "Using last snapshot VIX value; live sources unavailable",
                }
            return {"error": "No VIX tickers available and no valid fallback", "timeframe": timeframe}

        if len(hist) > 1:
            latest, comparison = _latest_and_comparison_for_timeframe(hist, timeframe, default_days=1)
        else:
            latest = hist.iloc[-1]
            comparison = latest

        current_vix = float(latest["Close"])
        comparison_vix = float(comparison["Close"])
        change = current_vix - comparison_vix

        result = {
            "current_value": round(current_vix, 2),
            "date": _safe_date_str(latest.name),
            "data_as_of": _safe_date_str(latest.name),
            "comparison_date": _safe_date_str(comparison.name),
            "change": round(change, 2),
            "change_label": _change_label(timeframe),
            "change_unit": "points",
            "level": "high" if current_vix > 20 else "moderate" if current_vix > 15 else "low",
            "trend": "rising" if change > 0 else "falling" if change < 0 else "stable",
            "timeframe": timeframe,
            "source": symbol,
        }
        return _with_obs_fetch(result, latest.name)
    except Exception as e:
        return {"error": f"VIX fetch error: {str(e)}", "timeframe": timeframe}


def get_sp500_data(timeframe: str = "current") -> Dict:
    """Get S&P 500 data with timeframe support"""
    try:
        if STRICT_LIVE_OFFICIAL_ONLY:
            trusted = _trusted_sp500_fallback(timeframe)
            if trusted:
                return trusted

            fred_fallback = _fred_series_market_fallback(
                "SP500",
                timeframe,
                response_key="current_price",
                change_unit="percent",
                source_name="FRED:SP500",
            )
            if fred_fallback:
                return fred_fallback
            return {"error": "Official S&P 500 source unavailable", "timeframe": timeframe}

        if timeframe == "current":
            intraday = _current_intraday_yahoo_metric(
                ("^GSPC",),
                response_key="current_price",
                change_unit="percent",
            )
            if intraday:
                return intraday
            trusted = _trusted_sp500_fallback(timeframe)
            if trusted:
                return trusted

        symbol, hist = _select_same_scale_yahoo_history(("^GSPC",), timeframe)
        if hist.empty:
            trusted = _trusted_sp500_fallback(timeframe)
            if trusted:
                return trusted

            fred_fallback = _fred_series_market_fallback(
                "SP500",
                timeframe,
                response_key="current_price",
                change_unit="percent",
                source_name="FRED:SP500",
            )
            if fred_fallback:
                return fred_fallback

            snap_value = _fresh_snapshot_value("sp500_price")
            if snap_value is not None:
                value, timestamp = snap_value
                return {
                    "current_price": value,
                    "date": str(timestamp)[:10] if timestamp else datetime.now().strftime("%Y-%m-%d"),
                    "data_as_of": timestamp,
                    "comparison_date": (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d"),
                    "change": 0.0,
                    "change_label": _change_label(timeframe),
                    "change_unit": "percent",
                    "trend": "stable",
                    "timeframe": timeframe,
                    "source": "last_snapshot",
                    "_fallback": True,
                    "_fallback_source": "last_snapshot",
                }
            return {"error": "No S&P 500 sources available", "timeframe": timeframe}

        if len(hist) > 1:
            latest, comparison = _latest_and_comparison_for_timeframe(hist, timeframe)
        else:
            latest = hist.iloc[-1]
            comparison = latest

        current_price = float(latest["Close"])
        comparison_price = float(comparison["Close"])
        change = ((current_price - comparison_price) / comparison_price) * 100 if comparison_price else 0.0

        result = {
            "current_price": round(current_price, 2),
            "date": _safe_date_str(latest.name),
            "data_as_of": _safe_date_str(latest.name),
            "comparison_date": _safe_date_str(comparison.name),
            "change": round(change, 2),
            "change_label": _change_label(timeframe),
            "change_unit": "percent",
            "trend": "rising" if change > 0.05 else "falling" if change < -0.05 else "stable",
            "timeframe": timeframe,
            "source": symbol,
        }
        return _with_obs_fetch(result, latest.name)
    except Exception as e:
        return {"error": f"S&P 500 fetch error: {str(e)}", "timeframe": timeframe}


def get_gold_data(timeframe: str = "current") -> Dict:
    """Get Gold price data with timeframe support"""
    try:
        if STRICT_LIVE_OFFICIAL_ONLY:
            lbma = _lbma_gold_data(timeframe)
            if lbma:
                if lbma.get("change") is None:
                    aug = _yahoo_gold_pct_change_overlay(timeframe)
                    if aug is None:
                        aug = _fred_gold_month_percent_lbma_augment()
                    if aug:
                        sym = aug.get("symbol") or "XAUUSD=X"
                        lbma = {
                            **lbma,
                            "change": aug["change"],
                            "comparison_date": aug.get("comparison_date"),
                            "change_label": aug.get("change_label") or _change_label(timeframe),
                            "trend": aug.get("trend", lbma.get("trend", "stable")),
                            "source": f"{lbma.get('source', 'LBMA:today.json')}; % from {sym}",
                        }
                return lbma
            return {"error": "Official gold source unavailable", "timeframe": timeframe}

        if timeframe == "current":
            intraday = _current_intraday_yahoo_metric(
                ("GC=F", "XAUUSD=X"),
                response_key="current_price",
                change_unit="percent",
            )
            if intraday:
                return intraday
            trusted = _trusted_gold_fallback(timeframe)
            if trusted:
                return trusted

        symbol, hist = _select_same_scale_yahoo_history(("XAUUSD=X", "GC=F"), timeframe)
        if hist.empty:
            fred_fallback = _fred_series_market_fallback(
                "GOLDAMGBD228NLBM",
                timeframe,
                response_key="current_price",
                change_unit="percent",
                source_name="FRED:GOLDAMGBD228NLBM",
            )
            if fred_fallback:
                return fred_fallback

            snap_value = _fresh_snapshot_value("gold_price")
            if snap_value is not None:
                value, timestamp = snap_value
                return {
                    "current_price": value,
                    "date": str(timestamp)[:10] if timestamp else datetime.now().strftime("%Y-%m-%d"),
                    "data_as_of": timestamp,
                    "comparison_date": (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d"),
                    "change": 0.0,
                    "change_label": _change_label(timeframe),
                    "change_unit": "percent",
                    "trend": "stable",
                    "timeframe": timeframe,
                    "source": "last_snapshot",
                    "_fallback": True,
                    "_fallback_source": "last_snapshot",
                }
            return {"error": "No gold sources available", "timeframe": timeframe}

        if len(hist) > 1:
            latest, comparison = _latest_and_comparison_for_timeframe(hist, timeframe)
        else:
            latest = hist.iloc[-1]
            comparison = latest

        current_price = float(latest["Close"])
        comparison_price = float(comparison["Close"])
        change = ((current_price - comparison_price) / comparison_price) * 100 if comparison_price else 0.0

        result = {
            "current_price": round(current_price, 2),
            "date": _safe_date_str(latest.name),
            "data_as_of": _safe_date_str(latest.name),
            "comparison_date": _safe_date_str(comparison.name),
            "change": round(change, 2),
            "change_label": _change_label(timeframe),
            "change_unit": "percent",
            "trend": "rising" if change > 0 else "falling" if change < 0 else "stable",
            "timeframe": timeframe,
            "source": symbol,
        }
        return _with_obs_fetch(result, latest.name)
    except Exception as e:
        return {"error": f"Gold fetch error: {str(e)}", "timeframe": timeframe}


def get_btc_spot_yahoo(timeframe: str = "current") -> Dict:
    """Bitcoin spot via Yahoo BTC-USD.

    Shape aligns with ``coingecko_data.get_btc_price`` (price_usd, change, date, …).
    ``date`` uses *today* (like CoinGecko) so freshness checks stay valid when the
    last daily bar is slightly behind wall clock (weekends).
    """
    try:
        ticker = yf.Ticker("BTC-USD")
        period = TIMEFRAME_PERIODS.get(timeframe, "3mo")
        hist = ticker.history(period=period)
        if hist.empty:
            return {"error": "No BTC-USD history", "timeframe": timeframe}

        if len(hist) > 1:
            latest, comparison = _latest_and_comparison_for_timeframe(hist, timeframe)
        else:
            latest = hist.iloc[-1]
            comparison = latest

        price = float(latest["Close"])
        cmp_price = float(comparison["Close"])
        change_pct = ((price - cmp_price) / cmp_price) * 100 if cmp_price else 0.0

        change_24h = 0.0
        change_7d = 0.0
        if len(hist) >= 2:
            c0 = float(hist.iloc[-1]["Close"])
            c1 = float(hist.iloc[-2]["Close"])
            if c1:
                change_24h = round(((c0 - c1) / c1) * 100, 2)
        if len(hist) >= 8:
            c0 = float(hist.iloc[-1]["Close"])
            cold = float(hist.iloc[-8]["Close"])
            if cold:
                change_7d = round(((c0 - cold) / cold) * 100, 2)

        if timeframe == "current":
            eff_change = change_24h
        elif timeframe == "week":
            eff_change = change_7d if change_7d else round(change_pct, 2)
        else:
            eff_change = round(change_pct, 2)

        return {
            "price_usd": round(price, 2),
            "change_24h": change_24h,
            "change_7d": change_7d,
            "change": eff_change,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "observed_at": _safe_iso(latest.name),
            "bar_as_of": _safe_date_str(latest.name),
            "timeframe": timeframe,
            "_source": "yahoo_btc_usd",
        }
    except Exception as e:
        logger.warning("Yahoo BTC-USD fetch failed: %s", e)
        return {"error": f"BTC-USD fetch error: {str(e)}", "timeframe": timeframe}


def get_btc_ma200_vol_from_yahoo() -> Dict:
    """200D MA and 30D realized vol from Yahoo BTC-USD (CoinGecko OHLC fallback)."""
    try:
        ticker = yf.Ticker("BTC-USD")
        hist = ticker.history(period="400d")
        if hist.empty or len(hist) < 30:
            return {"error": "Insufficient BTC-USD history for MA/vol"}
        closes = hist["Close"].dropna().astype(float)
        if len(closes) < 30:
            return {"error": "Insufficient BTC closes"}
        tail200 = closes.tail(200) if len(closes) >= 200 else closes
        ma200 = float(tail200.mean())
        recent = closes.tail(31).tolist()
        realized_vol_30d = None
        if len(recent) >= 2:
            log_returns = [math.log(recent[i] / recent[i - 1]) for i in range(1, len(recent))]
            mean_r = sum(log_returns) / len(log_returns)
            variance = sum((r - mean_r) ** 2 for r in log_returns) / len(log_returns)
            realized_vol_30d = round(math.sqrt(variance) * math.sqrt(365), 4)
        return {
            "ma200": round(ma200, 2),
            "days_of_data": len(closes),
            "realized_vol_30d": realized_vol_30d,
            "_source": "yahoo_btc_usd",
        }
    except Exception as e:
        return {"error": str(e)}


def get_natural_gas_data(timeframe: str = "current") -> Dict:
    """Get Henry Hub Natural Gas futures price via yfinance (NG=F)."""
    try:
        if STRICT_LIVE_OFFICIAL_ONLY:
            try:
                from data_fetchers import fred_data

                df = fred_data._get_eia_series_data("NG.RNGWHHD.D")
                if not df.empty:
                    d = df.sort_values("date").reset_index(drop=True)
                    latest = d.iloc[-1]
                    if timeframe == "month" and len(d) >= 2:
                        comparison = fred_data._fred_observation_on_or_before_months_ago(d, 1)
                    elif len(d) >= 2:
                        comparison = fred_data._fred_observation_on_or_before_calendar_days_ago(
                            d, TIMEFRAME_COMPARISON.get(timeframe, 7)
                        )
                    else:
                        comparison = latest
                    cur = float(latest["value"])
                    prev = float(comparison["value"])
                    change = ((cur - prev) / prev) * 100 if prev else 0.0
                    return {
                        "current_price": round(cur, 2),
                        "date": _safe_date_str(latest["date"]),
                        "data_as_of": _safe_date_str(latest["date"]),
                        "comparison_date": _safe_date_str(comparison["date"]),
                        "change": round(change, 2),
                        "change_label": _change_label(timeframe),
                        "change_unit": "percent",
                        "trend": "rising" if change > 0.5 else "falling" if change < -0.5 else "stable",
                        "timeframe": timeframe,
                        "source": "EIA (NG.RNGWHHD.D)",
                        "_fallback": True,
                    }
            except Exception:
                logger.exception("EIA natgas fallback failed")

            fred_fallback = _fred_series_market_fallback(
                "DHHNGSP",
                timeframe,
                response_key="current_price",
                change_unit="percent",
                source_name="FRED:DHHNGSP",
            )
            if fred_fallback:
                return fred_fallback
            return {"error": "Official natural gas source unavailable", "timeframe": timeframe}

        symbol, hist = _select_same_scale_yahoo_history(("NG=F",), timeframe)
        if hist.empty:
            fred_fallback = _fred_series_market_fallback(
                "DHHNGSP",
                timeframe,
                response_key="current_price",
                change_unit="percent",
                source_name="FRED:DHHNGSP",
            )
            if fred_fallback:
                return fred_fallback

            snap_value = _fresh_snapshot_value("natgas_price")
            if snap_value is not None:
                value, timestamp = snap_value
                return {
                    "current_price": value,
                    "date": str(timestamp)[:10] if timestamp else datetime.now().strftime("%Y-%m-%d"),
                    "data_as_of": timestamp,
                    "comparison_date": (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d"),
                    "change": 0.0,
                    "change_label": _change_label(timeframe),
                    "change_unit": "percent",
                    "trend": "stable",
                    "timeframe": timeframe,
                    "source": "last_snapshot",
                    "_fallback": True,
                    "_fallback_source": "last_snapshot",
                }
            return {"error": "No natural gas sources available", "timeframe": timeframe}

        # For 1D/current view, use live intraday vs prior session close when possible.
        # This aligns more closely with TradingView's default daily % change semantics.
        if timeframe == "current":
            try:
                ticker = yf.Ticker(symbol or "NG=F")
                intraday = ticker.history(period="2d", interval="60m")
                if intraday is not None and not intraday.empty:
                    h = _normalize_hist_index(intraday)
                    latest = h.iloc[-1]
                    latest_day = h.index[-1].normalize()
                    prev_session = h[h.index.normalize() < latest_day]
                    if not prev_session.empty:
                        comparison = prev_session.iloc[-1]
                    elif len(h) > 1:
                        comparison = h.iloc[-2]
                    else:
                        comparison = latest
                elif len(hist) > 1:
                    latest, comparison = _latest_and_comparison_for_timeframe(hist, timeframe)
                else:
                    latest = hist.iloc[-1]
                    comparison = latest
            except Exception:
                if len(hist) > 1:
                    latest, comparison = _latest_and_comparison_for_timeframe(hist, timeframe)
                else:
                    latest = hist.iloc[-1]
                    comparison = latest
        elif len(hist) > 1:
            latest, comparison = _latest_and_comparison_for_timeframe(hist, timeframe)
        else:
            latest = hist.iloc[-1]
            comparison = latest

        current_price = float(latest["Close"])
        comparison_price = float(comparison["Close"])
        change = ((current_price - comparison_price) / comparison_price) * 100 if comparison_price else 0.0

        return {
            "current_price": round(current_price, 2),
            "date": _safe_date_str(latest.name),
            "data_as_of": _safe_date_str(latest.name),
            "comparison_date": _safe_date_str(comparison.name),
            "change": round(change, 2),
            "change_label": _change_label(timeframe),
            "change_unit": "percent",
            "trend": "rising" if change > 0.5 else "falling" if change < -0.5 else "stable",
            "timeframe": timeframe,
            "source": symbol,
        }
    except Exception as e:
        return {"error": f"Natural gas fetch error: {str(e)}", "timeframe": timeframe}


def _yahoo_pct_change_series(symbol: str, timeframe: str) -> Dict:
    """Shared helper for index/ETF % change over the analysis window."""
    ticker = yf.Ticker(symbol)
    period = TIMEFRAME_PERIODS.get(timeframe, "3mo")
    hist = ticker.history(period=period)
    if hist.empty:
        return {"error": f"No data for {symbol}", "timeframe": timeframe, "symbol": symbol}
    if len(hist) > 1:
        latest, comparison = _latest_and_comparison_for_timeframe(hist, timeframe)
    else:
        latest = hist.iloc[-1]
        comparison = latest
    cur = float(latest["Close"])
    prev = float(comparison["Close"])
    change_pct = ((cur - prev) / prev) * 100 if prev else 0.0
    return {
        "current_price": round(cur, 2),
        "date": _safe_date_str(latest.name),
        "data_as_of": _safe_date_str(latest.name),
        "comparison_date": _safe_date_str(comparison.name),
        "change": round(change_pct, 2),
        "change_label": _change_label(timeframe),
        "change_unit": "percent",
        "trend": "rising" if change_pct > 0.05 else "falling" if change_pct < -0.05 else "stable",
        "timeframe": timeframe,
        "source": symbol,
    }


def _trusted_quote_metric_payload(
    quote: Dict[str, Any],
    *,
    timeframe: str,
    response_key: str = "current_price",
    change_unit: str = "percent",
    baseline_snapshot_field: Optional[str] = None,
    trend_up: str = "rising",
    trend_down: str = "falling",
) -> Optional[Dict[str, Any]]:
    if not isinstance(quote, dict):
        return None

    value = quote.get("price")
    try:
        current_value = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(current_value):
        return None

    comparison_date = None
    change = None
    if baseline_snapshot_field:
        baseline = _snapshot_baseline_for_timeframe(baseline_snapshot_field, timeframe)
        if baseline and baseline[0] not in (None, 0):
            try:
                baseline_val = float(baseline[0])
                if baseline_val != 0:
                    if change_unit == "points":
                        change = current_value - baseline_val
                    else:
                        change = ((current_value - baseline_val) / baseline_val) * 100.0
                    comparison_date = str(baseline[1])[:10] if baseline[1] else None
            except (TypeError, ValueError):
                change = None

    if change is None:
        raw_change = quote.get("change_points") if change_unit == "points" else quote.get("change_percent")
        try:
            change = float(raw_change) if raw_change is not None else 0.0
        except (TypeError, ValueError):
            change = 0.0

    threshold = 0.1 if change_unit == "points" else 0.05
    trend = trend_up if change > threshold else trend_down if change < -threshold else "stable"

    observed_at = quote.get("observed_at")
    fetched_at = datetime.utcnow().isoformat()
    as_of = str((observed_at or quote.get("date") or datetime.now().strftime("%Y-%m-%d")))[:10]
    return {
        response_key: round(current_value, 2),
        "date": as_of,
        "data_as_of": as_of,
        "observed_at": observed_at,
        "fetched_at": fetched_at,
        "comparison_date": comparison_date,
        "change": round(change, 2),
        "change_label": _change_label(timeframe),
        "change_unit": change_unit,
        "trend": trend,
        "timeframe": timeframe,
        "source": str(quote.get("source") or "trusted_provider"),
        "_fallback": True,
    }


def _trusted_dxy_fallback(timeframe: str) -> Optional[Dict[str, Any]]:
    if trusted_market_apis is None:
        return None

    for symbol in ("DX-Y.NYB", "DX=F", "DXY"):
        quote = trusted_market_apis.get_fmp_quote(symbol)
        out = _trusted_quote_metric_payload(
            quote or {},
            timeframe=timeframe,
            response_key="current_price",
            change_unit="percent",
            baseline_snapshot_field="dxy_value",
            trend_up="strengthening",
            trend_down="weakening",
        )
        if out:
            return out

    te_quote = trusted_market_apis.get_tradingeconomics_quote_from_search(
        "u.s. dollar index",
        preferred_symbol="DXY:CUR",
        preferred_ticker="DXY",
    )
    out = _trusted_quote_metric_payload(
        te_quote or {},
        timeframe=timeframe,
        response_key="current_price",
        change_unit="percent",
        baseline_snapshot_field="dxy_value",
        trend_up="strengthening",
        trend_down="weakening",
    )
    if out:
        return out

    for query in ("DXY", "US Dollar Index"):
        eod_quote = trusted_market_apis.get_eodhd_quote_from_search(query, asset_type="index")
        out = _trusted_quote_metric_payload(
            eod_quote or {},
            timeframe=timeframe,
            response_key="current_price",
            change_unit="percent",
            baseline_snapshot_field="dxy_value",
            trend_up="strengthening",
            trend_down="weakening",
        )
        if out:
            return out

    return None


def _trusted_gold_fallback(timeframe: str) -> Optional[Dict[str, Any]]:
    if trusted_market_apis is None:
        return None

    for symbol in ("GCUSD", "XAUUSD", "GC=F"):
        quote = trusted_market_apis.get_fmp_quote(symbol)
        out = _trusted_quote_metric_payload(
            quote or {},
            timeframe=timeframe,
            response_key="current_price",
            change_unit="percent",
            baseline_snapshot_field="gold_price",
        )
        if out:
            return out

    for query, preferred_symbol, preferred_ticker in (
        ("gold", "XAUUSD:CUR", "XAUUSD"),
        ("gold", "XAUUSD", "XAUUSD"),
    ):
        te_quote = trusted_market_apis.get_tradingeconomics_quote_from_search(
            query,
            preferred_symbol=preferred_symbol,
            preferred_ticker=preferred_ticker,
        )
        out = _trusted_quote_metric_payload(
            te_quote or {},
            timeframe=timeframe,
            response_key="current_price",
            change_unit="percent",
            baseline_snapshot_field="gold_price",
        )
        if out:
            return out

    for asset_type in ("commodity", "forex", "index"):
        eod_quote = trusted_market_apis.get_eodhd_quote_from_search("gold", asset_type=asset_type)
        out = _trusted_quote_metric_payload(
            eod_quote or {},
            timeframe=timeframe,
            response_key="current_price",
            change_unit="percent",
            baseline_snapshot_field="gold_price",
        )
        if out:
            return out

    return None


def _trusted_move_fallback(timeframe: str) -> Optional[Dict[str, Any]]:
    if trusted_market_apis is None:
        return None

    for symbol in ("^MOVE", "MOVE"):
        quote = trusted_market_apis.get_fmp_quote(symbol)
        out = _trusted_quote_metric_payload(
            quote or {},
            timeframe=timeframe,
            response_key="current_price",
            change_unit="percent",
            baseline_snapshot_field="move_index_value",
        )
        if out:
            return out

    eod_quote = trusted_market_apis.get_eodhd_quote_from_search("MOVE", asset_type="index")
    out = _trusted_quote_metric_payload(
        eod_quote or {},
        timeframe=timeframe,
        response_key="current_price",
        change_unit="percent",
        baseline_snapshot_field="move_index_value",
    )
    return out


def _trusted_vix_fallback(timeframe: str) -> Optional[Dict[str, Any]]:
    if trusted_market_apis is None:
        return None

    for symbol in ("^VIX", "VIX"):
        quote = trusted_market_apis.get_fmp_quote(symbol)
        out = _trusted_quote_metric_payload(
            quote or {},
            timeframe=timeframe,
            response_key="current_value",
            change_unit="points",
            baseline_snapshot_field="vix",
        )
        if out:
            current_vix = float(out["current_value"])
            out["level"] = "high" if current_vix > 20 else "moderate" if current_vix > 15 else "low"
            return out

    te_quote = trusted_market_apis.get_tradingeconomics_quote_from_search(
        "vix",
        preferred_symbol="VIX:IND",
        preferred_ticker="VIX",
    )
    out = _trusted_quote_metric_payload(
        te_quote or {},
        timeframe=timeframe,
        response_key="current_value",
        change_unit="points",
        baseline_snapshot_field="vix",
    )
    if out:
        current_vix = float(out["current_value"])
        out["level"] = "high" if current_vix > 20 else "moderate" if current_vix > 15 else "low"
        return out

    eod_quote = trusted_market_apis.get_eodhd_quote_from_search("VIX", asset_type="index")
    out = _trusted_quote_metric_payload(
        eod_quote or {},
        timeframe=timeframe,
        response_key="current_value",
        change_unit="points",
        baseline_snapshot_field="vix",
    )
    if out:
        current_vix = float(out["current_value"])
        out["level"] = "high" if current_vix > 20 else "moderate" if current_vix > 15 else "low"
    return out


def _trusted_sp500_fallback(timeframe: str) -> Optional[Dict[str, Any]]:
    if trusted_market_apis is None:
        return None

    quote = trusted_market_apis.get_fmp_quote("^GSPC")
    out = _trusted_quote_metric_payload(
        quote or {},
        timeframe=timeframe,
        response_key="current_price",
        change_unit="percent",
        baseline_snapshot_field="sp500_price",
    )
    if out:
        return out

    te_quote = trusted_market_apis.get_tradingeconomics_quote_from_search(
        "s&p 500",
        preferred_symbol="SPX:IND",
    )
    out = _trusted_quote_metric_payload(
        te_quote or {},
        timeframe=timeframe,
        response_key="current_price",
        change_unit="percent",
        baseline_snapshot_field="sp500_price",
    )
    if out:
        return out

    eod_quote = trusted_market_apis.get_eodhd_quote_from_search("SPX", asset_type="index")
    out = _trusted_quote_metric_payload(
        eod_quote or {},
        timeframe=timeframe,
        response_key="current_price",
        change_unit="percent",
        baseline_snapshot_field="sp500_price",
    )
    return out


def _trusted_emerging_markets_fallback(timeframe: str) -> Optional[Dict[str, Any]]:
    if trusted_market_apis is None:
        return None

    for symbol in ("EEM", "VWO"):
        quote = trusted_market_apis.get_fmp_quote(symbol)
        out = _trusted_quote_metric_payload(
            quote or {},
            timeframe=timeframe,
            response_key="current_price",
            change_unit="percent",
            baseline_snapshot_field="eem_price",
        )
        if out:
            return out

    for query in ("EEM", "VWO"):
        eod_quote = trusted_market_apis.get_eodhd_quote_from_search(query, asset_type="etf")
        out = _trusted_quote_metric_payload(
            eod_quote or {},
            timeframe=timeframe,
            response_key="current_price",
            change_unit="percent",
            baseline_snapshot_field="eem_price",
        )
        if out:
            return out

    return None


def _trusted_btc_etf_volume(etf_tickers: Tuple[str, ...], timeframe: str) -> Optional[Dict[str, Any]]:
    if trusted_market_apis is None:
        return None

    quotes = trusted_market_apis.get_fmp_batch_quotes(etf_tickers)
    if not quotes:
        return None

    total_volume = 0
    sources = []
    latest_date = None
    for sym in etf_tickers:
        row = quotes.get(sym.upper())
        if not isinstance(row, dict):
            continue
        volume = row.get("volume")
        if volume is None:
            continue
        try:
            total_volume += int(volume)
        except (TypeError, ValueError):
            continue
        sources.append(sym)
        if latest_date is None:
            date_val = row.get("date")
            latest_date = str(date_val)[:10] if date_val else None

    if not sources:
        return None

    level = "high" if total_volume > 80_000_000 else "moderate" if total_volume > 30_000_000 else "low"
    return {
        "total_volume": total_volume,
        "level": level,
        "etfs_tracked": sources,
        "date": latest_date or datetime.now().strftime("%Y-%m-%d"),
        "timeframe": timeframe,
        "source": "FMP:batch-quote",
        "_fallback": True,
    }


def _tradingview_scan_latest_close(ticker: str) -> Optional[float]:
    payload = {
        "symbols": {
            "tickers": [ticker],
            "query": {"types": []},
        },
        "columns": ["close"],
    }
    try:
        resp = requests.post(TRADINGVIEW_SCANNER_URL, json=payload, timeout=15)
        resp.raise_for_status()
        body = resp.json()
        rows = body.get("data") if isinstance(body, dict) else None
        if not isinstance(rows, list) or not rows:
            return None
        first = rows[0] if isinstance(rows[0], dict) else None
        if not isinstance(first, dict):
            return None
        values = first.get("d")
        if not isinstance(values, list) or not values:
            return None
        val = float(values[0])
        if not math.isfinite(val):
            return None
        return val
    except Exception as e:
        logger.debug("TradingView scan failed for %s: %s", ticker, e)
        return None


def _cboe_tyvix_move_proxy(timeframe: str) -> Optional[Dict[str, Any]]:
    """Free Treasury-volatility proxy when direct MOVE is unavailable.

    TYVIX tracks implied volatility on U.S. Treasury futures and is a practical
    substitute signal for MOVE stress direction.
    """
    try:
        resp = get_with_retries(CBOE_TYVIX_CSV_URL, timeout=20, max_attempts=2)
        df = pd.read_csv(StringIO(resp.text))
        if df.empty or "DATE" not in df.columns or "CLOSE" not in df.columns:
            return None

        d = pd.DataFrame(
            {
                "Close": pd.to_numeric(df["CLOSE"], errors="coerce"),
            },
            index=pd.to_datetime(df["DATE"], errors="coerce"),
        ).dropna()
        if d.empty:
            return None

        if len(d) > 1:
            latest, comparison = _latest_and_comparison_for_timeframe(d, timeframe, default_days=1)
        else:
            latest = d.iloc[-1]
            comparison = latest

        current_price = float(latest["Close"])
        comparison_price = float(comparison["Close"])
        if not math.isfinite(current_price):
            return None

        change = ((current_price - comparison_price) / comparison_price) * 100 if comparison_price else 0.0
        trend = "rising" if change > 0.05 else "falling" if change < -0.05 else "stable"

        return {
            "current_price": round(current_price, 2),
            "date": _safe_date_str(latest.name),
            "data_as_of": _safe_date_str(latest.name),
            "comparison_date": _safe_date_str(comparison.name),
            "change": round(change, 2),
            "change_label": _change_label(timeframe),
            "change_unit": "percent",
            "trend": trend,
            "timeframe": timeframe,
            "source": "CBOE:TYVIX_proxy",
            "_fallback": True,
        }
    except Exception as e:
        logger.debug("CBOE TYVIX proxy fallback failed: %s", e)
        return None


def get_move_index_data(timeframe: str = "current") -> Dict:
    """ICE BofA MOVE Treasury volatility index (^MOVE)."""
    try:
        for symbol in ["^MOVE", "MOVE"]:
            try:
                out = _yahoo_pct_change_series(symbol, timeframe)
                if "error" not in out:
                    return out
            except Exception:
                continue

        trusted = _trusted_move_fallback(timeframe)
        if trusted:
            return trusted

        tv_value = _tradingview_scan_latest_close("INDEX:MOVE")
        if tv_value is not None:
            baseline = _fresh_snapshot_value("move_index_value")
            baseline_val = baseline[0] if baseline else None
            change = ((tv_value - baseline_val) / baseline_val) * 100 if baseline_val and baseline_val > 0 else None
            trend = "stable"
            if change is not None:
                trend = "rising" if change > 0.05 else "falling" if change < -0.05 else "stable"
            return {
                "current_price": round(tv_value, 2),
                "date": datetime.now().strftime("%Y-%m-%d"),
                "data_as_of": datetime.now().strftime("%Y-%m-%d"),
                "comparison_date": str(baseline[1])[:10] if baseline and baseline[1] else None,
                "change": round(change, 2) if change is not None else None,
                "change_label": _change_label(timeframe),
                "change_unit": "percent",
                "trend": trend,
                "timeframe": timeframe,
                "source": "TradingView:INDEX:MOVE",
                "_fallback": True,
            }

        tyvix_proxy = _cboe_tyvix_move_proxy(timeframe)
        if tyvix_proxy:
            return tyvix_proxy

        fred_proxy = _fred_series_market_fallback(
            "BAMLH0A0HYM2",
            timeframe,
            response_key="current_price",
            change_unit="points",
            source_name="FRED:BAMLH0A0HYM2",
            trend_up="widening",
            trend_down="tightening",
        )
        if fred_proxy:
            fred_proxy["_proxy_note"] = "HY OAS proxy for MOVE volatility stress"
            return fred_proxy

        return {"error": "No MOVE index data available", "timeframe": timeframe}
    except Exception as e:
        return {"error": f"MOVE fetch error: {str(e)}", "timeframe": timeframe}


def get_emerging_markets_data(timeframe: str = "current") -> Dict:
    """Emerging markets equity proxy via EEM (fallback: VWO)."""
    try:
        for symbol in ("EEM", "VWO"):
            out = _yahoo_pct_change_series(symbol, timeframe)
            if "error" not in out:
                return out

        trusted = _trusted_emerging_markets_fallback(timeframe)
        if trusted:
            return trusted

        return {"error": "No EEM data available", "timeframe": timeframe}
    except Exception as e:
        return {"error": f"Emerging markets fetch error: {str(e)}", "timeframe": timeframe}


def get_btc_etf_volume(timeframe: str = "current") -> Dict:
    """Get aggregate BTC spot ETF daily volume."""
    etf_tickers = ("IBIT", "FBTC", "GBTC", "ARKB", "BITB")
    total_volume: Optional[int] = 0
    sources = []
    latest_date = None
    try:
        trusted = _trusted_btc_etf_volume(etf_tickers, timeframe)
        if trusted:
            return trusted

        period = TIMEFRAME_PERIODS.get(timeframe, "1mo")
        for sym in etf_tickers:
            try:
                hist = yf.Ticker(sym).history(period=period)
                if not hist.empty:
                    vol = int(hist.iloc[-1].get("Volume", 0))
                    total_volume += vol
                    sources.append(sym)
                    if latest_date is None:
                        latest_date = _safe_date_str(hist.index[-1])
            except Exception:
                continue

        if not sources:
            total_volume = None

        if total_volume is None:
            return {"error": "No BTC ETF data available", "timeframe": timeframe}

        level = "high" if total_volume > 80_000_000 else "moderate" if total_volume > 30_000_000 else "low"

        return {
            "total_volume": total_volume,
            "level": level,
            "etfs_tracked": sources,
            "date": latest_date or datetime.now().strftime("%Y-%m-%d"),
            "timeframe": timeframe,
            "source": "Yahoo Finance",
        }
    except Exception as e:
        return {"error": f"BTC ETF volume fetch error: {str(e)}", "timeframe": timeframe}


def get_dxy_structure(timeframe: str = "current") -> Dict:
    """Detect DXY swing structure (higher-highs/lower-lows) from recent daily closes."""
    try:
        if STRICT_LIVE_OFFICIAL_ONLY:
            hist = _ecb_dxy_history(timeframe, lookback_days={"current": 90, "week": 120, "month": 210, "year": 420}.get(timeframe, 120))
            if hist.empty or len(hist) < 20:
                return {
                    "structure": "unknown",
                    "timeframe": timeframe,
                    "error": "Official ECB FX basket history unavailable",
                }
        else:
            period = {"current": "3mo", "week": "3mo", "month": "6mo", "year": "2y"}.get(timeframe, "3mo")
            hist = None
            for symbol in ["DX-Y.NYB", "DX=F"]:
                t = yf.Ticker(symbol)
                hist = t.history(period=period)
                if not hist.empty:
                    break
            if hist is None or hist.empty or len(hist) < 20:
                t2 = yf.Ticker("EURUSD=X")
                h2 = t2.history(period=period)
                if not h2.empty and len(h2) >= 20:
                    hist = h2.copy()
                    hist["Close"] = -hist["Close"]
                else:
                    return {"structure": "unknown", "timeframe": timeframe}

        closes = hist["Close"].dropna().values
        window = min(5, len(closes) // 4)
        if window < 2:
            return {"structure": "unknown", "timeframe": timeframe}

        swing_highs = []
        swing_lows = []
        for i in range(window, len(closes) - window):
            if closes[i] == max(closes[i - window:i + window + 1]):
                swing_highs.append((i, closes[i]))
            if closes[i] == min(closes[i - window:i + window + 1]):
                swing_lows.append((i, closes[i]))

        structure = "unclear"
        if len(swing_highs) >= 2 and len(swing_lows) >= 2:
            hh = swing_highs[-1][1] > swing_highs[-2][1]
            hl = swing_lows[-1][1] > swing_lows[-2][1]
            lh = swing_highs[-1][1] < swing_highs[-2][1]
            ll = swing_lows[-1][1] < swing_lows[-2][1]
            if hh and hl:
                structure = "uptrend"
            elif lh and ll:
                structure = "downtrend"
            elif hh and ll:
                structure = "expanding"
            elif lh and hl:
                structure = "contracting"
        elif len(swing_highs) >= 2:
            structure = "uptrend" if swing_highs[-1][1] > swing_highs[-2][1] else "downtrend"

        return {
            "structure": structure,
            "recent_swing_high": round(swing_highs[-1][1], 2) if swing_highs else None,
            "recent_swing_low": round(swing_lows[-1][1], 2) if swing_lows else None,
            "timeframe": timeframe,
            "source": "ECB:EXR_fx_basket" if STRICT_LIVE_OFFICIAL_ONLY else None,
        }
    except Exception as e:
        return {"structure": "unknown", "error": str(e), "timeframe": timeframe}
