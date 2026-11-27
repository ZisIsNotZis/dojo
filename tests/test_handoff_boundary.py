"""What the next discussion is shown before the model says anything.

Three claims are checked here, each one measured on the standard CLI before it was fixed
(`.scratch/3419/probe_story.py` and the supervisor's two reproducers):

  1. the card's limits -- when it holds, when it does not, what is still unmeasured --
     reach the person's screen, not only the model's request. The model had all three and
     the screen had none, which is the one arrangement where the boundary cannot do its
     job: the person decides whether to transfer the sentence, and they were reading a
     claim without its conditions.
  2. the status word does not assert an acceptance fact. `draft` printed "这一句还没有
     人认可" over a card whose ledger held `wording_accepted` with `acceptance_path=
     discuss_conclusion`, so a session that had just agreed to the sentence told the next
     session nobody had.
  3. the revision line does not assert a direction or an author. `revise` records what
     the wording moved from and the reason it was given; it records neither whether the
     change narrowed or generalised the claim, nor who ran it.

The general rule these all belong to: a screen may state what the program checked, and
nothing else.
"""
import io
import json
import tempfile
import unittest
from pathlib import Path

from dojo.discuss import (
    acceptance_line, boundary_lines, handoff_block, handoff_for_model, run_discuss,
)
from dojo.storage import Store


STATEMENT = "值班通知都先等两次失败再呼叫负责人。"
NARROW = "只有普通日报才等两次失败再呼叫负责人。"
SCOPE = "只适用已经失去一个采样周期的日报。"
COUNTER = "冷库温度超过安全线时不能等待第二次。"
UNKNOWN = "交接班期间能否容忍这段延迟还没有测。"
PREMISE = "系统能自己判定连续失败"
REASON = "这次想把做法试着推广到所有值班通知。"


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


def last_context(client):
    for message in reversed(client.calls[-1]):
        if message["role"] == "user":
            return message["content"]
    raise AssertionError("no user message in the last request")


class BoundaryCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "dojo.sqlite3")
        self.addCleanup(self.store.close)

    def card(self, *, statement=STATEMENT) -> str:
        """One card with all four limits, and its real id -- `add` generates one."""
        added = self.store.add(
            statement=statement, kind="experience_claim",
            scope=[SCOPE], premises=[PREMISE], contradictions=[COUNTER],
            unknowns=[UNKNOWN],
            sources=[{"id": "src-1", "type": "claimed_firsthand", "verification": "unverified",
                      "independence_group": "gA", "claim": "他这样值过两次班",
                      "scope_note": "两个班次都在同一个组"}],
            session="sess-A",
        )
        return added["id"]


class TheLimitsReachThePerson(BoundaryCase):
    def test_the_three_limits_are_printed_for_the_person_not_only_the_model(self):
        """The measured defect: scope, counterexample and unknown went to the model only."""
        card = self.card()
        shown = self.store.show(card)
        block = handoff_block(shown["candidate"], shown.get("revision_basis"))
        model_text = handoff_for_model(shown["candidate"], shown.get("revision_basis"))
        for text in (block, model_text):
            for value in (SCOPE, COUNTER, UNKNOWN, PREMISE):
                self.assertIn(value, text, value)

    def test_each_limit_is_labelled_with_what_it_answers(self):
        """A bare list of four sentences would not tell a reader which is a condition and
        which is a reason the rule already fails."""
        card = self.card()
        shown = self.store.show(card)
        block = handoff_block(shown["candidate"], shown.get("revision_basis"))
        for label in ("什么时候成立", "什么时候不成立", "还没定的是", "它靠这些前提"):
            self.assertIn(label, block, label)

    def test_an_absent_limit_gets_no_line(self):
        """The same rule `time_basis` follows: an empty field is not "he ruled it out"."""
        card = self.store.add(statement=STATEMENT, kind="experience_claim",
                              scope=[SCOPE], session="sess-A")
        shown = self.store.show(card["id"])
        lines = boundary_lines(shown["candidate"])
        self.assertEqual(1, len(lines))
        self.assertNotIn("什么时候不成立", "\n".join(lines))
        self.assertNotIn("还没定的是", "\n".join(lines))
        self.assertNotIn("它靠这些前提", "\n".join(lines))

    def test_a_counterexample_added_by_a_challenge_is_shown_to_the_person(self):
        """A doubt is stored in `contradictions`, so it travels with the limit line. The
        measured defect printed the status only: 被人质疑过 with nothing saying what the
        doubt was."""
        card = self.card()
        self.store.challenge(card, COUNTER)
        shown = self.store.show(card)
        block = handoff_block(shown["candidate"], shown.get("revision_basis"))
        self.assertIn(COUNTER, block)
        self.assertIn("什么时候不成立", block)

    def test_the_alternatives_stay_off_the_screen(self):
        """Deliberate: a route the card did not take does not help somebody decide about
        their own case, and five lines in front of a session that just opened is a wall.
        `show` still carries it. The model keeps it, because it is asked to compare."""
        card = self.store.add(statement=STATEMENT, kind="experience_claim", scope=[SCOPE],
                              alternatives=["把提醒留给人手"], session="sess-A")["id"]
        shown = self.store.show(card)
        block = handoff_block(shown["candidate"], shown.get("revision_basis"))
        self.assertNotIn("把提醒留给人手", block)
        self.assertIn("把提醒留给人手",
                      handoff_for_model(shown["candidate"], shown.get("revision_basis")))


class TheStatusWordClaimsNothing(BoundaryCase):
    def test_a_draft_the_ledger_shows_was_accepted_does_not_say_nobody_accepted_it(self):
        """The measured contradiction: status `draft` printed "这一句还没有人认可" while
        `time_basis.acceptance_path` said `discuss_conclusion`."""
        card = self.card()
        self.store.record_acceptance(card, "sess-A", path="discuss_conclusion")
        shown = self.store.show(card)
        basis = shown.get("time_basis") or {}
        acceptance = {"accepted": bool(basis.get("accepted_at")),
                      "path": basis.get("acceptance_path"),
                      "accepted_at": basis.get("accepted_at")}
        block = handoff_block(shown["candidate"], shown.get("revision_basis"),
                              acceptance=acceptance)
        self.assertNotIn("还没有人认可", block)
        self.assertIn("库里有这套说法", block)
        self.assertIn("讨论里认可", block)

    def test_a_missing_acceptance_record_is_reported_as_a_gap_in_the_record(self):
        """No record is a fact about the ledger. A card written by hand may well have been
        agreed to in a room, so the screen says which of the two it knows."""
        card = self.card()
        shown = self.store.show(card)
        line = acceptance_line({"accepted": False})
        self.assertIn("库里没有", line)
        self.assertIn("不等于没人认可过它", line)

    def test_not_asking_prints_nothing(self):
        """A caller that did not read the ledger must not be answered for."""
        self.assertEqual("", acceptance_line(None))
        self.assertEqual("", acceptance_line({}))

    def test_the_model_is_told_what_the_screen_is_told(self):
        """One reading, two renderers: otherwise the person and the model disagree about
        the same card, which is this project's recurring defect one layer out."""
        card = self.card()
        self.store.record_acceptance(card, "sess-A", path="discuss_conclusion")
        shown = self.store.show(card)
        basis = shown.get("time_basis") or {}
        acceptance = {"accepted": True, "path": basis.get("acceptance_path"),
                      "accepted_at": basis.get("accepted_at")}
        text = handoff_for_model(shown["candidate"], shown.get("revision_basis"),
                                 acceptance=acceptance)
        self.assertIn("认可记录", text)
        self.assertIn("discuss_conclusion", text)

    def test_confirming_a_card_is_not_the_same_act_as_accepting_its_wording(self):
        """Both facts can be true at once and they must not read as a contradiction:
        a facilitator marking a card discussable writes no acceptance record."""
        card = self.card()
        self.store.confirm(card, "值得讨论；不表示为真", session="sess-B")
        shown = self.store.show(card)
        block = handoff_block(shown["candidate"], shown.get("revision_basis"),
                              acceptance={"accepted": False})
        self.assertIn("可讨论", block)
        self.assertNotIn("有人认可它值得讨论", block)
        self.assertIn("库里没有这套说法", block)

    def test_the_handout_row_carries_the_acceptance_fact_so_resume_agrees(self):
        """Resume rebuilds the handout from the trace, never from the library: the row is
        the version this conversation is about. If the fact is not on the row, the second
        half of one session prints a different sentence than the first half."""
        card = self.card()
        self.store.record_acceptance(card, "sess-A", path="discuss_conclusion")
        client = FakeClient([
            {"answer": "接着这句。", "candidate": None, "user_stance": "neutral"},
            {"answer": "继续说。", "candidate": None, "user_stance": "neutral"},
        ])
        run_discuss(self.store, client=client, card=card,
                    read_line=read_lines(["接着上次那条说"]),
                    output=io.StringIO(), environ={})
        handout = [row for path in sorted((self.root / "sessions").glob("*.jsonl"))
                   for row in (json.loads(line) for line in path.read_text().splitlines())
                   if row.get("event") == "handout"][0]
        # Asserted as a shape first: with the field dropped, indexing it would raise
        # and the red arm would look like a crash instead of a failed check. A crash is
        # not evidence that any check saw the defect.
        self.assertIn("acceptance", handout)
        self.assertIsInstance(handout["acceptance"], dict)
        self.assertTrue(handout["acceptance"].get("accepted"))
        self.assertEqual("discuss_conclusion", handout["acceptance"].get("path"))
        self.assertIn(COUNTER, handout["fields"]["contradictions"])


class TheSourcesAreReadableToo(BoundaryCase):
    def test_what_the_record_claims_reaches_the_person(self):
        """The supervisor's reproducer reported `source: false` on screen while the model
        was given the claim: the count-and-type line said how many and how checked, and
        never what the evidence was."""
        card = self.card()
        shown = self.store.show(card)
        block = handoff_block(shown["candidate"], shown.get("revision_basis"))
        self.assertIn("他这样值过两次班", block)
        self.assertIn("两个班次都在同一个组", block)

    def test_the_count_line_still_guards_against_reading_records_as_people(self):
        card = self.card()
        shown = self.store.show(card)
        block = handoff_block(shown["candidate"], shown.get("revision_basis"))
        self.assertIn("不是人数", block)

    def test_more_records_than_the_screen_shows_are_counted_not_summarised(self):
        """A bibliography would bury the limits; silence would hide a record. So the
        remainder is counted, and the number is a fact about the store."""
        card = self.card()
        for index in range(6):
            self.store.attach_source(card, {
                "id": "src-extra-" + str(index), "type": "secondhand_report",
                "verification": "unverified", "independence_group": "g" + str(index),
                "claim": "传来的第 " + str(index) + " 份说法",
            }, session="sess-B")
        shown = self.store.show(card)
        from dojo.discuss import SCREEN_SOURCE_LINES, source_lines
        lines = source_lines(shown["candidate"])
        self.assertEqual(SCREEN_SOURCE_LINES + 1, len(lines))
        self.assertIn("还有 3 条", lines[-1])


class TheRevisionLineReportsTheRecord(BoundaryCase):
    def test_a_widened_card_is_not_described_as_narrowed(self):
        """Reproduced by the supervisor on the standard CLI: a card revised from 只有普通
        日报才等两次 to 值班通知都先等两次 was announced as "它比更早那句窄" and then
        handed the reason for generalising it."""
        card = self.card(statement=NARROW)
        self.store.revise(card, STATEMENT, REASON)
        shown = self.store.show(card)
        block = handoff_block(shown["candidate"], shown.get("revision_basis"))
        for word in ("更早那句窄", "比更早", "改窄"):
            self.assertNotIn(word, block, word)
        self.assertIn("之前是", block)
        self.assertIn(NARROW, block)
        self.assertIn(REASON, block)

    def test_the_reason_is_not_attributed_to_a_person(self):
        """`revise` is also run by a reader or a script and the row records no author, so
        "他改主意时说的是" was an authorship claim the record does not support."""
        card = self.card(statement=NARROW)
        self.store.revise(card, STATEMENT, REASON)
        shown = self.store.show(card)
        for text in (handoff_block(shown["candidate"], shown.get("revision_basis")),
                     handoff_for_model(shown["candidate"], shown.get("revision_basis"))):
            self.assertNotIn("改主意", text)
            self.assertNotIn("他的理由", text)
            self.assertIn("改动理由", text)

    def test_the_export_does_not_name_an_author_or_a_direction_either(self):
        """The third exit for the same two facts, and the one a downstream participant
        actually reads."""
        card = self.card(statement=NARROW)
        self.store.revise(card, STATEMENT, REASON)
        # Mode C is the exit that carries excerpts, and it refuses a card whose whole
        # provenance is one session -- so this one has to arrive twice, which is also
        # the state the export path was written for.
        self.store.attach_source(card, {
            "id": "src-2", "type": "artifact_observation", "verification": "unverified",
            "independence_group": "gB", "claim": "第二班的记录里也这样回过",
        }, session="sess-B")
        self.store.confirm(card, "值得讨论", session="sess-B")
        exported = self.store.export_prompt("c", [card], 20_000, str(self.root / "out"))
        text = Path(exported["path"]).read_text(encoding="utf-8")
        self.assertIn("revision_reason: " + REASON, text)
        self.assertNotIn("他改主意", text)
        self.assertNotIn("是他后来改掉的", text)

    def test_the_screen_says_a_change_is_a_new_arrival_without_naming_one_direction(self):
        card = self.card()
        shown = self.store.show(card)
        block = handoff_block(shown["candidate"], shown.get("revision_basis"))
        self.assertIn("改变它的条件", block)
        self.assertNotIn("改窄它", block)


if __name__ == "__main__":
    unittest.main()
