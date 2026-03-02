"""
Agent for Section 5: Risk Sentiment Analysis
"""
from langchain_core.prompts import PromptTemplate
from typing import Dict, Any

from .base_agent import BaseAgent
from .signal_validator import SignalValidator
from models.schemas import ValidatedSignal, DataSource, SignalValidationStatus
from data_fetchers import yahoo_data
from typing import List
from datetime import datetime


class RiskAgent(BaseAgent):
    """Analyzes overall market risk sentiment"""
    
    def __init__(self):
        super().__init__("Risk Sentiment")
    
    def fetch_data(self, timeframe: str = "current") -> Dict[str, Any]:
        """Fetch risk sentiment indicators with timeframe support"""
        vix = yahoo_data.get_vix_data(timeframe)
        sp500 = yahoo_data.get_sp500_data(timeframe)
        gold = yahoo_data.get_gold_data(timeframe)
        
        data_sources = [
            SignalValidator.create_data_source("CBOE", "^VIX", "https://www.cboe.com/tradable_products/vix/")
        ]
        
        return {
            "vix": vix,
            "sp500": sp500,
            "gold": gold,
            "_data_sources": data_sources
        }
    
    def validate_signals(self, data: Dict[str, Any]) -> List[ValidatedSignal]:
        """Validate risk sentiment signals: VIX level, S&P 500 trend, and gold safe-haven signal."""
        validated_signals = []
        validator = SignalValidator()
        vix = data.get("vix", {})
        sp500 = data.get("sp500", {})
        gold = data.get("gold", {})

        data_sources = data.get("_data_sources", [])
        vix_source = data_sources[0] if data_sources else SignalValidator.create_data_source("CBOE")

        # 1. VIX level — extreme fear (>30) INVALIDATES bullish thesis
        vix_value = vix.get("current_value")
        if vix_value is not None:
            signal = validator.validate_vix_level(vix_value, vix_source)
            validated_signals.append(signal)

        # 2. S&P 500 trend — rising equities = risk-on = bullish for BTC
        sp500_change = sp500.get("change", sp500.get("change_7d"))
        if sp500_change is not None and not sp500.get("error"):
            if sp500_change > 1.0:
                sp500_label = f"rising strongly (+{sp500_change:.1f}%) — risk-on"
                sp500_contrib = 10.0
                sp500_status = SignalValidationStatus.VALIDATED
                sp500_valid = True
                sp500_notes = None
            elif sp500_change > 0:
                sp500_label = f"rising ({sp500_change:+.1f}%) — mild risk-on"
                sp500_contrib = 5.0
                sp500_status = SignalValidationStatus.VALIDATED
                sp500_valid = True
                sp500_notes = None
            elif sp500_change < -1.0:
                sp500_label = f"falling ({sp500_change:.1f}%) — risk-off"
                sp500_contrib = 0.0
                sp500_status = SignalValidationStatus.NEUTRALIZED
                sp500_valid = False
                sp500_notes = f"S&P 500 falling {sp500_change:.1f}% — risk-off environment weighs on BTC"
            else:
                sp500_label = f"flat ({sp500_change:+.1f}%)"
                sp500_contrib = 3.0
                sp500_status = SignalValidationStatus.VALIDATED
                sp500_valid = True
                sp500_notes = None

            validated_signals.append(ValidatedSignal(
                name=f"S&P 500 {sp500_label}",
                value=float(sp500.get("current_price", 0) or 0),
                previous_value=None,
                trend_direction="up" if sp500_change > 0 else "down",
                validation_status=sp500_status,
                validation_check=f"sp500_change > -1.0% (actual: {sp500_change:+.1f}%)",
                validation_result=sp500_valid,
                score_contribution=sp500_contrib,
                data_source=SignalValidator.create_data_source(
                    "Yahoo Finance", "^GSPC", "https://finance.yahoo.com/quote/%5EGSPC"
                ),
                notes=sp500_notes,
            ))

        # 3. Gold safe-haven signal — sharp gold rally = flight to safety = risk-off
        gold_change = gold.get("change", gold.get("change_7d"))
        if gold_change is not None and not gold.get("error"):
            if gold_change > 3.0:
                gold_label = f"safe-haven rally (+{gold_change:.1f}%) — flight to safety"
                gold_contrib = 0.0
                gold_status = SignalValidationStatus.INVALIDATED
                gold_valid = False
                gold_notes = f"Gold +{gold_change:.1f}%: strong safe-haven demand signals risk-off — bearish for BTC"
            elif gold_change > 1.0:
                gold_label = f"rising moderately (+{gold_change:.1f}%)"
                gold_contrib = 2.0
                gold_status = SignalValidationStatus.VALIDATED
                gold_valid = True
                gold_notes = None
            elif gold_change < -1.0:
                gold_label = f"falling ({gold_change:.1f}%) — risk-on"
                gold_contrib = 5.0
                gold_status = SignalValidationStatus.VALIDATED
                gold_valid = True
                gold_notes = None
            else:
                gold_label = f"stable ({gold_change:+.1f}%)"
                gold_contrib = 3.0
                gold_status = SignalValidationStatus.VALIDATED
                gold_valid = True
                gold_notes = None

            validated_signals.append(ValidatedSignal(
                name=f"Gold {gold_label}",
                value=float(gold.get("current_price", 0) or 0),
                previous_value=None,
                trend_direction="up" if gold_change > 0 else "down",
                validation_status=gold_status,
                validation_check=f"gold_change <= 3.0% for non-INVALIDATED (actual: {gold_change:+.1f}%)",
                validation_result=gold_valid,
                score_contribution=gold_contrib,
                data_source=SignalValidator.create_data_source(
                    "Yahoo Finance", "GC=F", "https://finance.yahoo.com/quote/GC%3DF"
                ),
                notes=gold_notes,
            ))

        return validated_signals
    
    def create_prompt(self) -> PromptTemplate:
        """Create prompt for risk sentiment analysis"""
        return PromptTemplate(
            input_variables=["query"],
            template="""You are an expert market sentiment analyst.

Knowledge Base Context:
{{context}}

Task: Analyze overall risk sentiment. Score from 0-100 where:
- 0-20: Extreme risk-off, VIX high, flight to safety
- 21-40: Risk-off, defensive positioning
- 41-60: Mixed/neutral sentiment
- 61-80: Risk-on, equities strong, low VIX
- 81-100: Extreme risk-on, greed, potential top

Consider:
- VIX level (high = fear, low = complacency)
- S&P 500 trend (risk-on vs risk-off)
- Gold strength (safe haven demand)
- Overall market breadth

Signals:
- VIX spike + divergence → market bottom
- Extreme greed → distribution
- Fear but price stable → smart money buying

Provide your analysis in this format:
Score: [0-100]
Signals:
- [Key signal 1]
- [Key signal 2]
Reasoning: [Detailed explanation of risk sentiment and implications for BTC]

Query: {query}
"""
        )

