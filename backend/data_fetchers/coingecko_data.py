"""
Fetch cryptocurrency data from CoinGecko API
"""
import math
import requests
from typing import Dict, Optional
from datetime import datetime, timedelta


COINGECKO_BASE_URL = "https://api.coingecko.com/api/v3"

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
        response = requests.get(url, params=params, timeout=10)
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
        response = requests.get(url, params=params, timeout=10)
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


def get_btc_dominance(timeframe: str = "current") -> Dict:
    """Get Bitcoin market dominance"""
    url = f"{COINGECKO_BASE_URL}/global"
    
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        market_cap_data = data.get("data", {}).get("market_cap_percentage", {})
        btc_dominance = market_cap_data.get("btc", 0)
        
        return {
            "btc_dominance": round(btc_dominance, 2),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "timeframe": timeframe
        }
    except Exception as e:
        return {"error": str(e), "timeframe": timeframe}


def get_stablecoin_data(timeframe: str = "current") -> Dict:
    """Get stablecoin market cap data"""
    url = f"{COINGECKO_BASE_URL}/global"
    
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        market_cap_data = data.get("data", {}).get("market_cap_percentage", {})
        
        # Get USDT and USDC dominance
        usdt_dom = market_cap_data.get("usdt", 0)
        usdc_dom = market_cap_data.get("usdc", 0)
        total_stable_dom = usdt_dom + usdc_dom
        
        return {
            "usdt_dominance": round(usdt_dom, 2),
            "usdc_dominance": round(usdc_dom, 2),
            "total_stablecoin_dominance": round(total_stable_dom, 2),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "timeframe": timeframe
        }
    except Exception as e:
        return {"error": str(e), "timeframe": timeframe}


def get_eth_btc_ratio(timeframe: str = "current") -> Dict:
    """Get ETH/BTC ratio"""
    url = f"{COINGECKO_BASE_URL}/simple/price"
    params = {
        "ids": "ethereum,bitcoin",
        "vs_currencies": "usd"
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        eth_price = data.get("ethereum", {}).get("usd", 0)
        btc_price = data.get("bitcoin", {}).get("usd", 0)
        
        if btc_price > 0:
            ratio = eth_price / btc_price
            return {
                "eth_btc_ratio": round(ratio, 6),
                "eth_price": eth_price,
                "btc_price": btc_price,
                "date": datetime.now().strftime("%Y-%m-%d"),
                "timeframe": timeframe
            }
        else:
            return {"error": "Invalid price data", "timeframe": timeframe}
    except Exception as e:
        return {"error": str(e), "timeframe": timeframe}


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
        response = requests.get(url, params=params, timeout=20)
        response.raise_for_status()
        candles = response.json()

        if not candles or len(candles) < 30:
            return {"error": "Insufficient OHLCV data from CoinGecko"}

        close_prices = [c[4] for c in candles]

        # 200-day simple moving average of all available close prices
        ma200 = sum(close_prices) / len(close_prices)

        # 30-day annualized realized volatility from the most recent 31 closes
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
        return {"error": str(e)}


def get_crypto_summary(timeframe: str = "current") -> Dict:
    """Get comprehensive crypto market summary with timeframe support"""
    return {
        "btc": get_btc_price(timeframe),
        "btc_dominance": get_btc_dominance(timeframe),
        "stablecoins": get_stablecoin_data(timeframe),
        "eth_btc_ratio": get_eth_btc_ratio(timeframe),
        "timeframe": timeframe
    }


