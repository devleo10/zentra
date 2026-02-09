"""
FastAPI server for BTC Macro AI Agent
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
import os

from models.schemas import (
    AnalysisRequest, VerdictResponse, HealthResponse, SectionScore
)
from agents.orchestrator import AgentOrchestrator

load_dotenv()

app = FastAPI(
    title="BTC Macro AI Agent API",
    description="AI agentic system for Bitcoin macro analysis",
    version="1.0.0"
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

# Initialize orchestrator
orchestrator = AgentOrchestrator()


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "BTC Macro AI Agent API",
        "version": "1.0.0",
        "endpoints": {
            "/api/analyze": "Run full analysis",
            "/api/analyze/{section}": "Run single section",
            "/api/health": "Health check"
        }
    }


@app.post("/api/analyze", response_model=VerdictResponse)
async def analyze(request: AnalysisRequest = None):
    """
    Run full 7-section analysis
    
    Returns complete verdict with all section scores and final bias
    """
    try:
        sections = request.sections if request else None
        verdict = orchestrator.run_full_analysis(sections=sections)
        return verdict
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


@app.get("/api/analyze/{section}", response_model=SectionScore)
async def analyze_section(section: str):
    """
    Run analysis for a single section
    
    Available sections: inflation, fed, liquidity, dxy, risk, bitcoin
    """
    try:
        score = orchestrator.run_single_section(section)
        return score
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


@app.get("/api/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    services = {}
    
    # Check OpenAI API key
    services["openai"] = "ok" if os.getenv("OPENAI_API_KEY") else "missing_key"
    
    # Check FRED API key
    services["fred"] = "ok" if os.getenv("FRED_API_KEY") else "missing_key"
    
    # Check NewsAPI key (optional)
    services["newsapi"] = "ok" if os.getenv("NEWS_API_KEY") else "optional"
    
    # Check if vector store exists
    from pathlib import Path
    faiss_db = Path(__file__).parent / "faiss_db"
    services["vector_store"] = "ok" if faiss_db.exists() else "not_initialized"
    
    status = "healthy" if all(
        v in ["ok", "optional"] for v in services.values()
    ) else "degraded"
    
    return HealthResponse(
        status=status,
        services=services
    )


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("BACKEND_PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

