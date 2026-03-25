"""
Data freshness validation.

Enforces staleness rules. Refuses to compute verdict if critical data is missing.
All thresholds loaded from config/scoring_weights.json data_freshness (single source of truth).
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


class FreshnessReport:
    """Holds freshness check results for all data points."""

    def __init__(self):
        self.checks: List[Dict[str, Any]] = []
        self.warnings: List[str] = []
        self.critical_failures: List[str] = []

    def add_check(self, name: str, data_date: Optional[datetime], max_age: timedelta, is_critical: bool = True):
        now = datetime.now()

        if data_date is None:
            entry = {
                "name": name,
                "status": "MISSING",
                "data_date": None,
                "max_age": str(max_age),
                "age": None,
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
            "max_age": str(max_age),
            "age": str(age),
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
        return {
            "can_proceed": self.can_proceed,
            "checks": self.checks,
            "warnings": self.warnings,
            "critical_failures": self.critical_failures,
        }


def validate_data_freshness(data: Dict[str, Any]) -> FreshnessReport:
    """
    Validate freshness of all fetched data using only data_freshness keys from scoring_weights.json.
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

    def _parse_date(date_str: Optional[str]) -> Optional[datetime]:
        if not date_str:
            return None
        try:
            dt = datetime.fromisoformat(date_str[:19])
            return dt
        except ValueError:
            pass
        try:
            dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
            return dt + timedelta(hours=18)
        except (ValueError, TypeError):
            return None

    # --- All max ages from config (defaults match previous behavior) ---
    report.add_check(
        "CPI",
        _parse_date(data.get("cpi", {}).get("latest_date")),
        _days("cpi_max_age_days", 90),
        is_critical=False,
    )
    report.add_check(
        "PCE",
        _parse_date(data.get("pce", {}).get("latest_date")),
        _days("pce_max_age_days", 45),
        is_critical=False,
    )
    report.add_check(
        "10Y Yield",
        _parse_date(data.get("yields", {}).get("yield_10y", {}).get("date")),
        _days("yields_max_age_days", 5),
        is_critical=False,
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
    report.add_check(
        "Oil",
        _parse_date(
            data.get("oil", {}).get("latest_date")
            or data.get("oil", {}).get("data_as_of")
        ),
        _days("oil_max_age_days", 3),
        is_critical=False,
    )
    report.add_check(
        "Fed Funds Rate",
        _parse_date(
            data.get("fed_rate", {}).get("latest_date")
            or data.get("fed_rate", {}).get("data_as_of")
        ),
        _days("fed_funds_max_age_days", 35),
        is_critical=False,
    )
    report.add_check(
        "BTC Price",
        _parse_date(data.get("btc", {}).get("date")),
        _hours("btc_price_max_age_hours", 24),
        is_critical=True,
    )
    report.add_check(
        "Fed Balance Sheet",
        _parse_date(data.get("balance_sheet", {}).get("latest_date")),
        _days("fed_balance_sheet_max_age_days", 10),
        is_critical=False,
    )
    report.add_check(
        "Unemployment Rate",
        _parse_date(
            data.get("jobs", {}).get("unemployment_date")
            or data.get("jobs", {}).get("data_as_of")
        ),
        _days("unemployment_max_age_days", 35),
        is_critical=False,
    )
    report.add_check(
        "GDP",
        _parse_date(
            data.get("gdp", {}).get("latest_date") or data.get("gdp", {}).get("data_as_of")
        ),
        _days("gdp_max_age_days", 120),
        is_critical=False,
    )
    report.add_check(
        "PMI",
        _parse_date(
            data.get("pmi", {}).get("latest_date") or data.get("pmi", {}).get("data_as_of")
        ),
        _days("pmi_max_age_days", 35),
        is_critical=False,
    )
    report.add_check(
        "M2 Money Supply",
        _parse_date(
            data.get("m2", {}).get("latest_date") or data.get("m2", {}).get("data_as_of")
        ),
        _days("m2_max_age_days", 35),
        is_critical=False,
    )
    fs = data.get("financial_stress") or {}
    report.add_check(
        "HY OAS",
        _parse_date(fs.get("latest_date") or fs.get("data_as_of")),
        _days("hy_oas_max_age_days", 14),
        is_critical=False,
    )

    return report
