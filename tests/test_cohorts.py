import json
import tempfile
import unittest
from pathlib import Path

from oracle.calibration.cohorts import (
    create_cohort_manifest,
    write_manifest,
    read_manifest,
    update_observation_state,
    status,
)


class CohortTests(unittest.TestCase):
    def test_manifest_creation_and_status(self):
        markets = [
            {"conditionId": "0x1", "question": "Q1", "category": "test"},
            {"conditionId": "0x2", "question": "Q2", "category": "test"},
        ]
        manifest = create_cohort_manifest(
            cohort_id="test_cohort",
            selection_criteria={"active": True, "category": "test"},
            markets=markets,
            features=["question_text", "latest_market_price"],
            gates={"ece_threshold": 0.05},
            target_n=2,
        )
        self.assertEqual(manifest["cohort_id"], "test_cohort")
        self.assertEqual(len(manifest["markets"]), 2)
        st = status(manifest)
        self.assertEqual(st["selected"], 2)
        self.assertEqual(st["states"]["pending"], 2)

    def test_write_read_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cohort.json"
            markets = [{"conditionId": "0x1", "question": "Q", "category": "test"}]
            manifest = create_cohort_manifest(
                cohort_id="test", selection_criteria={}, markets=markets,
                features=[], gates={}, target_n=1,
            )
            write_manifest(path, manifest)
            with self.assertRaises(ValueError):
                write_manifest(path, manifest)
            read = read_manifest(path)
            self.assertEqual(read["cohort_id"], "test")

    def test_update_observation_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cohort.json"
            markets = [{"conditionId": "0x1", "question": "Q", "category": "test"}]
            manifest = create_cohort_manifest(
                cohort_id="test", selection_criteria={}, markets=markets,
                features=[], gates={}, target_n=1,
            )
            write_manifest(path, manifest)
            update_observation_state(path, "0x1", "resolved", "snap_123")
            read = read_manifest(path)
            self.assertEqual(read["markets"][0]["state"], "resolved")
            self.assertEqual(read["markets"][0]["snapshot_id"], "snap_123")

    def test_invalid_state_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cohort.json"
            markets = [{"conditionId": "0x1", "question": "Q", "category": "test"}]
            manifest = create_cohort_manifest(
                cohort_id="test", selection_criteria={}, markets=markets,
                features=[], gates={}, target_n=1,
            )
            write_manifest(path, manifest)
            with self.assertRaises(ValueError):
                update_observation_state(path, "0x1", "not_a_state")


if __name__ == "__main__":
    unittest.main()
