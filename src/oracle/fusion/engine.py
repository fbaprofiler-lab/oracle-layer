"""
Oracle Layer — Fusion Engine
Macro transmission → Market microstructure → Jev judgment → Explainer generation
The core orchestration layer that fuses all signals.
"""

import asyncio
import pickle
import math
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from ..sources.base import registry
from ..sources.eia import eia_source
from ..sources.fred import fred_source
from ..sources.polymarket import polymarket_source
from ..markets.analyzer import MarketAnalyzer, MarketMetrics
from ..judgment.laya_client import LayaJevCompatClient as JevClient, LayaOutput as JevOutput, LayaDecisionType as JevDecisionType, LayaInput as JevInput
from ..judgment.jev_client import CalibrationEngine
from ..judgment.calibrator import OracleCalibrator, CalibrationFeatures
from ..explainers.pipeline import ExplainerPipeline, ExplainerConfig


class SignalStrength(str, Enum):
    WEAK = "weak"
    MODERATE = "moderate"
    STRONG = "strong"
    CRITICAL = "critical"


@dataclass
class OracleSignal:
    """Unified signal output from the fusion engine."""
    signal_id: str
    timestamp: datetime
    market_id: str
    question: str
    category: str

    # Macro transmission
    macro_drivers: Dict[str, Any] = field(default_factory=dict)
    transmission_lag_weeks: Dict[str, int] = field(default_factory=dict)
    macro_signal_strength: SignalStrength = SignalStrength.WEAK

    # Market microstructure
    market_metrics: Optional[MarketMetrics] = None
    market_signal_strength: SignalStrength = SignalStrength.WEAK

    # Jev judgment
    jev_output: Optional[JevOutput] = None
    judgment_confidence: float = 0.0

    # Fused probability
    fused_probability_up: float = 0.5
    fused_confidence: float = 0.0

    # Explainer
    explainer_script: Optional[Any] = None
    explainer_video_url: Optional[str] = None

    # Risk & metadata
    risk_factors: List[str] = field(default_factory=list)
    key_drivers: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class FusionEngine:
    """
    Core orchestration engine that fuses:
    1. Macro transmission chains (energy → inflation → Fed → prediction markets)
    2. Market microstructure (liquidity, smart money, mispricing)
    3. Calibrated probabilistic judgment (Jev)
    4. Generative explanations (Higgsfield)
    """

    def __init__(self):
        self.jev_client = JevClient()
        self.market_analyzer = MarketAnalyzer(polymarket_source)
        self.explainer_pipeline = ExplainerPipeline()
        self.calibration_engine = CalibrationEngine()
        self.calibrator: Optional[OracleCalibrator] = None
        
        # Load trained calibrator
        self._load_calibrator()
        
        # Transmission lag models (from fuel-briefing design)
        self.transmission_lags = {
            "crude_to_gasoline_retail": 2,      # weeks
            "crude_to_diesel_retail": 2,
            "gasoline_to_cpi_energy": 4,
            "diesel_to_freight": 3,
            "diesel_to_food_cpi": 6,
            "cracks_to_chemicals_ppi": 7,
            "energy_to_core_cpi": 8,
            "energy_to_fed_policy": 10,
            "fed_policy_to_rates_markets": 1,
            "gpr_to_crude": 0,  # immediate
        }

    async def process_market(self, condition_id: str) -> OracleSignal:
        """Process a single market through the full fusion pipeline."""
        
        # 1. Get market details
        details = await polymarket_source.get_market_details(condition_id)
        if not details:
            raise ValueError(f"Market not found: {condition_id}")

        # 2. Analyze market microstructure
        market_metrics = await self.market_analyzer.analyze_market(condition_id)

        # 3. Fetch macro context
        macro_context = await self._fetch_macro_context()

        # 4. Build Jev input features
        features = self._build_jev_features(market_metrics, macro_context)
        context = self._build_jev_context(macro_context)

        # 5. Get Jev judgment
        jev_input = self._build_jev_input(condition_id, details, features, context)
        jev_output = await self.jev_client.judge(jev_input)

        # 6. Fuse signals
        signal = self._fuse_signals(
            condition_id=condition_id,
            details=details,
            market_metrics=market_metrics,
            macro_context=macro_context,
            jev_output=jev_output,
        )

        # 7. Generate explainer if signal is strong enough
        if signal.fused_confidence > 0.6 and signal.market_signal_strength in (SignalStrength.STRONG, SignalStrength.CRITICAL):
            signal.explainer_script = await generate_explainer(
                jev_output=signal.jev_output,
                market_data=self._market_data_for_explainer(market_metrics),
                macro_context=macro_context,
                wallet_signals=self._wallet_signals_for_explainer(market_metrics),
            )

        # 8. Record for calibration
        self.calibration_engine.add_prediction(signal.jev_output, features)

        return signal

    async def _fetch_macro_context(self) -> Dict[str, Any]:
        """Fetch current macro context from EIA/FRED."""
        # Fetch key series in parallel
        eia_series = ["gasoline_us", "diesel_us", "gasoline_stocks", "distillate_stocks", "crude_stocks", "crude_runs"]
        fred_series = ["wti", "brent", "rbo_b", "ho", "dxy", "gpr", "fed_funds", "breakeven_5y5y", "cass_freight"]

        eia_data = await eia_source.fetch_multiple(eia_series, limit=1)
        fred_data = await fred_source.fetch_multiple(fred_series, limit=1)

        # Extract latest values
        context = {}
        
        # EIA values
        for series_id, points in eia_data.items():
            if points:
                context[series_id] = points[-1].value

        # FRED values
        for series_id, points in fred_data.items():
            if points:
                context[series_id] = points[-1].value

        # Compute derived values
        context["gasoline_crack"] = self._compute_crack(context.get("rbo_b"), context.get("wti"))
        context["diesel_crack"] = self._compute_crack(context.get("ho"), context.get("wti"))
        context["wti_brent_spread"] = self._compute_spread(context.get("wti"), context.get("brent"))

        return context

    def _compute_crack(self, product_price: Optional[float], crude_price: Optional[float]) -> Optional[float]:
        """Compute crack spread (product - crude)."""
        if product_price is not None and crude_price is not None:
            # Convert to common units if needed (simplified)
            return round(product_price * 42 - crude_price, 2)  # $/bbl
        return None

    def _compute_spread(self, price1: Optional[float], price2: Optional[float]) -> Optional[float]:
        """Compute spread between two prices."""
        if price1 is not None and price2 is not None:
            return round(price1 - price2, 2)
        return None

    def _build_jev_features(self, market_metrics: MarketMetrics, macro_context: Dict) -> Dict[str, Any]:
        """Build feature dict for Jev judgment."""
        return {
            "current_price": market_metrics.current_prices.get("Yes", 0.5),
            "volume_24h": market_metrics.volume_24h,
            "price_change_1h": market_metrics.price_change_1h,
            "price_change_24h": market_metrics.price_change_24h,
            "smart_money_net_flow": market_metrics.smart_money_net_flow,
            "smart_money_wallets": market_metrics.smart_money_wallets,
            "wallet_concentration": market_metrics.wallet_concentration,
            "mispricing_score": market_metrics.mispricing_score,
            "momentum_signal": market_metrics.momentum_signal,
        }

    def _build_jev_context(self, macro_context: Dict) -> Dict[str, Any]:
        """Build context dict for Jev judgment."""
        return {
            "wti": macro_context.get("wti"),
            "brent": macro_context.get("brent"),
            "gasoline_crack": macro_context.get("gasoline_crack"),
            "diesel_crack": macro_context.get("diesel_crack"),
            "gpr": macro_context.get("gpr"),
            "dxy": macro_context.get("dxy"),
            "fed_funds": macro_context.get("fed_funds"),
            "breakeven_5y5y": macro_context.get("breakeven_5y5y"),
            "cass_freight": macro_context.get("cass_freight"),
        }

    def _build_jev_input(self, condition_id: str, details: Dict, features: Dict, context: Dict) -> Any:
        """Build JevInput for market move prediction."""
        from ..judgment.jev_client import JevInput, JevDecisionType
        
        return JevInput(
            decision_type=JevDecisionType.MARKET_MOVE,
            market_id=condition_id,
            question=details.get("question", ""),
            features=features,
            context=context,
        )

    def _load_calibrator(self):
        """Load trained calibrator from disk."""
        try:
            model_dir = Path("/tmp/oracle_models")
            calibrator_files = list(model_dir.glob("oracle_calibrator_*.pkl"))
            if calibrator_files:
                latest = max(calibrator_files, key=lambda f: f.stat().st_mtime)
                self.calibrator = OracleCalibrator.load(str(latest))
                print(f"Loaded calibrator: {latest}")
            else:
                print("No calibrator found, using raw Jev output")
        except Exception as e:
            print(f"Failed to load calibrator: {e}")
    
    def _calibrate_jev(self, jev_output: JevOutput, market_metrics: MarketMetrics, macro_context: Dict) -> float:
        """Calibrate Jev probability using our custom calibrator."""
        if not self.calibrator.trained:
            return jev_output.probability
        
        features = CalibrationFeatures(
            jev_prob=jev_output.probability,
            category=market_metrics.category if hasattr(market_metrics, 'category') else "unknown",
            latest_market_price=market_metrics.current_prices.get("Yes") if market_metrics.current_prices else None,
            volume_24h=market_metrics.volume_24h,
            smart_money_net_flow=sum(market_metrics.smart_money_net_flow.values()) if market_metrics.smart_money_net_flow else None,
            wallet_concentration=market_metrics.wallet_concentration,
            momentum_signal=market_metrics.momentum_signal,
            macro_wti=None,  # Would need to pass macro context
            macro_gasoline_crack=None,
            macro_diesel_crack=None,
            macro_gpr=None,
            macro_dxy=None,
            macro_fed_funds=None,
            macro_breakeven_5y5y=None,
            macro_cass_freight=None,
        )
        return self.calibrator.predict(features)

    def _fuse_signals(
        self,
        condition_id: str,
        details: Dict,
        market_metrics: MarketMetrics,
        macro_context: Dict,
        jev_output: JevOutput,
    ) -> OracleSignal:
        """Fuse all signals into a unified Oracle signal."""

        # Determine macro signal strength
        macro_strength = self._assess_macro_strength(macro_context, market_metrics.category)

        # Determine market signal strength
        market_strength = self._assess_market_strength(market_metrics)

        # Calibrate Jev probability
        jev_prob_calibrated = self._calibrate_jev(jev_output, market_metrics, macro_context)

        # Fuse probabilities (weighted by confidence)
        macro_weight = 0.3
        market_weight = 0.3
        jev_weight = 0.4

        # Macro probability (simplified heuristic)
        macro_prob = self._macro_probability(macro_context, market_metrics.category)

        fused_prob = (
            macro_weight * macro_prob +
            market_weight * (0.5 + 0.2 if market_metrics.momentum_signal == "bullish" else -0.2 if market_metrics.momentum_signal == "bearish" else 0) +
            jev_weight * jev_prob_calibrated
        )
        fused_prob = max(0.0, min(1.0, fused_prob))

        # Fused confidence
        fused_conf = (
            macro_weight * (0.8 if macro_strength == SignalStrength.STRONG else 0.4 if macro_strength == SignalStrength.MODERATE else 0.1) +
            market_weight * (0.8 if market_strength == SignalStrength.STRONG else 0.4 if market_strength == SignalStrength.MODERATE else 0.1) +
            jev_weight * jev_output.confidence
        )

        # Collect risk factors
        risk_factors = []
        if market_metrics.wallet_concentration > 0.5:
            risk_factors.append("High wallet concentration — manipulation risk")
        if market_metrics.volume_24h < 10000:
            risk_factors.append("Thin liquidity — high slippage risk")
        if jev_output.confidence < 0.5:
            risk_factors.append("Low judgment confidence")
        if macro_context.get("gpr", 0) > 200:
            risk_factors.append("Extreme geopolitical risk — regime break possible")

        # Key drivers
        key_drivers = []
        if jev_output.key_drivers:
            key_drivers.extend(jev_output.key_drivers)
        if market_metrics.momentum_signal != "neutral":
            key_drivers.append(f"Market momentum: {market_metrics.momentum_signal}")
        if market_metrics.smart_money_net_flow:
            key_drivers.append("Smart money flow detected")

        return OracleSignal(
            signal_id=f"oracle_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{condition_id[:8]}",
            timestamp=datetime.now(),
            market_id=condition_id,
            question=details.get("question", ""),
            category=details.get("category", "unknown"),
            macro_drivers=self._extract_macro_drivers(macro_context),
            transmission_lag_weeks=self.transmission_lags,
            macro_signal_strength=macro_strength,
            market_metrics=market_metrics,
            market_signal_strength=market_strength,
            jev_output=jev_output,
            judgment_confidence=jev_output.confidence,
            fused_probability_up=fused_prob,
            fused_confidence=fused_conf,
            risk_factors=risk_factors,
            key_drivers=key_drivers[:5],
            metadata={
                "macro_weight": 0.3,
                "market_weight": 0.3,
                "jev_weight": 0.4,
                "macro_prob": macro_prob,
            }
        )

    def _assess_macro_strength(self, macro_context: Dict, category: str) -> SignalStrength:
        """Assess macro signal strength based on context."""
        score = 0
        
        # Strong cracks = strong signal
        if macro_context.get("gasoline_crack", 0) > 25:
            score += 2
        elif macro_context.get("gasoline_crack", 0) > 15:
            score += 1

        if macro_context.get("diesel_crack", 0) > 25:
            score += 2
        elif macro_context.get("diesel_crack", 0) > 15:
            score += 1

        # GPR elevated
        if macro_context.get("gpr", 0) > 150:
            score += 2
        elif macro_context.get("gpr", 0) > 100:
            score += 1

        # DXY extreme
        if macro_context.get("dxy", 0) > 108 or macro_context.get("dxy", 0) < 95:
            score += 1

        if score >= 4:
            return SignalStrength.STRONG
        elif score >= 2:
            return SignalStrength.MODERATE
        return SignalStrength.WEAK

    def _assess_market_strength(self, metrics: MarketMetrics) -> SignalStrength:
        """Assess market microstructure signal strength."""
        score = 0

        if metrics.mispricing_score > 0.6:
            score += 2
        elif metrics.mispricing_score > 0.3:
            score += 1

        if metrics.momentum_signal != "neutral":
            score += 1

        if metrics.smart_money_net_flow:
            score += 1

        if metrics.volume_24h > 100000:
            score += 1

        if score >= 3:
            return SignalStrength.STRONG
        elif score >= 1:
            return SignalStrength.MODERATE
        return SignalStrength.WEAK

    def _macro_probability(self, macro_context: Dict, category: str) -> float:
        """Heuristic macro probability for the category."""
        prob = 0.5

        # Fed rate decisions category - strongest macro linkage
        if "fed" in category.lower() or "rate" in category.lower() or "cpi" in category.lower():
            # High cracks → inflation pressure → higher rates
            if macro_context.get("gasoline_crack", 0) > 20:
                prob += 0.15
            if macro_context.get("diesel_crack", 0) > 20:
                prob += 0.15
            if macro_context.get("gpr", 0) > 150:
                prob += 0.1

        return max(0.0, min(1.0, prob))

    def _extract_macro_drivers(self, macro_context: Dict) -> Dict[str, Any]:
        """Extract key macro drivers for the signal."""
        return {
            "crude_oil": {"wti": macro_context.get("wti"), "brent": macro_context.get("brent")},
            "cracks": {"gasoline": macro_context.get("gasoline_crack"), "diesel": macro_context.get("diesel_crack")},
            "geopolitical_risk": {"gpr": macro_context.get("gpr")},
            "dollar": {"dxy": macro_context.get("dxy")},
            "fed_policy": {"fed_funds": macro_context.get("fed_funds"), "breakeven_5y5y": macro_context.get("breakeven_5y5y")},
            "freight": {"cass_index": macro_context.get("cass_freight")},
        }

    def _market_data_for_explainer(self, metrics: MarketMetrics) -> Dict:
        return {
            "question": metrics.question,
            "current_prices": metrics.current_prices,
            "volume_24h": metrics.volume_24h,
        }

    def _wallet_signals_for_explainer(self, metrics: MarketMetrics) -> Dict:
        return {
            "smart_money_wallets": metrics.smart_money_wallets,
            "smart_money_net_flow": metrics.smart_money_net_flow,
            "wallet_concentration": metrics.wallet_concentration,
        }

    async def scan_category(self, category: str = "fed-rate-decisions", top_k: int = 5) -> List[OracleSignal]:
        """Scan a category and return top fused signals."""
        top_markets = await self.market_analyzer.get_top_signals(category, top_k)
        signals = []

        for market in top_markets:
            try:
                signal = await self.process_market(market.condition_id)
                signals.append(signal)
            except Exception as e:
                print(f"Failed to process {market.condition_id}: {e}")

        # Sort by fused confidence * probability deviation from 0.5
        signals.sort(key=lambda s: s.fused_confidence * abs(s.fused_probability_up - 0.5), reverse=True)
        return signals

    async def close(self):
        await self.jev_client.close()
        await eia_source.close()
        await fred_source.close()
        await polymarket_source.close()


# Convenience function
async def run_fusion_scan(category: str = "fed-rate-decisions", top_k: int = 5) -> List[OracleSignal]:
    """Run a full fusion scan on a category."""
    engine = FusionEngine()
    try:
        return await engine.scan_category(category, top_k)
    finally:
        await engine.close()