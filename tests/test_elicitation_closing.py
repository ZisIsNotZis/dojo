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
from dojo.elicit import (
    PART_ORDER, QUESTIONS, classify_answer, is_back_request, is_skip_request,
    is_stop_statement,
)
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


PROPOSE = result("你描述的是：检查该谁做。", CONCLUSION)


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
        scripted = ["讲一条做法", "/认可", *answers]
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
            client=FakeClient([PROPOSE]),
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
        self.assertIn("四件你都说了原话", line)
        # Not "you answered all four": the program checked that the replies were not
        # empty, not that they hit the question. Asserted separately below.
        self.assertNotIn("四件你都答了", line)
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
        self.assertNotIn("说了原话", line)

    def test_heard_skipped_and_unanswered_are_three_different_words(self):
        code, text = self.run_session(MIXED)
        self.assertEqual(0, code)
        end = self.recorded()
        self.assertEqual(["情境", "失效"], end["collected"])
        self.assertEqual(["张力"], end["skipped"])
        self.assertEqual(["代价"], end["supplied"])
        line = self.closing_line(text)
        self.assertIn("你在 情境、失效 上说了原话", line)
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
        self.assertNotIn("说了原话", line)
        # Nothing was said, so nothing may be said about where the words went, and the
        # "this does not judge whether you hit" line would be about nothing.
        self.assertNotIn("这些原话", line)
        self.assertNotIn("答没答到点上", line)

    # ---- the sentence must not claim the answers reached the card -----------------

    def test_the_card_does_not_move_when_answers_arrive(self):
        """The claim "我按这条的写法补上了" is what a reader took as "the card changed".

        Dumping every table at every turn shows the card is written before the first
        question and never rewritten: all snapshots are identical. The line must
        say what the user chose to attach while leaving the card's wording unchanged.
        """
        code, text = self.run_session((*MIXED, "/附答 情境"))
        self.assertEqual(0, code)
        self.assertTrue(self.snapshots, "no snapshot was taken")
        # The first snapshots are taken before the card exists (they cover the rounds
        # that decide it); from the first question onward the card must not move.
        with_card = [snap for snap in self.snapshots if snap.get("candidates")]
        self.assertTrue(with_card, "结论卡应当在第一问之前就已写入")
        self.assertIs(self.snapshots.index(with_card[0]), 2,
                      "第一问之前就该有卡：第 0/1 次读入是开场两轮")
        # The card's own rows: version, state, snapshots and events. His answers now go
        # into their own table (`answers`), which is a different fact and is asserted
        # below -- so this compares the card's part of the library, not the whole file.
        card_tables = ("candidates", "snapshots")
        first = {name: with_card[0].get(name) for name in card_tables}
        for later in with_card[1:]:
            self.assertEqual(first, {name: later.get(name) for name in card_tables},
                             "卡片本身在问答过程中被改写了")
        line = self.closing_line(text)
        self.assertIn("附在卡片", line)
        self.assertIn("没有改写成卡片的措辞", line)
        self.assertNotIn("补上了", line)
        # And the answers really are on the card now, which is what the sentence claims.
        shown = self.store.show(self.store.list_candidates()[0]["id"])
        self.assertTrue(shown.get("answers"), "回执说附上了，库里却没有")

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
        self.assertIn("你在 情境 上说了原话", line)
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

    def test_the_wind_down_forms_the_review_found_never_become_material(self):
        """Twelve sentences that reached the entry point as `answer`.

        Measured on `a4b16b7` by a read-only reviewer: each one landed in `collected` and
        the receipt then said "你答了 情境、张力" while the session kept asking. The
        previous slice's SUMMARY called that harmless ("不会说错话，只是不够好"); it was
        not. The claim is withdrawn and these are pinned.

        The split matters and is asserted, not just the fact that they are not `answer`:
        a sentence naming a question (这题/这个问题) is a decision about *this question*
        (`skip`); 算了 / 我该走了 / 别说了 is a decision about the *conversation*
        (`stop`). Reading the first group as `stop` would claim he ended the session.
        """
        for phrase in ("算了吧", "算了算了", "我该走了", "我说完了", "今天先到这儿",
                       "先聊到这儿吧", "别说了"):
            self.assertEqual("stop", classify_answer(phrase), phrase)
        for phrase in ("这题就到这儿吧", "这一题我没什么要补充的", "这道题算了",
                       "我不说了", "这个问题先不聊了"):
            self.assertEqual("skip", classify_answer(phrase), phrase)
            # The order in `classify_answer` is the防线 here: `is_skip_request` runs
            # before `is_stop_statement`, so even a sentence both recognisers would claim
            # reads as `skip`. Made explicit because an arm that adds a stop pattern and
            # stays green looks like a hole until you know why (the reviewer's G/H arms).
            self.assertTrue(is_skip_request(phrase), phrase)
            # Not just "skip wins for now": the *stop* recogniser must not claim it
            # either. With only the ordering asserted, adding a stop pattern that also
            # matches this sentence stayed green (arm E), so the arm had to be made
            # compound to say anything. This is the sentence-level version of that.
            self.assertFalse(is_stop_statement(phrase), phrase)

    def test_the_length_gate_is_not_the_thing_holding_the_boundary(self):
        """The reviewer's arm I: deleting `len(core) > 12` left 34 tests and verify green.

        A guard no test asserts is a guard nobody would notice losing. This asserts what
        it actually does -- it only ever *narrows*, and the whole-sentence patterns carry
        the boundary on their own -- by checking a long sentence that patterns would
        reject anyway, and a long sentence whose *prefix* is a wind-down.
        """
        from dojo.elicit import STOP_PATTERNS, _normalize_skip
        long_prefix = "先到这吧，那次我们从周三一直聊到天黑才把事情定下来"
        self.assertEqual("answer", classify_answer(long_prefix), long_prefix)
        # No stop pattern matches it even with the length gate out of the way: the
        # boundary is the whole-sentence anchor, not the character count.
        core = _normalize_skip(long_prefix)
        self.assertFalse(any(__import__("re").fullmatch(pattern, core) for pattern in STOP_PATTERNS))
        self.assertGreater(len(core), 12)

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

    def test_with_the_trace_off_his_words_are_not_written_to_the_card(self):
        """--no-trace covers the card too, and the screen has to say so.

        The build before this one attached all four answers to the card in a session that
        had said 这场不留原文 -- measured at the CLI with `.scratch/3480/probe_notrace.py`,
        where `show` returned four verbatim sentences and no session file existed. A card
        is a file on the same disk, so the flag has to cover it or it is not a promise
        about privacy but a promise about one filename.
        """
        code, text = self.run_session(ALL_FOUR, no_trace=True)
        self.assertEqual(0, code)
        line = self.closing_line(text)
        self.assertIn("没有附到卡片上", line)
        self.assertNotIn("留在本场记录", line)
        cards = self.store.list_candidates()
        self.assertEqual(1, len(cards))
        self.assertEqual({}, self.store.answers_for(cards[0]["id"]))
        # And the whole card is untouched, not just the answers table: the four answers
        # must not have leaked into the sentence, a scope line or anywhere else.
        stored = json.dumps(self.store.show(cards[0]["id"]), ensure_ascii=False)
        for answer in ALL_FOUR:
            self.assertNotIn(answer, stored)

    def test_a_trace_alone_is_not_authorization_to_attach(self):
        code, text = self.run_session(ALL_FOUR)
        self.assertEqual(0, code)
        self.assertIn("附答核对", text)
        self.assertIn("没有把任何问答原话附到卡片上", self.closing_line(text))
        self.assertEqual([], self.recorded()["promoted"])
        card = self.store.list_candidates()[0]["id"]
        self.assertEqual({}, self.store.answers_for(card))

    def test_invalid_attachment_selection_is_all_or_nothing(self):
        code, text = self.run_session((*MIXED, "/附答 情境 张力"))
        self.assertEqual(0, code)
        self.assertIn("整次不附", text)
        self.assertEqual([], self.recorded()["promoted"])
        card = self.store.list_candidates()[0]["id"]
        self.assertEqual({}, self.store.answers_for(card))

    def test_with_the_trace_on_the_skipped_parts_are_still_recorded(self):
        code, _ = self.run_session((SKIP,) * 4)
        self.assertEqual(0, code)
        self.assertEqual(list(PART_ORDER), self.recorded()["skipped"])

    # ---- the pure function -------------------------------------------------------

    def test_the_pure_function_names_three_outcomes_in_part_order(self):
        line = closing_text(["情境", "失效"], ["张力"], ["代价"])
        self.assertIn("你在 情境、失效 上说了原话", line)
        self.assertIn("你说跳过 张力", line)
        self.assertIn("没答出来 代价", line)
        # With no promotion result there is nothing on the card, so the line says the
        # words stayed in the record and says nothing about the card.
        self.assertIn("留在本场记录里", line)
        self.assertNotIn("附在卡片", line)

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
        self.assertIn("你在 情境 上说了原话", line)
        self.assertIn("你说跳过 张力", line)
        self.assertIn("你说剩下的先不答 代价、失效", line)
        self.assertNotIn("没答出来", line)
        self.assertNotIn("你答了 情境、张力", line)
        self.assertNotIn("张力 上说了原话", line)
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
        self.assertIn("四件你都说了原话", self.closing_line(text))

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

    def test_asking_politely_to_skip_is_a_skip_not_an_answer(self):
        """"能先跳过这一题吗？" and "这题先跳过，下一题吧" are the same request.

        Both were recorded as his answer to the part (measured at the entry point), which
        is the defect this slice exists for. Asking is how people ask.
        """
        for phrase in ("能先跳过这一题吗？", "可以跳过吗", "这题先跳过，下一题吧",
                       "这题先跳过吧，下一题", "这题用不着答了"):
            self.assertEqual("skip", classify_answer(phrase), phrase)
            code, text = self.run_session((phrase, "检查的活搬走了，我自己判断少了"))
            self.assertEqual(0, code)
            end = self.recorded()
            self.assertEqual(["情境"], end["skipped"], phrase)
            self.assertEqual(["张力"], end["collected"], phrase)
            self.assertIn("你说跳过 情境", self.closing_line(text))

    def test_a_skip_shaped_sentence_that_is_kept_says_so_on_screen_and_in_the_receipt(self):
        """The parser will miss phrasings. When it does, nothing is decided for him --
        but the product says what it understood, so he can say "跳过" and be heard.
        """
        phrase = "这题先跳过吧，然后我们下一个"
        self.assertEqual("answer", classify_answer(phrase))
        code, text = self.run_session((phrase, "检查的活搬走了，我自己判断少了",
                                       "第一次觉得亏是没人再复核",
                                       "有一次我照着做反而漏了"))
        self.assertEqual(0, code)
        end = self.recorded()
        # His words stay exactly as spoken: kept as material, not read as a request.
        self.assertEqual(list(PART_ORDER), end["collected"])
        self.assertEqual(["情境"], end["uncertain"])
        events = [row for row in self.trace() if row.get("event") == "elicitation"]
        self.assertEqual(phrase, events[0]["answer"])
        self.assertEqual("answer", events[0]["reading"])
        # The screen says what it understood, at the moment it happens -- and the way out
        # it names is one the program really performs (see the correction test below).
        self.assertIn("这句我按你的原话收下了。想重来就说「改回上一题」。", text)
        # And the receipt does not call it a plain answer.
        line = self.closing_line(text)
        self.assertIn("你提到跳过的那句我按原话收在 情境 里", line)
        self.assertNotIn("你答了 情境", line)

    def test_the_short_word_and_the_correction_are_announced_before_they_are_needed(self):
        """The note promised "直接说「跳过」" for a part already answered -- advice that
        could not work, because the product had no way to go back. Now the shape text says
        the short word up front and names a correction the program really performs.
        """
        code, text = self.run_session((SKIP,) * 4)
        self.assertEqual(0, code)
        self.assertIn("想略过就说「跳过」；说错了，下一句说「改回上一题」。", text)
        # The correction has to be a real instruction, not a phrase in a sentence.
        self.assertEqual("answer", classify_answer("改回上一题"))
        self.assertTrue(is_back_request("改回上一题"))
        self.assertFalse(is_back_request(""), "空行不能读成“改回上一题”")
        # Said before the first question, not after a missed guess.
        shape_at = text.index("想略过就说「跳过」")
        self.assertLess(shape_at, text.index(QUESTIONS["情境"]["ask"]))

    def test_the_correction_actually_reopens_the_part(self):
        """Every promise the receipt makes has to be executable (#3363).

        Two wrong shapes were caught here before this passed: `continue` only advanced the
        inner turn loop, so the part was never asked again; inserting the part left the one
        that was interrupted skipped. Both looked fine in the trace.
        """
        # A sentence kept as material, then taken back, then answered properly.
        code, text = self.run_session(
            ("这题先跳过吧，然后我们下一个", "改回上一题",
             "上次是把一套检查交给别人的时候", "检查的活搬走了，我自己判断少了",
             "第一次觉得亏是没人再复核", "有一次我照着做反而漏了"))
        self.assertEqual(0, code)
        end = self.recorded()
        self.assertEqual(list(PART_ORDER), end["collected"])
        self.assertEqual([], end["uncertain"])
        self.assertIn("好，退回「情境」。", text)
        self.assertIn("四件你都说了原话", self.closing_line(text))
        readings = [row["reading"] for row in self.trace()
                    if row.get("event") == "elicitation" and row.get("part") == "情境"]
        self.assertEqual(["answer", "undo", "answer"], readings)

        # A skip request taken back: the receipt must not still say it was skipped.
        code, text = self.run_session(
            ("跳过", "改回上一题", "上次是把一套检查交给别人的时候",
             "检查的活搬走了，我自己判断少了", "第一次觉得亏是没人再复核",
             "有一次我照着做反而漏了"))
        self.assertEqual(0, code)
        end = self.recorded()
        self.assertEqual([], end["skipped"])
        self.assertEqual(list(PART_ORDER), end["collected"])
        self.assertNotIn("你说跳过", self.closing_line(text))

    def test_a_correction_survives_a_resumed_session(self):
        """Resume used to rebuild a different story than the screen it resumed (#3363).

        Two independent reconstructions (the live lists and a scan of the trace) disagreed
        after an undo: a part taken back and then skipped came back as answered, and a
        part asked after "next two" was reported as set aside. There is now one replay,
        and both the receipt and `--resume` read it.
        """
        from dojo.discuss import _load_resume_trace

        # 情境: skipped, taken back, then answered.
        code, text = self.run_session(
            ("跳过", "改回上一题", "上次是把一套检查交给别人的时候",
             "检查的活搬走了，我自己判断少了", "第一次觉得亏是没人再复核",
             "有一次我照着做反而漏了"))
        self.assertEqual(0, code)
        end = self.recorded()
        path = sorted((self.root / "sessions").glob("*.jsonl"))[-1]
        resumed = _load_resume_trace(path)
        self.assertEqual(end["collected"], resumed["elicitation_collected"])
        self.assertEqual(end["skipped"], resumed["elicitation_skipped"])
        self.assertEqual([], resumed["elicitation_skipped"])
        self.assertNotIn("你说跳过", self.closing_line(text))


    def test_a_counted_request_leaves_the_last_part_his_and_resume_agrees(self):
        """"接下来两题先跳过" at the first question covers 张力 and 代价, not 失效.

        A part he reached and answered afterwards is his -- it must not stay in the
        "set aside" list, on screen or after a resume (#3363).
        """
        from dojo.discuss import _load_resume_trace

        code, text = self.run_session(("接下来两题先跳过", "有一次我照着做反而漏了"))
        self.assertEqual(0, code)
        end = self.recorded()
        self.assertEqual(["失效"], end["collected"])
        self.assertEqual(["张力", "代价"], end["declined"])
        path = sorted((self.root / "sessions").glob("*.jsonl"))[-1]
        resumed = _load_resume_trace(path)
        self.assertEqual(end["collected"], resumed["elicitation_collected"])
        self.assertEqual(end["declined"], resumed["elicitation_declined"])
        self.assertEqual(2, resumed["elicitation_declined_count"])
        self.assertIn("你在 失效 上说了原话", self.closing_line(text))

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


    # ---- saying "I am done" in words, instead of ending the input -------------------

    def test_saying_he_is_done_ends_the_session_and_is_not_his_answer(self):
        """"先到这吧" is neither an answer nor a failure to answer.

        It used to be read as an answer to the part on screen: the words were kept as
        material for 张力, the receipt said "你答了 张力", and the asking went on. Three
        of these phrasings were worse -- they also matched the skip-mention detector, so
        the receipt said "你提到跳过的那句我按原话收在 张力 里" about a sentence that
        mentions no skipping at all.
        """
        for phrase in ("算了，先不说了", "先到这吧", "不想聊了", "就说这么多吧",
                       "我没什么要补充的", "就这样吧"):
            code, text = self.run_session(
                ("上次是把一套检查交给别人的时候", phrase))
            self.assertEqual(0, code, phrase)
            end = self.recorded()
            self.assertEqual(["情境"], end["collected"], phrase)
            self.assertEqual([], end["skipped"], phrase)
            self.assertEqual([], end["supplied"], phrase)
            events = [row for row in self.trace() if row.get("event") == "elicitation"]
            self.assertEqual("stop", events[-1]["reading"], phrase)
            self.assertEqual("张力", events[-1]["part"], phrase)
            line = self.closing_line(text)
            self.assertIn("问到 张力 时你说到这儿为止", line, phrase)
            self.assertNotIn("你结束了输入", line, phrase)
            self.assertNotIn("你答了 情境、张力", line, phrase)
            # The lie that made this slice: it never mentioned skipping.
            self.assertNotIn("你提到跳过", line, phrase)
            self.assertNotIn("四件问完了", line, phrase)
            # The question after it was never put to him.
            self.assertNotIn(QUESTIONS["代价"]["ask"], self.host_lines(text), phrase)

    def test_saying_he_is_done_keeps_the_draft_and_agrees_with_a_resume(self):
        """Ending in words is the same ending as end-of-input: draft kept, one story."""
        from dojo.discuss import _load_resume_trace

        code, text = self.run_session(
            ("上次是把一套检查交给别人的时候", "先到这吧"))
        self.assertEqual(0, code)
        end = self.recorded()
        path = sorted((self.root / "sessions").glob("*.jsonl"))[-1]
        resumed = _load_resume_trace(path)
        self.assertEqual(end["collected"], resumed["elicitation_collected"])
        self.assertEqual(end["skipped"], resumed["elicitation_skipped"])
        self.assertEqual(end["supplied"], resumed["elicitation_supplied"])
        self.assertEqual(["情境"], resumed["elicitation_collected"])
        self.assertIn("讨论已结束。", text)

    def test_a_sentence_with_a_wind_down_word_in_it_is_still_material(self):
        """The wind-down reading has to stay narrow or it eats real answers.

        "说到这儿我想起来，那次是周三" begins with the same three characters as
        "说到这儿吧". A whole-sentence match is what keeps them apart, and these are the
        sentences that prove the boundary is where it is.
        """
        for phrase in ("说到这儿我想起来，那次是周三",
                       "就这样吧，我们当时是这么定的",
                       "我算了吧，这事我后来没再提",
                       "剩下的流程我都不讲给新人听",
                       "上一次为了做到它，我推掉了两个会"):
            self.assertEqual("answer", classify_answer(phrase), phrase)
        # Short ones, which the length gate cannot protect: only the whole-sentence
        # match stands between them and being read as "I am done". A prefix matcher
        # swallows every one of these (measured -- the first version of this test used
        # only the long sentences above and stayed green under that red arm).
        for phrase in ("算了，没谈拢", "算了，那次没成", "到这儿为止都顺利",
                       "就这样吧，后来改了", "先到这的人少", "说到这儿就够了",
                       "先撤的人是他"):
            self.assertEqual("answer", classify_answer(phrase), phrase)

    def test_a_spoken_stop_never_becomes_an_empty_answer(self):
        """"stop" must not fall through to "没答出来", which is the other wrong word."""
        code, text = self.run_session(("先到这吧",))
        self.assertEqual(0, code)
        end = self.recorded()
        self.assertEqual([], end["collected"])
        self.assertEqual([], end["supplied"], "说到这儿为止不是“问了两轮没答出来”")
        line = self.closing_line(text)
        self.assertIn("问到 情境 时你说到这儿为止", line)
        self.assertNotIn("没答出来", line)
        self.assertIn("没问到 张力、代价、失效", line)

    # ---- the number he said vs. the number there was ---------------------------

    def test_asking_for_more_questions_than_remain_says_what_really_happened(self):
        """"接下来五题都先不答" with two left is two set aside, not five.

        `declined_count` used to hold the number he spoke, so a field named "count"
        said 5 about two parts. The receipt avoided the lie by falling back to "剩下的",
        which also dropped the fact that he had named a number at all.
        """
        code, text = self.run_session(
            ("上次是把一套检查交给别人的时候", "接下来五题都先不答"))
        self.assertEqual(0, code)
        end = self.recorded()
        self.assertEqual(["代价", "失效"], end["declined"])
        self.assertEqual(2, end["declined_count"], "这个字段要说实际搁下了几件")
        self.assertEqual(5, end["declined_stated"], "他说的是五题，这句也要留下")
        line = self.closing_line(text)
        self.assertIn("你说接下来 5 题先不答，剩下只有 代价、失效", line)

    def test_a_count_that_matches_what_is_left_is_reported_once(self):
        code, text = self.run_session(
            ("上次是把一套检查交给别人的时候", "接下来两题先不答"))
        self.assertEqual(0, code)
        end = self.recorded()
        self.assertEqual(2, end["declined_count"])
        self.assertEqual(2, end["declined_stated"])
        line = self.closing_line(text)
        self.assertIn("你说接下来 2 题先不答 代价、失效", line)
        self.assertNotIn("剩下只有", line)

    def test_a_resume_keeps_both_numbers(self):
        from dojo.discuss import _load_resume_trace

        code, _ = self.run_session(
            ("上次是把一套检查交给别人的时候", "接下来五题都先不答"))
        self.assertEqual(0, code)
        path = sorted((self.root / "sessions").glob("*.jsonl"))[-1]
        resumed = _load_resume_trace(path)
        self.assertEqual(2, resumed["elicitation_declined_count"])
        self.assertEqual(5, resumed["elicitation_declined_stated"])


if __name__ == "__main__":
    unittest.main()
