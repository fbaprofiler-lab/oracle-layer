"""
Isotonic Calibration for Oracle Layers

Implements isotonic regression calibration for probability calibration.
"""

import numpy as np
from sklearn.isotonic import IsotonicRegression
import pickle
from pathlib import Path
from typing import Tuple


class IsotonicCalibrator:
    """
    Isotonic regression calibrator for probability calibration.
    
    Wraps sklearn's IsotonicRegression with Oracle Layers interface.
    """
    
    def __init__(self, out_of_bounds: str = "clip"):
        self.calibrator = IsotonicRegression(out_of_bounds=out_of_bounds)
        self.fitted = False
    
    def fit(self, predictions: np.ndarray, outcomes: np.ndarray) -> dict:
        """Fit isotonic calibrator on predictions and binary outcomes."""
        # Ensure inputs are valid
        predictions = np.asarray(predictions).ravel()
        outcomes = np.asarray(outcomes).ravel()
        
        # Clip to valid range
        predictions = np.clip(predictions, 0.0, 1.0)
        outcomes = np.clip(outcomes, 0.0, 1.0)
        
        # Fit
        self.calibrator.fit(predictions, outcomes)
        self.fitted = True
        
        # Compute metrics
        calibrated = self.calibrator.predict(predictions)
        ece = self._compute_ece(calibrated, outcomes)
        brier = np.mean((calibrated - outcomes) ** 2)
        
        return {
            "fitted": True,
            "n_samples": len(predictions),
            "ece": float(ece),
            "brier": float(brier),
            "boundaries": self.calibrator.X_thresholds_.tolist() if hasattr(self.calibrator, 'X_thresholds_') else [],
        }
    
    def predict(self, predictions: np.ndarray) -> np.ndarray:
        """Apply calibration to new predictions."""
        if not self.fitted:
            # Return uncalibrated if not fitted
            return np.clip(predictions, 0.0, 1.0)
        
        predictions = np.asarray(predictions).ravel()
        predictions = np.clip(predictions, 0.0, 1.0)
        return self.calibrator.predict(predictions)
    
    def _compute_ece(self, calibrated: np.ndarray, outcomes: np.ndarray, n_bins: int = 10) -> float:
        """Compute Expected Calibration Error."""
        bin_boundaries = np.linspace(0, 1, n_bins + 1)
        bin_lowers = bin_boundaries[:-1]
        bin_uppers = bin_boundaries[1:]
        
        ece = 0.0
        for lower, upper in zip(bin_lowers, bin_uppers):
            in_bin = (calibrated >= lower) & (calibrated < upper)
            if in_bin.sum() == 0:
                continue
            bin_conf = calibrated[in_bin].mean()
            bin_acc = outcomes[in_bin].mean()
            ece += in_bin.sum() * abs(bin_conf - bin_acc)
        return ece / len(calibrated)
    
    def save(self, path: str):
        """Save calibrator to disk."""
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'wb') as f:
            pickle.dump(self, f)
    
    @classmethod
    def load(cls, path: str) -> "IsotonicCalibrator":
        """Load calibrator from disk."""
        with open(path, 'rb') as f:
            return pickle.load(f)


def create_isotonic_calibrator() -> IsotonicCalibrator:
    """Factory function for isotonic calibrator."""
    return IsotonicCalibrator()
