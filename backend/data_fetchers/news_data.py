"""
Fetch Fed speeches and macro news from NewsAPI with free-tier fallback
"""
import os
import requests
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

NEWS_API_KEY = os.getenv("NEWS_API_KEY")
NEWS_API_URL = "https://newsapi.org/v2/everything"

# NewsAPI free tier only allows ~30 days lookback
NEWSAPI_MAX_DAYS = 29


def _fetch_google_news_rss(query: str, num: int = 10) -> List[Dict]:
    """
    Fallback: fetch news from Google News RSS (no API key needed, no date limits)
    """
    try:
        from urllib.parse import quote
        rss_url = f"https://news.google.com/rss/search?q={quote(query)}&hl=en-US&gl=US&ceid=US:en"
        response = requests.get(rss_url, timeout=10)
        response.raise_for_status()

        root = ET.fromstring(response.content)
        articles = []
        for item in root.findall(".//item")[:num]:
            title = item.findtext("title", "")
            desc = item.findtext("description", "")
            pub_date = item.findtext("pubDate", "")
            source = item.findtext("source", "")
            link = item.findtext("link", "")
            articles.append({
                "title": title,
                "description": desc,
                "published_at": pub_date,
                "source": source,
                "url": link
            })
        return articles
    except Exception as e:
        print(f"Google News RSS fallback also failed: {e}")
        return []


def get_fed_speeches(days: int = 7) -> List[Dict]:
    """
    Get recent Federal Reserve speeches and statements.
    Uses NewsAPI for short lookbacks, falls back to Google News RSS
    when NewsAPI's free-tier date limit is exceeded.
    
    Args:
        days: Number of days to look back
        
    Returns:
        List of news articles about Fed
    """
    query = "Federal Reserve OR Fed OR Jerome Powell OR FOMC"

    # Try NewsAPI first (only if within free-tier date limit)
    if NEWS_API_KEY and days <= NEWSAPI_MAX_DAYS:
        articles = _fetch_newsapi(query, days)
        if articles:
            return articles

    # Fallback: Google News RSS (free, no date limits)
    print(f"Using Google News RSS fallback for Fed speeches (days={days})...")
    return _fetch_google_news_rss(query, num=10)


def _fetch_newsapi(query: str, days: int) -> List[Dict]:
    """Fetch from NewsAPI (free tier: max ~30 days lookback)"""
    # Clamp to free-tier limit
    effective_days = min(days, NEWSAPI_MAX_DAYS)
    from_date = (datetime.now() - timedelta(days=effective_days)).strftime("%Y-%m-%d")

    params = {
        "q": query,
        "from": from_date,
        "sortBy": "publishedAt",
        "language": "en",
        "pageSize": 10,
        "apiKey": NEWS_API_KEY
    }

    try:
        response = requests.get(NEWS_API_URL, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        articles = data.get("articles", [])
        return [
            {
                "title": article.get("title", ""),
                "description": article.get("description", ""),
                "published_at": article.get("publishedAt", ""),
                "source": article.get("source", {}).get("name", ""),
                "url": article.get("url", "")
            }
            for article in articles
        ]
    except Exception as e:
        print(f"NewsAPI error: {e}")
        return []


def analyze_fed_keywords(articles: List[Dict]) -> Dict:
    """
    Analyze Fed speeches for dovish/hawkish keywords
    
    Returns:
        Dict with keyword counts and tone assessment
    """
    dovish_keywords = [
        "data dependent", "disinflation", "policy is restrictive",
        "balanced risks", "financial conditions tightening", "tools are available"
    ]
    
    hawkish_keywords = [
        "higher for longer", "inflation sticky", "labor market strong",
        "premature easing", "upside risks"
    ]
    
    pivot_keywords = [
        "at or near terminal rate", "lagged effects",
        "monitoring credit conditions", "financial stability"
    ]
    
    text_content = " ".join([
        article.get("title", "") + " " + article.get("description", "")
        for article in articles
    ]).lower()
    
    dovish_count = sum(1 for keyword in dovish_keywords if keyword in text_content)
    hawkish_count = sum(1 for keyword in hawkish_keywords if keyword in text_content)
    pivot_count = sum(1 for keyword in pivot_keywords if keyword in text_content)
    
    # Determine tone
    if pivot_count >= 2 or dovish_count >= 2:
        tone = "dovish"
    elif hawkish_count >= 2:
        tone = "hawkish"
    else:
        tone = "neutral"
    
    return {
        "dovish_keywords_found": dovish_count,
        "hawkish_keywords_found": hawkish_count,
        "pivot_keywords_found": pivot_count,
        "tone": tone,
        "articles_analyzed": len(articles)
    }


def get_macro_news(days: int = 7) -> List[Dict]:
    """
    Get recent macroeconomic news.
    Uses NewsAPI for short lookbacks, falls back to Google News RSS.
    
    Args:
        days: Number of days to look back
        
    Returns:
        List of macro news articles
    """
    query = "inflation OR CPI OR GDP OR unemployment OR Fed rate"

    # Try NewsAPI first (only if within free-tier limit)
    if NEWS_API_KEY and days <= NEWSAPI_MAX_DAYS:
        articles = _fetch_newsapi(query, days)
        if articles:
            return articles

    # Fallback: Google News RSS
    print(f"Using Google News RSS fallback for macro news (days={days})...")
    return _fetch_google_news_rss(query, num=10)


