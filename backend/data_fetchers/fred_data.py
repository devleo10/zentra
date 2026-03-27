"""
Fetch macroeconomic data from FRED API and BLS API v2.

CPI priority:
  1. BLS API v2 (official source, returns MoM/YoY calculations natively)
  2. FRED API (fallback — same underlying data, slightly delayed)
"""
import os
import requests
import pandas as pd

from utils.http_retry import get_with_retries
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

_CHANGE_LABELS = {
    "current": "1D",
    "week": "7D",
    "month": "1M",
    "year": "1Y",
}


def _fred_observation_on_or_before_calendar_days_ago(df: pd.DataFrame, calendar_days: int) -> pd.Series:
    """Last row with date <= (latest_date − calendar_days); matches equity % windows."""
    if df is None or df.empty:
        raise ValueError("empty dataframe")
    d = df.sort_values("date").copy()
    latest_dt = pd.Timestamp(d.iloc[-1]["date"]).normalize()
    cutoff = latest_dt - pd.Timedelta(days=max(1, int(calendar_days)))
    past = d[pd.to_datetime(d["date"]).dt.normalize() <= cutoff]
    if past.empty:
        return d.iloc[0]
    return past.iloc[-1]


def _fred_first_observation_of_current_month(df: pd.DataFrame) -> pd.Series:
    """First available observation in the latest calendar month."""
    if df is None or df.empty:
        raise ValueError("empty dataframe")
    d = df.sort_values("date").copy()
    latest_dt = pd.Timestamp(d.iloc[-1]["date"]).normalize()
    month_start = latest_dt.to_period("M").to_timestamp().normalize()
    this_month = d[pd.to_datetime(d["date"]).dt.normalize() >= month_start]
    if this_month.empty:
        return d.iloc[0]
    first_row = this_month.iloc[0]
    # On the very first observation of the month, fall back to the prior row so
    # the display has a meaningful baseline instead of a forced 0% self-compare.
    if pd.Timestamp(first_row["date"]).normalize() == latest_dt:
        prev = d[pd.to_datetime(d["date"]).dt.normalize() < month_start]
        return prev.iloc[-1] if not prev.empty else first_row
    return first_row


def _fred_observation_on_or_before_months_ago(df: pd.DataFrame, months: int = 1) -> pd.Series:
    """Last row with date <= (latest_date - N calendar months)."""
    if df is None or df.empty:
        raise ValueError("empty dataframe")
    d = df.sort_values("date").copy()
    latest_dt = pd.Timestamp(d.iloc[-1]["date"]).normalize()
    cutoff = (latest_dt - pd.DateOffset(months=max(1, int(months)))).normalize()
    past = d[pd.to_datetime(d["date"]).dt.normalize() <= cutoff]
    if past.empty:
        return d.iloc[0]
    return past.iloc[-1]


def _yield_month_end_track(df_10: pd.DataFrame, df_2: pd.DataFrame, n: int = 3) -> list:
    """Last n calendar months with month-end (last available) 10Y and 2Y from daily FRED series."""
    if df_10.empty or df_2.empty:
        return []
    a = df_10.sort_values("date").copy()
    b = df_2.sort_values("date").copy()
    a["ym"] = pd.to_datetime(a["date"]).dt.to_period("M")
    b["ym"] = pd.to_datetime(b["date"]).dt.to_period("M")
    a_m = a.groupby("ym", as_index=False).last().rename(columns={"date": "d10", "value": "v10"})
    b_m = b.groupby("ym", as_index=False).last().rename(columns={"date": "d2", "value": "v2"})
    merged = pd.merge(a_m, b_m, on="ym")
    if merged.empty:
        return []
    tail = merged.tail(n)
    out = []
    for _, r in tail.iterrows():
        y10 = float(r["v10"])
        y2 = float(r["v2"])
        d10 = r["d10"]
        if hasattr(d10, "strftime"):
            ds = d10.strftime("%Y-%m-%d")
        else:
            ds = str(d10)[:10]
        out.append({
            "date": ds,
            "yield_10y": round(y10, 2),
            "yield_2y": round(y2, 2),
            "spread": round(y10 - y2, 2),
        })
    return out


def _cpi_three_month_mom_stats_from_fred_df(df: pd.DataFrame) -> Dict:
    """Average of last 3 monthly MoM % changes vs prior 3 (inflation pulse)."""
    if df is None or len(df) < 4:
        return {}
    moms = []
    for i in range(1, min(8, len(df))):
        curr = float(df.iloc[-i]["value"])
        prev = float(df.iloc[-i - 1]["value"])
        if prev:
            moms.append((curr - prev) / prev * 100.0)
    if len(moms) < 3:
        return {}
    avg3 = sum(moms[:3]) / 3.0
    prior3 = sum(moms[3:6]) / 3.0 if len(moms) >= 6 else None
    if prior3 is not None:
        if avg3 > prior3 + 0.02:
            tr = "rising"
        elif avg3 < prior3 - 0.02:
            tr = "falling"
        else:
            tr = "flat"
    else:
        if avg3 > 0.05:
            tr = "rising"
        elif avg3 < -0.05:
            tr = "falling"
        else:
            tr = "flat"
    return {
        "cpi_mom_avg_3m": round(avg3, 3),
        "cpi_mom_avg_3m_prior": round(prior3, 3) if prior3 is not None else None,
        "cpi_mom_avg_3m_trend": tr,
    }


def _cpi_three_month_mom_stats_from_bls_headline(headline: list) -> Dict:
    """Same 3-month MoM average logic; BLS `headline` rows are newest-first."""
    if not headline or len(headline) < 4:
        return {}
    vals = []
    for row in headline[:12]:
        try:
            vals.append(float(row["value"]))
        except Exception:
            break
    if len(vals) < 4:
        return {}
    moms = []
    for i in range(len(vals) - 1):
        prev = vals[i + 1]
        if prev:
            moms.append((vals[i] - prev) / prev * 100.0)
    if len(moms) < 3:
        return {}
    avg3 = sum(moms[:3]) / 3.0
    prior3 = sum(moms[3:6]) / 3.0 if len(moms) >= 6 else None
    if prior3 is not None:
        if avg3 > prior3 + 0.02:
            tr = "rising"
        elif avg3 < prior3 - 0.02:
            tr = "falling"
        else:
            tr = "flat"
    else:
        if avg3 > 0.05:
            tr = "rising"
        elif avg3 < -0.05:
            tr = "falling"
        else:
            tr = "flat"
    return {
        "cpi_mom_avg_3m": round(avg3, 3),
        "cpi_mom_avg_3m_prior": round(prior3, 3) if prior3 is not None else None,
        "cpi_mom_avg_3m_trend": tr,
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


def _get_latest_snapshot() -> Optional[Dict]:
    """Return the latest stored snapshot row if available."""
    try:
        # Import locally to avoid import cycles at module import time
        from storage.db import get_latest_snapshots
        snaps = get_latest_snapshots(1)
        if snaps:
            return snaps[0]
    except Exception:
        logger.exception("Failed to read last snapshot for fallback")
    return None


def _get_last_snapshot_field(field_name: str):
    """Return the last known value for a named snapshot field, if available."""
    snap = _get_latest_snapshot()
    if snap:
        return snap.get(field_name)
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
        latest_date = latest.get("date")
        return {
            "value": value,
            "date": latest_date,
            "data_as_of": latest_date,
            "_source": "FRED",
            "series_id": series_id,
        }
    except Exception as e:
        logger.exception("Error fetching FRED series %s: %s", series_id, e)
        return {"error": str(e)}


def get_fred_data(
    series_id: str,
    start_date: Optional[str] = None,
    timeframe: str = "current",
    sort_order: Optional[str] = "desc",
) -> pd.DataFrame:
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
    }
    if sort_order is not None:
        params["sort_order"] = sort_order
    
    try:
        response = get_with_retries(
            FRED_BASE_URL,
            params=params,
            timeout=15,
            max_attempts=3,
            backoff_base=2.0,
            log_4xx_body=True,
        )
        data = response.json()

        if "observations" not in data:
            return pd.DataFrame()

        df = pd.DataFrame(data["observations"])
        df["date"] = pd.to_datetime(df["date"])
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        df = df.dropna(subset=["value"])

        return df[["date", "value"]].sort_values("date")
    except requests.HTTPError as e:
        status = getattr(getattr(e, "response", None), "status_code", "unknown")
        logger.warning("Error fetching FRED data for %s: HTTP %s", series_id, status)
        return pd.DataFrame()
    except Exception as e:
        logger.warning("Error fetching FRED data for %s: %s", series_id, type(e).__name__)
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
        result.update(_cpi_three_month_mom_stats_from_bls_headline(headline))
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
        bls_result["data_as_of"] = bls_result.get("latest_date")
        return bls_result

    logger.info("BLS CPI unavailable; falling back to FRED CPIAUCSL")

    # ── Attempt 2: FRED API (fallback) ─────────────────────────────────────
    # Always fetch 400 days to guarantee 13+ monthly observations for YoY
    df = get_fred_data("CPIAUCSL", start_date=(datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d"))
    if df.empty:
        last_cpi = _get_last_snapshot_field("cpi_mom_change")
        logger.warning("No CPI data from FRED; using last snapshot fallback: %s", last_cpi)
        if last_cpi is not None:
            snap = _get_latest_snapshot() or {}
            return {
                "latest_value": None,
                "latest_date": None,
                "comparison_date": None,
                "mom_change": last_cpi,
                "_fallback": True,
                "_fallback_source": "last_snapshot",
                "source": "last_snapshot",
                "data_as_of": snap.get("timestamp"),
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
        "data_as_of": latest["date"].strftime("%Y-%m-%d"),
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

    result.update(_cpi_three_month_mom_stats_from_fred_df(df))

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
            snap = _get_latest_snapshot() or {}
            return {
                "latest_value": None,
                "latest_date": None,
                "comparison_date": None,
                "mom_change": last_pce,
                "_fallback": True,
                "_fallback_source": "last_snapshot",
                "source": "last_snapshot",
                "data_as_of": snap.get("timestamp"),
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
        "source": "FRED",
        "data_as_of": latest["date"].strftime("%Y-%m-%d"),
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
            snap = _get_latest_snapshot() or {}
            result["yield_10y"] = {
                "value": last_10y,
                "_fallback": True,
                "_fallback_source": "last_snapshot",
                "source": "last_snapshot",
                "data_as_of": snap.get("timestamp"),
            }
        else:
            logger.error("No treasury yield data available and no snapshot fallback")
            return {"error": "No treasury yields available", "timeframe": timeframe}

    if not df_2y.empty:
        latest_2y = df_2y.iloc[-1]
        try:
            prev_2y = _fred_observation_on_or_before_calendar_days_ago(df_2y, comparison_days)
        except Exception:
            prev_2y = latest_2y
        change_2y = latest_2y["value"] - prev_2y["value"]
        
        result["yield_2y"] = {
            "value": float(latest_2y["value"]),
            "date": latest_2y["date"].strftime("%Y-%m-%d"),
            "change": round(change_2y, 2),
            "trend": "rising" if change_2y > 0 else "falling" if change_2y < 0 else "flat",
            "source": "FRED",
            "data_as_of": latest_2y["date"].strftime("%Y-%m-%d"),
        }
    
    if not df_10y.empty:
        latest_10y = df_10y.iloc[-1]
        try:
            prev_10y = _fred_observation_on_or_before_calendar_days_ago(df_10y, comparison_days)
        except Exception:
            prev_10y = latest_10y
        change_10y = latest_10y["value"] - prev_10y["value"]
        
        result["yield_10y"] = {
            "value": float(latest_10y["value"]),
            "date": latest_10y["date"].strftime("%Y-%m-%d"),
            "change": round(change_10y, 2),
            "trend": "rising" if change_10y > 0 else "falling" if change_10y < 0 else "flat",
            "source": "FRED",
            "data_as_of": latest_10y["date"].strftime("%Y-%m-%d"),
        }
        
        # Calculate yield curve spread
        if "yield_2y" in result:
            spread = result["yield_10y"]["value"] - result["yield_2y"]["value"]
            result["yield_curve_spread"] = round(spread, 2)
            result["yield_curve_status"] = "steepening" if spread > 0 else "inverted" if spread < 0 else "flat"

    if not df_2y.empty and not df_10y.empty:
        track = _yield_month_end_track(df_10y, df_2y, 3)
        if track:
            result["yield_monthly_track"] = track
            if len(track) >= 2:
                d_spread = track[-1]["spread"] - track[0]["spread"]
                result["yield_spread_delta_3m"] = round(d_spread, 2)
                result["yield_spread_trend_3m"] = (
                    "rising" if d_spread > 0.03 else "falling" if d_spread < -0.03 else "flat"
                )
                result["yield_10y_delta_3m"] = round(track[-1]["yield_10y"] - track[0]["yield_10y"], 2)
                result["yield_2y_delta_3m"] = round(track[-1]["yield_2y"] - track[0]["yield_2y"], 2)

    return result


def get_oil_data(timeframe: str = "current") -> Dict:
    """Get WTI crude oil price data.

    Use Yahoo Finance CL=F as the primary source so the dashboard shows a
    near-live futures price, then fall back to FRED spot data if Yahoo is
    unavailable.
    """
    start_date, comparison_days = get_timeframe_dates(timeframe)
    try:
        import yfinance as yf
        ticker = yf.Ticker("CL=F")
        period_map = {"current": "1mo", "week": "1mo", "month": "3mo", "year": "2y"}
        hist = ticker.history(period=period_map.get(timeframe, "1mo"))
        if not hist.empty:
            h = hist.copy()
            idx = pd.to_datetime(h.index)
            if getattr(idx, "tz", None) is not None:
                idx = idx.tz_convert("UTC").tz_localize(None)
            h.index = idx
            latest_price = float(h.iloc[-1]["Close"])
            if timeframe == "month":
                latest_date = h.index[-1].normalize()
                cutoff = (latest_date - pd.DateOffset(months=1)).normalize()
                past = h[h.index.normalize() <= cutoff]
                comparison = past.iloc[-1] if not past.empty else h.iloc[0]
                prev_price = float(comparison["Close"])
                comparison_date = comparison.name.strftime("%Y-%m-%d")
            else:
                latest_date = h.index[-1].normalize()
                cutoff = latest_date - pd.Timedelta(days=max(1, int(comparison_days)))
                past = h[h.index.normalize() <= cutoff]
                comparison = past.iloc[-1] if not past.empty else h.iloc[0]
                prev_price = float(comparison["Close"])
                comparison_date = comparison.name.strftime("%Y-%m-%d")
            change = ((latest_price - prev_price) / prev_price) * 100 if prev_price else 0
            logger.info("Oil fetched from Yahoo Finance (CL=F): %.2f", latest_price)
            return {
                "current_price": round(latest_price, 2),
                "latest_date": h.index[-1].strftime("%Y-%m-%d"),
                "comparison_date": comparison_date,
                "change": round(change, 2),
                "change_label": _CHANGE_LABELS.get(timeframe, ""),
                "change_unit": "percent",
                "trend": "rising" if change > 0 else "falling" if change < 0 else "stable",
                "source": "Yahoo Finance (CL=F)",
                "data_as_of": h.index[-1].strftime("%Y-%m-%d"),
                "timeframe": timeframe,
            }
    except Exception as e:
        logger.warning("Oil Yahoo Finance primary source failed: %s", e)

    df = get_fred_data("DCOILWTICO", start_date=start_date)  # WTI Crude Oil Spot Price
    if df.empty:
        logger.warning("No oil data available from Yahoo Finance or FRED")
        return {"error": "No oil data available", "timeframe": timeframe}

    latest = df.iloc[-1]
    if timeframe == "month":
        prev_value = _fred_observation_on_or_before_months_ago(df, 1)
    else:
        prev_value = _fred_observation_on_or_before_calendar_days_ago(df, comparison_days)
    change = ((latest["value"] - prev_value["value"]) / prev_value["value"]) * 100 if len(df) > 1 else 0

    result = {
        "current_price": round(float(latest["value"]), 2),
        "latest_date": latest["date"].strftime("%Y-%m-%d"),
        "comparison_date": prev_value["date"].strftime("%Y-%m-%d"),
        "change": round(change, 2),
        "change_label": _CHANGE_LABELS.get(timeframe, ""),
        "change_unit": "percent",
        "trend": "rising" if change > 0 else "falling" if change < 0 else "stable",
        "source": "FRED (DCOILWTICO)",
        "data_as_of": latest["date"].strftime("%Y-%m-%d"),
        "timeframe": timeframe,
    }
    logger.info("Oil fetched: $%.2f (change=%+.2f%%, date=%s)", result["current_price"], change, result["latest_date"])
    return result


def get_fed_funds_rate(timeframe: str = "current") -> Dict:
    """Get the Federal Funds Rate from FRED for display and scoring.

    Prefers the official target (upper) rate (DFEDTARU) when available, so the
    dashboard matches FOMC communications (e.g. 3.75% target). Falls back to
    effective rate (FEDFUNDS) for trend and when target is missing. Returns
    current_rate (for display), trend, and rate_type ("target" | "effective").
    """
    effective_start = (datetime.now() - timedelta(days=max(90, TIMEFRAME_DAYS.get(timeframe, 90)))).strftime("%Y-%m-%d")

    # Prefer official target upper (DFEDTARU) so displayed rate matches FOMC
    df_target = get_fred_data("DFEDTARU", start_date=effective_start)
    if not df_target.empty:
        latest_target = df_target.iloc[-1]
        target_rate = float(latest_target["value"])
        target_date = latest_target["date"].strftime("%Y-%m-%d")
    else:
        target_rate = None
        target_date = None

    df_eff = get_fred_data("FEDFUNDS", start_date=effective_start)
    if df_eff.empty and target_rate is None:
        last_rate = _get_last_snapshot_field("fed_funds_rate")
        logger.warning("No Fed Funds Rate data from FRED; using last snapshot fallback: %s", last_rate)
        if last_rate is not None:
            snap = _get_latest_snapshot() or {}
            return {
                "current_rate": last_rate,
                "previous_rate": None,
                "change": None,
                "trend": "unknown",
                "rate_type": "unknown",
                "_fallback": True,
                "_fallback_source": "last_snapshot",
                "source": "last_snapshot",
                "data_as_of": snap.get("timestamp"),
                "timeframe": timeframe,
            }
        return {"error": "No Fed Funds Rate data available", "timeframe": timeframe}

    # Use target for display when available and recent; else effective
    if target_rate is not None:
        current_rate = round(target_rate, 2)
        rate_type = "target"
        latest_date = target_date
        df_trend = df_target if len(df_target) >= 2 else df_eff
    else:
        latest = df_eff.iloc[-1]
        current_rate = round(float(latest["value"]), 2)
        rate_type = "effective"
        latest_date = latest["date"].strftime("%Y-%m-%d")
        df_trend = df_eff

    prev_rate = None
    change = None
    trend = "stable"
    if len(df_trend) >= 2:
        prev_val = float(df_trend.iloc[-2]["value"])
        curr_val = float(df_trend.iloc[-1]["value"])
        prev_rate = round(prev_val, 2)
        change = round(curr_val - prev_val, 2)
        if change > 0.1:
            trend = "rising"
        elif change < -0.1:
            trend = "falling"

    result = {
        "current_rate": current_rate,
        "previous_rate": prev_rate,
        "change": change,
        "trend": trend,
        "rate_type": rate_type,
        "latest_date": latest_date,
        "source": "FRED",
        "data_as_of": latest_date,
        "timeframe": timeframe,
    }
    logger.info("Fed Funds Rate: %.2f%% (%s, trend=%s, date=%s)", current_rate, rate_type, trend, latest_date)
    return result


def get_jobs_data(timeframe: str = "current") -> Dict:
    """Get employment data from FRED: Unemployment Rate, Non-Farm Payrolls, Initial Claims.

    Returns unemployment_rate, unemployment_trend, nfp_change (MoM thousands),
    initial_claims, and claims_trend.
    """
    effective_start = (datetime.now() - timedelta(days=max(180, TIMEFRAME_DAYS.get(timeframe, 90)))).strftime("%Y-%m-%d")

    result: Dict = {"timeframe": timeframe, "source": "FRED"}

    # Unemployment Rate (UNRATE) — monthly
    df_ur = get_fred_data("UNRATE", start_date=effective_start)
    if not df_ur.empty:
        latest = df_ur.iloc[-1]
        result["unemployment_rate"] = round(float(latest["value"]), 1)
        result["unemployment_date"] = latest["date"].strftime("%Y-%m-%d")
        result["data_as_of"] = latest["date"].strftime("%Y-%m-%d")
        if len(df_ur) >= 2:
            prev = float(df_ur.iloc[-2]["value"])
            diff = result["unemployment_rate"] - prev
            result["unemployment_trend"] = "rising" if diff > 0.1 else "falling" if diff < -0.1 else "stable"
        else:
            result["unemployment_trend"] = "unknown"
        # Past three monthly prints + 3-month average (for monthly analysis UI)
        n = len(df_ur)
        hist3 = []
        for i in range(min(3, n)):
            row = df_ur.iloc[-1 - i]
            hist3.append({
                "date": row["date"].strftime("%Y-%m-%d"),
                "rate": round(float(row["value"]), 1),
            })
        result["unemployment_history_3"] = list(reversed(hist3))
        if n >= 3:
            result["unemployment_3m_avg"] = round(
                float(df_ur.iloc[-3:]["value"].astype(float).mean()), 2
            )
        if n >= 4:
            latest_r = float(df_ur.iloc[-1]["value"])
            r3ago = float(df_ur.iloc[-4]["value"])
            d3 = latest_r - r3ago
            result["unemployment_trend_3m"] = (
                "rising" if d3 > 0.05 else "falling" if d3 < -0.05 else "stable"
            )
        logger.info("Unemployment Rate: %.1f%% (trend=%s)", result["unemployment_rate"], result["unemployment_trend"])
    else:
        last_val = _get_last_snapshot_field("unemployment_rate")
        if last_val is not None:
            result["unemployment_rate"] = last_val
            result["unemployment_trend"] = "unknown"
            result["_fallback"] = True
            logger.warning("UNRATE unavailable; using snapshot fallback: %s", last_val)
        else:
            result["unemployment_rate"] = None
            result["unemployment_trend"] = "unknown"
            logger.warning("No unemployment rate data available")

    # Non-Farm Payrolls (PAYEMS) — monthly, thousands of persons
    df_nfp = get_fred_data("PAYEMS", start_date=effective_start)
    if not df_nfp.empty and len(df_nfp) >= 2:
        latest_nfp = float(df_nfp.iloc[-1]["value"])
        prev_nfp = float(df_nfp.iloc[-2]["value"])
        result["nfp_change"] = round(latest_nfp - prev_nfp, 0)
        result["nfp_date"] = df_nfp.iloc[-1]["date"].strftime("%Y-%m-%d")
        logger.info("NFP MoM change: %+.0f thousand", result["nfp_change"])
    else:
        last_nfp = _get_last_snapshot_field("nfp_change")
        result["nfp_change"] = last_nfp
        if last_nfp is not None:
            result["_nfp_fallback"] = True

    # Initial Jobless Claims (ICSA) — weekly
    df_claims = get_fred_data("ICSA", start_date=effective_start)
    if not df_claims.empty:
        latest_claims = float(df_claims.iloc[-1]["value"])
        result["initial_claims"] = round(latest_claims, 0)
        result["claims_date"] = df_claims.iloc[-1]["date"].strftime("%Y-%m-%d")
        if len(df_claims) >= 5:
            avg_4w = df_claims.iloc[-5:-1]["value"].mean()
            result["claims_trend"] = "rising" if latest_claims > avg_4w * 1.05 else "falling" if latest_claims < avg_4w * 0.95 else "stable"
        else:
            result["claims_trend"] = "unknown"
        logger.info("Initial Claims: %.0f (trend=%s)", latest_claims, result.get("claims_trend"))
    else:
        result["initial_claims"] = None
        result["claims_trend"] = "unknown"

    return result


def get_gdp_data(timeframe: str = "current") -> Dict:
    """Get Real GDP growth rate from FRED.

    Uses A191RL1Q225SBEA (Real GDP % change, quarterly, annualized).
    Quarterly data — freshness check should allow up to 120 days.
    """
    effective_start = (datetime.now() - timedelta(days=500)).strftime("%Y-%m-%d")
    df = get_fred_data("A191RL1Q225SBEA", start_date=effective_start)

    if df.empty:
        last_val = _get_last_snapshot_field("gdp_growth_rate")
        if last_val is not None:
            logger.warning("No GDP data from FRED; using snapshot fallback: %s", last_val)
            return {
                "gdp_growth_rate": last_val,
                "gdp_trend": "unknown",
                "_fallback": True,
                "source": "last_snapshot",
                "timeframe": timeframe,
            }
        logger.warning("No GDP data available")
        return {"error": "No GDP data available", "timeframe": timeframe}

    latest = df.iloc[-1]
    growth_rate = round(float(latest["value"]), 1)
    latest_date = latest["date"].strftime("%Y-%m-%d")

    trend = "contracting" if growth_rate < 0 else "decelerating" if growth_rate < 2.0 else "stable" if growth_rate < 3.0 else "accelerating"
    if len(df) >= 2:
        prev_rate = float(df.iloc[-2]["value"])
        if growth_rate < prev_rate - 0.5:
            trend = "decelerating"
        elif growth_rate > prev_rate + 0.5:
            trend = "accelerating"

    result = {
        "gdp_growth_rate": growth_rate,
        "gdp_trend": trend,
        "latest_date": latest_date,
        "source": "FRED",
        "data_as_of": latest_date,
        "timeframe": timeframe,
    }
    logger.info("GDP growth: %.1f%% (trend=%s, date=%s)", growth_rate, trend, latest_date)
    return result


def get_dxy_from_fred_trade_weighted(timeframe: str = "current") -> Dict:
    """FRED DTWEXBGS (trade-weighted broad USD) when Yahoo DXY tickers fail.

    Level is scaled (~×0.88) so it sits in a DXY-like band for scoring thresholds.
    """
    if not FRED_API_KEY:
        return {"error": "FRED_API_KEY missing", "timeframe": timeframe}
    days = max(500, TIMEFRAME_DAYS.get(timeframe, 120) * 4)
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    df = pd.DataFrame()
    for sort_o in ("asc", "desc"):
        df = get_fred_data("DTWEXBGS", start_date=start, timeframe=timeframe, sort_order=sort_o)
        if not df.empty:
            break
    if df.empty:
        return {"error": "DTWEXBGS unavailable", "timeframe": timeframe}

    d = df.sort_values("date").reset_index(drop=True)
    latest = d.iloc[-1]
    tw_latest = float(latest["value"])
    latest_dt = pd.Timestamp(latest["date"]).normalize()

    if timeframe == "month" and len(d) >= 2:
        comp_row = _fred_observation_on_or_before_months_ago(d, 1)
    elif len(d) >= 2:
        comp_row = d.iloc[-2]
    else:
        comp_row = latest

    tw_comp = float(comp_row["value"])
    chg = ((tw_latest - tw_comp) / tw_comp * 100) if tw_comp else 0.0
    level_scale = 104.0 / 118.0
    level = tw_latest * level_scale

    def _ds(row) -> str:
        x = row["date"]
        return x.strftime("%Y-%m-%d") if hasattr(x, "strftime") else str(x)[:10]

    out = {
        "current_price": round(level, 2),
        "date": _ds(latest),
        "data_as_of": _ds(latest),
        "comparison_date": _ds(comp_row),
        "change": round(chg, 2),
        "change_label": _CHANGE_LABELS.get(timeframe, ""),
        "change_unit": "percent",
        "trend": "weakening" if chg < 0 else "strengthening" if chg > 0 else "stable",
        "timeframe": timeframe,
        "source": "FRED_DTWEXBGS",
        "_fallback": True,
        "_note": "Broad trade-weighted USD; level scaled to approximate DXY",
    }

    # Rolling ~1 calendar month on the same series (TradingView-style 1M vs MTD).
    cutoff_1m = latest_dt - pd.DateOffset(months=1)
    past_1m = d[pd.to_datetime(d["date"]).dt.normalize() <= cutoff_1m]
    if not past_1m.empty and tw_latest:
        comp_1m = past_1m.iloc[-1]
        tw_1m = float(comp_1m["value"])
        if tw_1m:
            chg_r = ((tw_latest - tw_1m) / tw_1m) * 100.0
            out["change_rolling_1m"] = round(chg_r, 2)
            out["change_rolling_1m_label"] = "1M"
            out["comparison_date_rolling_1m"] = _ds(comp_1m)

    return out


def get_pmi_data(timeframe: str = "current") -> Dict:
    """Get ISM Manufacturing PMI from FRED (NAPM series).

    PMI > 50 = expansion, < 50 = contraction. A key leading indicator.
    Tries multiple request shapes (sort order, long history, no sort) to avoid FRED 400 quirks.
    Fallback: Chicago Fed national activity index (CFNAI) scaled to ~PMI-like
    50-center only when NAPM is unavailable (documented proxy, not ISM).
    """
    # Prefer ISM Manufacturing PMI (NAPM). If unavailable, try ISM Manufacturing New Orders
    # (NAPMNO) — same 50 diffusion scale. CFNAI remains last-resort proxy.
    long_start = "1990-01-01"
    df = pd.DataFrame()
    used_series: Optional[str] = None
    for sid in ("NAPM", "NAPMNO"):
        tdf = get_fred_data(sid, start_date=long_start, timeframe=timeframe, sort_order="asc")
        if not tdf.empty:
            df = tdf
            used_series = sid
            break

    if df.empty:
        # CFNAI 3-month moving average: negative = below trend, positive = above; map loosely to PMI scale
        df_cf = get_fred_data("CFNAI", start_date=long_start, timeframe=timeframe, sort_order="asc")
        if not df_cf.empty:
            latest = df_cf.iloc[-1]
            cfv = float(latest["value"])
            latest_date = latest["date"].strftime("%Y-%m-%d")
            # Map CFNAI roughly [-0.5, +0.5] -> PMI [45, 55] (center 50)
            pmi_proxy = 50.0 + max(-5.0, min(5.0, cfv * 10.0))
            logger.warning(
                "PMI NAPM unavailable; using CFNAI proxy -> synthetic PMI %.1f (date=%s)",
                pmi_proxy,
                latest_date,
            )
            return {
                "pmi_value": round(pmi_proxy, 1),
                "pmi_trend": "stable",
                "pmi_status": "expansion" if pmi_proxy >= 50 else "contraction",
                "latest_date": latest_date,
                "source": "FRED_CFNAI_proxy",
                "data_as_of": latest_date,
                "timeframe": timeframe,
                "_fallback": True,
                "_proxy_note": "CFNAI scaled to PMI-like level; not ISM Manufacturing PMI",
            }

    if df.empty:
        last_val = _get_last_snapshot_field("pmi_value")
        if last_val is not None:
            logger.warning("No PMI data from FRED; using snapshot fallback: %s", last_val)
            return {
                "pmi_value": float(last_val),
                "pmi_trend": "unknown",
                "pmi_status": "expansion" if float(last_val) >= 50 else "contraction",
                "latest_date": datetime.now().strftime("%Y-%m-%d"),
                "_fallback": True,
                "source": "last_snapshot",
                "timeframe": timeframe,
            }
        logger.warning("PMI unavailable; using neutral placeholder (50) so pipeline continues")
        today = datetime.now().strftime("%Y-%m-%d")
        return {
            "pmi_value": 50.0,
            "pmi_trend": "stable",
            "pmi_status": "neutral",
            "latest_date": today,
            "data_as_of": today,
            "_fallback": True,
            "source": "neutral_placeholder",
            "timeframe": timeframe,
        }

    latest = df.iloc[-1]
    pmi_value = round(float(latest["value"]), 1)
    latest_date = latest["date"].strftime("%Y-%m-%d")

    pmi_status = "expansion" if pmi_value >= 50 else "contraction"
    pmi_trend = "stable"
    if len(df) >= 2:
        prev_pmi = float(df.iloc[-2]["value"])
        diff = pmi_value - prev_pmi
        pmi_trend = "rising" if diff > 0.5 else "falling" if diff < -0.5 else "stable"

    result = {
        "pmi_value": pmi_value,
        "pmi_trend": pmi_trend,
        "pmi_status": pmi_status,
        "latest_date": latest_date,
        "source": f"FRED:{used_series}" if used_series else "FRED",
        "data_as_of": latest_date,
        "timeframe": timeframe,
    }
    if used_series == "NAPMNO":
        result["_proxy_note"] = "ISM Manufacturing New Orders (NAPMNO); headline PMI proxy when NAPM unavailable"
    logger.info(
        "PMI (%s): %.1f (%s, trend=%s, date=%s)",
        used_series or "?",
        pmi_value,
        pmi_status,
        pmi_trend,
        latest_date,
    )
    return result


def get_m2_money_supply(timeframe: str = "current") -> Dict:
    """Get M2 Money Stock from FRED (M2SL series, seasonally adjusted).

    M2 expanding = more liquidity = bullish for BTC.
    M2 contracting = tightening = bearish.
    """
    effective_start = (datetime.now() - timedelta(days=max(400, TIMEFRAME_DAYS.get(timeframe, 90)))).strftime("%Y-%m-%d")
    df = get_fred_data("M2SL", start_date=effective_start)

    if df.empty:
        last_trend = _get_last_snapshot_field("m2_trend")
        if last_trend is not None:
            logger.warning("No M2 data from FRED; using snapshot fallback trend: %s", last_trend)
            return {
                "m2_value": None,
                "m2_change": None,
                "m2_trend": last_trend,
                "_fallback": True,
                "source": "last_snapshot",
                "timeframe": timeframe,
            }
        logger.warning("No M2 money supply data available")
        return {"error": "No M2 data available", "timeframe": timeframe}

    latest = df.iloc[-1]
    m2_value = round(float(latest["value"]) / 1000, 2)  # Convert billions to trillions
    latest_date = latest["date"].strftime("%Y-%m-%d")

    m2_change = None
    m2_trend = "stable"
    if len(df) >= 2:
        prev = float(df.iloc[-2]["value"])
        current = float(latest["value"])
        m2_change = round(((current - prev) / prev) * 100, 2)
        # Qualify trend: small positive = "slight expansion" so client sees nuance (weak M2 growth in tight-policy periods)
        if m2_change > 0.5:
            m2_trend = "expanding"
        elif m2_change > 0.1:
            m2_trend = "slight expansion"
        elif m2_change < -0.5:
            m2_trend = "contracting"
        elif m2_change < -0.1:
            m2_trend = "slight contraction"
        else:
            m2_trend = "stable"

    # Also compute YoY change if enough data
    m2_yoy = None
    if len(df) >= 13:
        year_ago = float(df.iloc[-13]["value"])
        current = float(latest["value"])
        m2_yoy = round(((current - year_ago) / year_ago) * 100, 2)

    result = {
        "m2_value": m2_value,
        "m2_change": m2_change,
        "m2_yoy_change": m2_yoy,
        "m2_trend": m2_trend,
        "latest_date": latest_date,
        "source": "FRED",
        "data_as_of": latest_date,
        "timeframe": timeframe,
    }
    logger.info("M2 Money Supply: $%.2fT (MoM=%s%%, trend=%s, date=%s)", m2_value, m2_change, m2_trend, latest_date)
    return result


def get_financial_stress(timeframe: str = "current") -> Dict:
    """Get St. Louis Fed Financial Stress Index (STLFSI4) and ICE BofA HY OAS (BAMLH0A0HYM2).

    STLFSI4: 0 = normal, >1 = elevated stress, >2 = crisis-level.
    HY OAS:  credit spread in basis points — wider = more stress.
    """
    effective_start = (datetime.now() - timedelta(days=max(400, TIMEFRAME_DAYS.get(timeframe, 90)))).strftime("%Y-%m-%d")

    stress_idx = None
    stress_trend = "stable"
    stress_date = None
    try:
        df = get_fred_data("STLFSI4", start_date=effective_start)
        if not df.empty:
            stress_idx = round(float(df.iloc[-1]["value"]), 3)
            stress_date = df.iloc[-1]["date"]
            if len(df) >= 2:
                prev = float(df.iloc[-2]["value"])
                if stress_idx > prev + 0.1:
                    stress_trend = "rising"
                elif stress_idx < prev - 0.1:
                    stress_trend = "falling"
    except Exception as e:
        logger.warning("STLFSI4 fetch failed: %s", e)

    hy_oas = None
    hy_trend = "stable"
    hy_date = None
    try:
        df2 = get_fred_data("BAMLH0A0HYM2", start_date=effective_start)
        if not df2.empty:
            hy_oas = round(float(df2.iloc[-1]["value"]), 2)
            hy_date = df2.iloc[-1]["date"]
            if len(df2) >= 2:
                prev2 = float(df2.iloc[-2]["value"])
                if hy_oas > prev2 + 0.05:
                    hy_trend = "widening"
                elif hy_oas < prev2 - 0.05:
                    hy_trend = "tightening"
    except Exception as e:
        logger.warning("BAMLH0A0HYM2 fetch failed: %s", e)

    if stress_idx is None and hy_oas is None:
        return {"error": "No financial stress data available", "timeframe": timeframe}

    level = "normal"
    if stress_idx is not None:
        if stress_idx > 2:
            level = "crisis"
        elif stress_idx > 1:
            level = "elevated"
        elif stress_idx > 0.5:
            level = "above_average"

    latest_date = None
    dts = [d for d in (stress_date, hy_date) if d is not None]
    if dts:
        latest_dt = max(pd.to_datetime(x) for x in dts)
        latest_date = latest_dt.strftime("%Y-%m-%d")

    return {
        "stress_index": stress_idx,
        "stress_trend": stress_trend,
        "hy_oas": hy_oas,
        "hy_trend": hy_trend,
        "level": level,
        "latest_date": latest_date,
        "data_as_of": latest_date,
        "source": "FRED",
        "timeframe": timeframe,
    }


def get_10y_breakeven_expectation(timeframe: str = "current") -> Dict:
    """10-year breakeven inflation (T10YIE) for real yield = nominal 10Y - breakeven."""
    effective_start = (datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d")
    df = get_fred_data("T10YIE", start_date=effective_start)
    if df.empty:
        return {"error": "No T10YIE data", "timeframe": timeframe}
    latest = df.iloc[-1]
    v = round(float(latest["value"]), 3)
    ds = latest["date"].strftime("%Y-%m-%d")
    return {
        "value": v,
        "latest_date": ds,
        "data_as_of": ds,
        "timeframe": timeframe,
        "source": "FRED",
    }


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
        "source": "FRED",
        "data_as_of": latest["date"].strftime("%Y-%m-%d"),
        "timeframe": timeframe
    }


