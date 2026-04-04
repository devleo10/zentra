"""
Fetch cryptocurrency data from CoinGecko API
"""
import logging
import math
import threading
import time
import requests
from typing import Dict, List, Optional
from datetime import datetime, timedelta

logger = logging.getLogger("btc_macro.data_fetchers.coingecko")

COINGECKO_BASE_URL = "https://api.coingecko.com/api/v3"
COINLORE_BASE_URL = "https://api.coinlore.net/api"

# Minimum seconds between CoinGecko calls in one process (free tier friendly).
_CG_MIN_INTERVAL_SEC = 2.0
_cg_lock = threading.Lock()
_cg_last_call_monotonic: float = 0.0

# One /global response serves both BTC dominance and stablecoin dominance.
_GLOBAL_CACHE_TTL_SEC = 600.0
_GLOBAL_FAIL_BACKOFF_SEC = 120.0
_global_payload_lock = threading.Lock()
_global_payload: Optional[dict] = None
_global_payload_ts: float = 0.0
_global_skip_http_until: float = 0.0

# One /simple/price for bitcoin+ethereum serves get_btc_price + get_eth_btc_ratio.
_SIMPLE_MACRO_TTL_SEC = 180.0
_simple_macro_lock = threading.Lock()
_simple_macro_json: Optional[dict] = None
_simple_macro_ts: float = 0.0

_COINLORE_TTL_SEC = 600.0
_coinlore_global_lock = threading.Lock()
_coinlore_global_payload: Optional[dict] = None
_coinlore_global_ts: float = 0.0
_coinlore_tickers_lock = threading.Lock()
_coinlore_tickers_payload: Optional[List[dict]] = None
_coinlore_tickers_ts: float = 0.0

STABLECOIN_SYMBOLS = frozenset(
    {
        "USDT",
        "USDC",
        "DAI",
        "FDUSD",
        "USDE",
        "PYUSD",
        "TUSD",
        "USDS",
        "USDB",
        "GUSD",
        "FRAX",
    }
)
STABLECOIN_IDS = ("tether", "usd-coin", "dai")

_CG_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ZentraMacro/1.0)",
    "Accept": "application/json",
}

_COINBASE_EXCHANGE_URL = "https://api.exchange.coinbase.com"
_KRAKEN_PUBLIC_URL = "https://api.kraken.com/0/public"

_DOMINANCE_TIMEFRAME_DAYS = {"current": 1, "week": 7, "month": 30}


def _cg_throttle() -> None:
    global _cg_last_call_monotonic
    with _cg_lock:
        now = time.monotonic()
        wait = _CG_MIN_INTERVAL_SEC - (now - _cg_last_call_monotonic)
        if wait > 0:
            time.sleep(wait)
        _cg_last_call_monotonic = time.monotonic()


def _cg_get(
    url: str,
    *,
    timeout: float = 15,
    params=None,
    retries_on_429: int = 1,
    max_wait_on_429: float = 8.0,
):
    """Throttled GET with bounded 429 waits to keep total latency predictable."""
    attempts = max(1, retries_on_429 + 1)
    for attempt in range(attempts):
        _cg_throttle()
        resp = requests.get(url, params=params, timeout=timeout, headers=_CG_HEADERS)
        if resp.status_code == 429:
            ra = resp.headers.get("Retry-After")
            try:
                wait_s = min(float(ra), max_wait_on_429) if ra else 2.0 * (attempt + 1)
            except (TypeError, ValueError):
                wait_s = 2.0 * (attempt + 1)
            logger.warning("CoinGecko 429 for %s; sleeping %.1fs (attempt %s/%s)", url, wait_s, attempt + 1, attempts)
            if attempt < attempts - 1:
                time.sleep(wait_s)
                continue
        resp.raise_for_status()
        return resp
    raise RuntimeError("CoinGecko request failed")


def _get_global_market_payload() -> Optional[dict]:
    """Single throttled GET /global; cached ~10m. Serves dominance + stables (was 2× duplicate calls)."""
    global _global_payload, _global_payload_ts, _global_skip_http_until
    with _global_payload_lock:
        now = time.monotonic()
        if _global_payload is not None and (now - _global_payload_ts) < _GLOBAL_CACHE_TTL_SEC:
            return _global_payload
        if now < _global_skip_http_until:
            return _global_payload
        url = f"{COINGECKO_BASE_URL}/global"
        try:
            resp = _cg_get(url, timeout=20, retries_on_429=1, max_wait_on_429=10.0)
            resp.raise_for_status()
            body = resp.json()
            inner = body.get("data")
            _global_payload = inner if isinstance(inner, dict) else {}
            _global_payload_ts = time.monotonic()
            _global_skip_http_until = 0.0
            return _global_payload
        except Exception as e:
            logger.warning("CoinGecko global fetch failed: %s", e)
            _global_skip_http_until = time.monotonic() + _GLOBAL_FAIL_BACKOFF_SEC
            return _global_payload


def _cg_fetch_simple_macro() -> Optional[dict]:
    """GET /simple/price for bitcoin+ethereum (24h/7d flags for BTC). Cached a few minutes."""
    global _simple_macro_json, _simple_macro_ts
    with _simple_macro_lock:
        now = time.monotonic()
        if _simple_macro_json is not None and (now - _simple_macro_ts) < _SIMPLE_MACRO_TTL_SEC:
            return _simple_macro_json
        url = f"{COINGECKO_BASE_URL}/simple/price"
        params = {
            "ids": "bitcoin,ethereum",
            "vs_currencies": "usd",
            "include_24hr_change": "true",
            "include_7d_change": "true",
        }
        try:
            resp = _cg_get(url, params=params, timeout=12, retries_on_429=2, max_wait_on_429=10.0)
            resp.raise_for_status()
            _simple_macro_json = resp.json()
            _simple_macro_ts = time.monotonic()
            return _simple_macro_json
        except Exception as e:
            logger.warning("CoinGecko simple/price (BTC+ETH bundle) failed: %s", e)
            return None


def _safe_float(value) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(out):
        return None
    return out


def _pct_change(start: Optional[float], end: Optional[float]) -> float:
    if start is None or end is None:
        return 0.0
    if not start or not math.isfinite(start) or not math.isfinite(end):
        return 0.0
    return round((end - start) / start * 100.0, 2)


def _timeframe_change_from_daily_closes(closes: List[float], timeframe: str) -> Dict[str, float]:
    if not closes:
        return {"change_24h": 0.0, "change_7d": 0.0, "change": 0.0}
    last_close = closes[-1]
    change_24h = _pct_change(closes[-2], last_close) if len(closes) >= 2 else 0.0
    change_7d = _pct_change(closes[-8], last_close) if len(closes) >= 8 else _pct_change(closes[0], last_close)
    change_1m = _pct_change(closes[-31], last_close) if len(closes) >= 31 else _pct_change(closes[0], last_close)
    effective = change_24h if timeframe == "current" else change_7d if timeframe == "week" else change_1m
    return {
        "change_24h": change_24h,
        "change_7d": change_7d,
        "change": effective,
    }


def _coinbase_btc_daily_closes(limit: int = 120) -> List[float]:
    resp = requests.get(
        f"{_COINBASE_EXCHANGE_URL}/products/BTC-USD/candles",
        params={"granularity": 86400},
        timeout=20,
        headers=_CG_HEADERS,
    )
    resp.raise_for_status()
    rows = resp.json()
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("Coinbase candles empty")
    rows = sorted(rows, key=lambda row: int(row[0]))
    closes = [_safe_float(row[4]) for row in rows[-limit:]]
    return [c for c in closes if c is not None and c > 0]


def _kraken_btc_daily_closes(limit: int = 120) -> List[float]:
    resp = requests.get(
        f"{_KRAKEN_PUBLIC_URL}/OHLC",
        params={"pair": "XBTUSD", "interval": 1440},
        timeout=20,
        headers=_CG_HEADERS,
    )
    resp.raise_for_status()
    body = resp.json()
    if body.get("error"):
        raise RuntimeError("; ".join(body["error"]))
    result = body.get("result") or {}
    rows = result.get("XXBTZUSD") or result.get("XBTUSD") or []
    if not rows:
        raise RuntimeError("Kraken OHLC empty")
    closes = [_safe_float(row[4]) for row in rows[-limit:]]
    return [c for c in closes if c is not None and c > 0]


def _coinlore_get_json(path: str, *, params=None, timeout: float = 15.0):
    resp = requests.get(f"{COINLORE_BASE_URL}{path}", params=params, timeout=timeout, headers=_CG_HEADERS)
    resp.raise_for_status()
    return resp.json()


def _coinlore_global_market_payload() -> Optional[dict]:
    global _coinlore_global_payload, _coinlore_global_ts
    with _coinlore_global_lock:
        now = time.monotonic()
        if _coinlore_global_payload is not None and (now - _coinlore_global_ts) < _COINLORE_TTL_SEC:
            return _coinlore_global_payload
        try:
            body = _coinlore_get_json("/global/")
            row = body[0] if isinstance(body, list) and body else None
            _coinlore_global_payload = row if isinstance(row, dict) else None
            _coinlore_global_ts = now
            return _coinlore_global_payload
        except Exception as e:
            logger.warning("CoinLore global fetch failed: %s", e)
            return _coinlore_global_payload


def _coinlore_top_tickers(limit: int = 100) -> List[dict]:
    global _coinlore_tickers_payload, _coinlore_tickers_ts
    with _coinlore_tickers_lock:
        now = time.monotonic()
        if _coinlore_tickers_payload is not None and (now - _coinlore_tickers_ts) < _COINLORE_TTL_SEC:
            return _coinlore_tickers_payload
        try:
            body = _coinlore_get_json("/tickers/", params={"start": 0, "limit": limit})
            data = body.get("data") if isinstance(body, dict) else None
            _coinlore_tickers_payload = data if isinstance(data, list) else []
            _coinlore_tickers_ts = now
            return _coinlore_tickers_payload
        except Exception as e:
            logger.warning("CoinLore tickers fetch failed: %s", e)
            return _coinlore_tickers_payload or []


def _snapshot_btc_dominance():
    try:
        from storage.db import get_latest_snapshots
        rows = get_latest_snapshots(1)
        if rows and rows[0].get("btc_dominance") is not None:
            return float(rows[0]["btc_dominance"])
    except Exception:
        logger.debug("snapshot btc_dominance read failed", exc_info=True)
    return None


def _snapshot_stable_dom():
    """Return total stablecoin dominance from the last snapshot if present."""
    try:
        from storage.db import get_latest_snapshots
        rows = get_latest_snapshots(1)
        if not rows:
            return None
        r = rows[0]
        t = r.get("stablecoin_dominance")
        if t is None:
            return None
        return float(t)
    except Exception:
        logger.debug("snapshot stablecoin read failed", exc_info=True)
    return None


def _snapshot_series_change(field_name: str, current_value: float, timeframe: str) -> Optional[float]:
    """Compare a live dominance reading to the nearest historical snapshot for the timeframe."""
    try:
        from storage.db import get_latest_snapshots

        rows = get_latest_snapshots(90)
        if not rows:
            return None
        latest_ts = datetime.now()
        cutoff_days = _DOMINANCE_TIMEFRAME_DAYS.get(timeframe, 1)
        target_ts = latest_ts - timedelta(days=cutoff_days)

        baseline = None
        for row in rows:
            raw_val = row.get(field_name)
            if raw_val is None:
                continue
            try:
                row_ts = datetime.fromisoformat(str(row.get("timestamp")))
            except Exception:
                continue
            if row_ts <= target_ts:
                baseline = float(raw_val)
                break
        if baseline is None:
            for row in rows[1:]:
                raw_val = row.get(field_name)
                if raw_val is not None:
                    baseline = float(raw_val)
                    break
        if baseline is None and rows:
            raw_val = rows[0].get(field_name)
            if raw_val is not None:
                baseline = float(raw_val)
        if baseline is None:
            return None
        return round(current_value - baseline, 2)
    except Exception:
        logger.debug("snapshot %s change calc failed", field_name, exc_info=True)
        return None


_MCAP_HISTORY_TTL_SEC = 3600.0
_mcap_history_lock = threading.Lock()
_mcap_history_cache: Dict[str, list] = {}
_mcap_history_ts: float = 0.0


def _fetch_cg_market_cap_history(coin_id: str, days: int = 90) -> Optional[list]:
    """Daily market cap history for a CoinGecko coin. Returns [(timestamp_ms, mcap_usd), ...]."""
    global _mcap_history_cache, _mcap_history_ts
    with _mcap_history_lock:
        now = time.monotonic()
        if coin_id in _mcap_history_cache and (now - _mcap_history_ts) < _MCAP_HISTORY_TTL_SEC:
            return _mcap_history_cache[coin_id]
    try:
        url = f"{COINGECKO_BASE_URL}/coins/{coin_id}/market_chart"
        resp = _cg_get(url, params={"vs_currency": "usd", "days": days, "interval": "daily"}, timeout=20, retries_on_429=1)
        resp.raise_for_status()
        data = resp.json()
        mcaps = data.get("market_caps", [])
        if not mcaps:
            return None
        result = []
        for row in mcaps:
            if not isinstance(row, (list, tuple)) or len(row) < 2:
                continue
            ts, val = _safe_float(row[0]), _safe_float(row[1])
            if ts is not None and val is not None and val > 0:
                result.append((ts, val))
        if not result:
            return None
        with _mcap_history_lock:
            _mcap_history_cache[coin_id] = result
            _mcap_history_ts = time.monotonic()
        return result
    except Exception as e:
        logger.warning("CoinGecko market_chart for %s failed: %s", coin_id, e)
        return None


def _closest_mcap_at(series: list, target_ts_ms: float) -> Optional[float]:
    """Find market cap value closest to target timestamp (ms)."""
    if not series:
        return None
    return min(series, key=lambda x: abs(x[0] - target_ts_ms))[1]


def _estimate_dominance_change(
    current_dom: float,
    dom_field: str,
    timeframe: str,
) -> Optional[float]:
    """Estimate dominance change by fetching BTC+ETH market cap history from CoinGecko.

    Uses the fact that BTC+ETH ≈ 65-70% of total crypto market cap;
    scales by the current combined share to estimate past total market cap,
    then computes past dominance from (past coin mcap / past total mcap).

    Falls back to snapshot-based change if CoinGecko history is unavailable.
    """
    delta = _snapshot_series_change(dom_field, current_dom, timeframe)
    if delta is not None:
        return delta

    days = _DOMINANCE_TIMEFRAME_DAYS.get(timeframe, 1)
    if days < 1:
        return None

    payload = _get_global_market_payload()
    if not payload:
        return None
    mcap_pct = payload.get("market_cap_percentage") or {}
    btc_pct = _safe_float(mcap_pct.get("btc"))
    eth_pct = _safe_float(mcap_pct.get("eth"))
    if btc_pct is None or eth_pct is None or btc_pct <= 0 or eth_pct <= 0:
        return None

    combined_pct = btc_pct + eth_pct

    fetch_days = max(days + 15, 45)
    btc_mcaps = _fetch_cg_market_cap_history("bitcoin", fetch_days)
    eth_mcaps = _fetch_cg_market_cap_history("ethereum", fetch_days)
    if not btc_mcaps or not eth_mcaps:
        return None

    target_ms = (datetime.now() - timedelta(days=days)).timestamp() * 1000

    btc_mcap_past = _closest_mcap_at(btc_mcaps, target_ms)
    eth_mcap_past = _closest_mcap_at(eth_mcaps, target_ms)
    btc_mcap_now = btc_mcaps[-1][1]
    eth_mcap_now = eth_mcaps[-1][1]

    if not all(v and v > 0 for v in (btc_mcap_past, eth_mcap_past, btc_mcap_now, eth_mcap_now)):
        return None

    total_now_est = (btc_mcap_now + eth_mcap_now) / (combined_pct / 100.0)
    total_past_est = (btc_mcap_past + eth_mcap_past) / (combined_pct / 100.0)

    if dom_field == "btc_dominance":
        past_dom = btc_mcap_past / total_past_est * 100.0
    elif dom_field == "stablecoin_dominance":
        total_mcap = payload.get("total_market_cap") or {}
        current_total = _safe_float(total_mcap.get("usd"))
        if current_total and current_total > 0:
            stable_mcap_now = current_dom / 100.0 * current_total
            past_dom = stable_mcap_now / total_past_est * 100.0
        else:
            return None
    else:
        return None

    return round(current_dom - past_dom, 2)


def _cg_stablecoin_dominance_from_markets() -> Optional[Dict[str, float]]:
    payload = _get_global_market_payload() or {}
    total_market_cap = _safe_float((payload.get("total_market_cap") or {}).get("usd"))
    if total_market_cap is None or total_market_cap <= 0:
        return None

    try:
        response = _cg_get(
            f"{COINGECKO_BASE_URL}/coins/markets",
            params={
                "vs_currency": "usd",
                "per_page": 250,
                "page": 1,
            },
            timeout=20,
            retries_on_429=2,
            max_wait_on_429=10.0,
        )
        rows = response.json()
        if not isinstance(rows, list):
            return None
    except Exception as e:
        logger.warning("CoinGecko stablecoin markets fetch failed: %s", e)
        return None

    caps = {"tether": 0.0, "usd-coin": 0.0, "dai": 0.0}
    for row in rows:
        if not isinstance(row, dict):
            continue
        cid = str(row.get("id") or "").strip().lower()
        if cid not in caps:
            continue
        cap = _safe_float(row.get("market_cap"))
        if cap is not None and cap > 0:
            caps[cid] = cap

    total_stable_cap = sum(caps.values())
    if total_stable_cap <= 0:
        return None

    return {
        "usdt_dominance": round(caps["tether"] / total_market_cap * 100.0, 2),
        "usdc_dominance": round(caps["usd-coin"] / total_market_cap * 100.0, 2),
        "dai_dominance": round(caps["dai"] / total_market_cap * 100.0, 2),
        "total_stablecoin_dominance": round(total_stable_cap / total_market_cap * 100.0, 2),
    }

# Timeframe to days mapping for historical data
TIMEFRAME_DAYS = {
    "current": 1,
    "week": 7,
    "month": 30,
    "year": 365
}


def get_btc_price(timeframe: str = "current") -> Dict:
    """Get Bitcoin price data with timeframe support"""
    try:
        data = _cg_fetch_simple_macro()
        if not data:
            raise RuntimeError("simple/price macro bundle empty")
        btc_data = data.get("bitcoin", {})
        
        result = {
            "price_usd": btc_data.get("usd", 0),
            "change_24h": round(btc_data.get("usd_24h_change", 0), 2),
            "change_7d": round(btc_data.get("usd_7d_change", 0), 2),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "timeframe": timeframe
        }
        
        # For timeframe-specific change, use appropriate field
        if timeframe == "current":
            result["change"] = result["change_24h"]
        elif timeframe == "week":
            result["change"] = result["change_7d"]
        else:
            # For month/year, we need historical data
            hist_data = get_btc_historical(TIMEFRAME_DAYS.get(timeframe, 30))
            if "change" in hist_data:
                result["change"] = hist_data["change"]
            else:
                result["change"] = result["change_7d"]  # fallback
        
        return result
    except Exception as e:
        return {"error": str(e), "timeframe": timeframe}


def get_btc_spot_coinbase(timeframe: str = "current") -> Dict:
    """BTC spot via Coinbase Exchange public REST API."""
    try:
        closes = _coinbase_btc_daily_closes(limit=120)
        if not closes:
            return {"error": "Coinbase BTC candles empty", "timeframe": timeframe}
        changes = _timeframe_change_from_daily_closes(closes, timeframe)
        return {
            "price_usd": round(closes[-1], 2),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "timeframe": timeframe,
            "_source": "coinbase_exchange",
            **changes,
        }
    except Exception as e:
        return {"error": str(e), "timeframe": timeframe}


def get_btc_spot_kraken(timeframe: str = "current") -> Dict:
    """BTC spot via Kraken public REST API."""
    try:
        closes = _kraken_btc_daily_closes(limit=120)
        if not closes:
            return {"error": "Kraken BTC OHLC empty", "timeframe": timeframe}
        changes = _timeframe_change_from_daily_closes(closes, timeframe)
        return {
            "price_usd": round(closes[-1], 2),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "timeframe": timeframe,
            "_source": "kraken_public",
            **changes,
        }
    except Exception as e:
        return {"error": str(e), "timeframe": timeframe}


def get_btc_historical(days: int = 30) -> Dict:
    """Get Bitcoin historical data for calculating change over period"""
    url = f"{COINGECKO_BASE_URL}/coins/bitcoin/market_chart"
    params = {
        "vs_currency": "usd",
        "days": days
    }
    
    try:
        response = _cg_get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        prices = data.get("prices", [])
        if len(prices) >= 2:
            start_price = prices[0][1]
            end_price = prices[-1][1]
            change = ((end_price - start_price) / start_price) * 100
            return {
                "start_price": round(start_price, 2),
                "end_price": round(end_price, 2),
                "change": round(change, 2),
                "days": days
            }
        return {"error": "Insufficient historical data"}
    except Exception as e:
        return {"error": str(e)}


def get_btc_spot_binance(timeframe: str = "current") -> Dict:
    """BTC spot via Binance public REST API (no API key).

    Datacenter-friendly fallback when CoinGecko rate-limits and Yahoo is flaky.
    Output shape matches ``get_btc_price`` (price_usd, change, date, …).
    """
    from datetime import timezone

    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": "BTCUSDT", "interval": "1d", "limit": 120}
    try:
        response = requests.get(url, params=params, timeout=20)
        response.raise_for_status()
        kl = response.json()
        if not kl:
            return {"error": "Binance klines empty", "timeframe": timeframe}

        def _close(row) -> float:
            return float(row[4])

        last_close = _close(kl[-1])
        last_open_ms = int(kl[-1][0])

        def _pct(frm: float, to: float) -> float:
            if not frm:
                return 0.0
            return round((to - frm) / frm * 100, 2)

        change_24h = _pct(_close(kl[-2]), last_close) if len(kl) >= 2 else 0.0
        change_7d = _pct(_close(kl[-8]), last_close) if len(kl) >= 8 else _pct(_close(kl[0]), last_close)

        latest_dt = datetime.fromtimestamp(last_open_ms / 1000.0, tz=timezone.utc)
        cutoff_1m = latest_dt - timedelta(days=30)
        cutoff_1m_ms = int(cutoff_1m.timestamp() * 1000)
        close_1m = None
        for row in kl:
            if int(row[0]) <= cutoff_1m_ms:
                close_1m = _close(row)
            else:
                break
        if close_1m is None:
            close_1m = _close(kl[0])
        change_1m = _pct(close_1m, last_close)

        if timeframe == "current":
            ch = change_24h
        elif timeframe == "week":
            ch = change_7d
        else:
            ch = change_1m

        return {
            "price_usd": round(last_close, 2),
            "change_24h": change_24h,
            "change_7d": change_7d,
            "change": ch,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "timeframe": timeframe,
            "_source": "binance_public",
        }
    except Exception as e:
        return {"error": str(e), "timeframe": timeframe}


def _dominance_result(current: float, delta: Optional[float], timeframe: str, source: str, change_source: Optional[str] = None, fallback: bool = False) -> Dict:
    trend = "stable"
    if delta is not None:
        if delta > 0.05:
            trend = "rising"
        elif delta < -0.05:
            trend = "falling"
    out: Dict = {
        "btc_dominance": current,
        "change": delta,
        "change_source": change_source,
        "trend": trend,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "timeframe": timeframe,
        "source": source,
    }
    if fallback:
        out["_fallback"] = True
    return out


def get_btc_dominance(timeframe: str = "current") -> Dict:
    """Get Bitcoin market dominance (CoinGecko → CoinLore → snapshot).

    Change is computed from stored snapshots first; if none exist,
    CoinGecko historical market cap data (BTC + ETH) is used to
    estimate past dominance so the very first run has a real delta.
    """
    payload = _get_global_market_payload()
    if payload:
        market_cap_data = payload.get("market_cap_percentage") or {}
        btc_dominance = market_cap_data.get("btc")
        if btc_dominance is not None and float(btc_dominance) > 0:
            current = round(float(btc_dominance), 2)
            delta = _estimate_dominance_change(current, "btc_dominance", timeframe)
            cs = "snapshot_history" if _snapshot_series_change("btc_dominance", current, timeframe) is not None else "cg_market_chart" if delta is not None else None
            return _dominance_result(current, delta, timeframe, "CoinGecko", cs)

    coinlore_global = _coinlore_global_market_payload()
    if coinlore_global:
        btc_d = _safe_float(coinlore_global.get("btc_d"))
        if btc_d is not None and btc_d > 0:
            current = round(btc_d, 2)
            delta = _estimate_dominance_change(current, "btc_dominance", timeframe)
            cs = "snapshot_history" if _snapshot_series_change("btc_dominance", current, timeframe) is not None else "cg_market_chart" if delta is not None else None
            return _dominance_result(current, delta, timeframe, "CoinLore", cs, fallback=True)

    snap = _snapshot_btc_dominance()
    if snap is not None:
        logger.warning("BTC dominance: using last snapshot %.2f%%", snap)
        return _dominance_result(round(snap, 2), None, timeframe, "last_snapshot", None, fallback=True)

    return {"error": "BTC dominance unavailable", "timeframe": timeframe}


def _stablecoin_result(usdt: float, usdc: float, dai: float, total_dom: float, delta: Optional[float], timeframe: str, source: str, change_source: Optional[str] = None, fallback: bool = False) -> Dict:
    trend = "stable"
    if delta is not None:
        if delta > 0.05:
            trend = "rising"
        elif delta < -0.05:
            trend = "falling"
    out: Dict = {
        "usdt_dominance": round(usdt, 2),
        "usdc_dominance": round(usdc, 2),
        "dai_dominance": round(dai, 2),
        "total_stablecoin_dominance": total_dom,
        "change": delta,
        "change_source": change_source,
        "trend": trend,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "timeframe": timeframe,
        "source": source,
    }
    if fallback:
        out["_fallback"] = True
    return out


def get_stablecoin_data(timeframe: str = "current") -> Dict:
    """Stablecoin dominance from CoinGecko global → CoinLore → snapshot.

    Change uses stored snapshots first; falls back to CoinGecko BTC+ETH
    market-cap-based total-market estimation so the first run can compute a delta.
    """
    payload = _get_global_market_payload()
    if payload:
        market_cap_data = payload.get("market_cap_percentage") or {}
        usdt_dom = float(market_cap_data.get("usdt") or 0)
        usdc_dom = float(market_cap_data.get("usdc") or 0)
        dai_dom = float(market_cap_data.get("dai") or 0)

        market_caps_dom = _cg_stablecoin_dominance_from_markets()
        source = "CoinGecko"
        if market_caps_dom:
            if usdt_dom <= 0:
                usdt_dom = market_caps_dom["usdt_dominance"]
            if usdc_dom <= 0:
                usdc_dom = market_caps_dom["usdc_dominance"]
            if dai_dom <= 0:
                dai_dom = market_caps_dom["dai_dominance"]
            source = "CoinGecko:global+markets"

        total_stable_dom = usdt_dom + usdc_dom + dai_dom
        if total_stable_dom > 0:
            total_stable_dom = round(total_stable_dom, 2)
            delta = _estimate_dominance_change(total_stable_dom, "stablecoin_dominance", timeframe)
            cs = "snapshot_history" if _snapshot_series_change("stablecoin_dominance", total_stable_dom, timeframe) is not None else "cg_market_chart" if delta is not None else None
            return _stablecoin_result(usdt_dom, usdc_dom, dai_dom, total_stable_dom, delta, timeframe, source, cs)

    coinlore_global = _coinlore_global_market_payload()
    coinlore_tickers = _coinlore_top_tickers()
    total_mcap = _safe_float((coinlore_global or {}).get("total_mcap"))
    if total_mcap:
        stable_caps: Dict[str, float] = {}
        for row in coinlore_tickers:
            symbol = str(row.get("symbol") or "").upper()
            if symbol not in STABLECOIN_SYMBOLS:
                continue
            mcap = _safe_float(row.get("market_cap_usd"))
            if mcap is None or mcap <= 0:
                continue
            stable_caps[symbol] = mcap
        total_stable_mcap = sum(stable_caps.values())
        if total_stable_mcap > 0:
            usdt_dom = stable_caps.get("USDT", 0.0) / total_mcap * 100.0
            usdc_dom = stable_caps.get("USDC", 0.0) / total_mcap * 100.0
            dai_dom = stable_caps.get("DAI", 0.0) / total_mcap * 100.0
            total_stable_dom = round(total_stable_mcap / total_mcap * 100.0, 2)
            delta = _estimate_dominance_change(total_stable_dom, "stablecoin_dominance", timeframe)
            cs = "snapshot_history" if _snapshot_series_change("stablecoin_dominance", total_stable_dom, timeframe) is not None else "cg_market_chart" if delta is not None else None
            return _stablecoin_result(usdt_dom, usdc_dom, dai_dom, total_stable_dom, delta, timeframe, "CoinLore", cs, fallback=True)

    snap = _snapshot_stable_dom()
    if snap is not None:
        logger.warning("Stablecoin dominance: using last snapshot total=%.2f%%", snap)
        return {
            "usdt_dominance": None, "usdc_dominance": None, "dai_dominance": None,
            "total_stablecoin_dominance": round(snap, 2),
            "change": None, "change_source": None, "trend": "stable",
            "date": datetime.now().strftime("%Y-%m-%d"),
            "timeframe": timeframe, "_fallback": True, "source": "last_snapshot",
        }
    return {"error": "Stablecoin dominance unavailable", "timeframe": timeframe}


def get_eth_btc_ratio(timeframe: str = "current") -> Dict:
    """Get ETH/BTC ratio"""
    try:
        data = _cg_fetch_simple_macro()
        if not data:
            raise RuntimeError("simple/price macro bundle empty")
        eth_price = data.get("ethereum", {}).get("usd", 0)
        btc_price = data.get("bitcoin", {}).get("usd", 0)
        
        if btc_price and float(btc_price) > 0:
            ratio = float(eth_price) / float(btc_price)
            return {
                "eth_btc_ratio": round(ratio, 6),
                "eth_price": eth_price,
                "btc_price": btc_price,
                "date": datetime.now().strftime("%Y-%m-%d"),
                "timeframe": timeframe,
            }
    except Exception as e:
        logger.warning("CoinGecko ETH/BTC ratio failed: %s", e)

    try:
        import yfinance as yf
        eth = yf.Ticker("ETH-USD").history(period="5d")
        btc = yf.Ticker("BTC-USD").history(period="5d")
        if not eth.empty and not btc.empty:
            ep = float(eth["Close"].iloc[-1])
            bp = float(btc["Close"].iloc[-1])
            if bp > 0:
                return {
                    "eth_btc_ratio": round(ep / bp, 6),
                    "eth_price": round(ep, 2),
                    "btc_price": round(bp, 2),
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "timeframe": timeframe,
                    "_fallback": True,
                    "source": "yahoo_eth_btc",
                }
    except Exception as e2:
        logger.warning("Yahoo ETH/BTC fallback failed: %s", e2)

    return {"error": "ETH/BTC ratio unavailable", "timeframe": timeframe}


def get_btc_ohlcv_200d() -> Dict:
    """Fetch the real BTC 200-day MA and 30-day realized vol from free sources."""

    def _technicals_from_closes(closes: List[float], source: str, *, fallback: bool = False) -> Dict:
        if len(closes) < 200:
            return {"error": "Insufficient BTC close history"}
        tail200 = closes[-200:]
        ma200 = float(sum(tail200) / len(tail200))
        recent = closes[-31:] if len(closes) >= 31 else closes
        realized_vol_30d = None
        if len(recent) >= 2:
            log_returns = [math.log(recent[i] / recent[i - 1]) for i in range(1, len(recent))]
            mean_r = sum(log_returns) / len(log_returns)
            variance = sum((r - mean_r) ** 2 for r in log_returns) / len(log_returns)
            realized_vol_30d = round(math.sqrt(variance) * math.sqrt(365), 4)
        result = {
            "ma200": round(ma200, 2),
            "days_of_data": len(closes),
            "realized_vol_30d": realized_vol_30d,
            "source": source,
        }
        if fallback:
            result["_fallback"] = True
        return result

    try:
        closes = _coinbase_btc_daily_closes(limit=400)
        if len(closes) >= 200:
            return _technicals_from_closes(closes, "coinbase_exchange", fallback=True)
    except Exception as e:
        logger.warning("Coinbase BTC technicals fallback failed: %s", e)

    try:
        closes = _kraken_btc_daily_closes(limit=400)
        if len(closes) >= 200:
            return _technicals_from_closes(closes, "kraken_public", fallback=True)
    except Exception as e:
        logger.warning("Kraken BTC technicals fallback failed: %s", e)

    try:
        from data_fetchers import yahoo_data

        yb = yahoo_data.get_btc_ma200_vol_from_yahoo()
        if yb and not yb.get("error") and (yb.get("days_of_data") or 0) >= 200:
            yb["source"] = "yahoo_btc_usd"
            return yb
    except Exception as e:
        logger.warning("Yahoo BTC MA/vol fetch failed: %s", e)

    try:
        response = requests.get(
            "https://api.binance.com/api/v3/klines",
            params={"symbol": "BTCUSDT", "interval": "1d", "limit": 400},
            timeout=20,
            headers=_CG_HEADERS,
        )
        response.raise_for_status()
        klines = response.json()
        closes = [_safe_float(row[4]) for row in klines]
        close_series = [c for c in closes if c is not None and c > 0]
        if len(close_series) >= 200:
            return _technicals_from_closes(close_series, "binance_public", fallback=True)
    except Exception as e:
        logger.warning("Binance BTC technicals fallback failed: %s", e)

    try:
        response = _cg_get(
            f"{COINGECKO_BASE_URL}/coins/bitcoin/market_chart",
            params={"vs_currency": "usd", "days": 365},
            timeout=22,
            retries_on_429=2,
            max_wait_on_429=10.0,
        )
        response.raise_for_status()
        prices = response.json().get("prices", [])
        by_day: Dict[str, float] = {}
        for ts, px in prices:
            close = _safe_float(px)
            if close is None or close <= 0:
                continue
            day = datetime.utcfromtimestamp(ts / 1000.0).strftime("%Y-%m-%d")
            by_day[day] = close
        close_series = [by_day[k] for k in sorted(by_day.keys())]
        if len(close_series) >= 200:
            return _technicals_from_closes(close_series, "coingecko_market_chart", fallback=True)
    except Exception as e:
        logger.warning("CoinGecko BTC market_chart fallback failed: %s", e)

    return {
        "ma200": None,
        "days_of_data": 0,
        "realized_vol_30d": None,
        "_fallback": True,
        "source": "unavailable",
    }


def get_crypto_summary(timeframe: str = "current") -> Dict:
    """Get comprehensive crypto market summary with timeframe support"""
    return {
        "btc": get_btc_price(timeframe),
        "btc_dominance": get_btc_dominance(timeframe),
        "stablecoins": get_stablecoin_data(timeframe),
        "eth_btc_ratio": get_eth_btc_ratio(timeframe),
        "timeframe": timeframe
    }
