"""
Pydantic models for API responses and data structures
"""
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum


class BiasType(str, Enum):
    """BTC bias classification"""
    STRONG_BULL = "Strong Bull"
    BULLISH = "Bullish"
    NEUTRAL = "Neutral"
    BEARISH = "Bearish"
    HIGH_RISK = "High Risk"


class ActionType(str, Enum):
    """Recommended action"""
    ACCUMULATE_AGGRESSIVELY = "Accumulate BTC aggressively"
    HOLD_ADD_DIPS = "Hold + add on dips"
    SMALL_POSITIONS = "Small positions only"
    CAPITAL_PROTECTION = "Capital protection"
    STAY_OUT = "Stay out / hedge"


class SectionScore(BaseModel):
    """Score for a single checklist section"""
    name: str = Field(..., description="Section name")
    score: int = Field(..., ge=0, le=100, description="Score from 0-100")
    signals: List[str] = Field(default_factory=list, description="Key signals detected")
    reasoning: str = Field(..., description="Explanation of the score")
    data_used: Optional[Dict[str, Any]] = Field(default=None, description="Raw data used in analysis")


class VerdictResponse(BaseModel):
    """Final verdict and aggregated analysis"""
    timestamp: datetime = Field(default_factory=datetime.now)
    sections: List[SectionScore] = Field(..., description="All 7 section scores")
    final_score: int = Field(..., ge=0, le=100, description="Weighted final score 0-100")
    bias: BiasType = Field(..., description="BTC bias classification")
    action: ActionType = Field(..., description="Recommended action")
    confidence: str = Field(..., description="Confidence level (Low/Medium/High)")
    summary: str = Field(..., description="Overall summary of analysis")


class AnalysisRequest(BaseModel):
    """Request to run analysis"""
    sections: Optional[List[str]] = Field(
        default=None,
        description="Specific sections to analyze. If None, analyzes all 7 sections"
    )


class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    timestamp: datetime = Field(default_factory=datetime.now)
    services: Dict[str, str] = Field(default_factory=dict)

