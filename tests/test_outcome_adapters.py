import asyncio
import tempfile
import unittest
from pathlib import Path

from oracle.calibration.forward_snapshot import append_snapshot, create_snapshot
from oracle.calibration.outcome_adapters import collect_outcome_for_snapshot, collect_outcomes_for_snapshots
from oracle.calibration.outcomes import read_outcomes


class FakeSource:
    def __init__(self, markets):
        self.markets = markets
        self.calls = []

    async def get_market_details(self, condition_id):
        self.calls.append(condition_id)
        return self.markets.get(condition_id)


class OutcomeAdapterTests(unittest.TestCase):
    def make_snapshot(self):
        return create_snapshot(
            evaluation_id="eval", prediction_timestamp="2026-09-24T15:00:00+00:00",
            condition_id="0xresolved", question="Q", category="test", features={},
            probability=0.6, confidence=0.5, judgment_backend="fake",
        )

    def test_unresolved_market_does_not_write_outcome(self):
        with tempfile.TemporaryDirectory() as directory:
            source = FakeSource({"0xopen": {"closed": False}})
            snapshot = self.make_snapshot()
            snapshot["condition_id"] = "0xopen"
            result = asyncio.run(collect_outcome_for_snapshot(
                snapshot, market_source=source, outcome_path=Path(directory) / "outcomes.jsonl",
            ))
            self.assertIsNone(result)
            self.assertEqual(read_outcomes(Path(directory) / "outcomes.jsonl"), [])

    def test_resolved_market_appends_separate_outcome(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot_path = Path(directory) / "predictions.jsonl"
            outcome_path = Path(directory) / "outcomes.jsonl"
            snapshot = self.make_snapshot()
            append_snapshot(snapshot_path, snapshot)
            source = FakeSource({
                "0xresolved": {
                    "closed": True,
                    "endDate": "2026-09-25T15:00:00Z",
                    "outcomePrices": "[1, 0]",
                }
            })
            outcomes = asyncio.run(collect_outcomes_for_snapshots(
                snapshot_path, market_source=source, outcome_path=outcome_path,
            ))
            self.assertEqual(len(outcomes), 1)
            self.assertEqual(outcomes[0]["actual_outcome"], 1)
            self.assertEqual(len(read_snapshots_for_test(snapshot_path)), 1)
            self.assertEqual(len(read_outcomes(outcome_path)), 1)

    def test_resolution_is_idempotent_on_rerun(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot_path = Path(directory) / "predictions.jsonl"
            outcome_path = Path(directory) / "outcomes.jsonl"
            snapshot = self.make_snapshot()
            append_snapshot(snapshot_path, snapshot)
            source = FakeSource({
                "0xresolved": {
                    "closed": True,
                    "endDate": "2026-09-25T15:00:00Z",
                    "outcomePrices": "[1, 0]",
                }
            })
            asyncio.run(collect_outcomes_for_snapshots(snapshot_path, market_source=source, outcome_path=outcome_path))
            asyncio.run(collect_outcomes_for_snapshots(snapshot_path, market_source=source, outcome_path=outcome_path))
            self.assertEqual(len(read_outcomes(outcome_path)), 1)


def read_snapshots_for_test(path):
    from oracle.calibration.forward_snapshot import read_snapshots
    return read_snapshots(path)


if __name__ == "__main__":
    unittest.main()
