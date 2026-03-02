"""
Agent for Section 4: US Dollar (DXY) Analysis
"""
from langchain_core.prompts import PromptTemplate
from typing import Dict, Any

from .base_agent import BaseAgent
from .signal_validator import SignalValidator
from models.schemas import ValidatedSignal, DataSource, SignalValidationStatus
from data_fetchers import yahoo_data, coingecko_data
from typing import List
from datetime import datetime


class DXYAgent(BaseAgent):
    """Analyzes US Dollar strength and its impact on Bitcoin"""
    
    def __init__(self):
        super().__init__("US Dollar (DXY)")
    
    def fetch_data(self, timeframe: str = "current") -> Dict[str, Any]:
        """Fetch DXY and BTC correlation data with timeframe support"""
        dxy = yahoo_data.get_dxy_data(timeframe)
        btc = coingecko_data.get_btc_price(timeframe)
        
        data_sources = [
            SignalValidator.create_data_source(
                "Yahoo Finance", "^DX-Y.NYB", "https://finance.yahoo.com/quote/DX-Y.NYB"
            )
        ]
        
        return {
            "dxy": dxy,
            "btc": btc,
            "correlation_note": "Bitcoin is anti-Dollar. When DXY falls, BTC typically rises.",
            "_data_sources": data_sources
        }
    
    def validate_signals(self, data: Dict[str, Any]) -> List[ValidatedSignal]:
        """Validate DXY signals"""
        validated_signals = []
        validator = SignalValidator()
        dxy = data.get("dxy", {})
        
        data_sources = data.get("_data_sources", [])
        source = data_sources[0] if data_sources else SignalValidator.create_data_source("Yahoo Finance")
        
        current_price = dxy.get("current_price")
        change = dxy.get("change", dxy.get("week_change", 0))
        
        if current_price and abs(change) >= 0.5:
            # Correct calculation: if current = previous * (1 + change/100), then previous = current / (1 + change/100)
            previous_price = current_price / (1 + change/100) if change != -100 else current_price
            signal = validator.validate_dxy_trend(
                current_price,
                previous_price,
                source
            )
            validated_signals.append(signal)
        
        return validated_signals
    
    def create_prompt(self) -> PromptTemplate:
        """Create prompt for DXY analysis"""
        return PromptTemplate(
            input_variables=["query"],
            template="""You are an expert currency and Bitcoin correlation analyst.

Knowledge Base Context:
{{context}}

Task: Analyze US Dollar (DXY) strength. Score from 0-100 where:
- 0-20: DXY very strong (>107), risk assets pressured, bearish for BTC
- 21-40: DXY strengthening or elevated (104-107), negative for BTC
- 41-60: DXY stable/range-bound (~100-104), neutral
- 61-80: DXY weakening or low (95-100), bullish for BTC
- 81-100: DXY collapsing or very weak (<95), very bullish for BTC and risk assets

Key Rule: Bitcoin is anti-Dollar. When DXY falls OR is at a low absolute level, BTC typically rises.
IMPORTANT: Consider BOTH the direction (7D trend) AND the absolute level of DXY.
A DXY at 106 with 0% change is still bearish for BTC. A DXY at 92 with 0% change is still bullish.

Consider:
- DXY current absolute price level (critical — not just direction)
- DXY 7D/30D trend direction
- DXY correlation with BTC price movement
- Emerging market stress (strong USD = EM outflows)

Interpretation:
- DXY > 105: Strong dollar headwind for BTC
- DXY 100-105: Neutral zone
- DXY < 100: Weak dollar tailwind for BTC
- DXY topping → stocks & commodities next
- Weak USD → money flows into EM, crypto, metals

Provide your analysis in this format:
Score: [0-100]
Signals:
- [Key signal 1]
- [Key signal 2]
Reasoning: [Detailed explanation of DXY trend and BTC implications]

Query: {query}
"""
        )

