"""This slice's evidence script must run, must fail without the fix, and be named in docs.

Same rule as the earlier slices' entry gates: a verifier nobody executes quietly stops
working, and a verifier that always returns 0 proves nothing. The nine arms themselves
live beside it (`redarm.py`); this gate runs the verifier, then runs it again on a copy
where the answers are made to stay out of the card.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


def _repo_root():
    for parent in Path(__file__).resolve().parents:
        if (parent / "dojo" / "discuss.py").is_file() and (parent / "dojo" / "answers.py").is_file():
            return parent
    raise RuntimeError("cannot locate the dojo repository root")


ROOT = _repo_root()
EVIDENCE = ROOT / "docs" / "evidence" / "2026-11-28-answers-on-card"


def clean_env():
    env = {k: v for k, v in os.environ.items() if not k.startswith("DOJO_")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


class TheAnswersEntryPoint(unittest.TestCase):
    def run_entry(self, tree):
        return subprocess.run(
            [sys.executable, "-B", str(tree / "docs" / "evidence"
                                       / "2026-11-28-answers-on-card" / "verify.py")],
            cwd=str(tree), capture_output=True, text=True, env=clean_env(), timeout=900,
        )

    def test_it_says_ok_and_exits_zero(self):
        done = self.run_entry(ROOT)
        self.assertEqual(0, done.returncode,
                         "the entry point did not pass:\n%s" % done.stdout[-3000:])
        self.assertIn("0 不成立", done.stdout)
        for phrase in ("附在卡片", "他的话", "part_sources 仍是系统补"):
            self.assertIn(phrase, done.stdout, phrase)

    def test_it_is_not_vacuous(self):
        """It has to fail on a tree where the answers stay out of the card again."""
        work = Path(tempfile.mkdtemp(prefix="answers-entry."))
        self.addCleanup(shutil.rmtree, work, ignore_errors=True)
        for name in ("dojo", "docs"):
            shutil.copytree(ROOT / name, work / name)
        path = work / "dojo" / "discuss.py"
        source = path.read_text(encoding="utf-8")
        anchor = '            if offer_attachment and stopped_at is None and trace_is_open:'
        stripped = source.replace(anchor, '            if False:', 1)
        self.assertNotEqual(source, stripped, "the promotion call was not found to change")
        path.write_text(stripped, encoding="utf-8")
        done = self.run_entry(work)
        self.assertEqual(1, done.returncode,
                         "the entry point passed with the answers kept out of the card:\n%s"
                         % done.stdout[-2000:])
        self.assertIn("不成立", done.stdout)
        self.assertNotIn("0 不成立", done.stdout)

    def test_public_discuss_author_recovery_and_reader_handoff(self):
        with tempfile.TemporaryDirectory(prefix="discuss-retention-entry.") as tmp:
            done = subprocess.run(
                [sys.executable, "-B", "scripts/verify_discuss_retention.py",
                 "--output", str(Path(tmp) / "evidence")], cwd=ROOT, env=clean_env(),
                capture_output=True, text=True, encoding="utf-8", timeout=60,
            )
        self.assertEqual(0, done.returncode, done.stdout + done.stderr)
        self.assertIn("明确留下含补注的版本后才可跨场借用", done.stdout)

    def test_the_docs_name_the_commands_they_claim(self):
        summary = (EVIDENCE / "SUMMARY.md").read_text(encoding="utf-8")
        walk = (EVIDENCE / "WALK.md").read_text(encoding="utf-8")
        for command in (
            "python3 docs/evidence/2026-11-28-answers-on-card/verify.py",
            "python3 docs/evidence/2026-11-28-answers-on-card/redarm.py",
            "python3 -B -m unittest tests.test_answers",
        ):
            self.assertIn(command, summary, command)
        # The two commands the walkthrough tells a reader to run must exist.
        for command in ("promote", "unpromote"):
            self.assertIn(f"dojo --db \"$DB\" {command}", walk, command)
            done = subprocess.run([sys.executable, "-m", "dojo", command, "--help"],
                                  cwd=str(ROOT), capture_output=True, text=True,
                                  env=clean_env(), timeout=60)
            self.assertEqual(0, done.returncode, done.stderr[-500:])


if __name__ == "__main__":
    unittest.main()
