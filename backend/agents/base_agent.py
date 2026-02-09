"""
Base agent class for all analysis agents
"""
from abc import ABC, abstractmethod
from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from typing import Dict, Any
import os
from dotenv import load_dotenv

from rag.retriever import get_retriever
from models.schemas import SectionScore

load_dotenv()


class BaseAgent(ABC):
    """Base class for all analysis agents"""
    
    def __init__(self, section_name: str):
        self.section_name = section_name
        self.llm = ChatOpenAI(
            model="gpt-4o",
            temperature=0.3,
            api_key=os.getenv("OPENAI_API_KEY")
        )
        self.retriever = get_retriever(k=5)
        
    def get_relevant_knowledge(self, query: str) -> str:
        """Retrieve relevant knowledge from RAG"""
        docs = self.retriever.get_relevant_documents(query)
        return "\n\n".join([doc.page_content for doc in docs])
    
    @abstractmethod
    def fetch_data(self) -> Dict[str, Any]:
        """Fetch relevant real-time data"""
        pass
    
    @abstractmethod
    def create_prompt(self) -> PromptTemplate:
        """Create the prompt template for this agent"""
        pass
    
    def analyze(self) -> SectionScore:
        """Run the full analysis pipeline"""
        # Fetch data
        data = self.fetch_data()
        
        # Get relevant knowledge from RAG
        knowledge_query = f"{self.section_name} analysis framework scoring methodology"
        docs = self.retriever.get_relevant_documents(knowledge_query)
        knowledge = "\n\n".join([doc.page_content for doc in docs])
        
        # Create prompt
        prompt_template = self.create_prompt()
        
        # Format data for prompt
        data_str = self._format_data(data)
        
        # Build full prompt
        query = f"""
        Current market data:
        {data_str}
        
        Knowledge Base Context:
        {knowledge}
        
        Using the knowledge base framework, analyze this data and provide:
        1. A score from 0-100
        2. Key signals detected
        3. Reasoning for the score
        """
        
        # Run LLM
        formatted_prompt = prompt_template.format(query=query)
        result_text = self.llm.invoke(formatted_prompt).content
        
        # Parse result and create SectionScore
        return self._parse_result({"result": result_text}, data)
    
    def _format_data(self, data: Dict[str, Any]) -> str:
        """Format data dictionary as string"""
        import json
        return json.dumps(data, indent=2, default=str)
    
    def _parse_result(self, result: Dict, data: Dict) -> SectionScore:
        """Parse LLM result into SectionScore"""
        # Extract from result
        answer = result.get("result", "")
        
        # Try to extract score, signals, and reasoning
        # This is a simplified parser - in production, use structured output
        score = self._extract_score(answer)
        signals = self._extract_signals(answer)
        reasoning = self._extract_reasoning(answer)
        
        return SectionScore(
            name=self.section_name,
            score=score,
            signals=signals,
            reasoning=reasoning,
            data_used=data
        )
    
    def _extract_score(self, text: str) -> int:
        """Extract score from text (0-100)"""
        import re
        # Look for patterns like "score: 65" or "65/100"
        patterns = [
            r"score[:\s]+(\d+)",
            r"(\d+)/100",
            r"(\d+)\s*out\s*of\s*100"
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                score = int(match.group(1))
                return max(0, min(100, score))  # Clamp to 0-100
        
        # Default to 50 if no score found
        return 50
    
    def _extract_signals(self, text: str) -> list:
        """Extract key signals from text"""
        import re
        signals = []
        
        # Look for bullet points or numbered lists
        lines = text.split("\n")
        for line in lines:
            line = line.strip()
            if line.startswith("-") or line.startswith("•") or re.match(r"^\d+\.", line):
                signal = re.sub(r"^[-•\d.\s]+", "", line).strip()
                if signal and len(signal) > 10:  # Filter out very short items
                    signals.append(signal)
        
        return signals[:5]  # Return top 5 signals
    
    def _extract_reasoning(self, text: str) -> str:
        """Extract reasoning from text"""
        # Look for reasoning section
        if "reasoning:" in text.lower():
            parts = text.lower().split("reasoning:")
            if len(parts) > 1:
                return parts[1].strip()
        
        # Otherwise return first paragraph or first 200 chars
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        if paragraphs:
            return paragraphs[0][:500]  # Limit length
        
        return text[:500] if text else "Analysis completed"

