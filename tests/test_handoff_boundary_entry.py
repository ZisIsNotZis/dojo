"""The slice's own verifier must run, pass, and go red when its fix is undone.

Same rule as the typed-stop and card-handoff gates: a verifier nobody executes quietly
stops working, and a verifier that always returns 0 proves nothing. The arms live beside
the verifier it checks (`docs/evidence/2026-11-28-handoff-boundary/redarm.py`, eight of
them); this gate keeps the cheap part -- that the entry runs green here, and that it goes
red on a tree where the boundary is only sent to the model.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SLICE = "2026-11-28-handoff-boundary"


def _repo_root():
    for parent in Path(__file__).resolve().parents:
        if (parent / "dojo" / "discuss.py").is_file() and (parent / "dojo" / "elicit.py").is_file():
            return parent
    raise RuntimeError("cannot locate the dojo repository root")


ROOT = _repo_root()
ENTRY = ROOT / "docs" / "evidence" / SLICE / "verify.py"
ARMS = ROOT / "docs" / "evidence" / SLICE / "redarm.py"
SUMMARY = ROOT / "docs" / "evidence" / SLICE / "SUMMARY.md"
WALK = ROOT / "docs" / "evidence" / SLICE / "WALK.md"


def clean_env():
    env = {k: v for k, v in os.environ.items() if not k.startswith("DOJO_")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


class TheHandoffBoundaryEntryPoint(unittest.TestCase):
    def run_entry(self, tree):
        return subprocess.run(
            [sys.executable, "-B", str(tree / "docs" / "evidence" / SLICE / "verify.py")],
            cwd=str(tree), capture_output=True, text=True, env=clean_env(), timeout=900,
        )

    def test_it_says_ok_and_exits_zero(self):
        done = self.run_entry(ROOT)
        self.assertEqual(0, done.returncode,
                         "the entry point did not pass:\n%s" % done.stdout[-4000:])
        self.assertIn("项检查：", done.stdout)
        self.assertIn("0 不成立", done.stdout)
        # The facts this slice exists for, each with its own item. These are the printed
        # item names: the sentences themselves are asserted inside `verify.py` against
        # what the screen showed, so asserting them here would only re-read the script.
        for phrase in ("开场屏幕印出「什么时候成立」", "开场屏幕印出「什么时候不成立」",
                       "开场屏幕印出「还没定的是」", "开场屏幕印出「它靠这些前提」",
                       "质疑之后，认可记录说的是「库里没有」而不是「没人认可」",
                       "印出库里的改动理由", "来源记录说的是什么也印在屏幕上",
                       "草稿状态的卡不再说没人认可过它",
                       "续跑仍印出认可记录（从轨迹行重建）"):
            self.assertIn("ok   " + phrase, done.stdout, phrase)

    def test_it_is_not_vacuous(self):
        """Red on a tree where the limits go to the model and not to the person -- the
        measured defect this slice exists for."""
        work = Path(tempfile.mkdtemp(prefix="handoff-boundary."))
        self.addCleanup(shutil.rmtree, work, ignore_errors=True)
        for name in ("dojo", "docs"):
            shutil.copytree(ROOT / name, work / name)
        path = work / "dojo" / "discuss.py"
        source = path.read_text(encoding="utf-8")
        stripped = source.replace(
            '    limits = boundary_lines(candidate)\n'
            '    if limits:\n'
            '        block += "\\n" + "\\n".join(limits)\n',
            "", 1,
        )
        # The anchor moved once already (the boundary block was added to `handoff_block`
        # in this slice), so the control asserts it found the line and that the entry
        # goes red -- not merely that some bytes were edited.
        self.assertNotEqual(source, stripped, "the boundary block was not found to remove")
        path.write_text(stripped, encoding="utf-8")
        done = self.run_entry(work)
        self.assertEqual(1, done.returncode,
                         "the entry point passed with the limits only in the model's request:"
                         "\n%s" % done.stdout[-3000:])
        self.assertIn("项检查：", done.stdout)
        self.assertIn("不成立", done.stdout)

    def test_the_docs_name_the_commands_they_claim(self):
        summary = SUMMARY.read_text(encoding="utf-8")
        walk = WALK.read_text(encoding="utf-8")
        for command in (
            "python3 docs/evidence/2026-11-28-handoff-boundary/verify.py",
            "python3 -B -m unittest discover -s tests",
        ):
            self.assertIn(command, summary, command)
        self.assertIn("python3 -m dojo --db \"$DB\" discuss --card", walk)
        for path in (
            ROOT / "docs" / "evidence" / SLICE / "verify.py",
            ROOT / "docs" / "evidence" / SLICE / "redarm.py",
            ROOT / "tests" / "test_handoff_boundary.py",
        ):
            self.assertTrue(path.is_file(), str(path))

    def test_the_arms_file_is_runnable_and_reports_a_verdict(self):
        """Not the arms themselves (they take minutes); just that the file is a program
        with arms in it, so a reader who runs it is not met with a syntax error."""
        text = ARMS.read_text(encoding="utf-8")
        self.assertIn("ARMS = [", text)
        self.assertGreaterEqual(text.count('"dojo/discuss.py"'), 6)
        done = subprocess.run(
            [sys.executable, "-B", "-m", "py_compile", str(ARMS)],
            capture_output=True, text=True, env=clean_env(), timeout=120,
        )
        self.assertEqual(0, done.returncode, done.stderr[-1000:])


if __name__ == "__main__":
    unittest.main()
