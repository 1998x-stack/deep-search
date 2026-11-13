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

    def test_duplicate_claim(self):
        src = [{"id": "S001", "url": "https://example.org", "content": "X"}]
        data = {"claims": [{"text": "Claim", "status": "unverified", "evidence": []}]}
        first, _ = normalize_claims(data, src)
        second, _ = normalize_claims(data, src, first)
        self.assertEqual(len(second), 1)

