"""四句问法接进讨论：写在同意那一轮仍然立刻发生，之后才问，问不出来就不填。

这一支测的是「接进去之后纪律没丢」：同一个写入规则、同一份轨迹、没有表单；
以及一场提前结束的会话只留下实际收集的原话；收集不等于候选字段已锚定。
"""

import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dojo.discuss import _load_resume_trace, run_discuss
from dojo.elicit import QUESTIONS
from dojo.live import MAX_DISCUSS_USER_TURN_CHARS
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


PROPOSE = result("你描述的是：检查该谁做。", CONCLUSION)


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
            client=FakeClient(responses or [PROPOSE]),
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
        code, output = self.run_session(["讲一条做法", "/认可", *answers, "/附答 情境 张力 代价 失效"])
        self.assertEqual(0, code)
        events = self.elicitation_events()
        self.assertEqual(["情境", "张力", "代价", "失效"], [row["part"] for row in events])
        for row in events:
            self.assertIn(QUESTIONS[row["part"]]["ask"], output)
            # The row's `promoted` flag is written while the questions run, before
            # anything is on the card; the session summary is what says what landed.
            self.assertFalse(row["promoted"])
            self.assertTrue(row["collected"])
        end = self.elicitation_end()
        self.assertEqual(["情境", "张力", "代价", "失效"], end["promoted"])
        self.assertEqual(["情境", "张力", "代价", "失效"], end["collected"])
        self.assertEqual(4, end["turns"])
        self.assertEqual("系统的", end["authorship"])
        self.assertEqual("系统的（六件都是系统补的）", end["line"])

    def test_the_conclusion_is_written_at_the_accept_turn_before_any_question(self):
        seen = []

        def read_line(prompt):
            seen.append(prompt)
            if len(seen) == 1:
                return "讲一条做法"
            if len(seen) == 2:
                return "/认可"
            self.assertEqual(1, len(self.store.list_candidates()), "结论必须在问第一件之前就写进去")
            raise EOFError

        output = io.StringIO()
        code = run_discuss(self.store, client=FakeClient([PROPOSE]), read_line=read_line, output=output)
        self.assertEqual(0, code)
        self.assertEqual(1, len(self.store.list_candidates()))
        self.assertIn(QUESTIONS["情境"]["ask"], output.getvalue())

    def test_the_person_is_told_the_shape_before_the_first_question(self):
        """`dojo-d-002`: shape first (including when it stops), then the details.

        Measured at the entry a person actually meets, not asserted about a constant:
        the block shown immediately before the first question has to say how many
        parts there are and when the asking stops. Before this, a person met four
        questions with no statement of either -- leaving was the only way to learn
        when it ended, which is the cost the lesson names.
        """
        code, output = self.run_session(
            ["讲一条做法", "/认可", "那天我手上是三件没做完的事", "", "", "", "", ""])
        self.assertEqual(0, code)
        text = output
        first_q = text.find(QUESTIONS["情境"]["ask"])
        self.assertGreaterEqual(first_q, 0, "the first question was never asked")
        head = text[:first_q]
        # `head` ends at the marker that introduces the question, so the block is
        # what sits between the marker before that one and this one.
        end = head.rfind("主持人> ")
        start = head.rfind("主持人> ", 0, end)
        block = head[start + len("主持人> "):end]
        self.assertIn("四件事", block, "the shape does not say how many parts there are")
        self.assertIn("两轮", block, "the shape does not say when the asking stops")
        self.assertIn("跳过", block,
                      "the shape does not say what happens to a part he cannot answer")
        self.assertIn("结束输入", block, "the shape does not say how to stop")
        # The block must not promise a label the entry cannot produce. Every part is
        # recorded `系统补` even when he answers all four (see
        # test_a_written_rule_is_followed_by_the_four_questions_in_order), so an
        # earlier draft of this block saying the entry would read 合写 told the reader
        # something the product never does.
        self.assertNotIn("合写", block,
                         "the shape promises 合写, which this entry never records")

    def test_the_shape_promises_exactly_the_authorship_the_entry_records(self):
        """The block's sentence about authorship has to be true at the end of a session."""
        answers = ["上次是把一套检查交给别人的时候", "检查的活搬走了，我自己判断少了",
                   "第一次觉得亏是没人再复核", "有一次我照着做反而漏了"]
        code, output = self.run_session(["讲一条做法", "/认可", *answers])
        self.assertEqual(0, code)
        end = self.elicitation_end()
        self.assertEqual("系统的", end["authorship"])
        first_q = output.find(QUESTIONS["情境"]["ask"])
        head = output[:first_q]
        marker = head.rfind("主持人> ")
        block = head[head.rfind("主持人> ", 0, marker) + len("主持人> "):marker]
        # The block must match the record in plain words: his answers are kept and now
        # attached to the card, while the sentence and its conditions stay the system's.
        # `part_sources` still reads 系统补 for all four, because promotion writes a
        # separate row and does not put his words into a field.
        self.assertIn("仍算我写的", block,
                      "the block does not say who the card credits")
        self.assertEqual("系统补", end["part_sources"]["situation"],
                         "the field is still the system's, however the answer is kept")
        # The block's other half: "你答的原话会留在本场记录里". Every one of his
        # answers has to be in the trace word for word, or that sentence is false too.
        events = self.elicitation_events()
        self.assertEqual(answers, [row["answer"] for row in events])
        self.assertNotIn("合写", block,
                         "the block promises 合写, which this entry never records")

    def test_the_shape_says_what_happens_only_when_the_session_keeps_a_trace(self):
        """With --no-trace the opening says nothing is kept; the block must agree."""
        answers = ["上次是把一套检查交给别人的时候", "检查的活搬走了，我自己判断少了"]
        output = io.StringIO()
        code = run_discuss(
            self.store,
            client=FakeClient([PROPOSE]),
            read_line=read_lines(["讲一条做法", "/认可", *answers, "", "", "", "", ""]),
            output=output,
            no_trace=True,
        )
        self.assertEqual(0, code)
        text = output.getvalue()
        self.assertIn("会话原文轨迹已关闭", text)
        block = None
        first_q = text.find(QUESTIONS["情境"]["ask"])
        if first_q > 0:
            head = text[:first_q]
            marker = head.rfind("主持人> ")
            block = head[head.rfind("主持人> ", 0, marker) + len("主持人> "):marker]
        self.assertIsNotNone(block, "the shape was never printed")
        self.assertNotIn("会留在本场记录", block,
                         "the shape promises retention in a session that keeps no trace")
        self.assertIn("不保存会话原文", block,
                      "the shape does not say the transcript is off")
        # And it no longer claims more than it can: the accepted card is still kept, which
        # review measured (`show` returned the opening sentence verbatim under --no-trace).
        self.assertIn("卡片仍会像平常一样留在库里", block,
                      "the shape does not say what is still kept")

    def test_an_early_end_leaves_exactly_the_parts_it_should(self):
        code, _ = self.run_session(["讲一条做法", "/认可", "上次是把一套检查交给别人的时候", "检查的活搬走了，我自己判断少了"])
        self.assertEqual(0, code)
        end = self.elicitation_end()
        # EOF retains the two answers in the trace but authorizes no attachment.
        self.assertEqual([], end["promoted"])
        self.assertEqual({}, end["answers_attached"])
        self.assertEqual(["情境", "张力"], end["collected"])
        self.assertEqual([], end["supplied"])
        self.assertEqual(3, end["turns"])  # 情境 1 轮、张力 1 轮、代价第 1 轮就 EOF
        self.assertEqual("系统补", end["part_sources"]["situation"])
        self.assertEqual("系统补", end["part_sources"]["tension"])
        self.assertEqual("系统补", end["part_sources"]["price"])
        self.assertEqual("系统补", end["part_sources"]["off"])
        self.assertEqual("系统的", end["authorship"])
        self.assertEqual(set(end["part_sources"]), set(end["unanchored"]))

    def test_card_edit_between_preview_and_choice_refuses_attachment(self):
        output = io.StringIO()
        inputs = read_lines(["讲一条做法", "/认可", "上次是这样", "跳过", "跳过", "跳过",
                             "/附答 情境"])

        def read_line(prompt):
            line = inputs(prompt)
            if line == "/附答 情境":
                self.assertIn("附答核对", output.getvalue())
                ident = self.store.list_candidates()[0]["id"]
                editor = Store(self.store.path)
                try:
                    editor.revise(ident, "从另一处同时改成了一条别的说法。", "另一个终端编辑")
                finally:
                    editor.close()
            return line

        self.assertEqual(0, run_discuss(self.store, client=FakeClient([PROPOSE]),
                                       read_line=read_line, output=output))
        self.assertIn("卡片已不是问答针对的那一版", output.getvalue())
        self.assertEqual([], self.elicitation_end()["promoted"])
        ident = self.store.list_candidates()[0]["id"]
        self.assertEqual({}, self.store.answers_for(ident))

    def test_nothing_is_filled_when_the_person_answers_nothing(self):
        code, _ = self.run_session(["讲一条做法", "/认可", "", "", "", "", "", "", "", ""])
        self.assertEqual(0, code)
        end = self.elicitation_end()
        self.assertEqual([], end["promoted"])
        self.assertEqual(["情境", "张力", "代价", "失效"], end["supplied"])
        self.assertEqual(8, end["turns"])
        self.assertEqual("系统的", end["authorship"])
        self.assertEqual(1, len(self.store.list_candidates()), "问不出来时也不能多出一条结论")

    def test_each_part_records_the_question_and_raw_answer_without_promotion(self):
        code, _ = self.run_session(["讲一条做法", "/认可", "上次是把一套检查交给别人的时候", "", "", "", "", "", ""])
        self.assertEqual(0, code)
        events = self.elicitation_events()
        first = events[0]
        self.assertEqual("情境", first["part"])
        self.assertEqual("situation", first["field"])
        self.assertEqual(1, first["turn"])
        self.assertEqual(QUESTIONS["情境"]["ask"], first["question"])
        self.assertEqual("上次是把一套检查交给别人的时候", first["answer"])
        self.assertFalse(first["promoted"])
        self.assertTrue(first["collected"])
        follow_up = [row for row in events if row["part"] == "张力" and row["turn"] == 2][0]
        self.assertEqual(QUESTIONS["张力"]["follow_ups"]["none"], follow_up["question"])
        self.assertFalse(follow_up["promoted"])

    def test_structured_input_is_not_a_way_to_answer(self):
        code, output = self.run_session(["讲一条做法", "/认可", "1", "", "", "", "", "", ""])
        self.assertEqual(0, code)
        self.assertIn("用一句话说就行；这里不填表。", output)
        first = self.elicitation_events()[0]
        self.assertFalse(first["promoted"])
        self.assertEqual("none", first["reading"])

    def test_no_forms_no_counters_no_options_in_the_questions(self):
        code, output = self.run_session(["讲一条做法", "/认可", "上次是这样", "少了判断", "耽误了时间", "有一次反着做"])
        self.assertEqual(0, code)
        for forbidden in ("1/4", "（1/", "2/4", "y/n", "第 1 件", "请选择", "选项"):
            self.assertNotIn(forbidden, output)

    def test_a_resumed_trace_knows_the_questions_already_ran(self):
        self.run_session(["讲一条做法", "/认可", "上次是这样", "少了判断", "", "", "", "", ""])
        path = next((self.root / "sessions").glob("*.jsonl"))
        state = _load_resume_trace(path)
        self.assertTrue(state["elicitation_done"])
        self.assertEqual([], state["elicitation_promoted"])
        self.assertEqual(["情境", "张力"], state["elicitation_collected"])

    def test_unrelated_and_useful_answers_are_collected_not_candidate_sources(self):
        answers = [
            "  今天晚饭吃面条，与这个问题完全无关。  ",
            "要么把持续检查交给系统，要么留住自己每次判断的机会，不能同时拿满。",
            "昨天上线时，我为了复核系统回执多花了半小时。",
            "上周系统拿不到现场数据时就该停，不能继续自动检查。",
        ]
        code, _ = self.run_session(["讲一条做法", "/认可", *answers, "/附答 情境 张力 代价 失效"])
        self.assertEqual(0, code)
        events = self.elicitation_events()
        self.assertEqual(answers, [event["answer"] for event in events])
        self.assertEqual(["situation", "tension", "price", "off"], [event["field"] for event in events])
        self.assertTrue(all(event["collected"] for event in events))
        # The per-row `promoted` flag keeps its old meaning and stays False: rows are
        # written while the questions run, before anything is on the card. What the card
        # carries is the session-level summary below.
        self.assertFalse(any(event["promoted"] for event in events))
        end = self.elicitation_end()
        # Premotion attaches the sentence; it still does not judge whether it fits the
        # part, which is why `part_sources` stays 系统补 even here -- one of these four
        # answers is about dinner.
        self.assertEqual(["情境", "张力", "代价", "失效"], end["promoted"])
        self.assertEqual(["情境", "张力", "代价", "失效"], end["collected"])
        self.assertTrue(all(source == "系统补" for source in end["part_sources"].values()))
        self.assertEqual("系统的", end["authorship"])
        candidate = self.store.show(end["entry"])["candidate"]
        self.assertEqual(CONCLUSION["statement"], candidate["statement"])
        self.assertTrue(all(source["type"] == "unknown" for source in candidate["sources"]))
        self.assertTrue(all(source["verification"] == "unknown" for source in candidate["sources"]))

    def test_bounded_raw_answer_is_not_silently_truncated_at_4000(self):
        answer = "  " + "经" * (MAX_DISCUSS_USER_TURN_CHARS - 4) + "  "
        self.assertLessEqual(len(answer), MAX_DISCUSS_USER_TURN_CHARS)
        self.run_session(["讲一条做法", "/认可", answer])
        event = self.elicitation_events()[0]
        self.assertEqual(answer, event["answer"])
        self.assertTrue(event["collected"])
        self.assertFalse(event["promoted"])

    def test_oversized_answer_is_explicitly_rejected_without_partial_collection(self):
        oversized = "超" * (MAX_DISCUSS_USER_TURN_CHARS + 1)
        code, output = self.run_session(["讲一条做法", "/认可", oversized, "一次有效长度的原话"])
        self.assertEqual(0, code)
        self.assertIn("未收录原文，也未截断保存", output)
        events = self.elicitation_events()
        rejected, collected = events[:2]
        self.assertIsNone(rejected["answer"])
        self.assertEqual("user_turn_too_large", rejected["error"])
        self.assertEqual(len(oversized), rejected["answer_chars"])
        self.assertFalse(rejected["collected"])
        self.assertFalse(rejected["promoted"])
        self.assertEqual("一次有效长度的原话", collected["answer"])
        self.assertEqual(2, collected["turn"])
        self.assertNotIn(oversized[:4000], json.dumps(self.trace(), ensure_ascii=False))

    def test_legacy_promotions_do_not_become_resumed_authorship_guarantees(self):
        self.run_session(["讲一条做法", "/认可", "今天晚饭吃面条，与这个问题完全无关。"])
        path = next((self.root / "sessions").glob("*.jsonl"))
        records = self.trace()
        for row in records:
            if row.get("event") == "elicitation":
                row.pop("collected", None)
                row["promoted"] = row["reading"] == "answer"
            if row.get("event") == "session_end":
                summary = row["elicitation"]
                summary.pop("collected", None)
                summary["promoted"] = ["情境", "张力", "代价", "失效"]
                summary["part_sources"] = {key: "他的原话" for key in summary["part_sources"]}
                summary["authorship"] = "他的"
        path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records), encoding="utf-8")
        original_bytes = path.read_bytes()
        state = _load_resume_trace(path)
        self.assertEqual(original_bytes, path.read_bytes())
        self.assertTrue(state["elicitation_done"])
        self.assertEqual([], state["elicitation_promoted"])
        self.assertEqual(["情境"], state["elicitation_collected"])
        output = io.StringIO()
        self.assertEqual(0, run_discuss(
            self.store, client=FakeClient([]), resume=path,
            read_line=read_lines([]), output=output,
        ))
        self.assertNotIn(QUESTIONS["情境"]["ask"], output.getvalue())
        self.assertTrue(path.read_bytes().startswith(original_bytes))
        end = self.elicitation_end()
        self.assertEqual([], end["promoted"])
        self.assertEqual(["情境"], end["collected"])
        self.assertEqual("系统的", end["authorship"])
        self.assertTrue(all(source == "系统补" for source in end["part_sources"].values()))

    def test_the_accepting_line_s_moment_reaches_the_ledger(self):
        """r1638: the live conversation also states *when* it was agreed, not just when written.

        The local acceptance turn captures when the line arrived, which is distinct
        from when the ledger records it. The clock is driven here so the
        two facts are forced apart -- inside one second they would compare equal and the
        test could not tell "used the arrival" from "used the write time".
        """
        from unittest.mock import patch

        ticks = iter(range(200))
        base = datetime(2026, 10, 17, 22, 52, 0, tzinfo=timezone.utc)
        real = datetime

        class Clock(real):
            @classmethod
            def now(cls, tz=None):
                return base + timedelta(seconds=10 * next(ticks))

        output = io.StringIO()
        with patch("dojo.discuss.datetime", Clock), patch("dojo.storage.datetime", Clock):
            code = run_discuss(
                self.store, client=FakeClient([PROPOSE]), read_line=read_lines(["讲一条做法", "/认可"]),
                output=output, environ={}, no_profile=True,
            )
        self.assertEqual(0, code)
        card = self.store.list_candidates()[0]["id"]
        event = [e for e in self.store.history(card)["events"] if e["event"] == "wording_accepted"][-1]
        self.assertIn("agreed_at", event["details"],
                      "the conversation route must state the moment it agreed, not only when it wrote")
        agreed = event["details"]["agreed_at"]
        basis = self.store.time_basis(card)
        self.assertEqual(agreed, basis["agreed_at"])
        # The discriminating fact is the order, not a particular tick: a writer that
        # stamped the write time would have produced two equal strings, which is exactly
        # the state this test has to be able to call out. Both values are ticks of the
        # driven clock, so the comparison is on a clock this test owns.
        self.assertLess(agreed, basis["accepted_at"],
                        "the local acceptance arrived before the write")
        self.assertEqual(0, (datetime.fromisoformat(agreed) - base).seconds % 10,
                         "the moment came from this test's clock, not the host's")

    def test_legacy_event_promotions_without_summary_are_also_untrusted(self):
        self.run_session(["讲一条做法", "/认可", "真实的回答材料"])
        path = next((self.root / "sessions").glob("*.jsonl"))
        records = self.trace()
        for row in records:
            if row.get("event") == "session_end":
                row.pop("elicitation", None)
            elif row.get("event") == "elicitation":
                row.pop("collected", None)
                row["promoted"] = row["reading"] == "answer"
        path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records), encoding="utf-8")
        state = _load_resume_trace(path)
        self.assertEqual([], state["elicitation_promoted"])
        self.assertEqual(["情境"], state["elicitation_collected"])


if __name__ == "__main__":
    unittest.main()
