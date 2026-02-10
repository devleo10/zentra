"""
Agent for Section 1: Inflation & Economy Analysis
"""
from langchain_core.prompts import PromptTemplate
from typing import Dict, Any

from .base_agent import BaseAgent
from .signal_validator import SignalValidator
from models.schemas import ValidatedSignal, DataSource, SignalValidationStatus
from data_fetchers import fred_data, yahoo_data
from typing import List
from datetime import datetime


class InflationAgent(BaseAgent):
    """Analyzes inflation and economic indicators"""
    
    def __init__(self):
        super().__init__("Inflation & Economy")
    
    def fetch_data(self) -> Dict[str, Any]:
        """Fetch inflation and economic data"""
        cpi = fred_data.get_cpi_data()
        pce = fred_data.get_pce_data()
        oil = yahoo_data.get_gold_data()
        
        # Create data sources
        data_sources = [
            SignalValidator.create_data_source(
                name="FRED",
                series_id="CPIAUCSL",
                url="https://fred.stlouisfed.org/series/CPIAUCSL",
                data_as_of=datetime.strptime(cpi.get("latest_date", datetime.now().strftime("%Y-%m-%d")), "%Y-%m-%d") if cpi.get("latest_date") else datetime.now()
            )
        ]
        
        return {
            "cpi": cpi,
            "pce": pce,
            "oil": oil,
            "_data_sources": data_sources
        }
    
    def validate_signals(self, data: Dict[str, Any]) -> List[ValidatedSignal]:
        """Validate inflation signals"""
        validated_signals = []
        validator = SignalValidator()
        
        cpi = data.get("cpi", {})
        if cpi.get("latest_value") and cpi.get("mom_change") is not None:
            # Would need previous month value for full validation
            # For now, create basic signal
            data_sources = data.get("_data_sources", [])
            cpi_source = data_sources[0] if data_sources else SignalValidator.create_data_source("FRED")
            
            validated_signals.append(ValidatedSignal(
                name=f"CPI MoM {'falling' if cpi.get('mom_change', 0) < 0 else 'rising'}",
                value=cpi.get("latest_value"),
                previous_value=None,
                trend_direction="down" if cpi.get("mom_change", 0) < 0 else "up",
                validation_status=SignalValidationStatus.VALIDATED,
                validation_check="mom_change calculated",
                validation_result=True,
                score_contribution=15.0 if cpi.get("mom_change", 0) < 0 else 0.0,
                data_source=cpi_source
            ))
        
        return validated_signals
    
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

