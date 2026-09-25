import unittest
import tempfile
from pathlib import Path

from oracle.calibration.candidate_registry import CandidateRegistry


class CandidateRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.registry_path = Path(self.temp_dir.name) / "candidates.jsonl"
        self.registry = CandidateRegistry(self.registry_path)
    
    def tearDown(self):
        self.temp_dir.cleanup()
    
    def test_add_and_get(self):
        exp = {"experiment_id": "test_001", "status": "pending", "sandbox_score": 0.7}
        self.registry.add(exp)
        got = self.registry.get("test_001")
        self.assertEqual(got["experiment_id"], "test_001")
        self.assertEqual(got["status"], "pending")
    
    def test_update_status(self):
        exp = {"experiment_id": "test_001", "status": "pending"}
        self.registry.add(exp)
        ok = self.registry.update_status("test_001", "sandbox_complete", sandbox_score=0.8)
        self.assertTrue(ok)
        got = self.registry.get("test_001")
        self.assertEqual(got["status"], "sandbox_complete")
        self.assertEqual(got["sandbox_score"], 0.8)
    
    def test_query_status(self):
        for i in range(5):
            self.registry.add({
                "experiment_id": f"exp_{i}",
                "status": "sandbox_complete" if i < 3 else "pending",
                "sandbox_score": 0.7 + i * 0.05,
                "charter_verdict": "BUILD-1" if i % 2 == 0 else "KILL",
                "feature_hypothesis": {"expected_impact": "macro_transmission" if i % 2 == 0 else "smart_money"},
            })
        results = self.registry.query(status="sandbox_complete")
        self.assertEqual(len(results), 3)
    
    def test_query_min_score(self):
        # Scores: 0.75, 0.8, 0.875, 0.9, 0.95 (exact binary floats)
        # min=0.85 should give 3: 0.875, 0.9, 0.95
        scores = [0.75, 0.8, 0.875, 0.9, 0.95]
        for i, score in enumerate(scores):
            self.registry.add({
                "experiment_id": f"exp_{i}",
                "status": "sandbox_complete",
                "sandbox_score": score,
            })
        results = self.registry.query(min_sandbox_score=0.85)
        self.assertEqual(len(results), 3)
    
    def test_query_verdict(self):
        for i in range(5):
            self.registry.add({
                "experiment_id": f"exp_{i}",
                "status": "sandbox_complete",
                "charter_verdict": "BUILD-1" if i % 2 == 0 else "KILL",
            })
        results = self.registry.query(charter_verdict="BUILD-1")
        self.assertEqual(len(results), 3)
    
    def test_query_impact(self):
        for i in range(5):
            self.registry.add({
                "experiment_id": f"exp_{i}",
                "feature_hypothesis": {"expected_impact": "macro_transmission" if i % 2 == 0 else "smart_money"},
            })
        results = self.registry.query(impact_filter="macro_transmission")
        self.assertEqual(len(results), 3)
    
    def test_stats(self):
        self.registry.add({"experiment_id": "e1", "status": "pending", "charter_verdict": "BUILD-1", "feature_hypothesis": {"expected_impact": "macro_transmission"}})
        self.registry.add({"experiment_id": "e2", "status": "sandbox_complete", "charter_verdict": "KILL", "feature_hypothesis": {"expected_impact": "smart_money"}})
        stats = self.registry.stats()
        self.assertEqual(stats["total"], 2)
        self.assertEqual(stats["by_status"]["pending"], 1)
        self.assertEqual(stats["by_status"]["sandbox_complete"], 1)
        self.assertEqual(stats["by_verdict"]["BUILD-1"], 1)
        self.assertEqual(stats["by_impact"]["macro_transmission"], 1)


if __name__ == "__main__":
    unittest.main()
