"""
Agent for Section 7: Final Bias Calculation
Production-grade with regime detection, computed confidence, and invalidation logic
"""
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime

from models.schemas import (
    SectionScore, VerdictResponse, BiasType, ActionType, RegimeType, ConfidenceLevel, TimeFrame
)
from .regime_detector import RegimeDetector
from .confidence_calculator import ConfidenceCalculator


class VerdictAgent:
    """Calculates final weighted score and verdict with full validation"""
    
    def __init__(self):
        self.regime_detector = RegimeDetector()
        self.confidence_calculator = ConfidenceCalculator()
    
    def calculate_verdict(
        self,
        sections: List[SectionScore],
        raw_data: Optional[Dict[str, Any]] = None,
        timeframe: TimeFrame = TimeFrame.CURRENT
    ) -> VerdictResponse:
        """
        Calculate final weighted score and determine bias/action
        
        Args:
            sections: List of 6 section scores
            raw_data: Raw data dictionary for regime detection
            timeframe: Timeframe of the analysis
        
        Returns:
            VerdictResponse with final score, bias, action, confidence, regime, invalidation conditions
        """
        if raw_data is None:
            raw_data = {}
        
        # Convert timeframe to enum if string
        if isinstance(timeframe, str):
            timeframe = TimeFrame(timeframe)
        # 1. Detect regime
        regime = self.regime_detector.detect_regime(sections, raw_data)
        
        # 2. Get regime-adaptive weights
        weights = self.regime_detector.get_regime_weights(regime)
        
        # 3. Calculate weighted score with breakdown
        score_breakdown = {}
        weighted_sum = 0.0
        total_weight = 0.0
        
        for section in sections:
            weight = weights.get(section.name, 0.0)
            contribution = section.score * weight
            weighted_sum += contribution
            total_weight += weight
            score_breakdown[section.name] = round(contribution, 2)
        
        final_score = int(round(weighted_sum / total_weight if total_weight > 0 else 50))
        
        # 4. Determine bias with output discipline (prevent overconfidence)
        bias, action = self._determine_bias_with_discipline(final_score, sections)
        
        # 5. Calculate confidence dynamically
        vix_value = raw_data.get("risk", {}).get("vix", {}).get("current_value")
        btc_volatility = raw_data.get("bitcoin", {}).get("volatility")
        
        confidence_score, confidence_level = self.confidence_calculator.calculate_confidence(
            sections, vix_value, btc_volatility
        )
        
        signal_agreement_pct = self.confidence_calculator.get_signal_agreement_pct(sections)
        data_freshness_score = self.confidence_calculator.get_data_freshness_score(sections)
        
        # 6. Identify dominant signals (top 2-3 driving the verdict)
        dominant_signals = self._identify_dominant_signals(sections, weights)
        
        # 7. Generate invalidation conditions
        invalidation_conditions = self._generate_invalidation_conditions(
            sections, dominant_signals, regime
        )
        
        # 8. Get most recent data timestamp
        data_timestamp = self._get_most_recent_timestamp(sections)
        
        # 9. Generate summary with discipline
        summary = self._generate_summary_with_discipline(
            sections, final_score, bias, confidence_level, regime
        )
        
        # 10. Create audit log
        audit_log = {
            "regime": regime.value,
            "weights_used": weights,
            "score_breakdown": score_breakdown,
            "signal_agreement_pct": round(signal_agreement_pct, 1),
            "data_freshness_score": round(data_freshness_score, 1),
            "confidence_components": {
                "signal_agreement": round(signal_agreement_pct * 0.4, 1),
                "data_freshness": round(data_freshness_score * 0.3, 1),
                "volatility": round((100 - (vix_value or 50) * 2) * 0.3, 1) if vix_value else 15.0
            },
            "calculation_timestamp": datetime.now().isoformat()
        }
        
        return VerdictResponse(
            timestamp=datetime.now(),
            data_timestamp=data_timestamp,
            timeframe=timeframe,
            sections=sections,
            final_score=final_score,
            bias=bias,
            action=action,
            confidence_score=confidence_score,
            confidence=confidence_level,
            summary=summary,
            regime=regime,
            dominant_signals=dominant_signals,
            invalidation_conditions=invalidation_conditions,
            score_breakdown=score_breakdown,
            signal_agreement_pct=round(signal_agreement_pct, 1),
            data_freshness_score=round(data_freshness_score, 1),
            audit_log=audit_log
        )
    
    def _determine_bias_with_discipline(
        self,
        final_score: int,
        sections: List[SectionScore]
    ) -> Tuple[BiasType, ActionType]:
        """
        Determine bias with output discipline - prevent overconfidence when signals conflict
        """
        # Check for signal conflict (mixed signals)
        scores = [s.score for s in sections]
        score_range = max(scores) - min(scores)
        is_mixed = score_range > 40  # High variance = mixed signals
        
        # Determine base bias
        if final_score >= 80:
            if is_mixed:
                bias = BiasType.BULLISH  # Downgrade from Strong Bull if mixed
            else:
                bias = BiasType.STRONG_BULL
            action = ActionType.ACCUMULATE_AGGRESSIVELY
        elif final_score >= 65:
            if is_mixed:
                bias = BiasType.CAUTIOUSLY_BULLISH
            else:
                bias = BiasType.BULLISH
            action = ActionType.HOLD_ADD_DIPS
        elif final_score >= 55:
            # Neutral range - check for bias
            bullish_count = sum(1 for s in sections if s.score > 60)
            bearish_count = sum(1 for s in sections if s.score < 40)
            
            if bullish_count > bearish_count:
                bias = BiasType.NEUTRAL_UPSIDE_BIAS
            elif bearish_count > bullish_count:
                bias = BiasType.NEUTRAL_DOWNSIDE_BIAS
            else:
                bias = BiasType.NEUTRAL
            action = ActionType.SMALL_POSITIONS
        elif final_score >= 40:
            if is_mixed:
                bias = BiasType.NEUTRAL_DOWNSIDE_BIAS
            else:
                bias = BiasType.BEARISH
            action = ActionType.CAPITAL_PROTECTION
        elif final_score >= 20:
            bias = BiasType.BEARISH
            action = ActionType.CAPITAL_PROTECTION
        else:
            bias = BiasType.HIGH_RISK
            action = ActionType.STAY_OUT
        
        return bias, action
    
    def _identify_dominant_signals(
        self,
        sections: List[SectionScore],
        weights: Dict[str, float]
    ) -> List[str]:
        """Identify top 2-3 signals driving the verdict"""
        # Sort by (score * weight) to find most impactful
        section_impact = [
            (s.name, s.score * weights.get(s.name, 0.0))
            for s in sections
        ]
        section_impact.sort(key=lambda x: x[1], reverse=True)
        
        dominant = []
        for name, impact in section_impact[:3]:
            section = next((s for s in sections if s.name == name), None)
            if section and section.signals:
                # Get top validated signal if available
                if section.validated_signals:
                    top_signal = max(
                        section.validated_signals,
                        key=lambda s: s.score_contribution
                    )
                    dominant.append(f"{name}: {top_signal.name}")
                else:
                    dominant.append(f"{name}: {section.signals[0]}")
        
        return dominant[:3]
    
    def _generate_invalidation_conditions(
        self,
        sections: List[SectionScore],
        dominant_signals: List[str],
        regime: RegimeType
    ) -> List[str]:
        """
        Generate conditions that would invalidate/flip this verdict
        """
        conditions = []
        
        # Get top 2-3 sections by impact
        top_sections = sorted(sections, key=lambda s: s.score, reverse=True)[:3]
        
        for section in top_sections:
            current_score = section.score
            
            # Generate flip condition
            if current_score > 60:
                # Currently bullish - what would flip it?
                conditions.append(
                    f"If {section.name} score drops below 40 "
                    f"(currently {current_score})"
                )
            elif current_score < 40:
                # Currently bearish - what would flip it?
                conditions.append(
                    f"If {section.name} score rises above 60 "
                    f"(currently {current_score})"
                )
        
        # Regime-specific conditions
        if regime == RegimeType.TIGHTENING:
            conditions.append("If Fed signals shift from hawkish to dovish")
            conditions.append("If liquidity conditions start expanding (balance sheet growth)")
        elif regime == RegimeType.EASING:
            conditions.append("If Fed signals shift from dovish to hawkish")
            conditions.append("If DXY strengthens significantly (>5% in 7 days)")
        
        return conditions[:3]  # Limit to top 3
    
    def _get_most_recent_timestamp(self, sections: List[SectionScore]) -> datetime:
        """Get the most recent data timestamp across all sections"""
        timestamps = []
        
        for section in sections:
            for source in section.data_sources:
                timestamps.append(source.data_as_of)
        
        if timestamps:
            return max(timestamps)
        
        return datetime.now()
    
    def _generate_summary_with_discipline(
        self,
        sections: List[SectionScore],
        score: int,
        bias: BiasType,
        confidence: Any,
        regime: RegimeType
    ) -> str:
        """Generate summary with output discipline - no overconfident language"""
        # Get top contributing sections
        top_sections = sorted(sections, key=lambda s: s.score, reverse=True)[:2]
        
        factors = []
        for section in top_sections:
            if section.validated_signals:
                top_signal = max(
                    section.validated_signals,
                    key=lambda s: s.score_contribution
                )
                if top_signal.validation_status.value == "validated":
                    factors.append(f"{section.name}: {top_signal.name}")
        
        factors_str = "; ".join(factors) if factors else "Mixed signals across sections"
        
        # Confidence-aware language
        if confidence.value in ["Very Low", "Low"]:
            confidence_lang = "with low confidence"
        elif confidence.value in ["Very High", "High"]:
            confidence_lang = "with high confidence"
        else:
            confidence_lang = "with moderate confidence"
        
        # Regime context
        regime_context = f"Current regime: {regime.value}. "
        
        # Summary
        summary = (
            f"Macro Score: {score}/100 = {bias.value} {confidence_lang}. "
            f"{regime_context}"
            f"Key factors: {factors_str}. "
        )
        
        # Add caution if mixed signals
        scores = [s.score for s in sections]
        if max(scores) - min(scores) > 40:
            summary += "Note: Mixed signals detected - exercise caution."
        
        return summary
