"""Release date helpers for key US macro indicators.

Source priority is dynamic:
1) API calendar/release endpoints when available (BEA, TradingEconomics)
2) Deterministic publication cadence rules as fallback

No fixed date lists are embedded in code.
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta
from functools import lru_cache
from typing import Any, Callable, Dict, Iterable, Optional, Sequence, Tuple

import requests

logger = logging.getLogger("btc_macro.release_calendar")

_BEA_RELEASE_DATES_URL = "https://apps.bea.gov/API/signup/release_dates.json"
_TE_CALENDAR_US_URL = "https://api.tradingeconomics.com/calendar/country/united%20states"
_HTTP_TIMEOUT = 20
_HTTP_HEADERS = {
    "User-Agent": "ZentraMacro/1.0",
    "Accept": "application/json",
}


def _parse_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None

    # ISO-like input (including datetime strings)
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except Exception:
        pass

    if len(raw) >= 10:
        try:
            return datetime.strptime(raw[:10], "%Y-%m-%d").date()
        except Exception:
            pass

    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(raw.replace(".", ""), fmt).date()
        except Exception:
            continue

    return None


def _iso(d: Optional[date]) -> Optional[str]:
    return d.isoformat() if d else None


def _year_month_add(year: int, month_1_12: int, delta_months: int) -> Tuple[int, int]:
    total = year * 12 + (month_1_12 - 1) + delta_months
    return total // 12, (total % 12) + 1


def _next_business_day(d: date) -> date:
    out = d
    while out.weekday() >= 5:  # 5=Sat, 6=Sun
        out += timedelta(days=1)
    return out


def _first_business_day(year: int, month_1_12: int) -> date:
    return _next_business_day(date(year, month_1_12, 1))


def _last_business_day(year: int, month_1_12: int) -> date:
    next_year, next_month = _year_month_add(year, month_1_12, 1)
    out = date(next_year, next_month, 1) - timedelta(days=1)
    while out.weekday() >= 5:
        out -= timedelta(days=1)
    return out


def _nth_weekday_of_month(year: int, month_1_12: int, weekday: int, occurrence: int) -> date:
    # Python weekday: Monday=0 ... Sunday=6
    out = date(year, month_1_12, 1)
    while out.weekday() != weekday:
        out += timedelta(days=1)
    out += timedelta(days=7 * max(0, occurrence - 1))
    return out


def _fourth_tuesday(year: int, month_1_12: int) -> date:
    return _nth_weekday_of_month(year, month_1_12, weekday=1, occurrence=4)


def _estimate_next_from_latest(
    latest_known_date: Optional[str],
    period_step_months: int,
    release_for_reference_period: Callable[[int, int], date],
) -> Optional[date]:
    latest = _parse_date(latest_known_date)
    if latest is None:
        return None

    today = date.today()
    ref_year, ref_month = latest.year, latest.month

    for _ in range(24):
        ref_year, ref_month = _year_month_add(ref_year, ref_month, period_step_months)
        release_date = release_for_reference_period(ref_year, ref_month)
        if release_date >= today:
            return release_date

    return None


@lru_cache(maxsize=1)
def _get_bea_release_payload() -> Optional[Dict[str, Any]]:
    try:
        resp = requests.get(_BEA_RELEASE_DATES_URL, timeout=_HTTP_TIMEOUT, headers=_HTTP_HEADERS)
        resp.raise_for_status()
        payload = resp.json()
        if isinstance(payload, dict):
            return payload
    except Exception as e:
        logger.warning("BEA release date fetch failed: %s", e)
    return None


def _next_bea_release(product_name: str) -> Optional[date]:
    payload = _get_bea_release_payload() or {}
    bucket = payload.get(product_name)
    if not isinstance(bucket, dict):
        return None

    today = date.today()
    release_dates = bucket.get("release_dates")
    if not isinstance(release_dates, list):
        return None

    candidates = sorted(
        {
            d
            for d in (_parse_date(v) for v in release_dates)
            if d is not None and d >= today
        }
    )
    return candidates[0] if candidates else None


@lru_cache(maxsize=1)
def _get_te_us_calendar_rows() -> Sequence[Dict[str, Any]]:
    cred = (os.getenv("TRADINGECONOMICS_API_KEY") or "guest:guest").strip()
    try:
        resp = requests.get(
            _TE_CALENDAR_US_URL,
            params={"c": cred},
            timeout=_HTTP_TIMEOUT,
            headers=_HTTP_HEADERS,
        )
        resp.raise_for_status()
        payload = resp.json()
        if isinstance(payload, list):
            return [row for row in payload if isinstance(row, dict)]
    except Exception as e:
        logger.debug("TradingEconomics US calendar fetch failed: %s", e)
    return []


def _next_te_calendar_event_date(
    required_term_sets: Iterable[Iterable[str]],
    *,
    excluded_terms: Optional[Iterable[str]] = None,
) -> Optional[date]:
    rows = _get_te_us_calendar_rows()
    if not rows:
        return None

    excluded = tuple((t or "").lower() for t in (excluded_terms or ()))
    today = date.today()
    candidates = []

    for row in rows:
        event_name = str(row.get("Event") or row.get("Category") or "").strip().lower()
        if not event_name:
            continue
        if excluded and any(term in event_name for term in excluded):
            continue

        matched = any(all(term.lower() in event_name for term in terms) for terms in required_term_sets)
        if not matched:
            continue

        d = _parse_date(row.get("Date") or row.get("DateTime") or row.get("ReferenceDate"))
        if d is None or d < today:
            continue
        candidates.append(d)

    if not candidates:
        return None
    return min(candidates)


def _entry(next_date: Optional[date], latest_known_date: Optional[str], source: str, method: str) -> Dict[str, Optional[str]]:
    return {
        "next_release_date": _iso(next_date),
        "latest_known_date": _iso(_parse_date(latest_known_date)),
        "source": source,
        "method": method,
    }


def build_release_calendar_snapshot(latest_dates: Dict[str, Optional[str]]) -> Dict[str, Dict[str, Optional[str]]]:
    """Build next-release metadata for dashboard indicators.

    latest_dates keys:
    - cpi_mom
    - core_cpi_mom
    - pce_mom
    - gdp_quarterly
    - pmi_mom
    - m2_mom
    - unemployment_rate
    """

    # CPI (headline)
    cpi_next = _next_te_calendar_event_date((("inflation rate", "mom"), ("cpi",)))
    if cpi_next:
        cpi_entry = _entry(cpi_next, latest_dates.get("cpi_mom"), "TradingEconomics calendar", "economic_calendar")
    else:
        cpi_fallback = _estimate_next_from_latest(
            latest_dates.get("cpi_mom"),
            1,
            lambda y, m: _next_business_day(date(*_year_month_add(y, m, 1), 12)),
        )
        cpi_entry = _entry(cpi_fallback, latest_dates.get("cpi_mom"), "BLS cadence rule", "rule_fallback")

    # Core CPI (same release event as CPI)
    core_cpi_next = _next_te_calendar_event_date((("core inflation rate", "mom"), ("core", "cpi")))
    if core_cpi_next:
        core_cpi_entry = _entry(
            core_cpi_next,
            latest_dates.get("core_cpi_mom"),
            "TradingEconomics calendar",
            "economic_calendar",
        )
    else:
        core_cpi_entry = _entry(
            _parse_date(cpi_entry.get("next_release_date")),
            latest_dates.get("core_cpi_mom"),
            cpi_entry.get("source") or "BLS cadence rule",
            cpi_entry.get("method") or "rule_fallback",
        )

    # PCE (Personal Income and Outlays)
    pce_next = _next_bea_release("Personal Income and Outlays")
    if pce_next:
        pce_entry = _entry(pce_next, latest_dates.get("pce_mom"), "BEA release_dates.json", "official_api")
    else:
        pce_fallback = _estimate_next_from_latest(
            latest_dates.get("pce_mom"),
            1,
            lambda y, m: _last_business_day(*_year_month_add(y, m, 1)),
        )
        pce_entry = _entry(pce_fallback, latest_dates.get("pce_mom"), "BEA cadence rule", "rule_fallback")

    # GDP quarterly (advance/second/third releases all from BEA product)
    gdp_next = _next_bea_release("Gross Domestic Product")
    if gdp_next:
        gdp_entry = _entry(gdp_next, latest_dates.get("gdp_quarterly"), "BEA release_dates.json", "official_api")
    else:
        gdp_fallback = _estimate_next_from_latest(
            latest_dates.get("gdp_quarterly"),
            3,
            lambda y, m: _last_business_day(*_year_month_add(y, m, 3)),
        )
        gdp_entry = _entry(gdp_fallback, latest_dates.get("gdp_quarterly"), "BEA cadence rule", "rule_fallback")

    # Manufacturing PMI
    pmi_next = _next_te_calendar_event_date((("ism", "manufacturing", "pmi"), ("manufacturing", "pmi")))
    if pmi_next:
        pmi_entry = _entry(pmi_next, latest_dates.get("pmi_mom"), "TradingEconomics calendar", "economic_calendar")
    else:
        pmi_fallback = _estimate_next_from_latest(
            latest_dates.get("pmi_mom"),
            1,
            lambda y, m: _first_business_day(*_year_month_add(y, m, 1)),
        )
        pmi_entry = _entry(pmi_fallback, latest_dates.get("pmi_mom"), "S&P Global/ISM cadence rule", "rule_fallback")

    # M2 (H.6 release cadence)
    m2_fallback = _estimate_next_from_latest(
        latest_dates.get("m2_mom"),
        1,
        lambda y, m: _fourth_tuesday(*_year_month_add(y, m, 1)),
    )
    m2_entry = _entry(m2_fallback, latest_dates.get("m2_mom"), "Federal Reserve H.6 cadence", "rule_fallback")

    # Unemployment rate / Employment Situation
    jobs_next = _next_te_calendar_event_date(
        (("unemployment rate",),),
        excluded_terms=("jobless claims", "continuing", "4-week"),
    )
    if jobs_next:
        jobs_entry = _entry(
            jobs_next,
            latest_dates.get("unemployment_rate"),
            "TradingEconomics calendar",
            "economic_calendar",
        )
    else:
        jobs_fallback = _estimate_next_from_latest(
            latest_dates.get("unemployment_rate"),
            1,
            lambda y, m: _nth_weekday_of_month(*_year_month_add(y, m, 1), weekday=4, occurrence=1),
        )
        jobs_entry = _entry(jobs_fallback, latest_dates.get("unemployment_rate"), "BLS cadence rule", "rule_fallback")

    return {
        "cpi_mom": cpi_entry,
        "core_cpi_mom": core_cpi_entry,
        "pce_mom": pce_entry,
        "gdp_quarterly": gdp_entry,
        "pmi_mom": pmi_entry,
        "m2_mom": m2_entry,
        "unemployment_rate": jobs_entry,
    }
