import unittest
import tempfile
from pathlib import Path

from oracle.calibration.hypothesis_generator import HypothesisGenerator


class HypothesisGeneratorTests(unittest.TestCase):
    def test_feature_hypothesis_generation(self):
        gen = HypothesisGenerator()
        h = gen.generate_feature_hypothesis()
        self.assertIn(h.name, [f.name for f in __import__('oracle.calibration.hypothesis_generator', fromlist=['FEATURE_HYPOTHESES']).FEATURE_HYPOTHESES])
    
    def test_lag_hypothesis_generation(self):
        gen = HypothesisGenerator()
        h = gen.generate_lag_hypothesis()
        self.assertIn(h.chain_name, ["crude_to_gasoline_retail", "gasoline_to_cpi_energy", "energy_to_fed_policy"])
    
    def test_transform_hypothesis_generation(self):
        gen = HypothesisGenerator()
        h = gen.generate_transform_hypothesis()
        self.assertIn(h.name, ["log_return", "zscore_normalize", "regime_indicator"])
    
    def test_signal_combination_generation(self):
        gen = HypothesisGenerator()
        h = gen.generate_signal_combination_hypothesis()
        self.assertIn(h.name, ["macro_heavy", "judgment_heavy", "balanced", "market_heavy"])
    
    def test_full_experiment_generation(self):
        gen = HypothesisGenerator()
        exp = gen.generate_full_experiment("test_exp_001")
        self.assertEqual(exp["experiment_id"], "test_exp_001")
        self.assertIn("feature_hypothesis", exp)
        self.assertIn("lag_hypothesis", exp)
        self.assertIn("transform_hypothesis", exp)
        self.assertIn("signal_combination", exp)
        self.assertEqual(exp["status"], "pending")
    
    def test_experiment_persistence(self):
        with tempfile.TemporaryDirectory() as directory:
            gen = HypothesisGenerator(Path(directory) / "catalog.json")
            exp = gen.generate_full_experiment("test_exp_001")
            exp_path = gen.save_experiment(exp)
            self.assertTrue(exp_path.exists())
            
            import json
            loaded = json.loads(exp_path.read_text())
            self.assertEqual(loaded["experiment_id"], "test_exp_001")


if __name__ == "__main__":
    unittest.main()
