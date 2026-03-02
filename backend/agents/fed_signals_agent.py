"""
Agent for Section 2: Federal Reserve Signals Analysis
"""
from langchain_core.prompts import PromptTemplate
from typing import Dict, Any

from .base_agent import BaseAgent
from .signal_validator import SignalValidator
from models.schemas import ValidatedSignal, DataSource, SignalValidationStatus
from data_fetchers import news_data, fred_data
from typing import List
from datetime import datetime


class FedSignalsAgent(BaseAgent):
    """Analyzes Federal Reserve signals and policy direction"""
    
    def __init__(self):
        super().__init__("Federal Reserve Signals")
    
    def fetch_data(self, timeframe: str = "current") -> Dict[str, Any]:
        """Fetch Fed speeches, keyword analysis, and actual Fed Funds Rate."""
        days_map = {"current": 3, "week": 7, "month": 30, "year": 90}
        days = days_map.get(timeframe, 7)
        articles = news_data.get_fed_speeches(days=days)
        keyword_analysis = news_data.analyze_fed_keywords(articles)

        # Fetch actual Fed Funds Rate from FRED (FEDFUNDS series)
        fed_rate_data = fred_data.get_fed_funds_rate(timeframe)

        fred_source = SignalValidator.create_data_source(
            name="FRED",
            series_id="FEDFUNDS",
            url="https://fred.stlouisfed.org/series/FEDFUNDS",
            data_as_of=datetime.now()
        )
        data_sources = [
            SignalValidator.create_data_source(
                name="NewsAPI",
                url="https://newsapi.org",
                data_as_of=datetime.now()
            ),
            fred_source,
        ]

        return {
            "recent_articles": articles[:5],
            "keyword_analysis": keyword_analysis,
            "fed_rate": fed_rate_data,
            "_data_sources": data_sources,
        }
    
    def validate_signals(self, data: Dict[str, Any]) -> List[ValidatedSignal]:
        """Validate Fed signals: keyword tone + actual Fed Funds Rate level/direction."""
        validated_signals = []
        keyword_analysis = data.get("keyword_analysis", {})

        data_sources = data.get("_data_sources", [])
        news_source = data_sources[0] if data_sources else SignalValidator.create_data_source("NewsAPI")
        fred_source = data_sources[1] if len(data_sources) > 1 else SignalValidator.create_data_source("FRED")

        # 1. Keyword tone signal
        dovish_count = keyword_analysis.get("dovish_keywords_found", 0)
        hawkish_count = keyword_analysis.get("hawkish_keywords_found", 0)

        if dovish_count > hawkish_count:
            validated_signals.append(ValidatedSignal(
                name=f"Dovish tone detected ({dovish_count} dovish keywords)",
                value=float(dovish_count),
                previous_value=float(hawkish_count),
                trend_direction="down",
                validation_status=SignalValidationStatus.VALIDATED,
                validation_check=f"dovish_count ({dovish_count}) > hawkish_count ({hawkish_count})",
                validation_result=True,
                score_contribution=20.0,
                data_source=news_source,
            ))
        elif hawkish_count > dovish_count:
            validated_signals.append(ValidatedSignal(
                name=f"Hawkish tone detected ({hawkish_count} hawkish keywords)",
                value=float(hawkish_count),
                previous_value=float(dovish_count),
                trend_direction="up",
                validation_status=SignalValidationStatus.VALIDATED,
                validation_check=f"hawkish_count ({hawkish_count}) > dovish_count ({dovish_count})",
                validation_result=True,
                score_contribution=0.0,
                data_source=news_source,
            ))

        # 2. Fed Funds Rate level and direction signal
        fed_rate_data = data.get("fed_rate", {})
        current_rate = fed_rate_data.get("current_rate")
        rate_trend = fed_rate_data.get("trend", "stable")

        if current_rate is not None:
            # Rate level: low rate = bullish for BTC
            if current_rate <= 1.0:
                rate_label = "very low (ultra-accommodative)"
                rate_score_contrib = 15.0
            elif current_rate <= 2.5:
                rate_label = "low (accommodative)"
                rate_score_contrib = 10.0
            elif current_rate <= 4.0:
                rate_label = "neutral"
                rate_score_contrib = 5.0
            elif current_rate <= 5.5:
                rate_label = "high (restrictive)"
                rate_score_contrib = 0.0
            else:
                rate_label = "very high (deeply restrictive)"
                rate_score_contrib = 0.0

            # Direction bonus/penalty
            direction_adj = 5.0 if rate_trend == "falling" else (-5.0 if rate_trend == "rising" else 0.0)
            final_rate_contrib = max(0.0, min(15.0, rate_score_contrib + direction_adj))

            is_bullish_rate = current_rate <= 4.0 or rate_trend == "falling"
            validation_status = (
                SignalValidationStatus.VALIDATED if is_bullish_rate
                else SignalValidationStatus.NEUTRALIZED
            )
            validated_signals.append(ValidatedSignal(
                name=f"Fed Funds Rate at {current_rate:.2f}% ({rate_label}, trend: {rate_trend})",
                value=current_rate,
                previous_value=fed_rate_data.get("previous_rate"),
                trend_direction="down" if rate_trend == "falling" else "up" if rate_trend == "rising" else "flat",
                validation_status=validation_status,
                validation_check=f"rate={current_rate:.2f}%, trend={rate_trend}",
                validation_result=is_bullish_rate,
                score_contribution=final_rate_contrib,
                data_source=fred_source,
                notes=f"Rate direction adjustment: {direction_adj:+.1f}",
            ))

        return validated_signals
    
    def create_prompt(self) -> PromptTemplate:
        """Create prompt for Fed signals analysis"""
        return PromptTemplate(
            input_variables=["query"],
            template="""You are an expert at decoding Federal Reserve communication for market signals.

Knowledge Base Context:
{{context}}

Task: Analyze Fed speeches and statements. Score from 0-100 where:
- 0-20: Very hawkish ("higher for longer", "inflation sticky")
- 21-40: Hawkish (rate hikes likely)
- 41-60: Neutral/data dependent
- 61-80: Dovish (pivot signals, "policy is restrictive")
- 81-100: Very dovish (rate cuts expected, QE mentioned)

Key Dovish Keywords: "data dependent", "disinflation", "policy is restrictive", "balanced risks", "financial conditions tightening", "tools are available"
Key Hawkish Keywords: "higher for longer", "inflation sticky", "labor market strong", "premature easing", "upside risks"
Pivot Signals: "at or near terminal rate", "lagged effects", "monitoring credit conditions", "financial stability"

Provide your analysis in this format:
Score: [0-100]
Signals:
- [Key signal 1]
- [Key signal 2]
Reasoning: [Detailed explanation of Fed tone and implications for BTC]

Query: {query}
"""
        )

