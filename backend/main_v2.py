"""
FastAPI server for BTC Macro AI Agent — v2 (Deterministic Engine)

This is the NEW deterministic-only server.
- Does NOT depend on legacy LangChain agents
- Uses config-driven numeric scoring
- LLM only for headline classification (temperature=0)
"""
from fastapi import FastAPI, HTTPException
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

# Ensure backend is on the path
sys.path.insert(0, str(Path(__file__).parent))

load_dotenv()

logger = logging.getLogger("btc_macro.api")


# ═══════════════════════════════════════════════════════════════════════════
#  PYDANTIC MODELS (inline to avoid legacy imports)
# ═══════════════════════════════════════════════════════════════════════════

class TimeFrame(str, Enum):
    CURRENT = "current"
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"


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

# CORS middleware
cors_origins = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:3000,http://localhost:3001"
).split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ═══════════════════════════════════════════════════════════════════════════
#  v2 DETERMINISTIC ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/api/v2/analyze")
async def v2_analyze(timeframe: str = "current"):
    """
    Run the deterministic analysis pipeline with timeframe support.
    
    Args:
        timeframe: Analysis timeframe - 'current', 'week', 'month', or 'year'
    
    This is the new engine:
    - Numeric scoring is 100% deterministic (zero LLM)
    - LLM is used ONLY for headline classification (temperature=0)
    - All weights from config/scoring_weights.json
    - Result is stored to SQLite automatically
    - Returns full audit trail
    """
    # Validate timeframe
    if timeframe not in ["current", "week", "month", "year"]:
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid timeframe: {timeframe}. Must be one of: current, week, month, year"
        )
    
    try:
        from run_analysis import run_analysis as _run
        result = _run(timeframe=timeframe)
        return JSONResponse(content=result, status_code=200)
    except SystemExit as e:
        raise HTTPException(
            status_code=503,
            detail=f"Analysis aborted: critical data missing or stale (exit code {e.code})"
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


@app.get("/api/v2/analyze/compare")
async def v2_compare_timeframes(
    timeframes: str = "current,week,month"
):
    """
    Compare analysis across multiple timeframes.
    
    Args:
        timeframes: Comma-separated timeframes to compare (e.g., "current,week,month,year")
    
    Returns:
        Comparative analysis across specified timeframes
    """
    try:
        # Parse and validate timeframes
        tf_list = [tf.strip() for tf in timeframes.split(",")]
        valid_timeframes = ["current", "week", "month", "year"]
        
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
async def v2_analyze_timeframe(timeframe: str):
    """
    Run analysis for a specific timeframe via GET request.

    Must be registered AFTER /api/v2/analyze/compare so FastAPI does not
    capture 'compare' as a timeframe path parameter.

    Args:
        timeframe: Analysis timeframe - 'current', 'week', 'month', or 'year'
    """
    if timeframe not in ["current", "week", "month", "year"]:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid timeframe: {timeframe}. Must be one of: current, week, month, year"
        )

    try:
        from run_analysis import run_analysis as _run
        result = _run(timeframe=timeframe)
        return JSONResponse(content=result, status_code=200)
    except SystemExit as e:
        raise HTTPException(
            status_code=503,
            detail=f"Analysis aborted: critical data missing or stale (exit code {e.code})"
        )
    except Exception as e:
        logger.error(f"Analysis error for timeframe {timeframe}: {e}")
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


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
async def v2_history(limit: int = 10):
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
async def v2_history_detail(snapshot_id: int):
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
async def v2_config():
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
            "/api/v2/analyze": "Run deterministic analysis (recommended)",
            "/api/v2/analyze/{timeframe}": "Run analysis for specific timeframe (current/week/month/year)",
            "/api/v2/analyze/compare": "Compare analysis across multiple timeframes",
            "/api/v2/history": "View past analysis results",
            "/api/v2/config": "View scoring configuration",
            "/api/health": "Health check",
        },
        "timeframes": ["current", "week", "month", "year"],
        "examples": {
            "single_timeframe": "/api/v2/analyze/week",
            "compare_timeframes": "/api/v2/analyze/compare?timeframes=current,week,month"
        }
    }


@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    services = {}

    openai_key = os.getenv("OPENAI_API_KEY")
    gemini_key = os.getenv("GEMINI_API_KEY")
    if openai_key:
        services["llm"] = "ok (openai)"
    elif gemini_key:
        services["llm"] = "ok (gemini)"
    else:
        services["llm"] = "missing_key"

    services["fred"] = "ok" if os.getenv("FRED_API_KEY") else "missing_key"
    services["bls"] = "ok" if os.getenv("BLS_API_KEY") else "optional (FRED fallback available)"
    services["newsapi"] = "ok" if os.getenv("NEWS_API_KEY") else "optional (Google RSS fallback available)"

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


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("BACKEND_PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
