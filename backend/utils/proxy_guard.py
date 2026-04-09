from __future__ import annotations

import logging
import os
from urllib.parse import urlparse

logger = logging.getLogger("btc_macro.proxy_guard")


_PROXY_ENV_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)


def _looks_like_dead_local_proxy(value: str) -> bool:
    """Detect the common "localhost:9" dead-proxy pattern seen on Windows."""
    if not value:
        return False
    try:
        u = urlparse(value)
        host = (u.hostname or "").strip().lower()
        port = u.port
    except Exception:
        return False
    if host in {"127.0.0.1", "localhost", "::1"} and port in {9, 0}:
        return True
    return False


def sanitize_proxy_env(*, allow_system_proxy: bool | None = None) -> None:
    """Remove broken system proxy env vars for this process.

    This avoids outbound data fetches failing when the machine has a dead
    proxy configured (common in some dev environments).

    Controlled by env var:
      RESPECT_SYSTEM_PROXY=1 -> do nothing
    """
    if allow_system_proxy is None:
        allow_system_proxy = os.getenv("RESPECT_SYSTEM_PROXY", "0").strip().lower() in {"1", "true", "yes"}
    if allow_system_proxy:
        return

    removed = []
    for k in _PROXY_ENV_KEYS:
        v = os.environ.get(k)
        if not v:
            continue
        # If any proxy is set, and it points at a dead local proxy, remove it.
        if _looks_like_dead_local_proxy(v):
            removed.append((k, v))
            os.environ.pop(k, None)

    if removed:
        def _redact_proxy_url(raw: str) -> str:
            try:
                u = urlparse(raw)
                host = u.hostname or ""
                port = u.port
                scheme = u.scheme or "http"
                if host and port:
                    return f"{scheme}://{host}:{port}"
                if host:
                    return f"{scheme}://{host}"
            except Exception:
                pass
            return "<redacted>"

        # Keep this as a warning so it's visible in prod logs if misconfigured.
        logger.warning(
            "Removed broken proxy env vars for this process: %s",
            ", ".join([f"{k}={_redact_proxy_url(v)}" for (k, v) in removed]),
        )
