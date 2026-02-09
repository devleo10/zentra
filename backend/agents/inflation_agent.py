"""
Agent for Section 1: Inflation & Economy Analysis
"""
from langchain_core.prompts import PromptTemplate
from typing import Dict, Any

from .base_agent import BaseAgent
from data_fetchers import fred_data, yahoo_data


class InflationAgent(BaseAgent):
    """Analyzes inflation and economic indicators"""
    
    def __init__(self):
        super().__init__("Inflation & Economy")
    
    def fetch_data(self) -> Dict[str, Any]:
        """Fetch inflation and economic data"""
        return {
            "cpi": fred_data.get_cpi_data(),
            "pce": fred_data.get_pce_data(),
            "oil": yahoo_data.get_gold_data()  # Using gold as proxy for commodities
        }
    
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

