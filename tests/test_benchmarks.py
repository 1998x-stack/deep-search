import tempfile
import unittest
from pathlib import Path

from benchmarks.offline_eval import run_suite

ROOT = Path(__file__).resolve().parents[1]


class EvaluationTests(unittest.TestCase):
    def test_structural_suite_matches_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_suite(ROOT / "evals/scenarios.json", Path(tmp))
            self.assertEqual(result["total"], 2)
            self.assertEqual(result["passed"], 2)
            self.assertFalse(result["factual_accuracy_tested"])

