"""
Data freshness validation.

Enforces staleness rules. Refuses to compute verdict if critical data is missing.
Thresholds from config/scoring_weights.json `data_freshness`.

Macro semantics:
  - Each successful fetch is stamped with `fetched_at` (ISO) in run_analysis.
  - For designated macro checks, a series is FRESH if EITHER the batch fetch is recent
    (now - fetched_at <= macro_fetched_max_age_hours) OR the observation date is within
    the series max_age_days. This avoids false STALE flags when the API returns the
    latest print but the observation month/quarter is dated in the past.
"""
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

logger = logging.getLogger("btc_macro.freshness")

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "scoring_weights.json"


def _load_full_config() -> Dict:
    import json

    with open(_CONFIG_PATH, "r") as f:
        return json.load(f)


def get_freshness_config() -> Dict:
    """Freshness subsection only (reload each call for consistency with validate)."""
    return _load_full_config().get("data_freshness", {})


def _parse_date(date_str: Optional[str]) -> Optional[datetime]:
    if not date_str:
        return None
    s = str(date_str).strip()
    if s.endswith("Z"):
        s = s[:-1]
    try:
        if "T" in s[:11]:
            return datetime.fromisoformat(s[:19])
    except ValueError:
        pass
    try:
        dt = datetime.strptime(s[:10], "%Y-%m-%d")
        return dt + timedelta(hours=18)
    except (ValueError, TypeError):
        return None


def compute_data_quality_metrics(checks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate freshness checks into API-friendly quality metrics."""
    total = len(checks)
    if not total:
        return {
            "score": 0.0,
            "fresh": 0,
            "stale": 0,
            "missing": 0,
            "total": 0,
            "stale_ratio": 0.0,
        }
    fresh = sum(1 for c in checks if c.get("status") == "FRESH")
    stale = sum(1 for c in checks if c.get("status") == "STALE")
    missing = sum(1 for c in checks if c.get("status") == "MISSING")
    available = fresh + stale
    score = round(100.0 * available / total, 1)
    stale_ratio = round(stale / total, 4)
    return {
        "score": score,
        "availability_score": score,
        "fresh": fresh,
        "stale": stale,
        "missing": missing,
        "available": available,
        "total": total,
        "stale_ratio": stale_ratio,
    }


class FreshnessReport:
    """Holds freshness check results for all data points."""

    def __init__(self):
        self.checks: List[Dict[str, Any]] = []
        self.warnings: List[str] = []
        self.critical_failures: List[str] = []

    def add_check(
        self,
        name: str,
        observation_date: Optional[datetime],
        max_age_observation: timedelta,
        is_critical: bool = True,
        *,
        fetched_at: Optional[datetime] = None,
        macro_fetch_max_age: Optional[timedelta] = None,
    ):
        """
        If macro_fetch_max_age is set, macro dual rule:
          FRESH if (fetched_at recent) OR (observation_date within max_age_observation).
        Otherwise legacy: observation_date only vs max_age_observation.
        """
        now = datetime.now()

        if macro_fetch_max_age is None:
            self._add_check_simple(name, observation_date, max_age_observation, is_critical)
            return

        if observation_date is None and fetched_at is None:
            entry = {
                "name": name,
                "status": "MISSING",
                "data_date": None,
                "fetched_at": None,
                "max_age": str(max_age_observation),
                "macro_fetch_max": str(macro_fetch_max_age),
                "age": None,
                "age_fetch": None,
                "freshness_basis": None,
                "is_critical": is_critical,
            }
            self.checks.append(entry)
            msg = f"[MISSING] {name}: No data available"
            if is_critical:
                self.critical_failures.append(msg)
            else:
                self.warnings.append(msg)
            return

        fetch_fresh = False
        age_fetch = None
        if fetched_at is not None:
            age_fetch = now - fetched_at
            fetch_fresh = age_fetch <= macro_fetch_max_age

        obs_fresh = False
        age_obs = None
        if observation_date is not None:
            age_obs = now - observation_date
            obs_fresh = age_obs <= max_age_observation

        is_fresh = fetch_fresh or obs_fresh
        if fetch_fresh and obs_fresh:
            basis = "fetch+observation"
        elif fetch_fresh:
            basis = "fetch"
        elif obs_fresh:
            basis = "observation"
        else:
            basis = None

        entry = {
            "name": name,
            "status": "FRESH" if is_fresh else "STALE",
            "data_date": observation_date.isoformat() if observation_date else None,
            "fetched_at": fetched_at.isoformat() if fetched_at else None,
            "max_age": str(max_age_observation),
            "macro_fetch_max": str(macro_fetch_max_age),
            "age": str(age_obs) if age_obs is not None else None,
            "age_fetch": str(age_fetch) if age_fetch is not None else None,
            "freshness_basis": basis if is_fresh else None,
            "is_critical": is_critical,
        }
        self.checks.append(entry)

        if not is_fresh:
            parts = []
            if age_obs is not None:
                parts.append(f"obs_age={age_obs} max_obs={max_age_observation}")
            if age_fetch is not None:
                parts.append(f"fetch_age={age_fetch} max_fetch={macro_fetch_max_age}")
            msg = f"[STALE] {name}: " + ", ".join(parts)
            if is_critical:
                self.critical_failures.append(msg)
            else:
                self.warnings.append(msg)

    def _add_check_simple(
        self,
        name: str,
        data_date: Optional[datetime],
        max_age: timedelta,
        is_critical: bool = True,
    ):
        now = datetime.now()

        if data_date is None:
            entry = {
                "name": name,
                "status": "MISSING",
                "data_date": None,
                "fetched_at": None,
                "max_age": str(max_age),
                "age": None,
                "freshness_basis": None,
                "is_critical": is_critical,
            }
            self.checks.append(entry)
            msg = f"[MISSING] {name}: No data available"
            if is_critical:
                self.critical_failures.append(msg)
            else:
                self.warnings.append(msg)
            return

        age = now - data_date
        is_stale = age > max_age

        entry = {
            "name": name,
            "status": "STALE" if is_stale else "FRESH",
            "data_date": data_date.isoformat(),
            "fetched_at": None,
            "max_age": str(max_age),
            "age": str(age),
            "freshness_basis": "observation" if not is_stale else None,
            "is_critical": is_critical,
        }
        self.checks.append(entry)

        if is_stale:
            msg = f"[STALE] {name}: age={age}, max={max_age}"
            if is_critical:
                self.critical_failures.append(msg)
            else:
                self.warnings.append(msg)

    @property
    def can_proceed(self) -> bool:
        return len(self.critical_failures) == 0

    def to_dict(self) -> Dict[str, Any]:
        dq = compute_data_quality_metrics(self.checks)
        return {
            "can_proceed": self.can_proceed,
            "checks": self.checks,
            "warnings": self.warnings,
            "critical_failures": self.critical_failures,
            "data_quality": dq,
        }


def _blob_fetched_at(blob: Any) -> Optional[datetime]:
    if not isinstance(blob, dict):
        return None
    return _parse_date(blob.get("fetched_at"))


def validate_data_freshness(data: Dict[str, Any]) -> FreshnessReport:
    """
    Validate freshness of all fetched data using data_freshness keys from scoring_weights.json.
    """
    report = FreshnessReport()
    cfg = get_freshness_config()

    def _days(key: str, default: int) -> timedelta:
        v = cfg.get(key, default)
        try:
            return timedelta(days=int(v))
        except (TypeError, ValueError):
            return timedelta(days=default)

    def _hours(key: str, default: int) -> timedelta:
        v = cfg.get(key, default)
        try:
            return timedelta(hours=int(v))
        except (TypeError, ValueError):
            return timedelta(hours=default)

    macro_fetch_max = _hours("macro_fetched_max_age_hours", 168)

    # --- Macro-style: fetch OR observation ---
    cpi_b = data.get("cpi") or {}
    report.add_check(
        "CPI",
        _parse_date(cpi_b.get("latest_date")),
        _days("cpi_max_age_days", 90),
        is_critical=False,
        fetched_at=_blob_fetched_at(cpi_b),
        macro_fetch_max_age=macro_fetch_max,
    )
    pce_b = data.get("pce") or {}
    report.add_check(
        "PCE",
        _parse_date(pce_b.get("latest_date")),
        _days("pce_max_age_days", 100),
        is_critical=False,
        fetched_at=_blob_fetched_at(pce_b),
        macro_fetch_max_age=macro_fetch_max,
    )

    yb = data.get("yields") or {}
    y10 = yb.get("yield_10y") or {}
    report.add_check(
        "10Y Yield",
        _parse_date(y10.get("date")),
        _days("yields_max_age_days", 5),
        is_critical=False,
        fetched_at=_blob_fetched_at(yb),
        macro_fetch_max_age=macro_fetch_max,
    )

    report.add_check(
        "DXY",
        _parse_date(data.get("dxy", {}).get("date")),
        _days("dxy_max_age_days", 3),
        is_critical=False,
    )
    report.add_check(
        "VIX",
        _parse_date(data.get("vix", {}).get("date")),
        _days("vix_max_age_days", 3),
        is_critical=False,
    )
    report.add_check(
        "S&P 500",
        _parse_date(data.get("sp500", {}).get("date")),
        _days("sp500_max_age_days", 3),
        is_critical=False,
    )
    report.add_check(
        "Gold",
        _parse_date(data.get("gold", {}).get("date")),
        _days("gold_max_age_days", 3),
        is_critical=False,
    )

    oil_b = data.get("oil") or {}
    report.add_check(
        "Oil",
        _parse_date(oil_b.get("latest_date") or oil_b.get("data_as_of")),
        _days("oil_max_age_days", 3),
        is_critical=False,
        fetched_at=_blob_fetched_at(oil_b),
        macro_fetch_max_age=macro_fetch_max,
    )

    fr = data.get("fed_rate") or {}
    report.add_check(
        "Fed Funds Rate",
        _parse_date(fr.get("latest_date") or fr.get("data_as_of")),
        _days("fed_funds_max_age_days", 35),
        is_critical=False,
        fetched_at=_blob_fetched_at(fr),
        macro_fetch_max_age=macro_fetch_max,
    )

    report.add_check(
        "BTC Price",
        _parse_date(data.get("btc", {}).get("date")),
        _hours("btc_price_max_age_hours", 24),
        is_critical=True,
    )

    bs = data.get("balance_sheet") or {}
    report.add_check(
        "Fed Balance Sheet",
        _parse_date(bs.get("latest_date")),
        _days("fed_balance_sheet_max_age_days", 10),
        is_critical=False,
        fetched_at=_blob_fetched_at(bs),
        macro_fetch_max_age=macro_fetch_max,
    )

    jobs = data.get("jobs") or {}
    report.add_check(
        "Unemployment Rate",
        _parse_date(jobs.get("unemployment_date") or jobs.get("data_as_of")),
        _days("unemployment_max_age_days", 70),
        is_critical=False,
        fetched_at=_blob_fetched_at(jobs),
        macro_fetch_max_age=macro_fetch_max,
    )
    report.add_check(
        "NFP",
        _parse_date(jobs.get("unemployment_date") or jobs.get("data_as_of")) if jobs.get("nfp_change") is not None else None,
        _days("unemployment_max_age_days", 70),
        is_critical=False,
        fetched_at=_blob_fetched_at(jobs),
        macro_fetch_max_age=macro_fetch_max,
    )

    gdp_b = data.get("gdp") or {}
    report.add_check(
        "GDP",
        _parse_date(gdp_b.get("latest_date") or gdp_b.get("data_as_of")),
        _days("gdp_max_age_days", 200),
        is_critical=False,
        fetched_at=_blob_fetched_at(gdp_b),
        macro_fetch_max_age=macro_fetch_max,
    )

    pmi_b = data.get("pmi") or {}
    report.add_check(
        "PMI",
        _parse_date(pmi_b.get("latest_date") or pmi_b.get("data_as_of")),
        _days("pmi_max_age_days", 70),
        is_critical=False,
        fetched_at=_blob_fetched_at(pmi_b),
        macro_fetch_max_age=macro_fetch_max,
    )

    m2_b = data.get("m2") or {}
    report.add_check(
        "M2 Money Supply",
        _parse_date(m2_b.get("latest_date") or m2_b.get("data_as_of")),
        _days("m2_max_age_days", 70),
        is_critical=False,
        fetched_at=_blob_fetched_at(m2_b),
        macro_fetch_max_age=macro_fetch_max,
    )

    fs = data.get("financial_stress") or {}
    report.add_check(
        "HY OAS",
        _parse_date(fs.get("latest_date") or fs.get("data_as_of")),
        _days("hy_oas_max_age_days", 14),
        is_critical=False,
        fetched_at=_blob_fetched_at(fs),
        macro_fetch_max_age=macro_fetch_max,
    )

    return report
