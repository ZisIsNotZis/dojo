"""The commands this program prints have to work when pasted, on the library it used.

#3419, found by walking the real CLI: `dojo discuss --db <somewhere>` ended by printing
`python3 -m dojo show d-7f9adf0f22a8`. Pasted, that reads the *default* library and says
`candidate not found` about a draft the session had just written. With `--no-trace` there
is no trace at all to lean on, so that line has to be right by itself.

What these tests refuse to accept:

  wrong library   a printed command that reads a different library than the session used
  written record  the library path being stored in the trace. It is local command
                  context, not part of what he said; a trace is copied, shared and read
                  on other machines.
  mangled path    a path pasted as two arguments, or expanded by the shell
  side effect     pasting a read-only command creating an empty default library
  blank library   the short form (`python3 -m dojo show ID`) disappearing where it is
                  already correct -- the default library is the common case
"""
import json
import os
import shlex
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from dojo import commands
from dojo.discuss import run_discuss
from dojo.storage import Store

ROOT = Path(__file__).resolve().parents[1]

CARD = "持续检查交给系统自己跑，但只在检查结果会打断他时才叫醒他。"
CONCLUSION = {
    "statement": CARD, "kind": "abstract_idea",
    "scope": ["他已经抽身的时候"], "premises": ["系统能自己跑检查"],
    "alternatives": ["把检查留给人"], "contradictions": ["检查必须发生在世界里时"],
    "unknowns": ["他会不会来看回执"],
}
# A space and a single quote: the two characters the supervisor named, plus `$` and a
# backtick, which a double-quoted shell word would still act on.
TRICKY = "a library's $dir`x"


def read_lines(lines):
    iterator = iter(lines)

    def read_line(_prompt):
        try:
            return next(iterator)
        except StopIteration:
            raise EOFError
    return read_line


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)

    def complete(self, messages):
        return self.responses.pop(0)


class TheRenderer(unittest.TestCase):
    def test_a_plain_name_is_printed_plain(self):
        for text in ("c1", "d-0123456789ab", "seed-m01", "/tmp/x/dojo.sqlite3"):
            self.assertEqual(text, commands.quote(text), text)

    def test_a_spaced_or_quoted_path_arrives_as_one_word(self):
        for text in (TRICKY, "a plain dir/x.sqlite3", "it's here", 'say "hi"', "a\nnewline"):
            with self.subTest(text=text):
                self.assertEqual([text], shlex.split(commands.quote(text)), text)

    def test_the_flag_is_not_wrapped_in_quotes(self):
        """`discuss \"--resume\" x` is correct and reads like a mistake."""
        line = commands.dojo("discuss", "--resume", "/tmp/a b/t.jsonl")
        self.assertNotIn('"--resume"', line)
        self.assertEqual("--resume", shlex.split(line)[4])

    def test_dollar_and_backtick_survive_a_real_shell(self):
        path = "/tmp/it's $HOME `echo hi`/x.sqlite3"
        line = "printf %s " + commands.quote(path)
        done = subprocess.run(["sh", "-c", line], capture_output=True, text=True)
        self.assertEqual(path, done.stdout)

    def test_a_bare_command_needs_no_library(self):
        self.assertIsNone(commands.library_argument(None))


class TheExitLines(unittest.TestCase):
    """A session on a named library, ended early so it leaves a draft to look at."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.library = self.root / TRICKY
        self.library.mkdir()
        self.store = Store(self.library / "my dojo's.sqlite3")
        self.addCleanup(self.store.close)

    def run_session(self, *, no_trace=False):
        import io
        output = io.StringIO()
        code = run_discuss(
            self.store,
            client=FakeClient([{"answer": "那我们把这句当成现在这一版。",
                                "candidate": CONCLUSION, "user_stance": "neutral"}]),
            read_line=read_lines(["我想接着说"]),
            output=output, no_trace=no_trace, environ={},
        )
        return code, output.getvalue()

    def printed(self, text, marker):
        """The command a reader copies off the line carrying `marker`, shell-parsed.

        The line carries prose before it ("...先看它：python3 -m dojo ..."), so the
        command starts at `python3`, not after the first colon -- splitting on a colon
        kept the draft id and dropped the command, which is the kind of test bug that
        makes a red result say the wrong thing.
        """
        line = next(line for line in text.splitlines() if marker in line)
        start = line.index("python3 -m dojo")
        command = line[start:].split("（", 1)[0].strip().rstrip("。")
        return shlex.split(command)

    def test_with_a_trace_the_card_command_names_the_draft_and_the_library(self):
        code, text = self.run_session()
        self.assertEqual(0, code)
        tokens = self.printed(text, "草稿")
        self.assertIn("show", tokens)
        self.assertIn("--db", tokens)
        self.assertEqual(str(self.store.path), tokens[tokens.index("--db") + 1])
        draft = tokens[tokens.index("show") + 1]
        self.assertTrue(draft.startswith("d-"), draft)
        self.assertIn(draft, text)

    def test_without_a_trace_the_card_command_is_still_complete(self):
        """`--no-trace` writes no record at all, so this line is the only pointer."""
        code, text = self.run_session(no_trace=True)
        self.assertEqual(0, code)
        self.assertNotIn("transcript", text, "no record was written, so name no view")
        tokens = self.printed(text, "草稿")
        self.assertIn("--db", tokens)
        self.assertEqual(str(self.store.path), tokens[tokens.index("--db") + 1])

    def test_the_library_path_is_not_put_into_the_trace(self):
        """The record of what he said is not the place for this host's file layout."""
        self.run_session()
        trace = sorted((self.library / "sessions").glob("*.jsonl"))[-1]
        raw = trace.read_text(encoding="utf-8")
        self.assertNotIn(str(self.store.path), raw, "the library path was written into the trace")
        self.assertNotIn(TRICKY, raw, "a local directory name was written into the trace")

    def test_the_read_back_line_carries_the_library_so_its_own_commands_do_too(self):
        code, text = self.run_session()
        self.assertEqual(0, code)
        tokens = self.printed(text, "回看这一场说了什么")
        self.assertEqual("transcript", tokens[tokens.index("transcript")])
        self.assertEqual(str(self.store.path), tokens[tokens.index("--db") + 1])


class AlwaysNamed(unittest.TestCase):
    """Every printed line names the file, including on the default library.

    There used to be a short form for the default location. Four reports (#3419) each
    broke it in a different place, the last one the worst: a line printed on the default
    library, pasted in a terminal whose `$DOJO_DB` points elsewhere, exited 0 on
    `--resume` and appended the second half of that conversation to the other library.
    """

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "dojo.sqlite3")
        self.addCleanup(self.store.close)

    def run_session(self):
        import io
        output = io.StringIO()
        run_discuss(
            self.store,
            client=FakeClient([{"answer": "那我们把这句当成现在这一版。",
                                "candidate": CONCLUSION, "user_stance": "neutral"}]),
            read_line=read_lines(["我想接着说"]), output=output, environ={},
        )
        return output.getvalue()

    def test_the_draft_line_names_the_library_even_when_it_is_the_default(self):
        text = self.run_session()
        draft_line = next(line for line in text.splitlines() if "草稿" in line)
        self.assertIn(" show ", draft_line)
        self.assertIn("--db", draft_line, draft_line)
        self.assertIn(str(self.store.path), draft_line)
        view_line = next(line for line in text.splitlines() if "回看这一场说了什么" in line)
        self.assertIn("--db", view_line, view_line)

    def test_the_rule_never_asks_the_environment_or_the_clock(self):
        """One rule, stated four ways and measured against each other.

        Each of these was a separate report: explicit `--db`, relative `$DOJO_DB`,
        one-shot absolute `$DOJO_DB`, and a terminal that usually works on another
        library. All four are answered the same way, from the library alone.
        """
        default = Path.home() / ".local" / "share" / "dojo" / "dojo.sqlite3"
        named = self.root / "chosen.sqlite3"
        previous = os.environ.get("DOJO_DB")
        try:
            for value in (None, str(named), "chosen.sqlite3", str(default), str(self.root)):
                if value is None:
                    os.environ.pop("DOJO_DB", None)
                else:
                    os.environ["DOJO_DB"] = value
                with self.subTest(value=value):
                    self.assertEqual(commands.library_argument(named), named)
                    self.assertEqual(commands.library_argument(default), default,
                                     "the default library is named too")
                    self.assertEqual(commands.library_argument(self.root / "x.sqlite3"),
                                     self.root / "x.sqlite3")
                    self.assertIsNone(commands.library_argument(None))
        finally:
            os.environ.pop("DOJO_DB", None)
            if previous is not None:
                os.environ["DOJO_DB"] = previous

    def test_a_relative_path_is_printed_absolutely(self):
        """`--db run/dojo.sqlite3` from another directory is another file."""
        relative = Path("run") / "dojo.sqlite3"
        self.assertEqual(commands.library_argument(relative),
                         Path.cwd() / relative)


class TheReadBack(unittest.TestCase):
    """`transcript --db` passes the library through to the commands it prints."""

    def test_the_view_prints_short_commands_when_no_library_was_named(self):
        from dojo import transcript as transcript_module

        view = {"session": "discuss-" + "0" * 32, "path": Path("/tmp/x.jsonl"),
                "records": 0, "partial_tail": False, "complete": True, "resumable": None,
                "ended": "eof", "saved": ["c1"], "draft": None, "turns": [], "parts": [],
                "handed": None}
        shown = transcript_module.render(view)
        self.assertIn("python3 -m dojo show c1", shown)
        self.assertNotIn("--db", shown)

    def test_the_view_names_the_library_when_one_was_given(self):
        from dojo import transcript as transcript_module

        view = {"session": "discuss-" + "0" * 32, "path": Path("/tmp/x.jsonl"),
                "records": 0, "partial_tail": False, "complete": True, "resumable": None,
                "ended": "eof", "saved": ["c1"], "draft": None, "turns": [], "parts": [],
                "handed": None}
        shown = transcript_module.render(view, database=Path("/tmp/an other/dojo.sqlite3"))
        self.assertIn("--db", shown)
        self.assertIn("/tmp/an other/dojo.sqlite3", shown)


if __name__ == "__main__":
    unittest.main()
