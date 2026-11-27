"""The typed-stop slice's evidence script must run, and must fail when the fix is gone.

A reader-facing verifier that nobody executes is a verifier that quietly stops working.
This runs it the way its SUMMARY tells a reader to, and then checks that it is not
vacuous: on a copy whose stop branch is removed, it has to return 1.

The red arms themselves live beside it (`redarm.py`) but are not run here -- they copy
the whole tree six times and take a while. This gate is the cheap part: the verifier
passes now, and it would not pass on the old behaviour.
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
ENTRY = ROOT / "docs" / "evidence" / "2026-11-27-typed-stop" / "verify.py"
SUMMARY = ROOT / "docs" / "evidence" / "2026-11-27-typed-stop" / "SUMMARY.md"
WALK = ROOT / "docs" / "evidence" / "2026-11-27-typed-stop" / "WALK.md"


def clean_env():
    env = {k: v for k, v in os.environ.items() if not k.startswith("DOJO_")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


class TheTypedStopEntryPoint(unittest.TestCase):
    def run_entry(self, tree, entry):
        return subprocess.run([sys.executable, "-B", str(entry)], cwd=str(tree),
                              capture_output=True, text=True, env=clean_env(), timeout=600)

    def test_it_says_ok_and_exits_zero(self):
        done = self.run_entry(ROOT, ENTRY)
        self.assertEqual(0, done.returncode,
                         "the entry point did not pass:\n%s" % done.stdout[-3000:])
        self.assertIn("全部成立。", done.stdout)
        # Every phrase the slice claims is checked, not just one.
        for phrase in ("算了，先不说了", "先到这吧", "不想聊了", "就说这么多吧"):
            self.assertIn("「%s」" % phrase, done.stdout, phrase)

    def test_it_is_not_vacuous(self):
        """It must fail on a tree where the stop branch is absent.

        Run from a copy whose `dojo/discuss.py` no longer handles `stop`, rather than
        trusting the checks to be meaningful. Without this, a verifier that always
        returned 0 would pass the test above -- and this slice's whole subject is
        evidence that describes something the code does not do.
        """
        work = Path(tempfile.mkdtemp(prefix="typed-stop."))
        self.addCleanup(shutil.rmtree, work, ignore_errors=True)
        for name in ("dojo", "docs"):
            shutil.copytree(ROOT / name, work / name)
        source = (work / "dojo" / "discuss.py").read_text(encoding="utf-8")
        stripped = source.replace('                    if reading == "stop":\n',
                                  '                    if False and reading == "stop":\n')
        self.assertNotEqual(source, stripped, "the stop branch was not found to remove")
        (work / "dojo" / "discuss.py").write_text(stripped, encoding="utf-8")
        copy_entry = work / "docs" / "evidence" / "2026-11-27-typed-stop" / "verify.py"
        done = self.run_entry(work, copy_entry)
        self.assertEqual(1, done.returncode,
                         "the entry point passed on a tree with no stop handling:\n%s"
                         % done.stdout[-2000:])
        self.assertIn("项不成立。", done.stdout)

    def test_the_docs_name_the_commands_they_claim(self):
        """A reader has to be able to find the checks from the docs themselves."""
        summary = SUMMARY.read_text(encoding="utf-8")
        for command in ("python3 docs/evidence/2026-11-27-typed-stop/verify.py",
                        "python3 -B -m unittest tests.test_elicitation_closing",
                        "python3 -B -m unittest discover -s tests"):
            self.assertIn(command, summary, command)
        self.assertIn("redarm.py", summary)
        self.assertTrue((ENTRY.parent / "redarm.py").is_file())
        # The walkthrough must not instruct a reader to write over a tracked file.
        for number, line in enumerate(WALK.read_text(encoding="utf-8").splitlines(), 1):
            self.assertIsNone(
                __import__("re").search(r">\s*(docs|tests|dojo|scripts)/", line),
                "WALK.md:%d writes over a tracked path: %s" % (number, line.strip()),
            )


if __name__ == "__main__":
    unittest.main()
