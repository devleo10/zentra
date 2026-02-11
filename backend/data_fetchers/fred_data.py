"""
Fetch macroeconomic data from FRED API
"""
import os
import requests
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, Optional, Literal, Tuple
from dotenv import load_dotenv

load_dotenv()

FRED_API_KEY = os.getenv("FRED_API_KEY")
FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"

# Timeframe to days mapping
# Note: FRED series like CPI/PCE are monthly, so we need enough lookback
# to get at least 2 data points for comparison
TIMEFRAME_DAYS = {
    "current": 90,   # 3 months to ensure we get at least 2 CPI points
    "week": 90,      # Still need monthly data points for FRED
    "month": 120,    # 4 months for month-over-month
    "year": 400      # Over a year for year-over-year
}


def get_timeframe_dates(timeframe: str = "current") -> Tuple[str, int]:
    """
    Get start date and comparison days based on timeframe
    
    Args:
        timeframe: One of 'current', 'week', 'month', 'year'
    
    Returns:
        Tuple of (start_date_str, comparison_days)
    """
    days = TIMEFRAME_DAYS.get(timeframe, 30)
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    
    comparison_days = {
        "current": 1,
        "week": 7,
        "month": 30,
        "year": 365
    }.get(timeframe, 1)
    
    return start_date, comparison_days


def get_fred_data(series_id: str, start_date: Optional[str] = None, timeframe: str = "current") -> pd.DataFrame:
    """
    Fetch data from FRED API
    
    Args:
        series_id: FRED series ID (e.g., 'CPIAUCSL' for CPI)
        start_date: Start date in YYYY-MM-DD format (default based on timeframe)
        timeframe: One of 'current', 'week', 'month', 'year'
        
    Returns:
        DataFrame with date and value columns
    """
    if not FRED_API_KEY:
        print("Warning: FRED_API_KEY not found in environment variables")
        return pd.DataFrame()
    
    if not start_date:
        start_date, _ = get_timeframe_dates(timeframe)
    
    params = {
        "series_id": series_id,
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "observation_start": start_date,
        "sort_order": "desc"
    }
    
    try:
        response = requests.get(FRED_BASE_URL, params=params, timeout=15)
        response.raise_for_status()
        
        data = response.json()
        
        if "observations" not in data:
            return pd.DataFrame()
        
        df = pd.DataFrame(data["observations"])
        df["date"] = pd.to_datetime(df["date"])
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        df = df.dropna(subset=["value"])
        
        return df[["date", "value"]].sort_values("date")
    except Exception as e:
        print(f"Error fetching FRED data for {series_id}: {e}")
        return pd.DataFrame()


def get_cpi_data(timeframe: str = "current") -> Dict:
    """Get CPI data based on timeframe"""
    start_date, comparison_days = get_timeframe_dates(timeframe)
    df = get_fred_data("CPIAUCSL", start_date=start_date)  # CPI All Items Urban Consumers
    
    if df.empty:
        return {"error": "No CPI data available", "timeframe": timeframe}
    
    latest = df.iloc[-1]
    
    # Find comparison point based on timeframe
    comparison_idx = min(comparison_days, len(df) - 1)
    prev_value = df.iloc[-comparison_idx - 1] if len(df) > comparison_idx else latest
    
    change = ((latest["value"] - prev_value["value"]) / prev_value["value"]) * 100 if len(df) > 1 else 0
    
    timeframe_label = {
        "current": "mom",
        "week": "wow",
        "month": "mom",
        "year": "yoy"
    }.get(timeframe, "change")
    
    return {
        "latest_value": float(latest["value"]),
        "latest_date": latest["date"].strftime("%Y-%m-%d"),
        "comparison_date": prev_value["date"].strftime("%Y-%m-%d"),
        f"{timeframe_label}_change": round(change, 2),
        "change": round(change, 2),
        "trend": "falling" if change < 0 else "rising" if change > 0 else "flat",
        "timeframe": timeframe
    }


def get_pce_data(timeframe: str = "current") -> Dict:
    """Get PCE data based on timeframe"""
    start_date, comparison_days = get_timeframe_dates(timeframe)
    df = get_fred_data("PCEPI", start_date=start_date)  # Personal Consumption Expenditures Price Index
    
    if df.empty:
        return {"error": "No PCE data available", "timeframe": timeframe}
    
    latest = df.iloc[-1]
    comparison_idx = min(comparison_days, len(df) - 1)
    prev_value = df.iloc[-comparison_idx - 1] if len(df) > comparison_idx else latest
    
    change = ((latest["value"] - prev_value["value"]) / prev_value["value"]) * 100 if len(df) > 1 else 0
    
    timeframe_label = {
        "current": "mom",
        "week": "wow",
        "month": "mom",
        "year": "yoy"
    }.get(timeframe, "change")
    
    return {
        "latest_value": float(latest["value"]),
        "latest_date": latest["date"].strftime("%Y-%m-%d"),
        "comparison_date": prev_value["date"].strftime("%Y-%m-%d"),
        f"{timeframe_label}_change": round(change, 2),
        "change": round(change, 2),
        "trend": "falling" if change < 0 else "rising" if change > 0 else "flat",
        "timeframe": timeframe
    }


def get_treasury_yields(timeframe: str = "current") -> Dict:
    """Get 2Y and 10Y Treasury yields with timeframe comparison"""
    start_date, comparison_days = get_timeframe_dates(timeframe)
    df_2y = get_fred_data("DGS2", start_date=start_date)  # 2-Year Treasury
    df_10y = get_fred_data("DGS10", start_date=start_date)  # 10-Year Treasury
    
    result = {"timeframe": timeframe}
    
    if not df_2y.empty:
        latest_2y = df_2y.iloc[-1]
        comparison_idx = min(comparison_days, len(df_2y) - 1)
        prev_2y = df_2y.iloc[-comparison_idx - 1] if len(df_2y) > comparison_idx else latest_2y
        change_2y = latest_2y["value"] - prev_2y["value"]
        
        result["yield_2y"] = {
            "value": float(latest_2y["value"]),
            "date": latest_2y["date"].strftime("%Y-%m-%d"),
            "change": round(change_2y, 2),
            "trend": "rising" if change_2y > 0 else "falling" if change_2y < 0 else "flat"
        }
    
    if not df_10y.empty:
        latest_10y = df_10y.iloc[-1]
        comparison_idx = min(comparison_days, len(df_10y) - 1)
        prev_10y = df_10y.iloc[-comparison_idx - 1] if len(df_10y) > comparison_idx else latest_10y
        change_10y = latest_10y["value"] - prev_10y["value"]
        
        result["yield_10y"] = {
            "value": float(latest_10y["value"]),
            "date": latest_10y["date"].strftime("%Y-%m-%d"),
            "change": round(change_10y, 2),
            "trend": "rising" if change_10y > 0 else "falling" if change_10y < 0 else "flat"
        }
        
        # Calculate yield curve spread
        if "yield_2y" in result:
            spread = result["yield_10y"]["value"] - result["yield_2y"]["value"]
            result["yield_curve_spread"] = round(spread, 2)
            result["yield_curve_status"] = "steepening" if spread > 0 else "inverted" if spread < 0 else "flat"
    
    return result


def get_fed_balance_sheet(timeframe: str = "current") -> Dict:
    """Get Federal Reserve balance sheet size with timeframe comparison"""
    start_date, comparison_days = get_timeframe_dates(timeframe)
    df = get_fred_data("WALCL", start_date=start_date)  # Total Assets of the Federal Reserve
    
    if df.empty:
        return {"error": "No balance sheet data available", "timeframe": timeframe}
    
    latest = df.iloc[-1]
    comparison_idx = min(comparison_days, len(df) - 1)
    prev_value = df.iloc[-comparison_idx - 1] if len(df) > comparison_idx else latest
    
    change = ((latest["value"] - prev_value["value"]) / prev_value["value"]) * 100 if len(df) > 1 else 0
    
    return {
        "total_assets": float(latest["value"]) / 1e9,  # Convert to billions
        "latest_date": latest["date"].strftime("%Y-%m-%d"),
        "comparison_date": prev_value["date"].strftime("%Y-%m-%d"),
        "change": round(change, 2),
        "trend": "expanding" if change > 0 else "contracting" if change < 0 else "stable",
        "timeframe": timeframe
    }


