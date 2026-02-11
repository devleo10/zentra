"""
Market regime detection - determines current market regime for adaptive weighting
"""
from typing import Dict, Any, List
from datetime import datetime
from models.schemas import RegimeType, SectionScore


class RegimeDetector:
    """Detects market regime to adjust scoring weights"""
    
    @staticmethod
    def detect_regime(sections: List[SectionScore], data: Dict[str, Any]) -> RegimeType:
        """
        Detect current market regime based on section scores and data
        
        Args:
            sections: List of section scores
            data: Raw data dictionary with fed, liquidity, risk signals
        
        Returns:
            Detected regime type
        """
        # Extract key signals
        fed_score = next((s.score for s in sections if "Federal Reserve" in s.name), 50)
        liquidity_score = next((s.score for s in sections if "Liquidity" in s.name), 50)
        risk_score = next((s.score for s in sections if "Risk" in s.name), 50)
        inflation_score = next((s.score for s in sections if "Inflation" in s.name), 50)
        
        # Get yield curve data
        yield_curve = data.get("liquidity", {}).get("yields", {}).get("yield_curve_spread", 0)
        fed_balance_sheet_trend = data.get("liquidity", {}).get("balance_sheet", {}).get("trend", "stable")
        
        # Regime detection logic
        # 1. Tightening: Fed score low (<40), liquidity contracting, yields rising
        if fed_score < 40 and fed_balance_sheet_trend == "contracting":
            return RegimeType.TIGHTENING
        
        # 2. Easing: Fed score high (>60), liquidity expanding, yields falling
        if fed_score > 60 and fed_balance_sheet_trend == "expanding":
            return RegimeType.EASING
        
        # 3. Late Cycle: Risk score very high (>80), inflation high, but growth concerns
        if risk_score > 80 and inflation_score > 60:
            return RegimeType.LATE_CYCLE
        
        # 4. Recession: All scores low (<40), yield curve inverted
        if all(s.score < 40 for s in sections) and yield_curve < 0:
            return RegimeType.RECESSION
        
        # 5. Early Cycle: Recovery from low scores, liquidity improving
        if liquidity_score > 60 and any(s.score < 40 for s in sections):
            return RegimeType.EARLY_CYCLE
        
        return RegimeType.UNKNOWN
    
    @staticmethod
    def get_regime_weights(regime: RegimeType) -> Dict[str, float]:
        """
        Get adaptive weights based on regime
        
        Returns:
            Dictionary of section name -> weight
        """
        base_weights = {
            "Inflation & Economy": 0.20,
            "Federal Reserve Signals": 0.25,
            "Liquidity & Bonds": 0.20,
            "US Dollar (DXY)": 0.20,
            "Risk Sentiment": 0.15,
            "Bitcoin Focus": 0.20  # Always included
        }
        
        if regime == RegimeType.TIGHTENING:
            # During tightening, Fed and Liquidity dominate
            return {
                "Inflation & Economy": 0.15,
                "Federal Reserve Signals": 0.30,
                "Liquidity & Bonds": 0.30,
                "US Dollar (DXY)": 0.15,
                "Risk Sentiment": 0.10,
                "Bitcoin Focus": 0.20
            }
        elif regime == RegimeType.EASING:
            # During easing, Liquidity and DXY dominate
            return {
                "Inflation & Economy": 0.15,
                "Federal Reserve Signals": 0.20,
                "Liquidity & Bonds": 0.30,
                "US Dollar (DXY)": 0.25,
                "Risk Sentiment": 0.10,
                "Bitcoin Focus": 0.20
            }
        elif regime == RegimeType.LATE_CYCLE:
            # Late cycle, risk sentiment dominates
            return {
                "Inflation & Economy": 0.20,
                "Federal Reserve Signals": 0.20,
                "Liquidity & Bonds": 0.15,
                "US Dollar (DXY)": 0.15,
                "Risk Sentiment": 0.30,
                "Bitcoin Focus": 0.20
            }
        elif regime == RegimeType.RECESSION:
            # Recession, Fed and Liquidity matter most
            return {
                "Inflation & Economy": 0.20,
                "Federal Reserve Signals": 0.30,
                "Liquidity & Bonds": 0.30,
                "US Dollar (DXY)": 0.10,
                "Risk Sentiment": 0.10,
                "Bitcoin Focus": 0.20
            }
        else:
            # Default/base weights
            return base_weights

