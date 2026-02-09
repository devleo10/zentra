"""
Orchestrator to run all 7 agents in sequence
"""
from typing import List, Optional
from models.schemas import SectionScore, VerdictResponse

from .inflation_agent import InflationAgent
from .fed_signals_agent import FedSignalsAgent
from .liquidity_agent import LiquidityAgent
from .dxy_agent import DXYAgent
from .risk_agent import RiskAgent
from .bitcoin_agent import BitcoinAgent
from .verdict_agent import VerdictAgent


class AgentOrchestrator:
    """Orchestrates all analysis agents"""
    
    def __init__(self):
        self.agents = {
            "inflation": InflationAgent(),
            "fed": FedSignalsAgent(),
            "liquidity": LiquidityAgent(),
            "dxy": DXYAgent(),
            "risk": RiskAgent(),
            "bitcoin": BitcoinAgent()
        }
        self.verdict_agent = VerdictAgent()
    
    def run_full_analysis(self, sections: Optional[List[str]] = None) -> VerdictResponse:
        """
        Run full analysis across all sections
        
        Args:
            sections: Optional list of specific sections to analyze.
                     If None, analyzes all 6 sections.
        
        Returns:
            VerdictResponse with all scores and final verdict
        """
        section_scores: List[SectionScore] = []
        
        # Determine which sections to run
        sections_to_run = sections if sections else list(self.agents.keys())
        
        # Run each agent
        for section_name in sections_to_run:
            if section_name in self.agents:
                try:
                    print(f"Running {section_name} agent...")
                    agent = self.agents[section_name]
                    score = agent.analyze()
                    section_scores.append(score)
                    print(f"{section_name} agent completed: Score {score.score}")
                except Exception as e:
                    print(f"Error in {section_name} agent: {e}")
                    # Create a default score on error
                    section_scores.append(SectionScore(
                        name=agent.section_name if 'agent' in locals() else section_name,
                        score=50,
                        signals=[],
                        reasoning=f"Error during analysis: {str(e)}"
                    ))
        
        # Calculate final verdict
        verdict = self.verdict_agent.calculate_verdict(section_scores)
        
        return verdict
    
    def run_single_section(self, section_name: str) -> SectionScore:
        """
        Run analysis for a single section
        
        Args:
            section_name: Name of section to analyze
        
        Returns:
            SectionScore for that section
        """
        if section_name not in self.agents:
            raise ValueError(f"Unknown section: {section_name}")
        
        agent = self.agents[section_name]
        return agent.analyze()

