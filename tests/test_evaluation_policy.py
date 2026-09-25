import unittest

from oracle.calibration.evaluation_policy import determine_verdict


GATES = {
    "ece_threshold": 0.05,
    "brier_threshold": 0.20,
    "hit_rate_threshold": 0.55,
    "min_samples": 100,
}


class EvaluationPolicyTests(unittest.TestCase):
    def test_retrospective_never_qualifies_even_with_excellent_metrics(self):
        verdict = determine_verdict(
            {"n": 1000, "ece": 0.001, "brier_score": 0.01, "accuracy": 0.99},
            "retrospective",
            GATES,
        )
        self.assertEqual(verdict, "RETROSPECTIVE ONLY")

    def test_forward_small_sample_is_inconclusive(self):
        verdict = determine_verdict(
            {"n": 99, "ece": 0.001, "brier_score": 0.01, "accuracy": 0.99},
            "forward",
            GATES,
        )
        self.assertEqual(verdict, "INCONCLUSIVE")

    def test_forward_passing_gates_builds_one(self):
        verdict = determine_verdict(
            {"n": 100, "ece": 0.049, "brier_score": 0.19, "accuracy": 0.56},
            "forward",
            GATES,
        )
        self.assertEqual(verdict, "BUILD-1")

    def test_forward_failed_gates_kills(self):
        verdict = determine_verdict(
            {"n": 100, "ece": 0.11, "brier_score": 0.30, "accuracy": 0.40},
            "forward",
            GATES,
        )
        self.assertEqual(verdict, "KILL")

    def test_invalid_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            determine_verdict({"n": 100}, "paper", GATES)


if __name__ == "__main__":
    unittest.main()
