"""
Oracle Layer — Custom Calibrator (Pure Python, no external dependencies)
Learns calibration from our Polymarket evaluation data.
Market-agnostic: features in → calibrated probability out.
"""

import json
import pickle
import math
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class CalibrationFeatures:
    """Feature vector for a single market prediction."""
    jev_prob: float
    category: str
    latest_market_price: Optional[float]
    volume_24h: Optional[float]
    smart_money_net_flow: Optional[float]
    wallet_concentration: Optional[float]
    momentum_signal: str
    macro_wti: Optional[float]
    macro_gasoline_crack: Optional[float]
    macro_diesel_crack: Optional[float]
    macro_gpr: Optional[float]
    macro_dxy: Optional[float]
    macro_fed_funds: Optional[float]
    macro_breakeven_5y5y: Optional[float]
    macro_cass_freight: Optional[float]
    
    def to_vector(self, category_encoder: Dict[str, int]) -> List[float]:
        """Convert to feature vector for ML models."""
        cat_idx = category_encoder.get(self.category, 0)
        return [
            self.jev_prob,
            float(cat_idx),
            self.latest_market_price or 0.5,
            math.log1p(self.volume_24h or 0),
            self.smart_money_net_flow or 0.0,
            self.wallet_concentration or 0.0,
            {"bullish": 1, "bearish": -1, "neutral": 0}.get(self.momentum_signal, 0),
            self.macro_wti or 70.0,
            self.macro_gasoline_crack or 0.0,
            self.macro_diesel_crack or 0.0,
            self.macro_gpr or 100.0,
            self.macro_dxy or 103.0,
            self.macro_fed_funds or 4.5,
            self.macro_breakeven_5y5y or 2.5,
            self.macro_cass_freight or 1.0,
        ]


@dataclass
class TrainingExample:
    """Single training example: features + actual outcome."""
    features: CalibrationFeatures
    outcome: int  # 0 or 1
    market_id: str
    timestamp: datetime


class OracleCalibrator:
    """
    Market-agnostic calibrator.
    Learns from our evaluation data to produce calibrated probabilities.
    Pure Python implementation (no numpy/sklearn required).
    """
    
    def __init__(self):
        self.category_encoder: Dict[str, int] = {}
        self.category_decoder: Dict[int, str] = {}
        self.temperature: float = 1.0
        self.isotonic_x: List[float] = []  # sorted input probabilities
        self.isotonic_y: List[float] = []  # calibrated outputs (pool adjacent violators)
        self.logistic_weights: Optional[List[float]] = None
        self.logistic_bias: float = 0.0
        self.best_model_name: str = "temperature"
        self.trained: bool = False
        self.training_metadata: Dict[str, Any] = {}
        
        # Model paths
        self.model_dir = Path("/tmp/oracle_models")
        self.model_dir.mkdir(parents=True, exist_ok=True)
        
    def load_training_data(self, evaluation_files: List[str]) -> List[TrainingExample]:
        """Load training examples from evaluation JSON files."""
        examples = []
        all_categories = set()
        
        for filepath in evaluation_files:
            with open(filepath) as f:
                data = json.load(f)
            
            results = data.get("results", [])
            
            for r in results:
                if r.get("jev_prob") is None:
                    continue
                
                features = CalibrationFeatures(
                    jev_prob=r["jev_prob"],
                    category=r.get("category", "unknown"),
                    latest_market_price=r.get("latest_market_price"),
                    volume_24h=None,
                    smart_money_net_flow=None,
                    wallet_concentration=None,
                    momentum_signal="neutral",
                    macro_wti=None,
                    macro_gasoline_crack=None,
                    macro_diesel_crack=None,
                    macro_gpr=None,
                    macro_dxy=None,
                    macro_fed_funds=None,
                    macro_breakeven_5y5y=None,
                    macro_cass_freight=None,
                )
                
                all_categories.add(features.category)
                
                # Parse timestamp
                ts_str = data.get("completed_at", datetime.now().isoformat())
                try:
                    ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                except:
                    ts = datetime.now()
                
                example = TrainingExample(
                    features=features,
                    outcome=r["actual_outcome"],
                    market_id=r.get("condition_id", ""),
                    timestamp=ts,
                )
                examples.append(example)
        
        # Build category encoder
        sorted_cats = sorted(all_categories)
        self.category_encoder = {cat: i for i, cat in enumerate(sorted_cats)}
        self.category_decoder = {i: cat for i, cat in enumerate(sorted_cats)}
        
        # Sort by timestamp for time-series split
        examples.sort(key=lambda x: x.timestamp)
        
        print(f"Loaded {len(examples)} training examples from {len(evaluation_files)} evaluations")
        print(f"Categories: {sorted_cats}")
        
        return examples
    
    def prepare_data(self, examples: List[TrainingExample]) -> Tuple[List[List[float]], List[int]]:
        """Convert examples to X, y arrays."""
        X = [ex.features.to_vector(self.category_encoder) for ex in examples]
        y = [ex.outcome for ex in examples]
        return X, y
    
    def brier_score(self, y_true: List[int], y_prob: List[float]) -> float:
        """Compute Brier score."""
        return sum((p - y) ** 2 for p, y in zip(y_prob, y_true)) / len(y_true)
    
    def ece_score(self, y_true: List[int], y_prob: List[float], n_bins: int = 10) -> float:
        """Compute Expected Calibration Error."""
        ece = 0.0
        n = len(y_true)
        for i in range(n_bins):
            low = i / n_bins
            high = (i + 1) / n_bins
            bin_probs = []
            bin_outcomes = []
            for p, y in zip(y_prob, y_true):
                if low <= p < high:
                    bin_probs.append(p)
                    bin_outcomes.append(y)
            if not bin_probs:
                continue
            avg_prob = sum(bin_probs) / len(bin_probs)
            accuracy = sum(bin_outcomes) / len(bin_outcomes)
            weight = len(bin_probs) / n
            ece += weight * abs(avg_prob - accuracy)
        return ece
    
    def sigmoid(self, x: float) -> float:
        return 1.0 / (1.0 + math.exp(-x))
    
    def logit(self, p: float) -> float:
        p = max(1e-8, min(1 - 1e-8, p))
        return math.log(p / (1 - p))
    
    def train_temperature_scaling(self, probs: List[float], outcomes: List[int]) -> float:
        """Learn optimal temperature for scaling."""
        logits = [self.logit(p) for p in probs]
        
        best_T = 1.0
        best_brier = float('inf')
        
        for T in [i * 0.05 for i in range(2, 201)]:  # 0.1 to 10.0
            scaled = [self.sigmoid(l / T) for l in logits]
            brier = self.brier_score(outcomes, scaled)
            if brier < best_brier:
                best_brier = brier
                best_T = T
        
        return best_T
    
    def isotonic_regression(self, probs: List[float], outcomes: List[int]) -> Tuple[List[float], List[float]]:
        """
        Pool Adjacent Violators Algorithm (PAVA) for isotonic regression.
        Returns (sorted_unique_probs, calibrated_values) for interpolation.
        """
        # Combine and sort by probability
        pairs = sorted(zip(probs, outcomes))
        n = len(pairs)
        
        # Initialize: each point is its own block
        blocks = []
        for p, y in pairs:
            blocks.append({"probs": [p], "outcomes": [y], "avg_p": p, "avg_y": float(y)})
        
        # Pool adjacent violators
        i = 0
        while i < len(blocks) - 1:
            if blocks[i]["avg_y"] <= blocks[i + 1]["avg_y"]:
                i += 1
            else:
                # Merge blocks i and i+1
                merged_probs = blocks[i]["probs"] + blocks[i + 1]["probs"]
                merged_outcomes = blocks[i]["outcomes"] + blocks[i + 1]["outcomes"]
                merged_avg_p = sum(merged_probs) / len(merged_probs)
                merged_avg_y = sum(merged_outcomes) / len(merged_outcomes)
                blocks[i] = {
                    "probs": merged_probs,
                    "outcomes": merged_outcomes,
                    "avg_p": merged_avg_p,
                    "avg_y": merged_avg_y
                }
                del blocks[i + 1]
                # Step back to check previous
                if i > 0:
                    i -= 1
        
        # Extract calibrated values
        x_vals = [b["avg_p"] for b in blocks]
        y_vals = [b["avg_y"] for b in blocks]
        
        # Ensure monotonicity (should be guaranteed by PAVA)
        for i in range(1, len(y_vals)):
            if y_vals[i] < y_vals[i - 1]:
                y_vals[i] = y_vals[i - 1]
        
        return x_vals, y_vals
    
    def isotonic_predict(self, x_vals: List[float], y_vals: List[float], prob: float) -> float:
        """Interpolate isotonic calibration."""
        if prob <= x_vals[0]:
            return y_vals[0]
        if prob >= x_vals[-1]:
            return y_vals[-1]
        # Linear interpolation
        for i in range(len(x_vals) - 1):
            if x_vals[i] <= prob <= x_vals[i + 1]:
                t = (prob - x_vals[i]) / (x_vals[i + 1] - x_vals[i])
                return y_vals[i] + t * (y_vals[i + 1] - y_vals[i])
        return y_vals[-1]
    
    def train_logistic(self, X: List[List[float]], y: List[int], lr: float = 0.01, epochs: int = 1000) -> Tuple[List[float], float]:
        """Simple logistic regression with gradient descent."""
        n_features = len(X[0])
        weights = [0.0] * n_features
        bias = 0.0
        
        n = len(X)
        
        for epoch in range(epochs):
            # Compute predictions and gradients
            grad_w = [0.0] * n_features
            grad_b = 0.0
            
            for i in range(n):
                # Linear combination
                z = bias
                for j in range(n_features):
                    z += weights[j] * X[i][j]
                p = self.sigmoid(z)
                
                error = p - y[i]
                
                for j in range(n_features):
                    grad_w[j] += error * X[i][j]
                grad_b += error
            
            # Update
            for j in range(n_features):
                weights[j] -= lr * grad_w[j] / n
            bias -= lr * grad_b / n
        
        return weights, bias
    
    def logistic_predict(self, weights: List[float], bias: float, features: List[float]) -> float:
        z = bias
        for w, f in zip(weights, features):
            z += w * f
        return self.sigmoid(z)
    
    def train(self, evaluation_files: List[str]) -> Dict[str, Any]:
        """Train all calibration models and select best."""
        print("=" * 60)
        print("TRAINING ORACLE CALIBRATOR (Pure Python)")
        print("=" * 60)
        
        examples = self.load_training_data(evaluation_files)
        if len(examples) < 30:
            raise ValueError(f"Need at least 30 examples, got {len(examples)}")
        
        X, y = self.prepare_data(examples)
        probs = [x[0] for x in X]  # jev_prob is first feature
        
        # Time-series split for validation (older -> train, newer -> test)
        split_idx = int(len(examples) * 0.7)
        train_probs = probs[:split_idx]
        train_y = y[:split_idx]
        test_probs = probs[split_idx:]
        test_y = y[split_idx:]
        
        results = {}
        
        # 1. Temperature Scaling
        print("\n1. Temperature Scaling...")
        T = self.train_temperature_scaling(train_probs, train_y)
        scaled_test = [self.sigmoid(self.logit(p) / T) for p in test_probs]
        temp_brier = self.brier_score(test_y, scaled_test)
        temp_ece = self.ece_score(test_y, scaled_test)
        results["temperature"] = {"T": T, "brier": temp_brier, "ece": temp_ece}
        print(f"   T={T:.3f}, Brier={temp_brier:.4f}, ECE={temp_ece:.4f}")
        
        # 2. Isotonic Regression
        print("\n2. Isotonic Regression...")
        iso_x, iso_y = self.isotonic_regression(train_probs, train_y)
        iso_test = [self.isotonic_predict(iso_x, iso_y, p) for p in test_probs]
        iso_brier = self.brier_score(test_y, iso_test)
        iso_ece = self.ece_score(test_y, iso_test)
        results["isotonic"] = {"brier": iso_brier, "ece": iso_ece}
        print(f"   Brier={iso_brier:.4f}, ECE={iso_ece:.4f}")
        
        # 3. Logistic Regression (full features)
        print("\n3. Logistic Regression (full features)...")
        train_X = X[:split_idx]
        test_X = X[split_idx:]
        weights, bias = self.train_logistic(train_X, train_y)
        log_test = [self.logistic_predict(weights, bias, x) for x in test_X]
        log_brier = self.brier_score(test_y, log_test)
        log_ece = self.ece_score(test_y, log_test)
        results["logistic"] = {"brier": log_brier, "ece": log_ece}
        print(f"   Brier={log_brier:.4f}, ECE={log_ece:.4f}")
        
        # Select best by Brier score
        best_name = min(results.keys(), key=lambda k: results[k]["brier"])
        self.best_model_name = best_name
        
        # Store best model
        if best_name == "temperature":
            self.temperature = results[best_name]["T"]
        elif best_name == "isotonic":
            self.isotonic_x, self.isotonic_y = self.isotonic_regression(probs, y)
        elif best_name == "logistic":
            self.logistic_weights, self.logistic_bias = self.train_logistic(X, y)
        
        self.trained = True
        
        # Metadata
        self.training_metadata = {
            "trained_at": datetime.now().isoformat(),
            "n_examples": len(examples),
            "n_features": len(X[0]),
            "categories": list(self.category_decoder.values()),
            "results": results,
            "best_model": best_name,
            "best_brier": results[best_name]["brier"],
            "best_ece": results[best_name]["ece"],
        }
        
        print(f"\n{'='*60}")
        print(f"BEST MODEL: {best_name.upper()}")
        print(f"  Brier: {results[best_name]['brier']:.4f}")
        print(f"  ECE: {results[best_name]['ece']:.4f}")
        print(f"{'='*60}")
        
        return results
    
    def predict(self, features: CalibrationFeatures) -> float:
        """Predict calibrated probability for new market."""
        if not self.trained:
            raise RuntimeError("Calibrator not trained. Call train() first.")
        
        prob = features.jev_prob
        
        if self.best_model_name == "temperature":
            logit = self.logit(prob)
            calibrated = self.sigmoid(logit / self.temperature)
            return calibrated
        
        elif self.best_model_name == "isotonic":
            return self.isotonic_predict(self.isotonic_x, self.isotonic_y, prob)
        
        elif self.best_model_name == "logistic":
            X = features.to_vector(self.category_encoder)
            return self.logistic_predict(self.logistic_weights, self.logistic_bias, X)
        
        return prob  # fallback
    
    def predict_batch(self, features_list: List[CalibrationFeatures]) -> List[float]:
        return [self.predict(f) for f in features_list]
    
    def save(self, path: Optional[str] = None) -> str:
        """Save calibrator to disk."""
        if path is None:
            path = self.model_dir / f"oracle_calibrator_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pkl"
        
        save_data = {
            "category_encoder": self.category_encoder,
            "category_decoder": self.category_decoder,
            "temperature": self.temperature,
            "isotonic_x": self.isotonic_x,
            "isotonic_y": self.isotonic_y,
            "logistic_weights": self.logistic_weights,
            "logistic_bias": self.logistic_bias,
            "best_model_name": self.best_model_name,
            "trained": self.trained,
            "training_metadata": self.training_metadata,
        }
        
        with open(path, "wb") as f:
            pickle.dump(save_data, f)
        
        print(f"Calibrator saved to {path}")
        return str(path)
    
    @classmethod
    def load(cls, path: str) -> "OracleCalibrator":
        """Load calibrator from disk."""
        with open(path, "rb") as f:
            save_data = pickle.load(f)
        
        calibrator = cls()
        calibrator.category_encoder = save_data["category_encoder"]
        calibrator.category_decoder = save_data["category_decoder"]
        calibrator.temperature = save_data["temperature"]
        calibrator.isotonic_x = save_data["isotonic_x"]
        calibrator.isotonic_y = save_data["isotonic_y"]
        calibrator.logistic_weights = save_data["logistic_weights"]
        calibrator.logistic_bias = save_data["logistic_bias"]
        calibrator.best_model_name = save_data["best_model_name"]
        calibrator.trained = save_data["trained"]
        calibrator.training_metadata = save_data["training_metadata"]
        
        print(f"Calibrator loaded from {path} (model: {calibrator.best_model_name})")
        return calibrator


if __name__ == "__main__":
    # Train on existing evaluation files
    eval_files = [
        "/home/openclaw/.openclaw/workspace/oracle-layer/eval_report_eval_20260920_171015.json",
        "/home/openclaw/.openclaw/workspace/oracle-layer/eval_report_eval_20260920_172200.json",
        "/home/openclaw/.openclaw/workspace/oracle-layer/eval_report_eval_final_20260920_180142.json",
        "/home/openclaw/.openclaw/workspace/oracle-layer/eval_report_eval_ablation_20260920_173921.json",
    ]
    
    calibrator = OracleCalibrator()
    results = calibrator.train(eval_files)
    
    # Save
    calibrator.save()
    
    print("\nTraining complete. Ready for production use.")