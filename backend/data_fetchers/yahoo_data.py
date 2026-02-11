"""
Fetch market data from Yahoo Finance using yfinance
"""
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, Optional


def _safe_date_str(ts) -> str:
    """Safely convert a pandas Timestamp (possibly tz-aware) to YYYY-MM-DD string"""
    try:
        if hasattr(ts, 'strftime'):
            return ts.strftime("%Y-%m-%d")
        return str(ts)[:10]
    except Exception:
        return datetime.now().strftime("%Y-%m-%d")


# Timeframe to period mapping for yfinance
TIMEFRAME_PERIODS = {
    "current": "1mo",
    "week": "1mo",
    "month": "3mo",
    "year": "2y"
}

# Timeframe to comparison days
TIMEFRAME_COMPARISON = {
    "current": 1,
    "week": 7,
    "month": 30,
    "year": 365
}


def get_dxy_data(timeframe: str = "current") -> Dict:
    """Get US Dollar Index (DXY) data with timeframe support"""
    try:
        ticker = yf.Ticker("DX-Y.NYB")
        period = TIMEFRAME_PERIODS.get(timeframe, "3mo")
        hist = ticker.history(period=period)

        if hist.empty:
            return {"error": "No DXY data available", "timeframe": timeframe}

        latest = hist.iloc[-1]
        comparison_days = TIMEFRAME_COMPARISON.get(timeframe, 7)
        comparison_idx = min(comparison_days, len(hist) - 1)
        comparison = hist.iloc[-comparison_idx - 1] if len(hist) > comparison_idx else latest

        current_price = float(latest["Close"])
        comparison_price = float(comparison["Close"])
        change = ((current_price - comparison_price) / comparison_price) * 100

        return {
            "current_price": round(current_price, 2),
            "date": _safe_date_str(latest.name),
            "comparison_date": _safe_date_str(comparison.name),
            "change": round(change, 2),
            "trend": "weakening" if change < 0 else "strengthening" if change > 0 else "stable",
            "timeframe": timeframe
        }
    except Exception as e:
        return {"error": f"DXY fetch error: {str(e)}", "timeframe": timeframe}


def get_vix_data(timeframe: str = "current") -> Dict:
    """Get VIX (Volatility Index) data with timeframe support"""
    try:
        ticker = yf.Ticker("^VIX")
        period = TIMEFRAME_PERIODS.get(timeframe, "1mo")
        hist = ticker.history(period=period)

        if hist.empty:
            return {"error": "No VIX data available", "timeframe": timeframe}

        latest = hist.iloc[-1]
        comparison_days = TIMEFRAME_COMPARISON.get(timeframe, 1)
        comparison_idx = min(comparison_days, len(hist) - 1)
        comparison = hist.iloc[-comparison_idx - 1] if len(hist) > comparison_idx else latest

        current_vix = float(latest["Close"])
        comparison_vix = float(comparison["Close"])
        change = current_vix - comparison_vix

        return {
            "current_value": round(current_vix, 2),
            "date": _safe_date_str(latest.name),
            "comparison_date": _safe_date_str(comparison.name),
            "change": round(change, 2),
            "level": "high" if current_vix > 20 else "moderate" if current_vix > 15 else "low",
            "trend": "rising" if change > 0 else "falling" if change < 0 else "stable",
            "timeframe": timeframe
        }
    except Exception as e:
        return {"error": f"VIX fetch error: {str(e)}", "timeframe": timeframe}


def get_sp500_data(timeframe: str = "current") -> Dict:
    """Get S&P 500 data with timeframe support"""
    try:
        ticker = yf.Ticker("^GSPC")
        period = TIMEFRAME_PERIODS.get(timeframe, "3mo")
        hist = ticker.history(period=period)

        if hist.empty:
            return {"error": "No S&P 500 data available", "timeframe": timeframe}

        latest = hist.iloc[-1]
        comparison_days = TIMEFRAME_COMPARISON.get(timeframe, 7)
        comparison_idx = min(comparison_days, len(hist) - 1)
        comparison = hist.iloc[-comparison_idx - 1] if len(hist) > comparison_idx else latest

        current_price = float(latest["Close"])
        comparison_price = float(comparison["Close"])
        change = ((current_price - comparison_price) / comparison_price) * 100

        return {
            "current_price": round(current_price, 2),
            "date": _safe_date_str(latest.name),
            "comparison_date": _safe_date_str(comparison.name),
            "change": round(change, 2),
            "trend": "risk_on" if change > 0 else "risk_off" if change < 0 else "neutral",
            "timeframe": timeframe
        }
    except Exception as e:
        return {"error": f"S&P 500 fetch error: {str(e)}", "timeframe": timeframe}


def get_gold_data(timeframe: str = "current") -> Dict:
    """Get Gold price data with timeframe support"""
    try:
        ticker = yf.Ticker("GC=F")
        period = TIMEFRAME_PERIODS.get(timeframe, "3mo")
        hist = ticker.history(period=period)

        if hist.empty:
            return {"error": "No Gold data available", "timeframe": timeframe}

        latest = hist.iloc[-1]
        comparison_days = TIMEFRAME_COMPARISON.get(timeframe, 7)
        comparison_idx = min(comparison_days, len(hist) - 1)
        comparison = hist.iloc[-comparison_idx - 1] if len(hist) > comparison_idx else latest

        current_price = float(latest["Close"])
        comparison_price = float(comparison["Close"])
        change = ((current_price - comparison_price) / comparison_price) * 100

        return {
            "current_price": round(current_price, 2),
            "date": _safe_date_str(latest.name),
            "comparison_date": _safe_date_str(comparison.name),
            "change": round(change, 2),
            "trend": "strengthening" if change > 0 else "weakening" if change < 0 else "stable",
            "timeframe": timeframe
        }
    except Exception as e:
        return {"error": f"Gold fetch error: {str(e)}", "timeframe": timeframe}