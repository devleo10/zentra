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
        # Try multiple DXY ticker symbols as availability varies
        for symbol in ["DX-Y.NYB", "DX=F", "UUP"]:
            ticker = yf.Ticker(symbol)
            period = TIMEFRAME_PERIODS.get(timeframe, "3mo")
            hist = ticker.history(period=period)
            if not hist.empty:
                break
        else:
            # Fallback: return mock data with warning
            return {
                "current_price": 104.0,
                "date": datetime.now().strftime("%Y-%m-%d"),
                "comparison_date": (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d"),
                "change": 0.0,
                "trend": "stable",
                "timeframe": timeframe,
                "_fallback": True,
                "_warning": "Using fallback DXY value - all tickers unavailable"
            }

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
        # Try multiple VIX ticker symbols
        for symbol in ["^VIX", "VIX", "VIXY"]:
            ticker = yf.Ticker(symbol)
            period = TIMEFRAME_PERIODS.get(timeframe, "1mo")
            hist = ticker.history(period=period)
            if not hist.empty:
                break
        else:
            # Fallback: return moderate VIX with warning
            return {
                "current_value": 18.0,
                "date": datetime.now().strftime("%Y-%m-%d"),
                "comparison_date": (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"),
                "change": 0.0,
                "level": "moderate",
                "trend": "stable",
                "timeframe": timeframe,
                "_fallback": True,
                "_warning": "Using fallback VIX value - all tickers unavailable"
            }

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
        # Try multiple S&P 500 ticker symbols
        for symbol in ["^GSPC", "SPY", "VOO"]:
            ticker = yf.Ticker(symbol)
            period = TIMEFRAME_PERIODS.get(timeframe, "3mo")
            hist = ticker.history(period=period)
            if not hist.empty:
                break
        else:
            # Fallback: return neutral S&P with warning
            return {
                "current_price": 5000.0,
                "date": datetime.now().strftime("%Y-%m-%d"),
                "comparison_date": (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d"),
                "change": 0.0,
                "trend": "neutral",
                "timeframe": timeframe,
                "_fallback": True,
                "_warning": "Using fallback S&P 500 value - all tickers unavailable"
            }

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
        # Try multiple Gold ticker symbols
        for symbol in ["GC=F", "GLD", "IAU"]:
            ticker = yf.Ticker(symbol)
            period = TIMEFRAME_PERIODS.get(timeframe, "3mo")
            hist = ticker.history(period=period)
            if not hist.empty:
                break
        else:
            # Fallback: return stable gold with warning
            return {
                "current_price": 2000.0,
                "date": datetime.now().strftime("%Y-%m-%d"),
                "comparison_date": (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d"),
                "change": 0.0,
                "trend": "stable",
                "timeframe": timeframe,
                "_fallback": True,
                "_warning": "Using fallback Gold value - all tickers unavailable"
            }

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