"""Operator-imported discovery list provider: provenance, ranking, manifest wiring."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from factory.config import ResearchConfig
from factory.pipeline import run_research
from factory.replay_search import (PROVIDER_NAME, load_discovery_list, query_terms)
from factory.search import SearchError, create_search

LIST = {
    "schema_version": "1.0",
    "provenance": {
        "collected_by": "operator@example.test",
        "collected_at": "2026-11-13T03:00:00Z",
        "collection_tool": "external-web-search-api",
        "notes": "automated engine responses were degraded on this host",
    },
    "pool": [
        {"url": "https://example.org/upstream", "title": "减速器 与 伺服电机 供应商",
         "snippet": "上游核心零部件 减速器 伺服电机", "published_at": "2026-08-01",
         "tags": "上游 部件"},
        {"url": "https://example.org/midstream", "title": "人形机器人 本体 量产",
         "snippet": "中游 本体 厂商 量产 出货", "tags": "中游"},
        {"url": "https://example.org/downstream", "title": "Downstream deployment",
         "snippet": "industrial application scenarios", "tags": "downstream"},
    ],
}


class ReplayListTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.path = self.dir / "discovery.json"
        self.path.write_text(json.dumps(LIST, ensure_ascii=False), encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def payload(self, **overrides) -> Path:
        data = json.loads(json.dumps(LIST))
        data.update(overrides)
        path = self.dir / "variant.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return path

    def test_valid_list_loads(self):
        payload = load_discovery_list(str(self.path))
        self.assertEqual(payload["provenance"]["collection_tool"], "external-web-search-api")

    def test_synthetic_list_is_refused(self):
        with self.assertRaises(SearchError):
            load_discovery_list(str(self.payload(synthetic=True)))

    def test_missing_provenance_is_refused(self):
        data = json.loads(json.dumps(LIST))
        del data["provenance"]
        path = self.dir / "no-provenance.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(SearchError):
            load_discovery_list(str(path))
        data["provenance"] = {"collected_by": "someone"}
        path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(SearchError):
            load_discovery_list(str(path))

    def test_schema_and_file_errors(self):
        with self.assertRaises(SearchError):
            load_discovery_list(str(self.payload(schema_version="2.0")))
        with self.assertRaises(SearchError):
            load_discovery_list(str(self.dir / "absent.json"))
        broken = self.dir / "broken.json"
        broken.write_text("{oops", encoding="utf-8")
        with self.assertRaises(SearchError):
            load_discovery_list(str(broken))

    def test_invalid_entry_url_is_refused(self):
        with self.assertRaises(SearchError):
            load_discovery_list(str(self.payload(pool=[{"url": "javascript:alert(1)"}])))
        with self.assertRaises(SearchError):
            load_discovery_list(str(self.payload(pool=[])))

    def test_query_terms_support_cjk_and_latin(self):
        self.assertIn("减速器", query_terms("上游 减速器 供应商"))
        self.assertIn("humanoid", query_terms("humanoid supply chain"))

    def test_search_is_ranked_deterministic_and_deduplicated(self):
        cfg = ResearchConfig(question="chain", provider="replay",
                             search_fixture=str(self.path))
        search = create_search(cfg, search_fixture=str(self.path))
        first = search.search("减速器 伺服电机 上游", num=2)
        self.assertTrue(first)
        self.assertEqual(first[0]["url"], "https://example.org/upstream")
        self.assertEqual(first[0]["provider"], PROVIDER_NAME)
        self.assertEqual(first[0]["published_at"], "2026-08-01")
        self.assertTrue(all(not item["content"] for item in first))
        again = search.search("减速器 伺服电机 上游", num=2)
        self.assertNotIn(first[0]["url"], [item["url"] for item in again])
        self.assertEqual(search.search("减速器", num=5),
                         search.search("减速器", num=5))

    def test_zero_overlap_returns_empty_and_preserves_pool(self):
        cfg = ResearchConfig(question="chain", provider="replay", search_fixture=str(self.path))
        search = create_search(cfg)
        self.assertEqual(search.search("quantum astrophysics neutrino superconductor", num=3), [])
        self.assertEqual(search.remaining, 3)
        self.assertFalse(search.exhausted)
        self.assertFalse(search.open_world_discovery)
        self.assertTrue(search.fixed_corpus)

    def test_results_by_query_only_is_not_silently_ignored(self):
        rows = {
            "schema_version": "1.0",
            "provenance": LIST["provenance"],
            "results_by_query": {
                "industrial application scenarios": [{
                    "url": "https://example.org/downstream",
                    "title": "industrial application scenarios",
                    "snippet": "Manufacturing evidence"
                }]
            }
        }
        path = self.payload(**rows)
        cfg = ResearchConfig(question="chain", provider="replay", search_fixture=str(path))
        search = create_search(cfg)
        got = search.search("industrial application scenarios", num=2)
        self.assertEqual([x["url"] for x in got], ["https://example.org/downstream"])
        self.assertTrue(search.exhausted)

    def test_query_agnostic_list_is_searchable(self):
        path = self.payload(pool=[], queries=[
            {"url": "https://example.org/reference",
             "title": "quantum researcher primary text", "snippet": "primary"}
        ])
        cfg = ResearchConfig(question="chain", provider="replay", search_fixture=str(path))
        search = create_search(cfg)
        self.assertEqual(len(search.search("quantum researcher", num=2)), 1)

    def test_search_rejects_bad_arguments(self):
        cfg = ResearchConfig(question="chain", provider="replay", search_fixture=str(self.path))
        search = create_search(cfg, search_fixture=str(self.path))
        with self.assertRaises(ValueError):
            search.search("  ")
        with self.assertRaises(ValueError):
            search.search("x", num=101)

    def test_config_requires_search_fixture_for_replay(self):
        with self.assertRaises(ValueError):
            ResearchConfig(question="chain", provider="replay")

    def test_manifest_records_discovery_mode_and_provenance(self):
        with tempfile.TemporaryDirectory() as out:
            cfg = ResearchConfig(
                question="A fictional chain", out=out, provider="replay", llm="mock",
                fixture="examples/offline_fixture.json", search_fixture=str(self.path),
                max_rounds=1, max_queries=1, results_per_query=3, fetch_pages=True)
            fetcher = lambda url, timeout=10: {"url": url, "content": "synthetic text " * 20}
            result = run_research(cfg, fetcher=fetcher)
            saved = json.loads((Path(out) / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(result["discovery_mode"], "operator_imported")
        self.assertEqual(result["discovery_scope"], "fixed_corpus")
        self.assertFalse(result.get("open_world_discovery", False))
        self.assertEqual(saved["discovery_provenance"]["collection_tool"],
                         "external-web-search-api")
        self.assertIn("discovery.json", saved["artifacts"])
        self.assertIn("logging", saved)
        self.assertGreaterEqual(saved["queries_executed"], 1)


if __name__ == "__main__":
    unittest.main()
