import tempfile
import unittest
from pathlib import Path

from oracle.calibration.forward_snapshot import append_snapshot, create_snapshot
from oracle.calibration.outcomes import append_outcome, create_outcome
from oracle.calibration.evaluation_runner import run_evaluation


class EvaluationRunnerTests(unittest.TestCase):
    def make_snapshot(self, condition_id, question, prob, cat="test"):
        # Include enhanced fields required for forward evaluation
        return create_snapshot(
            evaluation_id="eval", prediction_timestamp="2026-09-24T15:00:00+00:00",
            condition_id=condition_id, question=question, category=cat, features={
                "macro_context": {"wti": 70.0, "source": "test"},
                "smart_money_net_flow": {"Yes": 1000, "No": -500},
                "source_collected_at": "2026-09-24T15:00:00+00:00",
                "feature_schema_version": "forward-1",
            },
            probability=prob, confidence=0.5, judgment_backend="fake",
        )

    def make_outcome(self, snapshot_id, condition_id, actual_outcome, actual_price):
        return create_outcome(
            snapshot_id=snapshot_id, condition_id=condition_id,
            outcome_timestamp="2026-09-25T15:00:00+00:00",
            actual_outcome=actual_outcome, actual_price=actual_price,
            resolution_source="test",
        )

    def test_perfect_calibration_builds_one(self):
        with tempfile.TemporaryDirectory() as directory:
            snap_path = Path(directory) / "snapshots.jsonl"
            outcome_path = Path(directory) / "outcomes.jsonl"
            prereg_path = Path(directory) / "prereg.json"
            
            # 100 predictions with prob=0.96, all correct (ECE = |0.96-1.0| = 0.04 < 0.05)
            for i in range(100):
                condition_id = f"0x{i}"
                snap = self.make_snapshot(condition_id, "Q", 0.96)
                append_snapshot(snap_path, snap)
                outcome = self.make_outcome(snap["snapshot_id"], condition_id, 1, 1.0)
                append_outcome(outcome_path, outcome)
            
            prereg_path.write_text('{"features_used":["macro_context","smart_money_net_flow"],"registered_at":"2026-09-24T00:00:00Z"}')
            
            report = run_evaluation(snap_path, outcome_path, prereg_path)
            self.assertEqual(report["verdict"], "BUILD-1")
            self.assertTrue(report["leakage_passed"])
            self.assertEqual(report["n"], 100)

    def test_poor_calibration_kills(self):
        with tempfile.TemporaryDirectory() as directory:
            snap_path = Path(directory) / "snapshots.jsonl"
            outcome_path = Path(directory) / "outcomes.jsonl"
            prereg_path = Path(directory) / "prereg.json"
            
            # 100 predictions all wrong (predict 0.96 but outcome 0)
            for i in range(100):
                condition_id = f"0x{i}"
                snap = self.make_snapshot(condition_id, "Q", 0.96)
                append_snapshot(snap_path, snap)
                outcome = self.make_outcome(snap["snapshot_id"], condition_id, 0, 0.0)
                append_outcome(outcome_path, outcome)
            
            prereg_path.write_text('{"features_used":["macro_context","smart_money_net_flow"],"registered_at":"2026-09-24T00:00:00Z"}')
            
            report = run_evaluation(snap_path, outcome_path, prereg_path)
            self.assertEqual(report["verdict"], "KILL")

    def test_insufficient_samples_inconclusive(self):
        with tempfile.TemporaryDirectory() as directory:
            snap_path = Path(directory) / "snapshots.jsonl"
            outcome_path = Path(directory) / "outcomes.jsonl"
            prereg_path = Path(directory) / "prereg.json"
            
            for i in range(50):
                condition_id = f"0x{i}"
                snap = self.make_snapshot(condition_id, "Q", 0.96)
                append_snapshot(snap_path, snap)
                outcome = self.make_outcome(snap["snapshot_id"], condition_id, 1, 1.0)
                append_outcome(outcome_path, outcome)
            
            prereg_path.write_text('{"features_used":["macro_context","smart_money_net_flow"],"registered_at":"2026-09-24T00:00:00Z"}')
            
            report = run_evaluation(snap_path, outcome_path, prereg_path)
            self.assertEqual(report["verdict"], "INCONCLUSIVE")


if __name__ == "__main__":
    unittest.main()
