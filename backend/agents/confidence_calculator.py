"""
Confidence calculation - computes confidence score for the legacy agent pipeline.

Formula aligns with scoring_weights.json confidence_formula:
    confidence = (agreement_pct * 0.40) + (distance_from_50 * 0.35) + (headline_confidence * 0.25)

This matches the deterministic v2 engine in scoring_engine/verdict.py.
"""
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from models.schemas import SectionScore, ValidatedSignal, ConfidenceLevel, DataSource

# Max distance from 50 used to normalise the distance component (same as config)
_MAX_DISTANCE = 50.0


class ConfidenceCalculator:
    """Calculates confidence score using the unified config-driven formula."""

    @staticmethod
    def calculate_confidence(
        sections: List[SectionScore],
        final_score: Optional[float] = None,
        headline_confidence: float = 0.0,
        data_freshness_score: Optional[float] = None,
    ) -> Tuple[float, ConfidenceLevel]:
        """
        Calculate confidence score (0-100) and level.

        Formula:
            confidence = (agreement_pct * 0.40) + (distance_score * 0.35) + (headline_conf_score * 0.25)

        Args:
            sections: List of SectionScore objects from all agents
            final_score: The final weighted score (0-100). Used for distance-from-50 component.
                         If None, falls back to the average of section scores.
            headline_confidence: Average LLM headline classification confidence (0-1 scale).

        Returns:
            (confidence_score 0-100, ConfidenceLevel)
        """
        # 1. Section agreement (40%)
        agreement_pct = ConfidenceCalculator._calculate_signal_agreement(sections)

        # 2. Distance from 50 — higher distance = more conviction (35%)
        score_for_distance = final_score
        if score_for_distance is None and sections:
            score_for_distance = sum(s.score for s in sections) / len(sections)
        distance = abs((score_for_distance or 50.0) - 50.0)
        distance_score = min(100.0, (distance / _MAX_DISTANCE) * 100.0)

        # 3. Headline classification confidence (25%)
        headline_conf_score = min(100.0, headline_confidence * 100.0)

        total_confidence = (
            agreement_pct * 0.40
            + distance_score * 0.35
            + headline_conf_score * 0.25
        )

        # Freshness penalty: stale data reduces confidence even if signals align.
        if data_freshness_score is not None:
            if data_freshness_score < 40:
                total_confidence -= 20
            elif data_freshness_score < 60:
                total_confidence -= 12
            elif data_freshness_score < 75:
                total_confidence -= 6

        total_confidence = round(max(0.0, min(100.0, total_confidence)), 1)

        if total_confidence >= 75:
            level = ConfidenceLevel.HIGH
        elif total_confidence >= 50:
            level = ConfidenceLevel.MEDIUM_HIGH
        elif total_confidence >= 30:
            level = ConfidenceLevel.MEDIUM
        else:
            level = ConfidenceLevel.LOW

        return total_confidence, level

    @staticmethod
    def _calculate_signal_agreement(sections: List[SectionScore]) -> float:
        """
        Percentage of sections that agree on directional bias (0-100).
        Bullish = score > 60, Bearish = score < 40.
        """
        if not sections:
            return 50.0

        bullish_count = sum(1 for s in sections if s.score > 60)
        bearish_count = sum(1 for s in sections if s.score < 40)
        total = len(sections)

        max_aligned = max(bullish_count, bearish_count)
        agreement_pct = (max_aligned / total) * 100.0

        if agreement_pct >= 80:
            agreement_pct = min(100.0, agreement_pct * 1.1)

        return agreement_pct

    @staticmethod
    def get_signal_agreement_pct(sections: List[SectionScore]) -> float:
        """Get signal agreement percentage for reporting."""
        return ConfidenceCalculator._calculate_signal_agreement(sections)

