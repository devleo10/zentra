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
cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
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
async def v2_analyze():
    """
    Run the deterministic analysis pipeline.
    
    This is the new engine:
    - Numeric scoring is 100% deterministic (zero LLM)
    - LLM is used ONLY for headline classification (temperature=0)
    - All weights from config/scoring_weights.json
    - Result is stored to SQLite automatically
    - Returns full audit trail
    """
    try:
        from run_analysis import run_analysis as _run
        result = _run()
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


@app.get("/api/v2/history")
async def v2_history(limit: int = 10):
    """Get past analysis snapshots from local SQLite."""
    try:
        from storage.db import get_latest_snapshots
        snapshots = get_latest_snapshots(limit=limit)
        # Parse JSON strings back to dicts
        for s in snapshots:
            for key in ["section_scores", "section_reasoning", "score_breakdown",
                        "headlines_classified", "data_freshness_info"]:
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
                     "headlines_classified", "data_freshness_info"]:
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
            "/api/v2/history": "View past analysis results",
            "/api/v2/config": "View scoring configuration",
            "/api/health": "Health check",
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
