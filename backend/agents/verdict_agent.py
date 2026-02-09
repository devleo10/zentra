"""
Agent for Section 7: Final Bias Calculation
"""
from typing import Dict, Any, List

from models.schemas import (
    SectionScore, VerdictResponse, BiasType, ActionType
)


class VerdictAgent:
    """Calculates final weighted score and verdict"""
    
    def __init__(self):
        self.weights = {
            "Inflation & Economy": 0.20,
            "Federal Reserve Signals": 0.25,
            "Liquidity & Bonds": 0.20,
            "US Dollar (DXY)": 0.20,
            "Risk Sentiment": 0.15
        }
    
    def calculate_verdict(self, sections: List[SectionScore]) -> VerdictResponse:
        """
        Calculate final weighted score and determine bias/action
        
        Args:
            sections: List of 6 section scores (excluding verdict)
            
        Returns:
            VerdictResponse with final score, bias, and action
        """
        # Calculate weighted score
        weighted_sum = 0.0
        total_weight = 0.0
        
        for section in sections:
            weight = self.weights.get(section.name, 0.0)
            weighted_sum += section.score * weight
            total_weight += weight
        
        final_score = int(round(weighted_sum / total_weight if total_weight > 0 else 50))
        
        # Determine bias
        if final_score >= 80:
            bias = BiasType.STRONG_BULL
            action = ActionType.ACCUMULATE_AGGRESSIVELY
            confidence = "High"
        elif final_score >= 60:
            bias = BiasType.BULLISH
            action = ActionType.HOLD_ADD_DIPS
            confidence = "Medium-High"
        elif final_score >= 40:
            bias = BiasType.NEUTRAL
            action = ActionType.SMALL_POSITIONS
            confidence = "Medium"
        elif final_score >= 20:
            bias = BiasType.BEARISH
            action = ActionType.CAPITAL_PROTECTION
            confidence = "Medium"
        else:
            bias = BiasType.HIGH_RISK
            action = ActionType.STAY_OUT
            confidence = "Low"
        
        # Generate summary
        summary = self._generate_summary(sections, final_score, bias)
        
        return VerdictResponse(
            sections=sections,
            final_score=final_score,
            bias=bias,
            action=action,
            confidence=confidence,
            summary=summary
        )
    
    def _generate_summary(self, sections: List[SectionScore], score: int, bias: BiasType) -> str:
        """Generate human-readable summary"""
        top_signals = []
        for section in sorted(sections, key=lambda x: x.score, reverse=True)[:3]:
            if section.signals:
                top_signals.append(f"{section.name}: {section.signals[0]}")
        
        signals_str = "; ".join(top_signals) if top_signals else "Mixed signals"
        
        return (
            f"Macro Score: {score}/100 = {bias.value}. "
            f"Key factors: {signals_str}. "
            f"Overall macro conditions {'favor' if score >= 60 else 'challenge' if score < 40 else 'are neutral for'} BTC."
        )

