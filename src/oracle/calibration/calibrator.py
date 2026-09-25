"""
Unified Oracle Calibrator

Wraps existing calibration components into a single interface for DealCalibrator.
"""

from dataclasses import dataclass
from typing import Any, Optional
import numpy as np
import pickle
from pathlib import Path

from oracle.calibration.isotonic import IsotonicCalibrator
from oracle.calibration.leakage_scanner import run_leakage_scan
from oracle.calibration.sandbox_evaluator import SandboxEvaluator, SandboxMetrics
from oracle.calibration.monitor import CalibrationMonitor


@dataclass
class CalibrationFeatures:
    """Features for calibration prediction."""
    
    # Core
    jev_prob: float
    category: str = "sales"
    
    # Market context (analogous to market price)
    latest_market_price: float = 0.5
    volume_24h: int = 0
    smart_money_net_flow: float = 0.0
    wallet_concentration: float = 0.5
    momentum_signal: float = 0.0
    
    # Macro context
    macro_wti: Optional[float] = None
    macro_gasoline_crack: Optional[float] = None
    macro_diesel_crack: Optional[float] = None
    macro_gpr: Optional[float] = None
    macro_dxy: Optional[float] = None
    macro_fed_funds: Optional[float] = None
    macro_breakeven_5y5y: Optional[float] = None
    macro_cass_freight: Optional[float] = None
    
    def to_array(self) -> np.ndarray:
        """Convert to feature array for model."""
        return np.array([
            self.jev_prob,
            self.latest_market_price,
            float(self.volume_24h),
            self.smart_money_net_flow,
            self.wallet_concentration,
            self.momentum_signal,
            self.macro_wti or 0.0,
            self.macro_gasoline_crack or 0.0,
            self.macro_diesel_crack or 0.0,
            self.macro_gpr or 0.0,
            self.macro_dxy or 0.0,
            self.macro_fed_funds or 0.0,
            self.macro_breakeven_5y5y or 0.0,
            self.macro_cass_freight or 0.0,
        ])


class OracleCalibrator:
    """
    Unified calibrator interface for Oracle Layers.
    
    Uses IsotonicCalibrator trained on historical outcomes.
    """
    
    def __init__(self):
        self.isotonic = IsotonicCalibrator()
        self.trained = False
        self._model_path = Path("models/calibrator.pkl")
    
    def train(self, predictions: np.ndarray, outcomes: np.ndarray) -> dict:
        """Train isotonic calibrator on historical data."""
        result = self.isotonic.fit(predictions, outcomes)
        self.trained = True
        self.save()
        return result
    
    def predict(self, features: CalibrationFeatures) -> float:
        """Get calibrated probability for a deal."""
        if not self.trained:
            # Fallback: return raw probability with small adjustment
            return float(np.clip(features.jev_prob, 0.01, 0.99))
        
        # Use isotonic calibration
        raw_prob = features.jev_prob
        calibrated = self.isotonic.predict(np.array([raw_prob]))[0]
        return float(np.clip(calibrated, 0.01, 0.99))
    
    def predict_batch(self, features_list: list) -> list[float]:
        """Calibrate multiple predictions at once."""
        if not self.trained:
            return [float(np.clip(f.jev_prob, 0.01, 0.99)) for f in features_list]
        
        raw_probs = np.array([f.jev_prob for f in features_list])
        calibrated = self.isotonic.predict(raw_probs)
        return [float(np.clip(c, 0.01, 0.99)) for c in calibrated]
    
    def save(self):
        """Save trained calibrator to disk."""
        self._model_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._model_path, 'wb') as f:
            pickle.dump(self.isotonic, f)
    
    @classmethod
    def load_latest(cls) -> "OracleCalibrator":
        """Load latest trained calibrator."""
        calibrator = cls()
        if calibrator._model_path.exists():
            with open(calibrator._model_path, 'rb') as f:
                calibrator.isotonic = pickle.load(f)
            calibrator.trained = True
        return calibrator


def create_calibrator_from_experiment_data() -> OracleCalibrator:
    """Create calibrator trained on sandbox experiment data."""
    evaluator = SandboxEvaluator()
    completed = evaluator.get_completed_experiments()
    
    if len(completed) < 10:
        return OracleCalibrator()  # Untrained
    
    # Use experiment composite scores as "predictions" and some proxy as outcomes
    # This is a placeholder - real implementation would use actual resolution data
    predictions = np.array([e.composite_score for e in completed])
    # Mock outcomes for now - would use real resolution data
    outcomes = np.random.binomial(1, predictions)
    
    calibrator = OracleCalibrator()
    calibrator.train(predictions, outcomes)
    return calibrator
