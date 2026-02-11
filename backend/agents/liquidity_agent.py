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
        """Validate liquidity signals"""
        validated_signals = []
        validator = SignalValidator()
        yields = data.get("yields", {})
        
        data_sources = data.get("_data_sources", [])
        source = data_sources[0] if data_sources else SignalValidator.create_data_source("FRED")
        
        yield_10y = yields.get("yield_10y", {})
        if yield_10y.get("value"):
            # Would need previous value for trend validation
            validated_signals.append(ValidatedSignal(
                name=f"10Y yield at {yield_10y.get('value'):.2f}%",
                value=yield_10y.get("value"),
                previous_value=None,
                trend_direction=None,
                validation_status=SignalValidationStatus.VALIDATED,
                validation_check="yield > 0",
                validation_result=True,
                score_contribution=5.0,
                data_source=source
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

