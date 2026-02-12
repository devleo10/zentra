"""
Scoring engine package.
Deterministic, threshold-based scoring with zero LLM involvement.
"""
from .numeric_scorer import (
    score_inflation,
    score_fed_policy,
    score_liquidity,
    score_dxy,
    score_risk_sentiment,
    compute_weighted_total,
)
from .headline_adjuster import compute_headline_adjustment
from .verdict import compute_final_verdict

__all__ = [
    "score_inflation",
    "score_fed_policy",
    "score_liquidity",
    "score_dxy",
    "score_risk_sentiment",
    "compute_weighted_total",
    "compute_headline_adjustment",
    "compute_final_verdict",
]
