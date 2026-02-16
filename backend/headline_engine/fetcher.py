"""
Headline ingestion and filtering pipeline.

Fetches macro headlines from NewsAPI / Google News RSS.
Filters by relevant keywords.
Returns only headlines from last 24-48 hours.
"""
import os
import re
import requests
import xml.etree.ElementTree as ET
import logging
from typing import List, Dict, Optional, Tuple
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

# Patterns for explicit decision detection (high-confidence signals)
DECISION_PATTERNS = [
    (re.compile(r"\brate (?:hike|increase|raised)\b|\braises rates?\b|\badds bps\b", re.I), "rate_hike"),
    (re.compile(r"\brate (?:cut|cutting|cut by)\b|\breduces rates?\b|\bcut bps\b", re.I), "rate_cut"),
    (re.compile(r"\bhold rates?\b|\bmaintains rate\b|\bno change to rates\b", re.I), "rate_hold"),
    (re.compile(r"\bdebt ceiling\b|\bdebt-limit\b|\braising the debt ceiling\b|\bdebt deal\b", re.I), "debt_ceiling"),
    (re.compile(r"\bjobs report\b|\bnonfarm payrolls\b|\bNFP\b|\bunemployment rate\b|\bpayrolls (?:beat|miss)\b", re.I), "jobs_print"),
    (re.compile(r"\bGovernment Shutdown\b|\bshutdown averts\b", re.I), "gov_shutdown"),
    (re.compile(r"\bFOMC statement\b|\bFOMC minutes?\b|\bpress release\b", re.I), "fomc_doc"),
]

# Authoritative news sources to prioritize
HIGH_AUTH_SOURCES = ["Reuters", "Bloomberg", "Associated Press", "AP", "Wall Street Journal", "WSJ", "CNBC", "Federal Reserve", "Fed", "BLS", "BEA"]


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
        
        # Source 0: Official sources (Federal Reserve, BLS) — highest priority
        try:
            from headline_engine.sources import fetch_fomc_releases, fetch_bls_releases
            try:
                fomc = fetch_fomc_releases()
                if fomc:
                    headlines.extend(fomc)
                    logger.info(f"Fetched {len(fomc)} FOMC/Fed releases")
            except Exception as _e:
                logger.warning(f"FOMC fetch failed: {_e}")

            try:
                bls = fetch_bls_releases()
                if bls:
                    headlines.extend(bls)
                    logger.info(f"Fetched {len(bls)} BLS releases")
            except Exception as _e:
                logger.warning(f"BLS fetch failed: {_e}")
        except Exception:
            logger.debug("Official-source scrapers unavailable")

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

        # Annotate headlines with explicit decision detection and authority score
        annotated = []
        for h in filtered:
            title = h.get("title", "")
            desc = h.get("description", "") or ""
            explicit, decision_type = self._is_explicit_decision(title, desc)
            h["_explicit_decision"] = explicit
            h["_decision_type"] = decision_type

            # Authority heuristic
            source = h.get("source", "") or ""
            auth_score = 2 if any(src.lower() in source.lower() for src in HIGH_AUTH_SOURCES) else 0
            h["_authority_score"] = auth_score
            h["_priority"] = "high" if explicit or auth_score >= 2 else "normal"

            # Log explicit decisions for auditing
            if explicit:
                logger.info(f"Explicit decision detected: type={decision_type} title={title[:120]}")

            annotated.append(h)

        return annotated
    
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

    def _is_explicit_decision(self, title: str, description: str) -> Tuple[bool, Optional[str]]:
        """Detect high-confidence explicit decisions or official documents in headline text.

        Returns: (True/False, decision_type or None)
        """
        text = (title + " " + (description or "")).lower()
        for pattern, dtype in DECISION_PATTERNS:
            if pattern.search(text):
                return True, dtype
        return False, None


class HeadlineFetchError(Exception):
    """Raised when all headline fetch sources fail."""
    pass
