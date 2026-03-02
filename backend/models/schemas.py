"""
Pydantic models for API responses and data structures
Production-grade schemas with validation, timestamps, and data freshness tracking
"""
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum


class TimeFrame(str, Enum):
    """Timeframe for analysis"""
    CURRENT = "current"  # Real-time / latest data point
    WEEK = "week"  # 7-day analysis
    MONTH = "month"  # 30-day analysis
    YEAR = "year"  # 365-day analysis


class BiasType(str, Enum):
    """BTC bias classification"""
    STRONG_BULL = "Strong Bull"
    BULLISH = "Bullish"
    CAUTIOUSLY_BULLISH = "Cautiously Bullish"
    NEUTRAL = "Neutral"
    NEUTRAL_UPSIDE_BIAS = "Neutral with Upside Bias"
    NEUTRAL_DOWNSIDE_BIAS = "Neutral with Downside Bias"
    BEARISH = "Bearish"
    HIGH_RISK = "High Risk"


class ActionType(str, Enum):
    """Recommended action"""
    ACCUMULATE_AGGRESSIVELY = "Accumulate BTC aggressively"
    HOLD_ADD_DIPS = "Hold + add on dips"
    SMALL_POSITIONS = "Small positions only"
    CAPITAL_PROTECTION = "Capital protection"
    STAY_OUT = "Stay out / hedge"


class SignalValidationStatus(str, Enum):
    """Signal validation status"""
    VALIDATED = "validated"      # Boolean check passed — signal contributes to score
    NEUTRALIZED = "neutralized"  # Boolean check failed — signal contribution zeroed, thesis not fully invalidated
    INVALIDATED = "invalidated"  # Hard condition failed — entire bullish/bearish thesis invalidated
    STALE_DATA = "stale_data"    # Data too old
    MISSING_DATA = "missing_data"  # Data unavailable
    PENDING = "pending"          # Not yet validated


class DataSource(BaseModel):
    """Data source metadata"""
    name: str = Field(..., description="Source name (FRED, BLS, ISM, Treasury, CBOE, CoinGecko, etc.)")
    series_id: Optional[str] = Field(None, description="Series ID if applicable")
    url: Optional[str] = Field(None, description="Source URL")
    last_updated: datetime = Field(..., description="When this data was last updated")
    data_as_of: datetime = Field(..., description="Data timestamp (when the data point is from)")
    freshness_hours: float = Field(..., description="Hours since data_as_of")


class ValidatedSignal(BaseModel):
    """A signal with validation metadata"""
    name: str = Field(..., description="Signal name (e.g., 'CPI MoM falling')")
    value: Any = Field(..., description="Current value")
    previous_value: Optional[Any] = Field(None, description="Previous value for comparison")
    trend_direction: Optional[str] = Field(None, description="up/down/flat")
    validation_status: SignalValidationStatus = Field(..., description="Validation status")
    validation_check: Optional[str] = Field(None, description="What was checked (e.g., 'btc_price > btc_200dma')")
    validation_result: Optional[bool] = Field(None, description="Boolean result of validation")
    score_contribution: float = Field(..., description="How much this signal contributes to score (0-100)")
    data_source: DataSource = Field(..., description="Where this data came from")
    notes: Optional[str] = Field(None, description="Additional notes if validation failed")


class SectionScore(BaseModel):
    """Score for a single checklist section with full validation"""
    name: str = Field(..., description="Section name")
    score: int = Field(..., ge=0, le=100, description="Score from 0-100")
    signals: List[str] = Field(default_factory=list, description="Key signals detected (human-readable)")
    validated_signals: List[ValidatedSignal] = Field(default_factory=list, description="Validated signals with metadata")
    reasoning: str = Field(..., description="Explanation of the score")
    data_used: Dict[str, Any] = Field(default_factory=dict, description="Raw data used in analysis")
    data_sources: List[DataSource] = Field(default_factory=list, description="All data sources used")
    timestamp: datetime = Field(default_factory=datetime.now, description="When this analysis was run")
    validation_summary: Dict[str, Any] = Field(default_factory=dict, description="Summary of validations performed")


class RegimeType(str, Enum):
    """Market regime classification"""
    TIGHTENING = "Tightening"  # Fed tightening, liquidity draining
    EASING = "Easing"  # Fed easing, liquidity expanding
    LATE_CYCLE = "Late Cycle"  # Late expansion, high risk sentiment
    EARLY_CYCLE = "Early Cycle"  # Recovery phase
    RECESSION = "Recession"  # Economic contraction
    UNKNOWN = "Unknown"  # Cannot determine


class ConfidenceLevel(str, Enum):
    """Confidence level labels"""
    VERY_LOW = "Very Low"
    LOW = "Low"
    MEDIUM = "Medium"
    MEDIUM_HIGH = "Medium-High"
    HIGH = "High"
    VERY_HIGH = "Very High"


class VerdictResponse(BaseModel):
    """Final verdict and aggregated analysis with full audit trail"""
    timestamp: datetime = Field(default_factory=datetime.now, description="Report generation timestamp")
    data_timestamp: datetime = Field(..., description="Most recent data timestamp across all sources")
    timeframe: TimeFrame = Field(default=TimeFrame.CURRENT, description="Timeframe of the analysis")
    sections: List[SectionScore] = Field(..., description="All 6 section scores")
    final_score: int = Field(..., ge=0, le=100, description="Weighted final score 0-100")
    bias: BiasType = Field(..., description="BTC bias classification")
    action: ActionType = Field(..., description="Recommended action")
    confidence_score: float = Field(..., ge=0, le=100, description="Computed confidence score 0-100")
    confidence: ConfidenceLevel = Field(..., description="Confidence level label")
    summary: str = Field(..., description="Overall summary of analysis")
    regime: RegimeType = Field(..., description="Detected market regime")
    dominant_signals: List[str] = Field(default_factory=list, description="Top 2-3 signals driving the verdict")
    invalidation_conditions: List[str] = Field(default_factory=list, description="What would flip this verdict")
    score_breakdown: Dict[str, float] = Field(default_factory=dict, description="Weighted contribution of each section")
    signal_agreement_pct: float = Field(..., ge=0, le=100, description="% of signals aligned (for confidence)")
    data_freshness_score: float = Field(..., ge=0, le=100, description="Overall data freshness score")
    audit_log: Dict[str, Any] = Field(default_factory=dict, description="Full audit trail of calculations")


class AnalysisRequest(BaseModel):
    """Request to run analysis"""
    sections: Optional[List[str]] = Field(
        default=None,
        description="Specific sections to analyze. If None, analyzes all 6 sections"
    )
    timeframe: TimeFrame = Field(
        default=TimeFrame.CURRENT,
        description="Timeframe for analysis: current (real-time), week (7d), month (30d), year (365d)"
    )


class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    timestamp: datetime = Field(default_factory=datetime.now)
    services: Dict[str, str] = Field(default_factory=dict)
