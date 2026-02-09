"""
Fetch cryptocurrency data from CoinGecko API
"""
import requests
from typing import Dict, Optional
from datetime import datetime


COINGECKO_BASE_URL = "https://api.coingecko.com/api/v3"


def get_btc_price() -> Dict:
    """Get Bitcoin current price and basic data"""
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
        
        return {
            "price_usd": btc_data.get("usd", 0),
            "change_24h": round(btc_data.get("usd_24h_change", 0), 2),
            "change_7d": round(btc_data.get("usd_7d_change", 0), 2),
            "date": datetime.now().strftime("%Y-%m-%d")
        }
    except Exception as e:
        return {"error": str(e)}


def get_btc_dominance() -> Dict:
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
            "date": datetime.now().strftime("%Y-%m-%d")
        }
    except Exception as e:
        return {"error": str(e)}


def get_stablecoin_data() -> Dict:
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
            "date": datetime.now().strftime("%Y-%m-%d")
        }
    except Exception as e:
        return {"error": str(e)}


def get_eth_btc_ratio() -> Dict:
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
                "date": datetime.now().strftime("%Y-%m-%d")
            }
        else:
            return {"error": "Invalid price data"}
    except Exception as e:
        return {"error": str(e)}


def get_crypto_summary() -> Dict:
    """Get comprehensive crypto market summary"""
    return {
        "btc": get_btc_price(),
        "btc_dominance": get_btc_dominance(),
        "stablecoins": get_stablecoin_data(),
        "eth_btc_ratio": get_eth_btc_ratio()
    }

