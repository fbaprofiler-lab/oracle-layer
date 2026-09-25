"""Evaluation runner for forward evaluations.

Joins snapshots + outcomes, runs leakage scan, computes calibration metrics,
and emits a charter verdict (BUILD-1 / NARROW / KILL / INCONCLUSIVE).
"""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .forward_snapshot import read_snapshots
from .outcomes import join_outcomes
from .leakage_scanner import run_leakage_scan
from .evaluation_policy import determine_verdict


def _flatten_for_leakage(record: Mapping[str, Any]) -> dict[str, Any]:
    """Extract required leakage fields from features to top level."""
    flat = dict(record)
    features = record.get("features", {})
    if isinstance(features, Mapping):
        for key in ("macro_context", "smart_money_net_flow", "prediction_timestamp", "outcome_timestamp"):
            if key in features and key not in flat:
                flat[key] = features[key]
    return flat


def compute_calibration(results: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Compute calibration metrics: ECE, Brier, reliability curve."""
    if not results:
        return {
            "status": "no_data", "n": 0, "accuracy": 0.0,
            "brier_score": 0.0, "ece": 0.0,
            "calibration_curve": [], "by_category": {},
            "reliability": "no_data",
        }
    
    # Compute correct from probability > 0.5 vs actual_outcome
    for r in results:
        prob = r.get("probability", 0.5)
        actual = r.get("actual_outcome", 0)
        r["correct"] = 1 if (prob > 0.5) == (actual == 1) else 0
    
    n = len(results)
    correct = sum(1 for r in results if r.get("correct") == 1)
    accuracy = correct / n
    
    brier = sum((r.get("probability", 0.5) - r.get("actual_outcome", 0)) ** 2 for r in results) / n
    
    bins = 10
    bin_edges = [i / bins for i in range(bins + 1)]
    ece = 0.0
    calibration_curve = []
    
    for i in range(bins):
        low, high = bin_edges[i], bin_edges[i + 1]
        bin_preds = [r for r in results if low <= r.get("probability", 0.5) < high]
        
        if not bin_preds:
            calibration_curve.append({"bin": f"{low:.1f}-{high:.1f}", "count": 0, "accuracy": None, "avg_prob": None})
            continue
        
        avg_prob = sum(r.get("probability", 0.5) for r in bin_preds) / len(bin_preds)
        bin_accuracy = sum(r.get("actual_outcome", 0) for r in bin_preds) / len(bin_preds)
        bin_weight = len(bin_preds) / n
        ece += bin_weight * abs(avg_prob - bin_accuracy)
        
        calibration_curve.append({
            "bin": f"{low:.1f}-{high:.1f}",
            "count": len(bin_preds),
            "accuracy": round(bin_accuracy, 4),
            "avg_prob": round(avg_prob, 4),
        })
    
    categories = {}
    for r in results:
        cat = r.get("category", "unknown")
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(r)
    
    cat_metrics = {}
    for cat, cat_results in categories.items():
        cat_n = len(cat_results)
        cat_correct = sum(1 for r in cat_results if r.get("correct") == 1)
        cat_brier = sum((r.get("probability", 0.5) - r.get("actual_outcome", 0)) ** 2 for r in cat_results) / cat_n
        cat_metrics[cat] = {"n": cat_n, "accuracy": cat_correct / cat_n, "brier": round(cat_brier, 4)}
    
    return {
        "status": "ok", "n": n, "accuracy": round(accuracy, 4),
        "brier_score": round(brier, 4), "ece": round(ece, 4),
        "calibration_curve": calibration_curve, "by_category": cat_metrics,
        "reliability": "good" if ece < 0.05 else "moderate" if ece < 0.10 else "poor",
    }


def run_evaluation(
    snapshot_path: str | Path,
    outcome_path: str | Path,
    prereg_path: str | Path | None = None,
    gates: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Run full evaluation: join snapshots/outcomes → leakage scan → metrics → verdict."""
    
    joined = join_outcomes(snapshot_path, outcome_path)
    valid_results = [r for r in joined if r.get("probability") is not None]
    
    if not valid_results:
        return {
            "status": "no_data", "verdict": "INCONCLUSIVE",
            "message": "no valid predictions with outcomes",
        }
    
    # Leakage scan on joined records with flattened features
    if prereg_path is None:
        prereg_path = Path(snapshot_path).with_suffix(".prereg.json")
    
    # Create a temporary joined file with flattened features for leakage scanning
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
        for record in joined:
            flat = dict(record)
            features = record.get("features", {})
            if isinstance(features, dict):
                for key in ("macro_context", "smart_money_net_flow", "prediction_timestamp", "outcome_timestamp"):
                    if key in features and key not in record:
                        record[key] = features[key]
            f.write(json.dumps(record, default=str) + '\n')
        joined_path = f.name
    
    try:
        leakage = run_leakage_scan(str(prereg_path), str(joined_path), str(joined_path))
    finally:
        Path(joined_path).unlink(missing_ok=True)
    
    # Metrics
    metrics = compute_calibration(valid_results)
    
    # Default gates from charter
    if gates is None:
        gates = {
            "ece_threshold": 0.05,
            "brier_threshold": 0.20,
            "hit_rate_threshold": 0.55,
            "min_samples": 100,
        }
    
    # Determine verdict
    verdict = determine_verdict(metrics, "forward", gates)
    
    # Override with INCONCLUSIVE if insufficient samples
    if metrics["n"] < gates["min_samples"]:
        verdict = "INCONCLUSIVE"
    
    report = {
        "evaluation_id": f"eval_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "snapshot_path": str(snapshot_path),
        "outcome_path": str(outcome_path),
        "prereg_path": str(prereg_path),
        "n": metrics["n"],
        "metrics": metrics,
        "leakage_scan": leakage,
        "gates": {
            "ece": {"threshold": gates["ece_threshold"], "actual": metrics["ece"], "passed": metrics["ece"] < gates["ece_threshold"]},
            "brier": {"threshold": gates["brier_threshold"], "actual": metrics["brier_score"], "passed": metrics["brier_score"] < gates["brier_threshold"]},
            "hit_rate": {"threshold": gates["hit_rate_threshold"], "actual": metrics["accuracy"], "passed": metrics["accuracy"] > gates["hit_rate_threshold"]},
            "min_samples": {"threshold": gates["min_samples"], "actual": metrics["n"], "passed": metrics["n"] >= gates["min_samples"]},
        },
        "verdict": verdict,
        "leakage_passed": leakage.get("pass", False),
    }
    
    return report


def save_report(report: Mapping[str, Any], output_path: str | Path) -> None:
    """Save evaluation report to file."""
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(report), indent=2, default=str) + "\n", encoding="utf-8")


def run_evaluation_for_cohort(
    cohort_manifest_path: str | Path,
    snapshot_path: str | Path,
    outcome_dir: str | Path,
    gates: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Run evaluation for a single cohort."""
    import json
    manifest = json.loads(Path(cohort_manifest_path).read_text())
    cohort_id = manifest.get("cohort_id")
    
    outcome_path = Path(outcome_dir) / f"{cohort_id}.outcomes.jsonl"
    if not outcome_path.exists():
        return {"cohort_id": cohort_id, "error": "no outcomes file"}
    
    prereg_path = Path(snapshot_path).parent.parent / "cohorts" / f"{cohort_id}.prereg.json"
    if not prereg_path.exists():
        prereg_path = None
    
    report = run_evaluation(snapshot_path, outcome_path, prereg_path, gates)
    report["cohort_id"] = cohort_id
    
    # Save report
    report_path = Path(outcome_dir).parent / "eval_reports" / f"{cohort_id}.eval_report.json"
    save_report(report, report_path)
    
    return report
