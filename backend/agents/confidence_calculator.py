"""
Confidence calculation - computes confidence score based on signal agreement, volatility, data freshness
"""
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from models.schemas import SectionScore, ValidatedSignal, ConfidenceLevel, DataSource


class ConfidenceCalculator:
    """Calculates confidence score dynamically"""
    
    @staticmethod
    def calculate_confidence(
        sections: List[SectionScore],
        vix_value: Optional[float] = None,
        btc_volatility: Optional[float] = None
    ) -> Tuple[float, ConfidenceLevel]:
        """
        Calculate confidence score (0-100) and level
        
        Args:
            sections: List of section scores
            vix_value: Current VIX level
            btc_volatility: BTC realized volatility (optional)
        
        Returns:
            (confidence_score, confidence_level)
        """
        # 1. Signal Agreement (0-40 points)
        signal_agreement = ConfidenceCalculator._calculate_signal_agreement(sections)
        agreement_score = signal_agreement * 0.4  # 40% weight
        
        # 2. Data Freshness (0-30 points)
        freshness_score = ConfidenceCalculator._calculate_freshness_score(sections) * 0.3  # 30% weight
        
        # 3. Volatility Penalty (0-30 points)
        volatility_score = ConfidenceCalculator._calculate_volatility_score(vix_value, btc_volatility) * 0.3  # 30% weight
        
        # Total confidence score
        total_confidence = agreement_score + freshness_score + volatility_score
        
        # Map to confidence level
        if total_confidence >= 85:
            level = ConfidenceLevel.VERY_HIGH
        elif total_confidence >= 70:
            level = ConfidenceLevel.HIGH
        elif total_confidence >= 55:
            level = ConfidenceLevel.MEDIUM_HIGH
        elif total_confidence >= 40:
            level = ConfidenceLevel.MEDIUM
        elif total_confidence >= 25:
            level = ConfidenceLevel.LOW
        else:
            level = ConfidenceLevel.VERY_LOW
        
        return round(total_confidence, 1), level
    
    @staticmethod
    def _calculate_signal_agreement(sections: List[SectionScore]) -> float:
        """
        Calculate % of signals that agree (all bullish or all bearish)
        
        Returns:
            Percentage 0-100
        """
        if not sections:
            return 50.0  # Neutral if no data
        
        # Count bullish (score > 60) vs bearish (score < 40)
        bullish_count = sum(1 for s in sections if s.score > 60)
        bearish_count = sum(1 for s in sections if s.score < 40)
        neutral_count = sum(1 for s in sections if 40 <= s.score <= 60)
        
        total = len(sections)
        if total == 0:
            return 50.0
        
        # Agreement = max(bullish, bearish) / total
        # Higher agreement = more confidence
        max_aligned = max(bullish_count, bearish_count)
        agreement_pct = (max_aligned / total) * 100
        
        # Boost if very clear direction (>80% agreement)
        if agreement_pct >= 80:
            agreement_pct = min(100, agreement_pct * 1.1)
        
        return agreement_pct
    
    @staticmethod
    def _calculate_freshness_score(sections: List[SectionScore]) -> float:
        """
        Calculate data freshness score based on all data sources
        
        Returns:
            Score 0-100 (100 = all fresh, 0 = all stale)
        """
        if not sections:
            return 50.0
        
        all_sources: List[DataSource] = []
        for section in sections:
            all_sources.extend(section.data_sources)
        
        if not all_sources:
            return 50.0  # No data sources = neutral
        
        # Calculate average freshness
        # Fresh = <24h (100 points), <7d (80 points), <30d (60 points), >30d (40 points), >90d (20 points)
        freshness_scores = []
        for source in all_sources:
            hours_old = source.freshness_hours
            if hours_old < 24:
                score = 100
            elif hours_old < 168:  # 7 days
                score = 80
            elif hours_old < 720:  # 30 days
                score = 60
            elif hours_old < 2160:  # 90 days
                score = 40
            else:
                score = 20
            
            freshness_scores.append(score)
        
        return sum(freshness_scores) / len(freshness_scores) if freshness_scores else 50.0
    
    @staticmethod
    def _calculate_volatility_score(vix_value: Optional[float], btc_volatility: Optional[float]) -> float:
        """
        Calculate volatility-based confidence penalty
        
        Lower volatility = higher confidence
        
        Returns:
            Score 0-100
        """
        scores = []
        
        # VIX component (0-50 points)
        if vix_value is not None:
            if vix_value < 15:
                vix_score = 50  # Low VIX = high confidence
            elif vix_value < 20:
                vix_score = 40
            elif vix_value < 25:
                vix_score = 30
            elif vix_value < 30:
                vix_score = 20
            else:
                vix_score = 10  # High VIX = low confidence
            scores.append(vix_score)
        
        # BTC volatility component (0-50 points)
        if btc_volatility is not None:
            # Assuming volatility is annualized % (e.g., 60% = 0.60)
            if btc_volatility < 0.30:  # <30% annualized
                btc_score = 50
            elif btc_volatility < 0.50:  # <50%
                btc_score = 40
            elif btc_volatility < 0.70:  # <70%
                btc_score = 30
            elif btc_volatility < 1.0:  # <100%
                btc_score = 20
            else:
                btc_score = 10  # >100% = very volatile
            scores.append(btc_score)
        
        if not scores:
            return 50.0  # Neutral if no volatility data
        
        return sum(scores) / len(scores)
    
    @staticmethod
    def get_signal_agreement_pct(sections: List[SectionScore]) -> float:
        """Get signal agreement percentage for reporting"""
        return ConfidenceCalculator._calculate_signal_agreement(sections)
    
    @staticmethod
    def get_data_freshness_score(sections: List[SectionScore]) -> float:
        """Get data freshness score for reporting"""
        return ConfidenceCalculator._calculate_freshness_score(sections)

