"""四句问法接进讨论：写在同意那一轮仍然立刻发生，之后才问，问不出来就不填。

这一支测的是「接进去之后纪律没丢」：同一个写入规则、同一份轨迹、没有表单；
以及一场提前结束的会话只留下它该留下的那几件。
"""

import io
import json
import tempfile
import unittest
from pathlib import Path

from dojo.discuss import run_discuss
from dojo.elicit import QUESTIONS
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


def result(answer, candidate=None, user_stance="neutral"):
    return {"answer": answer, "candidate": candidate, "user_stance": user_stance}


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.messages = []

    def complete(self, messages):
        self.messages.append(messages)
        return self.responses.pop(0)


def read_lines(lines, seen=None):
    iterator = iter(lines)

    def read_line(prompt):
        try:
            value = next(iterator)
        except StopIteration:
            raise EOFError
        if seen is not None:
            seen.append(value)
        return value

    return read_line


TWO_TURNS = [
    result("你描述的是：检查该谁做。", CONCLUSION),
    result("那我们把它写成这一条。", CONCLUSION, user_stance="accept"),
]


class ElicitationLoopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "dojo.sqlite3")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def run_session(self, lines, responses=None):
        output = io.StringIO()
        code = run_discuss(
            self.store,
            client=FakeClient(responses or TWO_TURNS),
            read_line=read_lines(lines),
            output=output,
        )
        return code, output.getvalue()

    def trace(self):
        path = next((self.root / "sessions").glob("*.jsonl"))
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def elicitation_end(self):
        return [row for row in self.trace() if row.get("event") == "session_end"][-1]["elicitation"]

    def elicitation_events(self):
        return [row for row in self.trace() if row.get("event") == "elicitation"]

    def test_a_written_rule_is_followed_by_the_four_questions_in_order(self):
        answers = ["上次是把一套检查交给别人的时候", "检查的活搬走了，我自己判断少了", "第一次觉得亏是没人再复核", "有一次我照着做反而漏了"]
        code, output = self.run_session(["讲一条做法", "对", *answers])
        self.assertEqual(0, code)
        events = self.elicitation_events()
        self.assertEqual(["情境", "张力", "代价", "失效"], [row["part"] for row in events])
        for row in events:
            self.assertIn(QUESTIONS[row["part"]]["ask"], output)
            self.assertTrue(row["promoted"])
        end = self.elicitation_end()
        self.assertEqual(["情境", "张力", "代价", "失效"], end["promoted"])
        self.assertEqual(4, end["turns"])
        self.assertEqual("他的", end["authorship"])
        self.assertEqual("他的（六件都来自他这次说的）", end["line"])

    def test_the_conclusion_is_written_at_the_accept_turn_before_any_question(self):
        seen = []

        def read_line(prompt):
            seen.append(prompt)
            if len(seen) == 1:
                return "讲一条做法"
            if len(seen) == 2:
                return "对"
            self.assertEqual(1, len(self.store.list_candidates()), "结论必须在问第一件之前就写进去")
            raise EOFError

        output = io.StringIO()
        code = run_discuss(self.store, client=FakeClient(TWO_TURNS), read_line=read_line, output=output)
        self.assertEqual(0, code)
        self.assertEqual(1, len(self.store.list_candidates()))
        self.assertIn(QUESTIONS["情境"]["ask"], output.getvalue())

    def test_an_early_end_leaves_exactly_the_parts_it_should(self):
        code, _ = self.run_session(["讲一条做法", "对", "上次是把一套检查交给别人的时候", "检查的活搬走了，我自己判断少了"])
        self.assertEqual(0, code)
        end = self.elicitation_end()
        self.assertEqual(["情境", "张力"], end["promoted"])
        self.assertEqual([], end["supplied"])
        self.assertEqual(3, end["turns"])  # 情境 1 轮、张力 1 轮、代价第 1 轮就 EOF
        self.assertEqual("他的原话", end["part_sources"]["situation"])
        self.assertEqual("他的原话", end["part_sources"]["tension"])
        self.assertEqual("系统补", end["part_sources"]["price"])
        self.assertEqual("系统补", end["part_sources"]["off"])
        self.assertEqual("合写", end["authorship"])
        self.assertIn("系统补了 代价、失效", end["line"])

    def test_nothing_is_filled_when_the_person_answers_nothing(self):
        code, _ = self.run_session(["讲一条做法", "对", "", "", "", "", "", "", "", ""])
        self.assertEqual(0, code)
        end = self.elicitation_end()
        self.assertEqual([], end["promoted"])
        self.assertEqual(["情境", "张力", "代价", "失效"], end["supplied"])
        self.assertEqual(8, end["turns"])
        self.assertEqual("合写", end["authorship"])
        self.assertEqual(1, len(self.store.list_candidates()), "问不出来时也不能多出一条结论")

    def test_each_part_records_the_question_his_answer_and_the_promotion(self):
        code, _ = self.run_session(["讲一条做法", "对", "上次是把一套检查交给别人的时候", "", "", "", "", "", ""])
        self.assertEqual(0, code)
        events = self.elicitation_events()
        first = events[0]
        self.assertEqual("情境", first["part"])
        self.assertEqual(1, first["turn"])
        self.assertEqual(QUESTIONS["情境"]["ask"], first["question"])
        self.assertEqual("上次是把一套检查交给别人的时候", first["answer"])
        self.assertTrue(first["promoted"])
        follow_up = [row for row in events if row["part"] == "张力" and row["turn"] == 2][0]
        self.assertEqual(QUESTIONS["张力"]["follow_ups"]["none"], follow_up["question"])
        self.assertFalse(follow_up["promoted"])

    def test_structured_input_is_not_a_way_to_answer(self):
        code, output = self.run_session(["讲一条做法", "对", "1", "", "", "", "", "", ""])
        self.assertEqual(0, code)
        self.assertIn("用一句话说就行；这里不填表。", output)
        first = self.elicitation_events()[0]
        self.assertFalse(first["promoted"])
        self.assertEqual("none", first["reading"])

    def test_no_forms_no_counters_no_options_in_the_questions(self):
        code, output = self.run_session(["讲一条做法", "对", "上次是这样", "少了判断", "耽误了时间", "有一次反着做"])
        self.assertEqual(0, code)
        for forbidden in ("1/4", "（1/", "2/4", "y/n", "第 1 件", "请选择", "选项"):
            self.assertNotIn(forbidden, output)

    def test_a_resumed_trace_knows_the_questions_already_ran(self):
        from dojo.discuss import _load_resume_trace

        self.run_session(["讲一条做法", "对", "上次是这样", "少了判断", "", "", "", "", ""])
        path = next((self.root / "sessions").glob("*.jsonl"))
        state = _load_resume_trace(path)
        self.assertTrue(state["elicitation_done"])
        self.assertEqual(["情境", "张力"], state["elicitation_promoted"])


if __name__ == "__main__":
    unittest.main()
