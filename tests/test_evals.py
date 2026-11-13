import json
import unittest
from pathlib import Path

from deep_search.research import validate_ledger


class CuratedEvalTests(unittest.TestCase):
    def test_structural_cases(self):
        path = Path(__file__).resolve().parents[1] / "evals" / "citation-validity.json"
        suite = json.loads(path.read_text(encoding="utf-8"))
        for case in suite["cases"]:
            with self.subTest(case=case["id"]):
                actual = validate_ledger(case["ledger"])["valid"]
                self.assertEqual(actual, case["expected_valid"])

    def test_manual_eval_suites_are_explicit(self):
        root = Path(__file__).resolve().parents[1] / "evals"
        for name in ("factual-accuracy.json", "contradiction-tests.json"):
            suite = json.loads((root / name).read_text(encoding="utf-8"))
            self.assertFalse(suite["automatic_scoring"])
            self.assertTrue(suite["cases"])

