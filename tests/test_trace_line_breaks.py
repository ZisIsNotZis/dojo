"""One trace record, one line -- whatever the person pasted into it.

The supervisor measured this at d7fbe00 with the real CLI: an answer copied from a document
carrying U+2028 (LINE SEPARATOR) went into the trace, all four answers were in the file,
and `dojo transcript` refused the session the program had just written itself with
"第 2 行不是 JSON". `json.dumps(..., ensure_ascii=False)` leaves U+0085, U+2028 and U+2029
raw because they are legal inside a JSON string; Python's `str.splitlines()` counts all
three as line breaks. Writer and reader disagreed about what a line is.

The fix has to be on both sides, and this file pins both:

  write   a record never contains one of those three code points, so it is one physical
          line for `splitlines()`, `readline()`, `grep` and an editor
  read    records are split on `\\n` alone, so a trace written before the fix -- or by
          anything else -- still parses

and it has to reach every reader, not just `transcript`: `--resume` and the two export
scripts read the same file. Each of those is walked at its real entry here.
"""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dojo.discuss import run_discuss  # noqa: E402
from dojo.storage import Store  # noqa: E402
from dojo.tracefile import (  # noqa: E402
    LINE_BREAK_CODEPOINTS, encode_record, split_lines,
)

CONCLUSION = {
    "statement": "把持续检查交给系统，人这一侧只保留随时可以推翻的位置。",
    "kind": "abstract_idea", "scope": ["一个人已经抽身时"],
    "premises": ["系统能自己跑检查"], "alternatives": ["把检查留给人"],
    "contradictions": ["检查必须发生在世界里时"], "unknowns": ["他会不会来看回执"],
}
# What a paste from a document looks like: U+2028 and U+2029 inside one sentence.
PASTED = "那天我在修数据库\u2028修到一半卡住了，因为通知没送到\u2029后来我自己翻的日志。"
PLAIN = "照这个做，我那种先自己看一遍的习惯就没机会用了。"


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete(self, messages):
        self.calls.append(messages)
        return self.responses.pop(0)


def read_lines(lines):
    iterator = iter(lines)

    def read_line(_prompt):
        try:
            return next(iterator)
        except StopIteration:
            raise EOFError
    return read_line


def clean_env(**extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith("DOJO_")}
    env["PYTHONPATH"] = str(ROOT)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.update(extra)
    return env


class TheCodec(unittest.TestCase):
    def test_a_record_is_one_line_whatever_the_text_holds(self):
        for codepoint in LINE_BREAK_CODEPOINTS:
            with self.subTest(codepoint=hex(ord(codepoint))):
                encoded = encode_record({"answer": "前" + codepoint + "后"})
                self.assertEqual(1, len(encoded.splitlines()), repr(encoded))
                self.assertEqual(1, encoded.count("\n"), "exactly one terminator")
                self.assertTrue(encoded.endswith("\n"))
                self.assertEqual("前" + codepoint + "后",
                                 json.loads(encoded)["answer"],
                                 "the character survives the round trip")

    def test_reading_splits_on_newline_only(self):
        text = json.dumps({"a": "x\u2028y"}, ensure_ascii=False) + "\n" + \
            json.dumps({"b": 1}, ensure_ascii=False) + "\n"
        lines = split_lines(text)
        self.assertEqual(2, len(lines))
        self.assertEqual({"a": "x\u2028y"}, json.loads(lines[0]))
        self.assertEqual({"b": 1}, json.loads(lines[1]))

    def test_a_trace_written_before_the_fix_still_reads(self):
        """The reader must not depend on the writer having been fixed."""
        legacy = json.dumps({"answer": "前\u2028后"}, ensure_ascii=False) + "\n"
        self.assertEqual(2, len(legacy.splitlines()), "the old shape really did split")
        self.assertEqual([{"answer": "前\u2028后"}],
                         [json.loads(line) for line in split_lines(legacy)])


class OneRealSessionWithAPastedAnswer(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "dojo.sqlite3")
        self.addCleanup(self.store.close)

    def run_session(self, answers):
        client = FakeClient([
            {"answer": "那我们把这句当成现在这一版。", "candidate": CONCLUSION,
             "user_stance": "neutral"},
            {"answer": "好，就这句。", "candidate": CONCLUSION, "user_stance": "accept"},
        ])
        output = io.StringIO()
        code = run_discuss(self.store, client=client,
                           read_line=read_lines(["讲一条做法", "对，就这么定", *answers]),
                           output=output, environ={})
        return code, output.getvalue()

    def trace(self):
        return sorted((self.root / "sessions").glob("*.jsonl"))[-1]

    def run_cli(self, *args, env=None):
        return subprocess.run([sys.executable, "-B", "-m", "dojo", *args], cwd=str(ROOT),
                              env=clean_env(**(env or {})), input="", text=True,
                              capture_output=True, timeout=300)

    def test_a_pasted_answer_is_written_and_read_back_verbatim(self):
        answers = [PASTED, PLAIN, "没人再复核", "有一次反而漏了"]
        code, _ = self.run_session(answers)
        self.assertEqual(0, code)
        trace = self.trace()
        raw = trace.read_text(encoding="utf-8")
        for codepoint in LINE_BREAK_CODEPOINTS:
            if codepoint in PASTED:
                self.assertNotIn(codepoint, raw,
                                 "a record still contains %r, so some reader will split it"
                                 % codepoint)
        every = [json.loads(line) for line in raw.splitlines()]
        self.assertTrue(every)
        rows = [row for row in every if row.get("event") == "elicitation"]
        self.assertEqual(PASTED, rows[0]["answer"], "the words are kept exactly as typed")

        shown = self.run_cli("transcript", str(trace))
        self.assertEqual(0, shown.returncode, shown.stderr)
        self.assertIn(PASTED, shown.stdout)

    def test_a_legacy_trace_from_before_the_fix_is_still_readable(self):
        """A trace written by d7fbe00 has the raw character; the view must still read it."""
        code, _ = self.run_session([PASTED, PLAIN, "没人再复核", "有一次反而漏了"])
        self.assertEqual(0, code)
        trace = self.trace()
        rows = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
        legacy = "\n".join(json.dumps(row, ensure_ascii=False, separators=(",", ":"))
                           for row in rows) + "\n"
        self.assertTrue(any(c in legacy for c in LINE_BREAK_CODEPOINTS))
        legacy_dir = self.root / "legacy"
        legacy_dir.mkdir()
        old = legacy_dir / trace.name
        old.write_text(legacy, encoding="utf-8")
        shown = self.run_cli("transcript", str(old))
        self.assertEqual(0, shown.returncode, shown.stderr)
        self.assertIn(PASTED, shown.stdout)

    def test_resume_parses_the_same_trace(self):
        self.run_session([PASTED, PLAIN, "没人再复核", "有一次反而漏了"])
        resumed = self.run_cli(
            "discuss", "--resume", str(self.trace()),
            env={"DOJO_DB": str(self.root / "dojo.sqlite3")},
        )
        # No endpoint here, so the run stops after the local validation. What matters is
        # that it is *not* "无法续跑轨迹": the trace itself parsed.
        self.assertNotIn("无法续跑轨迹", resumed.stderr, resumed.stderr)
        self.assertNotIn("无法续跑轨迹", resumed.stdout, resumed.stdout)
        self.assertIn("未配置 DOJO_LLM_BASE_URL", resumed.stderr)

    def test_the_exporter_reads_it_too(self):
        self.run_session([PASTED, PLAIN, "没人再复核", "有一次反而漏了"])
        out = self.root / "export"
        done = subprocess.run(
            [sys.executable, "-B", str(ROOT / "scripts" / "dao_session.py"),
             "--trace", str(self.trace()), "--out", str(out),
             "--person", "p", "--sample", "strangers"],
            cwd=str(ROOT), text=True, capture_output=True, timeout=120, env=clean_env(),
        )
        # Not a parse failure: the exporter reads the record, sees the answer, and refuses
        # it by name. Before the codec the same file produced "trace JSON: 第 2 行格式错误"
        # (a broken trace) or, worse, a note whose fields parsed as something else
        # ("张力 p-T1 少了「方向」这一格" about a sentence that was in the file).
        self.assertNotIn("trace JSON", done.stderr, done.stderr)
        self.assertIn("情境", done.stderr)
        self.assertIn("U+2028", done.stderr)
        self.assertEqual(2, done.returncode)


if __name__ == "__main__":
    unittest.main()
