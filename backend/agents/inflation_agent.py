"""
Agent for Section 1: Inflation & Economy Analysis
"""
from langchain_core.prompts import PromptTemplate
from typing import Dict, Any

from .base_agent import BaseAgent
from .signal_validator import SignalValidator
from models.schemas import ValidatedSignal, DataSource, SignalValidationStatus
from data_fetchers import fred_data
from typing import List
from datetime import datetime


class InflationAgent(BaseAgent):
    """Analyzes inflation and economic indicators"""
    
    def __init__(self):
        super().__init__("Inflation & Economy")
    
    def fetch_data(self, timeframe: str = "current") -> Dict[str, Any]:
        """Fetch inflation and economic data with timeframe support"""
        cpi = fred_data.get_cpi_data(timeframe)
        pce = fred_data.get_pce_data(timeframe)
        oil = fred_data.get_oil_data(timeframe)
        
        # Create data sources
        cpi_date_str = cpi.get("latest_date")
        try:
            cpi_date = datetime.strptime(cpi_date_str, "%Y-%m-%d") if cpi_date_str else datetime.now()
        except (ValueError, TypeError):
            cpi_date = datetime.now()
        
        cpi_source_name = cpi.get("source", "FRED")
        if cpi_source_name == "BLS":
            ds_name, ds_series, ds_url = "BLS", "CUSR0000SA0", "https://www.bls.gov/cpi/"
        else:
            ds_name, ds_series, ds_url = "FRED", "CPIAUCSL", "https://fred.stlouisfed.org/series/CPIAUCSL"
        data_sources = [
            SignalValidator.create_data_source(
                name=ds_name,
                series_id=ds_series,
                url=ds_url,
                data_as_of=cpi_date
            )
        ]
        
        return {
            "cpi": cpi,
            "pce": pce,
            "oil": oil,
            "_data_sources": data_sources
        }
    
    def validate_signals(self, data: Dict[str, Any]) -> List[ValidatedSignal]:
        """Validate inflation signals: CPI, PCE, and oil price change."""
        validated_signals = []
        data_sources = data.get("_data_sources", [])
        cpi_source = data_sources[0] if data_sources else SignalValidator.create_data_source("FRED")

        # 1. CPI MoM trend
        cpi = data.get("cpi", {})
        cpi_change = cpi.get("change", cpi.get("mom_change"))
        if cpi.get("latest_value") is not None and cpi_change is not None:
            trend = cpi.get("trend", "falling" if cpi_change < 0 else "rising")
            validated_signals.append(ValidatedSignal(
                name=f"CPI MoM {trend} ({cpi_change:+.3f}%)",
                value=float(cpi.get("latest_value")),
                previous_value=None,
                trend_direction="down" if cpi_change < 0 else "up",
                validation_status=SignalValidationStatus.VALIDATED,
                validation_check=f"CPI MoM change = {cpi_change:+.3f}%",
                validation_result=True,
                score_contribution=15.0 if cpi_change < 0 else 0.0,
                data_source=cpi_source,
            ))

        # 2. PCE MoM trend
        pce = data.get("pce", {})
        pce_change = pce.get("change", pce.get("mom_change"))
        if pce_change is not None and not pce.get("error"):
            pce_trend = "falling" if pce_change < 0 else "rising" if pce_change > 0 else "flat"
            is_bullish_pce = pce_change < 0
            validated_signals.append(ValidatedSignal(
                name=f"PCE MoM {pce_trend} ({pce_change:+.3f}%)",
                value=float(pce.get("latest_value", 0) or 0),
                previous_value=None,
                trend_direction="down" if pce_change < 0 else "up",
                validation_status=SignalValidationStatus.VALIDATED,
                validation_check=f"PCE MoM change = {pce_change:+.3f}%",
                validation_result=is_bullish_pce,
                score_contribution=10.0 if is_bullish_pce else 0.0,
                data_source=SignalValidator.create_data_source(
                    "FRED", "PCEPI", "https://fred.stlouisfed.org/series/PCEPI"
                ),
                notes=None if is_bullish_pce else "PCE rising — potential inflation persistence",
            ))

        # 3. Oil price change
        oil = data.get("oil", {})
        oil_change = oil.get("change")
        if oil_change is not None and not oil.get("error"):
            # Falling oil = bullish (lower energy costs → lower inflation pressure)
            if oil_change <= -5.0:
                oil_label = f"falling sharply ({oil_change:+.1f}%)"
                oil_contrib = 12.0
                oil_status = SignalValidationStatus.VALIDATED
                oil_valid = True
            elif oil_change < 0:
                oil_label = f"falling ({oil_change:+.1f}%)"
                oil_contrib = 6.0
                oil_status = SignalValidationStatus.VALIDATED
                oil_valid = True
            elif oil_change >= 10.0:
                oil_label = f"surging ({oil_change:+.1f}%) — inflation risk"
                oil_contrib = 0.0
                oil_status = SignalValidationStatus.INVALIDATED
                oil_valid = False
            else:
                oil_label = f"stable/rising ({oil_change:+.1f}%)"
                oil_contrib = 3.0
                oil_status = SignalValidationStatus.VALIDATED
                oil_valid = True

            validated_signals.append(ValidatedSignal(
                name=f"WTI Oil {oil_label}",
                value=float(oil.get("current_price", 0) or 0),
                previous_value=None,
                trend_direction="down" if oil_change < 0 else "up",
                validation_status=oil_status,
                validation_check=f"oil_change={oil_change:+.1f}% (bullish if < 0, INVALIDATED if >= 10%)",
                validation_result=oil_valid,
                score_contribution=oil_contrib,
                data_source=SignalValidator.create_data_source(
                    "FRED", "DCOILWTICO", "https://fred.stlouisfed.org/series/DCOILWTICO"
                ),
            ))

        return validated_signals
    
    def create_prompt(self) -> PromptTemplate:
        """Create prompt for inflation analysis"""
        return PromptTemplate(
            input_variables=["query"],
            template="""You are an expert macro economist analyzing inflation and economic data for Bitcoin investment decisions.

Knowledge Base Context:
{{context}}

Task: Analyze the provided inflation and economic data. Score from 0-100 where:
- 0-20: Inflation rising sharply, recession risk high
- 21-40: Inflation rising, growth slowing
- 41-60: Inflation stable, mixed signals
- 61-80: Inflation falling, growth stable
- 81-100: Inflation falling fast, Fed likely to ease

Consider:
- CPI/PCE month-over-month trends (MoM focus, not YoY)
- Energy prices (oil, gas)
- Recession risk indicators

Provide your analysis in this format:
Score: [0-100]
Signals:
- [Key signal 1]
- [Key signal 2]
Reasoning: [Detailed explanation]

Query: {query}
"""
        )

