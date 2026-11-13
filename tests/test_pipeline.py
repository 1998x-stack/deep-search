import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from algorithms.deep_research import main
from factory.config import ResearchConfig
from factory.pipeline import _context, _model_payload, run_research

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
            self.assertEqual(run["stop_reason"], "critic_requested_stop")
            reflection = json.loads((Path(tmp) / "reflection.json").read_text())
            self.assertEqual(len(reflection), 2)
            self.assertEqual(reflection[0]["decision"]["action"], "continue")
            self.assertEqual(reflection[1]["decision"]["reason"], "critic_requested_stop")
            a = json.loads((Path(tmp) / "audit.json").read_text())
            self.assertTrue(a["valid"], a)
            ledger = json.loads((Path(tmp) / "ledger.json").read_text())
            self.assertEqual(len(ledger["claims"]), 2)
            report = (Path(tmp) / "report.md").read_text()
            self.assertIn("[S001]", report)
            self.assertIn("[S002]", report)


    def test_standard_mode_does_not_complete_with_snippets_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
            for collection in fixture["search_results"].values():
                for source in collection:
                    source["content"] = ""
            file = Path(tmp) / "fixture.json"
            file.write_text(json.dumps(fixture), encoding="utf-8")
            cfg = ResearchConfig(question="Synthetic excerpt-only claim",
                                 out=str(Path(tmp) / "run"), provider="mock",
                                 llm="mock", fixture=str(file), strict=False)
            run = run_research(cfg)
            self.assertEqual(run["status"], "incomplete", run["errors"])
            audit = json.loads((Path(cfg.out) / "audit.json").read_text())
            self.assertFalse(audit["readiness"]["ready"])
            self.assertTrue(audit["errors"])

    def test_standard_mode_does_not_complete_empty_claim_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
            fixture["responses"]["evidence"] = {"claims": []}
            file = Path(tmp) / "fixture.json"
            file.write_text(json.dumps(fixture), encoding="utf-8")
            cfg = ResearchConfig(question="Synthetic source",
                                 out=str(Path(tmp) / "run"), provider="mock",
                                 llm="mock", fixture=str(file), strict=False)
            run = run_research(cfg)
            self.assertEqual(run["status"], "incomplete")
            audit = json.loads((Path(cfg.out) / "audit.json").read_text())
            self.assertEqual(audit["readiness"]["anchored_claims"], 0)

    def test_total_source_context_budget_and_recency(self):
        sources = [
            {"id": f"S{i:03d}", "url": f"https://example.org/{i}",
             "title": "Research", "snippet": "description",
             "content": "data " * 3000}
            for i in range(1, 21)
        ]
        context = _context(sources, max_chars=6000, max_total_chars=4000)
        self.assertLessEqual(len(json.dumps(context, ensure_ascii=False)), 4000)
        self.assertEqual(context[0]["id"], "S020")
        self.assertTrue(context[0]["excerpt_truncated"])

    def test_model_payload_explicitly_rejects_oversize_context(self):
        with self.assertRaisesRegex(ValueError, "max_context_chars"):
            _model_payload({"body": "x" * 20000}, limit=5000, stage="evidence")
        self.assertEqual(_model_payload({"ok": True}, limit=5000, stage="test"),
                         '{"ok": true}')
        with self.assertRaisesRegex(ValueError, "max_context_chars"):
            _model_payload({"ok": True}, limit=25, stage="test",
                           instructions="prefix " * 10)

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


    def test_end_to_end_stagnation_decides_without_llm_permission(self):
        # Search results keep repeating without new full text or anchored evidence.
        # Critic requests unbounded continuation, but the deterministic policy stops.
        with tempfile.TemporaryDirectory() as tmp:
            data = json.loads(FIXTURE.read_text())
            data["responses"]["planner"]["queries"] = ["first fictional source"]
            data["search_results"] = {"*": [
                {"url": "https://example.org/fictional/notice",
                 "title": "Synthetic", "snippet": "Summary",
                 "content": "The fictional public library opened in 2020 after an imaginary municipal vote."}
            ]}
            data["responses"]["evidence"] = data["responses"]["evidence"][0]
            data["responses"]["critic"] = [
                {"stop": False, "next_queries": ["novel alternative one"], "gaps": [], "contradictions": [], "rationale": "find more"},
                {"stop": False, "next_queries": ["different original two"], "gaps": [], "contradictions": [], "rationale": "find more"},
                {"stop": False, "next_queries": ["additional original three"], "gaps": [], "contradictions": [], "rationale": "find more"}
            ]
            fixture = Path(tmp) / "synthetic.json"
            fixture.write_text(json.dumps(data), encoding="utf-8")
            cfg = ResearchConfig(
                question="Fictional test", provider="mock", llm="mock",
                fixture=str(fixture), out=str(Path(tmp) / "run"),
                max_rounds=4, reflection_patience=2, max_queries=8,
            )
            run = run_research(cfg)
            self.assertEqual(run["stop_reason"], "stagnated", run["errors"])
            self.assertEqual(run["rounds"], 3)
            reflections = json.loads((Path(tmp) / "run/reflection.json").read_text())
            self.assertEqual([r["observation"]["progressed"] for r in reflections],
                             [True, False, False])
            self.assertEqual(reflections[-1]["decision"]["reason"], "stagnated")

    def test_query_repetition_stops_before_second_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = json.loads(FIXTURE.read_text())
            data["responses"]["critic"][0]["stop"] = False
            data["responses"]["critic"][0]["next_queries"] = ["fictional library official notice"]
            fixture = Path(tmp) / "synthetic.json"
            fixture.write_text(json.dumps(data), encoding="utf-8")
            cfg = ResearchConfig(
                question="Fictional test", provider="mock", llm="mock",
                fixture=str(fixture), out=str(Path(tmp) / "run"),
                max_rounds=4, max_queries=8,
            )
            run = run_research(cfg)
            self.assertEqual(run["stop_reason"], "no_novel_queries", run["errors"])
            self.assertEqual(run["queries_executed"], 1)
            reflections = json.loads((Path(tmp) / "run/reflection.json").read_text())
            self.assertEqual(reflections[0]["decision"]["next_queries"], [])

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

