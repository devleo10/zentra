"""Shared HTTP GET with retries for transient failures (5xx, 429, timeouts)."""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger("btc_macro.http_retry")

DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BACKOFF_BASE = 2.0


def _redact_params(params: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not params:
        return params
    redacted = dict(params)
    for key in ("api_key", "apikey", "token", "access_token", "authorization"):
        if key in redacted and redacted[key] is not None:
            redacted[key] = "***REDACTED***"
    return redacted


def get_with_retries(
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = 15,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    backoff_base: float = DEFAULT_BACKOFF_BASE,
    log_4xx_body: bool = True,
    body_snippet_len: int = 500,
) -> requests.Response:
    """
    GET with retries on timeout, connection error, 429, and 5xx.
    On 4xx (other than 429), logs response body snippet and raises HTTPError.
    """
    last_exc: Optional[BaseException] = None
    safe_params = _redact_params(params)
    for attempt in range(max_attempts):
        try:
            resp = requests.get(url, params=params, headers=headers or {}, timeout=timeout)
            if resp.status_code == 429:
                last_exc = None
                wait_hdr = resp.headers.get("Retry-After")
                try:
                    wait_s = float(wait_hdr) if wait_hdr else backoff_base ** (attempt + 1)
                except (TypeError, ValueError):
                    wait_s = backoff_base ** (attempt + 1)
                wait_s = min(max(wait_s, 0.5), 60.0)
                logger.warning("HTTP 429 for %s; retry in %.1fs (attempt %s/%s)", url, wait_s, attempt + 1, max_attempts)
                if attempt < max_attempts - 1:
                    time.sleep(wait_s)
                continue
            if 500 <= resp.status_code < 600:
                logger.warning("HTTP %s for %s (attempt %s/%s)", resp.status_code, url, attempt + 1, max_attempts)
                if attempt < max_attempts - 1:
                    time.sleep(backoff_base**attempt)
                continue
            if 400 <= resp.status_code < 500 and log_4xx_body:
                snippet = (resp.text or "")[:body_snippet_len]
                logger.warning("HTTP %s for %s params=%s body_snippet=%s", resp.status_code, url, safe_params, snippet)
            resp.raise_for_status()
            return resp
        except (requests.Timeout, requests.ConnectionError) as e:
            last_exc = e
            logger.warning("Request error %s for %s (attempt %s/%s)", e, url, attempt + 1, max_attempts)
            if attempt < max_attempts - 1:
                time.sleep(backoff_base**attempt)
    if last_exc:
        raise last_exc
    raise RuntimeError(f"Max retries exceeded for {url}")
