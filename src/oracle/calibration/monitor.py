"""
Oracle Layer — Calibration Monitoring Dashboard
Daily automated ECE/Brier/hit-rate tracking with regression alerts.
Level 2 RSI: Evaluation machinery that improves itself.
"""

import asyncio
import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from collections import defaultdict

from ..core.config import settings
from ..judgment.laya_client import LayaJevCompatClient as JevClient, LayaInput as JevInput, LayaDecisionType as JevDecisionType, LayaOutput as JevOutput
from ..judgment.calibrator import OracleCalibrator, CalibrationFeatures


@dataclass
class CalibrationSnapshot:
    """Single calibration measurement."""
    timestamp: datetime
    n_predictions: int
    ece: float
    brier_score: float
    accuracy: float
    by_category: Dict[str, Dict]
    reliability: str


@dataclass
class RegressionAlert:
    """Calibration regression alert."""
    alert_id: str
    timestamp: datetime
    metric: str  # ece, brier, accuracy
    current_value: float
    threshold: float
    severity: str  # warning, critical
    message: str


class CalibrationMonitor:
    """
    Continuous calibration monitoring for production Jev judgments.
    Runs daily, tracks rolling windows, alerts on regression.
    """

    def __init__(self, lookback_days: int = 30):
        self.lookback_days = lookback_days
        self.snapshots: List[CalibrationSnapshot] = []
        self.alerts: List[RegressionAlert] = []
        self.history_file = Path("/home/openclaw/.openclaw/workspace/oracle-layer/calibration_history.json")
        self.calibrator: Optional[OracleCalibrator] = None
        self._load_history()
        self._load_calibrator()

    def _load_calibrator(self):
        """Load trained calibrator."""
        try:
            model_dir = Path("/tmp/oracle_models")
            calibrator_files = list(model_dir.glob("oracle_calibrator_*.pkl"))
            if calibrator_files:
                latest = max(calibrator_files, key=lambda f: f.stat().st_mtime)
                self.calibrator = OracleCalibrator.load(str(latest))
        except Exception:
            pass

    def _load_history(self):
        """Load historical snapshots."""
        if self.history_file.exists():
            with open(self.history_file) as f:
                data = json.load(f)
            for s in data.get("snapshots", []):
                self.snapshots.append(CalibrationSnapshot(
                    timestamp=datetime.fromisoformat(s["timestamp"]),
                    n_predictions=s["n_predictions"],
                    ece=s["ece"],
                    brier_score=s["brier_score"],
                    accuracy=s["accuracy"],
                    by_category=s["by_category"],
                    reliability=s["reliability"],
                ))
            for a in data.get("alerts", []):
                self.alerts.append(RegressionAlert(
                    alert_id=a["alert_id"],
                    timestamp=datetime.fromisoformat(a["timestamp"]),
                    metric=a["metric"],
                    current_value=a["current_value"],
                    threshold=a["threshold"],
                    severity=a["severity"],
                    message=a["message"],
                ))

    def _save_history(self):
        """Persist snapshots and alerts."""
        data = {
            "snapshots": [
                {
                    "timestamp": s.timestamp.isoformat(),
                    "n_predictions": s.n_predictions,
                    "ece": s.ece,
                    "brier_score": s.brier_score,
                    "accuracy": s.accuracy,
                    "by_category": s.by_category,
                    "reliability": s.reliability,
                }
                for s in self.snapshots
            ],
            "alerts": [
                {
                    "alert_id": a.alert_id,
                    "timestamp": a.timestamp.isoformat(),
                    "metric": a.metric,
                    "current_value": a.current_value,
                    "threshold": a.threshold,
                    "severity": a.severity,
                    "message": a.message,
                }
                for a in self.alerts
            ],
        }
        self.history_file.write_text(json.dumps(data, indent=2))

    def record_jev_call(self, jev_output: JevOutput, features: Dict, actual_outcome: Optional[bool] = None):
        """Record a Jev prediction for later calibration."""
        daily_file = Path(f"/home/openclaw/.openclaw/workspace/oracle-layer/calibration_daily_{datetime.now().strftime('%Y%m%d')}.jsonl")
        record = {
            "timestamp": datetime.now().isoformat(),
            "decision_id": jev_output.decision_id,
            "market_id": jev_output.market_id,
            "decision_type": jev_output.decision_type.value,
            "probability": jev_output.probability,
            "confidence": jev_output.confidence,
            "features": features,
            "outcome": actual_outcome,
        }
        with open(daily_file, "a") as f:
            f.write(json.dumps(record) + "\n")

    def compute_daily_calibration(self, date: datetime = None) -> Optional[CalibrationSnapshot]:
        """Compute calibration metrics for a specific day."""
        if date is None:
            date = datetime.now().date()
        
        daily_file = Path(f"/home/openclaw/.openclaw/workspace/oracle-layer/calibration_daily_{date.strftime('%Y%m%d')}.jsonl")
        if not daily_file.exists():
            return None
        
        records = []
        with open(daily_file) as f:
            for line in f:
                try:
                    r = json.loads(line)
                    if r.get("outcome") is not None:
                        records.append(r)
                except:
                    continue
        
        if len(records) < 10:
            return None
        
        y_true = [r["outcome"] for r in records]
        y_prob = [r["probability"] for r in records]
        
        # Brier score
        brier = sum((p - y) ** 2 for p, y in zip(y_prob, y_true)) / len(y_true)
        
        # Accuracy
        correct = sum(1 for p, y in zip(y_prob, y_true) if (p > 0.5) == y)
        accuracy = correct / len(y_true)
        
        # ECE (10 bins)
        bins = 10
        ece = 0.0
        n = len(y_true)
        for i in range(bins):
            low, high = i / bins, (i + 1) / bins
            bin_pairs = [(p, y) for p, y in zip(y_prob, y_true) if low <= p < high]
            if not bin_pairs:
                continue
            avg_prob = sum(p for p, _ in bin_pairs) / len(bin_pairs)
            bin_acc = sum(y for _, y in bin_pairs) / len(bin_pairs)
            ece += (len(bin_pairs) / n) * abs(avg_prob - bin_acc)
        
        # By category
        by_cat = defaultdict(list)
        for r in records:
            cat = r.get("features", {}).get("category", "unknown")
            by_cat[cat].append(r)
        
        cat_metrics = {}
        for cat, cat_records in by_cat.items():
            cat_y_true = [r["outcome"] for r in cat_records]
            cat_y_prob = [r["probability"] for r in cat_records]
            cat_brier = sum((p - y) ** 2 for p, y in zip(cat_y_prob, cat_y_true)) / len(cat_y_true)
            cat_acc = sum(1 for p, y in zip(cat_y_prob, cat_y_true) if (p > 0.5) == y) / len(cat_y_true)
            cat_metrics[cat] = {"n": len(cat_records), "accuracy": round(cat_acc, 4), "brier": round(cat_brier, 4)}
        
        reliability = "good" if ece < 0.05 else "moderate" if ece < 0.10 else "poor"
        
        snapshot = CalibrationSnapshot(
            timestamp=datetime.combine(date, datetime.min.time()),
            n_predictions=len(records),
            ece=round(ece, 4),
            brier_score=round(brier, 4),
            accuracy=round(accuracy, 4),
            by_category=cat_metrics,
            reliability=reliability,
        )
        
        return snapshot

    def check_regression(self, snapshot: CalibrationSnapshot) -> List[RegressionAlert]:
        """Check for calibration regression vs recent history."""
        alerts = []
        
        # Compare to 7-day rolling average
        recent = [s for s in self.snapshots if s.timestamp >= snapshot.timestamp - timedelta(days=7)]
        if len(recent) >= 3:
            avg_ece = sum(s.ece for s in recent) / len(recent)
            avg_brier = sum(s.brier_score for s in recent) / len(recent)
            avg_acc = sum(s.accuracy for s in recent) / len(recent)
            
            # ECE regression
            if snapshot.ece > max(0.10, avg_ece * 1.5):
                alerts.append(RegressionAlert(
                    alert_id=f"reg_ece_{snapshot.timestamp.strftime('%Y%m%d')}",
                    timestamp=snapshot.timestamp,
                    metric="ece",
                    current_value=snapshot.ece,
                    threshold=round(max(0.10, avg_ece * 1.5), 4),
                    severity="critical" if snapshot.ece > 0.10 else "warning",
                    message=f"ECE regression: {snapshot.ece:.4f} vs 7-day avg {avg_ece:.4f}"
                ))
            
            # Brier regression
            if snapshot.brier_score > max(0.25, avg_brier * 1.3):
                alerts.append(RegressionAlert(
                    alert_id=f"reg_brier_{snapshot.timestamp.strftime('%Y%m%d')}",
                    timestamp=snapshot.timestamp,
                    metric="brier",
                    current_value=snapshot.brier_score,
                    threshold=round(max(0.25, avg_brier * 1.3), 4),
                    severity="critical" if snapshot.brier_score > 0.25 else "warning",
                    message=f"Brier regression: {snapshot.brier_score:.4f} vs 7-day avg {avg_brier:.4f}"
                ))
            
            # Accuracy drop
            if snapshot.accuracy < min(0.50, avg_acc * 0.9):
                alerts.append(RegressionAlert(
                    alert_id=f"reg_acc_{snapshot.timestamp.strftime('%Y%m%d')}",
                    timestamp=snapshot.timestamp,
                    metric="accuracy",
                    current_value=snapshot.accuracy,
                    threshold=round(min(0.50, avg_acc * 0.9), 4),
                    severity="warning",
                    message=f"Accuracy drop: {snapshot.accuracy:.2%} vs 7-day avg {avg_acc:.2%}"
                ))
        
        # Absolute thresholds (charter gates)
        if snapshot.ece > 0.10:
            alerts.append(RegressionAlert(
                alert_id=f"abs_ece_{snapshot.timestamp.strftime('%Y%m%d')}",
                timestamp=snapshot.timestamp,
                metric="ece",
                current_value=snapshot.ece,
                threshold=0.10,
                severity="critical",
                message=f"ECE exceeds charter kill threshold (0.10): {snapshot.ece:.4f}"
            ))
        
        if snapshot.brier_score > 0.25:
            alerts.append(RegressionAlert(
                alert_id=f"abs_brier_{snapshot.timestamp.strftime('%Y%m%d')}",
                timestamp=snapshot.timestamp,
                metric="brier",
                current_value=snapshot.brier_score,
                threshold=0.25,
                severity="critical",
                message=f"Brier exceeds charter kill threshold (0.25): {snapshot.brier_score:.4f}"
            ))
        
        if snapshot.accuracy < 0.50:
            alerts.append(RegressionAlert(
                alert_id=f"abs_acc_{snapshot.timestamp.strftime('%Y%m%d')}",
                timestamp=snapshot.timestamp,
                metric="accuracy",
                current_value=snapshot.accuracy,
                threshold=0.50,
                severity="critical",
                message=f"Accuracy below charter minimum (50%): {snapshot.accuracy:.2%}"
            ))
        
        return alerts

    async def run_daily_check(self) -> Dict[str, Any]:
        """Run daily calibration check and return status."""
        today = datetime.now().date()
        snapshot = self.compute_daily_calibration(today)
        
        if snapshot is None:
            return {"status": "no_data", "date": today.isoformat()}
        
        # Check regression
        new_alerts = self.check_regression(snapshot)
        self.alerts.extend(new_alerts)
        
        # Keep last 30 days
        cutoff = datetime.now() - timedelta(days=30)
        self.snapshots = [s for s in self.snapshots if s.timestamp >= cutoff]
        self.snapshots.append(snapshot)
        
        self._save_history()
        
        return {
            "status": "ok",
            "date": today.isoformat(),
            "snapshot": {
                "n": snapshot.n_predictions,
                "ece": snapshot.ece,
                "brier": snapshot.brier_score,
                "accuracy": snapshot.accuracy,
                "reliability": snapshot.reliability,
                "by_category": snapshot.by_category,
            },
            "new_alerts": len(new_alerts),
            "alerts": [
                {"metric": a.metric, "severity": a.severity, "message": a.message}
                for a in new_alerts
            ],
        }

    def get_dashboard_data(self) -> Dict[str, Any]:
        """Get data for monitoring dashboard."""
        return {
            "snapshots": [
                {
                    "date": s.timestamp.strftime("%Y-%m-%d"),
                    "n": s.n_predictions,
                    "ece": s.ece,
                    "brier": s.brier_score,
                    "accuracy": s.accuracy,
                    "reliability": s.reliability,
                }
                for s in sorted(self.snapshots, key=lambda x: x.timestamp)[-30:]
            ],
            "active_alerts": [
                {
                    "alert_id": a.alert_id,
                    "date": a.timestamp.strftime("%Y-%m-%d"),
                    "metric": a.metric,
                    "value": a.current_value,
                    "threshold": a.threshold,
                    "severity": a.severity,
                    "message": a.message,
                }
                for a in self.alerts if a.timestamp >= datetime.now() - timedelta(days=7)
            ],
            "summary": {
                "current_ece": self.snapshots[-1].ece if self.snapshots else None,
                "current_brier": self.snapshots[-1].brier_score if self.snapshots else None,
                "current_accuracy": self.snapshots[-1].accuracy if self.snapshots else None,
                "trend_7d_ece": self._trend("ece", 7),
                "trend_7d_brier": self._trend("brier_score", 7),
                "trend_7d_accuracy": self._trend("accuracy", 7),
            }
        }

    def _trend(self, metric: str, days: int) -> Optional[str]:
        """Compute trend direction over N days."""
        recent = [s for s in self.snapshots if s.timestamp >= datetime.now() - timedelta(days=days)]
        if len(recent) < 3:
            return None
        values = [getattr(s, metric) for s in recent]
        # Simple linear trend
        n = len(values)
        x = list(range(n))
        xy = sum(x[i] * values[i] for i in range(n))
        xx = sum(x[i] * x[i] for i in range(n))
        x_sum = sum(x)
        y_sum = sum(values)
        slope = (n * xy - x_sum * y_sum) / (n * xx - x_sum * x_sum)
        if slope > 0.001:
            return "improving" if metric in ["accuracy"] else "worsening"
        elif slope < -0.001:
            return "worsening" if metric in ["accuracy"] else "improving"
        return "stable"


async def run_calibration_monitor():
    """Standalone entry point for daily cron."""
    monitor = CalibrationMonitor()
    result = await monitor.run_daily_check()
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    asyncio.run(run_calibration_monitor())
