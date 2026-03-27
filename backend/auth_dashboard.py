"""
Dashboard login: DASHBOARD_CLIENT_ID + DASHBOARD_CLIENT_SECRET in env (login ID + password).

When both are set, v2 analysis routes require Authorization: Bearer <token>
from POST /api/auth/login. When either is unset, auth is disabled (local dev).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
from typing import Any, Dict, Optional

from fastapi import Header, HTTPException

logger = logging.getLogger("btc_macro.api.auth")

_TOKEN_TTL_SECONDS = int(os.getenv("DASHBOARD_TOKEN_TTL_SECONDS", str(7 * 24 * 3600)))


def token_ttl_seconds() -> int:
    return _TOKEN_TTL_SECONDS


def dashboard_auth_enabled() -> bool:
    cid = (os.getenv("DASHBOARD_CLIENT_ID") or "").strip()
    csec = (os.getenv("DASHBOARD_CLIENT_SECRET") or "").strip()
    return bool(cid and csec)


def _signing_secret() -> bytes:
    raw = (os.getenv("API_AUTH_SIGNING_SECRET") or os.getenv("DASHBOARD_CLIENT_SECRET") or "dev-insecure").encode(
        "utf-8"
    )
    return hashlib.sha256(raw).digest()


def issue_token(client_id: str) -> str:
    """Return URL-safe token: payload_b64.sig_b64"""
    now = int(time.time())
    payload = {"sub": client_id, "iat": now, "exp": now + _TOKEN_TTL_SECONDS}
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    pl_b64 = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    sig = hmac.new(_signing_secret(), pl_b64.encode("ascii"), hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).decode("ascii").rstrip("=")
    return f"{pl_b64}.{sig_b64}"


def verify_token(token: str) -> bool:
    if not token or "." not in token:
        return False
    pl_b64, sig_b64 = token.split(".", 1)
    pad = "=" * (-len(pl_b64) % 4)
    try:
        raw = base64.urlsafe_b64decode(pl_b64 + pad)
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        return False
    exp = int(payload.get("exp", 0))
    if exp < int(time.time()):
        return False
    sig_pad = "=" * (-len(sig_b64) % 4)
    try:
        sig = base64.urlsafe_b64decode(sig_b64 + sig_pad)
    except Exception:
        return False
    expected = hmac.new(_signing_secret(), pl_b64.encode("ascii"), hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected):
        return False
    return True


def verify_credentials(client_id: str, client_secret: str) -> bool:
    expect_id = (os.getenv("DASHBOARD_CLIENT_ID") or "").strip()
    expect_sec = (os.getenv("DASHBOARD_CLIENT_SECRET") or "").strip()
    if not expect_id or not expect_sec:
        return False
    return hmac.compare_digest(client_id.encode("utf-8"), expect_id.encode("utf-8")) and hmac.compare_digest(
        client_secret.encode("utf-8"), expect_sec.encode("utf-8")
    )


async def require_dashboard_user(authorization: Optional[str] = Header(None)) -> Optional[Dict[str, Any]]:
    """
    FastAPI dependency: no-op when auth disabled; otherwise require valid Bearer token.
    """
    if not dashboard_auth_enabled():
        return None
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401,
            detail="Authentication required. Log in to run analysis.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.split(" ", 1)[1].strip()
    if not verify_token(token):
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired session. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return {"ok": True}
