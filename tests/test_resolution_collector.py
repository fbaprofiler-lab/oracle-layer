import asyncio
import tempfile
import unittest
from pathlib import Path

from oracle.calibration.forward_snapshot import append_snapshot, create_snapshot
from oracle.calibration.cohorts import create_cohort_manifest, write_manifest, read_manifest
from oracle.calibration.resolution_collector import collect_cohort_outcomes


class FakeSource:
    def __init__(self, markets):
        self.markets = markets
    async def get_market_details(self, condition_id):
        return self.markets.get(condition_id)


class ResolutionCollectorTests(unittest.TestCase):
    def make_snapshot(self, condition_id, question, category="test", evaluation_id="test_cohort"):
        return create_snapshot(
            evaluation_id=evaluation_id, prediction_timestamp="2026-09-24T15:00:00+00:00",
            condition_id=condition_id, question=question, category=category, features={},
            probability=0.6, confidence=0.5, judgment_backend="fake",
        )

    def test_resolved_market_creates_outcome(self):
        with tempfile.TemporaryDirectory() as directory:
            snap_path = Path(directory) / "snapshots.jsonl"
            outcome_path = Path(directory) / "outcomes.jsonl"
            manifest_path = Path(directory) / "cohort.json"
            
            markets = [{"conditionId": "0x1", "question": "Q", "category": "test"}]
            manifest = create_cohort_manifest(
                cohort_id="test_cohort", selection_criteria={}, markets=markets,
                features=[], gates={}, target_n=1,
            )
            write_manifest(manifest_path, manifest)
            
            snap = self.make_snapshot("0x1", "Q", evaluation_id="test_cohort")
            from oracle.calibration.forward_snapshot import append_snapshot
            append_snapshot(snap_path, snap)
            
            source = FakeSource({
                "0x1": {
                    "closed": True,
                    "endDate": "2026-09-25T15:00:00Z",
                    "outcomePrices": "[1, 0]",
                }
            })
            
            result = asyncio.run(collect_cohort_outcomes(
                manifest_path, snap_path, outcome_path, source
            ))
            self.assertEqual(result["outcomes_collected"], 1)
            self.assertTrue(outcome_path.exists())

    def test_unresolved_market_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            snap_path = Path(directory) / "snapshots.jsonl"
            outcome_path = Path(directory) / "outcomes.jsonl"
            manifest_path = Path(directory) / "cohort.json"
            
            markets = [{"conditionId": "0x1", "question": "Q", "category": "test"}]
            manifest = create_cohort_manifest(
                cohort_id="test_cohort", selection_criteria={}, markets=markets,
                features=[], gates={}, target_n=1,
            )
            write_manifest(manifest_path, manifest)
            
            snap = self.make_snapshot("0x1", "Q", evaluation_id="test_cohort")
            from oracle.calibration.forward_snapshot import append_snapshot
            append_snapshot(snap_path, snap)
            
            source = FakeSource({
                "0x1": {"active": True, "closed": False, "endDate": "2027-01-01T00:00:00Z"}
            })
            
            result = asyncio.run(collect_cohort_outcomes(
                manifest_path, snap_path, outcome_path, source
            ))
            self.assertEqual(result["outcomes_collected"], 0)
            self.assertFalse(outcome_path.exists())


if __name__ == "__main__":
    unittest.main()
