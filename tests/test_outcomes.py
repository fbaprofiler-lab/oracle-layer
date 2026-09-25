import unittest
from pathlib import Path
import tempfile

from oracle.calibration.outcomes import (
    append_outcome,
    create_outcome,
    join_outcomes,
    read_outcomes,
)
from oracle.calibration.forward_snapshot import append_snapshot, create_snapshot


class OutcomeStoreTests(unittest.TestCase):
    def test_outcome_is_separate_append_only_and_joinable(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshots = Path(directory) / "predictions.jsonl"
            outcomes = Path(directory) / "outcomes.jsonl"
            snapshot = create_snapshot(
                evaluation_id="eval", prediction_timestamp="2026-09-24T15:00:00+00:00",
                condition_id="0x1", question="Q", category="test", features={},
                probability=0.6, confidence=0.5, judgment_backend="fake",
            )
            append_snapshot(snapshots, snapshot)
            outcome = create_outcome(
                snapshot_id=snapshot["snapshot_id"], condition_id="0x1",
                outcome_timestamp="2026-09-25T15:00:00+00:00", actual_outcome=1,
                actual_price=1.0, resolution_source="gamma-api",
            )
            append_outcome(outcomes, outcome)
            with self.assertRaises(ValueError):
                append_outcome(outcomes, outcome)
            joined = join_outcomes(snapshots, outcomes)
            self.assertEqual(len(joined), 1)
            self.assertEqual(joined[0]["actual_outcome"], 1)
            self.assertEqual(len(read_outcomes(outcomes)), 1)

    def test_outcome_rejects_invalid_value(self):
        with self.assertRaises(ValueError):
            create_outcome(
                snapshot_id="s", condition_id="c", outcome_timestamp="2026-09-25T15:00:00+00:00",
                actual_outcome=2, actual_price=1.0, resolution_source="test",
            )


if __name__ == "__main__":
    unittest.main()
