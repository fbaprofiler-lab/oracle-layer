import subprocess
import sys
import unittest
from pathlib import Path


class ForwardDryRunTests(unittest.TestCase):
    def test_default_dry_run_has_no_external_calls_or_write(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, "scripts/forward_dry_run.py"],
            cwd=root, text=True, capture_output=True, check=True,
        )
        self.assertIn('"external_calls": false', result.stdout)
        self.assertIn('"snapshot_written": false', result.stdout)


if __name__ == "__main__":
    unittest.main()
