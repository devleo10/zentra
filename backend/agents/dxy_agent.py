"""
Agent for Section 4: US Dollar (DXY) Analysis
"""
from langchain_core.prompts import PromptTemplate
from typing import Dict, Any

from .base_agent import BaseAgent
from data_fetchers import yahoo_data, coingecko_data


class DXYAgent(BaseAgent):
    """Analyzes US Dollar strength and its impact on Bitcoin"""
    
    def __init__(self):
        super().__init__("US Dollar (DXY)")
    
    def fetch_data(self) -> Dict[str, Any]:
        """Fetch DXY and BTC correlation data"""
        dxy = yahoo_data.get_dxy_data()
        btc = coingecko_data.get_btc_price()
        
        return {
            "dxy": dxy,
            "btc": btc,
            "correlation_note": "Bitcoin is anti-Dollar. When DXY falls, BTC typically rises."
        }
    
    def create_prompt(self) -> PromptTemplate:
        """Create prompt for DXY analysis"""
        return PromptTemplate(
            input_variables=["query"],
            template="""You are an expert currency and Bitcoin correlation analyst.

Knowledge Base Context:
{{context}}

Task: Analyze US Dollar (DXY) strength. Score from 0-100 where:
- 0-20: DXY very strong, risk assets pressured, bearish for BTC
- 21-40: DXY strengthening, negative for BTC
- 41-60: DXY stable/range-bound, neutral
- 61-80: DXY weakening, bullish for BTC
- 81-100: DXY collapsing, very bullish for BTC and risk assets

Key Rule: Bitcoin is anti-Dollar. When DXY falls, BTC typically rises.

Consider:
- DXY current price and 7D/30D trends
- DXY correlation with BTC price movement
- Emerging market stress (strong USD = EM outflows)

Interpretation:
- DXY topping → stocks & commodities next
- Strong USD → pressure on risk assets
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

