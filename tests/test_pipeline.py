import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from algorithms.deep_research import main
from factory.config import ResearchConfig
from factory.pipeline import run_research

FIXTURE = Path(__file__).resolve().parents[1] / "examples/offline_fixture.json"


class PipelineTests(unittest.TestCase):
    def test_two_round_strict(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = ResearchConfig(question="Synthetic example?", out=tmp, provider="mock",
                                 llm="mock", fixture=str(FIXTURE), strict=True,
                                 max_rounds=2, max_queries=4)
            run = run_research(cfg)
            self.assertEqual(run["status"], "completed", run["errors"])
            self.assertEqual(run["rounds"], 2)
            self.assertEqual(run["queries_executed"], 2)
            a = json.loads((Path(tmp) / "audit.json").read_text())
            self.assertTrue(a["valid"], a)
            ledger = json.loads((Path(tmp) / "ledger.json").read_text())
            self.assertEqual(len(ledger["claims"]), 2)
            report = (Path(tmp) / "report.md").read_text()
            self.assertIn("[S001]", report)
            self.assertIn("[S002]", report)

    def test_missing_keys_fails_and_preserves_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = ResearchConfig(question="Any question", out=tmp)
            with patch.dict(os.environ, {}, clear=True):
                run = run_research(cfg)
            self.assertEqual(run["status"], "failed")
            self.assertEqual(json.loads((Path(tmp) / "sources.json").read_text()), [])
            self.assertTrue((Path(tmp) / "deviations.json").exists())
            self.assertTrue((Path(tmp) / "run.json").exists())

    def test_cli_entrypoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            status = main(["--question", "Synthetic", "--out", tmp,
                           "--provider", "mock", "--llm", "mock",
                           "--fixture", str(FIXTURE), "--max-rounds", "2",
                           "--strict"])
            self.assertEqual(status, 0)
            self.assertTrue((Path(tmp) / "report.md").exists())


    def test_old_report_does_not_survive_failed_rerun(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            (output / "report.md").write_text("STALE PREVIOUS REPORT", encoding="utf-8")
            cfg = ResearchConfig(question="Missing live credentials", out=tmp)
            with patch.dict(os.environ, {}, clear=True):
                result = run_research(cfg)
            self.assertEqual(result["status"], "failed")
            self.assertNotIn("STALE PREVIOUS REPORT", (output / "report.md").read_text())

    def test_no_full_text_fails_strict(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = json.loads(FIXTURE.read_text())
            for group in data["search_results"].values():
                for item in group:
                    item["content"] = ""
            p = Path(tmp) / "fixture.json"
            p.write_text(json.dumps(data), encoding="utf-8")
            cfg = ResearchConfig(question="Synthetic", out=str(Path(tmp)/"run"),
                                 llm="mock", provider="mock", fixture=str(p),
                                 strict=True, max_rounds=2)
            run = run_research(cfg)
            self.assertEqual(run["status"], "incomplete")
            self.assertFalse(json.loads((Path(tmp)/"run"/"audit.json").read_text())["valid"])

