"""
Oracle Layer — REST API Server
FastAPI-based REST API for Oracle signals
"""

from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime
import asyncio

from ..core.config import settings
from ..fusion.engine import FusionEngine, OracleSignal, run_fusion_scan
from ..distribution.calibration_api import router as calibration_router

app = FastAPI(
    title="Oracle Layer API",
    description="Real-time calibrated prediction market intelligence with generative explanations",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include calibration monitoring routes
app.include_router(calibration_router)


class SignalResponse(BaseModel):
    signal_id: str
    timestamp: datetime
    market_id: str
    question: str
    category: str
    fused_probability_up: float
    fused_confidence: float
    macro_signal_strength: str
    market_signal_strength: str
    key_drivers: List[str]
    risk_factors: List[str]
    explainer_available: bool


class ScanRequest(BaseModel):
    category: str = "fed-rate-decisions"
    top_k: int = 5


class ScanResponse(BaseModel):
    signals: List[SignalResponse]
    scanned_at: datetime
    category: str


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "oracle-layer-api", "timestamp": datetime.now().isoformat()}


@app.get("/api/v1/signals/{condition_id}", response_model=SignalResponse)
async def get_signal(condition_id: str):
    """Get fused signal for a specific market."""
    engine = FusionEngine()
    try:
        signal = await engine.process_market(condition_id)
        return SignalResponse(
            signal_id=signal.signal_id,
            timestamp=signal.timestamp,
            market_id=signal.market_id,
            question=signal.question,
            category=signal.category,
            fused_probability_up=signal.fused_probability_up,
            fused_confidence=signal.fused_confidence,
            macro_signal_strength=signal.macro_signal_strength.value,
            market_signal_strength=signal.market_signal_strength.value,
            key_drivers=signal.key_drivers,
            risk_factors=signal.risk_factors,
            explainer_available=signal.explainer_script is not None,
        )
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))
    finally:
        await engine.close()


@app.post("/api/v1/scan", response_model=ScanResponse)
async def scan_category(request: ScanRequest):
    """Scan a category for top signals."""
    try:
        signals = await run_fusion_scan(request.category, request.top_k)
        return ScanResponse(
            signals=[
                SignalResponse(
                    signal_id=s.signal_id,
                    timestamp=s.timestamp,
                    market_id=s.market_id,
                    question=s.question,
                    category=s.category,
                    fused_probability_up=s.fused_probability_up,
                    fused_confidence=s.fused_confidence,
                    macro_signal_strength=s.macro_signal_strength.value,
                    market_signal_strength=s.market_signal_strength.value,
                    key_drivers=s.key_drivers,
                    risk_factors=s.risk_factors,
                    explainer_available=s.explainer_script is not None,
                )
                for s in signals
            ],
            scanned_at=datetime.now(),
            category=request.category,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/categories")
async def list_categories():
    """List available market categories."""
    return {
        "categories": [
            "fed-rate-decisions",
            "cpi-inflation",
            "crypto-prices",
            "election-politics",
            "climate-weather",
            "tech-ai-milestones",
            "geopolitics",
            "earnings-economy",
        ]
    }


@app.get("/api/v1/markets/{condition_id}/explainer")
async def get_explainer(condition_id: str):
    """Get explainer script for a market signal."""
    engine = FusionEngine()
    try:
        signal = await engine.process_market(condition_id)
        if not signal.explainer_script:
            raise HTTPException(status_code=404, detail="No explainer available for this signal")
        return signal.explainer_script.dict()
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))
    finally:
        await engine.close()


# Background task for periodic scans
async def periodic_scan_task():
    """Background task to run periodic scans and cache results."""
    while True:
        try:
            for category in ["fed-rate-decisions", "cpi-inflation", "crypto-prices"]:
                await run_fusion_scan(category, top_k=10)
        except Exception as e:
            print(f"Periodic scan failed: {e}")
        await asyncio.sleep(300)  # Every 5 minutes


def start_api_server():
    """Start the API server."""
    import uvicorn
    uvicorn.run(
        "oracle.distribution.api:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.environment == "development",
    )


# For background task management
_background_tasks = []


def start_background_tasks():
    """Start background periodic tasks."""
    global _background_tasks
    _background_tasks.append(asyncio.create_task(periodic_scan_task()))


def stop_background_tasks():
    """Stop background tasks."""
    global _background_tasks
    for task in _background_tasks:
        task.cancel()
    _background_tasks.clear()
