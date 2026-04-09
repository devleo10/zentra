"""
run_analysis.py — Main entry point for deterministic BTC macro analysis.

Designed to be executed manually, twice per day.
Runs locally. No cloud assumptions. No streaming. No auto-trading.

Pipeline:
    1. Fetch all numeric macro data
    2. Validate data freshness (refuse if critical data missing)
    3. Compute deterministic numeric scores (zero LLM)
    4. Fetch macro headlines (last 48h)
    5. Classify headlines via LLM (temperature=0, strict JSON)
    6. Compute headline adjustment (capped ±10)
    7. Compute final verdict (deterministic formula)
    8. Store snapshot to local SQLite
    9. Print result

Exit codes:
    0 — Success
    1 — Critical data missing / stale
    2 — Unrecoverable API failure
    3 — Configuration error
"""
import sys
import json
import math
import hashlib
import logging
import os
from datetime import datetime
from pathlib import Path

# ── Logging setup ──────────────────────────────────────────────────────────
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / f"analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("btc_macro")

# ── Imports ────────────────────────────────────────────────────────────────
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

from data_fetchers import fred_data, yahoo_data, coingecko_data, news_data
from scoring_engine.numeric_scorer import (
    score_inflation, score_fed_policy, score_liquidity,
    score_dxy, score_risk_sentiment, score_economy,
    compute_weighted_total_with_freshness,
)
from scoring_engine.coherence import compute_coherence_adjustment
from scoring_engine.headline_adjuster import compute_headline_adjustment
from scoring_engine.cross_signal_reviewer import review_cross_signals
from scoring_engine.narrative_generator import generate_narrative
from scoring_engine.verdict import compute_final_verdict
from scoring_engine.freshness import validate_data_freshness
from scoring_engine.signal_quality import detect_regime, evaluate_signal_quality, apply_weight_multipliers
from scoring_engine.config_loader import get_scoring_config
from headline_engine.fetcher import HeadlineFetcher, HeadlineFetchError
from headline_engine.classifier import HeadlineClassifier
from headline_engine.report import generate_market_report
from storage.db import save_snapshot
from storage.metric_cache import clear_cached_metric, get_cached_metric, put_cached_metric


_GEO_KEYWORDS = {
    "war", "iran", "israel", "ukraine", "russia", "middle east",
    "sanctions", "tariff", "tariffs", "trade war", "strait of hormuz",
    "ceasefire", "nato", "missile", "troops", "invasion",
}

# Only these explicit Fed/monetary decision tags get the 0.98 classifier confidence boost.
MONETARY_EXPLICIT_CONFIDENCE_BOOST_TYPES = frozenset(
    ("rate_hike", "rate_cut", "rate_hold", "fomc_doc")
)

STRICT_LIVE_OFFICIAL_ONLY = os.getenv("STRICT_LIVE_OFFICIAL_ONLY", "0").strip().lower() not in {"0", "false", "no"}

_STRICT_METRIC_LABELS = {
    "cpi": "CPI",
    "pce": "PCE",
    "yields": "Treasury Yields",
    "balance_sheet": "Fed Balance Sheet",
    "dxy": "DXY",
    "vix": "VIX",
    "sp500": "S&P 500",
    "gold": "Gold",
    "oil": "WTI Oil",
    "btc": "BTC Price",
    "fed_rate": "Fed Funds Rate",
    "jobs": "Jobs",
    "gdp": "GDP",
    "pmi": "PMI",
    "m2": "M2 Money Supply",
    "natgas": "Natural Gas",
    "move_index": "MOVE",
    "eem": "EEM",
    "btc_dominance": "BTC Dominance",
    "stablecoins": "Stablecoin Dominance",
    "btc_technicals": "BTC Technicals",
    "btc_etf": "BTC ETF Volume",
    "dxy_structure": "DXY Structure",
    "financial_stress": "Financial Stress",
    "breakeven_10y": "10Y Breakeven",
}

_STRICT_UNSUPPORTED_METRICS = set()

_STRICT_FRED_ONLY_METRICS = {"vix", "sp500", "natgas", "oil"}
_STRICT_OFFICIAL_METRICS = {
    "cpi",
    "pce",
    "yields",
    "balance_sheet",
    "fed_rate",
    "jobs",
    "gdp",
    "pmi",
    "m2",
    "financial_stress",
    "breakeven_10y",
}

_MONTHLY_METRIC_CACHE_ENABLED = os.getenv("ENABLE_MONTHLY_METRIC_CACHE", "1").strip().lower() not in {
    "0",
    "false",
    "no",
}
try:
    _MONTHLY_SLOW_METRIC_CACHE_TTL_SECONDS = max(
        60,
        int((os.getenv("MONTHLY_SLOW_METRIC_CACHE_TTL_SECONDS") or str(12 * 3600)).strip()),
    )
except ValueError:
    _MONTHLY_SLOW_METRIC_CACHE_TTL_SECONDS = 12 * 3600

_MONTHLY_SLOW_METRIC_KEYS = {
    "cpi",
    "pce",
    "yields",
    "balance_sheet",
    "fed_rate",
    "jobs",
    "gdp",
    "pmi",
    "m2",
    "financial_stress",
    "breakeven_10y",
}


def _safe_log_text(text: str) -> str:
    """Return text that is safe to emit on non-UTF8 consoles (e.g., Windows cp1252)."""
    if text is None:
        return ""
    # ASCII with replacement is universally safe for console/file handlers.
    return str(text).encode("ascii", errors="replace").decode("ascii")


def _log_trusted_provider_key_status() -> None:
    """Log trusted market provider credential availability without leaking values."""
    fmp_set = bool((os.getenv("FMP_API_KEY") or "").strip())
    eodhd_set = bool((os.getenv("EODHD_API_TOKEN") or "").strip())
    te_raw = (os.getenv("TRADINGECONOMICS_API_KEY") or "").strip()
    te_mode = "set" if te_raw else "guest"

    logger.info(
        "Trusted API credentials: FMP=%s EODHD=%s TradingEconomics=%s",
        "set" if fmp_set else "missing",
        "set" if eodhd_set else "missing",
        te_mode,
    )


def _compute_geopolitics_risk(classified_headlines: list) -> str:
    """Derive geopolitics risk level from classified headlines."""
    geo_count = 0
    geo_risk_off = 0
    for c in classified_headlines:
        title = (c.get("_headline_title", "") or c.get("reason", "")).lower()
        if any(kw in title for kw in _GEO_KEYWORDS):
            geo_count += 1
            if c.get("risk_impact") == "risk_off":
                geo_risk_off += 1
    if geo_risk_off >= 2:
        return "high"
    if geo_count >= 3:
        return "elevated"
    if geo_count >= 1:
        return "moderate"
    return "low"


def _config_hash() -> str:
    """SHA-256 of the scoring config for reproducibility tracking."""
    config_path = Path(__file__).parent / "config" / "scoring_weights.json"
    content = config_path.read_bytes()
    return hashlib.sha256(content).hexdigest()[:16]


def _stamp_batch_fetched_at(raw_data: dict) -> None:
    """
    Mark when numeric payloads were retrieved. Freshness uses this for macro series
    (avoids false STALE when observation dates are month/quarter starts).
    """
    ts = datetime.now().isoformat()
    for val in raw_data.values():
        if isinstance(val, dict) and "error" not in val:
            val.setdefault("fetched_at", ts)


def _warn_if_delayed(name: str, blob: dict, tolerance_minutes: int = 60) -> None:
    """Warn when observation time lags fetch time beyond tolerance."""
    if not isinstance(blob, dict):
        return
    obs = blob.get("observed_at") or blob.get("data_as_of")
    fetched = blob.get("fetched_at")
    if not obs or not fetched:
        return
    try:
        obs_dt = datetime.fromisoformat(str(obs).replace("Z", "+00:00"))
        fetched_dt = datetime.fromisoformat(str(fetched).replace("Z", "+00:00"))
        delay = fetched_dt - obs_dt
        if delay.total_seconds() > tolerance_minutes * 60:
            logger.warning(
                "  %s observation delayed: obs=%s fetched=%s delay=%s",
                name,
                obs_dt.isoformat(),
                fetched_dt.isoformat(),
                delay,
            )
    except Exception:
        return


def _dxy_needs_repair(dxy: dict) -> bool:
    """True when primary DXY payload is missing a usable level (UI/API hide the metric)."""
    if not dxy:
        return True
    if dxy.get("error"):
        return True
    cp = dxy.get("current_price")
    if cp is None:
        return True
    try:
        f = float(cp)
        if not math.isfinite(f) or f <= 0:
            return True
    except (TypeError, ValueError):
        return True
    return False


def _dxy_api_fields(dxy_blob: dict):
    """Snapshot/API dxy_value and dxy_change; avoid emitting 0% change when the fetch actually failed."""
    if not dxy_blob:
        return None, None
    err = dxy_blob.get("error")
    val = None
    chg = None
    try:
        cp = dxy_blob.get("current_price")
        if cp is not None:
            f = float(cp)
            if math.isfinite(f) and f > 0:
                val = f
    except (TypeError, ValueError):
        pass
    try:
        c = dxy_blob.get("change")
        if c is not None:
            f = float(c)
            if math.isfinite(f):
                chg = f
    except (TypeError, ValueError):
        pass
    if err and val is None:
        chg = None
    return val, chg


def _source_text(blob: dict) -> str:
    return str((blob or {}).get("source") or (blob or {}).get("_source") or "").strip()


def _detail_from_error(err: str) -> str:
    text = str(err or "").strip()
    low = text.lower()
    if any(tok in low for tok in ("429", "rate limit", "too many requests", "upgrade required")):
        return "live source rate-limited"
    if any(tok in low for tok in ("proxyerror", "failed to connect", "max retries exceeded", "could not connect", "unable to connect")):
        return "live source unreachable"
    if "api key" in low or "missing_api_key" in low:
        return "missing API key for live source"
    if text:
        return text
    return "live source unavailable"


def _is_source_official(metric_key: str, blob: dict) -> bool:
    if metric_key in _STRICT_UNSUPPORTED_METRICS:
        return False
    source = _source_text(blob)
    if metric_key == "pmi":
        return source.startswith(
            (
                "FRED",
                "AlphaVantage:ISM_MANUFACTURING",
                "TradingView:ECONOMICS:USPMI",
                "ISM:",
                "TradingEconomics:",
                "EODHD:",
                "Investing:",
            )
        )
    if metric_key == "move_index":
        return source.startswith(("^MOVE", "MOVE", "TradingView:INDEX:MOVE", "FRED:BAMLH0A0HYM2", "FMP:", "EODHD:", "CBOE:TYVIX"))
    if metric_key == "vix":
        return source.startswith(("^VIX", "VIX", "FRED:VIXCLS", "FMP:", "TradingEconomics:", "EODHD:"))
    if metric_key == "sp500":
        return source.startswith(("^GSPC", "FRED:SP500", "FMP:", "TradingEconomics:", "EODHD:"))
    if metric_key == "eem":
        return source in {"EEM", "VWO"} or source.startswith(("FMP:", "EODHD:"))
    if metric_key == "btc_dominance":
        return source.startswith(("CoinGecko", "CoinLore"))
    if metric_key == "stablecoins":
        return source.startswith(("CoinGecko", "CoinLore"))
    if metric_key == "btc_etf":
        return source.startswith(("Yahoo Finance", "FMP:"))
    if metric_key == "dxy":
        return source.startswith(("ECB:", "Federal Reserve", "FRED:DTWEXBGS"))
    if metric_key == "dxy_structure":
        return source.startswith("ECB:")
    if metric_key == "gold":
        return source.startswith(("LBMA:", "FRED:"))
    if metric_key == "btc":
        return source in {"coinbase_exchange", "kraken_public", "binance_public"}
    if metric_key == "btc_technicals":
        return source in {"coinbase_exchange", "kraken_public", "binance_public"}
    if metric_key in _STRICT_OFFICIAL_METRICS:
        return not source or source.startswith(("BLS", "BEA", "FRED", "Federal Reserve")) or "FRED" in source
    if metric_key in _STRICT_FRED_ONLY_METRICS:
        return "FRED" in source
    return False


def _apply_strict_live_official_policy(raw_data: dict, timeframe: str) -> list[str]:
    if not STRICT_LIVE_OFFICIAL_ONLY:
        return []

    warnings: list[str] = []
    for metric_key, label in _STRICT_METRIC_LABELS.items():
        blob = raw_data.get(metric_key)
        if not isinstance(blob, dict):
            continue

        source = _source_text(blob)
        if blob.get("error"):
            detail = _detail_from_error(blob.get("error"))
            warnings.append(f"{label}: {detail}.")
            continue

        if source == "last_snapshot" or blob.get("_fallback_source") == "last_snapshot":
            detail = "snapshot fallback disabled in live official mode"
        elif blob.get("_proxy_note"):
            detail = "proxy data disabled in live official mode"
        elif not _is_source_official(metric_key, blob):
            detail = "no official live source configured for this metric"
        else:
            continue

        raw_data[metric_key] = {
            "error": detail,
            "source": source or None,
            "timeframe": timeframe,
        }
        warnings.append(f"{label}: {detail}.")

    return warnings


def _load_monthly_slow_metric_cache(timeframe: str, fresh: bool) -> dict:
    if timeframe != "month" or fresh or not _MONTHLY_METRIC_CACHE_ENABLED:
        return {}
    cached: dict = {}
    for metric_key in sorted(_MONTHLY_SLOW_METRIC_KEYS):
        payload = get_cached_metric(
            metric_key,
            timeframe,
            max_age_seconds=_MONTHLY_SLOW_METRIC_CACHE_TTL_SECONDS,
        )
        if isinstance(payload, dict):
            cached[metric_key] = payload
    return cached


def _store_monthly_slow_metric(metric_key: str, timeframe: str, payload: dict) -> None:
    if timeframe != "month" or not _MONTHLY_METRIC_CACHE_ENABLED:
        return
    if metric_key not in _MONTHLY_SLOW_METRIC_KEYS:
        return
    if not isinstance(payload, dict) or payload.get("error"):
        return
    put_cached_metric(metric_key, timeframe, payload)


def run_analysis(timeframe: str = "current", fresh: bool = False):
    """
    Execute the full analysis pipeline with timeframe support.
    
    Args:
        timeframe: Analysis timeframe - 'current', 'week', or 'month'
        fresh: If True, clear cached news/LLM intermediates before running.
               Default False still uses cache for headline/Fed-tone/LLM
               steps, but live market prices are always fetched fresh.
    
    Returns the result dict on success, or raises SystemExit on failure.
    """
    if fresh:
        from data_fetchers.cache import clear as cache_clear
        cache_clear()
        logger.info("Cache cleared (--fresh mode)")
        if timeframe == "month" and _MONTHLY_METRIC_CACHE_ENABLED:
            clear_cached_metric(timeframe="month")
            logger.info("Persistent monthly cache cleared (--fresh mode)")

    timestamp = datetime.now().isoformat()
    logger.info("=" * 70)
    logger.info(f"BTC MACRO ANALYSIS - {timestamp} (timeframe: {timeframe})")
    logger.info("=" * 70)
    _log_trusted_provider_key_status()

    # ── STEP 1: Fetch all numeric data ─────────────────────────────────
    logger.info("[1/9] Fetching numeric macro data...")
    raw_data = {}

    month_cache_hits = _load_monthly_slow_metric_cache(timeframe, fresh)
    if month_cache_hits:
        raw_data.update(month_cache_hits)
        logger.info(
            "  Monthly macro cache HIT (ttl=%ss): %s",
            _MONTHLY_SLOW_METRIC_CACHE_TTL_SECONDS,
            ", ".join(sorted(month_cache_hits.keys())),
        )
    
    _cpi_from_cache = "cpi" in raw_data
    if _cpi_from_cache:
        if raw_data["cpi"].get("cpi_mom_avg_3m_prior") is None or raw_data["cpi"].get("core_cpi_mom_avg_3m_prior") is None:
            logger.info("  CPI cache missing prior averages — re-fetching fresh")
            _cpi_from_cache = False
            raw_data.pop("cpi", None)
    if _cpi_from_cache:
        logger.info(f"  CPI (cache): {raw_data['cpi'].get('latest_value', 'ERROR')}")
    else:
        try:
            raw_data["cpi"] = fred_data.get_cpi_data(timeframe)
            _store_monthly_slow_metric("cpi", timeframe, raw_data["cpi"])
            logger.info(f"  CPI: {raw_data['cpi'].get('latest_value', 'ERROR')}")
        except Exception as e:
            logger.error(f"  CPI fetch FAILED: {e}")
            raw_data["cpi"] = {"error": str(e)}
    
    if "pce" in raw_data:
        logger.info(f"  PCE (cache): {raw_data['pce'].get('latest_value', 'ERROR')}")
    else:
        try:
            raw_data["pce"] = fred_data.get_pce_data(timeframe)
            _store_monthly_slow_metric("pce", timeframe, raw_data["pce"])
            logger.info(f"  PCE: {raw_data['pce'].get('latest_value', 'ERROR')}")
        except Exception as e:
            logger.error(f"  PCE fetch FAILED: {e}")
            raw_data["pce"] = {"error": str(e)}
    
    if "yields" in raw_data:
        logger.info(f"  10Y Yield (cache): {raw_data['yields'].get('yield_10y', {}).get('value', 'ERROR')}")
    else:
        try:
            raw_data["yields"] = fred_data.get_treasury_yields(timeframe)
            _store_monthly_slow_metric("yields", timeframe, raw_data["yields"])
            logger.info(f"  10Y Yield: {raw_data['yields'].get('yield_10y', {}).get('value', 'ERROR')}")
        except Exception as e:
            logger.error(f"  Yields fetch FAILED: {e}")
            raw_data["yields"] = {"error": str(e)}
    
    if "balance_sheet" in raw_data:
        logger.info(f"  Fed BS trend (cache): {raw_data['balance_sheet'].get('trend', 'ERROR')}")
    else:
        try:
            raw_data["balance_sheet"] = fred_data.get_fed_balance_sheet(timeframe)
            _store_monthly_slow_metric("balance_sheet", timeframe, raw_data["balance_sheet"])
            logger.info(f"  Fed BS trend: {raw_data['balance_sheet'].get('trend', 'ERROR')}")
        except Exception as e:
            logger.error(f"  Balance sheet fetch FAILED: {e}")
            raw_data["balance_sheet"] = {"error": str(e)}
    
    try:
        raw_data["dxy"] = yahoo_data.get_dxy_data(timeframe)
        logger.info(
            "  DXY: %s (obs=%s fetched=%s)",
            raw_data["dxy"].get("current_price", "ERROR"),
            raw_data["dxy"].get("observed_at") or raw_data["dxy"].get("data_as_of"),
            raw_data["dxy"].get("fetched_at"),
        )
        _warn_if_delayed("DXY", raw_data["dxy"])
    except Exception as e:
        logger.error(f"  DXY fetch FAILED: {e}")
        raw_data["dxy"] = {"error": str(e), "timeframe": timeframe}

    if _dxy_needs_repair(raw_data.get("dxy") or {}):
        fb = yahoo_data.try_dxy_external_fallbacks(timeframe)
        if fb:
            raw_data["dxy"] = fb
            logger.info("  DXY: repaired via EURUSD/FRED fallbacks")
    
    try:
        raw_data["vix"] = yahoo_data.get_vix_data(timeframe)
        logger.info(
            "  VIX: %s (obs=%s fetched=%s)",
            raw_data["vix"].get("current_value", "ERROR"),
            raw_data["vix"].get("observed_at") or raw_data["vix"].get("data_as_of"),
            raw_data["vix"].get("fetched_at"),
        )
        _warn_if_delayed("VIX", raw_data["vix"])
    except Exception as e:
        logger.error(f"  VIX fetch FAILED: {e}")
        raw_data["vix"] = {"error": str(e)}
    
    try:
        raw_data["sp500"] = yahoo_data.get_sp500_data(timeframe)
        logger.info(
            "  S&P500: %s (obs=%s fetched=%s)",
            raw_data["sp500"].get("current_price", "ERROR"),
            raw_data["sp500"].get("observed_at") or raw_data["sp500"].get("data_as_of"),
            raw_data["sp500"].get("fetched_at"),
        )
        _warn_if_delayed("S&P 500", raw_data["sp500"])
    except Exception as e:
        logger.error(f"  S&P500 fetch FAILED: {e}")
        raw_data["sp500"] = {"error": str(e)}
    
    try:
        raw_data["gold"] = yahoo_data.get_gold_data(timeframe)
        logger.info(
            "  Gold: %s (obs=%s fetched=%s)",
            raw_data["gold"].get("current_price", "ERROR"),
            raw_data["gold"].get("observed_at") or raw_data["gold"].get("data_as_of"),
            raw_data["gold"].get("fetched_at"),
        )
        _warn_if_delayed("Gold", raw_data["gold"])
    except Exception as e:
        logger.error(f"  Gold fetch FAILED: {e}")
        raw_data["gold"] = {"error": str(e)}

    try:
        raw_data["oil"] = fred_data.get_oil_data(timeframe)
        logger.info(
            "  Oil (WTI): $%s (obs=%s fetched=%s)",
            raw_data["oil"].get("current_price", "ERROR"),
            raw_data["oil"].get("observed_at") or raw_data["oil"].get("data_as_of") or raw_data["oil"].get("latest_date"),
            raw_data["oil"].get("fetched_at"),
        )
        _warn_if_delayed("WTI", raw_data["oil"])
    except Exception as e:
        logger.error(f"  Oil fetch FAILED: {e}")
        raw_data["oil"] = {"error": str(e)}
    
    try:
        if STRICT_LIVE_OFFICIAL_ONLY:
            raw_data["btc"] = coingecko_data.get_btc_spot_coinbase(timeframe)
            if raw_data["btc"].get("error"):
                raw_data["btc"] = coingecko_data.get_btc_spot_kraken(timeframe)
        else:
            raw_data["btc"] = coingecko_data.get_btc_price(timeframe)
        logger.info(
            "  BTC: $%s (obs=%s fetched=%s)",
            raw_data["btc"].get("price_usd", "ERROR"),
            raw_data["btc"].get("date"),
            raw_data["btc"].get("fetched_at"),
        )
        _warn_if_delayed("BTC", raw_data["btc"])
    except Exception as e:
        logger.error(f"  BTC fetch FAILED: {e}")
        raw_data["btc"] = {"error": str(e)}

    def _btc_payload_ok(btc: dict) -> bool:
        if not btc or btc.get("error"):
            return False
        if not btc.get("date"):
            return False
        try:
            pf = float(btc.get("price_usd"))
        except (TypeError, ValueError):
            return False
        if not math.isfinite(pf) or pf <= 0:
            return False
        return True

    if not _btc_payload_ok(raw_data.get("btc") or {}):
        logger.warning("  BTC: CoinGecko missing or invalid; trying Coinbase Exchange fallback")
        cb = coingecko_data.get_btc_spot_coinbase(timeframe)
        if _btc_payload_ok(cb):
            raw_data["btc"] = cb
            logger.info(f"  BTC (Coinbase): ${raw_data['btc'].get('price_usd', 'ERROR')}")
        elif not _btc_payload_ok(raw_data.get("btc") or {}):
            logger.warning("  BTC: Coinbase failed; trying Kraken public API")
            kr = coingecko_data.get_btc_spot_kraken(timeframe)
            if _btc_payload_ok(kr):
                raw_data["btc"] = kr
                logger.info(f"  BTC (Kraken): ${raw_data['btc'].get('price_usd', 'ERROR')}")
            elif not _btc_payload_ok(raw_data.get("btc") or {}):
                logger.warning("  BTC: Kraken failed; trying Yahoo BTC-USD fallback")
                yb = yahoo_data.get_btc_spot_yahoo(timeframe)
                if _btc_payload_ok(yb):
                    raw_data["btc"] = yb
                    logger.info(f"  BTC (Yahoo): ${raw_data['btc'].get('price_usd', 'ERROR')}")
                elif not _btc_payload_ok(raw_data.get("btc") or {}):
                    logger.warning("  BTC: Yahoo failed; trying Binance public API")
                    bn = coingecko_data.get_btc_spot_binance(timeframe)
                    if _btc_payload_ok(bn):
                        raw_data["btc"] = bn
                        logger.info(f"  BTC (Binance): ${raw_data['btc'].get('price_usd', 'ERROR')}")
                    else:
                        logger.error(f"  BTC: Binance fallback also failed: {bn}")
                        raw_data["btc"] = raw_data.get("btc") or cb or kr or yb or bn or {"error": "btc_unavailable"}
    
    # Fed tone analysis — LLM-powered with keyword fallback
    try:
        days_map = {"current": 3, "week": 7, "month": 30, "year": 90}
        days = days_map.get(timeframe, 3)
        articles = news_data.get_fed_speeches(days=days)
        raw_data["fed_keywords"] = news_data.analyze_fed_tone_llm(articles)
        used_llm = raw_data["fed_keywords"].get("llm_fed_tone", False)
        logger.info(f"  Fed tone ({days}d, {'LLM' if used_llm else 'keywords'}): {raw_data['fed_keywords']}")
    except Exception as e:
        logger.error(f"  Fed tone analysis FAILED: {e}")
        raw_data["fed_keywords"] = {
            "dovish_keywords_found": 0,
            "hawkish_keywords_found": 0,
            "pivot_keywords_found": 0,
            "tone": "neutral",
        }

    # Actual Fed Funds Rate (FEDFUNDS) — essential for accurate fed_policy scoring
    if "fed_rate" in raw_data:
        logger.info(f"  Fed Funds Rate (cache): {raw_data['fed_rate'].get('current_rate', 'ERROR')}% "
                    f"(trend: {raw_data['fed_rate'].get('trend', 'N/A')})")
    else:
        try:
            raw_data["fed_rate"] = fred_data.get_fed_funds_rate(timeframe)
            _store_monthly_slow_metric("fed_rate", timeframe, raw_data["fed_rate"])
            logger.info(f"  Fed Funds Rate: {raw_data['fed_rate'].get('current_rate', 'ERROR')}% "
                        f"(trend: {raw_data['fed_rate'].get('trend', 'N/A')})")
        except Exception as e:
            logger.error(f"  Fed Funds Rate fetch FAILED: {e}")
            raw_data["fed_rate"] = {"error": str(e)}

    # Jobs data (Unemployment, NFP, Initial Claims)
    if "jobs" in raw_data:
        unemployment_rate = raw_data["jobs"].get("unemployment_rate", "ERROR")
        unemployment_trend = raw_data["jobs"].get("unemployment_trend", "N/A")
        if timeframe == "month" and raw_data["jobs"].get("unemployment_trend_3m"):
            logger.info(
                "  Unemployment (cache): %s%% (1m trend: %s, 3m trend: %s)",
                unemployment_rate,
                unemployment_trend,
                raw_data["jobs"].get("unemployment_trend_3m"),
            )
        else:
            logger.info("  Unemployment (cache): %s%% (trend: %s)", unemployment_rate, unemployment_trend)
    else:
        try:
            raw_data["jobs"] = fred_data.get_jobs_data(timeframe)
            _store_monthly_slow_metric("jobs", timeframe, raw_data["jobs"])
            unemployment_rate = raw_data["jobs"].get("unemployment_rate", "ERROR")
            unemployment_trend = raw_data["jobs"].get("unemployment_trend", "N/A")
            if timeframe == "month" and raw_data["jobs"].get("unemployment_trend_3m"):
                logger.info(
                    "  Unemployment: %s%% (1m trend: %s, 3m trend: %s)",
                    unemployment_rate,
                    unemployment_trend,
                    raw_data["jobs"].get("unemployment_trend_3m"),
                )
            else:
                logger.info("  Unemployment: %s%% (trend: %s)", unemployment_rate, unemployment_trend)
        except Exception as e:
            logger.error(f"  Jobs data fetch FAILED: {e}")
            raw_data["jobs"] = {"error": str(e)}

    # GDP growth rate
    if "gdp" in raw_data:
        logger.info(f"  GDP growth (cache): {raw_data['gdp'].get('gdp_growth_rate', 'ERROR')}%")
    else:
        try:
            raw_data["gdp"] = fred_data.get_gdp_data(timeframe)
            _store_monthly_slow_metric("gdp", timeframe, raw_data["gdp"])
            logger.info(f"  GDP growth: {raw_data['gdp'].get('gdp_growth_rate', 'ERROR')}%")
        except Exception as e:
            logger.error(f"  GDP fetch FAILED: {e}")
            raw_data["gdp"] = {"error": str(e)}

    # PMI (ISM Manufacturing)
    if "pmi" in raw_data:
        logger.info(f"  PMI (cache): {raw_data['pmi'].get('pmi_value', 'ERROR')} ({raw_data['pmi'].get('pmi_status', 'N/A')})")
    else:
        try:
            raw_data["pmi"] = fred_data.get_pmi_data(timeframe)
            _store_monthly_slow_metric("pmi", timeframe, raw_data["pmi"])
            logger.info(f"  PMI: {raw_data['pmi'].get('pmi_value', 'ERROR')} ({raw_data['pmi'].get('pmi_status', 'N/A')})")
        except Exception as e:
            logger.error(f"  PMI fetch FAILED: {e}")
            raw_data["pmi"] = {"error": str(e)}

    # M2 Money Supply
    if "m2" in raw_data:
        logger.info(f"  M2 (cache): ${raw_data['m2'].get('m2_value', 'ERROR')}T (trend: {raw_data['m2'].get('m2_trend', 'N/A')})")
    else:
        try:
            raw_data["m2"] = fred_data.get_m2_money_supply(timeframe)
            _store_monthly_slow_metric("m2", timeframe, raw_data["m2"])
            logger.info(f"  M2: ${raw_data['m2'].get('m2_value', 'ERROR')}T (trend: {raw_data['m2'].get('m2_trend', 'N/A')})")
        except Exception as e:
            logger.error(f"  M2 fetch FAILED: {e}")
            raw_data["m2"] = {"error": str(e)}

    # Natural Gas (Henry Hub futures)
    try:
        raw_data["natgas"] = yahoo_data.get_natural_gas_data(timeframe)
        logger.info(f"  NatGas: ${raw_data['natgas'].get('current_price', 'ERROR')} (trend: {raw_data['natgas'].get('trend', 'N/A')})")
    except Exception as e:
        logger.error(f"  NatGas fetch FAILED: {e}")
        raw_data["natgas"] = {"error": str(e)}

    # MOVE index & emerging markets (equity macro)
    try:
        raw_data["move_index"] = yahoo_data.get_move_index_data(timeframe)
        logger.info(f"  MOVE: {raw_data['move_index'].get('current_price', 'ERROR')} "
                    f"(chg={raw_data['move_index'].get('change', 'N/A')}%)")
    except Exception as e:
        logger.error(f"  MOVE fetch FAILED: {e}")
        raw_data["move_index"] = {"error": str(e)}

    try:
        raw_data["eem"] = yahoo_data.get_emerging_markets_data(timeframe)
        logger.info(f"  EEM: {raw_data['eem'].get('current_price', 'ERROR')} "
                    f"(chg={raw_data['eem'].get('change', 'N/A')}%)")
    except Exception as e:
        logger.error(f"  EEM fetch FAILED: {e}")
        raw_data["eem"] = {"error": str(e)}

    # BTC Market Structure (dominance, stablecoins, 200d MA)
    try:
        raw_data["btc_dominance"] = coingecko_data.get_btc_dominance(timeframe)
        logger.info(f"  BTC dominance: {raw_data['btc_dominance'].get('btc_dominance', 'ERROR')}%")
    except Exception as e:
        logger.error(f"  BTC dominance fetch FAILED: {e}")
        raw_data["btc_dominance"] = {
            "timeframe": timeframe,
            "error": str(e),
            "btc_dominance": None,
        }

    try:
        raw_data["stablecoins"] = coingecko_data.get_stablecoin_data(timeframe)
        logger.info(f"  Stablecoin dom: {raw_data['stablecoins'].get('total_stablecoin_dominance', 'ERROR')}%")
    except Exception as e:
        logger.error(f"  Stablecoin data fetch FAILED: {e}")
        raw_data["stablecoins"] = {
            "timeframe": timeframe,
            "error": str(e),
            "usdt_dominance": None,
            "usdc_dominance": None,
            "total_stablecoin_dominance": None,
        }

    try:
        raw_data["btc_technicals"] = coingecko_data.get_btc_ohlcv_200d()
        _bt = raw_data["btc_technicals"]
        _ma = _bt.get("ma200")
        if _ma is not None:
            _ma_s = f"${_ma:,.0f}"
        elif _bt.get("error"):
            _ma_s = "ERROR"
        else:
            _ma_s = "N/A"
        logger.info(f"  BTC 200d MA: {_ma_s}")
    except Exception as e:
        logger.error(f"  BTC technicals fetch FAILED: {e}")
        raw_data["btc_technicals"] = {"error": str(e)}

    # BTC ETF volume (institutional proxy)
    try:
        raw_data["btc_etf"] = yahoo_data.get_btc_etf_volume(timeframe)
        logger.info(f"  BTC ETF volume: {raw_data['btc_etf'].get('total_volume', 'ERROR')} ({raw_data['btc_etf'].get('level', 'N/A')})")
    except Exception as e:
        logger.error(f"  BTC ETF volume fetch FAILED: {e}")
        raw_data["btc_etf"] = {"error": str(e)}

    # DXY swing structure (HH/HL/LH/LL)
    try:
        raw_data["dxy_structure"] = yahoo_data.get_dxy_structure(timeframe)
        logger.info(f"  DXY structure: {raw_data['dxy_structure'].get('structure', 'ERROR')}")
    except Exception as e:
        logger.error(f"  DXY structure fetch FAILED: {e}")
        raw_data["dxy_structure"] = {"error": str(e)}

    if "financial_stress" in raw_data:
        logger.info(
            "  Financial stress (cache): HY OAS=%s STLFSI=%s",
            raw_data["financial_stress"].get("hy_oas", "N/A"),
            raw_data["financial_stress"].get("stress_index", "N/A"),
        )
    else:
        try:
            raw_data["financial_stress"] = fred_data.get_financial_stress(timeframe)
            _store_monthly_slow_metric("financial_stress", timeframe, raw_data["financial_stress"])
            logger.info(
                "  Financial stress: HY OAS=%s STLFSI=%s",
                raw_data["financial_stress"].get("hy_oas", "N/A"),
                raw_data["financial_stress"].get("stress_index", "N/A"),
            )
        except Exception as e:
            logger.error(f"  Financial stress fetch FAILED: {e}")
            raw_data["financial_stress"] = {"error": str(e)}

    if "breakeven_10y" in raw_data:
        logger.info(f"  10Y breakeven (cache): {raw_data['breakeven_10y'].get('value', 'ERROR')}%")
    else:
        try:
            raw_data["breakeven_10y"] = fred_data.get_10y_breakeven_expectation(timeframe)
            _store_monthly_slow_metric("breakeven_10y", timeframe, raw_data["breakeven_10y"])
            logger.info(f"  10Y breakeven: {raw_data['breakeven_10y'].get('value', 'ERROR')}%")
        except Exception as e:
            logger.error(f"  10Y breakeven fetch FAILED: {e}")
            raw_data["breakeven_10y"] = {"error": str(e)}

    _stamp_batch_fetched_at(raw_data)
    strict_live_warnings = _apply_strict_live_official_policy(raw_data, timeframe)

    # ── STEP 2: Validate data freshness ────────────────────────────────
    logger.info("[2/9] Validating data freshness...")
    freshness_report = validate_data_freshness(raw_data)
    for msg in strict_live_warnings:
        if msg not in freshness_report.warnings:
            freshness_report.warnings.append(msg)
    
    for w in freshness_report.warnings:
        logger.warning(f"  {w}")
    for c in freshness_report.critical_failures:
        logger.error(f"  {c}")
    
    if not freshness_report.can_proceed:
        logger.error("ABORTING: Critical data is missing or stale. Cannot compute reliable verdict.")
        logger.error(f"Critical failures: {freshness_report.critical_failures}")
        raise RuntimeError(json.dumps({
            "error": "analysis_failed",
            "message": "Critical data missing or stale.",
            "critical_failures": freshness_report.critical_failures,
            "warnings": freshness_report.warnings,
            "timeframe": timeframe,
        }))

    # ── STEP 3: Compute numeric scores (deterministic, zero LLM) ──────
    logger.info("[3/9] Computing deterministic numeric scores...")
    
    cpi_change = raw_data["cpi"].get("mom_change", raw_data["cpi"].get("change"))
    cpi_yoy = raw_data["cpi"].get("yoy_rate")
    core_cpi_yoy = raw_data["cpi"].get("core_yoy_rate")
    pce_change = raw_data["pce"].get("mom_change", raw_data["pce"].get("change", None))
    oil_change = raw_data.get("oil", {}).get("change")  # WTI crude oil % change (FRED DCOILWTICO)
    be_10y = raw_data.get("breakeven_10y", {}).get("value")

    regime, regime_reasoning, regime_multipliers = detect_regime(raw_data)

    inflation_score, inflation_reasoning, inflation_details = score_inflation(
        cpi_yoy,
        core_cpi_yoy,
        oil_change,
        breakeven_10y=be_10y,
    )

    dovish_kw = raw_data["fed_keywords"].get("dovish_keywords_found", 0)
    hawkish_kw = raw_data["fed_keywords"].get("hawkish_keywords_found", 0)
    pivot_kw = raw_data["fed_keywords"].get("pivot_keywords_found", 0)
    fed_rate_val = raw_data.get("fed_rate", {}).get("current_rate")
    fed_rate_trend = raw_data.get("fed_rate", {}).get("trend", "stable")
    fed_score, fed_reasoning = score_fed_policy(
        dovish_kw, hawkish_kw, pivot_kw,
        fed_rate=fed_rate_val,
        rate_trend=fed_rate_trend,
    )
    
    yield_10y = raw_data["yields"].get("yield_10y", {}).get("value")
    yield_curve = raw_data["yields"].get("yield_curve_spread")
    bs_trend = raw_data["balance_sheet"].get("trend", "stable")
    m2_trend = raw_data.get("m2", {}).get("m2_trend", "stable")
    m2_yoy = raw_data.get("m2", {}).get("m2_yoy_change")
    real_yield_10y = None
    try:
        be = raw_data.get("breakeven_10y") or {}
        bv = be.get("value")
        if yield_10y is not None and bv is not None:
            real_yield_10y = float(yield_10y) - float(bv)
    except (TypeError, ValueError):
        real_yield_10y = None
    liquidity_score, liquidity_reasoning = score_liquidity(
        yield_10y,
        yield_curve,
        bs_trend,
        m2_trend,
        real_yield_10y=real_yield_10y,
        m2_yoy_change=float(m2_yoy) if m2_yoy is not None else None,
    )
    
    dxy_blob = raw_data["dxy"]
    _dc = dxy_blob.get("change")
    if _dc is None and timeframe == "month":
        _dc = dxy_blob.get("change_rolling_1m")
    try:
        dxy_change = float(_dc) if _dc is not None else 0.0
        if not math.isfinite(dxy_change):
            dxy_change = 0.0
    except (TypeError, ValueError):
        dxy_change = 0.0
    dxy_level = dxy_blob.get("current_price")
    try:
        if dxy_level is not None:
            dxy_level = float(dxy_level)
            if not math.isfinite(dxy_level):
                dxy_level = None
    except (TypeError, ValueError):
        dxy_level = None
    dxy_score, dxy_reasoning = score_dxy(dxy_change, dxy_level)
    
    vix_val = raw_data["vix"].get("current_value")
    sp500_change = raw_data["sp500"].get("change")
    gold_change_val = raw_data["gold"].get("change")
    hy_oas_val = raw_data.get("financial_stress", {}).get("hy_oas")
    try:
        hy_oas_f = float(hy_oas_val) if hy_oas_val is not None else None
    except (TypeError, ValueError):
        hy_oas_f = None
    risk_score, risk_reasoning = score_risk_sentiment(
        vix_val, sp500_change, gold_change_val, hy_oas=hy_oas_f
    )

    # Economy section (Jobs, GDP, PMI)
    unemployment_rate = raw_data.get("jobs", {}).get("unemployment_rate")
    unemployment_trend = raw_data.get("jobs", {}).get("unemployment_trend", "stable")
    unemployment_trend_3m = raw_data.get("jobs", {}).get("unemployment_trend_3m", unemployment_trend)
    nfp_change = raw_data.get("jobs", {}).get("nfp_change")
    gdp_growth = raw_data.get("gdp", {}).get("gdp_growth_rate")
    pmi_value = raw_data.get("pmi", {}).get("pmi_value")
    economy_score, economy_reasoning, economy_details = score_economy(
        unemployment_rate=unemployment_rate,
        unemployment_trend=unemployment_trend,
        unemployment_trend_3m=unemployment_trend_3m,
        nfp_change=nfp_change,
        gdp_growth=gdp_growth,
        pmi_value=pmi_value,
        regime=regime,
    )

    section_scores = {
        "inflation": inflation_score,
        "economy": economy_score,
        "fed_policy": fed_score,
        "liquidity": liquidity_score,
        "dxy": dxy_score,
        "risk_sentiment": risk_score,
    }
    section_reasoning = {
        "inflation": inflation_reasoning,
        "economy": economy_reasoning,
        "fed_policy": fed_reasoning,
        "liquidity": liquidity_reasoning,
        "dxy": dxy_reasoning,
        "risk_sentiment": risk_reasoning,
    }
    
    signal_quality = evaluate_signal_quality(raw_data, section_scores, regime)
    contradiction_flags = signal_quality["contradiction_flags"]
    sanity_flags = signal_quality["sanity_flags"]
    quality_weight_multipliers = signal_quality["section_weight_multipliers"]
    section_confidence_multipliers = signal_quality["section_confidence_multipliers"]
    cfg_weights = get_scoring_config()["section_weights"]
    dynamic_weights = apply_weight_multipliers(cfg_weights, regime_multipliers)
    dynamic_weights = apply_weight_multipliers(dynamic_weights, quality_weight_multipliers)

    weighted_stale, score_breakdown = compute_weighted_total_with_freshness(
        section_scores, freshness_report.to_dict(), dynamic_weights=dynamic_weights
    )
    coh_adj, coh_reasoning = compute_coherence_adjustment(section_scores, raw_data)
    weighted_score = int(max(0, min(100, weighted_stale + coh_adj + signal_quality["additive_adjustment"])))

    section_reasoning["inflation"] += (
        f" | conf x{1.0 - inflation_details.get('confidence_haircut', 0.0):.2f}"
        if inflation_details.get("confidence_haircut", 0.0)
        else ""
    )
    for section_key, multiplier in section_confidence_multipliers.items():
        if multiplier != 1.0 and section_key in section_reasoning:
            section_reasoning[section_key] += f" | conf x{multiplier:.2f}"

    logger.info(f"  Inflation:      {inflation_score}/100 - {inflation_reasoning}")
    logger.info(f"  Economy:        {economy_score}/100 - {economy_reasoning}")
    logger.info(f"  Fed Policy:     {fed_score}/100 - {fed_reasoning}")
    logger.info(f"  Liquidity:      {liquidity_score}/100 - {liquidity_reasoning}")
    logger.info(f"  DXY:            {dxy_score}/100 - {dxy_reasoning}")
    logger.info(f"  Risk Sentiment: {risk_score}/100 - {risk_reasoning}")
    logger.info(f"  Regime:         {regime} - {regime_reasoning}")
    logger.info(f"  Weighted (stale-aware): {weighted_stale}/100 | Coherence: {coh_adj:+d} | Quality adj: {signal_quality['additive_adjustment']:+d} -> {weighted_score}/100")
    if coh_reasoning and coh_reasoning != "none":
        logger.info(f"  Coherence: {coh_reasoning}")
    if contradiction_flags:
        logger.warning("  Contradictions: %s", " | ".join(contradiction_flags))
    if sanity_flags:
        logger.warning("  Sanity flags: %s", " | ".join(sanity_flags))

    # ── STEP 3b: Cross-signal LLM review ──────────────────────────────
    logger.info("[3b/9] Running cross-signal LLM review...")
    cross_adj, cross_reasoning, signals_to_watch = review_cross_signals(
        section_scores=section_scores,
        section_reasoning=section_reasoning,
        raw_data=raw_data,
    )
    logger.info(f"  Cross-signal adjustment: {cross_adj:+d}")
    if cross_reasoning:
        logger.info(f"  Reasoning: {cross_reasoning[:150]}")

    # ── STEP 4: Fetch macro headlines ─────────────────────────────────
    headline_lookback = {"current": 48, "week": 168, "month": 720}.get(timeframe, 48)
    logger.info(f"[4/9] Fetching macro headlines (last {headline_lookback}h for timeframe={timeframe})...")
    headlines = []
    try:
        fetcher = HeadlineFetcher(lookback_hours=headline_lookback)
        headlines = fetcher.fetch_headlines()
        logger.info(f"  Fetched {len(headlines)} macro headlines")
    except HeadlineFetchError as e:
        logger.warning(f"  Headline fetch failed (non-critical): {e}")
        logger.warning("  Proceeding without headline adjustment.")
    except Exception as e:
        logger.warning(f"  Unexpected headline error (non-critical): {e}")

    # ── STEP 5: Classify headlines via LLM ────────────────────────────
    logger.info("[5/9] Classifying headlines via LLM (temperature=0)...")
    classified = []
    prompt_version = "n/a"
    llm_model = "n/a"
    
    if headlines:
        try:
            classifier = HeadlineClassifier()
            classified = classifier.classify_headlines(headlines[:10])  # Cap at 10
            prompt_version = classifier.prompt_version
            llm_model = classifier.model
            logger.info(f"  Classified {len(classified)} headlines")
            for c in classified[:3]:
                logger.info(f"    {c.get('event_bias')}/{c.get('risk_impact')} "
                           f"conf={c.get('confidence', 0):.2f}: {c.get('_headline_title', '')[:60]}")
            # ── Boosting: elevate confidence and optionally force bias for explicit decisions
            try:
                for i, cl in enumerate(classified):
                    if i >= len(headlines):
                        break
                    original = headlines[i]
                    # Keep fetch-time metadata attached even when classifier cache is reused.
                    cl["_explicit_decision"] = bool(
                        original.get("_explicit_decision", cl.get("_explicit_decision", False))
                    )
                    cl["_decision_type"] = original.get("_decision_type") or cl.get("_decision_type")
                    cl["_priority"] = original.get("_priority", cl.get("_priority", "normal"))
                    cl["_is_reuters"] = bool(original.get("_is_reuters", cl.get("_is_reuters", False)))
                    if original.get("source"):
                        cl["source"] = original.get("source")
                        cl["_headline_source"] = original.get("source")
                    try:
                        cl["_authority_score"] = int(
                            original.get("_authority_score", cl.get("_authority_score", 0)) or 0
                        )
                    except (TypeError, ValueError):
                        cl["_authority_score"] = 0
                    # If fetcher or official scraper annotated explicit decision, boost
                    if original.get("_explicit_decision"):
                        dtype = original.get("_decision_type")
                        if dtype in MONETARY_EXPLICIT_CONFIDENCE_BOOST_TYPES:
                            cl_conf = float(cl.get("confidence", 0) or 0)
                            if cl_conf < 0.98:
                                cl["confidence"] = 0.98
                                logger.info(
                                    "Boosted headline confidence to 0.98 for monetary explicit decision: %s",
                                    original.get("title", "")[:140],
                                )
                            # Map decision types to forced bias/impact
                            if dtype == "rate_hike":
                                cl["event_bias"] = "hawkish"
                                cl["risk_impact"] = "risk_off"
                            elif dtype == "rate_cut":
                                cl["event_bias"] = "dovish"
                                cl["risk_impact"] = "risk_on"
                            elif dtype == "rate_hold":
                                cl["event_bias"] = "neutral"
                                cl["risk_impact"] = "neutral"
                            elif dtype == "fomc_doc":
                                # Let classifier decide bias, but ensure high confidence
                                cl["confidence"] = max(cl.get("confidence", 0), 0.95)
                            logger.info(f"Forced classification for decision_type={dtype}: bias={cl.get('event_bias')} impact={cl.get('risk_impact')}")
                    else:
                        # Authority-based boost for trusted sources
                        if original.get("_authority_score", 0) >= 2:
                            cl["confidence"] = max(cl.get("confidence", 0), 0.9)
                            logger.info(f"Boosted confidence for authoritative source {original.get('source')} title={original.get('title','')[:120]}")
            except Exception as _e:
                logger.warning(f"Headline boosting step failed: {_e}")
        except Exception as e:
            logger.warning(f"  Headline classification failed (non-critical): {e}")
            logger.warning("  Proceeding without headline adjustment.")
    else:
        logger.info("  No headlines to classify. Headline adjustment = 0.")

    # ── REPORT: Generate market news report for auditability ───────────
    try:
        report_text, report_meta = generate_market_report(classified)
        logger.info("Market report generated:\n%s", _safe_log_text(report_text))
    except Exception as e:
        logger.warning(f"Failed to generate market report: {e}")
        report_text = ""
        report_meta = {}

    # ── STEP 6: Compute headline adjustment ───────────────────────────
    logger.info("[6/9] Computing headline adjustment...")
    headline_adj, headline_reasoning = compute_headline_adjustment(classified)
    logger.info(f"  Headline adjustment: {headline_adj:+d}")
    logger.info(f"  Reasoning: {headline_reasoning[:120]}")

    # ── STEP 7: Compute final verdict ─────────────────────────────────
    logger.info("[7/9] Computing final verdict...")
    avg_headline_conf = 0.0
    if classified:
        confs = [c.get("confidence", 0) for c in classified if c.get("confidence", 0) > 0]
        avg_headline_conf = sum(confs) / len(confs) if confs else 0.0
    
    verdict = compute_final_verdict(
        weighted_numeric_score=weighted_score,
        headline_adjustment=headline_adj,
        section_scores=section_scores,
        headline_confidence=avg_headline_conf,
        cross_signal_adjustment=cross_adj,
        data_freshness_info=freshness_report.to_dict(),
        contradiction_flags=contradiction_flags,
        sanity_flags=sanity_flags,
        downweighted_sections_count=sum(1 for v in quality_weight_multipliers.values() if v != 1.0),
    )
    
    logger.info(f"  Final Score:  {verdict['final_score']}/100")
    logger.info(f"  Bias:         {verdict['bias']}")
    logger.info(f"  Action:       {verdict['action']}")
    logger.info(f"  Confidence:   {verdict['confidence_pct']}% ({verdict['confidence_label']})")
    logger.info(
        "[CONFIDENCE BREAKDOWN] freshness=%.1f agreement=%.1f data_quality=%.1f headline=%.1f stability=%.1f critical_penalty=%.1f contradiction_multiplier=%.2f",
        verdict["components"].get("freshness_score", 0.0),
        verdict["components"].get("agreement_pct", 0.0),
        verdict["components"].get("data_quality_score", 0.0),
        verdict["components"].get("headline_conf_score", 0.0),
        verdict["components"].get("model_stability_score", 0.0),
        verdict["components"].get("critical_metric_penalty", 0.0),
        verdict["components"].get("contradiction_multiplier", 1.0),
    )

    # ── STEP 7b: Generate LLM narrative ───────────────────────────────
    logger.info("[7b/9] Generating verdict narrative...")
    narrative_data = generate_narrative(
        final_score=verdict["final_score"],
        bias=verdict["bias"],
        action=verdict["action"],
        section_scores=section_scores,
        section_reasoning=section_reasoning,
        headline_adjustment=headline_adj,
        cross_signal_adjustment=cross_adj,
        cross_signal_reasoning=cross_reasoning,
        raw_data=raw_data,
        classified_headlines=classified,
        freshness_info=freshness_report.to_dict(),
        template_reasoning=verdict.get("reasoning", ""),
    )
    logger.info(f"  Narrative: {narrative_data['narrative'][:120]}")
    if narrative_data["key_risk"]:
        logger.info(f"  Key risk: {narrative_data['key_risk']}")
    if narrative_data["catalyst_to_watch"]:
        logger.info(f"  Catalyst: {narrative_data['catalyst_to_watch']}")

    # ── STEP 8: Store snapshot to SQLite ──────────────────────────────
    logger.info("[8/9] Saving snapshot to local database...")
    # Derive fed rate stance from trend
    fed_rate_stance = "pausing"
    if fed_rate_trend == "falling":
        fed_rate_stance = "cutting"
    elif fed_rate_trend == "rising":
        fed_rate_stance = "hiking"

    btc_market_arrow = None
    try:
        bp = raw_data.get("btc", {}).get("price_usd")
        ma200 = raw_data.get("btc_technicals", {}).get("ma200")
        if bp is not None and ma200 is not None and float(ma200) > 0:
            btc_market_arrow = "up" if float(bp) >= float(ma200) else "down"
    except (TypeError, ValueError):
        pass

    # Build top headlines for frontend display (with matched keywords for UI)
    from utils.keyword_matcher import get_matched_keywords
    top_headlines = []
    for i, c in enumerate(classified[:5]):
        hl_title = c.get("_headline_title", c.get("reason", ""))
        hl_source = c.get("_headline_source", "")
        # Use title + description for keyword match (same as classifier)
        orig = headlines[i] if i < len(headlines) else {}
        text = (orig.get("title", "") or "") + " " + (orig.get("description", "") or "")
        matched = get_matched_keywords(text) if text.strip() else {"hawkish": [], "dovish": []}
        top_headlines.append({
            "title": (hl_title or "")[:200],
            "source": hl_source,
            "event_bias": c.get("event_bias", "neutral"),
            "risk_impact": c.get("risk_impact", "neutral"),
            "confidence": c.get("confidence", 0),
            "matched_hawkish": matched.get("hawkish", []),
            "matched_dovish": matched.get("dovish", []),
        })

    dxy_api_val, dxy_api_chg = _dxy_api_fields(raw_data["dxy"])
    freshness_payload = freshness_report.to_dict()

    snapshot = {
        "timestamp": timestamp,
        "timeframe": timeframe,
        "cpi_value": raw_data["cpi"].get("latest_value"),
        "cpi_mom_change": cpi_change,
        "cpi_yoy_rate": raw_data["cpi"].get("yoy_rate"),
        "core_cpi_value": raw_data["cpi"].get("core_latest_value"),
        "cpi_core_mom_change": raw_data["cpi"].get("core_mom_change"),
        "cpi_core_yoy_rate": raw_data["cpi"].get("core_yoy_rate"),
        "cpi_trend": raw_data["cpi"].get("trend"),
        "cpi_source": raw_data["cpi"].get("source", "FRED"),
        "cpi_mom_avg_3m": raw_data["cpi"].get("cpi_mom_avg_3m"),
        "cpi_mom_avg_3m_prior": raw_data["cpi"].get("cpi_mom_avg_3m_prior"),
        "cpi_mom_avg_3m_trend": raw_data["cpi"].get("cpi_mom_avg_3m_trend"),
        "core_cpi_mom_avg_3m": raw_data["cpi"].get("core_cpi_mom_avg_3m"),
        "core_cpi_mom_avg_3m_prior": raw_data["cpi"].get("core_cpi_mom_avg_3m_prior"),
        "core_cpi_mom_avg_3m_trend": raw_data["cpi"].get("core_cpi_mom_avg_3m_trend"),
        "pce_value": raw_data["pce"].get("latest_value"),
        "pce_latest_date": raw_data["pce"].get("latest_date"),
        "pce_mom_change": pce_change,
        "pce_mom_avg_3m": raw_data["pce"].get("pce_mom_avg_3m"),
        "pce_mom_avg_3m_prior": raw_data["pce"].get("pce_mom_avg_3m_prior"),
        "pce_mom_avg_3m_trend": raw_data["pce"].get("pce_mom_avg_3m_trend"),
        "oil_change": oil_change,
        "oil_change_label": raw_data.get("oil", {}).get("change_label"),
        "oil_change_unit": raw_data.get("oil", {}).get("change_unit"),
        "oil_price": raw_data.get("oil", {}).get("current_price"),
        "oil_observed_at": raw_data.get("oil", {}).get("observed_at") or raw_data.get("oil", {}).get("data_as_of"),
        "oil_fetched_at": raw_data.get("oil", {}).get("fetched_at"),
        "oil_trend": raw_data.get("oil", {}).get("trend"),
        "oil_source": raw_data.get("oil", {}).get("source"),
        "dxy_value": dxy_api_val,
        "dxy_change": dxy_api_chg,
        "dxy_change_7d": dxy_api_chg,
        "dxy_change_label": raw_data["dxy"].get("change_label"),
        "dxy_change_unit": raw_data["dxy"].get("change_unit"),
        "dxy_change_rolling_1m": raw_data["dxy"].get("change_rolling_1m"),
        "dxy_change_rolling_1m_label": raw_data["dxy"].get("change_rolling_1m_label"),
        "dxy_comparison_date_rolling_1m": raw_data["dxy"].get("comparison_date_rolling_1m"),
        "dxy_trend": raw_data["dxy"].get("trend"),
        "dxy_source": raw_data["dxy"].get("source"),
        "dxy_observed_at": raw_data["dxy"].get("observed_at") or raw_data["dxy"].get("data_as_of"),
        "dxy_fetched_at": raw_data["dxy"].get("fetched_at"),
        "vix": vix_val,
        "vix_change": raw_data["vix"].get("change"),
        "vix_change_label": raw_data["vix"].get("change_label"),
        "vix_change_unit": raw_data["vix"].get("change_unit"),
        "vix_trend": raw_data["vix"].get("trend"),
        "vix_source": raw_data["vix"].get("source"),
        "vix_observed_at": raw_data["vix"].get("observed_at") or raw_data["vix"].get("data_as_of"),
        "vix_fetched_at": raw_data["vix"].get("fetched_at"),
        "ten_year_yield": yield_10y,
        "ten_year_yield_trend": raw_data["yields"].get("yield_10y", {}).get("trend"),
        "two_year_yield": raw_data["yields"].get("yield_2y", {}).get("value"),
        "two_year_yield_trend": raw_data["yields"].get("yield_2y", {}).get("trend"),
        "yield_curve_spread": yield_curve,
        "yield_monthly_track": raw_data["yields"].get("yield_monthly_track"),
        "yield_spread_delta_3m": raw_data["yields"].get("yield_spread_delta_3m"),
        "yield_spread_trend_3m": raw_data["yields"].get("yield_spread_trend_3m"),
        "yield_10y_delta_3m": raw_data["yields"].get("yield_10y_delta_3m"),
        "yield_2y_delta_3m": raw_data["yields"].get("yield_2y_delta_3m"),
        "fed_balance_sheet_trend": bs_trend,
        "sp500_change": sp500_change,
        "sp500_change_label": raw_data["sp500"].get("change_label"),
        "sp500_change_unit": raw_data["sp500"].get("change_unit"),
        "sp500_price": raw_data["sp500"].get("current_price"),
        "sp500_trend": raw_data["sp500"].get("trend"),
        "sp500_source": raw_data["sp500"].get("source"),
        "sp500_observed_at": raw_data["sp500"].get("observed_at") or raw_data["sp500"].get("data_as_of"),
        "sp500_fetched_at": raw_data["sp500"].get("fetched_at"),
        "gold_price": raw_data["gold"].get("current_price"),
        "gold_change": gold_change_val,
        "gold_change_label": raw_data["gold"].get("change_label"),
        "gold_change_unit": raw_data["gold"].get("change_unit"),
        "gold_trend": raw_data["gold"].get("trend"),
        "gold_source": raw_data["gold"].get("source"),
        "gold_observed_at": raw_data["gold"].get("observed_at") or raw_data["gold"].get("data_as_of"),
        "gold_fetched_at": raw_data["gold"].get("fetched_at"),
        "btc_price": raw_data["btc"].get("price_usd"),
        "btc_change": raw_data["btc"].get("change"),
        "btc_change_24h": raw_data["btc"].get("change_24h"),
        "btc_change_7d": raw_data["btc"].get("change_7d"),
        "btc_observed_at": raw_data["btc"].get("date"),
        "btc_fetched_at": raw_data["btc"].get("fetched_at"),
        "fed_funds_rate": fed_rate_val,
        "fed_rate_trend": fed_rate_trend,
        "fed_rate_stance": fed_rate_stance,
        "fed_rate_type": raw_data.get("fed_rate", {}).get("rate_type"),
        "unemployment_rate": unemployment_rate,
        "unemployment_trend": unemployment_trend,
        "unemployment_trend_mom": raw_data.get("jobs", {}).get("unemployment_trend"),
        "unemployment_trend_3m": raw_data.get("jobs", {}).get("unemployment_trend_3m"),
        "unemployment_3m_avg": raw_data.get("jobs", {}).get("unemployment_3m_avg"),
        "unemployment_history_3": raw_data.get("jobs", {}).get("unemployment_history_3"),
        "nfp_change": nfp_change,
        "gdp_growth_rate": gdp_growth,
        "gdp_trend": raw_data.get("gdp", {}).get("gdp_trend"),
        "gdp_latest_date": raw_data.get("gdp", {}).get("latest_date"),
        "pmi_value": pmi_value,
        "pmi_previous_value": raw_data.get("pmi", {}).get("previous_value"),
        "pmi_delta_value": raw_data.get("pmi", {}).get("delta_value"),
        "pmi_latest_date": raw_data.get("pmi", {}).get("latest_date"),
        "pmi_status": raw_data.get("pmi", {}).get("pmi_status"),
        "pmi_trend": raw_data.get("pmi", {}).get("pmi_trend"),
        "pmi_source": raw_data.get("pmi", {}).get("source"),
        "pmi_proxy_note": raw_data.get("pmi", {}).get("_proxy_note"),
        "m2_trend": m2_trend,
        "m2_change": raw_data.get("m2", {}).get("m2_change"),
        "m2_yoy_change": raw_data.get("m2", {}).get("m2_yoy_change"),
        "section_scores": section_scores,
        "section_reasoning": section_reasoning,
        "regime": regime,
        "regime_reasoning": regime_reasoning,
        "confidence_breakdown": verdict.get("components", {}),
        "data_quality_score": freshness_payload.get("data_quality", {}).get("score"),
        "sanity_flags": sanity_flags,
        "contradiction_flags": contradiction_flags,
        "section_confidence_multipliers": section_confidence_multipliers,
        "section_weight_multipliers": quality_weight_multipliers,
        "weighted_numeric_stale_downweight": weighted_stale,
        "coherence_adjustment": coh_adj,
        "coherence_reasoning": coh_reasoning,
        "weighted_numeric_score": weighted_score,
        "score_breakdown": score_breakdown,
        "ten_year_breakeven": raw_data.get("breakeven_10y", {}).get("value"),
        "real_yield_10y": real_yield_10y,
        "headlines_fetched": len(headlines),
        "headlines_classified": [
            {k: v for k, v in c.items() if not k.startswith("_")}
            for c in classified
        ],
        "headline_adjustment": headline_adj,
        "headline_reasoning": headline_reasoning,
        "headline_report": report_text,
        "headline_report_meta": report_meta,
        "final_score": verdict["final_score"],
        "bias": verdict["bias"],
        "action": verdict["action"],
        "confidence_pct": verdict["confidence_pct"],
        "confidence_label": verdict["confidence_label"],
        "data_freshness_info": freshness_payload,
        "config_hash": _config_hash(),
        "prompt_version": prompt_version,
        "llm_model": llm_model,
        "fed_tone": raw_data["fed_keywords"].get("tone", "neutral"),
        "fed_tone_score": raw_data["fed_keywords"].get("fed_tone_score"),
        "fed_tone_summary": raw_data["fed_keywords"].get("fed_tone_summary"),
        "fed_tone_key_signals": raw_data["fed_keywords"].get("fed_tone_key_signals"),
        "fed_tone_confidence_pct": raw_data["fed_keywords"].get("fed_tone_confidence_pct"),
        "dovish_keyword_count": dovish_kw,
        "hawkish_keyword_count": hawkish_kw,
        "pivot_keyword_count": pivot_kw,
        "cross_signal_adjustment": cross_adj,
        "cross_signal_reasoning": cross_reasoning,
        "signals_to_watch": signals_to_watch,
        "narrative": narrative_data.get("narrative", ""),
        "key_risk": narrative_data.get("key_risk", ""),
        "catalyst_to_watch": narrative_data.get("catalyst_to_watch", ""),
        "top_headlines": top_headlines,
        # Natural gas
        "natgas_price": raw_data.get("natgas", {}).get("current_price"),
        "natgas_change": raw_data.get("natgas", {}).get("change"),
        "natgas_change_label": raw_data.get("natgas", {}).get("change_label"),
        "natgas_change_unit": raw_data.get("natgas", {}).get("change_unit"),
        "natgas_trend": raw_data.get("natgas", {}).get("trend"),
        "natgas_source": raw_data.get("natgas", {}).get("source"),
        "move_index_value": raw_data.get("move_index", {}).get("current_price"),
        "move_index_change": raw_data.get("move_index", {}).get("change"),
        "move_index_change_label": raw_data.get("move_index", {}).get("change_label"),
        "move_index_change_unit": raw_data.get("move_index", {}).get("change_unit"),
        "move_index_trend": raw_data.get("move_index", {}).get("trend"),
        "financial_stress_index": raw_data.get("financial_stress", {}).get("stress_index"),
        "financial_stress_level": raw_data.get("financial_stress", {}).get("level"),
        "financial_stress_trend": raw_data.get("financial_stress", {}).get("stress_trend"),
        "hy_oas": raw_data.get("financial_stress", {}).get("hy_oas"),
        "hy_trend": raw_data.get("financial_stress", {}).get("hy_trend"),
        "eem_price": raw_data.get("eem", {}).get("current_price"),
        "eem_change": raw_data.get("eem", {}).get("change"),
        "eem_change_label": raw_data.get("eem", {}).get("change_label"),
        "eem_change_unit": raw_data.get("eem", {}).get("change_unit"),
        "eem_trend": raw_data.get("eem", {}).get("trend"),
        "eem_source": raw_data.get("eem", {}).get("source"),
        # BTC market structure
        "btc_dominance": raw_data.get("btc_dominance", {}).get("btc_dominance"),
        "btc_dominance_change": raw_data.get("btc_dominance", {}).get("change"),
        "btc_dominance_source": raw_data.get("btc_dominance", {}).get("source"),
        "btc_dominance_change_source": raw_data.get("btc_dominance", {}).get("change_source"),
        "stablecoin_dominance": raw_data.get("stablecoins", {}).get("total_stablecoin_dominance"),
        "stablecoin_dominance_change": raw_data.get("stablecoins", {}).get("change"),
        "stablecoin_dominance_source": raw_data.get("stablecoins", {}).get("source"),
        "stablecoin_dominance_change_source": raw_data.get("stablecoins", {}).get("change_source"),
        "btc_ma200": raw_data.get("btc_technicals", {}).get("ma200"),
        "btc_realized_vol_30d": raw_data.get("btc_technicals", {}).get("realized_vol_30d"),
        "btc_etf_volume": raw_data.get("btc_etf", {}).get("total_volume"),
        "btc_etf_source": raw_data.get("btc_etf", {}).get("source"),
        "btc_etf_flow_level": raw_data.get("btc_etf", {}).get("level"),
        "btc_market_arrow": btc_market_arrow,
        # DXY structure
        "dxy_structure": raw_data.get("dxy_structure", {}).get("structure"),
        # Geopolitics
        "geopolitics_risk_level": _compute_geopolitics_risk(classified),
    }
    
    try:
        row_id = save_snapshot(snapshot)
        logger.info(f"  Snapshot saved: row_id={row_id}")
    except Exception as e:
        logger.error(f"  Database save failed: {e}")
        # Non-fatal — print result anyway

    # ── STEP 9: Print result ──────────────────────────────────────────
    logger.info("[9/9] Analysis complete.")
    
    print("\n" + "=" * 70)
    print("  BTC MACRO ANALYSIS RESULT")
    print("=" * 70)
    print(f"  Timestamp:      {timestamp}")
    print(f"  BTC Price:      ${raw_data['btc'].get('price_usd', 'N/A'):,.0f}" if isinstance(raw_data['btc'].get('price_usd'), (int, float)) else f"  BTC Price:      N/A")
    print()
    print("  -- Section Scores (Deterministic) --")
    print(f"    Inflation:      {inflation_score:3d}/100")
    print(f"    Economy:        {economy_score:3d}/100")
    print(f"    Fed Policy:     {fed_score:3d}/100")
    print(f"    Liquidity:      {liquidity_score:3d}/100")
    print(f"    DXY:            {dxy_score:3d}/100")
    print(f"    Risk Sentiment: {risk_score:3d}/100")
    print(f"    -------------------------")
    print(f"    Stale-aware base: {weighted_stale:3d}/100  (coherence {coh_adj:+d})")
    print(f"    Weighted Total:   {weighted_score:3d}/100")
    print()
    print(f"  -- Adjustments --")
    print(f"    Headlines analyzed: {len(headlines)}")
    print(f"    Headline adj:       {headline_adj:+d}")
    print(f"    Cross-signal adj:   {cross_adj:+d}")
    print()
    print(f"  -- Final Verdict --")
    print(f"    SCORE:      {verdict['final_score']}/100")
    print(f"    BIAS:       {verdict['bias']}")
    print(f"    ACTION:     {verdict['action']}")
    print(f"    CONFIDENCE: {verdict['confidence_pct']}% ({verdict['confidence_label']})")
    if narrative_data.get("narrative"):
        print()
        print(f"  -- Analyst Commentary --")
        print(f"    {narrative_data['narrative']}")
        if narrative_data.get("key_risk"):
            print(f"    Risk: {narrative_data['key_risk']}")
        if narrative_data.get("catalyst_to_watch"):
            print(f"    Watch: {narrative_data['catalyst_to_watch']}")
    print("=" * 70)
    
    if freshness_report.warnings:
        print("\n  Warnings:")
        for w in freshness_report.warnings:
            print(f"     - {w}")
    
    print()
    return snapshot


if __name__ == "__main__":
    import sys
    
    # Support command line arguments: [timeframe] [--fresh]
    timeframe = "current"
    fresh = "--fresh" in sys.argv

    for arg in sys.argv[1:]:
        if arg == "--fresh":
            continue
        tf_arg = arg.lower()
        if tf_arg in ["current", "week", "month"]:
            timeframe = tf_arg
        else:
            print(f"Invalid timeframe: {tf_arg}. Using 'current'.")
            print("Valid timeframes: current, week, month")
            print("Flags: --fresh  (clear cache and re-fetch all data)")
    
    try:
        result = run_analysis(timeframe, fresh=fresh)
        print(f"\nAnalysis completed successfully (timeframe: {timeframe})")
        print(f"Final Score: {result.get('final_score', 'N/A')}/100")
        print(f"Bias: {result.get('bias', 'N/A')}")
    except RuntimeError as e:
        try:
            payload = json.loads(str(e))
        except Exception:
            payload = None
        if isinstance(payload, dict) and payload.get("error") == "analysis_failed":
            print("\nANALYSIS ABORTED - Critical data missing or stale.")
            print("   Critical failures:")
            for f in payload.get("critical_failures", []):
                print(f"     - {f}")
            warnings = payload.get("warnings") or []
            if warnings:
                print("\n   Warnings:")
                for w in warnings:
                    print(f"     - {w}")
            print("\n   Fix: Check API keys, internet connection, and data source availability.")
            sys.exit(1)
        logger.error(f"Unexpected runtime error: {e}")
        print(f"\nAnalysis failed: {e}")
        sys.exit(2)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        print(f"\nAnalysis failed: {e}")
        sys.exit(2)
