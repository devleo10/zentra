"""
Fetch cryptocurrency data from CoinGecko API
"""
import logging
import math
import requests
from typing import Dict, Optional
from datetime import datetime, timedelta

logger = logging.getLogger("btc_macro.data_fetchers.coingecko")

COINGECKO_BASE_URL = "https://api.coingecko.com/api/v3"

_CG_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ZentraMacro/1.0)",
    "Accept": "application/json",
}


def _cg_get(url: str, *, timeout: float = 15, params=None):
    return requests.get(url, params=params, timeout=timeout, headers=_CG_HEADERS)


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
    """Return (usdt_dom, usdc_dom, total_dom) from last snapshot if present."""
    try:
        from storage.db import get_latest_snapshots
        rows = get_latest_snapshots(1)
        if not rows:
            return None
        r = rows[0]
        t = r.get("stablecoin_dominance")
        if t is None:
            return None
        total = float(t)
        half = round(total / 2.0, 2)
        return half, half, total
    except Exception:
        logger.debug("snapshot stablecoin read failed", exc_info=True)
    return None

# Timeframe to days mapping for historical data
TIMEFRAME_DAYS = {
    "current": 1,
    "week": 7,
    "month": 30,
    "year": 365
}


def get_btc_price(timeframe: str = "current") -> Dict:
    """Get Bitcoin price data with timeframe support"""
    url = f"{COINGECKO_BASE_URL}/simple/price"
    params = {
        "ids": "bitcoin",
        "vs_currencies": "usd",
        "include_24hr_change": "true",
        "include_7d_change": "true"
    }
    
    try:
        response = _cg_get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
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
        month_start = latest_dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        month_start_ms = int(month_start.timestamp() * 1000)
        month_first_close = None
        for row in kl:
            if int(row[0]) >= month_start_ms:
                month_first_close = _close(row)
                break
        if month_first_close is None:
            month_first_close = _close(kl[0])

        change_mtd = _pct(month_first_close, last_close)

        if timeframe == "current":
            ch = change_24h
        elif timeframe == "week":
            ch = change_7d
        else:
            ch = change_mtd

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


def get_btc_dominance(timeframe: str = "current") -> Dict:
    """Get Bitcoin market dominance (CoinGecko → snapshot → neutral estimate)."""
    url = f"{COINGECKO_BASE_URL}/global"
    today = datetime.now().strftime("%Y-%m-%d")
    for timeout in (12, 22):
        try:
            response = _cg_get(url, timeout=timeout)
            response.raise_for_status()
            data = response.json()
            market_cap_data = data.get("data", {}).get("market_cap_percentage", {})
            btc_dominance = market_cap_data.get("btc")
            if btc_dominance is not None and float(btc_dominance) > 0:
                return {
                    "btc_dominance": round(float(btc_dominance), 2),
                    "date": today,
                    "timeframe": timeframe,
                }
        except Exception as e:
            logger.warning("CoinGecko global (BTC dom) failed (timeout=%s): %s", timeout, e)
    snap = _snapshot_btc_dominance()
    if snap is not None:
        logger.warning("BTC dominance: using last snapshot %.2f%%", snap)
        return {
            "btc_dominance": round(snap, 2),
            "date": today,
            "timeframe": timeframe,
            "_fallback": True,
            "source": "last_snapshot",
        }
    logger.warning("BTC dominance: using neutral estimate 52%%")
    return {
        "btc_dominance": 52.0,
        "date": today,
        "timeframe": timeframe,
        "_fallback": True,
        "source": "neutral_estimate",
    }


def get_stablecoin_data(timeframe: str = "current") -> Dict:
    """Stablecoin dominance from CoinGecko global → snapshot → neutral estimate."""
    url = f"{COINGECKO_BASE_URL}/global"
    today = datetime.now().strftime("%Y-%m-%d")
    for timeout in (12, 22):
        try:
            response = _cg_get(url, timeout=timeout)
            response.raise_for_status()
            data = response.json()
            market_cap_data = data.get("data", {}).get("market_cap_percentage", {})
            usdt_dom = float(market_cap_data.get("usdt") or 0)
            usdc_dom = float(market_cap_data.get("usdc") or 0)
            total_stable_dom = usdt_dom + usdc_dom
            if total_stable_dom > 0:
                return {
                    "usdt_dominance": round(usdt_dom, 2),
                    "usdc_dominance": round(usdc_dom, 2),
                    "total_stablecoin_dominance": round(total_stable_dom, 2),
                    "date": today,
                    "timeframe": timeframe,
                }
        except Exception as e:
            logger.warning("CoinGecko global (stables) failed (timeout=%s): %s", timeout, e)
    snap = _snapshot_stable_dom()
    if snap:
        u, v, t = snap
        logger.warning("Stablecoin dominance: using last snapshot total=%.2f%%", t)
        return {
            "usdt_dominance": u,
            "usdc_dominance": v,
            "total_stablecoin_dominance": round(t, 2),
            "date": today,
            "timeframe": timeframe,
            "_fallback": True,
            "source": "last_snapshot",
        }
    logger.warning("Stablecoin dominance: using neutral estimate")
    return {
        "usdt_dominance": 4.25,
        "usdc_dominance": 4.25,
        "total_stablecoin_dominance": 8.5,
        "date": today,
        "timeframe": timeframe,
        "_fallback": True,
        "source": "neutral_estimate",
    }


def get_eth_btc_ratio(timeframe: str = "current") -> Dict:
    """Get ETH/BTC ratio"""
    url = f"{COINGECKO_BASE_URL}/simple/price"
    params = {
        "ids": "ethereum,bitcoin",
        "vs_currencies": "usd"
    }
    
    try:
        response = _cg_get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
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
    """Fetch 200 days of BTC daily OHLCV data from CoinGecko.

    Returns the real 200-day moving average and 30-day annualized realized volatility.
    CoinGecko OHLC endpoint returns [timestamp, open, high, low, close] candles.
    """
    url = f"{COINGECKO_BASE_URL}/coins/bitcoin/ohlc"
    params = {
        "vs_currency": "usd",
        "days": 200,
    }
    try:
        response = _cg_get(url, params=params, timeout=22)
        response.raise_for_status()
        candles = response.json()

        if candles and len(candles) >= 30:
            close_prices = [c[4] for c in candles]
            ma200 = sum(close_prices) / len(close_prices)
            recent = close_prices[-31:] if len(close_prices) >= 31 else close_prices
            realized_vol_30d = None
            if len(recent) >= 2:
                log_returns = [
                    math.log(recent[i] / recent[i - 1])
                    for i in range(1, len(recent))
                ]
                mean_r = sum(log_returns) / len(log_returns)
                variance = sum((r - mean_r) ** 2 for r in log_returns) / len(log_returns)
                realized_vol_30d = round(math.sqrt(variance) * math.sqrt(365), 4)
            return {
                "ma200": round(ma200, 2),
                "days_of_data": len(close_prices),
                "realized_vol_30d": realized_vol_30d,
            }
    except Exception as e:
        logger.warning("CoinGecko BTC OHLC failed: %s", e)

    try:
        from data_fetchers import yahoo_data
        yb = yahoo_data.get_btc_ma200_vol_from_yahoo()
        if yb and not yb.get("error"):
            yb["_fallback"] = True
            yb["source"] = "yahoo_btc_usd"
            logger.warning("BTC MA200/vol: using Yahoo BTC-USD fallback")
            return yb
    except Exception as e:
        logger.warning("Yahoo BTC MA/vol fallback failed: %s", e)

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


