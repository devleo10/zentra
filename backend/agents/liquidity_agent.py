"""
Agent for Section 3: Liquidity & Bonds Analysis
"""
from langchain_core.prompts import PromptTemplate
from typing import Dict, Any

from .base_agent import BaseAgent
from data_fetchers import fred_data


class LiquidityAgent(BaseAgent):
    """Analyzes liquidity conditions and bond markets"""
    
    def __init__(self):
        super().__init__("Liquidity & Bonds")
    
    def fetch_data(self) -> Dict[str, Any]:
        """Fetch bond yields and Fed balance sheet data"""
        yields = fred_data.get_treasury_yields()
        balance_sheet = fred_data.get_fed_balance_sheet()
        
        return {
            "yields": yields,
            "balance_sheet": balance_sheet
        }
    
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

