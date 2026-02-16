"""
Headline ingestion and filtering pipeline.

Fetches macro headlines from NewsAPI / Google News RSS.
Filters by relevant keywords.
Returns only headlines from last 24-48 hours.
"""
import os
import requests
import xml.etree.ElementTree as ET
import logging
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from urllib.parse import quote
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("btc_macro.headline_engine")

NEWS_API_KEY = os.getenv("NEWS_API_KEY")
NEWS_API_URL = "https://newsapi.org/v2/everything"

# Keywords that identify macro-relevant headlines
MACRO_KEYWORDS = [
    "Federal Reserve", "FOMC", "Interest Rate", "Rate Cut", "Rate Hike",
    "Inflation", "CPI", "PCE", "PPI",
    "Treasury", "Yield", "Bond",
    "Debt Ceiling", "Government Shutdown",
    "Jobs Report", "Nonfarm Payrolls", "Unemployment",
    "GDP", "Recession",
    "Quantitative Easing", "Quantitative Tightening", "QE", "QT",
    "Jerome Powell", "Fed Chair", "FOMC Minutes",
    "Bank Failure", "Credit Crisis", "Liquidity Crisis",
    "Tariff", "Trade War", "Sanctions",
]


class HeadlineFetcher:
    """Fetches and filters macro headlines."""
    
    def __init__(self, lookback_hours: int = 48):
        self.lookback_hours = lookback_hours
        self.api_key = NEWS_API_KEY
    
    def fetch_headlines(self) -> List[Dict]:
        """
        Fetch headlines from available sources, filtered by macro keywords.
        
        Returns:
            List of dicts with: title, description, published_at, source, url
        
        Raises:
            HeadlineFetchError if ALL sources fail.
        """
        headlines = []
        errors = []
        
        # Source 1: NewsAPI
        if self.api_key:
            try:
                newsapi_results = self._fetch_newsapi()
                headlines.extend(newsapi_results)
                logger.info(f"NewsAPI returned {len(newsapi_results)} headlines")
            except Exception as e:
                errors.append(f"NewsAPI: {e}")
                logger.warning(f"NewsAPI failed: {e}")
        
        # Source 2: Google News RSS (always try as fallback or supplement)
        try:
            rss_results = self._fetch_google_news_rss()
            headlines.extend(rss_results)
            logger.info(f"Google News RSS returned {len(rss_results)} headlines")
        except Exception as e:
            errors.append(f"Google News RSS: {e}")
            logger.warning(f"Google News RSS failed: {e}")
        
        if not headlines and errors:
            raise HeadlineFetchError(
                f"All headline sources failed: {'; '.join(errors)}"
            )
        
        # Deduplicate by title
        seen_titles = set()
        unique = []
        for h in headlines:
            title_key = h["title"].strip().lower()[:80]
            if title_key not in seen_titles:
                seen_titles.add(title_key)
                unique.append(h)
        
        # Filter by macro keywords
        filtered = self._filter_by_keywords(unique)
        logger.info(f"After keyword filter: {len(filtered)} of {len(unique)} headlines")
        
        return filtered
    
    def _fetch_newsapi(self) -> List[Dict]:
        """Fetch from NewsAPI (free tier: max 29 days lookback)."""
        lookback_days = min(self.lookback_hours // 24 + 1, 29)
        from_date = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        
        # Build a broad macro query
        query = (
            '"Federal Reserve" OR FOMC OR "interest rate" OR '
            'inflation OR CPI OR "Treasury yield" OR '
            '"jobs report" OR "nonfarm payrolls" OR recession OR '
            '"Jerome Powell" OR "debt ceiling"'
        )
        
        params = {
            "q": query,
            "from": from_date,
            "sortBy": "publishedAt",
            "language": "en",
            "pageSize": 20,
            "apiKey": self.api_key,
        }
        
        response = requests.get(NEWS_API_URL, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        articles = data.get("articles", [])
        return [
            {
                "title": a.get("title", ""),
                "description": a.get("description", "") or "",
                "published_at": a.get("publishedAt", ""),
                "source": a.get("source", {}).get("name", ""),
                "url": a.get("url", ""),
            }
            for a in articles
            if a.get("title")
        ]
    
    def _fetch_google_news_rss(self) -> List[Dict]:
        """Fetch from Google News RSS (free, no API key needed)."""
        query = "Federal Reserve OR FOMC OR inflation OR CPI OR Treasury OR interest rate"
        rss_url = f"https://news.google.com/rss/search?q={quote(query)}&hl=en-US&gl=US&ceid=US:en"
        
        response = requests.get(rss_url, timeout=15)
        response.raise_for_status()
        
        root = ET.fromstring(response.content)
        articles = []
        for item in root.findall(".//item")[:20]:
            articles.append({
                "title": item.findtext("title", ""),
                "description": item.findtext("description", "") or "",
                "published_at": item.findtext("pubDate", ""),
                "source": item.findtext("source", ""),
                "url": item.findtext("link", ""),
            })
        return articles
    
    def _filter_by_keywords(self, headlines: List[Dict]) -> List[Dict]:
        """Keep only headlines containing at least one macro keyword."""
        filtered = []
        keywords_lower = [kw.lower() for kw in MACRO_KEYWORDS]
        
        for h in headlines:
            text = (h.get("title", "") + " " + h.get("description", "")).lower()
            if any(kw in text for kw in keywords_lower):
                filtered.append(h)
        
        return filtered


class HeadlineFetchError(Exception):
    """Raised when all headline fetch sources fail."""
    pass
