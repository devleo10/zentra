"""
FastAPI server for BTC Macro AI Agent — v2 (Deterministic Engine)

This is the NEW deterministic-only server.
- Does NOT depend on legacy LangChain agents
- Uses config-driven numeric scoring
- LLM only for headline classification (temperature=0)
"""
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from pathlib import Path
import os
import sys
import json
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from enum import Enum
import threading
import time

# Ensure backend is on the path
sys.path.insert(0, str(Path(__file__).parent))

load_dotenv()

logger = logging.getLogger("btc_macro.api")

# Guard against broken system proxy env vars (e.g. HTTP_PROXY=http://127.0.0.1:9)
try:
    from utils.proxy_guard import sanitize_proxy_env
    sanitize_proxy_env()
except Exception:
    pass

from auth_dashboard import (
    dashboard_auth_enabled,
    issue_token,
    require_dashboard_user,
    token_ttl_seconds,
    verify_credentials,
)


class LoginRequest(BaseModel):
    client_id: str = Field(..., min_length=1)
    client_secret: str = Field(..., min_length=1)


_VALID_TIMEFRAMES = ("current", "week", "month")
_TIMEFRAME_UI_LABEL = {"current": "Now", "week": "7D", "month": "1M"}


def _timeframe_ui_label(timeframe: str) -> str:
    return _TIMEFRAME_UI_LABEL.get(timeframe, timeframe)


_ANALYSIS_CACHE_TTL_SECONDS = int(os.getenv("ANALYSIS_CACHE_TTL_SECONDS", "120"))
_ANALYSIS_RUNNING_RETRY_AFTER_SECONDS = int(os.getenv("ANALYSIS_RUNNING_RETRY_AFTER_SECONDS", "15"))
_ANALYSIS_SNAPSHOT_TTL_SECONDS = int(os.getenv("ANALYSIS_SNAPSHOT_TTL_SECONDS", "1800"))
_analysis_lock = threading.Lock()
_analysis_state: Dict[str, Dict[str, Any]] = {
    tf: {
        "in_progress": False,
        "started_at": None,
        "last_result": None,
        "last_completed_at": None,
        "last_error": None,
    }
    for tf in _VALID_TIMEFRAMES
}


def _cache_age_seconds(last_completed_at: Optional[float]) -> Optional[int]:
    if last_completed_at is None:
        return None
    return max(0, int(time.time() - float(last_completed_at)))


def _parse_json_fields_in_snapshot(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    for key in ["section_scores", "section_reasoning", "score_breakdown",
                "headlines_classified", "data_freshness_info",
                "headline_report_meta"]:
        if isinstance(snapshot.get(key), str):
            try:
                snapshot[key] = json.loads(snapshot[key])
            except (json.JSONDecodeError, TypeError):
                pass
    return snapshot


def _latest_snapshot_for_timeframe(timeframe: str) -> Optional[Dict[str, Any]]:
    """Read latest persisted snapshot for timeframe from SQLite."""
    try:
        from storage.db import get_latest_snapshots
        rows = get_latest_snapshots(limit=50)
        for row in rows:
            if row.get("timeframe") == timeframe:
                return _parse_json_fields_in_snapshot(dict(row))
    except Exception:
        logger.exception("Failed to read latest snapshot for timeframe=%s", timeframe)
    return None


def _snapshot_is_fresh_enough(snapshot: Optional[Dict[str, Any]], ttl_seconds: int) -> bool:
    if not snapshot:
        return False
    ts = snapshot.get("timestamp")
    if not ts:
        return False
    try:
        dt = datetime.fromisoformat(str(ts))
        age = (datetime.now() - dt).total_seconds()
        return age >= 0 and age <= ttl_seconds
    except Exception:
        return False


def _run_analysis_background(timeframe: str, fresh: bool = False) -> None:
    """Execute analysis in a background thread and cache the result."""
    error_payload = None
    try:
        from run_analysis import run_analysis as _run
        result = _run(timeframe=timeframe, fresh=fresh)
    except BaseException as e:
        import traceback
        traceback.print_exc()
        result = None
        try:
            parsed = json.loads(str(e))
            if isinstance(parsed, dict):
                error_payload = parsed
        except Exception:
            error_payload = None
        if error_payload is None:
            error_payload = {
                "error": "analysis_failed",
                "message": str(e) or "Analysis failed.",
                "timeframe": timeframe,
            }
    finally:
        with _analysis_lock:
            state = _analysis_state[timeframe]
            state["in_progress"] = False
            state["started_at"] = None
            if result is not None:
                state["last_result"] = result
                state["last_completed_at"] = time.time()
                state["last_error"] = None
            else:
                state["last_error"] = error_payload


def _analyze_with_guard(timeframe: str, fresh: bool = False) -> JSONResponse:
    now = time.time()
    with _analysis_lock:
        state = _analysis_state[timeframe]
        already_running = state.get("in_progress", False)

        # Complete-only mode: while analysis is running, never emit stale/partial data.
        if already_running:
            retry_after = _ANALYSIS_RUNNING_RETRY_AFTER_SECONDS
            label = _timeframe_ui_label(timeframe)
            detail = {
                "status": "in_progress",
                "error": "analysis_already_running",
                "message": (
                    f"Still computing the {label} analysis on the server. "
                    "The dashboard polls every few seconds until it is done—this is normal, not a conflict."
                ),
                "retry_after_seconds": retry_after,
                "timeframe": timeframe,
            }
            return JSONResponse(
                content=detail,
                status_code=202,
                headers={"Retry-After": str(retry_after), "X-Refresh-Status": "in_progress"},
            )

        last_completed = state.get("last_completed_at")
        cache_age = _cache_age_seconds(last_completed)
        if (
            not fresh
            and state.get("last_result") is not None
            and cache_age is not None
            and cache_age <= _ANALYSIS_CACHE_TTL_SECONDS
        ):
            headers = {
                "X-Analysis-Cache": "HIT",
                "X-Cache-Age-Seconds": str(cache_age),
            }
            return JSONResponse(content=state["last_result"], status_code=200, headers=headers)

        if not fresh:
            persisted = _latest_snapshot_for_timeframe(timeframe)
            if _snapshot_is_fresh_enough(persisted, _ANALYSIS_SNAPSHOT_TTL_SECONDS):
                age_seconds = int((datetime.now() - datetime.fromisoformat(str(persisted["timestamp"]))).total_seconds())
                headers = {
                    "X-Analysis-Cache": "SNAPSHOT_HIT",
                    "X-Cache-Age-Seconds": str(max(0, age_seconds)),
                }
                return JSONResponse(content=persisted, status_code=200, headers=headers)

        if not fresh and state.get("last_error") is not None:
            err = dict(state["last_error"])
            err.setdefault("timeframe", timeframe)
            return JSONResponse(content=err, status_code=503)

        # Mark in-progress *before* checking for a stale snapshot to return
        state["in_progress"] = True
        state["started_at"] = now
        state["last_error"] = None

    # Kick off the analysis in a background thread so we can respond quickly.
    thread = threading.Thread(
        target=_run_analysis_background,
        args=(timeframe, fresh),
        daemon=True,
    )
    thread.start()

    # Return in-progress while background run proceeds (complete-only: no stale snapshot response).
    retry_after = _ANALYSIS_RUNNING_RETRY_AFTER_SECONDS
    label = _timeframe_ui_label(timeframe)
    return JSONResponse(
        content={
            "status": "in_progress",
            "message": (
                f"{label} analysis started on the server. "
                "Keep this page open; results will appear when the run finishes."
            ),
            "retry_after_seconds": retry_after,
            "timeframe": timeframe,
        },
        status_code=202,
        headers={"Retry-After": str(retry_after), "X-Refresh-Status": "in_progress"},
    )


# ═══════════════════════════════════════════════════════════════════════════
#  PYDANTIC MODELS (inline to avoid legacy imports)
# ═══════════════════════════════════════════════════════════════════════════

class TimeFrame(str, Enum):
    CURRENT = "current"
    WEEK = "week"
    MONTH = "month"


class AnalysisRequest(BaseModel):
    sections: Optional[List[str]] = None
    timeframe: TimeFrame = TimeFrame.CURRENT


class HealthResponse(BaseModel):
    status: str
    timestamp: datetime = Field(default_factory=datetime.now)
    services: Dict[str, str] = Field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════════════
#  FASTAPI APP
# ═══════════════════════════════════════════════════════════════════════════

app = FastAPI(
    title="BTC Macro AI Agent API",
    description="AI agentic system for Bitcoin macro analysis — v2 deterministic engine",
    version="2.0.0"
)

# CORS — browser dashboard on Vercel / localhost (no cookies on API calls).
# CORS_ORIGINS: comma-separated exact origins, e.g. https://zentra01.vercel.app,http://localhost:3000
# CORS_ORIGIN_REGEX: optional; matches extra origins (e.g. all Vercel previews):
#   https://.*\.vercel\.app
_cors_raw = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:3000,http://localhost:3001",
)
cors_origins = [o.strip() for o in _cors_raw.split(",") if o.strip()]
if not cors_origins:
    cors_origins = ["http://localhost:3000", "http://localhost:3001"]
_cors_re = os.getenv("CORS_ORIGIN_REGEX", "").strip() or None
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_origin_regex=_cors_re,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    max_age=600,
)
logger.info(
    "CORS: origins=%s regex=%s credentials=False",
    cors_origins,
    _cors_re or "(none)",
)


# ═══════════════════════════════════════════════════════════════════════════
#  Dashboard auth (optional — enabled when DASHBOARD_CLIENT_ID + SECRET are set)
# ═══════════════════════════════════════════════════════════════════════════


@app.get("/api/auth/status")
async def api_auth_status():
    """Whether the API requires a Bearer token for protected routes."""
    return {"auth_required": dashboard_auth_enabled()}


@app.post("/api/auth/login")
async def api_auth_login(body: LoginRequest):
    """
    Exchange login ID + password (JSON: client_id, client_secret) for a Bearer token.
    Disabled when env credentials are not configured (local dev).
    """
    if not dashboard_auth_enabled():
        return {
            "access_token": None,
            "token_type": "bearer",
            "expires_in": 0,
            "auth_required": False,
        }
    if not verify_credentials(body.client_id.strip(), body.client_secret):
        raise HTTPException(status_code=401, detail="Invalid login ID or password")
    tok = issue_token(body.client_id.strip())
    return {
        "access_token": tok,
        "token_type": "bearer",
        "expires_in": token_ttl_seconds(),
        "auth_required": True,
    }


# ═══════════════════════════════════════════════════════════════════════════
#  v2 DETERMINISTIC ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/api/v2/analyze")
async def v2_analyze(
    timeframe: str = "current",
    fresh: bool = False,
    _auth: Optional[Dict[str, Any]] = Depends(require_dashboard_user),
):
    """
    Run the deterministic analysis pipeline with timeframe support.
    
    Args:
        timeframe: Analysis timeframe - 'current', 'week', or 'month'
        fresh: If True, clear cached news/LLM intermediates before running.
               Live market prices are fetched fresh either way.
    
    This is the new engine:
    - Numeric scoring is 100% deterministic (zero LLM)
    - LLM is used ONLY for headline classification (temperature=0)
    - All weights from config/scoring_weights.json
    - Result is stored to SQLite automatically
    - Returns full audit trail
    """
    # Validate timeframe
    if timeframe not in _VALID_TIMEFRAMES:
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid timeframe: {timeframe}. Must be one of: current, week, month"
        )
    return _analyze_with_guard(timeframe=timeframe, fresh=fresh)


@app.get("/api/v2/analyze/compare")
async def v2_compare_timeframes(
    timeframes: str = "current,week,month",
    _auth: Optional[Dict[str, Any]] = Depends(require_dashboard_user),
):
    """
    Compare analysis across multiple timeframes.
    
    Args:
        timeframes: Comma-separated timeframes to compare (e.g., "current,week,month")
    
    Returns:
        Comparative analysis across specified timeframes
    """
    try:
        # Parse and validate timeframes
        tf_list = [tf.strip() for tf in timeframes.split(",")]
        valid_timeframes = ["current", "week", "month"]
        
        for tf in tf_list:
            if tf not in valid_timeframes:
                raise HTTPException(
                    status_code=400, 
                    detail=f"Invalid timeframe: {tf}. Must be one of: {', '.join(valid_timeframes)}"
                )
        
        from run_analysis import run_analysis as _run
        results = {}
        
        for tf in tf_list:
            try:
                results[tf] = _run(timeframe=tf)
            except Exception as e:
                logger.error(f"Failed to analyze timeframe {tf}: {e}")
                results[tf] = {"error": str(e)}
        
        # Add comparison summary
        comparison = {
            "timeframes_analyzed": tf_list,
            "results": results,
            "summary": _generate_comparison_summary(results),
            "generated_at": datetime.now().isoformat()
        }
        
        return JSONResponse(content=comparison, status_code=200)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Timeframe comparison error: {e}")
        raise HTTPException(status_code=500, detail=f"Comparison failed: {str(e)}")


@app.get("/api/v2/analyze/{timeframe}")
async def v2_analyze_timeframe(
    timeframe: str,
    fresh: bool = False,
    _auth: Optional[Dict[str, Any]] = Depends(require_dashboard_user),
):
    """
    Run analysis for a specific timeframe via GET request.

    Must be registered AFTER /api/v2/analyze/compare so FastAPI does not
    capture 'compare' as a timeframe path parameter.

    Args:
        timeframe: Analysis timeframe - 'current', 'week', or 'month'
        fresh: If True, clear cached news/LLM intermediates before running.
    """
    if timeframe not in _VALID_TIMEFRAMES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid timeframe: {timeframe}. Must be one of: current, week, month"
        )
    return _analyze_with_guard(timeframe=timeframe, fresh=fresh)


def _generate_comparison_summary(results: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate a summary comparing results across timeframes.
    """
    valid_results = {k: v for k, v in results.items() if "error" not in v}
    
    if not valid_results:
        return {"error": "No valid results to compare"}
    
    # Extract scores and biases
    scores = {tf: result.get("final_score", 50) for tf, result in valid_results.items()}
    biases = {tf: result.get("bias", "Unknown") for tf, result in valid_results.items()}
    confidence_scores = {tf: result.get("confidence_pct", 50) for tf, result in valid_results.items()}
    
    # Calculate trends
    score_values = list(scores.values())
    if len(score_values) >= 2:
        score_trend = "improving" if score_values[-1] > score_values[0] else "deteriorating" if score_values[-1] < score_values[0] else "stable"
        score_volatility = max(score_values) - min(score_values)
    else:
        score_trend = "insufficient_data"
        score_volatility = 0
    
    # Check bias consistency
    unique_biases = set(biases.values())
    bias_consistent = len(unique_biases) == 1
    
    # Average confidence
    avg_confidence = sum(confidence_scores.values()) / len(confidence_scores) if confidence_scores else 0
    
    return {
        "score_analysis": {
            "scores": scores,
            "trend": score_trend,
            "volatility": score_volatility,
            "range": f"{min(score_values)}-{max(score_values)}" if score_values else "N/A"
        },
        "bias_analysis": {
            "biases": biases,
            "consistent": bias_consistent,
            "unique_biases": list(unique_biases)
        },
        "confidence_analysis": {
            "scores": confidence_scores,
            "average": round(avg_confidence, 1),
            "stability": "high" if max(confidence_scores.values()) - min(confidence_scores.values()) < 10 else "medium" if max(confidence_scores.values()) - min(confidence_scores.values()) < 25 else "low"
        },
        "recommendation": _generate_timeframe_recommendation(scores, biases, avg_confidence)
    }


def _generate_timeframe_recommendation(scores: Dict, biases: Dict, avg_confidence: float) -> str:
    """
    Generate a recommendation based on timeframe comparison.
    """
    if not scores:
        return "Insufficient data for recommendation"
    
    score_values = list(scores.values())
    unique_biases = set(biases.values())
    
    if len(unique_biases) == 1:
        dominant_bias = list(unique_biases)[0]
        if avg_confidence > 70:
            return f"Strong consensus: {dominant_bias} bias across all timeframes with high confidence ({avg_confidence:.1f}%)"
        else:
            return f"Consensus: {dominant_bias} bias across timeframes but with moderate confidence ({avg_confidence:.1f}%)"
    else:
        volatility = max(score_values) - min(score_values)
        if volatility > 30:
            return "High uncertainty: Conflicting signals across timeframes suggest caution"
        else:
            return "Mixed signals: Consider focusing on longer-term trends for clearer direction"


@app.get("/api/v2/history")
async def v2_history(
    limit: int = 10,
    _auth: Optional[Dict[str, Any]] = Depends(require_dashboard_user),
):
    """Get past analysis snapshots from local SQLite."""
    try:
        from storage.db import get_latest_snapshots
        snapshots = get_latest_snapshots(limit=limit)
        # Parse JSON strings back to dicts
        for s in snapshots:
            for key in ["section_scores", "section_reasoning", "score_breakdown",
                        "headlines_classified", "data_freshness_info",
                        "headline_report_meta"]:
                if isinstance(s.get(key), str):
                    try:
                        s[key] = json.loads(s[key])
                    except (json.JSONDecodeError, TypeError):
                        pass
        return JSONResponse(content=snapshots, status_code=200)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"History retrieval failed: {str(e)}")


@app.get("/api/v2/history/{snapshot_id}")
async def v2_history_detail(
    snapshot_id: int,
    _auth: Optional[Dict[str, Any]] = Depends(require_dashboard_user),
):
    """Get a specific snapshot by ID."""
    try:
        from storage.db import get_snapshot_by_id
        snapshot = get_snapshot_by_id(snapshot_id)
        if not snapshot:
            raise HTTPException(status_code=404, detail=f"Snapshot {snapshot_id} not found")
        # Parse JSON strings
        for key in ["section_scores", "section_reasoning", "score_breakdown",
                     "headlines_classified", "data_freshness_info",
                     "headline_report_meta"]:
            if isinstance(snapshot.get(key), str):
                try:
                    snapshot[key] = json.loads(snapshot[key])
                except (json.JSONDecodeError, TypeError):
                    pass
        return JSONResponse(content=snapshot, status_code=200)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v2/config")
async def v2_config(_auth: Optional[Dict[str, Any]] = Depends(require_dashboard_user)):
    """Return the current scoring configuration (for transparency)."""
    try:
        config_path = Path(__file__).parent / "config" / "scoring_weights.json"
        with open(config_path, "r") as f:
            config = json.load(f)
        return JSONResponse(content=config, status_code=200)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════════════════════
#  GENERAL ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/")
async def root():
    return {
        "message": "BTC Macro AI Agent API",
        "version": "2.0.0",
        "status": "running",
        "endpoints": {
            "/api/auth/status": "Whether Bearer auth is required",
            "/api/auth/login": "Login ID + password → Bearer token (when auth enabled)",
            "/api/v2/analyze": "Run deterministic analysis (recommended)",
            "/api/v2/analyze/{timeframe}": "Run analysis for specific timeframe (current/week/month)",
            "/api/v2/analyze/compare": "Compare analysis across multiple timeframes",
            "/api/v2/history": "View past analysis results",
            "/api/v2/config": "View scoring configuration",
            "/api/health": "Health check",
        },
        "timeframes": ["current", "week", "month"],
        "examples": {
            "single_timeframe": "/api/v2/analyze/week",
            "compare_timeframes": "/api/v2/analyze/compare?timeframes=current,week,month"
        }
    }


@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    services = {}

    services["llm"] = "ok" if os.getenv("OPENAI_API_KEY") else "missing_key"

    services["fred"] = "ok" if os.getenv("FRED_API_KEY") else "missing_key"
    services["bls"] = "ok" if os.getenv("BLS_API_KEY") else "optional (FRED fallback available)"
    services["newsapi"] = "ok" if os.getenv("NEWS_API_KEY") else "optional (Google RSS fallback available)"
    services["alphavantage"] = "ok" if (os.getenv("ALPHAVANTAGE_API_KEY") or os.getenv("ALPHA_VANTAGE_API_KEY")) else "optional"
    services["finnhub"] = "ok" if os.getenv("FINNHUB_API_KEY") else "optional"

    sqlite_db = Path(__file__).parent / "storage" / "macro_snapshots.db"
    services["sqlite_db"] = "ok" if sqlite_db.exists() else "will_be_created_on_first_run"

    config_path = Path(__file__).parent / "config" / "scoring_weights.json"
    services["scoring_config"] = "ok" if config_path.exists() else "MISSING"

    status = "healthy" if services.get("fred") == "ok" else "degraded"

    return {
        "status": status,
        "timestamp": datetime.now().isoformat(),
        "services": services
    }


@app.get("/api/keepalive")
async def keepalive():
    """Lightweight endpoint for external uptime pingers (e.g., Render cron/UptimeRobot)."""
    logger.info("Keepalive ping received")
    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "service": "btc_macro_api",
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("BACKEND_PORT") or os.getenv("PORT") or 8001)
    uvicorn.run(app, host="0.0.0.0", port=port)
