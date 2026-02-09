"""
Agent for Section 6: Bitcoin Focus Analysis
"""
from langchain_core.prompts import PromptTemplate
from typing import Dict, Any

from .base_agent import BaseAgent
from data_fetchers import coingecko_data, yahoo_data


class BitcoinAgent(BaseAgent):
    """Analyzes Bitcoin-specific metrics and structure"""
    
    def __init__(self):
        super().__init__("Bitcoin Focus")
    
    def fetch_data(self) -> Dict[str, Any]:
        """Fetch Bitcoin-specific data"""
        btc = coingecko_data.get_btc_price()
        dominance = coingecko_data.get_btc_dominance()
        stablecoins = coingecko_data.get_stablecoin_data()
        eth_btc = coingecko_data.get_eth_btc_ratio()
        sp500 = yahoo_data.get_sp500_data()
        
        # Calculate BTC vs S&P performance
        btc_perf = btc.get("change_7d", 0)
        sp500_perf = sp500.get("week_change", 0)
        outperforming = btc_perf > sp500_perf
        
        return {
            "btc_price": btc,
            "btc_dominance": dominance,
            "stablecoins": stablecoins,
            "eth_btc_ratio": eth_btc,
            "btc_vs_sp500": {
                "btc_7d_change": btc_perf,
                "sp500_7d_change": sp500_perf,
                "outperforming": outperforming
            }
        }
    
    def create_prompt(self) -> PromptTemplate:
        """Create prompt for Bitcoin analysis"""
        return PromptTemplate(
            input_variables=["query"],
            template="""You are an expert Bitcoin and cryptocurrency analyst.

Knowledge Base Context:
{{context}}

Task: Analyze Bitcoin-specific metrics. Score from 0-100 where:
- 0-20: BTC breaking down, weak structure, below key support
- 21-40: BTC weak, underperforming stocks
- 41-60: BTC neutral, mixed signals
- 61-80: BTC strong, outperforming stocks, good structure
- 81-100: BTC very strong, breakout, accumulation signals

Consider:
- BTC price trend and structure (higher highs/higher lows)
- BTC dominance (rising = BTC leading, falling = altseason)
- Stablecoin flows (inflow = accumulation, outflow = distribution)
- ETH/BTC ratio (rising = risk-on, falling = risk-off)
- BTC vs S&P 500 relative performance

BTC Structure Check:
- Higher highs + volume → Strong bullish
- Sideways + accumulation → Neutral to bullish
- Below key MA → Bearish
- Breakdown → Very bearish

Provide your analysis in this format:
Score: [0-100]
Signals:
- [Key signal 1]
- [Key signal 2]
Reasoning: [Detailed explanation of BTC structure and metrics]

Query: {query}
"""
        )

