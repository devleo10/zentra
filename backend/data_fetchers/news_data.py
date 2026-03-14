"""
Fetch Fed speeches and macro news from NewsAPI with free-tier fallback.
Includes LLM-powered semantic tone analysis with keyword fallback.
"""
import os
import re
import json
import logging
import requests
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from dotenv import load_dotenv
from data_fetchers.cache import get as cache_get, put as cache_put

load_dotenv()

logger = logging.getLogger("btc_macro.news_data")

NEWS_API_KEY = os.getenv("NEWS_API_KEY")
NEWS_API_URL = "https://newsapi.org/v2/everything"

_LLM_CONFIG_PATH = Path(__file__).parent.parent / "config" / "llm_config.json"

def _load_llm_config():
    with open(_LLM_CONFIG_PATH) as f:
        return json.load(f)

# NewsAPI free tier only allows ~30 days lookback
NEWSAPI_MAX_DAYS = 29

FED_ACTOR_PATTERNS = [
    r"\bfederal reserve\b",
    r"\bfomc\b",
    r"\bjerome powell\b",
    r"\bpowell\b",
    r"\bfed chair\b",
    r"\bfed officials?\b",
    r"\bfed funds\b",
    r"\bfed rate\b",
]

FED_POLICY_PATTERNS = [
    r"\binterest rates?\b",
    r"\brate (?:cut|cuts|cutting|hike|hikes|hiking|hold|holds|pause|pauses)\b",
    r"\bmonetary policy\b",
    r"\bpolicy stance\b",
    r"\bdot plot\b",
    r"\beconomic projections\b",
    r"\bfomc statement\b",
    r"\bfomc minutes?\b",
    r"\bbalance sheet\b",
    r"\bquantitative easing\b",
    r"\bquantitative tightening\b",
    r"\bqe\b",
    r"\bqt\b",
    r"\binflation\b",
    r"\bdisinflation\b",
    r"\bhigher for longer\b",
    r"\bpremature easing\b",
]

FED_PRIORITY_SOURCES = {"Federal Reserve", "Reuters", "Bloomberg", "Wall Street Journal", "WSJ", "CNBC", "Financial Times", "FT", "Stratfor"}


def _is_fed_policy_article(article: Dict) -> bool:
    """Require both a Fed actor and a policy context to avoid false positives."""
    title = article.get("title", "") or ""
    description = article.get("description", "") or ""
    source = article.get("source", "") or ""
    text = f"{title} {description}".lower()

    if source.lower() == "federal reserve":
        return True

    actor_match = any(re.search(pattern, text, re.I) for pattern in FED_ACTOR_PATTERNS)
    policy_match = any(re.search(pattern, text, re.I) for pattern in FED_POLICY_PATTERNS)
    return actor_match and policy_match


def _fed_article_sort_key(article: Dict) -> tuple:
    """Sort official/authoritative and most recent Fed-policy articles first."""
    source = article.get("source", "") or ""
    source_priority = 1 if source in FED_PRIORITY_SOURCES else 0
    published_at = article.get("published_at", "") or ""
    return (source_priority, published_at)


def _filter_fed_policy_articles(articles: List[Dict]) -> List[Dict]:
    filtered = [article for article in articles if _is_fed_policy_article(article)]
    filtered.sort(key=_fed_article_sort_key, reverse=True)
    return filtered


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

    Results are cached for 30 min so back-to-back analysis runs use
    identical article sets, eliminating the largest source of score jitter.
    
    Args:
        days: Number of days to look back
        
    Returns:
        List of news articles about Fed
    """
    cache_key = f"fed_speeches_{days}"
    cached = cache_get(cache_key)
    if cached is not None:
        logger.info("Using cached Fed speeches (%d articles, days=%d)", len(cached), days)
        return cached

    query = '"Federal Reserve" OR FOMC OR "Jerome Powell" OR "Fed Chair" OR "Fed funds" OR "interest rates"'

    # Try NewsAPI first (only if within free-tier date limit)
    if NEWS_API_KEY and days <= NEWSAPI_MAX_DAYS:
        articles = _fetch_newsapi(query, days)
        if articles:
            filtered = _filter_fed_policy_articles(articles)
            logger.info("Fed article filter kept %d of %d fetched articles", len(filtered), len(articles))
            cache_put(cache_key, filtered)
            return filtered

    # Fallback: Google News RSS (free, no date limits)
    print(f"Using Google News RSS fallback for Fed speeches (days={days})...")
    articles = _fetch_google_news_rss(query, num=10)
    filtered = _filter_fed_policy_articles(articles)
    logger.info("Fed article filter kept %d of %d fetched articles", len(filtered), len(articles))
    if filtered:
        cache_put(cache_key, filtered)
    return filtered


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
    Analyze Fed speeches for dovish/hawkish keywords (shared config + word-boundary matching).
    
    Returns:
        Dict with keyword counts and tone assessment
    """
    from utils.keyword_matcher import get_matched_keywords

    text_content = " ".join([
        article.get("title", "") + " " + article.get("description", "")
        for article in articles
    ])
    matched = get_matched_keywords(text_content)
    dovish_count = len(matched["dovish"])
    hawkish_count = len(matched["hawkish"])

    pivot_keywords = [
        "at or near terminal rate", "lagged effects",
        "monitoring credit conditions", "financial stability"
    ]
    text_lower = text_content.lower()
    pivot_count = sum(1 for keyword in pivot_keywords if keyword in text_lower)
    
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


def analyze_fed_tone_llm(articles: List[Dict]) -> Dict:
    """
    Use LLM to semantically analyze the tone of Fed-related articles.

    Returns the same shape as analyze_fed_keywords() so callers are
    drop-in compatible.  Falls back to keyword counting on any failure.

    Cached by a hash of article titles so identical inputs skip the LLM call.
    """
    if not articles:
        return analyze_fed_keywords(articles)

    import hashlib
    titles_key = hashlib.sha256(
        "|".join(a.get("title", "") for a in articles[:5]).encode()
    ).hexdigest()[:16]
    cache_key = f"fed_tone_llm_{titles_key}"
    cached = cache_get(cache_key)
    if cached is not None:
        logger.info("Using cached Fed tone LLM result")
        return cached

    top_articles = articles[:5]
    snippets = "\n\n".join(
        f"Title: {a.get('title', '')}\nSnippet: {(a.get('description') or '')[:200]}"
        for a in top_articles
    )

    prompt = (
        "You are a Federal Reserve policy tone analyst.\n"
        "Analyze these recent Fed-related news articles and determine the overall "
        "monetary policy tone.\n\n"
        f"--- ARTICLES ---\n{snippets}\n--- END ---\n\n"
        "Output ONLY valid JSON in this exact format:\n"
        "{\n"
        '  "overall_tone": "hawkish" | "dovish" | "neutral",\n'
        '  "dovish_signals": <int 0-5>,\n'
        '  "hawkish_signals": <int 0-5>,\n'
        '  "pivot_signals": <int 0-5>,\n'
        '  "key_insight": "<one sentence summary>",\n'
        '  "confidence": <float 0.0-1.0>\n'
        "}\n\n"
        "Rules:\n"
        "- hawkish = tighter policy, higher-for-longer, persistent inflation concerns\n"
        "- dovish = easing signals, rate cuts, disinflation progress\n"
        "- neutral = mixed signals or no clear direction\n"
        "- Pay attention to NEGATION (e.g. 'will NOT cut' is hawkish)\n"
        "- confidence = how clearly the articles point in one direction\n"
    )

    try:
        from scoring_engine.llm_caller import call_llm_json

        cfg = _load_llm_config().get("fed_tone_analysis", {})
        result = call_llm_json(
            prompt=prompt,
            system_message="You are a Federal Reserve policy tone analyst. Output only valid JSON.",
            model=cfg.get("model", "gpt-4o"),
            temperature=cfg.get("temperature", 0),
            max_tokens=cfg.get("max_tokens", 200),
            required_keys=[
                "overall_tone",
                "dovish_signals",
                "hawkish_signals",
                "pivot_signals",
                "key_insight",
                "confidence",
            ],
            strict_json=True,
        )

        if result is None:
            raise ValueError("LLM returned None")

        tone = result.get("overall_tone", "neutral")
        if tone not in ("hawkish", "dovish", "neutral"):
            tone = "neutral"

        dovish_s = max(0, min(5, int(result.get("dovish_signals", 0))))
        hawkish_s = max(0, min(5, int(result.get("hawkish_signals", 0))))
        pivot_s = max(0, min(5, int(result.get("pivot_signals", 0))))
        conf = max(0.0, min(1.0, float(result.get("confidence", 0.5))))

        logger.info(
            "LLM Fed tone: %s (dovish=%d hawkish=%d pivot=%d conf=%.2f) — %s",
            tone, dovish_s, hawkish_s, pivot_s, conf,
            result.get("key_insight", ""),
        )

        fed_result = {
            "dovish_keywords_found": dovish_s,
            "hawkish_keywords_found": hawkish_s,
            "pivot_keywords_found": pivot_s,
            "tone": tone,
            "articles_analyzed": len(top_articles),
            "llm_fed_tone": True,
            "key_insight": result.get("key_insight", ""),
            "fed_tone_confidence": conf,
        }
        cache_put(cache_key, fed_result)
        return fed_result

    except Exception as e:
        logger.warning("LLM Fed tone analysis failed (%s), falling back to keywords", e)
        fallback = analyze_fed_keywords(articles)
        fallback["llm_fed_tone"] = False
        return fallback


def get_macro_news(days: int = 7) -> List[Dict]:
    """
    Get recent macroeconomic news.
    Uses NewsAPI for short lookbacks, falls back to Google News RSS.
    
    Args:
        days: Number of days to look back
        
    Returns:
        List of macro news articles
    """
    cache_key = f"macro_news_{days}"
    cached = cache_get(cache_key)
    if cached is not None:
        logger.info("Using cached macro news (%d articles, days=%d)", len(cached), days)
        return cached

    query = "inflation OR CPI OR GDP OR unemployment OR Fed rate"

    # Try NewsAPI first (only if within free-tier limit)
    if NEWS_API_KEY and days <= NEWSAPI_MAX_DAYS:
        articles = _fetch_newsapi(query, days)
        if articles:
            cache_put(cache_key, articles)
            return articles

    # Fallback: Google News RSS
    print(f"Using Google News RSS fallback for macro news (days={days})...")
    articles = _fetch_google_news_rss(query, num=10)
    if articles:
        cache_put(cache_key, articles)
    return articles


