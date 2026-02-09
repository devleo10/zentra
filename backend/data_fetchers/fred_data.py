"""
Fetch macroeconomic data from FRED API
"""
import os
import requests
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, Optional
from dotenv import load_dotenv

load_dotenv()

FRED_API_KEY = os.getenv("FRED_API_KEY")
FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"


def get_fred_data(series_id: str, start_date: Optional[str] = None) -> pd.DataFrame:
    """
    Fetch data from FRED API
    
    Args:
        series_id: FRED series ID (e.g., 'CPIAUCSL' for CPI)
        start_date: Start date in YYYY-MM-DD format (default: 1 year ago)
        
    Returns:
        DataFrame with date and value columns
    """
    if not FRED_API_KEY:
        raise ValueError("FRED_API_KEY not found in environment variables")
    
    if not start_date:
        start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
    
    params = {
        "series_id": series_id,
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "observation_start": start_date,
        "sort_order": "desc"
    }
    
    response = requests.get(FRED_BASE_URL, params=params)
    response.raise_for_status()
    
    data = response.json()
    
    if "observations" not in data:
        return pd.DataFrame()
    
    df = pd.DataFrame(data["observations"])
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["value"])
    
    return df[["date", "value"]].sort_values("date")


def get_cpi_data() -> Dict:
    """Get latest CPI data"""
    df = get_fred_data("CPIAUCSL")  # CPI All Items Urban Consumers
    
    if df.empty:
        return {"error": "No CPI data available"}
    
    latest = df.iloc[-1]
    prev_month = df.iloc[-2] if len(df) > 1 else latest
    
    mom_change = ((latest["value"] - prev_month["value"]) / prev_month["value"]) * 100 if len(df) > 1 else 0
    
    return {
        "latest_value": float(latest["value"]),
        "latest_date": latest["date"].strftime("%Y-%m-%d"),
        "mom_change": round(mom_change, 2),
        "trend": "falling" if mom_change < 0 else "rising" if mom_change > 0 else "flat"
    }


def get_pce_data() -> Dict:
    """Get latest PCE data"""
    df = get_fred_data("PCEPI")  # Personal Consumption Expenditures Price Index
    
    if df.empty:
        return {"error": "No PCE data available"}
    
    latest = df.iloc[-1]
    prev_month = df.iloc[-2] if len(df) > 1 else latest
    
    mom_change = ((latest["value"] - prev_month["value"]) / prev_month["value"]) * 100 if len(df) > 1 else 0
    
    return {
        "latest_value": float(latest["value"]),
        "latest_date": latest["date"].strftime("%Y-%m-%d"),
        "mom_change": round(mom_change, 2),
        "trend": "falling" if mom_change < 0 else "rising" if mom_change > 0 else "flat"
    }


def get_treasury_yields() -> Dict:
    """Get 2Y and 10Y Treasury yields"""
    df_2y = get_fred_data("DGS2")  # 2-Year Treasury
    df_10y = get_fred_data("DGS10")  # 10-Year Treasury
    
    result = {}
    
    if not df_2y.empty:
        latest_2y = df_2y.iloc[-1]
        result["yield_2y"] = {
            "value": float(latest_2y["value"]),
            "date": latest_2y["date"].strftime("%Y-%m-%d")
        }
    
    if not df_10y.empty:
        latest_10y = df_10y.iloc[-1]
        result["yield_10y"] = {
            "value": float(latest_10y["value"]),
            "date": latest_10y["date"].strftime("%Y-%m-%d")
        }
        
        # Calculate yield curve spread
        if "yield_2y" in result:
            spread = result["yield_10y"]["value"] - result["yield_2y"]["value"]
            result["yield_curve_spread"] = round(spread, 2)
            result["yield_curve_status"] = "steepening" if spread > 0 else "inverted" if spread < 0 else "flat"
    
    return result


def get_fed_balance_sheet() -> Dict:
    """Get Federal Reserve balance sheet size"""
    df = get_fred_data("WALCL")  # Total Assets of the Federal Reserve
    
    if df.empty:
        return {"error": "No balance sheet data available"}
    
    latest = df.iloc[-1]
    prev_month = df.iloc[-2] if len(df) > 2 else latest
    
    mom_change = ((latest["value"] - prev_month["value"]) / prev_month["value"]) * 100 if len(df) > 1 else 0
    
    return {
        "total_assets": float(latest["value"]) / 1e9,  # Convert to billions
        "latest_date": latest["date"].strftime("%Y-%m-%d"),
        "mom_change": round(mom_change, 2),
        "trend": "expanding" if mom_change > 0 else "contracting" if mom_change < 0 else "stable"
    }

