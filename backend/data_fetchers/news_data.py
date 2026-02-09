"""
Fetch Fed speeches and macro news from NewsAPI
"""
import os
import requests
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

NEWS_API_KEY = os.getenv("NEWS_API_KEY")
NEWS_API_URL = "https://newsapi.org/v2/everything"


def get_fed_speeches(days: int = 7) -> List[Dict]:
    """
    Get recent Federal Reserve speeches and statements
    
    Args:
        days: Number of days to look back
        
    Returns:
        List of news articles about Fed
    """
    if not NEWS_API_KEY:
        # Return empty list if no API key (graceful degradation)
        return []
    
    from_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    
    params = {
        "q": "Federal Reserve OR Fed OR Jerome Powell OR FOMC",
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
        print(f"Error fetching Fed speeches: {e}")
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
    Get recent macroeconomic news
    
    Args:
        days: Number of days to look back
        
    Returns:
        List of macro news articles
    """
    if not NEWS_API_KEY:
        return []
    
    from_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    
    params = {
        "q": "inflation OR CPI OR GDP OR unemployment OR Fed rate",
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
        print(f"Error fetching macro news: {e}")
        return []

