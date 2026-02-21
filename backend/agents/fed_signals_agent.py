"""
Agent for Section 2: Federal Reserve Signals Analysis
"""
from langchain_core.prompts import PromptTemplate
from typing import Dict, Any

from .base_agent import BaseAgent
from .signal_validator import SignalValidator
from models.schemas import ValidatedSignal, DataSource, SignalValidationStatus
from data_fetchers import news_data
from typing import List
from datetime import datetime


class FedSignalsAgent(BaseAgent):
    """Analyzes Federal Reserve signals and policy direction"""
    
    def __init__(self):
        super().__init__("Federal Reserve Signals")
    
    def fetch_data(self, timeframe: str = "current") -> Dict[str, Any]:
        """Fetch Fed speeches and analyze keywords with timeframe support"""
        # Map timeframe to days for news search
        days_map = {"current": 3, "week": 7, "month": 30, "year": 90}
        days = days_map.get(timeframe, 7)
        articles = news_data.get_fed_speeches(days=days)
        keyword_analysis = news_data.analyze_fed_keywords(articles)
        
        data_sources = [
            SignalValidator.create_data_source(
                name="NewsAPI",
                url="https://newsapi.org",
                data_as_of=datetime.now()
            )
        ]
        
        return {
            "recent_articles": articles[:5],  # Top 5 most recent
            "keyword_analysis": keyword_analysis,
            "_data_sources": data_sources
        }
    
    def validate_signals(self, data: Dict[str, Any]) -> List[ValidatedSignal]:
        """Validate Fed signal keywords"""
        validated_signals = []
        keyword_analysis = data.get("keyword_analysis", {})
        
        data_sources = data.get("_data_sources", [])
        source = data_sources[0] if data_sources else SignalValidator.create_data_source("NewsAPI")
        
        dovish_count = keyword_analysis.get("dovish_keywords_found", 0)
        hawkish_count = keyword_analysis.get("hawkish_keywords_found", 0)
        
        if dovish_count > hawkish_count:
            validated_signals.append(ValidatedSignal(
                name=f"Dovish tone detected ({dovish_count} dovish keywords)",
                value=dovish_count,
                previous_value=hawkish_count,
                trend_direction="down",
                validation_status=SignalValidationStatus.VALIDATED,
                validation_check=f"dovish_count ({dovish_count}) > hawkish_count ({hawkish_count})",
                validation_result=True,
                score_contribution=20.0,
                data_source=source
            ))
        elif hawkish_count > dovish_count:
            validated_signals.append(ValidatedSignal(
                name=f"Hawkish tone detected ({hawkish_count} hawkish keywords)",
                value=hawkish_count,
                previous_value=dovish_count,
                trend_direction="up",
                validation_status=SignalValidationStatus.VALIDATED,
                validation_check=f"hawkish_count ({hawkish_count}) > dovish_count ({dovish_count})",
                validation_result=True,
                score_contribution=0.0,
                data_source=source
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

