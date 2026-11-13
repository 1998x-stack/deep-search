import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from deep_search.cli import main
from deep_search.network import ensure_public_url, extract_text
from deep_search.research import (
    audit_report, canonical_url, deduplicate, make_plan,
    render_report, validate_ledger,
)

SOURCE = {
    "id": "S001",
    "url": "https://example.org/article",
    "title": "Example article",
    "content": "The city opened a public library in 2020 after a public vote.",
}
CLAIM = {
    "id": "C001",
    "text": "The city opened a public library in 2020.",
    "status": "supported",
    "evidence": [{
        "source_id": "S001",
        "quote": "The city opened a public library in 2020",
        "polarity": "supports",
    }],
}


class ResearchTests(unittest.TestCase):
    def test_url_canonicalization(self):
        self.assertEqual(
            canonical_url("HTTPS://Example.org/article/?utm_source=mail&b=2&a=1#top"),
            "https://example.org/article?a=1&b=2",
        )

    def test_url_rejects_credentials_and_file_protocol(self):
        for value in ["file:///etc/passwd", "https://me:pass@example.com/a", "abc"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                canonical_url(value)

    def test_plan_has_bounded_queries(self):
        p = make_plan("What happened?", 3)
        self.assertEqual(len(p["subquestions"]), 3)
        self.assertEqual(p["budget"]["max_queries"], 3)

    def test_plan_empty_rejected(self):
        with self.assertRaises(ValueError):
            make_plan("  ")

    def test_dedup_tracking_url(self):
        entries = [dict(SOURCE), dict(SOURCE, id="S002",
                  url="https://example.org/article?utm_source=feed")]
        unique, duplicates = deduplicate(entries)
        self.assertEqual(len(unique), 1)
        self.assertEqual(duplicates[0]["duplicate_of"], "S001")

    def test_dedup_identical_content_across_domains(self):
        entries = [dict(SOURCE, content="a" * 200),
                   dict(SOURCE, id="S002", url="https://example.com/else",
                        content="a" * 200)]
        unique, duplicates = deduplicate(entries)
        self.assertEqual(len(unique), 1)
        self.assertEqual(duplicates[0]["reason"], "exact_content")

    def test_supported_claim_quote_verified_structurally(self):
        ledger = {"sources": [SOURCE], "claims": [CLAIM]}
        self.assertTrue(validate_ledger(ledger)["valid"])

    def test_invented_quote_is_rejected(self):
        bad = {"sources": [SOURCE], "claims": [copy.deepcopy(CLAIM)]}
        bad["claims"][0]["evidence"][0]["quote"] = "not found in the article"
        self.assertFalse(validate_ledger(bad)["valid"])

    def test_supported_claim_without_source_content_is_rejected(self):
        ledger = {"sources": [dict(SOURCE, content="")], "claims": [CLAIM]}
        self.assertFalse(validate_ledger(ledger)["valid"])

    def test_unknown_source_is_rejected(self):
        bad = {"sources": [], "claims": [CLAIM]}
        self.assertFalse(validate_ledger(bad)["valid"])

    def test_tampered_content_hash_is_rejected(self):
        source = dict(SOURCE, content_sha256="0" * 64)
        result = validate_ledger({"sources": [source], "claims": [CLAIM]})
        self.assertFalse(result["valid"])
        self.assertTrue(any("checksum" in error for error in result["errors"]))

    def test_fetch_is_explicit_opt_in(self):
        with tempfile.TemporaryDirectory() as folder:
            inp = Path(folder) / "input.json"
            out = Path(folder) / "output.json"
            inp.write_text(json.dumps({"sources": [SOURCE]}))
            self.assertEqual(main(["fetch", "--input", str(inp), "--output", str(out)]), 2)
            self.assertFalse(out.exists())

    def test_report_and_audit(self):
        p = make_plan("Did the library open?")
        ledger = {"sources": [SOURCE], "claims": [CLAIM]}
        report = render_report(p, ledger)
        self.assertTrue(audit_report(report, ledger)["valid"])
        self.assertFalse(audit_report(report.replace("[S001]", "[S999]"), ledger)["valid"])

    def test_html_extraction_ignores_scripts(self):
        html = "<html><body><script>bad()</script><p>Hello &amp; world</p></body></html>"
        self.assertEqual(extract_text(html, "text/html"), "Hello & world")

    def test_ssrf_localhost_is_rejected(self):
        with self.assertRaises(ValueError):
            ensure_public_url("http://127.0.0.1/secret")

    def test_ssrf_private_resolved_address(self):
        with patch("deep_search.network.socket.getaddrinfo",
                   return_value=[(2, 1, 6, "", ("10.0.0.4", 443))]):
            with self.assertRaises(ValueError):
                ensure_public_url("https://example.org/")

    def test_cli_offline_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            p, e, r, a = [root / n for n in ("plan.json", "ledger.json", "report.md", "audit.json")]
            self.assertEqual(main(["plan", "--question", "Library history", "--output", str(p)]), 0)
            e.write_text(json.dumps({"sources": [SOURCE], "claims": [CLAIM]}))
            self.assertEqual(main(["validate", "--input", str(e)]), 0)
            self.assertEqual(main(["report", "--plan", str(p), "--ledger", str(e),
                                   "--output", str(r)]), 0)
            self.assertEqual(main(["audit", "--report", str(r), "--ledger", str(e),
                                   "--output", str(a)]), 0)
            self.assertTrue(json.loads(a.read_text())["valid"])


if __name__ == "__main__":
    unittest.main()

