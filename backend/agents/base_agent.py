"""
Base agent class for all analysis agents
Production-grade with signal validation and data source tracking
"""
from abc import ABC, abstractmethod
from langchain_core.prompts import PromptTemplate
from typing import Dict, Any, List
import os
from datetime import datetime
from dotenv import load_dotenv

from rag.retriever import get_retriever
from models.schemas import SectionScore, ValidatedSignal, DataSource
from agents.signal_validator import SignalValidator

load_dotenv()


def get_llm():
    """Get LLM - try Gemini first, fallback to OpenAI"""
    # Prefer OpenAI when an OpenAI key is provided
    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key:
        try:
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=os.getenv("OPENAI_MODEL", "gpt-4o"),
                temperature=0.3,
                api_key=openai_key
            )
        except Exception:
            # If langchain_openai isn't available, fall back to trying Gemini
            pass

    # If OpenAI not present or failed, try Gemini (optional)
    gemini_key = os.getenv("GEMINI_API_KEY")
    if gemini_key:
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
            gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
            return ChatGoogleGenerativeAI(
                model=gemini_model,
                temperature=0.3,
                google_api_key=gemini_key
            )
        except Exception:
            # Could not initialize Gemini client
            pass

    raise ValueError("Neither OPENAI_API_KEY nor GEMINI_API_KEY (optional) could be used to initialize an LLM.\nPlease set OPENAI_API_KEY or a valid GEMINI_API_KEY in backend/.env")


class BaseAgent(ABC):
    """Base class for all analysis agents with validation"""
    
    def __init__(self, section_name: str):
        self.section_name = section_name
        self.llm = get_llm()
        self.retriever = get_retriever(k=5)
        self.validator = SignalValidator()
    
    def get_relevant_knowledge(self, query: str) -> str:
        """Retrieve relevant knowledge from RAG"""
        # Use invoke() for newer LangChain versions
        docs = self.retriever.invoke(query)
        return "\n\n".join([doc.page_content for doc in docs])
    
    @abstractmethod
    def fetch_data(self, timeframe: str = "current") -> Dict[str, Any]:
        """
        Fetch relevant real-time data
        
        Args:
            timeframe: One of 'current', 'week', 'month', 'year'
        
        Returns:
            Dictionary with data and DataSource metadata
        """
        pass
    
    @abstractmethod
    def validate_signals(self, data: Dict[str, Any]) -> List[ValidatedSignal]:
        """
        Validate all signals with boolean checks
        
        Args:
            data: Fetched data dictionary
        
        Returns:
            List of validated signals
        """
        pass
    
    @abstractmethod
    def create_prompt(self) -> PromptTemplate:
        """Create the prompt template for this agent"""
        pass
    
    def analyze(self, timeframe: str = "current") -> SectionScore:
        """Run the full analysis pipeline with validation"""
        # Fetch data with timeframe
        data = self.fetch_data(timeframe=timeframe)
        
        # Extract data sources
        data_sources = data.pop("_data_sources", [])
        
        # Validate signals
        validated_signals = self.validate_signals(data)
        
        # Get relevant knowledge from RAG
        knowledge_query = f"{self.section_name} analysis framework scoring methodology"
        # Use invoke() for newer LangChain versions
        docs = self.retriever.invoke(knowledge_query)
        knowledge = "\n\n".join([doc.page_content for doc in docs])
        
        # Create prompt
        prompt_template = self.create_prompt()
        
        # Get timeframe label for prompt
        timeframe_labels = {
            "current": "real-time/latest",
            "week": "7-day",
            "month": "30-day",
            "year": "365-day (annual)"
        }
        timeframe_label = timeframe_labels.get(timeframe, "current")
        
        # Format data for prompt (include validated signals)
        data_str = self._format_data(data)
        validated_signals_str = self._format_validated_signals(validated_signals)
        
        # Build full prompt with timeframe context
        query = f"""
        ANALYSIS TIMEFRAME: {timeframe_label} analysis
        
        Current market data:
        {data_str}
        
        Validated Signals (with truth checks):
        {validated_signals_str}
        
        Knowledge Base Context:
        {knowledge}
        
        Using the knowledge base framework, analyze this data for the {timeframe_label} timeframe and provide:
        1. A score from 0-100 (considering validated signals only)
        2. Key signals detected (must match validated signals)
        3. Reasoning for the score specific to the {timeframe_label} perspective
        
        IMPORTANT: Only use signals that passed validation. If a signal was neutralized, 
        do not claim it in your analysis. Be factually accurate. Focus on the {timeframe_label} trends.
        """
        
        # Run LLM
        formatted_prompt = prompt_template.format(query=query)
        result_text = self.llm.invoke(formatted_prompt).content
        
        # Parse result and create SectionScore with validation
        return self._parse_result(
            {"result": result_text},
            data,
            validated_signals,
            data_sources
        )
    
    def _format_data(self, data: Dict[str, Any]) -> str:
        """Format data dictionary as string"""
        import json
        # Remove internal keys
        clean_data = {k: v for k, v in data.items() if not k.startswith("_")}
        return json.dumps(clean_data, indent=2, default=str)
    
    def _format_validated_signals(self, signals: List[ValidatedSignal]) -> str:
        """Format validated signals for prompt"""
        lines = []
        for sig in signals:
            status_icon = "✓" if sig.validation_status.value == "validated" else "✗"
            lines.append(
                f"{status_icon} {sig.name}: {sig.value} "
                f"(previous: {sig.previous_value}, trend: {sig.trend_direction}) "
                f"[Status: {sig.validation_status.value}, Contribution: {sig.score_contribution:.1f}]"
            )
            if sig.notes:
                lines.append(f"  Note: {sig.notes}")
        return "\n".join(lines)
    
    def _parse_result(
        self,
        result: Dict,
        data: Dict,
        validated_signals: List[ValidatedSignal],
        data_sources: List[DataSource]
    ) -> SectionScore:
        """Parse LLM result into SectionScore with validation metadata"""
        answer = result.get("result", "")
        
        # Extract score, signals, and reasoning
        score = self._extract_score(answer)
        signals = self._extract_signals(answer)
        reasoning = self._extract_reasoning(answer)
        
        # Create validation summary
        validated_count = sum(1 for s in validated_signals if s.validation_status.value == "validated")
        neutralized_count = sum(1 for s in validated_signals if s.validation_status.value == "neutralized")
        total_score_contribution = sum(s.score_contribution for s in validated_signals)
        
        validation_summary = {
            "total_signals": len(validated_signals),
            "validated": validated_count,
            "neutralized": neutralized_count,
            "total_contribution": round(total_score_contribution, 1),
            "validation_rate": round((validated_count / len(validated_signals) * 100) if validated_signals else 0, 1)
        }
        
        return SectionScore(
            name=self.section_name,
            score=score,
            signals=signals,
            validated_signals=validated_signals,
            reasoning=reasoning,
            data_used=data,
            data_sources=data_sources,
            validation_summary=validation_summary
        )
    
    def _extract_score(self, text: str) -> int:
        """Extract score from text (0-100)"""
        import re
        patterns = [
            r"score[:\s]+(\d+)",
            r"(\d+)/100",
            r"(\d+)\s*out\s*of\s*100"
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                score = int(match.group(1))
                return max(0, min(100, score))
        
        return 50
    
    def _extract_signals(self, text: str) -> list:
        """Extract key signals from text"""
        import re
        signals = []
        
        lines = text.split("\n")
        for line in lines:
            line = line.strip()
            if line.startswith("-") or line.startswith("•") or re.match(r"^\d+\.", line):
                signal = re.sub(r"^[-•\d.\s]+", "", line).strip()
                if signal and len(signal) > 10:
                    signals.append(signal)
        
        return signals[:5]
    
    def _extract_reasoning(self, text: str) -> str:
        """Extract reasoning from text"""
        if "reasoning:" in text.lower():
            parts = text.lower().split("reasoning:")
            if len(parts) > 1:
                return parts[1].strip()
        
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        if paragraphs:
            return paragraphs[0][:500]
        
        return text[:500] if text else "Analysis completed"
