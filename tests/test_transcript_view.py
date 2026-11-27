"""The one place the receipt's promise about kept words can be acted on.

Before this slice the receipt said his words stay in the session record, and the only way
to read them was to open a JSONL and decode it. `--resume` restores the session; it prints
none of the words. So the promise was about the disk, not about anything he could use --
the same defect as "原话在上面" pointing at a line the screen never printed, one layer out.

What these tests refuse to accept:

  silent      the receipt says the words are kept and names no way to see them
  made-up     the named command being refused, or reading something else
  consent     the view turning collected material into "he answered it" / "he endorsed it"
  blind tail  a record that stopped mid-write being reported as a session without a card
  side effect a read that opens a library, writes a byte, or creates a file
"""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from dojo import transcript as transcript_module
from dojo.discuss import run_discuss
from dojo.storage import Store

CONCLUSION = {
    "statement": "把持续检查交给系统，人这一侧只保留随时可以推翻的位置。",
    "kind": "abstract_idea",
    "scope": ["一个人已经抽身、只在自己想推翻时回来时"],
    "premises": ["系统能自己跑检查"],
    "alternatives": ["把检查留给人"],
    "contradictions": ["检查必须发生在世界里时"],
    "unknowns": ["他自己会不会来看回执"],
}

OFF_SITUATION = "我觉得这里关键是通知得做好，不然谁都不知道系统跑完了没有。"
ON_TENSION = "照这个做，我那种先自己看一遍的习惯就没机会用了，那是我挺看重的一件好事。"
OFF_PRICE = "这个方案对工程师是好事，反正工程师本来就该多写点自动化。"
OFF_OFF = "每个团队都不一样，有的团队特别需要这个，有的完全不需要。"


def result(answer, candidate=None, user_stance="neutral"):
    return {"answer": answer, "candidate": candidate, "user_stance": user_stance}


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


PROPOSE = result("那我们把这句当成现在这一版。", CONCLUSION)
ACCEPT = result("好，就这句。", CONCLUSION, user_stance="accept")
ANSWERS = ["讲一条做法", "对，就这么定", OFF_SITUATION, ON_TENSION, OFF_PRICE, OFF_OFF]


class TranscriptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "dojo.sqlite3")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    # ---- helpers ----------------------------------------------------------------

    def run_session(self, answers=None, *, no_trace=False):
        output = io.StringIO()
        code = run_discuss(
            self.store,
            client=FakeClient([PROPOSE, ACCEPT]),
            read_line=read_lines(list(answers or ANSWERS)),
            output=output,
            no_trace=no_trace,
        )
        return code, output.getvalue()

    def trace(self):
        paths = sorted((self.root / "sessions").glob("*.jsonl"))
        self.assertTrue(paths, "the session should leave a trace")
        return paths[-1]

    def closing_line(self, text):
        for line in text.splitlines():
            if not line.startswith("主持人> "):
                continue
            body = line[len("主持人> "):]
            if body.startswith(("四件问完了", "问到这里停了")):
                return body
        return None

    def named_command(self, line):
        marker = "运行："
        self.assertIn(marker, line, line)
        command = line.split(marker, 1)[1].split("（", 1)[0].strip()
        return command

    def run_cli(self, *args, env=None):
        environ = {k: v for k, v in os.environ.items() if not k.startswith("DOJO_")}
        environ["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
        environ["PYTHONDONTWRITEBYTECODE"] = "1"
        environ.update(env or {})
        return subprocess.run([sys.executable, "-B", "-m", "dojo", *args],
                              cwd=str(Path(__file__).resolve().parents[1]),
                              env=environ, input="", text=True,
                              capture_output=True, timeout=180)

    # ---- the promise can be acted on -------------------------------------------

    def test_the_receipt_names_a_command_and_that_command_shows_his_words(self):
        code, text = self.run_session()
        self.assertEqual(0, code)
        line = self.closing_line(text)
        self.assertIsNotNone(line)
        self.assertIn("留在本场记录里", line)
        command = self.named_command(line)
        self.assertTrue(command.startswith("python3 -m dojo transcript "), command)
        self.assertIn(str(self.trace()), command)

        # The command the receipt printed, run as printed.
        done = self.run_cli(*command.split()[3:])
        self.assertEqual(0, done.returncode, done.stderr)
        for words in (OFF_SITUATION, ON_TENSION, OFF_PRICE, OFF_OFF):
            self.assertIn(words, done.stdout)
        # The questions are next to the words: "what did it ask" is half of reading back.
        self.assertIn("什么时候你会这么做", done.stdout)
        self.assertIn("照着这条做", done.stdout)

    def test_the_receipt_prints_no_path_when_there_is_no_record(self):
        code, text = self.run_session(no_trace=True)
        self.assertEqual(0, code)
        line = self.closing_line(text)
        self.assertIn("这场不留原文", line)
        self.assertNotIn("transcript", line)
        self.assertEqual([], sorted((self.root / "sessions").glob("*.jsonl")))

    def test_a_record_that_died_mid_write_points_at_what_was_written(self):
        """The words before the failure are on disk, so naming the view is still true."""
        from dojo import discuss as discuss_module

        real = discuss_module._SessionTrace.append
        calls = {"n": 0}

        def dying(self, value):
            calls["n"] += 1
            if calls["n"] >= 2:
                self._warn(OSError("no space left on device"))
                return
            real(self, value)

        discuss_module._SessionTrace.append = dying
        try:
            code, text = self.run_session()
        finally:
            discuss_module._SessionTrace.append = real
        self.assertEqual(0, code)
        line = self.closing_line(text)
        self.assertIn("轨迹中途写入失败", line)
        # Naming a file that holds the first part and saying the rest did not land are
        # both true; what is refused is pretending the whole session is in there.
        command = self.named_command(line)
        done = self.run_cli(*command.split()[3:])
        self.assertEqual(0, done.returncode, done.stderr)
        self.assertIn("你说：讲一条做法", done.stdout)

    # ---- the view's own honesty ------------------------------------------------

    def test_the_view_calls_collected_words_material_not_consent(self):
        self.run_session()
        shown = transcript_module.load_and_render(self.trace())
        self.assertIn("材料，不是结论", shown)
        disclaimer = "回看只说你说过什么，不判哪句答到了点上，也不代表你认可了哪条结论。"
        self.assertIn(disclaimer, shown)
        # Everything above the disclaimer is facts about the record. No line in it may
        # claim the question was answered or turn collected material into agreement;
        # `收作原话` is the trace's own word and stays that word.
        body = shown.split(disclaimer)[0]
        for claim in ("你答了", "答到了", "你认可", "已认可", "同意"):
            self.assertNotIn(claim, body, claim)
        self.assertEqual(4, shown.count("收作原话"))

    def test_a_truncated_record_is_not_read_as_a_session_without_a_card(self):
        """The row that would say "no card" is the row that never got written."""
        self.run_session()
        trace = self.trace()
        rows = trace.read_text(encoding="utf-8").splitlines(keepends=True)
        cut_dir = self.root / "cut"
        cut_dir.mkdir()
        cut = cut_dir / trace.name
        cut.write_text("".join(rows[:3]) + rows[3][:15], encoding="utf-8")

        view = transcript_module.load(cut)
        self.assertTrue(view["partial_tail"])
        shown = transcript_module.render(view)
        self.assertIn("最后一行只写了一半", shown)
        self.assertIn("看不出这一场有没有写下卡片", shown)
        self.assertNotIn("这一场没有写下卡片", shown)
        # And it does not offer a resume command that `--resume` would refuse.
        self.assertNotIn("discuss --resume", shown)
        self.assertIn("不能接着谈", shown)
        refused = self.run_cli("discuss", "--resume", str(cut))
        self.assertEqual(2, refused.returncode)

    def test_a_part_taken_back_shows_what_the_session_ended_with(self):
        """Undo is a row. The view reports the last one, not the first."""
        self.run_session()
        trace = self.trace()
        rows = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
        kept = [row for row in rows if row.get("event") != "elicitation"]
        first = {
            "event": "elicitation", "part": "情境", "field": "situation", "turn": 1,
            "question": "问的是情境", "answer": "先答的一句", "promoted": False,
            "collected": True, "reading": "answer", "at": "2026-11-28T00:00:00+00:00",
        }
        undo = dict(first, turn=1, answer="改回上一题", reading="undo", collected=False,
                    at="2026-11-28T00:00:01+00:00")
        again = dict(first, turn=1, answer="后来认真答的一句", reading="answer",
                     at="2026-11-28T00:00:02+00:00")
        craft = self.root / "craft"
        craft.mkdir()
        forged = craft / trace.name
        forged.write_text("\n".join(json.dumps(row, ensure_ascii=False)
                                    for row in [*kept, first, undo, again]) + "\n",
                          encoding="utf-8")
        shown = transcript_module.render(transcript_module.load(forged))
        self.assertIn("后来认真答的一句", shown)
        self.assertNotIn("先答的一句", shown)
        self.assertIn("问过不止一轮", shown)

    def test_reading_it_changes_nothing(self):
        self.run_session()
        trace = self.trace()
        before = trace.read_bytes()
        listing = sorted(p.name for p in trace.parent.iterdir())
        self.run_cli("transcript", str(trace))
        self.run_cli("transcript", str(trace), "--json")
        self.assertEqual(before, trace.read_bytes())
        self.assertEqual(listing, sorted(p.name for p in trace.parent.iterdir()))

    def test_it_opens_no_library(self):
        """A reader looking back may be on a machine where the library has moved."""
        self.run_session()
        store_path = self.root / "elsewhere.sqlite3"
        done = self.run_cli("transcript", str(self.trace()),
                            env={"DOJO_DB": str(store_path)})
        self.assertEqual(0, done.returncode, done.stderr)
        self.assertFalse(store_path.exists(), "a read created a library")

    def test_something_that_is_not_a_trace_is_refused_locally(self):
        junk = self.root / "junk.jsonl"
        junk.write_text('{"hello": "world"}\n', encoding="utf-8")
        done = self.run_cli("transcript", str(junk))
        self.assertEqual(2, done.returncode)
        self.assertIn("无法回看", done.stderr)
        self.assertNotIn("Traceback", done.stderr)
        missing = self.run_cli("transcript", str(self.root / "nope.jsonl"))
        self.assertEqual(2, missing.returncode)
        self.assertIn("无法回看", missing.stderr)

    def test_json_output_carries_the_same_facts(self):
        self.run_session()
        done = self.run_cli("transcript", str(self.trace()), "--json")
        self.assertEqual(0, done.returncode, done.stderr)
        payload = json.loads(done.stdout)
        self.assertEqual(4, len(payload["parts"]))
        self.assertEqual({"情境", "张力", "代价", "失效"},
                         {part["part"] for part in payload["parts"]})
        self.assertIs(False, payload["partial_tail"])
        self.assertEqual("eof", payload["ended"])
        self.assertTrue(payload["saved"])
        for part in payload["parts"]:
            self.assertIn("said", part)
            self.assertIn("question", part)


class TheFrontPagesShowTheReadBack(unittest.TestCase):
    """A first-time reader has to find it where the receipt sends them: the front page."""

    def pages(self):
        root = Path(__file__).resolve().parents[1]
        return [(root / name).read_text(encoding="utf-8")
                for name in ("README.md", "README.zh-CN.md")]

    def test_both_pages_show_a_copyable_transcript_command(self):
        for text in self.pages():
            lines = [line for line in text.splitlines()
                     if "python3 -m dojo transcript" in line
                     and not line.lstrip().startswith("#")]
            self.assertTrue(lines, "a front page never shows `dojo transcript` on a line "
                                   "a reader can copy")

    def test_both_pages_say_what_the_view_does_not_claim(self):
        for text in self.pages():
            self.assertTrue("材料，不是结论" in text or "material, not a conclusion" in text,
                            "a front page never says the words are material, not a verdict")


if __name__ == "__main__":
    unittest.main()
