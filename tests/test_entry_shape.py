"""The slice's entry point must run, and must fail when the shape is gone.

A reader-facing script that nobody executes is a script that quietly stops working.
This runs it the way the README tells a reader to, and then checks that it is not
vacuous: with the shape block removed from the source, it has to return 1.
"""
import os
import subprocess
import sys
import unittest
from pathlib import Path


def _repo_root():
    for parent in Path(__file__).resolve().parents:
        if (parent / "dojo" / "discuss.py").is_file() and (parent / "scripts" / "dao_life.py").is_file():
            return parent
    raise RuntimeError("cannot locate the dojo repository root")


ROOT = _repo_root()
ENTRY = ROOT / "docs" / "evidence" / "2026-11-27-entry-shape" / "verify.py"


class TheEntryPointRuns(unittest.TestCase):
    def run_entry(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith("DOJO_")}
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run([sys.executable, "-B", str(ENTRY)], cwd=str(ROOT),
                              capture_output=True, text=True, env=env, timeout=300)

    def test_it_says_ok_and_exits_zero(self):
        done = self.run_entry()
        self.assertEqual(0, done.returncode,
                         "the entry point did not pass:\n%s" % done.stderr[-2000:])
        self.assertIn("在第一个问题之前", done.stderr)

    def test_it_is_not_vacuous(self):
        """It must fail on a tree where the shape block is absent.

        Run from a copy whose `dojo/discuss.py` has `SHAPE` removed, rather than
        trusting the check to be meaningful. Without this, an entry point that
        always returns 0 would pass the test above.
        """
        import shutil
        import tempfile
        work = Path(tempfile.mkdtemp(prefix="entry-shape."))
        self.addCleanup(shutil.rmtree, work, ignore_errors=True)
        for name in ("dojo", "docs", "scripts"):
            shutil.copytree(ROOT / name, work / name)
        source = (work / "dojo" / "discuss.py").read_text(encoding="utf-8")
        stripped = source.replace('print("\\n主持人> " + shape_text(trace_is_open), file=output)\n', "")
        self.assertNotEqual(source, stripped, "the shape print was not found to remove")
        (work / "dojo" / "discuss.py").write_text(stripped, encoding="utf-8")
        copy_entry = work / "docs" / "evidence" / "2026-11-27-entry-shape" / "verify.py"
        env = {k: v for k, v in os.environ.items() if not k.startswith("DOJO_")}
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        done = subprocess.run([sys.executable, "-B", str(copy_entry)], cwd=str(work),
                              capture_output=True, text=True, env=env, timeout=300)
        self.assertEqual(1, done.returncode,
                         "the entry point passed on a tree with no shape block:\n%s"
                         % done.stdout[-1000:])


if __name__ == "__main__":
    unittest.main()
