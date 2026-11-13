import unittest
from factory.evidence import add_sources, audit, canonical_url, normalize_claims


class EvidenceTests(unittest.TestCase):
    def test_url_dedup(self):
        self.assertEqual(canonical_url("https://EXAMPLE.org/a/?utm_medium=x"), "https://example.org/a")
        docs = []
        n = add_sources(docs, [
            {"url": "https://example.org/a/?utm_medium=x", "content": "alpha"},
            {"url": "https://example.org/a", "content": "alpha"}], max_sources=4)
        self.assertEqual(n, 1)

    def test_snippet_is_not_full_text(self):
        src = [{"id": "S001", "url": "https://example.org/1",
                "title": "one", "snippet": "claim", "content": ""}]
        data = {"claims": [{
            "text": "The claim is true", "status": "supported",
            "evidence": [{"source_id": "S001", "quote": "claim", "polarity": "supports"}]}]}
        claims, deviations = normalize_claims(data, src)
        self.assertEqual(claims[0]["status"], "unverified")
        self.assertTrue(deviations)

    def test_anchored_audit_and_unknown_citation(self):
        src = [{"id": "S001", "url": "https://example.org/a", "title": "one",
                "snippet": "", "content": "A fictional train arrived in 2010.",
                "content_sha256": None}]
        data = {"claims": [{
            "text": "A train arrived", "status": "supported",
            "evidence": [{"source_id": "S001", "quote": "fictional train arrived in 2010",
                          "polarity": "supports"}]}]}
        claims, issues = normalize_claims(data, src)
        self.assertFalse(issues)
        self.assertTrue(audit({"sources": src, "claims": claims}, "Evidence [S001].")["valid"])
        self.assertFalse(audit({"sources": src, "claims": claims}, "Evidence [S999].")["valid"])


    def test_status_specific_evidence_gates(self):
        src = [{"id": "S001", "url": "https://example.org/a",
                "content": "Only an ambiguous sample is described."}]
        for status in ("supported", "partially_supported", "disputed", "refuted"):
            p = {"claims": [{"text": "Claim" + status, "status": status,
                  "evidence": [{"source_id": "S001", "quote": "ambiguous sample",
                                "polarity": "supports"}]}]}
            claims, _ = normalize_claims(p, src)
            expected = "supported" if status in {"supported", "partially_supported"} else "unverified"
            if status == "partially_supported":
                expected = "partially_supported"
            self.assertEqual(claims[0]["status"], expected)

    def test_exact_long_content_dedup_and_alias(self):
        src = []
        long_text = "A repeated original research press release. " * 9
        add_sources(src, [
            {"url": "https://example.org/one", "content": long_text},
            {"url": "https://other.example/one", "content": long_text},
        ], max_sources=10)
        self.assertEqual(len(src), 1)
        self.assertEqual(src[0]["aliases"][0]["reason"], "exact_content")

    def test_duplicate_claim(self):
        src = [{"id": "S001", "url": "https://example.org", "content": "X"}]
        data = {"claims": [{"text": "Claim", "status": "unverified", "evidence": []}]}
        first, _ = normalize_claims(data, src)
        second, _ = normalize_claims(data, src, first)
        self.assertEqual(len(second), 1)

