"""
Laya HTTP Server — Jev/TypeSafe SystemOne compatible endpoint.
Drop-in replacement for Jev API: POST /v1/systemone
"""

import os
import json
from typing import Dict, Any, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn

from laya import Router


# Global router instance
router: Optional[Router] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global router
    # Preload all checkpoints on startup
    device = os.getenv("LAYA_DEVICE", "cpu")  # Default to CPU since CUDA not available
    models_to_preload = os.getenv("LAYA_MODELS", "english,multilingual,typed-decisions").split(",")
    
    router = Router(preload=True, device=device)
    
    # Optionally preload specific models
    for model in models_to_preload:
        model = model.strip()
        if model:
            try:
                router.preload([model])
            except Exception as e:
                print(f"Warning: failed to preload {model}: {e}")
    
    loaded_models = list(router.loaded) if hasattr(router, 'loaded') and router.loaded else []
    print(f"Laya server started on {os.getenv('LAYA_HOST', '0.0.0.0')}:{os.getenv('LAYA_PORT', '8000')}")
    print(f"Device: {device}, Preloaded: {loaded_models}")
    
    yield
    
    # Cleanup
    if router:
        router.unload()


app = FastAPI(
    title="Laya SystemOne API",
    description="Jev-compatible calibrated probabilistic judgment endpoint",
    version="0.1.0",
    lifespan=lifespan,
)


class SystemOneRequest(BaseModel):
    """Request matching TypeSafe SystemOne API."""
    state: Dict[str, Any]
    model: Optional[str] = None
    questions: Dict[str, Dict[str, Any]]


class SystemOneResponse(BaseModel):
    """Response matching TypeSafe SystemOne API."""
    model: str
    answers: Dict[str, Dict[str, Any]]
    usage: Dict[str, int]
    routing: Optional[Dict[str, Any]] = None


@app.post("/v1/systemone", response_model=SystemOneResponse)
async def system_one(request: SystemOneRequest):
    """
    Jev-compatible SystemOne endpoint.
    
    Accepts:
    - state: input state (text, JSON, etc.)
    - model: optional explicit model (english, multilingual, typed-decisions)
    - questions: dict of typed questions (choice, score, noul)
    
    Returns:
    - model: checkpoint used
    - answers: dict with type, noul/score/choice, confidence
    - usage: token counts
    - routing: routing metadata (optional)
    """
    if router is None:
        raise HTTPException(status_code=503, detail="Router not initialized")
    
    try:
        # Call Laya's system_one method
        result = router.system_one(
            state=request.state,
            questions=request.questions,
            model=request.model
        )
        
        return SystemOneResponse(**result)
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health():
    loaded_models = list(router.loaded) if router and hasattr(router, 'loaded') and router.loaded else []
    return {"status": "ok", "loaded_models": loaded_models}


@app.get("/models")
async def models():
    loaded_models = list(router.loaded) if router and hasattr(router, 'loaded') and router.loaded else []
    return {
        "available": ["english", "multilingual", "typed-decisions"],
        "loaded": loaded_models,
    }


if __name__ == "__main__":
    host = os.getenv("LAYA_HOST", "0.0.0.0")
    port = int(os.getenv("LAYA_PORT", "8000"))
    uvicorn.run(app, host=host, port=port)
