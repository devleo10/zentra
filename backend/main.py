"""
FastAPI server for BTC Macro AI Agent
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
import os

from models.schemas import (
    AnalysisRequest, VerdictResponse, HealthResponse, SectionScore, TimeFrame
)
from agents.orchestrator import AgentOrchestrator

load_dotenv()

app = FastAPI(
    title="BTC Macro AI Agent API",
    description="AI agentic system for Bitcoin macro analysis",
    version="1.0.0"
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

# Initialize orchestrator (lazy - won't fail if vector store missing)
orchestrator = None

def get_orchestrator():
    """Get orchestrator instance (lazy initialization)"""
    global orchestrator
    if orchestrator is None:
        try:
            orchestrator = AgentOrchestrator()
        except Exception as e:
            raise HTTPException(
                status_code=503,
                detail=f"Orchestrator initialization failed: {str(e)}. Please ensure vector store is initialized."
            )
    return orchestrator


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "BTC Macro AI Agent API",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "/api/analyze": "Run full analysis",
            "/api/analyze/{section}": "Run single section",
            "/api/health": "Health check",
            "/api/demo": "Demo analysis (works without vector store)"
        }
    }


@app.get("/api/demo", response_model=VerdictResponse)
async def demo_analysis():
    """Demo endpoint that returns sample analysis without requiring vector store"""
    from models.schemas import (
        VerdictResponse, SectionScore, BiasType, ActionType, 
        RegimeType, ConfidenceLevel, ValidatedSignal, DataSource, SignalValidationStatus
    )
    from datetime import datetime
    from agents.signal_validator import SignalValidator
    
    # Create sample data sources
    validator = SignalValidator()
    sample_source = validator.create_data_source("Demo", "DEMO", data_as_of=datetime.now())
    
    # Return sample data for demonstration with full validation metadata
    sample_sections = [
        SectionScore(
            name="Inflation & Economy",
            score=65,
            signals=["CPI MoM falling", "Oil stable", "PMI above 50"],
            validated_signals=[
                ValidatedSignal(
                    name="CPI MoM falling",
                    value=3.2,
                    previous_value=3.5,
                    trend_direction="down",
                    validation_status=SignalValidationStatus.VALIDATED,
                    validation_check="mom_change < -0.1%",
                    validation_result=True,
                    score_contribution=15.0,
                    data_source=sample_source
                )
            ],
            reasoning="Inflation trending down but still above target. Growth stable.",
            data_used={},
            data_sources=[sample_source],
            validation_summary={"validated": 1, "total_signals": 1}
        ),
        SectionScore(
            name="Federal Reserve Signals",
            score=70,
            signals=["Fed said 'data dependent'", "Rate cut expectations rising"],
            validated_signals=[],
            reasoning="Dovish tone detected. Multiple pivot signal keywords found.",
            data_used={},
            data_sources=[sample_source],
            validation_summary={}
        ),
        SectionScore(
            name="Liquidity & Bonds",
            score=55,
            signals=["10Y yield falling", "Yield curve steepening"],
            validated_signals=[],
            reasoning="Liquidity conditions improving but not yet expansive.",
            data_used={},
            data_sources=[sample_source],
            validation_summary={}
        ),
        SectionScore(
            name="US Dollar (DXY)",
            score=60,
            signals=["DXY weakening 7D trend", "Negative BTC-DXY correlation"],
            validated_signals=[],
            reasoning="Dollar showing weakness, favorable for BTC.",
            data_used={},
            data_sources=[sample_source],
            validation_summary={}
        ),
        SectionScore(
            name="Risk Sentiment",
            score=58,
            signals=["VIX at 18", "S&P 500 near highs", "Gold stable"],
            validated_signals=[],
            reasoning="Mixed risk environment. Equities strong but caution present.",
            data_used={},
            data_sources=[sample_source],
            validation_summary={}
        ),
        SectionScore(
            name="Bitcoin Focus",
            score=72,
            signals=["BTC above 200 DMA", "BTC dominance rising", "Stablecoin inflow"],
            validated_signals=[],
            reasoning="BTC structure bullish. Outperforming stocks. Accumulation signals.",
            data_used={},
            data_sources=[sample_source],
            validation_summary={}
        )
    ]
    
    verdict = VerdictResponse(
        timestamp=datetime.now(),
        data_timestamp=datetime.now(),
        timeframe=TimeFrame.CURRENT,
        sections=sample_sections,
        final_score=63,
        bias=BiasType.BULLISH,
        action=ActionType.HOLD_ADD_DIPS,
        confidence_score=65.0,
        confidence=ConfidenceLevel.MEDIUM_HIGH,
        summary="Macro conditions favor BTC. Fed pivoting dovish, dollar weakening, BTC structure strong. Score 63/100 = Bullish bias.",
        regime=RegimeType.EASING,
        dominant_signals=["Inflation & Economy: CPI MoM falling", "Federal Reserve Signals: Dovish tone"],
        invalidation_conditions=["If Fed signals shift from dovish to hawkish", "If DXY strengthens significantly"],
        score_breakdown={},
        signal_agreement_pct=70.0,
        data_freshness_score=95.0,
        audit_log={}
    )
    
    return verdict


@app.post("/api/analyze", response_model=VerdictResponse)
async def analyze(request: AnalysisRequest = None):
    """
    Run full 7-section analysis with optional timeframe filter
    
    Timeframe options: current (real-time), week (7d), month (30d), year (365d)
    Returns complete verdict with all section scores and final bias
    """
    try:
        if request is None:
            request = AnalysisRequest()
        sections = request.sections
        timeframe = request.timeframe
        verdict = get_orchestrator().run_full_analysis(sections=sections, timeframe=timeframe)
        return verdict
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


@app.get("/api/analyze/{section}", response_model=SectionScore)
async def analyze_section(section: str, timeframe: TimeFrame = TimeFrame.CURRENT):
    """
    Run analysis for a single section with optional timeframe
    
    Available sections: inflation, fed, liquidity, dxy, risk, bitcoin
    Timeframe options: current (real-time), week (7d), month (30d), year (365d)
    """
    try:
        score = get_orchestrator().run_single_section(section, timeframe=timeframe)
        return score
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


@app.get("/api/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    services = {}
    
    # Check LLM API key (OpenAI only)
    services["llm"] = "ok" if os.getenv("OPENAI_API_KEY") else "missing_key"
    
    # Check FRED API key
    services["fred"] = "ok" if os.getenv("FRED_API_KEY") else "missing_key"
    
    # Check NewsAPI key (optional)
    services["newsapi"] = "ok" if os.getenv("NEWS_API_KEY") else "optional"
    services["alphavantage"] = "ok" if (os.getenv("ALPHAVANTAGE_API_KEY") or os.getenv("ALPHA_VANTAGE_API_KEY")) else "optional"
    services["finnhub"] = "ok" if os.getenv("FINNHUB_API_KEY") else "optional"
    
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

