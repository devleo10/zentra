"""Fetch market data from Yahoo Finance using yfinance.

This module includes lightweight validation and logging for DXY to
detect suspect values and enable fallbacks.

Unlike news/LLM steps, live market prices should remain uncached so the
client sees the most recent DXY, VIX, S&P 500, and Gold values on each
analysis run.
"""
import logging
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, Optional
import json
from pathlib import Path

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


def _safe_date_str(ts) -> str:
    """Safely convert a pandas Timestamp (possibly tz-aware) to YYYY-MM-DD string"""
    try:
        if hasattr(ts, 'strftime'):
            return ts.strftime("%Y-%m-%d")
        return str(ts)[:10]
    except Exception:
        return datetime.now().strftime("%Y-%m-%d")


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


# Timeframe to period mapping for yfinance
TIMEFRAME_PERIODS = {
    "current": "1mo",
    "week": "1mo",
    "month": "3mo",
    "year": "2y"
}

# Timeframe to comparison days (calendar days — not trading sessions)
TIMEFRAME_COMPARISON = {
    "current": 1,
    "week": 7,
    "month": 30,
    "year": 365
}


def _normalize_hist_index(hist: pd.DataFrame) -> pd.DataFrame:
    """Timezone-naive DatetimeIndex for reliable calendar arithmetic."""
    h = hist.copy()
    idx = pd.to_datetime(hist.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    h.index = idx
    return h


def _latest_and_comparison_rows(hist: pd.DataFrame, calendar_days: int):
    """Pick comparison bar as last row on or before (latest_date − calendar_days).

    Fixes % change for 'month' (30d): using 30 *trading* rows was ~6 weeks, not 30 days.
    Normalizes to date-only to avoid DST hour offsets (winter bars are 05:00 UTC,
    spring/summer bars are 04:00 UTC → naive subtraction misses the target day).
    Returns (latest_row, comparison_row) as Series.
    """
    h = _normalize_hist_index(hist)
    if h.empty:
        raise ValueError("empty history")
    latest = h.iloc[-1]
    latest_date = h.index[-1].normalize()  # midnight
    days = max(1, int(calendar_days))
    cutoff_date = latest_date - pd.Timedelta(days=days)
    past = h[h.index.normalize() <= cutoff_date]
    if past.empty:
        comparison = h.iloc[0]
    else:
        comparison = past.iloc[-1]
    return latest, comparison


def get_dxy_data(timeframe: str = "current") -> Dict:
    """Get US Dollar Index (DXY) data with timeframe support"""
    try:
        # Try multiple DXY ticker symbols as availability varies
        # Preferred order: market DXY futures or index symbols commonly used by yfinance
        for symbol in ["DX-Y.NYB", "DX=F", "DXY", "UUP"]:
            ticker = yf.Ticker(symbol)
            period = TIMEFRAME_PERIODS.get(timeframe, "3mo")
            hist = ticker.history(period=period)
            if not hist.empty:
                break
        else:
            # No live tickers returned. Attempt last-snapshot fallback if configured.
            if USE_LAST_SNAPSHOT_FOR_FALLBACK:
                try:
                    from storage.db import get_latest_snapshots
                    snaps = get_latest_snapshots(1)
                    if snaps:
                        snap = snaps[0]
                        dxy_val = snap.get("dxy_value")
                        timestamp = snap.get("timestamp")
                        if dxy_val is not None:
                            # Check freshness of snapshot
                            try:
                                snap_time = datetime.fromisoformat(timestamp)
                                age_hours = (datetime.now() - snap_time).total_seconds() / 3600.0
                            except Exception:
                                age_hours = float('inf')
                            if age_hours <= FALLBACK_MAX_SNAPSHOT_AGE_HOURS:
                                logger.warning("Using last snapshot DXY fallback (age %.1f h)", age_hours)
                                return {
                                    "current_price": float(dxy_val),
                                    "date": timestamp,
                                    "data_as_of": timestamp,
                                    "comparison_date": (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d"),
                                    "change": 0.0,
                                    "trend": "stable",
                                    "timeframe": timeframe,
                                    "source": "last_snapshot",
                                    "_fallback": True,
                                    "_fallback_source": "last_snapshot",
                                }
                except Exception:
                    logger.exception("Error attempting last-snapshot fallback for DXY")

            return {"error": "No DXY tickers available and no valid snapshot fallback", "timeframe": timeframe}

        if hist.empty:
            return {"error": "No DXY data available", "timeframe": timeframe}

        comparison_days = TIMEFRAME_COMPARISON.get(timeframe, 7)
        if len(hist) > 1:
            latest, comparison = _latest_and_comparison_rows(hist, comparison_days)
        else:
            latest = hist.iloc[-1]
            comparison = latest
            logger.warning("DXY history has only 1 row; change will be 0 (insufficient data)")

        current_price = float(latest["Close"])
        comparison_price = float(comparison["Close"])
        change = ((current_price - comparison_price) / comparison_price) * 100 if comparison_price else 0.0

        # Log source and value for auditing
        logger.info(f"DXY fetched from {symbol}: {current_price} (date={_safe_date_str(latest.name)})")

        # Lightweight validation: only compare same-scale DXY tickers.
        # UUP is an ETF (~28) and cannot be compared to DX-Y.NYB (~104) — different scales.
        # Only cross-validate between DX-Y.NYB and DX=F which are both the DXY index.
        SAME_SCALE_ALTS = {"DX-Y.NYB": ["DX=F"], "DX=F": ["DX-Y.NYB"]}
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
            "trend": "weakening" if change < 0 else "strengthening" if change > 0 else "stable",
            "timeframe": timeframe,
            "source": symbol,
            "_validation": validation,
        }

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

        return result
    except Exception as e:
        return {"error": f"DXY fetch error: {str(e)}", "timeframe": timeframe}


def get_vix_data(timeframe: str = "current") -> Dict:
    """Get VIX (Volatility Index) data with timeframe support"""
    try:
        # Try multiple VIX ticker symbols
        for symbol in ["^VIX", "VIX", "VIXY"]:
            ticker = yf.Ticker(symbol)
            period = TIMEFRAME_PERIODS.get(timeframe, "1mo")
            hist = ticker.history(period=period)
            if not hist.empty:
                break
        else:
            # Avoid fabricated fallback values for volatility metrics.
            snap = _get_latest_snapshot()
            if snap and snap.get("vix") is not None:
                timestamp = snap.get("timestamp")
                return {
                    "current_value": float(snap.get("vix")),
                    "date": str(timestamp)[:10] if timestamp else datetime.now().strftime("%Y-%m-%d"),
                    "data_as_of": timestamp,
                    "comparison_date": (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"),
                    "change": 0.0,
                    "level": "unknown",
                    "trend": "stable",
                    "timeframe": timeframe,
                    "source": "last_snapshot",
                    "_fallback": True,
                    "_fallback_source": "last_snapshot",
                    "_warning": "Using last snapshot VIX value; live VIX tickers unavailable",
                }
            return {"error": "No VIX tickers available and no valid snapshot fallback", "timeframe": timeframe}

        comparison_days = TIMEFRAME_COMPARISON.get(timeframe, 1)
        if len(hist) > 1:
            latest, comparison = _latest_and_comparison_rows(hist, comparison_days)
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
            "level": "high" if current_vix > 20 else "moderate" if current_vix > 15 else "low",
            "trend": "rising" if change > 0 else "falling" if change < 0 else "stable",
            "timeframe": timeframe,
            "source": symbol,
        }
        return result
    except Exception as e:
        return {"error": f"VIX fetch error: {str(e)}", "timeframe": timeframe}


def get_sp500_data(timeframe: str = "current") -> Dict:
    """Get S&P 500 data with timeframe support"""
    try:
        # Try multiple S&P 500 ticker symbols
        for symbol in ["^GSPC", "SPY", "VOO"]:
            ticker = yf.Ticker(symbol)
            period = TIMEFRAME_PERIODS.get(timeframe, "3mo")
            hist = ticker.history(period=period)
            if not hist.empty:
                break
        else:
            return {"error": "No S&P 500 tickers available", "timeframe": timeframe}

        comparison_days = TIMEFRAME_COMPARISON.get(timeframe, 7)
        if len(hist) > 1:
            latest, comparison = _latest_and_comparison_rows(hist, comparison_days)
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
            "trend": "rising" if change > 0.05 else "falling" if change < -0.05 else "stable",
            "timeframe": timeframe,
            "source": symbol,
        }
        return result
    except Exception as e:
        return {"error": f"S&P 500 fetch error: {str(e)}", "timeframe": timeframe}


def get_gold_data(timeframe: str = "current") -> Dict:
    """Get Gold price data with timeframe support"""
    try:
        # Try multiple Gold ticker symbols
        for symbol in ["GC=F", "GLD", "IAU"]:
            ticker = yf.Ticker(symbol)
            period = TIMEFRAME_PERIODS.get(timeframe, "3mo")
            hist = ticker.history(period=period)
            if not hist.empty:
                break
        else:
            return {"error": "No gold tickers available", "timeframe": timeframe}

        comparison_days = TIMEFRAME_COMPARISON.get(timeframe, 7)
        if len(hist) > 1:
            latest, comparison = _latest_and_comparison_rows(hist, comparison_days)
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
            "trend": "rising" if change > 0 else "falling" if change < 0 else "stable",
            "timeframe": timeframe,
            "source": symbol,
        }
        return result
    except Exception as e:
        return {"error": f"Gold fetch error: {str(e)}", "timeframe": timeframe}


def get_natural_gas_data(timeframe: str = "current") -> Dict:
    """Get Henry Hub Natural Gas futures price via yfinance (NG=F)."""
    try:
        for symbol in ["NG=F"]:
            ticker = yf.Ticker(symbol)
            period = TIMEFRAME_PERIODS.get(timeframe, "3mo")
            hist = ticker.history(period=period)
            if not hist.empty:
                break
        else:
            return {"error": "No natural gas tickers available", "timeframe": timeframe}

        comparison_days = TIMEFRAME_COMPARISON.get(timeframe, 7)
        if len(hist) > 1:
            latest, comparison = _latest_and_comparison_rows(hist, comparison_days)
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
    comparison_days = TIMEFRAME_COMPARISON.get(timeframe, 7)
    if len(hist) > 1:
        latest, comparison = _latest_and_comparison_rows(hist, comparison_days)
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
        "trend": "rising" if change_pct > 0.05 else "falling" if change_pct < -0.05 else "stable",
        "timeframe": timeframe,
        "source": symbol,
    }


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
        return {"error": "No MOVE index data available", "timeframe": timeframe}
    except Exception as e:
        return {"error": f"MOVE fetch error: {str(e)}", "timeframe": timeframe}


def get_emerging_markets_data(timeframe: str = "current") -> Dict:
    """Emerging markets equity proxy (iShares EEM)."""
    try:
        for symbol in ["EEM", "VWO"]:
            try:
                out = _yahoo_pct_change_series(symbol, timeframe)
                if "error" not in out:
                    return out
            except Exception:
                continue
        return {"error": "No emerging markets ETF data available", "timeframe": timeframe}
    except Exception as e:
        return {"error": f"Emerging markets fetch error: {str(e)}", "timeframe": timeframe}


def get_btc_etf_volume(timeframe: str = "current") -> Dict:
    """Get aggregate BTC spot ETF daily volume as a proxy for institutional flows."""
    etf_tickers = ["IBIT", "FBTC", "GBTC", "ARKB", "BITB"]
    total_volume = 0
    sources = []
    latest_date = None
    try:
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
            return {"error": "No BTC ETF data available", "timeframe": timeframe}

        level = "high" if total_volume > 80_000_000 else "moderate" if total_volume > 30_000_000 else "low"
        return {
            "total_volume": total_volume,
            "level": level,
            "etfs_tracked": sources,
            "date": latest_date or datetime.now().strftime("%Y-%m-%d"),
            "timeframe": timeframe,
        }
    except Exception as e:
        return {"error": f"BTC ETF volume fetch error: {str(e)}", "timeframe": timeframe}


def get_dxy_structure(timeframe: str = "current") -> Dict:
    """Detect DXY swing structure (higher-highs/lower-lows) from recent daily closes."""
    try:
        period = {"current": "3mo", "week": "3mo", "month": "6mo", "year": "2y"}.get(timeframe, "3mo")
        hist = None
        for symbol in ["DX-Y.NYB", "DX=F"]:
            t = yf.Ticker(symbol)
            hist = t.history(period=period)
            if not hist.empty:
                break
        if hist is None or hist.empty or len(hist) < 20:
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
        }
    except Exception as e:
        return {"structure": "unknown", "error": str(e), "timeframe": timeframe}