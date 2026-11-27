"""This slice's evidence script must run, must fail without the fix, and the docs must
name the commands they claim.

Same rule as the earlier slices' entry gates: a verifier nobody executes quietly stops
working, and a verifier that always returns 0 proves nothing. The six arms themselves live
beside it (`docs/evidence/2026-11-28-printed-commands/redarm.py`); this gate runs the
verifier, then runs it again on a copy where the exit line lost its library.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

EVIDENCE = "docs/evidence/2026-11-28-printed-commands"


def _repo_root():
    for parent in Path(__file__).resolve().parents:
        if (parent / "dojo" / "discuss.py").is_file() and (parent / "dojo" / "commands.py").is_file():
            return parent
    raise RuntimeError("cannot locate the dojo repository root")


ROOT = _repo_root()


def clean_env():
    env = {k: v for k, v in os.environ.items() if not k.startswith("DOJO_")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


class ThePrintedCommandsEntryPoint(unittest.TestCase):
    def run_entry(self, tree):
        return subprocess.run(
            [sys.executable, "-B", str(tree / EVIDENCE / "verify.py")],
            cwd=str(tree), capture_output=True, text=True, env=clean_env(), timeout=900,
        )

    def test_it_says_ok_and_exits_zero(self):
        done = self.run_entry(ROOT)
        self.assertEqual(0, done.returncode,
                         "the entry point did not pass:\n%s" % done.stdout[-3000:])
        self.assertIn("全部成立", done.stdout)
        for phrase in ("原样粘贴能打开草稿", "库路径没有写进原话记录", "默认库仍不存在"):
            self.assertIn(phrase, done.stdout, phrase)

    def test_it_is_not_vacuous(self):
        """It has to fail on a tree where the exit line lost the library again."""
        work = Path(tempfile.mkdtemp(prefix="printed."))
        self.addCleanup(shutil.rmtree, work, ignore_errors=True)
        for name in ("dojo", "docs"):
            shutil.copytree(ROOT / name, work / name)
        path = work / "dojo" / "discuss.py"
        source = path.read_text(encoding="utf-8")
        anchor = '''                    + "（系统整理的那一版，没有人认可过）。先看它："
                    + commands.dojo("show", draft_id,
                                    db=commands.library_argument(store.path)),'''
        stripped = source.replace(
            anchor,
            '''                    + "（系统整理的那一版，没有人认可过）。先看它："
                    + commands.dojo("show", draft_id),''', 1)
        self.assertNotEqual(source, stripped, "the exit line was not found to change")
        path.write_text(stripped, encoding="utf-8")
        done = self.run_entry(work)
        self.assertEqual(1, done.returncode,
                         "the entry point passed with the old word back:\n%s"
                         % done.stdout[-2000:])
        self.assertIn("项不成立", done.stdout)

    def test_the_docs_name_the_commands_they_claim(self):
        summary = (ROOT / EVIDENCE / "SUMMARY.md").read_text(encoding="utf-8")
        walk = (ROOT / EVIDENCE / "WALK.md").read_text(encoding="utf-8")
        for command in (
            "python3 docs/evidence/2026-11-28-printed-commands/verify.py",
            "python3 -B -m unittest tests.test_printed_commands",
            "python3 docs/evidence/2026-11-28-printed-commands/redarm.py",
        ):
            self.assertIn(command, summary, command)
        self.assertIn("python3 -m dojo --db", walk)


if __name__ == "__main__":
    unittest.main()
