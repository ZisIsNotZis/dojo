"""四件问完之后，屏幕上有没有一句说「哪几件是你说过的」。

测的是真入口 `run_discuss` 的屏幕输出，不是常量：一场四件全答、一场四件全跳过，
再加一场答两件跳过两件，三种情况下这一句都必须与轨迹里的 `collected`/`supplied` 一致。
`--no-trace` 下同样成立——这一句讲的是本场会话里发生过什么，不是磁盘上留了什么。
"""

import io
import json
import tempfile
import unittest
from pathlib import Path

from dojo.discuss import closing_text, run_discuss
from dojo.elicit import PART_ORDER
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

ALL_FOUR = ("上次是把一套检查交给别人的时候", "检查的活搬走了，我自己判断少了",
            "第一次觉得亏是没人再复核", "有一次我照着做反而漏了")


def result(answer, candidate=None, user_stance="neutral"):
    return {"answer": answer, "candidate": candidate, "user_stance": user_stance}


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)

    def complete(self, messages):
        return self.responses.pop(0)


def read_lines(lines):
    iterator = iter(lines)

    def read_line(prompt):
        try:
            return next(iterator)
        except StopIteration:
            raise EOFError
    return read_line


TWO_TURNS = [
    result("你描述的是：检查该谁做。", CONCLUSION),
    result("那我们把它写成这一条。", CONCLUSION, user_stance="accept"),
]


class ClosingLineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "dojo.sqlite3")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def run_session(self, answers, no_trace=False):
        output = io.StringIO()
        code = run_discuss(
            self.store,
            client=FakeClient(TWO_TURNS),
            read_line=read_lines(["讲一条做法", "对", *answers, "", "", "", "", ""]),
            output=output,
            no_trace=no_trace,
        )
        return code, output.getvalue()

    def recorded(self):
        """The session_end reading, when a trace exists."""
        sessions = sorted((self.root / "sessions").glob("*.jsonl"))
        self.assertTrue(sessions, "本场应当留下轨迹")
        for line in sessions[-1].read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row.get("event") == "session_end":
                return row["elicitation"]
        return None

    def test_all_four_answered_says_so_and_matches_the_trace(self):
        code, text = self.run_session(ALL_FOUR)
        self.assertEqual(0, code)
        end = self.recorded()
        self.assertEqual(list(PART_ORDER), end["collected"])
        self.assertEqual([], end["supplied"])
        self.assertIn("四件都落在你说过的话上", text)
        # Not a bare claim: no part may be named as filled when the trace says otherwise.
        for part in PART_ORDER:
            self.assertNotIn(f"{part} 没说出来", text)

    def test_all_four_skipped_names_every_part_as_filled(self):
        code, text = self.run_session(("", "", "", ""))
        self.assertEqual(0, code)
        end = self.recorded()
        self.assertEqual([], end["collected"])
        self.assertEqual(list(PART_ORDER), end["supplied"])
        self.assertIn("四件都没说出来", text)
        self.assertIn("、".join(PART_ORDER), text)

    def test_two_answered_two_skipped_splits_them_the_way_the_trace_does(self):
        # A skipped part costs two lines (the ask and its follow-up), so 张力 and 失效
        # each get an empty pair. Getting this wrong silently shifts every later answer
        # onto the wrong part -- which is exactly what the first version of this test did.
        code, text = self.run_session(("上次是把一套检查交给别人的时候", "", "",
                                       "第一次觉得亏是没人再复核", "", ""))
        self.assertEqual(0, code)
        end = self.recorded()
        self.assertEqual(["情境", "代价"], end["collected"])
        self.assertEqual(["张力", "失效"], end["supplied"])
        self.assertIn("情境、代价 是你说过的", text)
        self.assertIn("张力、失效 没说出来", text)

    def test_the_line_comes_after_the_last_question_not_before_it(self):
        from dojo.elicit import QUESTIONS
        code, text = self.run_session(ALL_FOUR)
        self.assertEqual(0, code)
        last_part = PART_ORDER[-1]
        first_q = text.find(QUESTIONS[last_part]["ask"])
        self.assertGreater(first_q, -1)
        self.assertGreater(text.find("四件问完了"), first_q)

    def test_it_holds_with_the_trace_off(self):
        code, text = self.run_session(("上次是把一套检查交给别人的时候", "", "", ""), no_trace=True)
        self.assertEqual(0, code)
        # No trace to read, so the sentence must stand on the session's own lists.
        self.assertIn("四件问完了", text)
        self.assertIn("情境 是你说过的", text)

    def test_the_pure_function_says_nothing_it_cannot_support(self):
        self.assertEqual(
            "四件问完了：四件都落在你说过的话上。卡片上的字这一版仍全算我写的。",
            closing_text(list(PART_ORDER), []),
        )
        mixed = closing_text(["情境"], ["张力", "代价", "失效"])
        self.assertIn("情境 是你说过的", mixed)
        self.assertIn("张力、代价、失效 没说出来", mixed)
        # Order comes from PART_ORDER, not from however the lists were built.
        reordered = closing_text(["代价", "情境"], ["失效", "张力"])
        self.assertIn("情境、代价 是你说过的", reordered)
        self.assertIn("张力、失效 没说出来", reordered)


if __name__ == "__main__":
    unittest.main()
