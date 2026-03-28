"""
Official-source scrapers for high-confidence market events.

Provides simple RSS/HTML fetchers for Federal Reserve press releases
and BLS news releases. Returns a list of article dicts compatible with
the headline pipeline: title, description, published_at, source, url.
"""
import logging
import time
import requests
import xml.etree.ElementTree as ET
from typing import Dict, List
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger("btc_macro.headline_engine.sources")


_RSS_REQUEST_TIMEOUT_SECONDS = 12
_RSS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; btc-macro-headline-fetcher/1.0)",
    "Accept": "application/rss+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.6",
    "Accept-Language": "en-US,en;q=0.9",
}
_BLS_HEADERS = {
    "Referer": "https://www.bls.gov/",
    "Cache-Control": "no-cache",
}


def _build_rss_session() -> requests.Session:
    retry = Retry(
        total=2,
        connect=2,
        read=2,
        status=2,
        backoff_factor=0.7,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


_RSS_SESSION = _build_rss_session()


def _headers_for_url(url: str) -> Dict[str, str]:
    headers = dict(_RSS_HEADERS)
    if "bls.gov" in url:
        headers.update(_BLS_HEADERS)
    return headers


def _parse_rss(url: str, limit: int = 10) -> List[Dict]:
    headers = _headers_for_url(url)
    last_error = None

    for attempt in range(2):
        try:
            resp = _RSS_SESSION.get(
                url,
                timeout=_RSS_REQUEST_TIMEOUT_SECONDS,
                headers=headers,
            )

            # Some strict RSS endpoints intermittently reject first contact.
            if resp.status_code == 403 and attempt == 0:
                time.sleep(0.6)
                continue

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
        except ET.ParseError as e:
            logger.warning("RSS XML parse failed for %s: %s", url, e)
            return []
        except requests.RequestException as e:
            last_error = e
            if attempt == 0:
                time.sleep(0.6)
                continue
        except Exception as e:
            logger.warning("RSS parse failed for %s: %s", url, e)
            return []

    if last_error is not None:
        response = getattr(last_error, "response", None)
        status = getattr(response, "status_code", "n/a") if response is not None else "n/a"
        reason = getattr(response, "reason", "") if response is not None else ""
        logger.warning("RSS fetch failed for %s after retry: HTTP %s %s", url, status, reason)
    return []


def fetch_fomc_releases(days: int = 3) -> List[Dict]:
    """Fetch recent Fed press releases / FOMC outputs via RSS where available."""
    # Order: feeds that still respond reliably first (press_releases often 404).
    feeds = [
        'https://www.federalreserve.gov/feeds/press_monetary.xml',
        'https://www.federalreserve.gov/feeds/speeches.xml',
        'https://www.federalreserve.gov/feeds/press_all.xml',
        'https://www.federalreserve.gov/feeds/press_releases.xml',
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
    """Fetch recent BLS news releases via RSS (try multiple endpoints)."""
    for feed in (
        'https://www.bls.gov/feed/bls_news.xml',
        'https://www.bls.gov/feed/',
    ):
        items = _parse_rss(feed, limit=10)
        if items:
            for it in items:
                it['source'] = 'BLS'
            return items
    return []
