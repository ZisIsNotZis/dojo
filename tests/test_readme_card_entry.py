"""The README's `--card` / `--resume` section has to be true and runnable.

The brief was "a first-time reader must be able to find how to open a session on a card
and how to continue one". Before this slice neither page mentioned either flag outside
the `--help` output, so the only way to learn them was to read the parser.

Two things this refuses to accept:

  absent    a page that never shows `--card` / `--resume` on a copyable line. Naming a
            flag in prose is not registration -- the same rule the `stories` views gate
            already enforces.
  false     the section quoting an output the command does not produce. The refused
            combinations are local: they exit 2 *before* any endpoint is needed, so they
            are run here from a throwaway library, not trusted as text.

The lines that need a live endpoint are not run here (the README gate already excludes
them by name), but the card-read and conflict refusals are offline and are executed.
"""
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


def _repo_root():
    if os.environ.get("DOJO_ROOT"):
        return Path(os.environ["DOJO_ROOT"]).resolve()
    for parent in Path(__file__).resolve().parents:
        if (parent / "dojo" / "cli.py").is_file() and (parent / "README.md").is_file():
            return parent
    raise RuntimeError("cannot locate the dojo repository root")


ROOT = _repo_root()
PAGES = ("README.md", "README.zh-CN.md")
FLAGS = ("--card", "--resume")


def page_text(name):
    return (ROOT / name).read_text(encoding="utf-8")


def copyable_lines(text):
    return [line for line in text.splitlines()
            if "python3 -m dojo discuss" in line and not line.lstrip().startswith("#")]


class FrontPageShowsTheCardEntry(unittest.TestCase):
    def test_each_page_shows_both_flags_on_a_copyable_line(self):
        for page in PAGES:
            with self.subTest(page=page):
                lines = copyable_lines(page_text(page))
                for flag in FLAGS:
                    self.assertTrue(any(flag in line for line in lines),
                                    "%s never shows `%s` on a command a reader can copy"
                                    % (page, flag))

    def test_each_page_says_the_two_cannot_be_combined(self):
        for page in PAGES:
            with self.subTest(page=page):
                text = page_text(page)
                self.assertRegex(text, r"--card[^\n]{0,120}--resume",
                                 "%s does not show the two flags together with a reason" % page)

    def test_the_refusals_the_pages_quote_really_happen(self):
        """Both lines exit 2 with no endpoint, so they can be executed, not trusted."""
        env = {k: v for k, v in os.environ.items() if not k.startswith("DOJO_")}
        env["PYTHONPATH"] = str(ROOT)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        with tempfile.TemporaryDirectory() as temp:
            env["DOJO_DB"] = str(Path(temp) / "d.sqlite3")
            base = [sys.executable, "-B", "-m", "dojo"]

            def run(*args):
                return subprocess.run(base + list(args), cwd=str(ROOT), env=env,
                                      input="", text=True, capture_output=True, timeout=120)

            self.assertEqual(0, run("add", "--id", "c1", "--kind", "abstract_idea",
                                    "--statement", "一句用来试入口的话。").returncode)
            missing = run("discuss", "--card", "c9")
            conflict = run("discuss", "--card", "c1", "--resume", "x.jsonl")
            no_endpoint = run("discuss", "--card", "c1")

        self.assertEqual(2, missing.returncode)
        self.assertIn("这张卡读不出来", missing.stderr)
        self.assertIn("未发送网络请求", missing.stderr)

        self.assertEqual(2, conflict.returncode)
        self.assertIn("--card 与 --resume 不能同时使用", conflict.stderr)

        self.assertEqual(2, no_endpoint.returncode)
        self.assertIn("未配置 DOJO_LLM_BASE_URL", no_endpoint.stderr)

        # And the pages quote those words, not something else.
        for page in PAGES:
            text = page_text(page)
            with self.subTest(page=page):
                self.assertIn("这张卡读不出来", text)
                self.assertIn("--card 与 --resume 不能同时使用", text)

    def test_the_section_names_the_trace_shape_a_reader_must_supply(self):
        """`--resume` takes a path; a reader needs to know which one is legal."""
        for page in PAGES:
            with self.subTest(page=page):
                text = page_text(page)
                self.assertIn("sessions/discuss-", text)
                self.assertRegex(text, r"32", "the page should say the id is 32 hex chars")


if __name__ == "__main__":
    unittest.main()
