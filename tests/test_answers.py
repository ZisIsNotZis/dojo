"""His own words beside the card: what promotion may and may not change.

The walk that produced `docs/evidence/2026-11-28-answers-on-card/` is the end-to-end
check. These are the contract checks under it, at the store and at the small module that
turns a card's answers into lines:

  one vocabulary   `answers.PARTS`, `storage.PART_KEYS_BY_FIELD` and `elicit.PART_KEYS`
                   are the same four parts; a drift there would put one part's answer
                   under another part's heading, which no screen would look wrong.
  the four facts   a promotion writes the answer verbatim; it moves no field, no source,
                   no status and no version.
  reversible       an unpromote takes one answer off and keeps what it was in the ledger.
  nothing invented an answer with no `at` gets no `at`, and a part with no answer prints
                   nothing at all.
"""
import json
import tempfile
import unittest
from pathlib import Path

from dojo import answers as answers_module
from dojo.elicit import PART_KEYS
from dojo.storage import PART_FIELD_BY_NAME, PART_KEYS_BY_FIELD, Store


class TheVocabularyAgrees(unittest.TestCase):
    def test_the_three_declarations_are_one_mapping(self):
        # `elicit.PART_KEYS` maps the part name to the field key (`结构` -> `situation`);
        # `storage.PART_KEYS_BY_FIELD` maps the key to the name. Same relation, both ways.
        self.assertEqual({key: name for name, key in PART_KEYS.items()}, PART_KEYS_BY_FIELD)
        self.assertEqual(PART_KEYS, PART_FIELD_BY_NAME)
        self.assertEqual(set(answers_module.PARTS), set(PART_KEYS_BY_FIELD))

    def test_every_part_has_a_label_a_person_can_read(self):
        for key in PART_KEYS_BY_FIELD:
            self.assertTrue(answers_module.PART_LABELS.get(key), key)


class Promotion(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "dojo.sqlite3")
        self.addCleanup(self.store.close)
        self.card = self.store.add(
            "把持续检查交给系统跑。", "abstract_idea",
            scope=["他已经抽身时"], contradictions=["人来不及时接手时"],
            sources=[{"type": "unknown", "claim": "一场讨论的结论",
                      "verification": "unknown", "independence_group": "s1"}],
            session="s1",
        )["id"]

    def answers(self):
        return [
            {"part": "情境", "answer": "上周二夜里报警，我已经回家了", "session": "s1",
             "at": "2026-11-28T01:02:03+00:00", "question": "问一"},
            {"part": "price", "answer": "两个同事要多跑一趟", "session": "s1"},
        ]

    def test_provenance_and_the_file_check_are_stored_and_read_back(self):
        """Two facts the screen needs, kept as stored rather than inferred later.

        Review found both screens inventing them: a hand-kept answer showed as a
        `--no-trace` discussion, and an answer missing from a half-written record still
        offered a command back to that record.
        """
        entries = self.answers()
        entries[0]["provenance"] = "discussion"
        entries[0]["trace"] = "/abs/sessions/discuss-a.jsonl"
        entries[0]["recorded"] = True
        entries[1]["provenance"] = "manual"
        entries[1]["recorded"] = False
        self.store.promote_answers(self.card, entries, session="s1")
        held = self.store.answers_for(self.card)
        self.assertEqual("discussion", held["situation"]["provenance"])
        self.assertEqual(1, held["situation"]["recorded"])
        self.assertEqual("manual", held["price"]["provenance"])
        self.assertEqual(0, held["price"]["recorded"])

    def test_a_row_without_provenance_stays_unknown_rather_than_guessed(self):
        self.store.promote_answers(self.card, self.answers(), session="s1")
        held = self.store.answers_for(self.card)
        self.assertIsNone(held["situation"]["provenance"])
        self.assertIsNone(held["situation"]["recorded"])

    def test_a_library_from_before_these_columns_gains_them_without_claiming_anything(self):
        """An older `answers` table must still be readable, and its rows must not lie."""
        self.store.promote_answers(self.card, self.answers(), session="s1")
        self.store.connection.execute("ALTER TABLE answers DROP COLUMN provenance")
        self.store.connection.execute("ALTER TABLE answers DROP COLUMN recorded")
        self.store.connection.commit()
        held = self.store.answers_for(self.card)
        self.assertEqual("上周二夜里报警，我已经回家了", held["situation"]["answer"])
        self.assertIsNone(held["situation"]["provenance"])
        self.assertIsNone(held["situation"]["recorded"])
        # Writing again widens the table rather than failing on a column that is missing.
        again = self.answers()
        again[0]["answer"] = "上周三夜里报警"
        again[0]["provenance"] = "discussion"
        self.store.promote_answers(self.card, again, session="s1")
        self.assertEqual("discussion", self.store.answers_for(self.card)["situation"]["provenance"])

    def test_the_words_are_stored_verbatim_with_their_origin(self):
        self.store.promote_answers(self.card, self.answers(), session="s1")
        held = self.store.answers_for(self.card)
        self.assertEqual("上周二夜里报警，我已经回家了", held["situation"]["answer"])
        self.assertEqual("s1", held["situation"]["session"])
        self.assertEqual("2026-11-28T01:02:03+00:00", held["situation"]["at"])

    def test_an_answer_with_no_moment_gets_no_moment(self):
        """Borrowing the write time would make two different answers look simultaneous."""
        self.store.promote_answers(self.card, self.answers(), session="s1")
        self.assertIsNone(self.store.answers_for(self.card)["price"]["at"])

    def test_the_card_itself_does_not_move(self):
        before = self.store.show(self.card)
        self.store.promote_answers(self.card, self.answers(), session="s1")
        after = self.store.show(self.card)
        self.assertEqual(before["candidate"], after["candidate"])
        self.assertEqual(1, after["candidate"]["version"])

    def test_it_adds_no_source_and_no_status(self):
        self.store.promote_answers(self.card, self.answers(), session="s1")
        state = self.store.show(self.card)["candidate"]
        self.assertEqual(1, len(state["sources"]))
        self.assertEqual("draft", state["status"])

    def test_it_does_not_count_as_an_independence_group(self):
        """His answer is material about the claim, not a second arrival at it."""
        self.store.promote_answers(self.card, self.answers(), session="s2")
        state = self.store.show(self.card)["candidate"]
        self.assertEqual(["s1"], state["sessions"])

    def test_the_ledger_names_the_fields_it_wrote(self):
        self.store.promote_answers(self.card, self.answers(), session="s1")
        events = [event for event in self.store.history(self.card)["events"]
                  if event["event"] == "promote_answers"]
        self.assertEqual(1, len(events))
        self.assertEqual(["situation", "price"], events[0]["details"]["fields"])

    def test_the_same_answers_again_move_nothing(self):
        self.store.promote_answers(self.card, self.answers(), session="s1")
        version = self.store.show(self.card)["candidate"]["version"]
        self.store.promote_answers(self.card, self.answers(), session="s1")
        self.assertEqual(version, self.store.show(self.card)["candidate"]["version"])
        self.assertIn("promote_answers.repeat",
                      [event["event"] for event in self.store.history(self.card)["events"]])

    def test_a_changed_answer_keeps_the_previous_one_in_the_ledger(self):
        self.store.promote_answers(self.card, self.answers(), session="s1")
        self.store.promote_answers(
            self.card, [{"part": "情境", "answer": "上周三夜里报警", "session": "s2"}],
            session="s2",
        )
        held = self.store.answers_for(self.card)
        self.assertEqual("上周三夜里报警", held["situation"]["answer"])
        self.assertEqual("两个同事要多跑一趟", held["price"]["answer"],
                         "the other part was not touched")
        events = [event for event in self.store.history(self.card)["events"]
                  if event["event"] == "promote_answers"]
        self.assertEqual("上周二夜里报警，我已经回家了",
                         events[-1]["details"]["from"]["situation"]["answer"])

    def test_unpromote_takes_one_answer_off_and_keeps_the_record(self):
        self.store.promote_answers(self.card, self.answers(), session="s1")
        self.store.unpromote_answer(self.card, "情境", "那次说的不是这条", session="s1")
        held = self.store.answers_for(self.card)
        self.assertNotIn("situation", held)
        self.assertIn("price", held)
        events = [event for event in self.store.history(self.card)["events"]
                  if event["event"] == "unpromote_answer"]
        self.assertEqual("上周二夜里报警，我已经回家了",
                         events[0]["details"]["from"]["answer"])
        self.assertEqual(1, self.store.show(self.card)["candidate"]["version"])

    def test_unpromoting_something_absent_is_refused(self):
        from dojo.storage import DojoError
        with self.assertRaises(DojoError):
            self.store.unpromote_answer(self.card, "off", "没有这件")

    def test_an_unknown_part_is_refused(self):
        from dojo.storage import DojoError
        with self.assertRaises(DojoError):
            self.store.promote_answers(self.card, [{"part": "动作", "answer": "x"}])

    def test_the_search_row_carries_them_and_show_does_too(self):
        self.store.promote_answers(self.card, self.answers(), session="s1")
        # The gate has to let the card through before a row exists to inspect: promotion
        # says nothing about discussability, so the test does that as a reader would.
        self.store.confirm(self.card, "值得讨论，不表示为真")
        row = self.store.retrieve("报警", for_reading=True)["results"][0]
        self.assertEqual("上周二夜里报警，我已经回家了", row["answers"]["situation"]["answer"])
        self.assertIn("answers", row.get("matched_in") or [])
        self.assertTrue(self.store.show(self.card)["answers"])


class TheWordsOnAScreen(unittest.TestCase):
    def card(self, **extra):
        state = {
            "statement": "一句话",
            "answers": {
                "situation": {"answer": "那次是周三", "session": "s1", "at": "2026-11-28T00:00:00+00:00"},
            },
        }
        state.update(extra)
        return state

    def test_it_prints_the_answer_and_says_which_part_and_where_it_came_from(self):
        text = "\n".join(answers_module.screen_lines(self.card()))
        self.assertIn("他的话", text)
        self.assertIn("那次是周三", text)
        self.assertIn("情境", text)
        self.assertIn("s1", text)
        self.assertIn("不是这张卡措辞的一部分", text)

    def test_parts_with_nothing_are_named_as_empty_not_as_his_silence(self):
        text = "\n".join(answers_module.screen_lines(self.card()))
        self.assertIn("这张卡上没有他的话", text)
        self.assertIn("不等于他没有说过", text)

    def test_a_card_with_no_answers_prints_no_line_at_all(self):
        self.assertEqual([], answers_module.screen_lines({"statement": "一句话"}))

    def test_each_answer_offers_a_command_that_opens_its_own_record(self):
        """The way back has to be a file a reader can open, with the library named.

        On fdd55ff the stored `trace` was `datetime.now().isoformat()` -- the time it was
        promoted -- so `show` handed a reader a field they could not open (found in
        review). The value is now the session's record path, and the screen turns it into
        a paste-able `transcript` command carrying this library.
        """
        card = self.card()
        card["answers"]["situation"]["provenance"] = "discussion"
        card["answers"]["situation"]["trace"] = "/abs/sessions/discuss-abc.jsonl"
        text = "\n".join(answers_module.screen_lines(card, database="/abs/lib.sqlite3"))
        self.assertIn("transcript", text)
        self.assertIn("discuss-abc.jsonl", text)
        self.assertIn("/abs/lib.sqlite3", text)
        self.assertIn("回看说这句的那一场", text)

    def test_a_hand_kept_answer_is_named_as_hand_kept_not_as_a_conversation(self):
        """`promote` typed by hand has no session and no moment; it must not borrow one."""
        card = self.card()
        card["answers"]["situation"] = {"answer": "那次是周三", "provenance": "manual"}
        text = "\n".join(answers_module.screen_lines(card, database="/abs/lib.sqlite3"))
        self.assertIn("手工附上", text)
        self.assertNotIn("transcript", text)
        self.assertNotIn("来自会话", text)

    def test_a_row_from_an_older_library_says_the_source_was_not_recorded(self):
        """No provenance, no session: say that, rather than pick one of the two stories."""
        text = "\n".join(answers_module.screen_lines(self.card()))
        self.assertIn("来源未记录", text)
        self.assertNotIn("手工附上", text)
        self.assertNotIn("来自会话", text)

    def test_an_answer_that_never_reached_the_file_gets_no_command(self):
        """The record died between answers: the way back must not be offered.

        Review on this slice: after the second answer's write failed, all four lines still
        said 回看说这句的那一场, and opening that file found only the first one. A command
        that lands on the wrong evidence is worse than no command.
        """
        card = self.card()
        row = card["answers"]["situation"]
        row["provenance"] = "discussion"
        row["trace"] = "/abs/sessions/discuss-abc.jsonl"
        row["recorded"] = 0
        text = "\n".join(answers_module.screen_lines(card, database="/abs/lib.sqlite3"))
        self.assertIn("没有写进那一场的记录文件", text)
        self.assertNotIn("回看说这句的那一场", text)
        self.assertNotIn("transcript", text)
        # The session id is still named, so the sentence is not orphaned.
        self.assertIn("s1", text)

    def test_a_session_that_kept_no_record_says_so_instead_of_nothing(self):
        card = self.card()
        card["answers"]["situation"]["provenance"] = "discussion"
        card["answers"]["situation"]["trace"] = ""
        text = "\n".join(answers_module.screen_lines(card))
        self.assertIn("没有留下记录文件", text)
        self.assertNotIn("transcript", text)

    def test_the_note_counts_and_does_not_judge(self):
        note = answers_module.screen_note(self.card())
        self.assertIn("1 件是他说的", note)
        self.assertIn("有没有答到点上，库里不判", note)

    def test_the_model_shape_says_what_it_is(self):
        shaped = answers_module.for_model(self.card())
        self.assertEqual("那次是周三", shaped["situation"]["answer"])
        self.assertIn("不是它的措辞", shaped["situation"]["is"])
        self.assertEqual({}, answers_module.for_model({"statement": "一句话"}))

    def test_malformed_entries_are_dropped_rather_than_printed(self):
        held = answers_module.stored({"answers": {"situation": {"answer": "  "},
                                                  "off": "not an object",
                                                  "unknown": {"answer": "x"}}})
        self.assertEqual({}, held)


if __name__ == "__main__":
    unittest.main()
