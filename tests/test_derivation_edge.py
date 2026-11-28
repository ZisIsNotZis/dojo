"""The edge a discussion writes, and the two ways it must not be read.

Three separate promises, each one measured on a real library:

  1. a session handed a card (`--card X`) that ends on a different wording records that
     the new card came out of a session holding X -- in the same transaction, with no
     source added and no status moved (`Store.add(..., derived_from=...)`);
  2. a `derived_from` row that the *ledger* does not attribute to such a session is a
     relation, not a discussion: `link` refuses the type, and a library that already
     holds one (written by the earlier build) prints it as a relation -- the supervisor's
     reproducer `/var/tmp/dojo-lineage-provenance.3dtLjtD6`;
  3. finding that edge costs one table read per search, not one per result row -- the
     supervisor's reproducer `/var/tmp/dojo-lineage-scale.WmglSP`, where 300 cards meant
     301 reads and 600 cards meant 601.
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from dojo import discuss
from dojo.finding import search_screen
from dojo.storage import DojoError, Store


def card(store: Store, identifier: str, statement: str, **fields) -> dict:
    return store.add(statement, fields.pop("kind", "abstract_idea"),
                     candidate_id=identifier, scope=["某个范围"], **fields)


class DerivationEdgeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Path(self.directory.name) / "lib.sqlite3"
        self.store = Store(self.db)
        self.addCleanup(self.store.close)

    def test_the_new_card_records_which_card_the_session_was_holding(self) -> None:
        origin = card(self.store, "d-origin", "原来那一句。")
        child = self.store.add("后来那一句。", "abstract_idea", scope=["某个范围"],
                               derived_from="d-origin")
        self.assertEqual([item["type"] for item in child["relations"]], ["derived_from"])
        self.assertEqual([item["target"] for item in child["relations"]], [origin["id"]])
        # The old card is not rewritten, restatused or joined from its own side.
        self.assertEqual(self.store.show("d-origin")["candidate"]["relations"], [])
        self.assertEqual(self.store.show("d-origin")["candidate"]["status"], "draft")

    def test_the_edge_adds_no_source_and_no_independence(self) -> None:
        card(self.store, "d-origin", "原来那一句。")
        source = {"type": "claimed_firsthand", "claim": "他说过", "verification": "unverified",
                  "independence_group": "s-one"}
        child = self.store.add("后来那一句。", "abstract_idea", scope=["某个范围"],
                               derived_from="d-origin", sources=[source], session="s-one")
        self.assertEqual(len(child["sources"]), 1)
        self.assertEqual(child["sessions"], ["s-one"])

    def test_a_card_cannot_come_out_of_itself(self) -> None:
        with self.assertRaises(DojoError):
            self.store.add("同一句。", "abstract_idea", scope=["某个范围"],
                           candidate_id="d-same", derived_from="d-same")

    def test_the_edge_points_at_the_survivor_of_a_merge(self) -> None:
        card(self.store, "d-old", "被合并掉的一句。")
        card(self.store, "d-keep", "留下来的那一句。")
        self.store.merge("d-old", "d-keep", confirmed=True, reason="同一条")
        child = self.store.add("从被合并那条长出来的。", "abstract_idea",
                               scope=["某个范围"], derived_from="d-old")
        self.assertEqual(child["relations"][0]["target"], "d-keep")

    def test_the_add_row_records_the_edge(self) -> None:
        card(self.store, "d-origin", "原来那一句。")
        self.store.add("后来那一句。", "abstract_idea", scope=["某个范围"],
                       derived_from="d-origin")
        events = self.store.history(
            [item["id"] for item in self.store.list_candidates()
             if item["statement"] == "后来那一句。"][0])["events"]
        self.assertEqual([event["details"].get("derived_from") for event in events
                          if event["event"] == "add"], ["d-origin"])

    def test_link_refuses_to_manufacture_a_discussion(self) -> None:
        card(self.store, "d-a", "第一句。")
        card(self.store, "d-b", "第二句。")
        with self.assertRaises(DojoError):
            self.store.link("d-b", "derived_from", "d-a", "手打一条")
        # The person-written relations are untouched.
        self.assertEqual(self.store.link("d-b", "supports", "d-a", "一句支持另一句")["relations"][0]["type"],
                         "supports")

    def test_a_relation_the_ledger_does_not_attribute_is_not_called_a_discussion(self) -> None:
        """The supervisor's reproducer, reproduced: two confirmed cards, joined by hand."""
        card(self.store, "railway-note", "The railway timetable should show transfer distance.")
        card(self.store, "museum-note", "A museum ticket should say when its QR expires.")
        for identifier in ("railway-note", "museum-note"):
            self.store.confirm(identifier, "worth discussing")
        # An older library already holds the row; write it the way that build did.
        state = self.store._get("museum-note")
        state["relations"] = [{"type": "derived_from", "target": "railway-note",
                               "note": "I am adding a reference between two stored notes."}]
        self.store._write(state, "link", {"reason": "seed"})
        result = self.store.retrieve("railway timetable", for_reading=True)
        row = next(row for row in result["results"] if row["id"] == "railway-note")
        later = row.get("derived_later") or []
        self.assertEqual([item["id"] for item in later], ["museum-note"])
        self.assertEqual(later[0]["basis"], "recorded_relation")
        screen = "\n".join(search_screen(result, database=str(self.db)))
        self.assertNotIn("后来有一场带着这条继续谈", screen)
        self.assertIn("不是一场讨论留下的", screen)
        self.assertIn("museum-note", screen)
        # And nothing on the other card claims a session either.
        other = self.store.retrieve("museum", for_reading=True)
        other_rows = [row for row in (other.get("results") or [])
                      + (other.get("withheld") or []) if row["id"] == "museum-note"]
        self.assertEqual(len(other_rows), 1, "the second card should be on the screen")
        self.assertNotIn("derivation", other_rows[0])

    def test_a_discussion_that_really_wrote_a_version_still_reads_as_one(self) -> None:
        origin = card(self.store, "d-origin", "原来那一句。")
        # Confirmed, so it is a handed-over result and not a withheld row: the gate's
        # refusal of an unconfirmed draft is a different promise, tested elsewhere.
        self.store.confirm("d-origin", "worth discussing")
        self.store.add("后来那一句。", "abstract_idea", scope=["某个范围"],
                       derived_from="d-origin")
        later = next(item for item in self.store.list_candidates()
                     if item["statement"] == "后来那一句。")
        self.assertEqual(self.store.derivation(later["id"]), origin["id"])
        result = self.store.retrieve("原来", for_reading=True)
        row = next(row for row in result["results"] if row["id"] == "d-origin")
        self.assertEqual(row["derived_later"][0]["basis"], "discussion")

    def test_one_search_reads_the_candidate_table_once(self) -> None:
        """The supervisor measured 301/601 reads for one search over 300/600 cards."""
        self.store.add("Observe railway inspection during the quiet shift.", "abstract_idea",
                       candidate_id="sample-0000")
        with self.store.transaction():
            one = self.store._get("sample-0000")
            for offset in range(1, 200):
                self.store._insert_candidate(
                    dict(one, id="sample-%04d" % offset,
                         statement=("Observe railway inspection during the quiet shift "
                                    "for platform %d." % offset)), "add", {})
        reads = [0]

        def trace(statement: str) -> None:
            if statement == "SELECT state_json FROM candidates ORDER BY id":
                reads[0] += 1

        self.store.connection.set_trace_callback(trace)
        try:
            result = self.store.retrieve("railway", limit=10, for_reading=True)
        finally:
            self.store.connection.set_trace_callback(None)
        self.assertEqual(reads[0], 1)
        self.assertEqual(len(result["withheld"]), 200)

    def test_a_reading_row_carries_the_basis_and_the_model_row_does_not(self) -> None:
        card(self.store, "d-origin", "原来那一句。")
        self.store.add("后来那一句。", "abstract_idea", scope=["某个范围"],
                       derived_from="d-origin")
        self.store.confirm("d-origin", "worth discussing")
        as_read = self.store.retrieve("原来", for_reading=True)
        rows = [row for row in (as_read.get("results") or [])
                + (as_read.get("withheld") or []) if row["id"] == "d-origin"]
        self.assertEqual(len(rows), 1)
        self.assertIn("derived_later", rows[0])
        plain = self.store.retrieve("原来")
        plain_rows = [row for row in (plain.get("results") or [])
                      + (plain.get("withheld") or []) if row["id"] == "d-origin"]
        self.assertEqual(len(plain_rows), 1)
        self.assertFalse({"derived_later", "derivation"} & set(plain_rows[0]))


class ResumeReplayTest(unittest.TestCase):
    """A handout row with no derivation key must replay, and must claim nothing.

    The full suite caught this and the evidence walk could not: a resumed session replays
    the `handout` row through `_load_resume_trace`, and the key added for the derivation
    basis was read without being initialised -- so every resume raised
    `UnboundLocalError` (13 suites went red at once). Rows written before the key existed
    are exactly the rows a resume has to keep working on.
    """

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        # The trace validator insists on the program's own session-id shape.
        self.path = Path(self.directory.name) / ("discuss-" + "a" * 32 + ".jsonl")

    def write(self, handout: dict, *, ending: dict | str | None = None) -> None:
        handout = {"revision_basis": None, **handout}
        # The program's own round shape: the validator names every key it needs, and a
        # hand-built row that leaves one out is refused as "格式不符" before the handout
        # is ever reached.
        rows = [
            {"event": "round", "seq": 1, "at": "2026-11-28T00:00:00+00:00",
             "user": "你好", "answer": "你好。", "candidate": None, "stance": "neutral",
             "reason": "no_pending", "decision": "none", "requests_sent": 1,
             "pending_after": None},
            {"event": "handout", **handout},
            {"event": "session_end", "reason": "eof", "saved": [], "requests_sent": 1},
        ]
        self.path.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
            encoding="utf-8")

    def test_a_handout_row_written_before_the_key_existed_still_resumes(self) -> None:
        self.write({"candidate": "d-x", "statement": "这句。", "status": "draft",
                    "at": "2026-11-28T00:00:00+00:00"})
        state = discuss._load_resume_trace(self.path)
        self.assertIsNone(state["handed_derivation"])
        self.assertEqual(state["handed"]["id"], "d-x")

    def test_a_recorded_derivation_survives_the_replay(self) -> None:
        self.write({"candidate": "d-x", "statement": "这句。", "status": "draft",
                    "at": "2026-11-28T00:00:00+00:00", "derivation": "d-origin"})
        self.assertEqual(discuss._load_resume_trace(self.path)["handed_derivation"], "d-origin")

    def test_the_resumed_handout_says_the_same_thing_the_live_one_did(self) -> None:
        self.write({"candidate": "d-x", "statement": "这句。", "status": "draft",
                    "at": "2026-11-28T00:00:00+00:00", "derivation": "d-origin",
                    # `fields` deliberately carries only the content fields; the handout
                    # rebuilds the edge from the row's own derivation, which is why this
                    # test has no `relations` in `fields`.
                    "fields": {"statement": "这句。", "kind": "abstract_idea",
                               "scope": ["某个范围"]}})
        state = discuss._load_resume_trace(self.path)
        screen = discuss.handoff_block(state["handed"], state["handed_basis"],
                                       derivation=state["handed_derivation"],
                                       database="/tmp/lib.sqlite3")
        self.assertIn("讨论里写下的", screen)
        self.assertIn("--db /tmp/lib.sqlite3 show d-origin", screen)


class HandoffTest(unittest.TestCase):
    """What a later session is told, in words, from the same fact."""

    def test_the_handout_says_a_discussion_wrote_it(self) -> None:
        candidate = {"id": "d-x", "statement": "这句。", "status": "draft",
                     "relations": [{"type": "derived_from", "target": "d-origin"}]}
        told = discuss.handoff_for_model(candidate, derivation="d-origin")
        self.assertIn("一场带着 d-origin 的讨论里写下的", told)
        self.assertIn("不表示变窄或变宽", told)

    def test_the_handout_does_not_claim_a_session_without_the_ledger(self) -> None:
        candidate = {"id": "d-x", "statement": "这句。", "status": "draft",
                     "relations": [{"type": "derived_from", "target": "d-origin"}]}
        told = discuss.handoff_for_model(candidate, derivation=None)
        self.assertNotIn("讨论里写下的", told)
        self.assertIn("那不是一场讨论留下的", told)
        screen = discuss.handoff_block(candidate, derivation=None)
        self.assertNotIn("讨论里写下", screen)
        self.assertIn("不是一场讨论留下的", screen)

    def test_the_handout_prints_the_edge_with_a_working_command(self) -> None:
        candidate = {"id": "d-x", "statement": "这句。", "status": "draft",
                     "relations": [{"type": "derived_from", "target": "d-origin"}]}
        # The command is printed only when the caller names the library: a handout built
        # without one has no file to point at, and an unopenable path is the defect #3419
        # fixed for every printed command.
        screen = discuss.handoff_block(candidate, derivation="d-origin", database="/tmp/lib.sqlite3")
        self.assertIn("show d-origin", screen)
        self.assertIn("--db /tmp/lib.sqlite3", screen)


if __name__ == "__main__":
    unittest.main()
