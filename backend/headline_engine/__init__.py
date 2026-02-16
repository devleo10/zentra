"""
Headline engine package.
Fetches, filters, and classifies macro headlines.
LLM is used ONLY for classification — not for scoring.
"""
from .fetcher import HeadlineFetcher, HeadlineFetchError
from .classifier import HeadlineClassifier

__all__ = [
    "HeadlineFetcher",
    "HeadlineFetchError",
    "HeadlineClassifier",
]
