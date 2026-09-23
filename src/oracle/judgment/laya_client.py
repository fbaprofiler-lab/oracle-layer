"""
Oracle Layer — Laya Integration Client
Drop-in replacement for JevClient with local, calibrated, multilingual System 1 decisions.
Compatible with Jev/TypeSafe SystemOne API.
"""

import os
import asyncio
import json
from datetime import datetime
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from enum import Enum

# Optional: HTTP client for remote Laya server
import httpx


class LayaDecisionType(str, Enum):
    """Types of decisions Laya can make."""
    MARKET_MOVE = "market_move"
    PRICE_TARGET = "price_target"
    REGIME_CHANGE = "regime_change"
    LIQUIDITY_SHIFT = "liquidity_shift"
    SMART_MONEY_SIGNAL = "smart_money_signal"


@dataclass
class LayaInput:
    """Structured input for Laya judgment."""
    decision_type: LayaDecisionType
    market_id: str
    question: str
    features: Dict[str, Any]
    context: Dict[str, Any] = field(default_factory=dict)
    few_shots: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class LayaOutput:
    """Structured output from Laya judgment."""
    decision_id: str
    decision_type: LayaDecisionType
    market_id: str
    probability: float  # 0-1 calibrated
    confidence: float   # 0-1, how confident in the calibration
    reasoning: str
    key_drivers: List[str]
    risk_factors: List[str]
    timestamp: datetime = field(default_factory=datetime.now)
    calibration_metadata: Dict[str, Any] = field(default_factory=dict)
    routing_info: Dict[str, Any] = field(default_factory=dict)


class LayaClient:
    """
    Client for Laya System 1 decisions.
    Supports both local (Router) and remote (HTTP server) modes.
    Jev-compatible API for drop-in replacement.
    """

    def __init__(
        self,
        mode: str = "local",  # "local" or "remote"
        remote_url: str = "http://localhost:8000",
        preload: bool = True,
        device: str = "cpu",
        api_key: Optional[str] = None,
    ):
        self.mode = mode
        self.remote_url = remote_url
        self.preload = preload
        self.device = device
        self.api_key = api_key
        
        self._local_router = None
        self._http_client = None
        
        if mode == "local":
            self._init_local()
        elif mode == "remote":
            self._init_remote()
        else:
            raise ValueError(f"Unknown mode: {mode}")

    def _init_local(self):
        """Initialize local Laya Router."""
        from laya import Router
        self._local_router = Router(preload=self.preload, device=self.device)

    def _init_remote(self):
        """Initialize HTTP client for remote Laya server."""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        self._http_client = httpx.AsyncClient(
            timeout=30.0,
            headers=headers,
            base_url=self.remote_url
        )

    async def judge(self, input_data: LayaInput) -> LayaOutput:
        """Make a calibrated judgment using Laya."""
        
        # Build state from input
        state = self._build_state(input_data)
        questions = self._build_questions(input_data)
        model = self._select_model(input_data)
        
        if self.mode == "local":
            return await self._judge_local(state, questions, model, input_data)
        else:
            return await self._judge_remote(state, questions, model, input_data)

    def _build_state(self, input_data: LayaInput) -> Dict[str, Any]:
        """Build state dict for Laya from oracle-layer input."""
        # Include all relevant features in state
        state = {
            "market_id": input_data.market_id,
            "question": input_data.question,
            "features": input_data.features,
            "context": input_data.context,
        }
        return state

    def _build_questions(self, input_data: LayaInput) -> Dict[str, Dict[str, Any]]:
        """Build questions dict for Laya from decision type."""
        
        if input_data.decision_type == LayaDecisionType.MARKET_MOVE:
            return {
                "market_move": {
                    "type": "noul",
                    "instructions": "Will the YES probability increase in the next 24 hours?"
                }
            }
        elif input_data.decision_type == LayaDecisionType.PRICE_TARGET:
            target = input_data.features.get('target_price', 0.55)
            return {
                "price_target": {
                    "type": "noul",
                    "instructions": f"Will the YES outcome probability reach {target} within 48 hours?"
                }
            }
        elif input_data.decision_type == LayaDecisionType.SMART_MONEY_SIGNAL:
            return {
                "smart_money_signal": {
                    "type": "noul",
                    "instructions": "Will smart money flow predict a >5% price move in flow direction within 24h?"
                }
            }
        else:
            return {
                "decision": {
                    "type": "noul",
                    "instructions": input_data.question
                }
            }

    def _select_model(self, input_data: LayaInput) -> Optional[str]:
        """Select Laya checkpoint based on decision type and context."""
        # For typed-decisions workflows (agent observability, customer service, security)
        if input_data.decision_type in [
            LayaDecisionType.MARKET_MOVE,
            LayaDecisionType.PRICE_TARGET,
            LayaDecisionType.SMART_MONEY_SIGNAL,
        ]:
            # Use typed-decisions for specialized market judgment
            return "typed-decisions"
        # Default: let router auto-select by language/script
        return None

    async def _judge_local(
        self,
        state: Dict,
        questions: Dict,
        model: Optional[str],
        input_data: LayaInput
    ) -> LayaOutput:
        """Judge using local Router."""
        
        result = self._local_router.system_one(
            state=state,
            questions=questions,
            model=model
        )
        
        # Extract first answer (assuming single question for now)
        first_answer = next(iter(result["answers"].values()))
        probability = first_answer.get("noul", 0.5)
        confidence = first_answer.get("confidence", 0.5)
        
        # Clamp
        probability = max(0.0, min(1.0, probability))
        confidence = max(0.0, min(1.0, confidence))
        
        routing = result.get("routing", {})
        
        return LayaOutput(
            decision_id=f"laya_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{input_data.market_id[:8]}",
            decision_type=input_data.decision_type,
            market_id=input_data.market_id,
            probability=probability,
            confidence=confidence,
            reasoning=f"Laya {routing.get('model', 'unknown')} noul: {probability:.4f}",
            key_drivers=[],
            risk_factors=[],
            calibration_metadata={
                "model": "laya",
                "checkpoint": routing.get("model", "unknown"),
                "repo": routing.get("repo", "unknown"),
                "prompt_tokens": result.get("usage", {}).get("input_tokens", 0),
                "completion_tokens": result.get("usage", {}).get("output_tokens", 0),
                "response_format": "systemone_noul",
            },
            routing_info=routing
        )

    async def _judge_remote(
        self,
        state: Dict,
        questions: Dict,
        model: Optional[str],
        input_data: LayaInput
    ) -> LayaOutput:
        """Judge using remote HTTP server."""
        
        payload = {
            "state": state,
            "questions": questions,
        }
        if model:
            payload["model"] = model
        
        response = await self._http_client.post("/v1/systemone", json=payload)
        response.raise_for_status()
        result = response.json()
        
        first_answer = next(iter(result["answers"].values()))
        probability = first_answer.get("noul", 0.5)
        confidence = first_answer.get("confidence", 0.5)
        
        probability = max(0.0, min(1.0, probability))
        confidence = max(0.0, min(1.0, confidence))
        
        routing = result.get("routing", {})
        
        return LayaOutput(
            decision_id=f"laya_remote_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{input_data.market_id[:8]}",
            decision_type=input_data.decision_type,
            market_id=input_data.market_id,
            probability=probability,
            confidence=confidence,
            reasoning=f"Laya remote {routing.get('model', 'unknown')} noul: {probability:.4f}",
            key_drivers=[],
            risk_factors=[],
            calibration_metadata={
                "model": "laya",
                "checkpoint": routing.get("model", "unknown"),
                "repo": routing.get("repo", "unknown"),
                "prompt_tokens": result.get("usage", {}).get("input_tokens", 0),
                "completion_tokens": result.get("usage", {}).get("output_tokens", 0),
                "response_format": "systemone_noul",
            },
            routing_info=routing
        )

    async def close(self):
        """Close connections."""
        if self._http_client:
            await self._http_client.aclose()
        if self._local_router:
            self._local_router.unload()


# Compatibility layer: same interface as JevClient
class LayaJevCompatClient:
    """
    Drop-in replacement for JevClient with identical interface.
    Uses Laya locally for calibrated, multilingual, free System 1 decisions.
    """
    
    def __init__(self, **kwargs):
        # Accept same kwargs as JevClient for compatibility
        self.laya_client = LayaClient(mode="local", **kwargs)
        
        # Map JevDecisionType to LayaDecisionType
        from ..judgment.jev_client import JevDecisionType
        self._decision_map = {
            JevDecisionType.MARKET_MOVE: LayaDecisionType.MARKET_MOVE,
            JevDecisionType.PRICE_TARGET: LayaDecisionType.PRICE_TARGET,
            JevDecisionType.SMART_MONEY_SIGNAL: LayaDecisionType.SMART_MONEY_SIGNAL,
        }
    
    async def judge(self, input_data) -> 'JevOutput':
        """Maintain JevClient interface."""
        from ..judgment.jev_client import JevOutput, JevInput
        
        # Convert JevInput to LayaInput
        laya_input = LayaInput(
            decision_type=self._decision_map.get(input_data.decision_type, LayaDecisionType.MARKET_MOVE),
            market_id=input_data.market_id,
            question=input_data.question,
            features=input_data.features,
            context=input_data.context,
            few_shots=input_data.few_shots,
        )
        
        laya_output = await self.laya_client.judge(laya_input)
        
        # Convert back to JevOutput
        return JevOutput(
            decision_id=laya_output.decision_id,
            decision_type=input_data.decision_type,
            market_id=laya_output.market_id,
            probability=laya_output.probability,
            confidence=laya_output.confidence,
            reasoning=laya_output.reasoning,
            key_drivers=laya_output.key_drivers,
            risk_factors=laya_output.risk_factors,
            timestamp=laya_output.timestamp,
            calibration_metadata=laya_output.calibration_metadata,
        )
    
    async def close(self):
        await self.laya_client.close()


async def judge_market_move_laya(
    market_id: str,
    features: Dict,
    context: Dict,
    laya_client: LayaClient = None
) -> LayaOutput:
    """Quick judgment for a market move prediction using Laya."""
    if laya_client is None:
        laya_client = LayaClient(mode="local")
    
    input_data = LayaInput(
        decision_type=LayaDecisionType.MARKET_MOVE,
        market_id=market_id,
        question="Will the YES probability increase in the next 24 hours?",
        features=features,
        context=context,
    )
    
    return await laya_client.judge(input_data)
