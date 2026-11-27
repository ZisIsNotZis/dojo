"""四件问完之后，屏幕上那句话说的是不是真的。

这一支测的是真入口 `run_discuss` 的屏幕输出，而且每一场都同时读轨迹与库，因为上一版
这句话的毛病正是「屏幕说了、记录里没有」：

- 他在四次里说「先跳过这一题」，屏幕却说「四件都落在你说过的话上」；
- 屏幕说「我按这条的写法补上了」，可卡片在提问**之前**就写好了，问答从头到尾没碰它。

所以每条断言都拿屏幕上的字与 `session_end` 的 `collected`/`skipped`/`supplied`
以及库的快照三方对照，而不是只 grep 一句话。
"""

import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from dojo.discuss import closing_text, run_discuss
from dojo.elicit import PART_ORDER, QUESTIONS, classify_answer
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
SKIP = "先跳过这一题"
# 一问答、一件说跳过、一件两个空行（问 + 换问法都没答）、一件答：
# 三种结局都要在屏幕上分得开，而且跳过的件不能再吃一次换问法。
MIXED = ("上次是把一套检查交给别人的时候", SKIP, "", "", "有一次我照着做反而漏了")


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


def store_snapshot(root):
    """Every row of every table, as plain tuples -- so "the card did not move" is
    checkable byte for byte instead of being taken on trust."""
    database = sorted(root.glob("*.sqlite3"))
    if not database:
        return {}
    connection = sqlite3.connect(database[0])
    try:
        tables = [row[0] for row in connection.execute(
            "select name from sqlite_master where type='table' order by name")]
        return {table: connection.execute(f"select * from {table}").fetchall()
                for table in tables}
    finally:
        connection.close()


class ClosingLineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "dojo.sqlite3")
        self.snapshots = []

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def run_session(self, answers, no_trace=False, snapshot_each_turn=True):
        output = io.StringIO()
        scripted = ["讲一条做法", "对", *answers]
        if snapshot_each_turn:
            inner = read_lines(scripted)

            def read_line(prompt):
                # Snapshot before each answer is consumed: this is the state the person
                # is answering against, i.e. what the card already says.
                self.snapshots.append(store_snapshot(self.root))
                return inner(prompt)
        else:
            read_line = read_lines(scripted)
        code = run_discuss(
            self.store,
            client=FakeClient(TWO_TURNS),
            read_line=read_line,
            output=output,
            no_trace=no_trace,
        )
        self.snapshots.append(store_snapshot(self.root))
        return code, output.getvalue()

    def trace(self):
        sessions = sorted((self.root / "sessions").glob("*.jsonl"))
        self.assertTrue(sessions, "本场应当留下轨迹")
        return [json.loads(line) for line in sessions[-1].read_text(encoding="utf-8").splitlines()]

    def recorded(self):
        sessions = sorted((self.root / "sessions").glob("*.jsonl"))
        self.assertTrue(sessions, "本场应当留下轨迹")
        for line in sessions[-1].read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row.get("event") == "session_end":
                return row["elicitation"]
        return None

    def host_lines(self, text):
        return [line[len("主持人> "):] for line in text.splitlines()
                if line.startswith("主持人> ")]

    def closing_line(self, text):
        for body in self.host_lines(text):
            if body.startswith("四件问完了") or body.startswith("问到这里停了"):
                return body
        return None

    # ---- the four stated outcomes, each checked against the record ----------------

    def test_all_four_answered_says_all_four_and_the_record_agrees(self):
        code, text = self.run_session(ALL_FOUR)
        self.assertEqual(0, code)
        end = self.recorded()
        self.assertEqual(list(PART_ORDER), end["collected"])
        self.assertEqual([], end["skipped"])
        self.assertEqual([], end["supplied"])
        line = self.closing_line(text)
        self.assertIn("四件你都答了", line)
        for part in PART_ORDER:
            self.assertNotIn(f"{part} 没答出来", line)
            self.assertNotIn(f"你说跳过 {part}", line)

    def test_all_four_skipped_says_skipped_not_answered(self):
        code, text = self.run_session((SKIP,) * 4)
        self.assertEqual(0, code)
        end = self.recorded()
        self.assertEqual([], end["collected"])
        self.assertEqual(list(PART_ORDER), end["skipped"])
        self.assertEqual([], end["supplied"])
        line = self.closing_line(text)
        self.assertIn("你说跳过", line)
        self.assertIn("、".join(PART_ORDER), line)
        # The defect this test exists for: four skip requests used to be reported as
        # "四件都落在你说过的话上".
        self.assertNotIn("四件都落在你说过的话上", text)
        self.assertNotIn("四件你都答了", line)

    def test_answered_skipped_and_unanswered_are_three_different_words(self):
        code, text = self.run_session(MIXED)
        self.assertEqual(0, code)
        end = self.recorded()
        self.assertEqual(["情境", "失效"], end["collected"])
        self.assertEqual(["张力"], end["skipped"])
        self.assertEqual(["代价"], end["supplied"])
        line = self.closing_line(text)
        self.assertIn("你答了 情境、失效", line)
        self.assertIn("你说跳过 张力", line)
        self.assertIn("没答出来 代价", line)
        # Order comes from PART_ORDER, not from the order the lists filled up.
        self.assertLess(line.index("情境"), line.index("张力"))
        self.assertLess(line.index("张力"), line.index("代价"))

    def test_all_blank_says_nothing_was_answered(self):
        # A blank part costs two lines: the ask and its follow-up.
        code, text = self.run_session(("",) * 8)
        self.assertEqual(0, code)
        end = self.recorded()
        self.assertEqual([], end["collected"])
        self.assertEqual([], end["skipped"])
        self.assertEqual(list(PART_ORDER), end["supplied"])
        line = self.closing_line(text)
        self.assertIn("没答出来", line)
        self.assertNotIn("你答了", line)
        # Nothing was answered, so nothing may be said about where answers went.
        self.assertNotIn("这些回答", line)

    # ---- the sentence must not claim the answers reached the card -----------------

    def test_the_card_does_not_move_when_answers_arrive(self):
        """The claim "我按这条的写法补上了" is what a reader took as "the card changed".

        Dumping every table at every turn shows the card is written before the first
        question and never rewritten: all snapshots are identical. The line must
        therefore say the answers stayed out of the card, and say the card predates them.
        """
        code, text = self.run_session(MIXED)
        self.assertEqual(0, code)
        self.assertTrue(self.snapshots, "no snapshot was taken")
        # The first snapshots are taken before the card exists (they cover the rounds
        # that decide it); from the first question onward the card must not move.
        with_card = [snap for snap in self.snapshots if snap.get("candidates")]
        self.assertTrue(with_card, "结论卡应当在第一问之前就已写入")
        self.assertIs(self.snapshots.index(with_card[0]), 2,
                      "第一问之前就该有卡：第 0/1 次读入是开场两轮")
        first = with_card[0]
        for later in with_card[1:]:
            self.assertEqual(first, later, "库在问答过程中被改写了")
        line = self.closing_line(text)
        self.assertIn("没有写进卡片", line)
        self.assertIn("卡片是提问前写下的那句", line)
        self.assertNotIn("补上了", line)

    # ---- the person who leaves early ---------------------------------------------

    def test_stopping_early_still_gets_a_receipt_without_false_completion(self):
        """The entry block invites "想停随时结束输入"; that person used to get nothing.

        #3363: the receipt then said "没答出来 张力" -- "you failed to answer tension" --
        about a part whose question was still on screen when the input ended. He did not
        fail at it; he declined to go on. Those are different facts and the receipt must
        not turn the second into the first.
        """
        code, text = self.run_session(("上次是把一套检查交给别人的时候",))
        self.assertEqual(0, code)
        end = self.recorded()
        self.assertEqual(["情境"], end["collected"])
        line = self.closing_line(text)
        self.assertIsNotNone(line, "提前结束的人没有拿到回执")
        self.assertIn("你答了 情境", line)
        self.assertIn("问到 张力 时你结束了输入", line)
        self.assertNotIn("没答出来 张力", line,
                         "他把输入结束在张力那一问上，没说答不出来")
        self.assertIn("没问到 代价、失效", line)
        # Four questions were not all put to him, so the completion claim is false here.
        self.assertNotIn("四件问完了", line)
    # ---- skip recognition --------------------------------------------------------

    def test_a_skip_request_is_asked_once_and_not_again(self):
        code, text = self.run_session((SKIP,) * 4)
        self.assertEqual(0, code)
        asks = [QUESTIONS[part]["ask"] for part in PART_ORDER]
        follow_ups = [text_ for part in PART_ORDER
                      for text_ in QUESTIONS[part]["follow_ups"].values()]
        shown = self.host_lines(text)
        self.assertEqual(asks, [line for line in shown if line in asks])
        self.assertEqual([], [line for line in shown if line in follow_ups])
        self.assertEqual(4, self.recorded()["turns"])

    def test_plain_speech_skip_forms_all_read_as_skip(self):
        for phrase in ("先跳过这一题", "跳过", "这题先跳过", "下一题", "不想说",
                       "先跳过这一题，我还没想好", "跳过吧。"):
            self.assertEqual("skip", classify_answer(phrase), phrase)

    def test_material_that_merely_mentions_skipping_is_still_an_answer(self):
        # 失效那件要的原话正是这种句子，不能把它当成跳过请求。
        for phrase in ("我跳过这一步的时候就会出错",
                       "有一次我照着做反而漏了，因为中间那步被跳过了",
                       "跳过复核就会出问题"):
            self.assertEqual("answer", classify_answer(phrase), phrase)
        for phrase in ("不知道", "看情况", "因人而异"):
            self.assertEqual("none", classify_answer(phrase), phrase)

    # ---- --no-trace --------------------------------------------------------------

    def test_with_the_trace_off_it_does_not_promise_retention(self):
        code, text = self.run_session((SKIP,) * 4, no_trace=True)
        self.assertEqual(0, code)
        line = self.closing_line(text)
        self.assertIn("你说跳过", line)
        self.assertNotIn("留在本场记录", line)

    def test_with_the_trace_on_the_skipped_parts_are_still_recorded(self):
        code, _ = self.run_session((SKIP,) * 4)
        self.assertEqual(0, code)
        self.assertEqual(list(PART_ORDER), self.recorded()["skipped"])

    # ---- the pure function -------------------------------------------------------

    def test_the_pure_function_names_three_outcomes_in_part_order(self):
        line = closing_text(["情境", "失效"], ["张力"], ["代价"])
        self.assertIn("你答了 情境、失效", line)
        self.assertIn("你说跳过 张力", line)
        self.assertIn("没答出来 代价", line)
        self.assertIn("没有写进卡片", line)

    def test_the_pure_function_does_not_say_all_four_when_they_were_not_asked(self):
        line = closing_text(["情境"], [], ["张力"], unfinished=["代价", "失效"])
        self.assertNotIn("四件问完了", line)
        self.assertIn("没问到", line)

    # ---- #3363: the two outcomes the receipt could not name ----------------------

    def test_stopping_at_a_question_has_its_own_word_again(self):
        """He answered the first, then ended the input at the second.

        The old line said "没答出来 张力". Every part has exactly one word, and the one
        for "the input ended while this question was on screen" is not the one for "it
        was asked twice and nothing came back".
        """
        code, text = self.run_session(("上次是把一套检查交给别人的时候",))
        self.assertEqual(0, code)
        line = self.closing_line(text)
        self.assertIn("问到 张力 时你结束了输入", line)
        self.assertNotIn("没答出来", line)
        end = self.recorded()
        self.assertEqual(["情境"], end["collected"])
        self.assertEqual([], end["supplied"], "结束输入不是“问了两轮没答出来”")

    def test_asking_to_drop_the_rest_is_not_an_answer_and_not_a_failure(self):
        """"这几题我想先跳过" said at the second question (#3363).

        Before this the sentence was recorded as his answer to 张力 -- the receipt said
        "你答了 情境、张力" -- and the questions after it were then asked anyway. Both are
        wrong: it is a request about the questions still to come, so they are not asked,
        and the receipt says so instead of counting them as parts he could not answer.
        """
        code, text = self.run_session(
            ("上次是把一套检查交给别人的时候", "这几题我想先跳过"))
        self.assertEqual(0, code)
        end = self.recorded()
        self.assertEqual(["情境"], end["collected"])
        self.assertEqual(["张力"], end["skipped"])
        self.assertEqual(["代价", "失效"], end["declined"])
        self.assertEqual([], end["supplied"])
        line = self.closing_line(text)
        self.assertIn("你答了 情境", line)
        self.assertIn("你说跳过 张力", line)
        self.assertIn("你说剩下的先不答 代价、失效", line)
        self.assertNotIn("没答出来", line)
        self.assertNotIn("你答了 情境、张力", line)
        # The last two questions were never put to him, so they are not on screen.
        shown = self.host_lines(text)
        self.assertNotIn(QUESTIONS["代价"]["ask"], shown)
        self.assertNotIn(QUESTIONS["失效"]["ask"], shown)
        # Nor is his request kept anywhere as material about the rule.
        self.assertNotIn("这几题我想先跳过", json.dumps(
            end["part_sources"], ensure_ascii=False))
        self.assertEqual("系统的", end["authorship"])

    def test_dropping_the_rest_at_the_first_question_asks_nothing_more(self):
        code, text = self.run_session(("这几题我想先跳过",))
        self.assertEqual(0, code)
        end = self.recorded()
        self.assertEqual([], end["collected"])
        self.assertEqual(["情境"], end["skipped"])
        self.assertEqual(["张力", "代价", "失效"], end["declined"])
        shown = self.host_lines(text)
        self.assertEqual([QUESTIONS["情境"]["ask"]],
                         [line for line in shown
                          if line in [QUESTIONS[p]["ask"] for p in PART_ORDER]])
        line = self.closing_line(text)
        self.assertIn("你说剩下的先不答 张力、代价、失效", line)
        self.assertNotIn("四件问完了", line)

    def test_a_sentence_about_a_skipped_step_is_still_material(self):
        """The whole-set boundary must not swallow a real answer about a skipped step."""
        answers = ("上次是把一套检查交给别人的时候", "检查的活搬走了，我自己判断少了",
                   "第一次觉得亏是没人再复核",
                   "有一次这几步都跳过了，结果漏了复核")
        code, _ = self.run_session(answers)
        self.assertEqual(0, code)
        end = self.recorded()
        self.assertEqual(list(PART_ORDER), end["collected"])
        self.assertEqual([], end["declined"])

    def test_material_that_mentions_the_remainder_of_a_process_is_an_answer(self):
        """"剩下的流程我都不讲给新人听" is a sentence about a rule (#3363).

        It was read as a request to stop asking: his material was thrown away and the
        session ended early. The word "剩下" only scopes the asking when what is left
        over after removing scope words and particles is empty. 流程 / 新人听 are content.
        """
        answer = "上次是把一套检查交给别人的时候：剩下的流程我都不讲给新人听"
        # These carry no time/narration word and no possessive, so the only thing standing
        # between them and "he asked to stop" is that 流程 / 细节 / 讲清楚 are content.
        for plain in ("剩下的流程我都不讲", "剩下的细节留给别人",
                      "接下来两题我想先讲清楚"):
            self.assertEqual("answer", classify_answer(plain), plain)
        answers = (answer, "检查的活搬走了，我自己判断少了",
                   "第一次觉得亏是没人再复核", "有一次我照着做反而漏了")
        code, text = self.run_session(answers)
        self.assertEqual(0, code)
        end = self.recorded()
        self.assertEqual(list(PART_ORDER), end["collected"])
        self.assertEqual([], end["declined"])
        self.assertEqual([], end["skipped"])
        events = [row for row in self.trace() if row.get("event") == "elicitation"]
        self.assertEqual(answer, events[0]["answer"])
        self.assertEqual("answer", events[0]["reading"])
        self.assertIn("四件你都答了", self.closing_line(text))

    def test_a_named_count_drops_exactly_that_many_and_the_rest_is_still_asked(self):
        """"接下来两题先跳过" covers two questions, not the whole remainder (#3363)."""
        code, text = self.run_session(
            ("上次是把一套检查交给别人的时候", "接下来两题先跳过"))
        self.assertEqual(0, code)
        end = self.recorded()
        self.assertEqual(["情境"], end["collected"])
        self.assertEqual(["张力"], end["skipped"])
        self.assertEqual(["代价", "失效"], end["declined"])
        line = self.closing_line(text)
        self.assertIn("你说接下来 2 题先不答 代价、失效", line)
        self.assertNotIn("剩下的先不答", line)

    def test_a_named_count_at_the_first_question_still_leaves_the_last_one_asked(self):
        # Said at the first question it covers 张力 and 代价 only: 失效 is still asked.
        code, text = self.run_session(("接下来两题先跳过", "有一次我照着做反而漏了"))
        self.assertEqual(0, code)
        end = self.recorded()
        self.assertEqual(["失效"], end["collected"])
        self.assertEqual(["情境"], end["skipped"])
        self.assertEqual(["张力", "代价"], end["declined"])
        shown = self.host_lines(text)
        self.assertIn(QUESTIONS["失效"]["ask"], shown)
        self.assertNotIn(QUESTIONS["代价"]["ask"], shown)

    def test_the_whole_set_forms_read_as_one_outcome(self):
        for phrase in ("这几题我想先跳过", "这几题先跳过吧", "剩下几件先跳过",
                       "其余的我不想答了", "这几题我不想说", "这几题我都不想答",
                       "这几题先跳过，我还没想好"):
            self.assertEqual("skip_rest", classify_answer(phrase), phrase)
        # One question at a time stays a single-question skip: nobody can tell how many
        # he meant, so the part ends but the rest is still asked.
        for phrase in ("跳过", "先跳过这一题", "这题先跳过", "下一题"):
            self.assertEqual("skip", classify_answer(phrase), phrase)
        # These are material about the rule, not requests about the asking.
        for phrase in ("我跳过这一步的时候就会出错",
                       "我跳过的这几题里有一次漏了复核",
                       "有一次这几步都跳过了，结果漏了",
                       "这几题我想先跳过，因为上周出过事",
                       "跳过复核就会出问题",
                       "这几题都答完了"):
            self.assertEqual("answer", classify_answer(phrase), phrase)


if __name__ == "__main__":
    unittest.main()
