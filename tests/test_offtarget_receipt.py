"""An answer that is substantive but off the question: what may the receipt claim?

The earlier slices made the receipt name what happened to each part, and the word for
"he wrote something" was 你答了 -- "you answered it". A run with realistic off-target
answers showed that word asserting something the program never checked:

    情境 asked "那天你手上是什么事" -> "我觉得这里关键是通知得做好"
    代价 asked "谁要多花时间、谁会不高兴" -> "对工程师是好事"
    失效 asked "有没有一次结果反而不对"   -> "每个团队都不一样"

All three are real material, all three miss the question, and the receipt said
四件你都答了. `classify_answer` only separates empty / declared-non-answer / skip /
wind-down / form-like from an attempt; whether the words fill the part is `to_fill`,
judged by a reader, and the session is not that reader.

These tests pin the three things that have to hold at once, or the word is a lie in one
direction or the other:

  kept      the words are kept verbatim, so "he said something real" is still true
  not-hit   the receipt does not say the question was answered, and says so on screen
  not-card  the words never reach the card or the confirm state

They run the real `run_discuss`, and read the trace next to the screen for the reason
this whole line of work exists: the two came apart before and the screen lied.
"""
import io
import json
import tempfile
import unittest
from pathlib import Path

from dojo.discuss import closing_text, run_discuss
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

# Substantive, first-person, and off the question that was asked.
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


class OffTargetAnswerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "dojo.sqlite3")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def run_session(self, answers):
        output = io.StringIO()
        code = run_discuss(
            self.store,
            client=FakeClient([PROPOSE, ACCEPT]),
            read_line=read_lines(["讲一条做法", "对，就这么定", *answers]),
            output=output,
        )
        return code, output.getvalue()

    def trace_rows(self):
        paths = sorted((self.root / "sessions").glob("*.jsonl"))
        self.assertTrue(paths, "本场应当留下轨迹")
        return [json.loads(line) for line in paths[-1].read_text(encoding="utf-8").splitlines()]

    def closing_line(self, text):
        for line in text.splitlines():
            if not line.startswith("主持人> "):
                continue
            body = line[len("主持人> "):]
            if body.startswith(("四件问完了", "问到这里停了")):
                return body
        return None

    # ---- the three facts ---------------------------------------------------------

    def test_the_words_are_kept_verbatim_even_when_they_miss(self):
        code, _ = self.run_session([OFF_SITUATION, ON_TENSION, OFF_PRICE, OFF_OFF])
        self.assertEqual(0, code)
        rows = {row["part"]: row for row in self.trace_rows()
                if row.get("event") == "elicitation" and row.get("turn") == 1}
        for part, words in (("情境", OFF_SITUATION), ("代价", OFF_PRICE), ("失效", OFF_OFF)):
            self.assertEqual("answer", rows[part]["reading"], part)
            self.assertIs(True, rows[part]["collected"], part)
            # Kept whole, not summarised or trimmed: the material is his.
            self.assertEqual(words, rows[part]["answer"], part)

    def test_the_receipt_does_not_say_the_questions_were_answered(self):
        # Two shapes, because the wording has two branches and a test of only the
        # all-four one let the per-part word regress silently (arm A stayed green).
        for answers, extra in (
            ([OFF_SITUATION, ON_TENSION, OFF_PRICE, OFF_OFF], None),
            (["先跳过这一题", ON_TENSION, OFF_PRICE, OFF_OFF], "你说跳过 情境"),
        ):
            with self.subTest(answers=answers):
                code, text = self.run_session(answers)
                self.assertEqual(0, code)
                line = self.closing_line(text)
                self.assertIsNotNone(line)
                # The bucket is named for what is true: his words were kept.
                self.assertIn("说了原话", line)
                # And not for the thing that was never checked.
                self.assertNotIn("你答了", line)
                self.assertNotIn("四件你都答了", line)
                if extra:
                    self.assertIn(extra, line)

    def test_the_receipt_says_on_screen_that_it_does_not_judge_the_fit(self):
        """The omission was the defect: the word asserted a judgement silently."""
        code, text = self.run_session([OFF_SITUATION, ON_TENSION, OFF_PRICE, OFF_OFF])
        self.assertEqual(0, code)
        line = self.closing_line(text)
        self.assertIn("答没答到点上，这句不判", line)
        # And it points at where the words actually are, so the person can judge.
        self.assertIn("原话在上面", line)

    def test_the_words_do_not_reach_the_card(self):
        code, text = self.run_session([OFF_SITUATION, ON_TENSION, OFF_PRICE, OFF_OFF])
        self.assertEqual(0, code)
        line = self.closing_line(text)
        self.assertIn("没有写进卡片", line)
        # The card holds the sentence it was written with, and the confirm kept its
        # own basis -- neither absorbed the answers.
        saved = [row for row in self.trace_rows() if row.get("event") == "session_end"][-1]
        self.assertTrue(saved["saved"], "这场应当写下了结论")
        shown = self.store.show(saved["saved"][0])
        self.assertEqual(CONCLUSION["statement"], shown["candidate"]["statement"])
        self.assertNotIn(OFF_PRICE, json.dumps(shown, ensure_ascii=False))

    # ---- the word must not swing the other way ----------------------------------

    def test_a_part_that_was_not_answered_does_not_get_this_word(self):
        """Against over-tightening: skip / blank must keep their own words."""
        # skip 情境; 张力 blank on both turns; 代价 answered; 失效 EOF.
        code, text = self.run_session(["先跳过这一题", "", "",
                                       "有一次我照着做反而漏了"])
        self.assertEqual(0, code)
        line = self.closing_line(text)
        self.assertIn("你说跳过 情境", line)
        self.assertIn("没答出来 张力", line)
        # The part that was really answered is named; the skipped one is not.
        self.assertIn("你在 代价 上说了原话", line)
        self.assertNotIn("情境 上说了原话", line)

    def test_the_judgement_line_is_absent_when_nothing_was_said(self):
        code, text = self.run_session(("",) * 8)
        self.assertEqual(0, code)
        line = self.closing_line(text)
        self.assertIn("没答出来", line)
        # Nothing was said, so there is no fit to decline judging, and saying so would
        # be about nothing.
        self.assertNotIn("答没答到点上", line)
        self.assertNotIn("说了原话", line)

    # ---- the pure function keeps the same contract -------------------------------

    def test_the_pure_function_separates_kept_from_answered(self):
        line = closing_text(["情境", "失效"], ["张力"], ["代价"])
        self.assertIn("你在 情境、失效 上说了原话", line)
        self.assertIn("答没答到点上", line)
        self.assertNotIn("你答了", line)

    def test_the_all_four_short_form_does_not_say_answered(self):
        line = closing_text(list(("情境", "张力", "代价", "失效")), [], [])
        self.assertIn("四件你都说了原话", line)
        self.assertNotIn("四件你都答了", line)

    def test_a_no_trace_session_still_says_where_the_words_did_not_go(self):
        output = io.StringIO()
        code = run_discuss(
            self.store,
            client=FakeClient([PROPOSE, ACCEPT]),
            read_line=read_lines(["讲一条做法", "对，就这么定", OFF_SITUATION,
                                  ON_TENSION, OFF_PRICE, OFF_OFF]),
            output=output,
            no_trace=True,
        )
        self.assertEqual(0, code)
        line = self.closing_line(output.getvalue())
        self.assertIn("这场不留原文", line)
        self.assertNotIn("留在本场记录", line)
        # Saying "look at the words above" is still true -- they were in this dialogue.
        self.assertIn("答没答到点上", line)


if __name__ == "__main__":
    unittest.main()
