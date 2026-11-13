"""Regression tests for master prompt contract, separate from semantic evals."""
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT / "prompts" / "deep-search-master.md"


class MasterPromptTests(unittest.TestCase):
    def test_prompt_stays_under_4000_unicode_characters(self):
        text = MASTER.read_text(encoding="utf-8")
        self.assertLessEqual(len(text), 4000)
        self.assertIn("```mermaid", text)

    def test_master_prompt_entrypoint_and_mirrors(self):
        source = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("prompts/deep-search-master.md", source)
        for path in (
            ".agents/skills/deep-search/SKILL.md",
            ".claude/skills/deep-search/SKILL.md",
            ".opencode/skills/deep-search/SKILL.md",
        ):
            with self.subTest(path=path):
                self.assertEqual((ROOT / path).read_text(encoding="utf-8"), source)

    def test_prompt_contract_checker_passes(self):
        script = ROOT / "scripts" / "validate_master_prompt.py"
        proc = subprocess.run(
            [sys.executable, str(script)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("PASS:", proc.stdout)

    def test_seven_phases_and_citation_contract(self):
        text = MASTER.read_text(encoding="utf-8")
        for n in range(1, 8):
            self.assertIn(f"### Phase {n} —", text)
        self.assertIn("`[S001]`", text)
        self.assertIn("引文出现≠语义支持", text)

