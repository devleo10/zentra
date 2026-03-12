"""
Agent for Economy Section: Jobs, GDP, PMI Analysis (v1 pipeline)
"""
from langchain_core.prompts import PromptTemplate
from typing import Dict, Any, List
from datetime import datetime

from .base_agent import BaseAgent
from .signal_validator import SignalValidator
from models.schemas import ValidatedSignal, DataSource, SignalValidationStatus
from data_fetchers import fred_data


class EconomyAgent(BaseAgent):
    """Analyzes employment, GDP growth, and manufacturing PMI indicators."""

    def __init__(self):
        super().__init__("Economy")

    def fetch_data(self, timeframe: str = "current") -> Dict[str, Any]:
        jobs = fred_data.get_jobs_data(timeframe)
        gdp = fred_data.get_gdp_data(timeframe)
        pmi = fred_data.get_pmi_data(timeframe)

        data_sources = [
            SignalValidator.create_data_source(
                name="FRED",
                series_id="UNRATE",
                url="https://fred.stlouisfed.org/series/UNRATE",
                data_as_of=jobs.get("data_as_of") or jobs.get("unemployment_date"),
            )
        ]

        return {
            "jobs": jobs,
            "gdp": gdp,
            "pmi": pmi,
            "_data_sources": data_sources,
        }

    def validate_signals(self, data: Dict[str, Any]) -> List[ValidatedSignal]:
        validated_signals = []
        validator = SignalValidator()

        # Unemployment rate
        jobs = data.get("jobs", {})
        ur = jobs.get("unemployment_rate")
        if ur is not None:
            trend = jobs.get("unemployment_trend", "stable")
            is_bullish = ur >= 4.5 or trend == "rising"
            contrib = 12.0 if ur >= 5.0 else 8.0 if ur >= 4.5 else 4.0 if trend == "rising" else 0.0
            ur_signal = ValidatedSignal(
                name=f"Unemployment {ur:.1f}% ({trend})",
                value=ur,
                previous_value=None,
                trend_direction="up" if trend == "rising" else "down" if trend == "falling" else "flat",
                validation_status=SignalValidationStatus.VALIDATED,
                validation_check=f"UNRATE={ur:.1f}%, trend={trend}",
                validation_result=is_bullish,
                score_contribution=contrib,
                data_source=SignalValidator.create_data_source(
                    "FRED", "UNRATE",
                    "https://fred.stlouisfed.org/series/UNRATE",
                    data_as_of=jobs.get("unemployment_date"),
                ),
            )
            validated_signals.append(
                validator.apply_freshness_guard(ur_signal, max_stale_hours=35 * 24)
            )

        # GDP growth
        gdp = data.get("gdp", {})
        gdp_rate = gdp.get("gdp_growth_rate")
        if gdp_rate is not None and not gdp.get("error"):
            gdp_trend = gdp.get("gdp_trend", "stable")
            is_bullish_gdp = gdp_rate < 2.0
            contrib = 10.0 if gdp_rate < 0 else 6.0 if gdp_rate < 1.5 else 0.0
            gdp_signal = ValidatedSignal(
                name=f"GDP growth {gdp_rate:+.1f}% ({gdp_trend})",
                value=gdp_rate,
                previous_value=None,
                trend_direction="down" if gdp_rate < 0 else "up",
                validation_status=SignalValidationStatus.VALIDATED,
                validation_check=f"GDP QoQ annualized={gdp_rate:+.1f}%",
                validation_result=is_bullish_gdp,
                score_contribution=contrib,
                data_source=SignalValidator.create_data_source(
                    "FRED", "A191RL1Q225SBEA",
                    "https://fred.stlouisfed.org/series/A191RL1Q225SBEA",
                    data_as_of=gdp.get("latest_date"),
                ),
            )
            validated_signals.append(
                validator.apply_freshness_guard(gdp_signal, max_stale_hours=120 * 24)
            )

        # PMI
        pmi = data.get("pmi", {})
        pmi_val = pmi.get("pmi_value")
        if pmi_val is not None and not pmi.get("error"):
            pmi_status = pmi.get("pmi_status", "expansion" if pmi_val >= 50 else "contraction")
            is_bullish_pmi = pmi_val < 50
            contrib = 10.0 if pmi_val < 48 else 5.0 if pmi_val < 50 else 0.0
            pmi_signal = ValidatedSignal(
                name=f"ISM PMI {pmi_val:.1f} ({pmi_status})",
                value=pmi_val,
                previous_value=None,
                trend_direction="down" if pmi_val < 50 else "up",
                validation_status=SignalValidationStatus.VALIDATED,
                validation_check=f"PMI={pmi_val:.1f}, status={pmi_status}",
                validation_result=is_bullish_pmi,
                score_contribution=contrib,
                data_source=SignalValidator.create_data_source(
                    "FRED", "NAPM",
                    "https://fred.stlouisfed.org/series/NAPM",
                    data_as_of=pmi.get("latest_date"),
                ),
            )
            validated_signals.append(
                validator.apply_freshness_guard(pmi_signal, max_stale_hours=35 * 24)
            )

        return validated_signals

    def create_prompt(self) -> PromptTemplate:
        return PromptTemplate(
            input_variables=["query"],
            template="""You are an expert macro economist analyzing employment, GDP, and manufacturing data for Bitcoin investment decisions.

Knowledge Base Context:
{{context}}

Task: Analyze the provided economy data. Score from 0-100 where:
- 0-20: Strong economy, tight labor market, Fed stays hawkish
- 21-40: Solid growth, moderate employment, Fed cautious
- 41-60: Mixed signals, some softening
- 61-80: Weakening economy, rising unemployment, Fed may pivot
- 81-100: Recession signals, collapsing PMI, Fed forced to ease

Consider:
- Unemployment rate level and trend (rising = bullish for BTC via Fed easing)
- GDP growth rate (weak = dovish Fed = bullish for BTC)
- ISM PMI (below 50 = contraction = dovish signal)
- Non-Farm Payrolls trend

Provide your analysis in this format:
Score: [0-100]
Signals:
- [Key signal 1]
- [Key signal 2]
Reasoning: [Detailed explanation]

Query: {query}
"""
        )
