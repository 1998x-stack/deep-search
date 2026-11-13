import hashlib
import json
import unittest

from factory.coverage import (
    batches_for_evidence, constrain_evidence_to_batch, mark_processed,
    prepare_coverage, segments_for_source, summarize_coverage,
)


class CoverageTests(unittest.TestCase):
    def test_segments_cover_every_retrieved_character(self):
        content = "A" * 1000 + "Important evidence." + "B" * 1000
        source = {"id": "S001", "content": content}
        parts = segments_for_source(source, size=512, overlap=100)
        self.assertGreater(len(parts), 1)
        self.assertEqual(parts[0]["start"], 0)
        self.assertEqual(parts[-1]["end"], len(content))
        self.assertEqual({p["segment_id"] for p in parts},
                         {f"S001-P{i:04d}" for i in range(1, len(parts)+1)})
        for part in parts:
            self.assertEqual(part["content"], content[part["start"]:part["end"]])
            self.assertEqual(hashlib.sha256(part["content"].encode()).hexdigest(),
                             part["sha256"])
        state, pending = prepare_coverage([source], {}, segment_size=512)
        self.assertEqual(len(pending), len(parts))
        mark_processed(state, parts[:1])
        first = summarize_coverage(state)
        self.assertEqual(first["partially_processed_source_ids"], ["S001"])
        self.assertFalse(first["all_retrieved_text_processed"])
        mark_processed(state, parts[1:])
        summary = summarize_coverage(state)
        self.assertEqual(summary["model_processed_source_ids"], ["S001"])
        self.assertEqual(state["S001"]["processed_chars"], len(content))
        self.assertEqual(state["S001"]["retrieved_text_coverage"], 1.0)
        self.assertFalse(summary["semantic_comprehension_verified"])

    def test_changed_source_hash_invalidates_previous_coverage(self):
        first = {"id": "S001", "content": "X" * 1300}
        state, parts = prepare_coverage([first], {}, segment_size=512)
        mark_processed(state, parts)
        state2, pending = prepare_coverage([first], state, segment_size=512)
        self.assertFalse(pending)
        changed = {"id": "S001", "content": "Y" * 1300}
        state3, pending = prepare_coverage([changed], state2, segment_size=512)
        self.assertEqual(len(pending), len(parts))
        self.assertEqual(state3["S001"]["processed_segment_ids"], [])

    def test_batching_exactly_respects_system_plus_payload_budget(self):
        src = {"id": "S001", "content": "Z" * 9200}
        segments = segments_for_source(src, size=1200, overlap=100)
        batches = batches_for_evidence(segments, question="topic",
                                       round_number=1, max_input_chars=3500,
                                       instructions="system prompt")
        self.assertGreater(len(batches), 1)
        self.assertEqual([s["segment_id"] for batch in batches for s in batch],
                         [s["segment_id"] for s in segments])
        for batch in batches:
            user = json.dumps({"question": "topic", "round": 1,
                               "sources": batch}, ensure_ascii=False)
            self.assertLessEqual(len(user) + len("system prompt"), 3500)

    def test_model_cannot_cite_unseen_part_of_full_source(self):
        source = {"id": "S001", "content": "Alpha." + "x" * 1500 + "Omega."}
        batch = segments_for_source(source, size=512)[:1]
        raw = {"claims": [{"text": "Omega was shown", "status": "supported",
                           "evidence": [
                              {"source_id": "S001", "quote": "Omega.", "polarity": "supports"},
                              {"source_id": "S001", "quote": "Alpha.", "polarity": "supports"},
                           ]}]}
        restricted, rejected = constrain_evidence_to_batch(raw, batch)
        self.assertEqual(rejected, 1)
        self.assertEqual([e["quote"] for e in restricted["claims"][0]["evidence"]],
                         ["Alpha."])

    def test_retrieval_unavailable_not_falsely_reviewed(self):
        state, pending = prepare_coverage([{"id": "S001", "content": ""}],
                                           {}, segment_size=512)
        self.assertEqual(pending, [])
        summary = summarize_coverage(state)
        self.assertEqual(summary["unavailable_source_ids"], ["S001"])
        self.assertEqual(summary["model_processed_source_count"], 0)


if __name__ == "__main__":
    unittest.main()
