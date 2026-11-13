import unittest
from factory.citation_audit import audit_claim_citations


def ledger():
    return {"sources": [
        {"id": "S001", "content": "Official notice: the date was 2020."},
        {"id": "S002", "content": "The alternative assertion was false."},
    ], "claims": [
        {"id": "C001", "text": "Date was 2020", "status": "supported",
         "evidence": [{"source_id": "S001", "quote": "the date was 2020",
                       "polarity": "supports", "anchored": True}]},
        {"id": "C002", "text": "Date was 2019", "status": "refuted",
         "evidence": [{"source_id": "S002", "quote": "assertion was false",
                       "polarity": "contradicts", "anchored": True}]},
    ]}


class ClaimCitationTests(unittest.TestCase):
    def test_valid_bound_claims_and_precise_positions(self):
        text = "# Findings\nThe date was 2020 [C001][S001].\nThe prior date was refuted [C002][S002].\n\n## Sources\n- [S001] bibliography"
        result = audit_claim_citations(ledger(), text)
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(len(result["bindings"]), 2)
        self.assertEqual(result["bindings"][0]["line"], 2)
        self.assertEqual(result["bindings"][1]["line"], 3)
        self.assertEqual(result["bindings"][0]["statement_line"],
                         "The date was 2020 [C001][S001].")
        self.assertFalse(result["semantic_entailment_verified"])

    def test_same_source_cited_for_wrong_claim_fails(self):
        value = audit_claim_citations(
            ledger(), "Date was 2020 [C001][S002]. Date was 2019 [C002][S001].")
        self.assertFalse(value["valid"])
        self.assertTrue(any("lacks status-appropriate" in e for e in value["errors"]))

    def test_standalone_sources_and_bibliography_do_not_count(self):
        value = audit_claim_citations(ledger(),
            "The original date was 2020 [S001].\n\n## Sources\n[C001][S001] [C002][S002]")
        self.assertFalse(value["valid"])
        self.assertEqual(len(value["orphaned_source_citations"]), 1)
        self.assertEqual(value["bindings"], [])

    def test_disputed_requires_both_polarities_cited(self):
        l = ledger()
        l["claims"] = [{"id": "C003", "text": "Conflicting versions",
                        "status": "disputed",
                        "evidence": [
                            {"source_id": "S001", "quote": "the date was 2020",
                             "polarity": "supports", "anchored": True},
                            {"source_id": "S002", "quote": "assertion was false",
                             "polarity": "contradicts", "anchored": True},
                        ]}]
        incomplete = audit_claim_citations(l, "Conflicting [C003][S001].")
        self.assertFalse(incomplete["valid"])
        self.assertTrue(any("contradicts-bound" in x for x in incomplete["errors"]))
        complete = audit_claim_citations(l, "Conflicting [C003][S001] [C003][S002].")
        self.assertTrue(complete["valid"], complete["errors"])

    def test_hallucinated_ids_are_rejected(self):
        item = audit_claim_citations(
            ledger(), "Something [C999][S001] and [C001][S999].")
        self.assertFalse(item["valid"])
        self.assertIn("unknown claim citation C999", item["errors"])
        self.assertIn("unknown source citation S999", item["errors"])


if __name__ == "__main__":
    unittest.main()
