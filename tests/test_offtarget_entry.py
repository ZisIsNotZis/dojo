"""This slice's evidence script must run, must fail without the fix, and its docs must
name the commands they claim.

Same rule as the earlier slices' entry gates: a verifier nobody executes quietly stops
working, and a verifier that always returns 0 proves nothing. The six arms themselves live
beside it (`.scratch/3389/redarm_offtarget.py`); this gate runs the verifier, then runs it
again on a copy where the receipt word is put back.
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
EVIDENCE = ROOT / "docs" / "evidence" / "2026-11-28-offtarget-receipt"
SUMMARY = EVIDENCE / "SUMMARY.md"
WALK = EVIDENCE / "WALK.md"


def clean_env():
    env = {k: v for k, v in os.environ.items() if not k.startswith("DOJO_")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


class TheOffTargetEntryPoint(unittest.TestCase):
    def run_entry(self, tree):
        return subprocess.run(
            [sys.executable, "-B", str(tree / "docs" / "evidence"
                                       / "2026-11-28-offtarget-receipt" / "verify.py")],
            cwd=str(tree), capture_output=True, text=True, env=clean_env(), timeout=600,
        )

    def test_it_says_ok_and_exits_zero(self):
        done = self.run_entry(ROOT)
        self.assertEqual(0, done.returncode,
                         "the entry point did not pass:\n%s" % done.stdout[-3000:])
        self.assertIn("全部成立。", done.stdout)
        # The third phrase was 没有写进卡片 until 2026-11-28, when the answers began
        # reaching the card; the guarantee that survived is the narrower one.
        for phrase in ("说了原话", "答没答到点上", "附在卡片"):
            self.assertIn(phrase, done.stdout, phrase)

    def test_it_is_not_vacuous(self):
        """It has to fail on a tree where the receipt claims the questions were answered."""
        work = Path(tempfile.mkdtemp(prefix="offtarget."))
        self.addCleanup(shutil.rmtree, work, ignore_errors=True)
        for name in ("dojo", "docs"):
            shutil.copytree(ROOT / name, work / name)
        source = (work / "dojo" / "discuss.py").read_text(encoding="utf-8")
        anchor = '            pieces.append("你在 " + "、".join(said) + " 上说了原话")'
        stripped = source.replace(anchor, '            pieces.append("你答了 " + "、".join(said))', 1)
        # The anchor moved once already in an earlier slice and the control silently
        # stopped biting; assert it found the line, then assert the entry point goes red.
        self.assertNotEqual(source, stripped, "the receipt line was not found to change")
        (work / "dojo" / "discuss.py").write_text(stripped, encoding="utf-8")
        done = self.run_entry(work)
        self.assertEqual(1, done.returncode,
                         "the entry point passed with the old word back:\n%s"
                         % done.stdout[-2000:])
        self.assertIn("项不成立。", done.stdout)

    def test_the_docs_name_the_commands_they_claim(self):
        summary = SUMMARY.read_text(encoding="utf-8")
        walk = WALK.read_text(encoding="utf-8")
        for command in (
            "python3 docs/evidence/2026-11-28-offtarget-receipt/verify.py",
            "python3 -B -m unittest tests.test_offtarget_receipt",
            "python3 .scratch/3389/redarm_offtarget.py",
        ):
            self.assertIn(command, summary, command)
        self.assertIn("python3 docs/evidence/2026-11-28-offtarget-receipt/verify.py", walk)
        self.assertIn("python3 .scratch/3389/probe_offtarget.py", walk)


if __name__ == "__main__":
    unittest.main()
