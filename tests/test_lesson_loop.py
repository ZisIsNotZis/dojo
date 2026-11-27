"""The reason he changed his mind reaches whoever acts later.

Measured before this file existed: a card walked through accept -> challenge -> revise
-> accept held the counterexample and the new wording on every reader surface, and the
`revise` event's `reason` and `from_statement` on none of them. `show --history` had
them; an export does not open `show --history`.

Each test here is a way for that gap to come back.
"""
import tempfile
import unittest
from pathlib import Path

from dojo.storage import Store

OLD = "持续检查交给系统自己跑，人只在想推翻的时候回来。"
NEW = "持续检查交给系统自己跑，但只在检查结果会打断他时才叫醒他。"
DOUBT = "第三次在同一团队反而更糟：检查结果他根本没看。"
WHY = "原来那句没写清楚什么时候该叫醒他，所以第三次更糟。"
QUERY = "持续检查 系统 自己 跑 回来 推翻"


class LessonLoopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "dojo.sqlite3")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def card(self, statement=OLD, source_id="s1", group="gA", session="sess-A"):
        added = self.store.add(
            statement, "abstract_idea",
            scope=["他抽身之后"], premises=["系统能自己跑检查"],
            alternatives=["把检查留给人"], contradictions=["检查必须发生在世界里时"],
            unknowns=["他会不会来看回执"],
            sources=[{"id": source_id, "type": "claimed_firsthand",
                      "verification": "unverified", "independence_group": group,
                      "claim": "他这样做过两次", "scope_note": "两次都在同一团队"}],
            session=session,
        )
        return added["id"]

    def accept(self, cid, session):
        """What a session does when he agrees: record it, then confirm discussability."""
        self.store.record_acceptance(cid, session, path="discuss_conclusion")
        self.store.confirm(cid, "他在会话里认可了这句", session=session)

    def revise(self, cid, statement=NEW, reason=WHY):
        return self.store.revise(
            cid, statement, reason,
            scope=["他抽身之后"], premises=["系统能自己跑检查"],
            alternatives=["把检查留给他自己"], contradictions=[DOUBT],
            unknowns=["打断多少次会变成骚扰"], session="sess-B",
        )

    def walked(self):
        """The whole story: arrived at, doubted, narrowed, and accepted again."""
        cid = self.card()
        self.accept(cid, "sess-A")
        self.store.challenge(cid, DOUBT, source={
            "id": "s2", "type": "claimed_firsthand", "verification": "unverified",
            "independence_group": "gB", "claim": "第三次照做反而更糟",
            "scope_note": "同一团队的第三次"})
        self.revise(cid)
        self.accept(cid, "sess-C")
        return cid

    # ---- what the later reader is handed -------------------------------------

    def test_search_hands_the_later_reader_why_he_changed_his_mind(self):
        cid = self.walked()
        results = self.store.retrieve(QUERY)["results"]
        self.assertTrue(results, "改写并被接受之后，这句话应当是能被检索到的")
        basis = results[0]["revision_basis"]
        self.assertEqual(WHY, basis["reason"])
        self.assertEqual(OLD, basis["left_wording"])
        self.assertTrue(basis["revised_at"])

    def test_broadcast_and_show_carry_the_same_reason(self):
        cid = self.walked()
        cast = self.store.broadcast(QUERY)["results"]
        self.assertTrue(cast)
        self.assertEqual(WHY, cast[0]["revision_basis"]["reason"])
        # Beside `candidate`, like `time_basis`: `candidate` stays the stored state.
        shown = self.store.show(cid)
        self.assertEqual(WHY, shown["revision_basis"]["reason"])
        self.assertNotIn("revision_basis", shown["candidate"])

    def test_the_frozen_prompt_says_the_sentence_was_replaced_and_why(self):
        cid = self.walked()
        exported = self.store.export_prompt("c", [cid], 8000, self.root / "exports")
        prompt = Path(exported["path"]).read_text(encoding="utf-8")
        self.assertIn(NEW, prompt)
        self.assertIn(OLD, prompt, "被改掉的那句必须出现，否则读者不知道换过")
        self.assertIn(WHY, prompt)
        # A reader has to be able to tell the old sentence is not the current claim.
        #
        # Reworded by the boundary slice: "这句是他后来改掉的" named an author the `revise`
        # row does not store (a reader or a script can revise a card), and the screen's
        # twin of this line named a direction -- "它比更早那句窄" -- that the row does not
        # record either. What the row does record is that this wording replaced that one,
        # and the reason it was given, so that is what the line says.
        self.assertIn("库里记着现在的说法换掉的是这一句；不是现在的说法。", prompt)
        self.assertNotIn("他后来改掉的", prompt)

    # ---- it speaks only for the wording the card holds now ---------------------

    def test_a_second_revision_does_not_leave_the_first_reason_attached(self):
        cid = self.walked()
        self.revise(cid, "持续检查交给系统自己跑，但每天至多叫醒他一次。", "第二次的理由：天天打断他受不了。")
        basis = self.store.revision_basis(cid)["revision_basis"]
        self.assertEqual("第二次的理由：天天打断他受不了。", basis["reason"])
        self.assertEqual(NEW, basis["left_wording"])
        # The earlier reason is not deleted -- history still has it.
        reasons = [event["details"].get("reason") for event in self.store.history(cid)["events"]
                   if event["event"] == "revise"]
        self.assertIn(WHY, reasons)

    def test_a_card_he_never_revised_keeps_exactly_the_bytes_it_had(self):
        cid = self.card()
        self.accept(cid, "sess-A")
        self.assertEqual({}, self.store.revision_basis(cid))
        self.assertNotIn("revision_basis", self.store.show(cid))
        row = self.store.retrieve("持续检查 系统 自己 跑")["results"][0]
        self.assertNotIn("revision_basis", row)
        prompt = Path(self.store.export_prompt(
            "c", [cid], 8000, self.root / "exports")["path"]).read_text(encoding="utf-8")
        self.assertNotIn("revision_reason", prompt)

    def test_the_same_revision_arriving_again_states_no_new_reason(self):
        cid = self.card()
        self.accept(cid, "sess-A")
        self.revise(cid)
        before = self.store.revision_basis(cid)
        # The same sentence for the same reason, back to back: nothing about the card
        # moves, so the ledger writes `revise.repeat` and this key must not change.
        self.revise(cid)
        events = [event["event"] for event in self.store.history(cid)["events"]]
        self.assertIn("revise.repeat", events, "重放应当被记成重放，本测试依赖这一点")
        self.assertEqual(before, self.store.revision_basis(cid))
        self.assertEqual(WHY, self.store.revision_basis(cid)["revision_basis"]["reason"])

    def test_a_reason_changed_after_re_acceptance_is_read_as_a_new_reason(self):
        """Not a replay: the card had been accepted again, and revising withdraws that."""
        cid = self.walked()
        self.revise(cid)
        events = [event["event"] for event in self.store.history(cid)["events"]]
        self.assertNotIn("revise.repeat", events)
        self.assertEqual(WHY, self.store.revision_basis(cid)["revision_basis"]["reason"])

    # ---- the limit this slice does not cross ---------------------------------

    def test_a_challenged_card_is_still_not_handed_to_a_later_reader(self):
        """Not a defect this slice fixes: a challenged card is not discussable.

        Pinned so nobody reads the tests above as "the doubt is now in retrieval": the
        doubt reaches a reader only once he has accepted a wording again. Between the
        challenge and that acceptance, all three exits hand back nothing.
        """
        cid = self.card()
        self.accept(cid, "sess-A")
        self.store.challenge(cid, DOUBT)
        self.revise(cid)
        self.assertEqual([], self.store.retrieve(QUERY)["results"])
        self.assertEqual([], self.store.broadcast(QUERY)["results"])
        with self.assertRaises(Exception):
            self.store.export_prompt("c", [cid], 8000, self.root / "exports")

    # ---- the claim is his, not the library's ---------------------------------

    def test_the_reason_is_carried_verbatim_and_not_restated(self):
        cid = self.walked()
        basis = self.store.revision_basis(cid)["revision_basis"]
        # Not trimmed, not summarised, not turned into a conclusion.
        self.assertIsInstance(basis["reason"], str)
        self.assertEqual(WHY, basis["reason"])
        self.assertEqual(1, len([key for key in basis if key == "reason"]))


if __name__ == "__main__":
    unittest.main()
