"""「没遇到过」 and 「我不知道」 are different answers -- and neither fills 失效.

The supervisor walked the real CLI at 8524586 and reported it:

    问 失效：「有没有一次你这么做，结果反而不对？」
    答：「没有。」          -> 被当成没回答，改口问了另一个问题
    追问：「换成另一个人来用，你最担心哪一点？」
    答：「没遇到过。」      -> 被当成已经说清楚了失效

Two sentences with one meaning, opposite receipts. And the second one is worse than the
first: not having seen a counterexample is not a statement about when the rule stops
working, so collecting it as 失效's material would let a reader conclude "this never
fails" from "I have not seen it fail".

What has to hold, all at once:

  same meaning, same reading   「没有」/「没遇到过」/「没有过」 are one fact
  his words kept               the sentence goes on the row verbatim
  part not filled              it is not collected as material for 失效
  not a failure                it is not reported as 没答出来 either
  no re-ask                    the follow-up question is not put to him
  no deduction                 the receipt says the rule is not thereby shown unfailing
  the question decides          a bare 没有 means "no example" only where an example was
                               asked for; elsewhere it stays what it was
"""
import io
import json
import unittest
from pathlib import Path
import tempfile

from dojo.discuss import closing_text, elicitation_state, run_discuss
from dojo.elicit import PART_ORDER, classify_answer
from dojo.storage import Store

CONCLUSION = {
    "statement": "把持续检查交给系统，人这一侧只保留随时可以推翻的位置。",
    "kind": "abstract_idea", "scope": ["一个人已经抽身时"],
    "premises": ["系统能自己跑检查"], "alternatives": ["把检查留给人"],
    "contradictions": ["检查必须发生在世界里时"], "unknowns": ["他会不会来看回执"],
}


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


class TheReading(unittest.TestCase):
    def test_the_three_ways_of_saying_it_are_one_reading(self):
        for phrase in ("没有", "没有。", "没遇到过", "没遇到过。", "我没有遇到过",
                       "没有过", "没有这样的例子", "我真的没遇到过", "没见过这种情况",
                       "没碰到过", "没遇上过"):
            with self.subTest(phrase=phrase):
                self.assertEqual("no_instance", classify_answer(phrase, part="失效"),
                                 phrase)

    def test_a_clause_of_his_own_is_still_material(self):
        for phrase in ("没有通知就没人知道", "我没有别的意思", "没有听到通知",
                       "那时没出现这种情况", "没见过他"):
            with self.subTest(phrase=phrase):
                self.assertEqual("answer", classify_answer(phrase, part="失效"), phrase)

    def test_a_bare_no_means_no_example_only_where_an_example_was_asked_for(self):
        """失效 asks 「有没有一次…」; 情境 asks 「那天你手上是什么事」. The same word is
        a complete answer to the first and a fragment against the second."""
        self.assertEqual("no_instance", classify_answer("没有", part="失效"))
        self.assertEqual("none", classify_answer("没有", part="情境"))
        self.assertEqual("no_instance", classify_answer("没遇到过", part="情境"),
                         "an explicit 'I have not met it' needs no context to read")

    def test_i_dont_know_and_i_have_not_seen_one_are_different(self):
        self.assertEqual("none", classify_answer("我不知道", part="失效"))
        self.assertEqual("no_instance", classify_answer("没遇到过", part="失效"))


class OneRealSession(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "dojo.sqlite3")
        self.addCleanup(self.store.close)

    def run_session(self, answers, replies=None):
        client = FakeClient(replies or [
            {"answer": "那我们把这句当成现在这一版。", "candidate": CONCLUSION,
             "user_stance": "neutral"},
            {"answer": "好，就这句。", "candidate": CONCLUSION, "user_stance": "accept"},
        ])
        output = io.StringIO()
        code = run_discuss(self.store, client=client,
                           read_line=read_lines(["讲一条做法", "对，就这么定", *answers]),
                           output=output, environ={})
        return code, output.getvalue(), client

    def trace_rows(self):
        path = sorted((self.root / "sessions").glob("*.jsonl"))[-1]
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def receipt(self, text):
        """The receipt, minus the trace path.

        Two sessions write two trace files, so the last clause differs by path alone. What
        this test is about is the words before it.
        """
        for line in text.splitlines():
            if line.startswith("主持人> ") and ("四件问完了" in line or "问到这里停了" in line):
                return line.split("要回看这一场", 1)[0]
        return ""

    def test_his_words_are_kept_and_the_part_is_not_filled(self):
        code, text, _ = self.run_session(["那天我把检查交出去了", "我少了判断的机会",
                                          "没人再复核", "没有。"])
        self.assertEqual(0, code)
        rows = [row for row in self.trace_rows()
                if row.get("event") == "elicitation" and row.get("part") == "失效"]
        self.assertEqual(1, len(rows), "the part should end here, not be re-asked")
        self.assertEqual("no_instance", rows[0]["reading"])
        self.assertEqual("没有。", rows[0]["answer"], "kept verbatim")
        self.assertIs(False, rows[0]["collected"], "not material for the part")

    def test_the_follow_up_question_is_not_put_to_him(self):
        code, text, _ = self.run_session(["那天我把检查交出去了", "我少了判断的机会",
                                          "没人再复核", "没有。"])
        self.assertEqual(0, code)
        self.assertNotIn("换成另一个人来用", text,
                         "the follow-up asked for the example he just said he has not got")
        self.assertIn("你没有这样的经历", text)

    def test_two_ways_of_saying_it_get_the_same_outcome(self):
        first = self.run_session(["那天我把检查交出去了", "我少了判断的机会", "没人再复核",
                                  "没有。"])
        second_replies = [
            {"answer": "那我们把这句当成现在这一版。", "candidate": CONCLUSION,
             "user_stance": "neutral"},
            {"answer": "好，就这句。", "candidate": CONCLUSION, "user_stance": "accept"},
        ]
        second = self.run_session(["那天我把检查交出去了", "我少了判断的机会", "没人再复核",
                                   "没遇到过。"], replies=second_replies)
        self.assertEqual(self.receipt(first[1]), self.receipt(second[1]),
                         "同一意思的两句话不该得到不同的回执")

    def test_the_receipt_does_not_turn_it_into_never_failing(self):
        code, text, _ = self.run_session(["那天我把检查交出去了", "我少了判断的机会",
                                          "没人再复核", "没遇到过。"])
        self.assertEqual(0, code)
        line = self.receipt(text)
        self.assertIn("没有碰到过这样的例子", line)
        self.assertIn("这一件没有材料", line)
        self.assertIn("不等于这条做法不会失效", line)
        # And 失效 is not reported under either of the two words it is not. The other
        # three parts really were said, so 说了原话 is correct about them -- the check is
        # about which clause names 失效.
        failure_clause = line.split("；")[1]
        self.assertIn("失效", failure_clause)
        self.assertNotIn("说了原话", failure_clause)
        self.assertNotIn("没答出来", line)
        self.assertNotIn("失效", line.split("没答出来", 1)[-1] if "没答出来" in line else "")

    def test_resume_replays_the_same_reading(self):
        self.run_session(["那天我把检查交出去了", "我少了判断的机会", "没人再复核",
                          "没遇到过。"])
        rows = [row for row in self.trace_rows() if row.get("event") == "elicitation"]
        state = elicitation_state(rows)
        self.assertEqual(["失效"], state["no_instance"])
        self.assertNotIn("失效", state["collected"], "the part is not filled by it")
        self.assertNotIn("失效", state["supplied"], "and it is not a failure either")
        self.assertEqual(["情境", "张力", "代价"], state["collected"],
                         "the parts that really were answered stay answered")

    def test_a_resumed_session_keeps_the_bucket(self):
        """The bucket is on the trace row, and the resume path rebuilds the receipt from
        it -- a part that was 没遇到过 must not come back as 没答出来 after a resume."""
        self.run_session(["那天我把检查交出去了", "我少了判断的机会", "没人再复核",
                          "没遇到过。"])
        trace = sorted((self.root / "sessions").glob("*.jsonl"))[-1]
        client = FakeClient([{"answer": "继续说。", "candidate": None,
                              "user_stance": "neutral"}])
        output = io.StringIO()
        code = run_discuss(self.store, client=client, resume=trace,
                           read_line=read_lines(["继续"]), output=output, environ={})
        self.assertEqual(0, code, output.getvalue())
        from dojo.discuss import _load_resume_trace
        state = _load_resume_trace(trace)
        self.assertEqual(["失效"], state["elicitation_no_instance"])
        self.assertNotIn("失效", state["elicitation_supplied"])

    def test_the_trace_and_the_screen_agree_on_the_bucket(self):
        self.run_session(["那天我把检查交出去了", "我少了判断的机会", "没人再复核",
                          "没遇到过。"])
        end = [row for row in self.trace_rows() if row.get("event") == "session_end"][-1]
        self.assertEqual(["失效"], end["elicitation"]["no_instance"])
        self.assertNotIn("失效", end["elicitation"]["collected"])


class ThePureReceipt(unittest.TestCase):
    def test_the_clause_only_uses_the_part_he_named(self):
        line = closing_text([], [], [], no_instance=["失效"])
        self.assertIn("你在 失效 上说没有碰到过这样的例子", line)
        self.assertNotIn("情境", line)

    def test_it_is_not_folded_into_the_kept_words_clause(self):
        line = closing_text(["情境"], [], [], no_instance=["失效"])
        self.assertIn("你在 情境 上说了原话", line)
        self.assertIn("没有碰到过这样的例子", line)
        self.assertIn("这一件没有材料", line)

    def test_all_four_parts_said_the_same_thing(self):
        line = closing_text([], [], [], no_instance=list(PART_ORDER))
        for part in PART_ORDER:
            self.assertIn(part, line)
        self.assertNotIn("说了原话", line)
        self.assertNotIn("没答出来", line)


class TheEndOfASession(unittest.TestCase):
    """Leaving a session is when the reader decides what to do next.

    Two reports from the supervisor on this screen:

      * after an early exit the screen offered a JSONL path and, in the view, a bare
        card id -- two commands to guess at;
      * with `--card c8` and one line of input, the ending row's `draft` was c8 itself and
        the sentence around it said 「没有人认可过它」 about a card that carries a
        confirmation.
    """

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "dojo.sqlite3")
        self.addCleanup(self.store.close)

    def card(self):
        fields = CONCLUSION
        return self.store.add(
            statement=fields["statement"], kind="abstract_idea", scope=fields["scope"],
            premises=fields["premises"], alternatives=fields["alternatives"],
            contradictions=fields["contradictions"], unknowns=fields["unknowns"],
            session="sess-A",
        )["id"]

    def run_early_exit(self, card=None, lines=("聊一下值班",)):
        client = FakeClient([{"answer": "那我们把这句当成现在这一版。",
                              "candidate": CONCLUSION, "user_stance": "neutral"}])
        output = io.StringIO()
        code = run_discuss(self.store, client=client, card=card,
                           read_line=read_lines(list(lines)), output=output, environ={})
        return code, output.getvalue()

    def test_the_exit_names_the_draft_and_the_command_that_shows_it(self):
        code, text = self.run_early_exit()
        self.assertEqual(0, code)
        draft_line = next(line for line in text.splitlines() if "草稿" in line)
        self.assertIn("python3 -m dojo show", draft_line)
        draft_id = draft_line.split("草稿：", 1)[1].split("（", 1)[0]
        self.assertIn(draft_id, text)

    def test_the_exit_names_the_way_back_into_the_words(self):
        code, text = self.run_early_exit()
        self.assertEqual(0, code)
        self.assertIn("python3 -m dojo transcript", text)
        command = [line for line in text.splitlines()
                   if line.startswith("回看这一场说了什么：")][0]
        path = command.split("transcript ", 1)[1]
        self.assertTrue(Path(path).exists(), "the printed command names a real file")

    def test_no_trace_prints_no_transcript_command(self):
        client = FakeClient([{"answer": "那我们把这句当成现在这一版。",
                              "candidate": CONCLUSION, "user_stance": "neutral"}])
        output = io.StringIO()
        run_discuss(self.store, client=client, read_line=read_lines(["聊一下值班"]),
                    output=output, environ={}, no_trace=True)
        self.assertNotIn("dojo transcript", output.getvalue())

    def test_a_reused_card_is_not_called_unaccepted(self):
        """The ending wording is the card that was handed over; it carries a confirmation.
        The screen may not say nobody has accepted it."""
        candidate_id = self.card()
        self.store.record_acceptance(candidate_id, "sess-A", path="discuss_conclusion")
        self.store.confirm(candidate_id, "值得讨论", session="sess-A")
        code, text = self.run_early_exit(card=candidate_id, lines=("我想接着说",))
        self.assertEqual(0, code)
        ending = [line for line in text.splitlines()
                  if "桌上仍是" in line or "未认可的草稿" in line]
        self.assertTrue(ending, text)
        self.assertIn("桌上仍是", ending[0])
        self.assertIn("以前就被认可过", ending[0])
        self.assertNotIn("没有人认可过", ending[0])

    def test_the_view_does_not_call_a_reused_card_unaccepted(self):
        """The view is store-free, so it decides from the handout row: when the ending
        draft names the card the session was opened on, it must not say nobody accepted
        it. The review measured the opposite on `--card c8`."""
        from dojo import transcript as transcript_module

        candidate_id = self.card()
        self.store.record_acceptance(candidate_id, "sess-A", path="discuss_conclusion")
        self.store.confirm(candidate_id, "值得讨论", session="sess-A")
        self.run_early_exit(card=candidate_id, lines=("我想接着说",))
        trace = sorted((self.root / "sessions").glob("*.jsonl"))[-1]
        view = transcript_module.load(trace)
        self.assertEqual(candidate_id, view["draft"])
        self.assertEqual(candidate_id, view["handed"]["candidate"])
        shown = transcript_module.render(view)
        self.assertIn("桌上仍是", shown)
        self.assertNotIn("没有人认可过", shown)
        self.assertIn("python3 -m dojo show", shown)

    def test_a_fresh_draft_is_still_called_unaccepted(self):
        code, text = self.run_early_exit()
        self.assertEqual(0, code)
        ending = [line for line in text.splitlines() if "草稿" in line][0]
        self.assertIn("没有写下被认可的卡片", ending)
        self.assertIn("没有人认可过", ending)


if __name__ == "__main__":
    unittest.main()
