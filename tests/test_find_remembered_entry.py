"""The slice's evidence must run, pass, and be described by numbers it produces.

Same rule as the earlier slices' gates: a verifier nobody executes quietly stops working,
and a verifier that always exits 0 proves nothing. The expensive part (ten red arms,
each restoring one behaviour in a copy of the tree) lives in `redarm.py` beside the
verifier; this gate keeps the cheap part, plus one full arm so the wiring is known live.

The numbers in `SUMMARY.md` are read from the scripts' own output, never counted by hand:
the previous slice measured that static counting of `check(` lines is wrong for loops.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SLICE = "2026-11-28-find-remembered"


def _repo_root():
    for parent in Path(__file__).resolve().parents:
        if (parent / "dojo" / "finding.py").is_file():
            return parent
    raise RuntimeError("cannot locate the dojo repository root")


ROOT = _repo_root()
DIR = ROOT / "docs" / "evidence" / SLICE
ENTRY = DIR / "verify.py"
ARMS = DIR / "redarm.py"
SUMMARY = DIR / "SUMMARY.md"
WALK = DIR / "WALK.md"


def clean_env():
    env = {k: v for k, v in os.environ.items() if not k.startswith("DOJO_")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def run(tree, script):
    return subprocess.run([sys.executable, "-B", str(tree / "docs" / "evidence" / SLICE / script),
                           str(tree)], cwd=str(tree), capture_output=True, text=True,
                          env=clean_env(), timeout=1800)


class TheFindRememberedEntryPoint(unittest.TestCase):
    def test_it_says_ok_and_exits_zero(self):
        done = run(ROOT, "verify.py")
        self.assertEqual(0, done.returncode, "the entry point did not pass:\n%s" % done.stdout[-4000:])
        self.assertIn("0 不成立。", done.stdout)
        # The facts this slice exists for, by the names its own readings print.
        for phrase in ("同样的词仍然列出我那条（不是只剩相反那条）",
                       "并且说了为什么：被人质疑过",
                       "没有把检索的拒绝说成库里的空缺",
                       "给出另一个办法：最近写下的卡",
                       "并说明那不是按意思找的",
                       "用换掉之前那句还能找到它",
                       "屏幕说这是它以前的说法",
                       "给出的命令带绝对 --db 和这张卡的 id",
                       "命令行 stdout 仍是四个旧键（屏幕的键不进 stdout）"):
            self.assertIn(phrase, done.stdout, phrase)

    def test_it_is_not_vacuous(self):
        """It must go red on a tree where refused cards stop being shown."""
        work = Path(tempfile.mkdtemp(prefix="find-entry."))
        self.addCleanup(shutil.rmtree, work, ignore_errors=True)
        for name in ("dojo", "docs"):
            shutil.copytree(ROOT / name, work / name)
        path = work / "dojo" / "cli.py"
        source = path.read_text(encoding="utf-8")
        stripped = source.replace("for_reading=True)", "for_reading=False)", 1)
        self.assertNotEqual(source, stripped, "the reading call was not found to change")
        path.write_text(stripped, encoding="utf-8")
        done = run(work, "verify.py")
        self.assertEqual(1, done.returncode,
                         "the entry point passed with refused cards re-hidden:\n%s"
                         % done.stdout[-2000:])
        self.assertIn("FAIL 同样的词仍然列出我那条", done.stdout)

    def test_the_documented_numbers_are_the_ones_the_scripts_print(self):
        """SUMMARY names a reading count and an arm count; both come from the scripts."""
        done = run(ROOT, "verify.py")
        readings = re.search(r"(\d+) 项读数：", done.stdout)
        self.assertIsNotNone(readings, done.stdout[-500:])
        summary = SUMMARY.read_text(encoding="utf-8")
        self.assertIn("%s 项" % readings.group(1), summary,
                      "SUMMARY.md must quote the count its own verifier prints")

        arms = re.search(r"baseline: verify\.py green \((\d+) arms\)", (run(ROOT, "redarm.py")).stdout)
        self.assertIsNotNone(arms, "redarm.py did not report its arm count")
        self.assertIn("%s 条臂" % arms.group(1), summary,
                      "SUMMARY.md must quote the arm count redarm.py reports")

    def test_every_documented_path_and_command_exists(self):
        """A walk through a command that does not run is worse than no walk."""
        for page in (SUMMARY, WALK):
            text = page.read_text(encoding="utf-8")
            for match in re.finditer(r"python3 (docs/evidence/[^\s#]+\.py)", text):
                self.assertTrue((ROOT / match.group(1)).is_file(), match.group(1))
            for match in re.finditer(r"python3 -m dojo [^\n`]*", text):
                line = match.group(0).replace("...", "").strip()
                # The subcommand is the first word after the program that is neither a
                # flag nor a flag's value. Reading a fixed position was wrong here: the
                # documented lines carry `--db "$DB"`, which is a flag and a value.
                tokens = line.split()
                # `python3 -m dojo` is three tokens; the subcommand follows them.
                command, index = None, 3
                while index < len(tokens):
                    token = tokens[index]
                    if token.startswith("-"):
                        index += 2 if token in ("--db", "--card") else 1
                        continue
                    command = token.strip("'\"")
                    break
                self.assertIsNotNone(command, line)
                parser = subprocess.run([sys.executable, "-B", "-m", "dojo", command, "--help"],
                                        cwd=str(ROOT), env=clean_env(), capture_output=True, text=True)
                self.assertEqual(0, parser.returncode, line)

    def test_a_screen_key_never_appears_in_the_published_json(self):
        """One more place the boundary is checked, because it is the easiest to break."""
        self.assertIn('published = {key: value for key, value in result.items()',
                      (ROOT / "dojo" / "cli.py").read_text(encoding="utf-8"))
        # The library is created first: a search against a missing file is refused now, so
        # this check would otherwise pass by reading an error message's empty stdout.
        work = Path(tempfile.mkdtemp(prefix="find-json."))
        self.addCleanup(shutil.rmtree, work, ignore_errors=True)
        db = work / "x.sqlite3"
        subprocess.run([sys.executable, "-B", "-m", "dojo", "--db", str(db), "add",
                        "--statement", "值班通知交系统跑。", "--kind", "abstract_idea"],
                       cwd=str(ROOT), env=clean_env(), capture_output=True, text=True)
        done = subprocess.run(
            [sys.executable, "-B", "-m", "dojo", "--db", str(db), "search", "值班"],
            cwd=str(ROOT), env=clean_env(), capture_output=True, text=True,
        )
        self.assertEqual(0, done.returncode, done.stderr)
        payload = json.loads(done.stdout)
        self.assertEqual({"query", "method", "matched_terms", "results"}, set(payload))


if __name__ == "__main__":
    unittest.main()
