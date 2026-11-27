"""The card-handoff slice's evidence script must run, must fail without the fix, and its
docs must name the commands they claim.

Same rule as the typed-stop gate: a verifier nobody executes quietly stops working, and a
verifier that always returns 0 proves nothing. The arms themselves live beside it
(`.scratch/3363/redarm_card.py`); this gate runs the verifier, then runs it again on a
copy with the handout wired out.
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
        if (parent / "dojo" / "discuss.py").is_file() and (parent / "dojo" / "elicit.py").is_file():
            return parent
    raise RuntimeError("cannot locate the dojo repository root")


ROOT = _repo_root()
ENTRY = ROOT / "docs" / "evidence" / "2026-11-28-card-handoff" / "verify.py"
SUMMARY = ROOT / "docs" / "evidence" / "2026-11-28-card-handoff" / "SUMMARY.md"
WALK = ROOT / "docs" / "evidence" / "2026-11-28-card-handoff" / "WALK.md"


def clean_env():
    env = {k: v for k, v in os.environ.items() if not k.startswith("DOJO_")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


class TheCardHandoffEntryPoint(unittest.TestCase):
    def run_entry(self, tree):
        return subprocess.run(
            [sys.executable, "-B", str(tree / "docs" / "evidence" / "2026-11-28-card-handoff" / "verify.py")],
            cwd=str(tree), capture_output=True, text=True, env=clean_env(), timeout=600,
        )

    def test_it_says_ok_and_exits_zero(self):
        done = self.run_entry(ROOT)
        self.assertEqual(0, done.returncode,
                         "the entry point did not pass:\n%s" % done.stdout[-3000:])
        self.assertIn("全部成立。", done.stdout)
        # The three facts this slice exists for, each checked by its own item.
        for phrase in ("之前是", "改动理由", "不算第二个独立来源"):
            self.assertIn(phrase, done.stdout, phrase)

    def test_it_is_not_vacuous(self):
        """It has to fail on a tree where the handout no longer reaches the model."""
        work = Path(tempfile.mkdtemp(prefix="card-handoff."))
        self.addCleanup(shutil.rmtree, work, ignore_errors=True)
        for name in ("dojo", "docs"):
            shutil.copytree(ROOT / name, work / name)
        source = (work / "dojo" / "discuss.py").read_text(encoding="utf-8")
        stripped = source.replace(
            '                context += block + "\\n\\n"',
            '                context += ""', 1,
        )
        # The anchor is whatever line actually puts the handout in the request. It moved
        # once already (the resume fix wrapped it in `block`), and this control silently
        # stopped biting when it did -- so it asserts it found the line, and the check
        # below asserts the entry point goes red, not just that some bytes were edited.
        self.assertNotEqual(source, stripped, "the handout line was not found to remove")
        # Moved again by the boundary slice: the call now carries the ledger's
        # acceptance fact beside the card. The guard is on the line that puts the
        # handout in the request, not on any particular spelling of its arguments.
        self.assertIn("handoff_for_model(handed, handed_basis, acceptance=handed_acceptance)",
                      source)
        (work / "dojo" / "discuss.py").write_text(stripped, encoding="utf-8")
        done = self.run_entry(work)
        self.assertEqual(1, done.returncode,
                         "the entry point passed with no handout in the request:\n%s"
                         % done.stdout[-2000:])
        self.assertIn("项不成立。", done.stdout)

    def test_the_docs_name_the_commands_they_claim(self):
        summary = SUMMARY.read_text(encoding="utf-8")
        walk = WALK.read_text(encoding="utf-8")
        for command in (
            "python3 docs/evidence/2026-11-28-card-handoff/verify.py",
            "python3 -B -m unittest discover -s tests",
        ):
            self.assertIn(command, summary, command)
        self.assertIn("python3 -m dojo discuss --card", walk)
        # Paths the docs point at must exist in this tree.
        for path in (
            ROOT / "docs" / "evidence" / "2026-11-28-card-handoff" / "verify.py",
            ROOT / "tests" / "test_card_handoff.py",
        ):
            self.assertTrue(path.is_file(), str(path))


if __name__ == "__main__":
    unittest.main()
