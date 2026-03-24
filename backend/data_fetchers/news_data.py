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


# ── Fed tone LLM v2: macro analyst rubric (prompt_version 2.0.0) ─────────────

FED_TONE_SYSTEM_MESSAGE = (
    "You are a macroeconomic analyst specializing in Federal Reserve communication. "
    "Do not use generic sentiment analysis—evaluate monetary policy signals only. "
    "Do not hallucinate facts outside the input. Return ONLY valid JSON, no markdown."
)

FED_TONE_USER_TEMPLATE = """## ROLE
You are a macroeconomic analyst specializing in Federal Reserve communication.

Your task is to analyze the "tone" of Federal Reserve communication and classify it as:
* Hawkish
* Dovish
* Neutral

---

## DATA SOURCE CONTEXT

The input text may come from:
* Federal Reserve FOMC statements
* Federal Reserve meeting minutes
* Speeches by Federal Reserve officials (e.g., Chair Jerome Powell)
* Official Federal Reserve press releases

Assume the text is authoritative and policy-relevant.

---

## ANALYSIS INSTRUCTIONS

Do NOT use generic sentiment analysis.

Instead, evaluate tone based on monetary policy signals:

HAWKISH indicators:
* Focus on inflation being high or persistent
* Emphasis on tightening policy or higher interest rates
* Strong labor market with no urgency to stimulate
* Language suggesting caution against easing

DOVISH indicators:
* Concern about economic slowdown or recession
* Emphasis on unemployment or weakening demand
* Signals of easing policy or rate cuts
* Language suggesting support/stimulus

NEUTRAL indicators:
* Balanced risks
* Data-dependent stance
* No clear bias toward tightening or easing

Pay attention to NEGATION (e.g. "will NOT cut rates" is hawkish).

---

## SCORING METHOD

1. Identify key phrases that indicate policy direction
2. Assign:
   +1 for hawkish signals
   -1 for dovish signals
3. Compute total score

Tone classification:
* Score ≥ +2 → Hawkish
* Score ≤ -2 → Dovish
* Otherwise → Neutral

---

## INPUT TEXT (Fed-related news excerpts)

{snippets}

---

## OUTPUT FORMAT (STRICT JSON)

Return ONLY valid JSON in this format:

{{
"tone": "Hawkish | Dovish | Neutral",
"score": <number>,
"confidence": <integer 0-100>,
"summary": "<2-3 sentence explanation of tone>",
"key_signals": [
  {{
    "text": "exact phrase from input",
    "type": "hawkish | dovish",
    "reason": "why it indicates this tone"
  }}
]
}}

---

## IMPORTANT RULES

* Do not hallucinate facts outside the input
* Only use evidence from the given text
* Keep explanations concise and analytical
* Prioritize policy meaning over emotional tone
"""


def _normalize_fed_tone_label(raw: Optional[str]) -> str:
    t = (raw or "neutral").strip().lower()
    if t in ("hawkish", "dovish", "neutral"):
        return t
    if "hawkish" in t:
        return "hawkish"
    if "dovish" in t:
        return "dovish"
    return "neutral"


def _fed_tone_counts_for_scoring(
    key_signals: List[Dict],
    tone_label: str,
    score: int,
) -> tuple:
    """Map LLM key_signals (+ tone/score fallback) to hawkish/dovish/pivot counts for score_fed_policy."""
    h, d = 0, 0
    if isinstance(key_signals, list):
        for item in key_signals:
            if not isinstance(item, dict):
                continue
            typ = (item.get("type") or "").strip().lower()
            if typ == "hawkish":
                h += 1
            elif typ == "dovish":
                d += 1
    if h == 0 and d == 0:
        if tone_label == "hawkish":
            h = max(2, min(5, abs(int(score)) if score else 3))
        elif tone_label == "dovish":
            d = max(2, min(5, abs(int(score)) if score else 3))
        else:
            h, d = 1, 1
    return h, d, 0


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
    Use LLM with macro-analyst rubric (+1/-1 scoring, strict JSON with key_signals).

    Returns the same base shape as analyze_fed_keywords() for score_fed_policy,
    plus fed_tone_score, fed_tone_summary, fed_tone_key_signals, fed_tone_confidence_pct.

    Cached by hash of article snippets (prompt v2).
    """
    if not articles:
        return analyze_fed_keywords(articles)

    import hashlib

    top_articles = articles[:5]
    snippets = "\n\n".join(
        f"Title: {a.get('title', '')}\nSnippet: {(a.get('description') or '')[:500]}"
        for a in top_articles
    )
    cache_key = f"fed_tone_llm_v2_{hashlib.sha256(snippets.encode()).hexdigest()[:20]}"
    cached = cache_get(cache_key)
    if cached is not None:
        logger.info("Using cached Fed tone LLM result (v2)")
        return cached

    user_prompt = FED_TONE_USER_TEMPLATE.format(snippets=snippets)

    try:
        from scoring_engine.llm_caller import call_llm_json

        cfg = _load_llm_config().get("fed_tone_analysis", {})
        result = call_llm_json(
            prompt=user_prompt,
            system_message=FED_TONE_SYSTEM_MESSAGE,
            model=cfg.get("model", "gpt-4o"),
            temperature=cfg.get("temperature", 0),
            max_tokens=cfg.get("max_tokens", 900),
            required_keys=["tone", "score", "confidence", "summary", "key_signals"],
            strict_json=True,
        )

        if result is None:
            raise ValueError("LLM returned None")

        tone_raw = result.get("tone", "neutral")
        tone = _normalize_fed_tone_label(str(tone_raw))

        try:
            score = int(result.get("score", 0))
        except (TypeError, ValueError):
            score = 0

        conf_raw = result.get("confidence", 50)
        try:
            conf_pct = int(float(conf_raw))
        except (TypeError, ValueError):
            conf_pct = 50
        conf_pct = max(0, min(100, conf_pct))
        conf = conf_pct / 100.0

        key_signals = result.get("key_signals")
        if not isinstance(key_signals, list):
            key_signals = []

        def _signal_type(raw: str) -> Optional[str]:
            sl = (raw or "").lower()
            if "hawkish" in sl:
                return "hawkish"
            if "dovish" in sl:
                return "dovish"
            return None

        cleaned_signals = []
        for item in key_signals[:12]:
            if not isinstance(item, dict):
                continue
            st = _signal_type(str(item.get("type", "")))
            if st is None:
                continue
            cleaned_signals.append({
                "text": str(item.get("text", ""))[:300],
                "type": st,
                "reason": str(item.get("reason", ""))[:400],
            })

        hawkish_s, dovish_s, pivot_s = _fed_tone_counts_for_scoring(
            cleaned_signals,
            tone,
            score,
        )

        summary = str(result.get("summary", "")).strip()

        logger.info(
            "LLM Fed tone v2: %s score=%d (h_sig=%d d_sig=%d) conf=%d%% — %s",
            tone, score, hawkish_s, dovish_s, conf_pct, summary[:120],
        )

        fed_result = {
            "dovish_keywords_found": dovish_s,
            "hawkish_keywords_found": hawkish_s,
            "pivot_keywords_found": pivot_s,
            "tone": tone,
            "articles_analyzed": len(top_articles),
            "llm_fed_tone": True,
            "key_insight": summary[:500] if summary else "",
            "fed_tone_confidence": conf,
            "fed_tone_confidence_pct": conf_pct,
            "fed_tone_score": score,
            "fed_tone_summary": summary,
            "fed_tone_key_signals": cleaned_signals,
            "fed_tone_prompt_version": cfg.get("prompt_version", "2.0.0"),
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


