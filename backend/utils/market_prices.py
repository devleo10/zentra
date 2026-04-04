"""Live market price sourcing (commodities, FX index, equities vol).

``STRICT_LIVE_OFFICIAL_ONLY=0`` (default): Yahoo Finance symbols that match what
most users see on TradingView (e.g. ``CL=F`` WTI futures, ``DX-Y.NYB`` ICE DXY,
``XAUUSD=X`` / ``GC=F`` gold, ``^VIX``, ``^GSPC``, ``NG=F``).

``STRICT_LIVE_OFFICIAL_ONLY=1``: prefer official/statistical feeds (FRED, EIA,
LBMA, ECB basket) where implemented; numbers may differ from TradingView charts.
"""
import os


def strict_live_official_prices() -> bool:
    """When True, use official feeds for prices that have a strict path in fetchers."""
    return os.getenv("STRICT_LIVE_OFFICIAL_ONLY", "0").strip().lower() not in {"0", "false", "no"}
