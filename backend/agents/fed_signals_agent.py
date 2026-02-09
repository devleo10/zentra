"""
Agent for Section 2: Federal Reserve Signals Analysis
"""
from langchain_core.prompts import PromptTemplate
from typing import Dict, Any

from .base_agent import BaseAgent
from data_fetchers import news_data


class FedSignalsAgent(BaseAgent):
    """Analyzes Federal Reserve signals and policy direction"""
    
    def __init__(self):
        super().__init__("Federal Reserve Signals")
    
    def fetch_data(self) -> Dict[str, Any]:
        """Fetch Fed speeches and analyze keywords"""
        articles = news_data.get_fed_speeches(days=7)
        keyword_analysis = news_data.analyze_fed_keywords(articles)
        
        return {
            "recent_articles": articles[:5],  # Top 5 most recent
            "keyword_analysis": keyword_analysis
        }
    
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

