import unittest
from factory.evidence import (
    add_sources, assess_research_readiness, audit, canonical_url, normalize_claims,
)


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


    def test_empty_anchor_is_not_valid_quote(self):
        src = [{"id": "S001", "content": "Some actual passage", "url": "https://example.org"}]
        ledger = {"sources": src, "claims": [{"id": "C001", "text": "claim",
                  "status": "supported", "evidence": [
                      {"source_id": "S001", "quote": "", "polarity": "supports", "anchored": True},
                  ]}]}
        self.assertFalse(audit(ledger, "Evidence [S001]")["valid"])
        self.assertFalse(assess_research_readiness(ledger, "Evidence [S001]")["ready"])

    def test_readiness_rejects_empty_ledger_and_bibliography_only(self):
        src = [{"id": "S001", "url": "https://example.org", "content": "Text about event"}]
        self.assertFalse(assess_research_readiness({"sources": src, "claims": []},
                         "Summary.\\n## Sources\\n[S001]")["ready"])
        claim = {"id": "C001", "text": "Event", "status": "supported",
                 "evidence": [{"source_id": "S001", "quote": "about event",
                               "polarity": "supports", "anchored": True}]}
        self.assertFalse(assess_research_readiness(
            {"sources": src, "claims": [claim]},
            "No actual citations.\\n## Sources\\n[S001]")["ready"])
        self.assertTrue(assess_research_readiness(
            {"sources": src, "claims": [claim]}, "Evidence [S001].")["ready"])

    def test_refuted_claim_can_be_ready_without_positive_support(self):
        src = [{"id": "S001", "url": "https://example.org", "content": "The date was wrong."}]
        ledger = {"sources": src, "claims": [{"id": "C001",
                  "text": "The date was correct", "status": "refuted",
                  "evidence": [{"source_id": "S001", "quote": "date was wrong",
                                "polarity": "contradicts", "anchored": True}]}]}
        check = assess_research_readiness(ledger, "This was refuted [S001].")
        self.assertTrue(check["ready"])
        self.assertEqual(check["anchored_claims"], 1)

    def test_duplicate_claim(self):
        src = [{"id": "S001", "url": "https://example.org", "content": "X"}]
        data = {"claims": [{"text": "Claim", "status": "unverified", "evidence": []}]}
        first, _ = normalize_claims(data, src)
        second, _ = normalize_claims(data, src, first)
        self.assertEqual(len(second), 1)

