"""
Agent for Section 3: Liquidity & Bonds Analysis
"""
from langchain_core.prompts import PromptTemplate
from typing import Dict, Any

from .base_agent import BaseAgent
from .signal_validator import SignalValidator
from models.schemas import ValidatedSignal, DataSource, SignalValidationStatus
from data_fetchers import fred_data
from typing import List
from datetime import datetime


class LiquidityAgent(BaseAgent):
    """Analyzes liquidity conditions and bond markets"""
    
    def __init__(self):
        super().__init__("Liquidity & Bonds")
    
    def fetch_data(self, timeframe: str = "current") -> Dict[str, Any]:
        """Fetch bond yields and Fed balance sheet data with timeframe support"""
        yields = fred_data.get_treasury_yields(timeframe)
        balance_sheet = fred_data.get_fed_balance_sheet(timeframe)
        
        data_sources = [
            SignalValidator.create_data_source("FRED", "DGS10", "https://fred.stlouisfed.org/series/DGS10")
        ]
        
        return {
            "yields": yields,
            "balance_sheet": balance_sheet,
            "_data_sources": data_sources
        }
    
    def validate_signals(self, data: Dict[str, Any]) -> List[ValidatedSignal]:
        """Validate liquidity signals: 10Y yield level, yield curve inversion, and balance sheet trend."""
        validated_signals = []
        yields = data.get("yields", {})
        balance_sheet = data.get("balance_sheet", {})

        data_sources = data.get("_data_sources", [])
        source = data_sources[0] if data_sources else SignalValidator.create_data_source("FRED")

        # 1. 10Y yield level — lower yield = more bullish for risk assets
        yield_10y = yields.get("yield_10y", {})
        y10_val = yield_10y.get("value")
        if y10_val is not None:
            if y10_val < 3.0:
                yield_label = f"low ({y10_val:.2f}%) — accommodative"
                yield_contrib = 12.0
                yield_valid = True
                yield_status = SignalValidationStatus.VALIDATED
            elif y10_val < 4.5:
                yield_label = f"moderate ({y10_val:.2f}%)"
                yield_contrib = 6.0
                yield_valid = True
                yield_status = SignalValidationStatus.VALIDATED
            else:
                yield_label = f"high ({y10_val:.2f}%) — restrictive"
                yield_contrib = 0.0
                yield_valid = False
                yield_status = SignalValidationStatus.NEUTRALIZED

            validated_signals.append(ValidatedSignal(
                name=f"10Y Treasury yield {yield_label}",
                value=y10_val,
                previous_value=None,
                trend_direction=yield_10y.get("trend"),
                validation_status=yield_status,
                validation_check=f"yield_10y < 4.5% for positive (actual: {y10_val:.2f}%)",
                validation_result=yield_valid,
                score_contribution=yield_contrib,
                data_source=source,
            ))

        # 2. Yield curve spread (10Y - 2Y) — inversion = recession risk = bearish for BTC
        yield_curve_spread = yields.get("yield_curve_spread")
        yield_2y_val = yields.get("yield_2y", {}).get("value")
        if yield_curve_spread is not None:
            if yield_curve_spread < 0:
                curve_label = f"inverted ({yield_curve_spread:+.2f}pp) — recession risk"
                curve_contrib = 0.0
                curve_status = SignalValidationStatus.INVALIDATED
                curve_valid = False
                curve_notes = f"Yield curve inverted by {abs(yield_curve_spread):.2f}pp — historical recession signal"
            elif yield_curve_spread > 0.5:
                curve_label = f"steepening ({yield_curve_spread:+.2f}pp) — recovery signal"
                curve_contrib = 10.0
                curve_status = SignalValidationStatus.VALIDATED
                curve_valid = True
                curve_notes = None
            else:
                curve_label = f"flat ({yield_curve_spread:+.2f}pp)"
                curve_contrib = 3.0
                curve_status = SignalValidationStatus.VALIDATED
                curve_valid = True
                curve_notes = None

            validated_signals.append(ValidatedSignal(
                name=f"Yield curve {curve_label}",
                value=yield_curve_spread,
                previous_value=yield_2y_val,
                trend_direction="up" if yield_curve_spread > 0 else "down",
                validation_status=curve_status,
                validation_check=f"yield_curve_spread >= 0 (actual: {yield_curve_spread:+.2f}pp)",
                validation_result=curve_valid,
                score_contribution=curve_contrib,
                data_source=SignalValidator.create_data_source(
                    "FRED", "DGS2/DGS10", "https://fred.stlouisfed.org/series/T10Y2Y"
                ),
                notes=curve_notes,
            ))

        # 3. Fed balance sheet trend — expanding = more liquidity = bullish
        bs_trend = balance_sheet.get("trend", "stable")
        bs_total = balance_sheet.get("total_assets")
        if bs_trend and not balance_sheet.get("error"):
            if bs_trend == "expanding":
                bs_label = "expanding (QE / liquidity injection)"
                bs_contrib = 12.0
                bs_status = SignalValidationStatus.VALIDATED
                bs_valid = True
                bs_notes = None
            elif bs_trend == "contracting":
                bs_label = "contracting (QT — liquidity draining)"
                bs_contrib = 0.0
                bs_status = SignalValidationStatus.INVALIDATED
                bs_valid = False
                bs_notes = "Fed balance sheet QT invalidates liquidity-expansion thesis"
            else:
                bs_label = "stable"
                bs_contrib = 5.0
                bs_status = SignalValidationStatus.VALIDATED
                bs_valid = True
                bs_notes = None

            validated_signals.append(ValidatedSignal(
                name=f"Fed balance sheet {bs_label}",
                value=float(bs_total) if bs_total is not None else 0.0,
                previous_value=None,
                trend_direction="up" if bs_trend == "expanding" else "down" if bs_trend == "contracting" else "flat",
                validation_status=bs_status,
                validation_check=f"balance_sheet_trend != 'contracting' (actual: {bs_trend})",
                validation_result=bs_valid,
                score_contribution=bs_contrib,
                data_source=SignalValidator.create_data_source(
                    "FRED", "WALCL", "https://fred.stlouisfed.org/series/WALCL"
                ),
                notes=bs_notes,
            ))

        return validated_signals
    
    def create_prompt(self) -> PromptTemplate:
        """Create prompt for liquidity analysis"""
        return PromptTemplate(
            input_variables=["query"],
            template="""You are an expert fixed income and liquidity analyst.

Knowledge Base Context:
{{context}}

Task: Analyze liquidity conditions and bond markets. Score from 0-100 where:
- 0-20: Liquidity contracting, yields rising, QT active
- 21-40: Liquidity tight, yields high, restrictive policy
- 41-60: Liquidity stable, mixed signals
- 61-80: Liquidity expanding, yields falling, easing expected
- 81-100: Liquidity rapidly expanding, QE active, yields collapsing

Consider:
- 2Y and 10Y Treasury yields
- Yield curve (steepening = recovery, inversion = recession risk)
- Fed balance sheet trend (expanding = QE, contracting = QT)
- Credit conditions

Early signals:
- Yields stop rising → growth slowdown ahead
- Yield curve steepens after inversion → recovery coming
- Bonds rally before stocks → risk-off ending

Provide your analysis in this format:
Score: [0-100]
Signals:
- [Key signal 1]
- [Key signal 2]
Reasoning: [Detailed explanation of liquidity conditions and implications for BTC]

Query: {query}
"""
        )

