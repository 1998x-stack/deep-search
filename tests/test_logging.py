"""Loguru logging system: sinks, redaction, isolation and stage timing."""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from factory.logging_setup import (REDACTED, configure_logging, describe, logger,
                                   log_run_summary, redact, redaction_count,
                                   register_secret, safe_url, stage, timed)

SECRET = "supersecret-value-123456"


class LoggingTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        register_secret(SECRET)
        configure_logging(self.root, level="DEBUG", json_logs=True, console=False,
                          secrets=[SECRET])

    def tearDown(self):
        logger.complete()
        self._tmp.cleanup()

    def read(self, name: str) -> str:
        logger.complete()
        return (self.root / "logs" / name).read_text(encoding="utf-8")

    def test_sinks_created_and_described(self):
        for name in ("run.log", "run.jsonl", "errors.log"):
            self.assertTrue((self.root / "logs" / name).exists(), name)
        description = describe()
        self.assertEqual(description["level"], "DEBUG")
        self.assertEqual(description["files"], ["logs/run.log", "logs/run.jsonl", "logs/errors.log"])
        self.assertIn("logs/run.jsonl", description["files"])
        self.assertTrue(description["json_logs"])
        self.assertFalse(description["console"])

    def test_registered_secret_is_scrubbed(self):
        logger.info("using credential {}", SECRET)
        self.assertIn(REDACTED, self.read("run.log"))
        self.assertNotIn(SECRET, self.read("run.log"))
        self.assertNotIn(SECRET, self.read("run.jsonl"))

    def test_pattern_scrubbing(self):
        logger.info("Authorization: Bearer abcdef0123456789 and api_key=OTHERTOKEN12345")
        logger.info("visit https://example.org/v1?key=GOOGLESECRET123&q=1")
        logger.info("prefix key sk-live-abcdef0123456789 end")
        text = self.read("run.log")
        for leak in ("abcdef0123456789", "OTHERTOKEN12345", "GOOGLESECRET123",
                     "sk-live-abcdef0123456789"):
            self.assertNotIn(leak, text)
        self.assertIn(REDACTED, text)

    def test_extra_fields_and_exception_are_redacted(self):
        try:
            raise RuntimeError("token=" + SECRET)
        except RuntimeError:
            logger.bind(stage="x", detail="leaked " + SECRET).opt(exception=True).error("boom")
        text = self.read("errors.log")
        self.assertNotIn(SECRET, text)
        self.assertIn("boom", text)
        self.assertTrue(text.strip())

    def test_jsonl_is_machine_readable(self):
        with logger.contextualize(run_id="run-test", stage="unit"):
            logger.info("structured {}", "message")
        lines = [json.loads(line) for line in self.read("run.jsonl").splitlines() if line.strip()]
        self.assertTrue(lines)
        record = lines[-1]["record"]
        self.assertEqual(record["message"], "structured message")
        self.assertEqual(record["extra"]["stage"], "unit")
        self.assertEqual(record["extra"]["run_id"], "run-test")

    def test_human_log_has_stage_field(self):
        with logger.contextualize(stage="search"):
            logger.info("hello")
        self.assertIn("search | hello", self.read("run.log"))

    def test_stage_logs_timing_and_reraises(self):
        with self.assertRaises(ValueError):
            with stage("planning", round=1):
                raise ValueError("no plan")
        text = self.read("run.log")
        self.assertIn("stage started: planning", text)
        self.assertIn("stage failed: planning", text)
        self.assertIn("ValueError", text)

    def test_stage_finished_records_duration(self):
        with stage("synthesis"):
            pass
        self.assertIn("stage finished: synthesis duration_ms=", self.read("run.log"))

    def test_timed_context_manager(self):
        with timed("fetch", source="S001") as clock:
            pass
        self.assertGreaterEqual(clock.seconds, 0.0)

    def test_reconfigure_does_not_duplicate_lines(self):
        configure_logging(self.root, level="INFO", json_logs=True, console=False)
        logger.info("single line please")
        occurrences = self.read("run.log").count("single line please")
        self.assertEqual(occurrences, 1)

    def test_invalid_level_rejected(self):
        with self.assertRaises(ValueError):
            configure_logging(self.root, level="LOUD")

    def test_short_secret_not_registered(self):
        self.assertFalse(register_secret("abc"))

    def test_redact_helper(self):
        before = redaction_count()
        out = redact("Bearer " + SECRET + " token=abc/def+ghi=")
        self.assertNotIn(SECRET, out)
        self.assertGreaterEqual(redaction_count(), before)

    def test_safe_url_drops_query_and_credentials(self):
        self.assertEqual(safe_url("https://example.org/a/b?key=SECRET#frag"),
                         "https://example.org/a/b")
        self.assertEqual(safe_url("https://user:pass@example.org/x"), "https://example.org/x")
        self.assertEqual(safe_url(None), "")
        self.assertEqual(safe_url("not a url"), "<unparsable-url>")

    def test_run_summary_logs_errors(self):
        log_run_summary({"run_id": "run-1", "status": "failed", "rounds": 1,
                         "queries_executed": 2, "fetches_attempted": 0,
                         "errors": ["ModelError: " + SECRET], "stop_reason": "execution_failed"})
        text = self.read("run.log")
        self.assertIn("status=failed", text)
        self.assertNotIn(SECRET, text)

    def test_console_only_configuration_creates_no_files(self):
        # A real text stream avoids loguru treating a Mock as a path-like sink.
        with patch("sys.stderr", new=io.StringIO()):
            configure_logging(None, level="INFO", json_logs=True, console=True)
            self.assertIsNone(describe()["log_dir"])
        configure_logging(self.root, level="DEBUG", json_logs=True, console=False,
                          secrets=[SECRET])


if __name__ == "__main__":
    unittest.main()
