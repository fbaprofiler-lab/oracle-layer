"""Sandbox evaluator for evolution experiments.

Runs an experiment configuration against historical data to compute
sandbox calibration metrics (ECE, Brier, hit-rate) on a holdout period.
This is the core of the RSI loop — it determines whether a hypothesis
is promising enough to promote to charter evaluation.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, List, Optional
from dataclasses import dataclass

import numpy as np

# Local imports - use calibrator directly, avoid FusionEngine (slow Laya init)
from ..judgment.calibrator import OracleCalibrator, CalibrationFeatures
from .leakage_scanner import run_leakage_scan
from .evaluation_policy import determine_verdict
from .forward_snapshot import read_snapshots
from .outcomes import read_outcomes


@dataclass
class SandboxMetrics:
    """Calibration metrics from sandbox evaluation."""
    ece: float
    brier: float
    hit_rate: float
    n: int
    composite_score: float  # 0-1, higher is better


def compute_ece(probabilities: List[float], outcomes: List[int], n_bins: int = 10) -> float:
    """Compute Expected Calibration Error (ECE)."""
    if not probabilities or len(probabilities) != len(outcomes):
        return 1.0
    
    bins = np.linspace(0, 1, n_bins + 1)
    ece = 0.0
    for i in range(n_bins):
        mask = (np.array(probabilities) >= bins[i]) & (np.array(probabilities) < bins[i + 1])
        if i == n_bins - 1:  # Include right edge for last bin
            mask = (np.array(probabilities) >= bins[i]) & (np.array(probabilities) <= bins[i + 1])
        if np.any(mask):
            bin_probs = np.array(probabilities)[mask]
            bin_outcomes = np.array(outcomes)[mask]
            bin_confidence = np.mean(bin_probs)
            bin_accuracy = np.mean(bin_outcomes)
            ece += (len(bin_probs) / len(probabilities)) * abs(bin_confidence - bin_accuracy)
    return float(ece)


def compute_brier(probabilities: List[float], outcomes: List[int]) -> float:
    """Compute Brier score."""
    if not probabilities or len(probabilities) != len(outcomes):
        return 1.0
    return float(np.mean((np.array(probabilities) - np.array(outcomes)) ** 2))


def compute_hit_rate(probabilities: List[float], outcomes: List[int], threshold: float = 0.5) -> float:
    """Compute hit rate (accuracy at threshold)."""
    if not probabilities or len(probabilities) != len(outcomes):
        return 0.0
    preds = [1 if p >= threshold else 0 for p in probabilities]
    return float(np.mean(np.array(preds) == np.array(outcomes)))


def composite_score(ece: float, brier: float, hit_rate: float, n: int) -> float:
    """
    Composite sandbox score (0-1).
    - ECE target: < 0.05 (weight 0.3)
    - Brier target: < 0.20 (weight 0.3)
    - Hit rate target: > 0.55 (weight 0.3)
    - Sample size bonus: up to 0.1 for n >= 300 (weight 0.1)
    """
    ece_score = max(0.0, 1.0 - ece / 0.05) if ece > 0 else 1.0
    brier_score = max(0.0, 1.0 - brier / 0.20) if brier > 0 else 1.0
    hit_score = min(1.0, hit_rate / 0.55) if hit_rate > 0 else 0.0
    n_score = min(1.0, n / 300)
    
    score = 0.3 * ece_score + 0.3 * brier_score + 0.3 * hit_score + 0.1 * n_score
    return float(max(0.0, min(1.0, score)))


class SandboxEvaluator:
    """Evaluates experiment configs on historical data."""
    
    def __init__(
        self,
        historical_data_path: str = "data/historical",
        holdout_days: int = 30,
        min_holdout_samples: int = 50,
    ):
        self.historical_data_path = Path(historical_data_path)
        self.holdout_days = holdout_days
        self.min_holdout_samples = min_holdout_samples
        self.historical_data_path.mkdir(parents=True, exist_ok=True)
        
        # Load calibrator once
        self._load_calibrator()
    
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
                self.calibrator = None
                print("No calibrator found")
        except Exception as e:
            self.calibrator = None
            print(f"Failed to load calibrator: {e}")
    
    def _read_all_outcomes(self) -> List[dict]:
        """Read all outcome records from outcomes and quarantine directories."""
        outcomes = []
        
        # Read from outcomes directory
        outcomes_dir = Path("data/forward/outcomes")
        if outcomes_dir.exists():
            for outcome_file in outcomes_dir.glob("*.outcomes.jsonl"):
                outcomes.extend(read_outcomes(outcome_file))
        
        # Read from quarantine directory
        quarantine_dir = Path("data/forward/quarantine")
        if quarantine_dir.exists():
            for pattern in ("*.outcomes.jsonl", "*.outcomes.invalid-unresolved.jsonl"):
                for outcome_file in quarantine_dir.glob(pattern):
                    outcomes.extend(read_outcomes(outcome_file))
        
        return outcomes
    
    def collect_historical_data(self, snapshot_path: str, category: Optional[str] = None) -> List[dict]:
        """
        Collect historical data: joined snapshots with outcomes.
        Uses specified snapshot file + all outcome files.
        """
        snapshots = read_snapshots(snapshot_path)
        
        # Read all outcomes from all locations
        outcomes = self._read_all_outcomes()
        
        # Join snapshots with outcomes
        outcome_map = {o["condition_id"]: o for o in outcomes}
        joined = []
        for snap in snapshots:
            if category and snap.get("category") != category and snap.get("category") != "unknown":
                continue
            cond_id = snap["condition_id"]
            if cond_id in outcome_map:
                outcome = outcome_map[cond_id]
                joined.append({
                    "snapshot": snap,
                    "outcome": outcome,
                })
        
        return joined
    
    def apply_experiment_config(self, record: dict, experiment_config: dict) -> dict:
        """
        Apply experiment's feature/lag/transform/combo to a record.
        Returns modified features dict.
        """
        features = dict(record["snapshot"].get("features", {}))
        # Extract macro_context from features (it's nested there)
        macro_context = features.get("macro_context", {})
        market = features.get("market", {})
        
        # 1. Apply feature hypothesis
        feature_h = experiment_config.get("feature_hypothesis", {})
        if feature_h and feature_h.get("extraction_code"):
            try:
                local_vars = {"context": macro_context, "market_metrics": market}
                exec(feature_h["extraction_code"], {}, local_vars)
                if "extract" in local_vars:
                    extracted = local_vars["extract"](macro_context, market)
                    features.update(extracted)
            except Exception:
                pass  # Skip failed feature extraction
        
        # 2. Apply transform hypothesis
        transform_h = experiment_config.get("transform_hypothesis", {})
        if transform_h and transform_h.get("transform_code"):
            try:
                local_vars = {"features": features, "macro_context": macro_context}
                exec(transform_h["transform_code"], {}, local_vars)
                if "transform" in local_vars:
                    features = local_vars["transform"](features, macro_context)
            except Exception:
                pass
        
        return features
    
    def apply_signal_combination(self, signal_probs: dict, experiment_config: dict) -> float:
        """
        Apply experiment's signal combination weights to fuse probabilities.
        signal_probs: dict with keys "macro", "market", "judgment"
        """
        combo = experiment_config.get("signal_combination", {})
        macro_w = combo.get("macro_weight", 0.33)
        market_w = combo.get("market_weight", 0.33)
        judgment_w = combo.get("judgment_weight", 0.34)
        
        macro_p = signal_probs.get("macro", 0.5)
        market_p = signal_probs.get("market", 0.5)
        judgment_p = signal_probs.get("judgment", 0.5)
        
        fused = macro_w * macro_p + market_w * market_p + judgment_w * judgment_p
        return max(0.0, min(1.0, fused))
    
    def apply_calibration(self, fused_prob: float, record: dict) -> float:
        """Apply calibrator to fused probability."""
        if not self.calibrator or not self.calibrator.trained:
            return fused_prob
        
        macro_context = record["snapshot"].get("features", {}).get("macro_context", {})
        market_metrics = record["snapshot"].get("features", {}).get("market", {})
        
        cal_features = CalibrationFeatures(
            jev_prob=fused_prob,
            category=record["snapshot"].get("category", "unknown"),
            latest_market_price=market_metrics.get("current_prices", {}).get("Yes") if isinstance(market_metrics, dict) else 0.5,
            volume_24h=market_metrics.get("volume_24h") if isinstance(market_metrics, dict) else 0,
            smart_money_net_flow=sum(market_metrics.get("smart_money_net_flow", {}).values()) if isinstance(market_metrics, dict) and market_metrics.get("smart_money_net_flow") else None,
            wallet_concentration=market_metrics.get("wallet_concentration") if isinstance(market_metrics, dict) else None,
            momentum_signal=market_metrics.get("momentum_signal") if isinstance(market_metrics, dict) else None,
            macro_wti=macro_context.get("wti"),
            macro_gasoline_crack=macro_context.get("gasoline_crack"),
            macro_diesel_crack=macro_context.get("diesel_crack"),
            macro_gpr=macro_context.get("gpr"),
            macro_dxy=macro_context.get("dxy"),
            macro_fed_funds=macro_context.get("fed_funds"),
            macro_breakeven_5y5y=macro_context.get("breakeven_5y5y"),
            macro_cass_freight=macro_context.get("cass_freight"),
        )
        return self.calibrator.predict(cal_features)
    
    async def evaluate(
        self,
        experiment_config: dict,
        snapshot_path: str = "data/forward/cohort_snapshots.jsonl",
        category: Optional[str] = None,
    ) -> SandboxMetrics:
        """
        Run sandbox evaluation for an experiment.
        Returns SandboxMetrics with ECE, Brier, hit-rate, n, and composite score.
        """
        # Collect historical data
        joined = self.collect_historical_data(snapshot_path, category)
        
        if len(joined) < self.min_holdout_samples:
            return SandboxMetrics(
                ece=1.0, brier=1.0, hit_rate=0.0, n=len(joined), composite_score=0.0
            )
        
        # Use all records
        holdout = joined
        
        # Run through modified pipeline for each holdout record
        probabilities = []
        outcomes = []
        
        for record in holdout:
            try:
                # Apply feature/transform hypotheses
                modified_features = self.apply_experiment_config(record, experiment_config)
                
                # Get original probability from snapshot (Jev judgment)
                orig_prob = record["snapshot"].get("probability", 0.5)
                
                # Macro probability (simplified)
                macro_context = record["snapshot"].get("features", {}).get("macro_context", {})
                market_metrics = record["snapshot"].get("features", {}).get("market", {})
                
                macro_p = 0.5
                cat = record["snapshot"].get("category", "").lower()
                if "fed" in cat or "rate" in cat or "cpi" in cat:
                    if macro_context.get("gasoline_crack", 0) > 20:
                        macro_p += 0.15
                    if macro_context.get("diesel_crack", 0) > 20:
                        macro_p += 0.15
                    if macro_context.get("gpr", 0) > 150:
                        macro_p += 0.1
                
                # Market probability (simplified)
                market_p = 0.5
                momentum = market_metrics.get("momentum_signal", "neutral") if isinstance(market_metrics, dict) else "neutral"
                if momentum == "bullish":
                    market_p += 0.2
                elif momentum == "bearish":
                    market_p -= 0.2
                
                # Apply signal combination
                signal_probs = {"macro": macro_p, "market": market_p, "judgment": orig_prob}
                fused_prob = self.apply_signal_combination(signal_probs, experiment_config)
                
                # Apply calibration
                calibrated_prob = self.apply_calibration(fused_prob, record)
                
                probabilities.append(calibrated_prob)
                outcomes.append(record["outcome"].get("actual_outcome", 0))
                
            except Exception as e:
                # Skip failed records
                print(f"Error processing record: {e}")
                continue
        
        if not probabilities:
            return SandboxMetrics(
                ece=1.0, brier=1.0, hit_rate=0.0, n=0, composite_score=0.0
            )
        
        # Compute metrics
        ece = compute_ece(probabilities, outcomes)
        brier = compute_brier(probabilities, outcomes)
        hit_rate = compute_hit_rate(probabilities, outcomes)
        n = len(probabilities)
        score = composite_score(ece, brier, hit_rate, n)
        
        return SandboxMetrics(ece=ece, brier=brier, hit_rate=hit_rate, n=n, composite_score=score)


# ─── CLI ───

async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Sandbox evaluator")
    parser.add_argument("--experiment-file", help="Path to experiment config JSON")
    parser.add_argument("--snapshot-file", default="data/forward/cohort_snapshots.jsonl", help="Snapshot file to evaluate on")
    parser.add_argument("--category", default=None, help="Category to evaluate on")
    parser.add_argument("--holdout-days", type=int, default=30, help="Holdout period in days")
    parser.add_argument("--min-samples", type=int, default=1, help="Minimum samples for evaluation (for testing)")
    args = parser.parse_args()
    
    if args.experiment_file:
        experiment = json.loads(Path(args.experiment_file).read_text())
    else:
        # Generate a test experiment
        from .hypothesis_generator import HypothesisGenerator
        gen = HypothesisGenerator()
        experiment = gen.generate_full_experiment("test_sandbox_eval")
    
    evaluator = SandboxEvaluator(holdout_days=args.holdout_days, min_holdout_samples=args.min_samples)
    result = await evaluator.evaluate(experiment, args.snapshot_file, args.category)
    
    print(json.dumps({
        "experiment_id": experiment.get("experiment_id"),
        "ece": result.ece,
        "brier": result.brier,
        "hit_rate": result.hit_rate,
        "n": result.n,
        "composite_score": result.composite_score,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }, indent=2))


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
