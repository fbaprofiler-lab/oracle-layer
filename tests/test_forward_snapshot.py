import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from oracle.calibration.forward_collector import collect_market_batch
from oracle.calibration.forward_snapshot import append_snapshot, create_snapshot, read_snapshots


class ForwardSnapshotTests(unittest.TestCase):
    def make_record(self):
        return create_snapshot(
            evaluation_id="eval_forward_1",
            prediction_timestamp="2026-09-24T15:00:00+00:00",
            condition_id="0xmarket",
            question="Will the test pass?",
            category="test",
            features={"latest_market_price": 0.5, "macro_context": {}},
            probability=0.6,
            confidence=0.55,
            judgment_backend="fake-laya",
        )

    def test_snapshot_is_append_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "predictions.jsonl"
            record = self.make_record()
            append_snapshot(path, record)
            with self.assertRaises(ValueError):
                append_snapshot(path, record)
            self.assertEqual(len(read_snapshots(path)), 1)

    def test_invalid_probability_rejected(self):
        with self.assertRaises(ValueError):
            create_snapshot(
                evaluation_id="eval", prediction_timestamp="2026-09-24T15:00:00+00:00",
                condition_id="0x", question="q", category="test", features={},
                probability=1.2, confidence=0.5, judgment_backend="fake",
            )


class ForwardCollectorTests(unittest.TestCase):
    def test_batch_collects_without_outcome_access(self):
        async def features(market):
            return {"question": market["question"]}

        async def judgment(question, feature_snapshot):
            return 0.61, 0.7, "fake-laya"

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "predictions.jsonl"
            # A market with no resolution date is filtered out by
            # collect_market_batch (it cannot be shown to resolve inside the
            # window), so the fixture needs a near-term end_date to exercise
            # the collect-and-never-touch-outcome path at all.
            resolves_at = datetime.now(timezone.utc) + timedelta(days=7)
            records = asyncio.run(collect_market_batch(
                [{
                    "conditionId": "0x1",
                    "question": "Q1",
                    "category": "test",
                    "endDate": resolves_at.isoformat().replace("+00:00", "Z"),
                }],
                evaluation_id="eval_forward_1", feature_collector=features,
                judgment=judgment, snapshot_path=path,
            ))
            self.assertEqual(len(records), 1)
            self.assertNotIn("actual_outcome", records[0])
            self.assertEqual(len(read_snapshots(path)), 1)


if __name__ == "__main__":
    unittest.main()
