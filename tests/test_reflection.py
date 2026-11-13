import unittest
from factory.reflection import Metrics, decide, novel_queries, observe


class ReflectionTests(unittest.TestCase):
    def metrics(self, *, progressed=True, queries=3, rounds=2, slots=5):
        return Metrics(
            sources_total=5, new_sources=int(progressed),
            full_text_sources=2, new_full_text=0,
            anchored_support_claims=1, new_anchored_support_claims=0,
            unverified_claims=2, disputed_claims=1, remaining_queries=queries,
            remaining_rounds=rounds, remaining_source_slots=slots,
            progressed=progressed,
        )

    def test_novel_queries_reject_exact_and_fuzzy(self):
        got = novel_queries(
            ["original sources", "Original  sources!!!", "alternative explanation",
             "alternative explanation", "new primary document"],
            {"original sources"}, limit=2)
        self.assertEqual(got, ["alternative explanation", "new primary document"])

    def test_hard_budgets(self):
        proposal = {"stop": False, "next_queries": ["unique candidate"]}
        for kwargs, expected in [
            ({"queries": 0}, "query_budget_exhausted"),
            ({"rounds": 0}, "round_budget_exhausted"),
            ({"slots": 0}, "source_budget_exhausted"),
        ]:
            with self.subTest(expected=expected):
                result = decide(self.metrics(**kwargs), proposal,
                                history=set(), previous_stalled_rounds=0)
                self.assertEqual(result.reason, expected)
                self.assertEqual(result.action, "stop")

    def test_critic_stop_is_a_proposal_with_reason(self):
        d = decide(self.metrics(), {"stop": True, "next_queries": ["new"]},
                   history=set(), previous_stalled_rounds=0)
        self.assertEqual(d.reason, "critic_requested_stop")

    def test_stagnation_overrides_model_continue(self):
        d = decide(self.metrics(progressed=False), {"stop": False,
                   "next_queries": ["new original evidence"]},
                   history=set(), previous_stalled_rounds=1, patience=2)
        self.assertEqual(d.reason, "stagnated")

    def test_no_novel_queries(self):
        d = decide(self.metrics(), {"stop": False, "next_queries": ["same query"]},
                   history={"SAME QUERY"}, previous_stalled_rounds=0)
        self.assertEqual(d.reason, "no_novel_queries")

    def test_valid_next_queries_bounded(self):
        d = decide(self.metrics(queries=1), {"stop": False,
                   "next_queries": ["alpha counterevidence", "beta original data"]},
                   history=set(), previous_stalled_rounds=0)
        self.assertEqual(d.action, "continue")
        self.assertEqual(len(d.next_queries), 1)

    def test_observe_progress_is_measured_not_model_reported(self):
        src = [{"id": "S001", "content": "Full text"}, {"id": "S002", "content": ""}]
        claims = [{"status": "supported", "evidence": [{
            "anchored": True, "polarity": "supports"}]}]
        m = observe(src, claims, previous_source_count=1, previous_full_text_count=0,
                    previous_anchored_count=0, remaining_queries=1, remaining_rounds=2,
                    max_sources=4)
        self.assertTrue(m.progressed)
        self.assertEqual(m.new_sources, 1)
        self.assertEqual(m.new_anchored_support_claims, 1)

    def test_invalid_critic_contract_rejected(self):
        with self.assertRaises(ValueError):
            decide(self.metrics(), {"stop": "false", "next_queries": []},
                   history=set(), previous_stalled_rounds=0)

