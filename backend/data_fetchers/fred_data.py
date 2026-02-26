"""
Fetch macroeconomic data from FRED API and BLS API v2.

CPI priority:
  1. BLS API v2 (official source, returns MoM/YoY calculations natively)
  2. FRED API (fallback — same underlying data, slightly delayed)
"""
import os
import requests
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, Optional, Literal, Tuple
from dotenv import load_dotenv
import logging

load_dotenv()

logger = logging.getLogger("btc_macro.data_fetchers.fred")

FRED_API_KEY = os.getenv("FRED_API_KEY")
FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"

BLS_API_KEY = os.getenv("BLS_API_KEY")
BLS_API_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"

# BLS series IDs for CPI
BLS_CPI_ALL_ITEMS_SA = "CUSR0000SA0"      # CPI-U All Items, seasonally adjusted (headline)
BLS_CPI_CORE_SA = "CUSR0000SA0L1E"        # CPI-U Core (ex food & energy), seasonally adjusted

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


def _get_last_snapshot_field(field_name: str):
    """Return the last known value for a named snapshot field, if available."""
    try:
        # Import locally to avoid import cycles at module import time
        from storage.db import get_latest_snapshots
        snaps = get_latest_snapshots(1)
        if snaps:
            snap = snaps[0]
            return snap.get(field_name)
    except Exception:
        logger.exception("Failed to read last snapshot for fallback")
    return None


def get_fred_series(series_id: str, timeframe: str = "current") -> Dict:
    """Fetch the latest observation for a generic FRED series (lightweight wrapper).

    Returns a dict with keys: value, date, _source
    """
    start_date, _ = get_timeframe_dates(timeframe)
    params = {
        "series_id": series_id,
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "observation_start": start_date,
        "sort_order": "desc"
    }
    try:
        if not FRED_API_KEY:
            logger.warning("FRED API key missing; cannot fetch %s", series_id)
            return {"error": "missing_api_key"}
        resp = requests.get(FRED_BASE_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        obs = data.get("observations", [])
        if not obs:
            return {"error": "no_observations"}
        # sort_order=desc means newest is first
        latest = obs[0]
        value = None
        try:
            value = float(latest.get("value"))
        except Exception:
            value = None
        return {"value": value, "date": latest.get("date"), "_source": "FRED", "series_id": series_id}
    except Exception as e:
        logger.exception("Error fetching FRED series %s: %s", series_id, e)
        return {"error": str(e)}


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


def _get_cpi_from_bls() -> Optional[Dict]:
    """Fetch CPI data from BLS API v2 (official source).

    Uses the registered API key to request:
    - CUSR0000SA0  — CPI-U All Items, seasonally adjusted
    - CUSR0000SA0L1E — Core CPI (ex food & energy), seasonally adjusted

    BLS v2 with calculations=true returns MoM and YoY percent changes natively,
    so no manual math is needed.

    Returns a dict compatible with get_cpi_data() output, or None on failure.
    """
    if not BLS_API_KEY:
        logger.debug("BLS_API_KEY not set; skipping BLS CPI fetch")
        return None

    current_year = datetime.now().year
    start_year = str(current_year - 2)  # 2 years back for YoY context
    end_year = str(current_year)

    payload = {
        "seriesid": [BLS_CPI_ALL_ITEMS_SA, BLS_CPI_CORE_SA],
        "startyear": start_year,
        "endyear": end_year,
        "calculations": True,
        "registrationkey": BLS_API_KEY,
    }

    try:
        resp = requests.post(
            BLS_API_URL,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("status") != "REQUEST_SUCCEEDED":
            logger.warning("BLS API returned non-success status: %s | messages: %s",
                           data.get("status"), data.get("message"))
            return None

        series_map: Dict[str, list] = {}
        for series in data.get("Results", {}).get("series", []):
            series_map[series["seriesID"]] = series.get("data", [])

        headline = series_map.get(BLS_CPI_ALL_ITEMS_SA, [])
        core = series_map.get(BLS_CPI_CORE_SA, [])

        if not headline:
            logger.warning("BLS returned no headline CPI data")
            return None

        # BLS data is sorted newest-first
        latest = headline[0]
        latest_value = float(latest["value"])
        latest_date = f"{latest['year']}-{latest['period'].replace('M', '').zfill(2)}-01"

        # Extract MoM and YoY from calculations block (BLS provides these directly)
        calcs = latest.get("calculations", {})
        pct_changes = calcs.get("pct_changes", {})
        mom_change = float(pct_changes.get("1", 0))   # 1-month % change
        yoy_rate = float(pct_changes.get("12", 0))    # 12-month % change = YoY

        # Core CPI YoY
        core_yoy = None
        if core:
            core_latest = core[0]
            core_calcs = core_latest.get("calculations", {}).get("pct_changes", {})
            core_yoy = float(core_calcs.get("12", 0)) if "12" in core_calcs else None

        result = {
            "latest_value": latest_value,
            "latest_date": latest_date,
            "mom_change": round(mom_change, 3),
            "yoy_rate": round(yoy_rate, 2),
            "core_yoy_rate": round(core_yoy, 2) if core_yoy is not None else None,
            "change": round(mom_change, 3),
            "trend": "falling" if mom_change < 0 else "rising" if mom_change > 0 else "flat",
            "source": "BLS",
            "_validation": {"validated": True, "reasons": []},
        }
        logger.info(
            "BLS CPI: index=%.3f MoM=%+.3f%% YoY=%.2f%% Core YoY=%s%% (date=%s)",
            latest_value, mom_change, yoy_rate,
            f"{core_yoy:.2f}" if core_yoy is not None else "N/A",
            latest_date,
        )
        return result

    except Exception as e:
        logger.warning("BLS CPI fetch failed: %s", e)
        return None


def get_cpi_data(timeframe: str = "current") -> Dict:
    """Get CPI data based on timeframe.

    Priority:
      1. BLS API v2 — official source, includes Core CPI, MoM/YoY built-in
      2. FRED API   — fallback, same underlying data, slightly delayed
      3. Last snapshot — last resort if both APIs fail
    """
    # ── Attempt 1: BLS API (primary) ───────────────────────────────────────
    bls_result = _get_cpi_from_bls()
    if bls_result:
        bls_result["timeframe"] = timeframe
        return bls_result

    logger.info("BLS CPI unavailable; falling back to FRED CPIAUCSL")

    # ── Attempt 2: FRED API (fallback) ─────────────────────────────────────
    # Always fetch 400 days to guarantee 13+ monthly observations for YoY
    df = get_fred_data("CPIAUCSL", start_date=(datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d"))
    if df.empty:
        last_cpi = _get_last_snapshot_field("cpi_mom_change")
        logger.warning("No CPI data from FRED; using last snapshot fallback: %s", last_cpi)
        if last_cpi is not None:
            return {
                "latest_value": None,
                "latest_date": None,
                "comparison_date": None,
                "mom_change": last_cpi,
                "_fallback": True,
                "_fallback_source": "last_snapshot",
                "timeframe": timeframe,
            }
        return {"error": "No CPI data available", "timeframe": timeframe}

    latest = df.iloc[-1]

    # MoM change: latest vs previous month
    mom_change = 0.0
    if len(df) >= 2:
        prev_month = df.iloc[-2]
        mom_change = ((latest["value"] - prev_month["value"]) / prev_month["value"]) * 100

    # YoY rate: latest vs same month ~12 observations ago
    yoy_rate = None
    if len(df) >= 13:
        year_ago = df.iloc[-13]
        yoy_rate = round(((latest["value"] - year_ago["value"]) / year_ago["value"]) * 100, 2)

    comparison_days = {
        "current": 1, "week": 7, "month": 30, "year": 365
    }.get(timeframe, 1)
    comparison_idx = min(comparison_days, len(df) - 1)
    prev_value = df.iloc[-comparison_idx - 1] if len(df) > comparison_idx else latest
    change = ((latest["value"] - prev_value["value"]) / prev_value["value"]) * 100 if len(df) > 1 else 0

    timeframe_label = {
        "current": "mom",
        "week": "wow",
        "month": "mom",
        "year": "yoy"
    }.get(timeframe, "change")

    result = {
        "latest_value": float(latest["value"]),
        "latest_date": latest["date"].strftime("%Y-%m-%d"),
        "comparison_date": prev_value["date"].strftime("%Y-%m-%d"),
        f"{timeframe_label}_change": round(change, 2),
        "change": round(change, 2),
        "mom_change": round(mom_change, 2),
        "yoy_rate": yoy_rate,
        "core_yoy_rate": None,          # Not available from FRED without separate series fetch
        "trend": "falling" if mom_change < 0 else "rising" if mom_change > 0 else "flat",
        "source": "FRED",
        "timeframe": timeframe
    }

    # Basic plausibility checks
    validation = {"validated": True, "reasons": []}
    if result["latest_value"] is None:
        validation["validated"] = False
        validation["reasons"].append("Latest CPI value is missing")
    else:
        if result["latest_value"] < 0 or result["latest_value"] > 1000:
            validation["validated"] = False
            validation["reasons"].append("CPI value out of plausible range")

    result["_validation"] = validation
    if not validation["validated"]:
        logger.warning("CPI validation failed: %s", validation["reasons"])

    logger.info(
        "CPI fetched: index=%s MoM=%+.2f%% YoY=%s%% (date=%s)",
        result.get("latest_value"),
        mom_change,
        yoy_rate,
        result.get("latest_date"),
    )
    return result


def get_pce_data(timeframe: str = "current") -> Dict:
    """Get PCE data based on timeframe"""
    start_date, comparison_days = get_timeframe_dates(timeframe)
    df = get_fred_data("PCEPI", start_date=start_date)  # Personal Consumption Expenditures Price Index
    
    if df.empty:
        last_pce = _get_last_snapshot_field("pce_mom_change")
        logger.warning("No PCE data from FRED; using last snapshot fallback: %s", last_pce)
        if last_pce is not None:
            return {
                "latest_value": None,
                "latest_date": None,
                "comparison_date": None,
                "mom_change": last_pce,
                "_fallback": True,
                "_fallback_source": "last_snapshot",
                "timeframe": timeframe,
            }
        return {"error": "No PCE data available", "timeframe": timeframe}

    latest = df.iloc[-1]

    # MoM change: latest vs previous month (PCE is monthly, so iloc[-2] is prior month)
    mom_change = 0.0
    prev_month = latest
    if len(df) >= 2:
        prev_month = df.iloc[-2]
        mom_change = ((latest["value"] - prev_month["value"]) / prev_month["value"]) * 100

    # Also compute timeframe-specific comparison for display
    comparison_idx = min(comparison_days, len(df) - 1)
    prev_value = df.iloc[-comparison_idx - 1] if len(df) > comparison_idx else latest
    change = ((latest["value"] - prev_value["value"]) / prev_value["value"]) * 100 if len(df) > 1 else 0

    timeframe_label = {
        "current": "mom",
        "week": "wow",
        "month": "mom",
        "year": "yoy"
    }.get(timeframe, "change")

    result = {
        "latest_value": float(latest["value"]),
        "latest_date": latest["date"].strftime("%Y-%m-%d"),
        "comparison_date": prev_value["date"].strftime("%Y-%m-%d"),
        f"{timeframe_label}_change": round(change, 2),
        "change": round(change, 2),
        "mom_change": round(mom_change, 2),
        "trend": "falling" if mom_change < 0 else "rising" if mom_change > 0 else "flat",
        "timeframe": timeframe
    }

    validation = {"validated": True, "reasons": []}
    if result["latest_value"] is None:
        validation["validated"] = False
        validation["reasons"].append("Latest PCE value is missing")
    else:
        if result["latest_value"] < 0 or result["latest_value"] > 1000:
            validation["validated"] = False
            validation["reasons"].append("PCE value out of plausible range")

    result["_validation"] = validation
    if not validation["validated"]:
        logger.warning("PCE validation failed: %s", validation["reasons"])

    logger.info("PCE fetched: %s (date=%s)", result.get("latest_value"), result.get("latest_date"))
    return result


def get_treasury_yields(timeframe: str = "current") -> Dict:
    """Get 2Y and 10Y Treasury yields with timeframe comparison"""
    start_date, comparison_days = get_timeframe_dates(timeframe)
    df_2y = get_fred_data("DGS2", start_date=start_date)  # 2-Year Treasury
    df_10y = get_fred_data("DGS10", start_date=start_date)  # 10-Year Treasury
    
    result = {"timeframe": timeframe}

    if df_2y.empty and df_10y.empty:
        # Attempt last snapshot fallback
        last_10y = _get_last_snapshot_field("ten_year_yield")
        last_2y = None
        if last_10y is not None:
            logger.warning("No treasury yield data; using last snapshot fallback for 10y: %s", last_10y)
            result["yield_10y"] = {"value": last_10y, "_fallback": True, "_fallback_source": "last_snapshot"}
        else:
            logger.error("No treasury yield data available and no snapshot fallback")
            return {"error": "No treasury yields available", "timeframe": timeframe}

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


def get_oil_data(timeframe: str = "current") -> Dict:
    """Get WTI crude oil price data from FRED (DCOILWTICO series).

    Uses FRED's weekly WTI spot price series as the primary source.
    Falls back to Yahoo Finance (CL=F) if FRED returns no data.
    """
    start_date, comparison_days = get_timeframe_dates(timeframe)
    df = get_fred_data("DCOILWTICO", start_date=start_date)  # WTI Crude Oil Spot Price

    if df.empty:
        # Fallback: try Yahoo Finance for oil futures
        try:
            import yfinance as yf
            ticker = yf.Ticker("CL=F")
            period_map = {"current": "1mo", "week": "1mo", "month": "3mo", "year": "2y"}
            hist = ticker.history(period=period_map.get(timeframe, "1mo"))
            if not hist.empty:
                latest_price = float(hist.iloc[-1]["Close"])
                comp_idx = min(comparison_days, len(hist) - 1)
                prev_price = float(hist.iloc[-comp_idx - 1]["Close"]) if len(hist) > comp_idx else latest_price
                change = ((latest_price - prev_price) / prev_price) * 100 if prev_price else 0
                logger.info("Oil fetched from Yahoo Finance (CL=F): %.2f", latest_price)
                return {
                    "current_price": round(latest_price, 2),
                    "latest_date": hist.index[-1].strftime("%Y-%m-%d"),
                    "change": round(change, 2),
                    "trend": "rising" if change > 0 else "falling" if change < 0 else "stable",
                    "source": "Yahoo Finance (CL=F)",
                    "timeframe": timeframe,
                }
        except Exception as e:
            logger.warning("Oil Yahoo Finance fallback failed: %s", e)
        logger.warning("No oil data available from FRED or Yahoo Finance")
        return {"error": "No oil data available", "timeframe": timeframe}

    latest = df.iloc[-1]
    comparison_idx = min(comparison_days, len(df) - 1)
    prev_value = df.iloc[-comparison_idx - 1] if len(df) > comparison_idx else latest
    change = ((latest["value"] - prev_value["value"]) / prev_value["value"]) * 100 if len(df) > 1 else 0

    result = {
        "current_price": round(float(latest["value"]), 2),
        "latest_date": latest["date"].strftime("%Y-%m-%d"),
        "comparison_date": prev_value["date"].strftime("%Y-%m-%d"),
        "change": round(change, 2),
        "trend": "rising" if change > 0 else "falling" if change < 0 else "stable",
        "source": "FRED (DCOILWTICO)",
        "timeframe": timeframe,
    }
    logger.info("Oil fetched: $%.2f (change=%+.2f%%, date=%s)", result["current_price"], change, result["latest_date"])
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


