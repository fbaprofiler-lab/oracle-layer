"""
Oracle Layer — Live Signals API
REST endpoints for serving calibrated probabilities to users.
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
import json

from ..judgment.laya_client import LayaClient, LayaDecisionType, LayaInput
from ..sources.polymarket import polymarket_source
from ..calibration.calibrator import OracleCalibrator
from ..calibration.forward_adapters import ForwardFeatureCollector

router = APIRouter(prefix="/api/v1/signals", tags=["signals"])

# Initialize clients
_laya_client = LayaClient(base_url="http://localhost:8000")
_feature_collector = ForwardFeatureCollector(polymarket_source)
_calibrator: Optional[OracleCalibrator] = None


def _get_calibrator() -> OracleCalibrator:
    global _calibrator
    if _calibrator is None:
        _calibrator = OracleCalibrator.load_latest()
    return _calibrator


class SignalResponse(BaseModel):
    condition_id: str
    question: str
    category: str
    raw_probability: float
    calibrated_probability: float
    confidence: float
    timestamp: str
    backend: str
    end_date: Optional[str] = None
    end_date_iso: Optional[str] = None


class SignalsListResponse(BaseModel):
    signals: List[SignalResponse]
    total: int
    timestamp: str


class HealthResponse(BaseModel):
    status: str
    laya_healthy: bool
    calibrator_loaded: bool
    timestamp: str


async def _get_live_markets(limit: int = 50) -> List[Dict[str, Any]]:
    """Fetch active markets from Polymarket."""
    return await polymarket_source.get_active_markets(limit=limit)


async def _generate_signal(market: Dict[str, Any]) -> SignalResponse:
    """Generate a calibrated signal for a single market."""
    condition_id = str(market.get("conditionId", ""))
    question = str(market.get("question", ""))
    category = str(market.get("category", "unknown"))
    end_date = market.get("endDate")
    end_date_iso = market.get("endDateIso")

    if not condition_id or not question:
        raise ValueError("Market missing conditionId or question")

    # Collect features
    features = await _feature_collector(market)

    # Get judgment from Laya
    result = await _laya_client.judge(LayaInput(
        decision_type=LayaDecisionType.MARKET_MOVE,
        market_id=condition_id,
        question=question,
        features=features,
        context={"macro_context": features.get("macro_context", {})},
    ))

    raw_prob = float(result.probability)
    confidence = float(result.confidence)
    backend = f"laya:{result.routing_info.get('model', 'unknown')}"

    # Apply calibration
    calibrator = _get_calibrator()
    if calibrator and calibrator.trained:
        from ..calibration.calibrator import CalibrationFeatures
        macro = features.get("macro_context", {})
        market_metrics = features.get("market", {})
        
        cal_features = CalibrationFeatures(
            jev_prob=raw_prob,
            category=category,
            latest_market_price=market_metrics.get("current_prices", {}).get("Yes") if isinstance(market_metrics, dict) else 0.5,
            volume_24h=market_metrics.get("volume_24h") if isinstance(market_metrics, dict) else 0,
            smart_money_net_flow=sum(market_metrics.get("smart_money_net_flow", {}).values()) if isinstance(market_metrics, dict) and market_metrics.get("smart_money_net_flow") else None,
            wallet_concentration=market_metrics.get("wallet_concentration") if isinstance(market_metrics, dict) else None,
            momentum_signal=market_metrics.get("momentum_signal") if isinstance(market_metrics, dict) else None,
            macro_wti=macro.get("wti"),
            macro_gasoline_crack=macro.get("gasoline_crack"),
            macro_diesel_crack=macro.get("diesel_crack"),
            macro_gpr=macro.get("gpr"),
            macro_dxy=macro.get("dxy"),
            macro_fed_funds=macro.get("fed_funds"),
            macro_breakeven_5y5y=macro.get("breakeven_5y5y"),
            macro_cass_freight=macro.get("cass_freight"),
        )
        calibrated_prob = calibrator.predict(cal_features)
    else:
        calibrated_prob = raw_prob

    return SignalResponse(
        condition_id=condition_id,
        question=question,
        category=category,
        raw_probability=raw_prob,
        calibrated_probability=calibrated_prob,
        confidence=confidence,
        timestamp=datetime.now(timezone.utc).isoformat(),
        backend=backend,
        end_date=end_date,
        end_date_iso=end_date_iso,
    )


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check for signals API and dependencies."""
    # Check Laya
    laya_healthy = False
    try:
        await _laya_client.health_check()
        laya_healthy = True
    except Exception:
        pass

    # Check calibrator
    calibrator_loaded = False
    try:
        calibrator = _get_calibrator()
        calibrator_loaded = calibrator.trained
    except Exception:
        pass

    return HealthResponse(
        status="healthy" if laya_healthy else "degraded",
        laya_healthy=laya_healthy,
        calibrator_loaded=calibrator_loaded,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@router.get("/latest", response_model=SignalsListResponse)
async def get_latest_signals(
    limit: int = Query(20, ge=1, le=100),
    category: Optional[str] = Query(None),
):
    """Get latest calibrated signals for active markets."""
    markets = await _get_live_markets(limit=200)

    # Filter by category if specified
    if category:
        markets = [m for m in markets if m.get("category") == category]

    # Limit
    markets = markets[:limit]

    signals = []
    for market in markets:
        try:
            signal = await _generate_signal(market)
            signals.append(signal)
        except Exception as e:
            # Log and continue
            print(f"Signal generation failed for {market.get('conditionId', 'unknown')}: {e}")

    return SignalsListResponse(
        signals=signals,
        total=len(signals),
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@router.get("/{condition_id}", response_model=SignalResponse)
async def get_signal(condition_id: str):
    """Get calibrated signal for a specific market by condition ID."""
    market = await polymarket_source.get_market_details(condition_id)
    if not market:
        raise HTTPException(status_code=404, detail="Market not found")
    return await _generate_signal(market)


@router.get("/category/{category}", response_model=SignalsListResponse)
async def get_signals_by_category(
    category: str,
    limit: int = Query(20, ge=1, le=100),
):
    """Get calibrated signals for a specific category."""
    return await get_latest_signals(limit=limit, category=category)
