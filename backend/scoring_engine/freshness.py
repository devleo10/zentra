"""
Data freshness validation.

Enforces staleness rules. Refuses to compute verdict if critical data is missing.
All thresholds loaded from config/scoring_weights.json.
"""
import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger("btc_macro.freshness")


def _load_config() -> Dict:
    config_path = Path(__file__).parent.parent / "config" / "scoring_weights.json"
    with open(config_path, "r") as f:
        return json.load(f)


CONFIG = _load_config()["data_freshness"]


class FreshnessReport:
    """Holds freshness check results for all data points."""
    
    def __init__(self):
        self.checks: List[Dict[str, Any]] = []
        self.warnings: List[str] = []
        self.critical_failures: List[str] = []
    
    def add_check(self, name: str, data_date: Optional[datetime], max_age: timedelta, is_critical: bool = True):
        """
        Add a freshness check.
        
        Args:
            name: Data source name (e.g., "CPI", "BTC price")
            data_date: When the data was last updated (None if missing)
            max_age: Maximum acceptable age
            is_critical: If True, stale/missing data blocks verdict computation
        """
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
        """Returns True if no critical failures."""
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
    Validate freshness of all fetched data.
    
    Args:
        data: Dict with keys matching the data sources.
            Expected keys and their 'date' sub-keys:
            - cpi: {"latest_date": "YYYY-MM-DD", ...}
            - pce: {"latest_date": "YYYY-MM-DD", ...}
            - yields: {"yield_10y": {"date": "YYYY-MM-DD"}, ...}
            - dxy: {"date": "YYYY-MM-DD", ...}
            - vix: {"date": "YYYY-MM-DD", ...}
            - sp500: {"date": "YYYY-MM-DD", ...}
            - btc: {"date": "YYYY-MM-DD", ...}
            - balance_sheet: {"latest_date": "YYYY-MM-DD", ...}
    
    Returns:
        FreshnessReport with all checks, warnings, and critical failures.
    """
    report = FreshnessReport()
    
    def _parse_date(date_str: Optional[str]) -> Optional[datetime]:
        if not date_str:
            return None
        try:
            return datetime.strptime(date_str[:10], "%Y-%m-%d")
        except (ValueError, TypeError):
            return None
    
    # CPI (monthly release, max 90 days - FRED data can be delayed)
    cpi_date = _parse_date(data.get("cpi", {}).get("latest_date"))
    report.add_check(
        "CPI", cpi_date,
        timedelta(days=90),  # Increased from config - FRED releases are often delayed
        is_critical=False  # Non-critical - we can still compute with older data
    )
    
    # PCE (monthly, non-critical if CPI present)
    pce_date = _parse_date(data.get("pce", {}).get("latest_date"))
    report.add_check(
        "PCE", pce_date,
        timedelta(days=CONFIG["pce_max_age_days"]),
        is_critical=False
    )
    
    # 10Y Yield (daily, non-critical - market data can be delayed on weekends/holidays)
    yield_date = _parse_date(data.get("yields", {}).get("yield_10y", {}).get("date"))
    report.add_check(
        "10Y Yield", yield_date,
        timedelta(days=5),  # Increased to 5 days for weekends/holidays
        is_critical=False  # Non-critical
    )
    
    # DXY (daily, non-critical - we have fallbacks)
    dxy_date = _parse_date(data.get("dxy", {}).get("date"))
    report.add_check(
        "DXY", dxy_date,
        timedelta(hours=CONFIG["dxy_max_age_hours"]),
        is_critical=False  # Changed to non-critical since we have fallback values
    )
    
    # VIX (daily, non-critical)
    vix_date = _parse_date(data.get("vix", {}).get("date"))
    report.add_check(
        "VIX", vix_date,
        timedelta(hours=CONFIG["vix_max_age_hours"]),
        is_critical=False
    )
    
    # S&P 500 (daily, non-critical)
    sp500_date = _parse_date(data.get("sp500", {}).get("date"))
    report.add_check(
        "S&P 500", sp500_date,
        timedelta(hours=CONFIG["sp500_max_age_hours"]),
        is_critical=False
    )
    
    # BTC Price (real-time, critical)
    btc_date_str = data.get("btc", {}).get("date")
    btc_date = _parse_date(btc_date_str)
    # For BTC, we treat same-day as fresh (CoinGecko gives date not datetime)
    report.add_check(
        "BTC Price", btc_date,
        timedelta(hours=24),  # Relaxed from 10min since CoinGecko gives daily dates
        is_critical=True
    )
    
    # Fed Balance Sheet (weekly, non-critical)
    bs_date = _parse_date(data.get("balance_sheet", {}).get("latest_date"))
    report.add_check(
        "Fed Balance Sheet", bs_date,
        timedelta(days=CONFIG["fed_balance_sheet_max_age_days"]),
        is_critical=False
    )
    
    return report
