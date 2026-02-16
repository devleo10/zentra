"""
Official-source scrapers for high-confidence market events.

Provides simple RSS/HTML fetchers for Federal Reserve press releases
and BLS news releases. Returns a list of article dicts compatible with
the headline pipeline: title, description, published_at, source, url.
"""
import requests
import xml.etree.ElementTree as ET
from typing import List, Dict
from datetime import datetime, timedelta
import logging

logger = logging.getLogger("btc_macro.headline_engine.sources")


def _parse_rss(url: str, limit: int = 10) -> List[Dict]:
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        items = root.findall('.//item')
        out = []
        for item in items[:limit]:
            title = item.findtext('title', '')
            desc = item.findtext('description', '') or ''
            pub = item.findtext('pubDate', '') or item.findtext('published', '') or ''
            link = item.findtext('link', '')
            out.append({
                'title': title,
                'description': desc,
                'published_at': pub,
                'source': url,
                'url': link,
            })
        return out
    except Exception as e:
        logger.warning("RSS parse failed for %s: %s", url, e)
        return []


def fetch_fomc_releases(days: int = 3) -> List[Dict]:
    """Fetch recent Fed press releases / FOMC outputs via RSS where available."""
    # Federal Reserve provides several feeds; try press releases first
    feeds = [
        'https://www.federalreserve.gov/feeds/press_releases.xml',
        'https://www.federalreserve.gov/feeds/press_releases.xml',
        'https://www.federalreserve.gov/feeds/press_releases.xml'
    ]
    # Try each feed in order
    for feed in feeds:
        items = _parse_rss(feed, limit=10)
        if items:
            # tag source to friendly name
            for it in items:
                it['source'] = 'Federal Reserve'
            return items

    # Fallback: try news RSS for the Fed site
    try:
        feed2 = 'https://www.federalreserve.gov/feeds/press.xml'
        items = _parse_rss(feed2, limit=10)
        for it in items:
            it['source'] = 'Federal Reserve'
        return items
    except Exception:
        return []


def fetch_bls_releases(days: int = 3) -> List[Dict]:
    """Fetch recent BLS news releases via RSS."""
    feed = 'https://www.bls.gov/feed/'
    items = _parse_rss(feed, limit=10)
    for it in items:
        it['source'] = 'BLS'
    return items
