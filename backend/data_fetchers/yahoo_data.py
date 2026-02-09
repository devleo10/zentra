"""
Fetch market data from Yahoo Finance using yfinance
"""
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, Optional


def get_dxy_data() -> Dict:
    """Get US Dollar Index (DXY) data"""
    ticker = yf.Ticker("DX-Y.NYB")
    
    # Get recent data
    hist = ticker.history(period="3mo")
    
    if hist.empty:
        return {"error": "No DXY data available"}
    
    latest = hist.iloc[-1]
    week_ago = hist.iloc[-7] if len(hist) >= 7 else latest
    month_ago = hist.iloc[-30] if len(hist) >= 30 else latest
    
    current_price = float(latest["Close"])
    week_change = ((current_price - float(week_ago["Close"])) / float(week_ago["Close"])) * 100
    month_change = ((current_price - float(month_ago["Close"])) / float(month_ago["Close"])) * 100
    
    return {
        "current_price": round(current_price, 2),
        "date": latest.name.strftime("%Y-%m-%d"),
        "week_change": round(week_change, 2),
        "month_change": round(month_change, 2),
        "trend": "weakening" if week_change < 0 else "strengthening" if week_change > 0 else "stable"
    }


def get_vix_data() -> Dict:
    """Get VIX (Volatility Index) data"""
    ticker = yf.Ticker("^VIX")
    
    hist = ticker.history(period="1mo")
    
    if hist.empty:
        return {"error": "No VIX data available"}
    
    latest = hist.iloc[-1]
    current_vix = float(latest["Close"])
    
    return {
        "current_value": round(current_vix, 2),
        "date": latest.name.strftime("%Y-%m-%d"),
        "level": "high" if current_vix > 20 else "moderate" if current_vix > 15 else "low"
    }


def get_sp500_data() -> Dict:
    """Get S&P 500 data"""
    ticker = yf.Ticker("^GSPC")
    
    hist = ticker.history(period="3mo")
    
    if hist.empty:
        return {"error": "No S&P 500 data available"}
    
    latest = hist.iloc[-1]
    week_ago = hist.iloc[-7] if len(hist) >= 7 else latest
    
    current_price = float(latest["Close"])
    week_change = ((current_price - float(week_ago["Close"])) / float(week_ago["Close"])) * 100
    
    return {
        "current_price": round(current_price, 2),
        "date": latest.name.strftime("%Y-%m-%d"),
        "week_change": round(week_change, 2),
        "trend": "risk_on" if week_change > 0 else "risk_off" if week_change < 0 else "neutral"
    }


def get_gold_data() -> Dict:
    """Get Gold price data"""
    ticker = yf.Ticker("GC=F")  # Gold futures
    
    hist = ticker.history(period="3mo")
    
    if hist.empty:
        return {"error": "No Gold data available"}
    
    latest = hist.iloc[-1]
    week_ago = hist.iloc[-7] if len(hist) >= 7 else latest
    
    current_price = float(latest["Close"])
    week_change = ((current_price - float(week_ago["Close"])) / float(week_ago["Close"])) * 100
    
    return {
        "current_price": round(current_price, 2),
        "date": latest.name.strftime("%Y-%m-%d"),
        "week_change": round(week_change, 2),
        "trend": "strengthening" if week_change > 0 else "weakening" if week_change < 0 else "stable"
    }

