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
        """Parse date string. Adds market-close grace (18h) so a date-only
        value from a trading-day close is never immediately stale."""
        if not date_str:
            return None
        try:
            # Try full ISO datetime first
            dt = datetime.fromisoformat(date_str[:19])
            return dt
        except ValueError:
            pass
        try:
            # Date-only: treat as end-of-trading-day + 18h grace to handle
            # weekend/holiday data that was last updated on the most-recent close
            dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
            # Add 18 hours so a Friday close is still fresh Monday morning
            return dt + timedelta(hours=18)
        except (ValueError, TypeError):
            return None

    # CPI (monthly release, max 90 days - BLS/FRED delay can exceed a month)
    cpi_date = _parse_date(data.get("cpi", {}).get("latest_date"))
    report.add_check(
        "CPI", cpi_date,
        timedelta(days=90),
        is_critical=False
    )

    # PCE (monthly, BEA releases ~last business day of following month → 45d max)
    pce_date = _parse_date(data.get("pce", {}).get("latest_date"))
    report.add_check(
        "PCE", pce_date,
        timedelta(days=45),  # BEA releases Dec PCE in late Jan; allow 45d window
        is_critical=False
    )
    
    # 10Y Yield (daily, non-critical - market data can be delayed on weekends/holidays)
    yield_date = _parse_date(data.get("yields", {}).get("yield_10y", {}).get("date"))
    report.add_check(
        "10Y Yield", yield_date,
        timedelta(days=5),  # Increased to 5 days for weekends/holidays
        is_critical=False  # Non-critical
    )
    
    # DXY (daily market data — allow 3 days for weekends/holidays)
    dxy_date = _parse_date(data.get("dxy", {}).get("date"))
    report.add_check(
        "DXY", dxy_date,
        timedelta(days=3),
        is_critical=False
    )

    # VIX (daily market data — allow 3 days for weekends/holidays)
    vix_date = _parse_date(data.get("vix", {}).get("date"))
    report.add_check(
        "VIX", vix_date,
        timedelta(days=3),
        is_critical=False
    )

    # S&P 500 (daily market data — allow 3 days for weekends/holidays)
    sp500_date = _parse_date(data.get("sp500", {}).get("date"))
    report.add_check(
        "S&P 500", sp500_date,
        timedelta(days=3),
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
