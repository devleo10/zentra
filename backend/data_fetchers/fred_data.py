"""
Fetch macroeconomic data from FRED API and BLS API v2.

CPI priority:
  1. BLS API v2 (official source, returns MoM/YoY calculations natively)
  2. FRED API (fallback — same underlying data, slightly delayed)
"""
import os
import re
import requests
import pandas as pd

from utils.http_retry import get_with_retries, post_with_retries
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Literal, Tuple
from dotenv import load_dotenv
import logging


def _with_obs_fetch(payload: Dict[str, Any], observation_ts) -> Dict[str, Any]:
    """Attach observation and fetch timestamps for auditing."""
    result = dict(payload)
    try:
        if hasattr(observation_ts, "isoformat"):
            result["observed_at"] = observation_ts.isoformat()
        else:
            result["observed_at"] = str(observation_ts) if observation_ts is not None else None
    except Exception:
        result["observed_at"] = None
    result["fetched_at"] = datetime.utcnow().isoformat()
    return result

try:
    from . import trusted_market_apis
except Exception:
    try:
        from data_fetchers import trusted_market_apis  # type: ignore
    except Exception:
        trusted_market_apis = None

load_dotenv()

logger = logging.getLogger("btc_macro.data_fetchers.fred")

FRED_API_KEY = os.getenv("FRED_API_KEY")
FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"
STRICT_LIVE_OFFICIAL_ONLY = os.getenv("STRICT_LIVE_OFFICIAL_ONLY", "0").strip().lower() not in {"0", "false", "no"}
ALPHAVANTAGE_API_KEY = os.getenv("ALPHAVANTAGE_API_KEY") or os.getenv("ALPHA_VANTAGE_API_KEY")
ALPHAVANTAGE_URL = "https://www.alphavantage.co/query"
TRADINGVIEW_SCANNER_URL = "https://scanner.tradingview.com/america/scan"
ISM_PMI_URL = "https://www.ismworld.org/supply-management-news-and-reports/reports/ism-pmi-reports/pmi/"
TRADINGECONOMICS_US_PMI_PAGE = "https://tradingeconomics.com/united-states/manufacturing-pmi"
INVESTING_US_ISM_PMI_PAGE = "https://www.investing.com/economic-calendar/ism-manufacturing-pmi-173"
try:
    PMI_RELEASE_MAX_AGE_DAYS = int((os.getenv("PMI_RELEASE_MAX_AGE_DAYS") or "45").strip() or "45")
except ValueError:
    PMI_RELEASE_MAX_AGE_DAYS = 45
EIA_API_KEY = os.getenv("EIA_API_KEY")
EIA_V2_SERIES_URL = "https://api.eia.gov/v2/seriesid"
EIA_V1_SERIES_URL = "https://api.eia.gov/series/"

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


def _get_eia_series_data(series_id: str) -> pd.DataFrame:
    """Fetch EIA time series using v2 seriesid, then legacy v1 as fallback."""
    if not EIA_API_KEY:
        return pd.DataFrame()

    def _norm_date(value: str) -> Optional[pd.Timestamp]:
        for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y-%m", "%Y%m"):
            try:
                return pd.Timestamp(datetime.strptime(str(value), fmt))
            except Exception:
                continue
        try:
            return pd.to_datetime(value, errors="coerce")
        except Exception:
            return None

    try:
        resp = get_with_retries(
            f"{EIA_V2_SERIES_URL}/{series_id}",
            params={"api_key": EIA_API_KEY},
            timeout=20,
        )
        body = resp.json()
        rows = (((body or {}).get("response") or {}).get("data") or [])
        if rows:
            data = []
            for row in rows:
                dt = _norm_date(row.get("period"))
                val = pd.to_numeric(row.get("value"), errors="coerce")
                if pd.notna(dt) and pd.notna(val):
                    data.append({"date": pd.Timestamp(dt), "value": float(val)})
            if data:
                return pd.DataFrame(data).sort_values("date").reset_index(drop=True)
    except Exception as e:
        logger.warning("EIA v2 fetch failed for %s: %s", series_id, e)

    try:
        resp = get_with_retries(
            EIA_V1_SERIES_URL,
            params={"api_key": EIA_API_KEY, "series_id": series_id},
            timeout=20,
        )
        body = resp.json()
        series = (body.get("series") or [None])[0] or {}
        rows = series.get("data") or []
        data = []
        for row in rows:
            if not isinstance(row, (list, tuple)) or len(row) < 2:
                continue
            dt = _norm_date(row[0])
            val = pd.to_numeric(row[1], errors="coerce")
            if pd.notna(dt) and pd.notna(val):
                data.append({"date": pd.Timestamp(dt), "value": float(val)})
        if data:
            return pd.DataFrame(data).sort_values("date").reset_index(drop=True)
    except Exception as e:
        logger.warning("EIA v1 fetch failed for %s: %s", series_id, e)

    return pd.DataFrame()

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
    return _three_month_mom_stats_from_fred_df(df, "cpi")


def _three_month_mom_stats_from_fred_df(df: pd.DataFrame, prefix: str) -> Dict:
    """Average of last 3 monthly MoM % changes vs prior 3 for any monthly series."""
    if df is None or len(df) < 4:
        return {}
    moms = []
    for i in range(1, min(20, len(df))):
        curr = float(df.iloc[-i]["value"])
        prev = float(df.iloc[-i - 1]["value"])
        if prev:
            moms.append((curr - prev) / prev * 100.0)
    if len(moms) < 3:
        return {}
    avg3 = sum(moms[:3]) / 3.0
    prior3 = None
    if len(moms) >= 6:
        prior3 = sum(moms[3:6]) / 3.0
    elif len(moms) >= 4:
        prior_tail = moms[3:]
        prior3 = sum(prior_tail) / len(prior_tail)
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
        f"{prefix}_mom_avg_3m": round(avg3, 3),
        f"{prefix}_mom_avg_3m_prior": round(prior3, 3) if prior3 is not None else None,
        f"{prefix}_mom_avg_3m_trend": tr,
    }

def _three_month_value_stats_from_fred_df(df: pd.DataFrame, prefix: str) -> Dict:
    """3-month average of the underlying *value* series vs prior 3 months.

    This is for displaying the average index/level itself (not the MoM %).
    """
    if df is None or len(df) < 3:
        return {}
    d = df.sort_values("date").copy()
    try:
        vals = [float(v) for v in d["value"].tolist() if pd.notna(v)]
    except Exception:
        return {}
    if len(vals) < 3:
        return {}
    last3 = vals[-3:]
    avg3 = sum(last3) / 3.0
    prior3 = None
    if len(vals) >= 6:
        prior = vals[-6:-3]
        if len(prior) == 3:
            prior3 = sum(prior) / 3.0
    return {
        f"{prefix}_value_avg_3m": round(avg3, 3),
        f"{prefix}_value_avg_3m_prior": round(prior3, 3) if prior3 is not None else None,
    }


def _cpi_three_month_mom_stats_from_bls_headline(headline: list) -> Dict:
    """Same 3-month MoM average logic; BLS `headline` rows are newest-first."""
    return _three_month_mom_stats_from_bls_rows(headline, "cpi")


def _three_month_mom_stats_from_bls_rows(rows: list, prefix: str) -> Dict:
    """3-month average of published monthly changes; BLS rows are newest-first."""
    if not rows or len(rows) < 4:
        return {}
    moms = []
    for i, row in enumerate(rows[:24]):
        try:
            pct_changes = row.get("calculations", {}).get("pct_changes", {})
            if "1" in pct_changes:
                moms.append(float(pct_changes["1"]))
                continue
        except Exception:
            pass
        try:
            curr = float(row["value"])
            prev = float(rows[i + 1]["value"])
        except Exception:
            break
        if prev:
            moms.append((curr - prev) / prev * 100.0)
    if len(moms) < 3:
        return {}
    avg3 = sum(moms[:3]) / 3.0
    prior3 = None
    if len(moms) >= 6:
        prior3 = sum(moms[3:6]) / 3.0
    elif len(moms) >= 4:
        prior_tail = moms[3:]
        prior3 = sum(prior_tail) / len(prior_tail)
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
        f"{prefix}_mom_avg_3m": round(avg3, 3),
        f"{prefix}_mom_avg_3m_prior": round(prior3, 3) if prior3 is not None else None,
        f"{prefix}_mom_avg_3m_trend": tr,
    }

def _three_month_value_stats_from_bls_rows(rows: list, prefix: str) -> Dict:
    """3-month average of the underlying *value* series vs prior 3 months.

    BLS rows are newest-first.
    """
    if not rows or len(rows) < 3:
        return {}
    vals = []
    for row in rows[:24]:
        try:
            v = float(row.get("value"))
        except Exception:
            continue
        vals.append(v)
        if len(vals) >= 6:
            break
    if len(vals) < 3:
        return {}
    avg3 = sum(vals[:3]) / 3.0
    prior3 = None
    if len(vals) >= 6:
        prior3 = sum(vals[3:6]) / 3.0
    return {
        f"{prefix}_value_avg_3m": round(avg3, 3),
        f"{prefix}_value_avg_3m_prior": round(prior3, 3) if prior3 is not None else None,
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
        resp = get_with_retries(FRED_BASE_URL, params=params, timeout=15)
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
        resp = post_with_retries(
            BLS_API_URL,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=20,
            max_attempts=3,
            backoff_base=2.0,
        )
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

        # Core CPI MoM/YoY
        core_latest_value = None
        core_mom = None
        core_yoy = None
        if core:
            core_latest = core[0]
            try:
                core_latest_value = float(core_latest.get("value"))
            except (TypeError, ValueError):
                core_latest_value = None
            core_calcs = core_latest.get("calculations", {}).get("pct_changes", {})
            core_mom = float(core_calcs.get("1", 0)) if "1" in core_calcs else None
            core_yoy = float(core_calcs.get("12", 0)) if "12" in core_calcs else None

        result = {
            "latest_value": latest_value,
            "latest_date": latest_date,
            "mom_change": round(mom_change, 3),
            "yoy_rate": round(yoy_rate, 2),
            "core_latest_value": round(core_latest_value, 3) if core_latest_value is not None else None,
            "core_mom_change": round(core_mom, 3) if core_mom is not None else None,
            "core_yoy_rate": round(core_yoy, 2) if core_yoy is not None else None,
            "change": round(mom_change, 3),
            "trend": "falling" if mom_change < 0 else "rising" if mom_change > 0 else "flat",
            "source": "BLS",
            "_validation": {"validated": True, "reasons": []},
        }
        result.update(_cpi_three_month_mom_stats_from_bls_headline(headline))
        result.update(_three_month_mom_stats_from_bls_rows(core, "core_cpi"))
        # Average of the index levels themselves (not MoM %) for display.
        result.update(_three_month_value_stats_from_bls_rows(headline, "cpi"))
        result.update(_three_month_value_stats_from_bls_rows(core, "core_cpi"))
        logger.info(
            "BLS CPI: index=%.3f MoM=%+.3f%% YoY=%.2f%% Core MoM=%s%% Core YoY=%s%% (date=%s)",
            latest_value, mom_change, yoy_rate,
            f"{core_mom:.3f}" if core_mom is not None else "N/A",
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
    # Fetch 540 days to guarantee 13+ monthly observations for YoY + 6 for 3m prior avg
    start_lookback = (datetime.now() - timedelta(days=540)).strftime("%Y-%m-%d")
    df = get_fred_data("CPIAUCSL", start_date=start_lookback)
    core_df = get_fred_data("CPILFESL", start_date=start_lookback)
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
                "core_latest_value": None,
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

    if timeframe == "year" and yoy_rate is not None and len(df) >= 13:
        prev_value = df.iloc[-13]
        change = yoy_rate
        timeframe_label = "yoy"
    else:
        prev_value = prev_month if len(df) >= 2 else latest
        change = mom_change
        timeframe_label = "mom"

    result = {
        "latest_value": float(latest["value"]),
        "latest_date": latest["date"].strftime("%Y-%m-%d"),
        "comparison_date": prev_value["date"].strftime("%Y-%m-%d"),
        f"{timeframe_label}_change": round(change, 2),
        "change": round(change, 2),
        "mom_change": round(mom_change, 2),
        "yoy_rate": yoy_rate,
        "core_latest_value": None,
        "core_mom_change": None,
        "core_yoy_rate": None,
        "trend": "falling" if mom_change < 0 else "rising" if mom_change > 0 else "flat",
        "source": "FRED",
        "data_as_of": latest["date"].strftime("%Y-%m-%d"),
        "timeframe": timeframe
    }
    if not core_df.empty:
        core_latest = core_df.iloc[-1]
        result["core_latest_value"] = round(float(core_latest["value"]), 3)
        result["core_mom_change"] = 0.0
        if len(core_df) >= 2:
            core_prev = core_df.iloc[-2]
            result["core_mom_change"] = round(((core_latest["value"] - core_prev["value"]) / core_prev["value"]) * 100, 2)
        if len(core_df) >= 13:
            core_year_ago = core_df.iloc[-13]
            result["core_yoy_rate"] = round(((core_latest["value"] - core_year_ago["value"]) / core_year_ago["value"]) * 100, 2)
        result.update(_three_month_mom_stats_from_fred_df(core_df, "core_cpi"))
        result.update(_three_month_value_stats_from_fred_df(core_df, "core_cpi"))

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
    result.update(_three_month_value_stats_from_fred_df(df, "cpi"))

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
    start_date = (datetime.now() - timedelta(days=540)).strftime("%Y-%m-%d")
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

    # Low-frequency macro print: current/week/month all display the latest MoM print.
    if timeframe == "year" and len(df) >= 13:
        year_ago = df.iloc[-13]
        change = ((latest["value"] - year_ago["value"]) / year_ago["value"]) * 100 if year_ago["value"] else 0
        prev_value = year_ago
        timeframe_label = "yoy"
    else:
        prev_value = prev_month
        change = mom_change
        timeframe_label = "mom"

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
    result.update(_three_month_mom_stats_from_fred_df(df, "pce"))
    result.update(_three_month_value_stats_from_fred_df(df, "pce"))

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
            if timeframe == "month":
                prev_2y = _fred_observation_on_or_before_months_ago(df_2y, 1)
            else:
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
            if timeframe == "month":
                prev_10y = _fred_observation_on_or_before_months_ago(df_10y, 1)
            else:
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
    if not STRICT_LIVE_OFFICIAL_ONLY:
        try:
            import yfinance as yf
            ticker = yf.Ticker("CL=F")
            period_map = {"current": "1mo", "week": "1mo", "month": "3mo", "year": "2y"}
            if timeframe == "current":
                hist = ticker.history(period="5d", interval="1m", prepost=True)
            else:
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
                return _with_obs_fetch(
                    {
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
                    },
                    h.index[-1],
                )
        except Exception as e:
            logger.warning("Oil Yahoo Finance primary source failed: %s", e)

    df = _get_eia_series_data("PET.RWTC.D")
    if not df.empty:
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
            "source": "EIA (PET.RWTC.D)",
            "data_as_of": latest["date"].strftime("%Y-%m-%d"),
            "timeframe": timeframe,
        }
        logger.info("Oil fetched from EIA: $%.2f (change=%+.2f%%, date=%s)", result["current_price"], change, result["latest_date"])
        return _with_obs_fetch(result, latest["date"])

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
    return _with_obs_fetch(result, latest["date"])


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
    """Get US manufacturing PMI with release-time priority and resilient fallback.

    Architecture:
    1) Primary: release-source path (economic calendar trigger + ISM scrape)
    2) Secondary: TradingEconomics API/page
    3) Delayed official/history fallback: FRED NAPM
    4) Final backups: EODHD / Investing / Alpha Vantage / TradingView
    """
    release_triggered = _get_pmi_from_calendar_trigger(timeframe)
    if release_triggered:
        return release_triggered

    ism = _get_pmi_from_ism_scrape(timeframe)
    if ism:
        logger.info("PMI primary source: ISM release page")
        return ism

    if trusted_market_apis is not None:
        te = trusted_market_apis.get_tradingeconomics_us_manufacturing_pmi()
        if te:
            result = _pmi_result(
                te["pmi_value"],
                te.get("date") or datetime.now().strftime("%Y-%m-%d"),
                te.get("source") or "TradingEconomics:PMI",
                timeframe,
                prev_value=te.get("previous_value"),
            )
            logger.info(
                "PMI secondary (TradingEconomics API): %.1f (%s, trend=%s, date=%s)",
                result["pmi_value"],
                result["pmi_status"],
                result["pmi_trend"],
                result["latest_date"],
            )
            return result

    te_web = _get_pmi_from_tradingeconomics_page(timeframe)
    if te_web:
        return te_web

    # FRED is still valuable, but can lag release-time updates.
    long_start = "1990-01-01"
    df = get_fred_data("NAPM", start_date=long_start, timeframe=timeframe, sort_order="asc")
    if not df.empty:
        latest = df.iloc[-1]
        latest_value = _safe_float(latest["value"])
        prev_value = _safe_float(df.iloc[-2]["value"]) if len(df) >= 2 else None
        if latest_value is not None:
            latest_date = latest["date"].strftime("%Y-%m-%d")
            result = _pmi_result(
                latest_value,
                latest_date,
                "FRED:NAPM",
                timeframe,
                prev_value=prev_value,
            )
            logger.info(
                "PMI delayed-series fallback (FRED NAPM): %.1f (%s, trend=%s, date=%s)",
                result["pmi_value"],
                result["pmi_status"],
                result["pmi_trend"],
                result["latest_date"],
            )
            return result

    if trusted_market_apis is not None:
        eod = trusted_market_apis.get_eodhd_us_manufacturing_pmi()
        if eod:
            result = _pmi_result(
                eod["pmi_value"],
                eod.get("date") or datetime.now().strftime("%Y-%m-%d"),
                eod.get("source") or "EODHD:PMI",
                timeframe,
                prev_value=eod.get("previous_value"),
            )
            logger.info(
                "PMI fallback (EODHD): %.1f (%s, trend=%s, date=%s)",
                result["pmi_value"],
                result["pmi_status"],
                result["pmi_trend"],
                result["latest_date"],
            )
            return result

    inv = _get_pmi_from_investing_page(timeframe)
    if inv:
        return inv

    alpha = _get_pmi_from_alphavantage(timeframe)
    if alpha:
        return alpha

    tv = _get_pmi_from_tradingview(timeframe)
    if tv:
        return tv

    logger.warning(
        "PMI unavailable from ISM/calendar, TradingEconomics API/page, FRED NAPM, EODHD, Investing, Alpha Vantage, and TradingView"
    )
    return {
        "error": "ISM Manufacturing PMI unavailable from configured sources",
        "source": "unavailable",
        "timeframe": timeframe,
    }


def _safe_float(value) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(out):
        return None
    if out == float("inf") or out == float("-inf"):
        return None
    return out


def _trend_from_values(current: float, previous: Optional[float]) -> str:
    if previous is None:
        return "stable"
    diff = current - previous
    return "rising" if diff > 0.5 else "falling" if diff < -0.5 else "stable"


def _pmi_result(
    pmi_value: float,
    latest_date: str,
    source: str,
    timeframe: str,
    *,
    prev_value: Optional[float] = None,
    proxy_note: Optional[str] = None,
) -> Dict:
    result = {
        "pmi_value": round(float(pmi_value), 1),
        "pmi_trend": _trend_from_values(float(pmi_value), prev_value),
        "pmi_status": "expansion" if float(pmi_value) >= 50 else "contraction",
        "latest_date": latest_date,
        "source": source,
        "data_as_of": latest_date,
        "timeframe": timeframe,
    }
    if prev_value is not None:
        pv = float(prev_value)
        result["previous_value"] = round(pv, 1)
        result["delta_value"] = round(float(pmi_value) - pv, 1)
    if proxy_note:
        result["_proxy_note"] = proxy_note
    return result


def _pmi_release_is_recent(date_text: Optional[str], max_age_days: int = PMI_RELEASE_MAX_AGE_DAYS) -> bool:
    if not date_text:
        return False
    dt = pd.to_datetime(date_text, errors="coerce")
    if pd.isna(dt):
        return False
    today = pd.Timestamp.utcnow().tz_localize(None).normalize()
    release_day = pd.Timestamp(dt)
    if release_day.tzinfo is not None:
        release_day = release_day.tz_convert(None)
    release_day = release_day.normalize()
    age_days = int((today - release_day).days)
    if age_days < -2:
        return False
    return age_days <= max(1, int(max_age_days))


def _tag_pmi_release_trigger(result: Dict, *, trigger_source: str, event_date: Optional[str], event_name: Optional[str]) -> Dict:
    tagged = dict(result)
    tagged["release_trigger"] = "economic_calendar"
    tagged["trigger_source"] = trigger_source
    if event_date:
        tagged["trigger_event_date"] = str(event_date)[:10]
    if event_name:
        tagged["trigger_event_name"] = event_name
    return tagged


def _get_pmi_from_calendar_trigger(timeframe: str) -> Optional[Dict]:
    """Calendar-first PMI trigger: detect release, then pull the latest print."""
    if trusted_market_apis is not None:
        try:
            calendar = trusted_market_apis.get_tradingeconomics_us_pmi_calendar_event()
        except Exception:
            calendar = None

        if isinstance(calendar, dict):
            event_date = str(calendar.get("date") or "")[:10] or None
            event_name = str(calendar.get("event_name") or "US Manufacturing PMI")
            trigger_source = str(calendar.get("source") or "TradingEconomics:calendar:US:Manufacturing PMI")
            actual = _safe_float(calendar.get("actual_value"))
            previous = _safe_float(calendar.get("previous_value"))

            if _pmi_release_is_recent(event_date):
                ism = _get_pmi_from_ism_scrape(timeframe)
                if ism:
                    ism_value = _safe_float(ism.get("pmi_value"))
                    if actual is None or (ism_value is not None and abs(ism_value - actual) <= 1.0):
                        logger.info("PMI release trigger: ISM scrape confirmed by calendar (%s)", event_date)
                        return _tag_pmi_release_trigger(
                            ism,
                            trigger_source=trigger_source,
                            event_date=event_date,
                            event_name=event_name,
                        )

                if actual is not None:
                    result = _pmi_result(
                        actual,
                        event_date or datetime.now().strftime("%Y-%m-%d"),
                        trigger_source,
                        timeframe,
                        prev_value=previous,
                    )
                    logger.info(
                        "PMI release trigger: using calendar actual %.1f (%s)",
                        result["pmi_value"],
                        result["latest_date"],
                    )
                    return _tag_pmi_release_trigger(
                        result,
                        trigger_source=trigger_source,
                        event_date=event_date,
                        event_name=event_name,
                    )

    investing = _get_pmi_from_investing_page(timeframe)
    if investing and _pmi_release_is_recent(investing.get("latest_date")):
        latest_date = str(investing.get("latest_date") or "")[:10] or None
        logger.info("PMI release trigger: Investing calendar latest release (%s)", latest_date)
        return _tag_pmi_release_trigger(
            investing,
            trigger_source="Investing:economic_calendar",
            event_date=latest_date,
            event_name="ISM Manufacturing PMI",
        )
    return None


def _snapshot_pmi_previous() -> Optional[float]:
    snap_val = _get_last_snapshot_field("pmi_value")
    return _safe_float(snap_val)


def _get_pmi_from_tradingeconomics_page(timeframe: str) -> Optional[Dict]:
    """Free fallback from TradingEconomics public PMI page metadata."""
    try:
        resp = get_with_retries(
            TRADINGECONOMICS_US_PMI_PAGE,
            timeout=20,
            max_attempts=2,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        text = resp.text or ""
        match = re.search(
            r"Manufacturing PMI in the United States .*? to ([0-9]+\.[0-9]+) points in ([A-Za-z]+) from ([0-9]+\.[0-9]+) points in ([A-Za-z]+) of ([0-9]{4})",
            text,
            re.IGNORECASE,
        )
        if not match:
            return None

        latest_val = _safe_float(match.group(1))
        prev_val = _safe_float(match.group(3))
        month_name = str(match.group(2) or "").strip()
        year_text = str(match.group(5) or "").strip()
        if latest_val is None:
            return None

        latest_date = datetime.now().strftime("%Y-%m-%d")
        try:
            dt = datetime.strptime(f"{month_name} {year_text}", "%B %Y")
            latest_date = dt.strftime("%Y-%m-01")
        except Exception:
            pass

        result = _pmi_result(
            latest_val,
            latest_date,
            "TradingEconomics:web",
            timeframe,
            prev_value=prev_val,
        )
        logger.info(
            "PMI fallback (TradingEconomics page): %.1f (%s, trend=%s, date=%s)",
            result["pmi_value"],
            result["pmi_status"],
            result["pmi_trend"],
            result["latest_date"],
        )
        return result
    except Exception as e:
        logger.debug("TradingEconomics page PMI fallback failed: %s", e)
        return None


def _get_pmi_from_investing_page(timeframe: str) -> Optional[Dict]:
    """Free fallback from Investing.com economic calendar event page."""
    try:
        resp = get_with_retries(
            INVESTING_US_ISM_PMI_PAGE,
            timeout=20,
            max_attempts=2,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        text = resp.text or ""

        actual_match = re.search(r'"latest_release"\s*:\s*\{\s*"actual"\s*:\s*([0-9]+\.[0-9]+)', text)
        if not actual_match:
            actual_match = re.search(r'"actual"\s*:\s*([0-9]+\.[0-9]+)', text)
        if not actual_match:
            return None

        latest_val = _safe_float(actual_match.group(1))
        if latest_val is None:
            return None

        prev_match = re.search(r'"latest_release"\s*:\s*\{[^\}]*"previous"\s*:\s*([0-9]+\.[0-9]+)', text)
        prev_val = _safe_float(prev_match.group(1)) if prev_match else _snapshot_pmi_previous()

        time_match = re.search(r'"latest_release"\s*:\s*\{[^\}]*"occurrence_time"\s*:\s*"([^"]+)"', text)
        latest_date = datetime.now().strftime("%Y-%m-%d")
        if time_match:
            dt = pd.to_datetime(time_match.group(1), errors="coerce")
            if pd.notna(dt):
                latest_date = pd.Timestamp(dt).strftime("%Y-%m-%d")

        result = _pmi_result(
            latest_val,
            latest_date,
            "Investing:ISM_PMI_event_173",
            timeframe,
            prev_value=prev_val,
        )
        logger.info(
            "PMI fallback (Investing page): %.1f (%s, trend=%s, date=%s)",
            result["pmi_value"],
            result["pmi_status"],
            result["pmi_trend"],
            result["latest_date"],
        )
        return result
    except Exception as e:
        logger.debug("Investing page PMI fallback failed: %s", e)
        return None


def _get_pmi_from_alphavantage(timeframe: str) -> Optional[Dict]:
    if not ALPHAVANTAGE_API_KEY:
        return None
    try:
        resp = get_with_retries(
            ALPHAVANTAGE_URL,
            params={"function": "ISM_MANUFACTURING", "apikey": ALPHAVANTAGE_API_KEY},
            timeout=20,
            max_attempts=2,
        )
        payload = resp.json()
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list) or not rows:
            return None

        parsed = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            value = _safe_float(
                row.get("value")
                if row.get("value") is not None
                else row.get("pmi")
                if row.get("pmi") is not None
                else row.get("manufacturing_pmi")
            )
            if value is None:
                continue
            date_text = (
                row.get("date")
                or row.get("timestamp")
                or row.get("period")
                or row.get("month")
            )
            date_parsed = pd.to_datetime(date_text, errors="coerce")
            parsed.append((date_parsed, value, date_text))

        if not parsed:
            return None

        parsed.sort(key=lambda x: x[0] if pd.notna(x[0]) else pd.Timestamp("1900-01-01"))
        latest_dt, latest_val, latest_text = parsed[-1]
        prev_val = parsed[-2][1] if len(parsed) >= 2 else _snapshot_pmi_previous()
        latest_date = (
            latest_dt.strftime("%Y-%m-%d")
            if pd.notna(latest_dt)
            else str(latest_text or datetime.now().strftime("%Y-%m-%d"))[:10]
        )

        result = _pmi_result(
            latest_val,
            latest_date,
            "AlphaVantage:ISM_MANUFACTURING",
            timeframe,
            prev_value=prev_val,
        )
        logger.info(
            "PMI fallback (Alpha Vantage): %.1f (%s, trend=%s, date=%s)",
            result["pmi_value"],
            result["pmi_status"],
            result["pmi_trend"],
            result["latest_date"],
        )
        return result
    except Exception as e:
        logger.debug("Alpha Vantage PMI fallback failed: %s", e)
        return None


def _get_pmi_from_tradingview(timeframe: str) -> Optional[Dict]:
    payload = {
        "symbols": {
            "tickers": ["ECONOMICS:USPMI"],
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

        first = rows[0] if isinstance(rows[0], dict) else {}
        vec = first.get("d") if isinstance(first, dict) else None
        if not isinstance(vec, list) or not vec:
            return None
        value = _safe_float(vec[0])
        if value is None:
            return None

        prev_val = _snapshot_pmi_previous()
        latest_date = datetime.now().strftime("%Y-%m-%d")
        result = _pmi_result(
            value,
            latest_date,
            "TradingView:ECONOMICS:USPMI",
            timeframe,
            prev_value=prev_val,
            proxy_note="Unofficial TradingView macro feed",
        )
        logger.info(
            "PMI fallback (TradingView): %.1f (%s, trend=%s)",
            result["pmi_value"],
            result["pmi_status"],
            result["pmi_trend"],
        )
        return result
    except Exception as e:
        logger.debug("TradingView PMI fallback failed: %s", e)
        return None


def _get_pmi_from_ism_scrape(timeframe: str) -> Optional[Dict]:
    try:
        resp = get_with_retries(ISM_PMI_URL, timeout=20, max_attempts=2)
        html = resp.text or ""
        match = re.search(r"PMI(?:\s*\u00ae)?[^\d]{0,30}(\d{2}\.\d)", html, re.IGNORECASE)
        if not match:
            match = re.search(r"Manufacturing\s+PMI[^\d]{0,30}(\d{2}\.\d)", html, re.IGNORECASE)
        if not match:
            return None

        value = _safe_float(match.group(1))
        if value is None:
            return None

        prev_val = _snapshot_pmi_previous()
        latest_date = datetime.now().strftime("%Y-%m-%d")
        result = _pmi_result(
            value,
            latest_date,
            "ISM:html",
            timeframe,
            prev_value=prev_val,
            proxy_note="Scraped from ISM report page",
        )
        logger.info(
            "PMI fallback (ISM scrape): %.1f (%s, trend=%s)",
            result["pmi_value"],
            result["pmi_status"],
            result["pmi_trend"],
        )
        return result
    except Exception as e:
        logger.debug("ISM scrape PMI fallback failed: %s", e)
        return None


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
    if timeframe == "month":
        prev_value = _fred_observation_on_or_before_months_ago(df, 1)
    else:
        prev_value = _fred_observation_on_or_before_calendar_days_ago(df, comparison_days)
    
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
