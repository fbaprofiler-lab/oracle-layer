"""
Oracle Layer — Judgment Module (Jev/TypeSafe Integration)
Calibrated probabilistic judgments for market moves
"""

import os
import asyncio
import json
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Literal
from dataclasses import dataclass, field
from enum import Enum
import httpx
from pydantic import BaseModel, Field

from ..core.config import settings
from ..sources.base import DataPoint
from .laya_client import LayaJevCompatClient


class JevDecisionType(str, Enum):
    """Types of decisions Jev can make."""
    MARKET_MOVE = "market_move"           # Will market move up/down?
    PRICE_TARGET = "price_target"         # Will price hit target?
    REGIME_CHANGE = "regime_change"       # Is regime shifting?
    LIQUIDITY_SHIFT = "liquidity_shift"   # Is liquidity changing?
    SMART_MONEY_SIGNAL = "smart_money_signal"  # Is smart money active?


@dataclass
class JevInput:
    """Structured input for Jev judgment."""
    decision_type: JevDecisionType
    market_id: str
    question: str
    features: Dict[str, Any]
    context: Dict[str, Any] = field(default_factory=dict)
    few_shots: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class JevOutput:
    """Structured output from Jev judgment."""
    decision_id: str
    decision_type: JevDecisionType
    market_id: str
    probability: float  # 0-1 calibrated
    confidence: float   # 0-1, how confident in the calibration
    reasoning: str
    key_drivers: List[str]
    risk_factors: List[str]
    timestamp: datetime = field(default_factory=datetime.now)
    calibration_metadata: Dict[str, Any] = field(default_factory=dict)


class JevSchema(BaseModel):
    """Schema for Jev market move prediction."""
    # The decision
    will_move_up: bool = Field(description="Whether the market probability will increase")
    probability_up: float = Field(ge=0, le=1, description="Calibrated P(up)")
    confidence: float = Field(ge=0, le=1, description="Calibration confidence")
    
    # Reasoning
    primary_driver: str = Field(description="Main factor driving the prediction")
    key_factors: List[str] = Field(description="Supporting factors")
    risk_factors: List[str] = Field(description="Factors that could invalidate")
    
    # Market context
    time_horizon_hours: int = Field(default=24, description="Prediction horizon")
    current_price: float = Field(description="Current market probability")
    predicted_price: float = Field(description="Predicted probability")


class JevClient:
    """Client for Jev/TypeSafe API."""

    def __init__(self):
        self.api_key = settings.typesafe_api_key or os.getenv("TYPESAFE_API_KEY")
        self.base_url = settings.typesafe_base_url
        self.model = settings.jev_model
        self.timeout = settings.jev_timeout_ms / 1000
        self.max_retries = settings.jev_max_retries
        
        if not self.api_key:
            raise ValueError("TYPESAFE_API_KEY required for JevClient")
        
        self.client = httpx.AsyncClient(
            timeout=self.timeout,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
        )

    async def judge(self, input_data: JevInput) -> JevOutput:
        """Make a calibrated judgment using Jev."""
        
        # Build the prompt/schema for Jev
        prompt = self._build_prompt(input_data)
        
        # Call Jev API
        response = await self._call_jev(prompt, input_data.decision_type)
        
        # Parse and validate
        output = self._parse_response(response, input_data)
        
        return output

    def _build_prompt(self, input_data: JevInput) -> str:
        """Build structured prompt for Jev based on decision type."""
        
        base_context = f"""
You are Jev, a calibrated probabilistic judgment engine for prediction markets.
You output structured probabilities with calibrated confidence, not opinions.

MARKET CONTEXT:
- Market ID: {input_data.market_id}
- Decision Type: {input_data.decision_type.value}
- Question: {input_data.question}
- Current Market Price: {input_data.features.get('current_price', 'N/A')}
- 24h Volume: {input_data.features.get('volume_24h', 'N/A')}
- Smart Money Net Flow: {input_data.features.get('smart_money_net_flow', 'N/A')}
- Wallet Concentration: {input_data.features.get('wallet_concentration', 'N/A')}

MACRO CONTEXT:
- WTI Crude: ${input_data.context.get('wti', 'N/A')}/bbl
- Gasoline Crack: ${input_data.context.get('gasoline_crack', 'N/A')}/bbl
- Diesel Crack: ${input_data.context.get('diesel_crack', 'N/A')}/bbl
- GPR Index: {input_data.context.get('gpr', 'N/A')}
- DXY: {input_data.context.get('dxy', 'N/A')}
- Fed Funds Rate: {input_data.context.get('fed_funds', 'N/A')}%

SMART MONEY SIGNALS:
- Smart Money Wallets Active: {len(input_data.features.get('smart_money_wallets', []))}
- Smart Money Net Flow (Yes): {input_data.features.get('smart_money_net_flow_yes', 'N/A')}
- Smart Money Net Flow (No): {input_data.features.get('smart_money_net_flow_no', 'N/A')}

TECHNICAL:
- 1h Price Change: {input_data.features.get('price_change_1h', 'N/A')}%
- 24h Price Change: {input_data.features.get('price_change_24h', 'N/A')}%
- Mispricing Score: {input_data.features.get('mispricing_score', 'N/A')}
"""
        
        if input_data.decision_type == JevDecisionType.MARKET_MOVE:
            specific = """
TASK: Predict whether the "YES" outcome probability will INCREASE over the next 24 hours.
Output a calibrated probability (0-1) with confidence (0-1).
Consider: macro transmission lags (energy→inflation→Fed→rates), smart money flow, 
liquidity conditions, geopolitical risk, and technical momentum.
"""
        elif input_data.decision_type == JevDecisionType.PRICE_TARGET:
            target = input_data.features.get('target_price', 0.5)
            specific = f"""
TASK: Predict whether the "YES" outcome probability will reach {target} within 48 hours.
Output a calibrated probability (0-1) with confidence.
"""
        elif input_data.decision_type == JevDecisionType.SMART_MONEY_SIGNAL:
            specific = """
TASK: Assess whether current smart money activity represents a genuine signal vs noise.
Output probability that smart money flow predicts a >5% price move in flow direction within 24h.
"""
        else:
            specific = "TASK: Provide calibrated probabilistic judgment for the given decision type."
        
        return base_context + specific

    async def _call_jev(self, prompt: str, decision_type: JevDecisionType) -> Dict:
        """Call Jev API with retry logic."""
        
        # Build the SystemOne request payload
        # For market move prediction, we use a noul (yes/no probability) question
        # The API expects: state, model, questions map with typed questions
        # For noul type, the field is 'instructions' not 'question'
        
        # Parse the prompt to extract key information for the structured request
        # We'll use a simpler approach: create a direct SystemOne request
        
        if decision_type == JevDecisionType.MARKET_MOVE:
            question_text = "Will the YES probability increase in the next 24 hours?"
        elif decision_type == JevDecisionType.PRICE_TARGET:
            target = self._extract_target_from_prompt(prompt)
            question_text = f"Will the YES outcome probability reach {target} within 48 hours?"
        elif decision_type == JevDecisionType.SMART_MONEY_SIGNAL:
            question_text = "Will smart money flow predict a >5% price move in flow direction within 24h?"
        else:
            question_text = "Provide calibrated probabilistic judgment for the given decision type."
        
        payload = {
            "state": prompt,
            "model": self.model,
            "questions": {
                "market_move": {
                    "type": "noul",
                    "instructions": question_text
                }
            }
        }
        
        for attempt in range(self.max_retries):
            try:
                response = await self.client.post(
                    f"{self.base_url}/systemone",
                    json=payload
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    await asyncio.sleep(2 ** attempt)
                    continue
                # Log the error for debugging
                print(f"Jev API error: {e.response.status_code} - {e.response.text}")
                raise
            except Exception as e:
                if attempt == self.max_retries - 1:
                    raise
                await asyncio.sleep(1)
        
        raise RuntimeError("Jev API call failed after retries")

    def _parse_response(self, response: Dict, input_data: JevInput) -> JevOutput:
        """Parse Jev SystemOne response into structured output."""
        try:
            # SystemOne returns: {model, answers: {question_name: {type: 'noul', noul: 0.XX}}, usage}
            answers = response.get("answers", {})
            
            # Extract probability from the first question's noul field
            probability = 0.5
            confidence = 0.5
            reasoning = ""
            key_drivers = []
            risk_factors = []
            
            for question_name, answer_data in answers.items():
                if answer_data.get("type") == "noul" and "noul" in answer_data:
                    probability = float(answer_data["noul"])
                    probability = max(0.0, min(1.0, probability))
                    # Use confidence from calibration metadata or default
                    confidence = 0.7  # Will be calibrated by CalibrationEngine
                    reasoning = f"Jev SystemOne noul prediction: {probability:.2f}"
                    break
            
            # Clamp
            probability = max(0.0, min(1.0, probability))
            confidence = max(0.0, min(1.0, confidence))
            
            return JevOutput(
                decision_id=f"jev_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{input_data.market_id[:8]}",
                decision_type=input_data.decision_type,
                market_id=input_data.market_id,
                probability=probability,
                confidence=confidence,
                reasoning=f"Jev SystemOne noul: {probability:.4f}",
                key_drivers=key_drivers,
                risk_factors=risk_factors,
                calibration_metadata={
                    "model": self.model,
                    "prompt_tokens": response.get("usage", {}).get("prompt_tokens", 0),
                    "completion_tokens": response.get("usage", {}).get("completion_tokens", 0),
                    "response_format": "systemone_noul",
                }
            )
        except (KeyError, ValueError, json.JSONDecodeError) as e:
            # Fallback to neutral
            return JevOutput(
                decision_id=f"jev_fallback_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                decision_type=input_data.decision_type,
                market_id=input_data.market_id,
                probability=0.5,
                confidence=0.1,
                reasoning=f"Parse failed: {e}. Using neutral prior.",
                key_drivers=[],
                risk_factors=["Model output parsing failed"],
            )

    async def close(self):
        await self.client.aclose()


class CalibrationEngine:
    """Calibrates Jev outputs using historical predictions vs outcomes."""

    def __init__(self, lookback_days: int = 180):
        self.lookback_days = lookback_days
        self.predictions_db: List[Dict] = []  # In production, use DB

    def add_prediction(self, prediction: JevOutput, features: Dict):
        """Record a prediction for later calibration."""
        self.predictions_db.append({
            "decision_id": prediction.decision_id,
            "market_id": prediction.market_id,
            "decision_type": prediction.decision_type.value,
            "probability": prediction.probability,
            "confidence": prediction.confidence,
            "timestamp": prediction.timestamp.isoformat(),
            "features": features,
            "outcome": None,  # Filled later
        })

    def record_outcome(self, decision_id: str, outcome: bool):
        """Record the actual outcome for a prediction."""
        for p in self.predictions_db:
            if p["decision_id"] == decision_id:
                p["outcome"] = outcome
                p["resolved_at"] = datetime.now().isoformat()
                break

    def compute_calibration(self) -> Dict[str, Any]:
        """Compute calibration metrics (ECE, reliability, etc.)."""
        resolved = [p for p in self.predictions_db if p["outcome"] is not None]
        if len(resolved) < 20:
            return {"status": "insufficient_data", "n": len(resolved)}

        # Bin predictions by probability
        bins = 10
        bin_edges = [i / bins for i in range(bins + 1)]
        
        ece = 0.0
        total = len(resolved)
        
        calibration_curve = []
        
        for i in range(bins):
            low, high = bin_edges[i], bin_edges[i + 1]
            bin_preds = [p for p in resolved if low <= p["probability"] < high]
            
            if not bin_preds:
                calibration_curve.append({"bin": f"{low:.1f}-{high:.1f}", "count": 0, "accuracy": None, "avg_prob": None})
                continue
            
            avg_prob = np.mean([p["probability"] for p in bin_preds])
            accuracy = np.mean([p["outcome"] for p in bin_preds])
            bin_weight = len(bin_preds) / total
            ece += bin_weight * abs(avg_prob - accuracy)
            
            calibration_curve.append({
                "bin": f"{low:.1f}-{high:.1f}",
                "count": len(bin_preds),
                "accuracy": round(accuracy, 4),
                "avg_prob": round(avg_prob, 4),
            })

        # Brier score
        brier = np.mean([(p["probability"] - p["outcome"]) ** 2 for p in resolved])

        return {
            "status": "ok",
            "n": total,
            "ece": round(ece, 4),
            "brier_score": round(brier, 4),
            "calibration_curve": calibration_curve,
            "reliability": "good" if ece < 0.05 else "moderate" if ece < 0.1 else "poor",
        }

    def apply_temperature_scaling(self, predictions: List[JevOutput]) -> List[JevOutput]:
        """Apply temperature scaling to calibrate probabilities."""
        # In production, learn temperature from validation set
        # For now, return as-is with metadata
        for p in predictions:
            p.calibration_metadata["temperature_applied"] = False
        return predictions


# Convenience function
async def judge_market_move(
    market_id: str,
    features: Dict,
    context: Dict,
    jev_client: LayaJevCompatClient = None
) -> JevOutput:
    """Quick judgment for a market move prediction."""
    if jev_client is None:
        jev_client = LayaJevCompatClient()
    
    input_data = JevInput(
        decision_type=JevDecisionType.MARKET_MOVE,
        market_id=market_id,
        question="Will the YES probability increase in the next 24 hours?",
        features=features,
        context=context,
    )
    
    return await jev_client.judge(input_data)