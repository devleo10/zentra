"""
Agent for Section 5: Risk Sentiment Analysis
"""
from langchain_core.prompts import PromptTemplate
from typing import Dict, Any

from .base_agent import BaseAgent
from data_fetchers import yahoo_data


class RiskAgent(BaseAgent):
    """Analyzes overall market risk sentiment"""
    
    def __init__(self):
        super().__init__("Risk Sentiment")
    
    def fetch_data(self) -> Dict[str, Any]:
        """Fetch risk sentiment indicators"""
        vix = yahoo_data.get_vix_data()
        sp500 = yahoo_data.get_sp500_data()
        gold = yahoo_data.get_gold_data()
        
        return {
            "vix": vix,
            "sp500": sp500,
            "gold": gold
        }
    
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

