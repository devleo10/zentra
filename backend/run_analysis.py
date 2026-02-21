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
import hashlib
import logging
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
    score_dxy, score_risk_sentiment, compute_weighted_total,
)
from scoring_engine.headline_adjuster import compute_headline_adjustment
from scoring_engine.verdict import compute_final_verdict
from scoring_engine.freshness import validate_data_freshness
from headline_engine.fetcher import HeadlineFetcher, HeadlineFetchError
from headline_engine.classifier import HeadlineClassifier
from headline_engine.report import generate_market_report
from storage.db import save_snapshot


def _config_hash() -> str:
    """SHA-256 of the scoring config for reproducibility tracking."""
    config_path = Path(__file__).parent / "config" / "scoring_weights.json"
    content = config_path.read_bytes()
    return hashlib.sha256(content).hexdigest()[:16]


def run_analysis(timeframe: str = "current"):
    """
    Execute the full analysis pipeline with timeframe support.
    
    Args:
        timeframe: Analysis timeframe - 'current', 'week', 'month', or 'year'
    
    Returns the result dict on success, or raises SystemExit on failure.
    """
    timestamp = datetime.now().isoformat()
    logger.info("=" * 70)
    logger.info(f"BTC MACRO ANALYSIS — {timestamp} (timeframe: {timeframe})")
    logger.info("=" * 70)

    # ── STEP 1: Fetch all numeric data ─────────────────────────────────
    logger.info("[1/9] Fetching numeric macro data...")
    raw_data = {}
    
    try:
        raw_data["cpi"] = fred_data.get_cpi_data(timeframe)
        logger.info(f"  CPI: {raw_data['cpi'].get('latest_value', 'ERROR')}")
    except Exception as e:
        logger.error(f"  CPI fetch FAILED: {e}")
        raw_data["cpi"] = {"error": str(e)}
    
    try:
        raw_data["pce"] = fred_data.get_pce_data(timeframe)
        logger.info(f"  PCE: {raw_data['pce'].get('latest_value', 'ERROR')}")
    except Exception as e:
        logger.error(f"  PCE fetch FAILED: {e}")
        raw_data["pce"] = {"error": str(e)}
    
    try:
        raw_data["yields"] = fred_data.get_treasury_yields(timeframe)
        logger.info(f"  10Y Yield: {raw_data['yields'].get('yield_10y', {}).get('value', 'ERROR')}")
    except Exception as e:
        logger.error(f"  Yields fetch FAILED: {e}")
        raw_data["yields"] = {"error": str(e)}
    
    try:
        raw_data["balance_sheet"] = fred_data.get_fed_balance_sheet(timeframe)
        logger.info(f"  Fed BS trend: {raw_data['balance_sheet'].get('trend', 'ERROR')}")
    except Exception as e:
        logger.error(f"  Balance sheet fetch FAILED: {e}")
        raw_data["balance_sheet"] = {"error": str(e)}
    
    try:
        raw_data["dxy"] = yahoo_data.get_dxy_data(timeframe)
        logger.info(f"  DXY: {raw_data['dxy'].get('current_price', 'ERROR')}")
    except Exception as e:
        logger.error(f"  DXY fetch FAILED: {e}")
        raw_data["dxy"] = {"error": str(e)}
    
    try:
        raw_data["vix"] = yahoo_data.get_vix_data(timeframe)
        logger.info(f"  VIX: {raw_data['vix'].get('current_value', 'ERROR')}")
    except Exception as e:
        logger.error(f"  VIX fetch FAILED: {e}")
        raw_data["vix"] = {"error": str(e)}
    
    try:
        raw_data["sp500"] = yahoo_data.get_sp500_data(timeframe)
        logger.info(f"  S&P500: {raw_data['sp500'].get('current_price', 'ERROR')}")
    except Exception as e:
        logger.error(f"  S&P500 fetch FAILED: {e}")
        raw_data["sp500"] = {"error": str(e)}
    
    try:
        raw_data["gold"] = yahoo_data.get_gold_data(timeframe)
        logger.info(f"  Gold: {raw_data['gold'].get('current_price', 'ERROR')}")
    except Exception as e:
        logger.error(f"  Gold fetch FAILED: {e}")
        raw_data["gold"] = {"error": str(e)}
    
    try:
        raw_data["btc"] = coingecko_data.get_btc_price(timeframe)
        logger.info(f"  BTC: ${raw_data['btc'].get('price_usd', 'ERROR')}")
    except Exception as e:
        logger.error(f"  BTC fetch FAILED: {e}")
        raw_data["btc"] = {"error": str(e)}
    
    # Fed keywords from news (for fed_policy scoring)
    try:
        # Map timeframe to days for news lookback
        days_map = {"current": 3, "week": 7, "month": 30, "year": 90}
        days = days_map.get(timeframe, 3)
        articles = news_data.get_fed_speeches(days=days)
        raw_data["fed_keywords"] = news_data.analyze_fed_keywords(articles)
        logger.info(f"  Fed keywords ({days}d lookback): {raw_data['fed_keywords']}")
    except Exception as e:
        logger.error(f"  Fed keywords fetch FAILED: {e}")
        raw_data["fed_keywords"] = {"dovish_keywords_found": 0, "hawkish_keywords_found": 0, "pivot_keywords_found": 0}

    # ── STEP 2: Validate data freshness ────────────────────────────────
    logger.info("[2/9] Validating data freshness...")
    freshness_report = validate_data_freshness(raw_data)
    
    for w in freshness_report.warnings:
        logger.warning(f"  {w}")
    for c in freshness_report.critical_failures:
        logger.error(f"  {c}")
    
    if not freshness_report.can_proceed:
        logger.error("ABORTING: Critical data is missing or stale. Cannot compute reliable verdict.")
        logger.error(f"Critical failures: {freshness_report.critical_failures}")
        print("\n❌ ANALYSIS ABORTED — Critical data missing or stale.")
        print("   Critical failures:")
        for f in freshness_report.critical_failures:
            print(f"     • {f}")
        print("\n   Fix: Check API keys, internet connection, and data source availability.")
        sys.exit(1)

    # ── STEP 3: Compute numeric scores (deterministic, zero LLM) ──────
    logger.info("[3/9] Computing deterministic numeric scores...")
    
    cpi_change = raw_data["cpi"].get("change", raw_data["cpi"].get("mom_change", 0))
    pce_change = raw_data["pce"].get("change", raw_data["pce"].get("mom_change", None))
    oil_change = raw_data.get("gold", {}).get("change")  # Using gold as proxy if oil not fetched separately
    
    inflation_score, inflation_reasoning = score_inflation(cpi_change, pce_change, oil_change)
    
    dovish_kw = raw_data["fed_keywords"].get("dovish_keywords_found", 0)
    hawkish_kw = raw_data["fed_keywords"].get("hawkish_keywords_found", 0)
    pivot_kw = raw_data["fed_keywords"].get("pivot_keywords_found", 0)
    fed_score, fed_reasoning = score_fed_policy(dovish_kw, hawkish_kw, pivot_kw)
    
    yield_10y = raw_data["yields"].get("yield_10y", {}).get("value")
    yield_curve = raw_data["yields"].get("yield_curve_spread")
    bs_trend = raw_data["balance_sheet"].get("trend", "stable")
    liquidity_score, liquidity_reasoning = score_liquidity(yield_10y, yield_curve, bs_trend)
    
    dxy_change = raw_data["dxy"].get("change", 0)
    dxy_score, dxy_reasoning = score_dxy(dxy_change)
    
    vix_val = raw_data["vix"].get("current_value")
    sp500_change = raw_data["sp500"].get("change")
    gold_change_val = raw_data["gold"].get("change")
    risk_score, risk_reasoning = score_risk_sentiment(vix_val, sp500_change, gold_change_val)
    
    section_scores = {
        "inflation": inflation_score,
        "fed_policy": fed_score,
        "liquidity": liquidity_score,
        "dxy": dxy_score,
        "risk_sentiment": risk_score,
    }
    section_reasoning = {
        "inflation": inflation_reasoning,
        "fed_policy": fed_reasoning,
        "liquidity": liquidity_reasoning,
        "dxy": dxy_reasoning,
        "risk_sentiment": risk_reasoning,
    }
    
    weighted_score, score_breakdown = compute_weighted_total(section_scores)
    
    logger.info(f"  Inflation:      {inflation_score}/100 — {inflation_reasoning}")
    logger.info(f"  Fed Policy:     {fed_score}/100 — {fed_reasoning}")
    logger.info(f"  Liquidity:      {liquidity_score}/100 — {liquidity_reasoning}")
    logger.info(f"  DXY:            {dxy_score}/100 — {dxy_reasoning}")
    logger.info(f"  Risk Sentiment: {risk_score}/100 — {risk_reasoning}")
    logger.info(f"  Weighted Total: {weighted_score}/100")

    # ── STEP 4: Fetch macro headlines (last 48h) ──────────────────────
    logger.info("[4/9] Fetching macro headlines...")
    headlines = []
    try:
        fetcher = HeadlineFetcher(lookback_hours=48)
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
                    # If fetcher or official scraper annotated explicit decision, boost
                    if original.get("_explicit_decision"):
                        # Force high confidence and, for rate decisions / FOMC docs, set bias/impact
                        cl_conf = float(cl.get("confidence", 0) or 0)
                        if cl_conf < 0.98:
                            cl["confidence"] = 0.98
                            logger.info(f"Boosted headline confidence to 0.98 for explicit decision: {original.get('title','')[:140]}")
                        dtype = original.get("_decision_type")
                        if dtype in ("rate_hike", "rate_cut", "rate_hold", "fomc_doc"):
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
        logger.info("Market report generated:\n%s", report_text)
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
    )
    
    logger.info(f"  Final Score:  {verdict['final_score']}/100")
    logger.info(f"  Bias:         {verdict['bias']}")
    logger.info(f"  Action:       {verdict['action']}")
    logger.info(f"  Confidence:   {verdict['confidence_pct']}% ({verdict['confidence_label']})")

    # ── STEP 8: Store snapshot to SQLite ──────────────────────────────
    logger.info("[8/9] Saving snapshot to local database...")
    snapshot = {
        "timestamp": timestamp,
        "cpi_mom_change": cpi_change,
        "pce_mom_change": pce_change,
        "oil_change": oil_change,
        "dxy_value": raw_data["dxy"].get("current_price"),
        "dxy_change_7d": dxy_change,
        "vix": vix_val,
        "ten_year_yield": yield_10y,
        "yield_curve_spread": yield_curve,
        "fed_balance_sheet_trend": bs_trend,
        "sp500_change": sp500_change,
        "gold_change": gold_change_val,
        "btc_price": raw_data["btc"].get("price_usd"),
        "section_scores": section_scores,
        "section_reasoning": section_reasoning,
        "weighted_numeric_score": weighted_score,
        "score_breakdown": score_breakdown,
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
        "data_freshness_info": freshness_report.to_dict(),
        "config_hash": _config_hash(),
        "prompt_version": prompt_version,
        "llm_model": llm_model,
        "dovish_keyword_count": dovish_kw,
        "hawkish_keyword_count": hawkish_kw,
        "pivot_keyword_count": pivot_kw,
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
    print("  ── Section Scores (Deterministic) ──")
    print(f"    Inflation:      {inflation_score:3d}/100")
    print(f"    Fed Policy:     {fed_score:3d}/100")
    print(f"    Liquidity:      {liquidity_score:3d}/100")
    print(f"    DXY:            {dxy_score:3d}/100")
    print(f"    Risk Sentiment: {risk_score:3d}/100")
    print(f"    ─────────────────────────")
    print(f"    Weighted Total: {weighted_score:3d}/100")
    print()
    print(f"  ── Headline Adjustment ──")
    print(f"    Headlines analyzed: {len(headlines)}")
    print(f"    Adjustment:         {headline_adj:+d}")
    print()
    print(f"  ── Final Verdict ──")
    print(f"    SCORE:      {verdict['final_score']}/100")
    print(f"    BIAS:       {verdict['bias']}")
    print(f"    ACTION:     {verdict['action']}")
    print(f"    CONFIDENCE: {verdict['confidence_pct']}% ({verdict['confidence_label']})")
    print("=" * 70)
    
    if freshness_report.warnings:
        print("\n  ⚠️  Warnings:")
        for w in freshness_report.warnings:
            print(f"     • {w}")
    
    print()
    return snapshot


if __name__ == "__main__":
    import sys
    
    # Support command line timeframe argument
    timeframe = "current"
    if len(sys.argv) > 1:
        tf_arg = sys.argv[1].lower()
        if tf_arg in ["current", "week", "month", "year"]:
            timeframe = tf_arg
        else:
            print(f"Invalid timeframe: {tf_arg}. Using 'current'.")
            print("Valid timeframes: current, week, month, year")
    
    try:
        result = run_analysis(timeframe)
        print(f"\n✅ Analysis completed successfully (timeframe: {timeframe})")
        print(f"Final Score: {result.get('final_score', 'N/A')}/100")
        print(f"Bias: {result.get('bias', 'N/A')}")
    except SystemExit:
        # Already handled in run_analysis
        pass
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        print(f"\n❌ Analysis failed: {e}")
        sys.exit(2)


if __name__ == "__main__":
    try:
        run_analysis()
        sys.exit(0)
    except SystemExit:
        raise
    except Exception as e:
        logger.exception(f"Unrecoverable error: {e}")
        print(f"\n❌ FATAL ERROR: {e}")
        sys.exit(2)
