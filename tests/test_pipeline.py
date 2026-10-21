"""The end-of-session pipeline: ordered passes, once per card revision.

M2 acceptance ④ asks that re-running the pipeline for the same session be
idempotent and side-effect free. These tests are that check: the second run must
write nothing, and a card that changes afterwards must be processed again.
"""

import json
import tempfile
import unittest
from pathlib import Path

from dojo.pipeline import PASS_ORDER, run_pipeline
from dojo.storage import Store


def pass_events(store, event_window_start=0):
    rows = store.connection.execute(
        "SELECT candidate_id,details_json FROM events ORDER BY seq"
    ).fetchall()
    values = []
    for index, row in enumerate(rows):
        details = json.loads(row["details_json"])
        if index >= event_window_start:
            values.append((row["candidate_id"], details))
    return values


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "dojo.sqlite3")
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.store.close)

    def add(self, statement, session="sess-a", candidate_id=None, **kwargs):
        return self.store.add(statement, "application", session=session, candidate_id=candidate_id, **kwargs)

    def test_a_second_run_for_the_same_session_writes_nothing(self):
        self.add("交接前先写下当前版本的范围，能减少返工。")
        first = run_pipeline(self.store, "sess-a")
        self.assertGreater(first["events_written"], 0)
        events_after_first = len(pass_events(self.store))
        second = run_pipeline(self.store, "sess-a")
        self.assertEqual(0, second["events_written"])
        self.assertEqual(events_after_first, len(pass_events(self.store)))
        skipped = {entry["pass"]: entry["skipped"] for entry in second["passes"]}
        self.assertEqual(1, len(skipped["locate"]))
        self.assertEqual(1, len(skipped["challenge"]))

    def test_passes_run_in_the_declared_order(self):
        self.add("交接前先写下当前版本的范围，能减少返工。")
        report = run_pipeline(self.store, "sess-a")
        self.assertEqual(list(PASS_ORDER), [entry["pass"] for entry in report["passes"]])

    def test_a_revised_card_is_processed_again(self):
        card = self.add("交接前先写下当前版本的范围，能减少返工。")
        run_pipeline(self.store, "sess-a")
        self.store.revise(card["id"], "交接前先写下当前版本要交付的范围，能减少返工。", "补充交付范围", scope=["交接", "上线前"])
        again = run_pipeline(self.store, "sess-a")
        located = [item for entry in again["passes"] if entry["pass"] == "locate" for item in entry["ran"]]
        self.assertEqual([card["id"]], [item["id"] for item in located])
        self.assertEqual(2, located[0]["version"])

    def test_classify_reports_itself_unavailable_and_writes_nothing(self):
        card = self.add("交接前先写下当前版本的范围，能减少返工。")
        report = run_pipeline(self.store, "sess-a")
        classify = next(entry for entry in report["passes"] if entry["pass"] == "classify")
        self.assertIn("unavailable", classify)
        self.assertIn("模型判定", classify["unavailable"])
        self.assertEqual([], classify["ran"])
        self.assertIsNone(self.store.pipeline_mark("sess-a", "classify", card["id"]))
        written = [details for _id, details in pass_events(self.store) if details.get("pass") == "classify"]
        self.assertEqual([], written)

    def test_dry_run_writes_neither_marks_nor_events(self):
        card = self.add("交接前先写下当前版本的范围，能减少返工。")
        before = len(pass_events(self.store))
        report = run_pipeline(self.store, "sess-a", dry_run=True)
        self.assertEqual(0, report["events_written"])
        self.assertEqual(before, len(pass_events(self.store)))
        self.assertIsNone(self.store.pipeline_mark("sess-a", "locate", card["id"]))
        self.assertGreater(len(next(entry for entry in report["passes"] if entry["pass"] == "locate")["ran"]), 0)

    def test_locate_proposes_variant_and_reports_new_when_alone(self):
        alone = self.add("先把交接范围写下来，再动手。", candidate_id="d-alone")
        card = self.add("交接前写下当前版本的范围，能减少返工。", candidate_id="d-card", scope=["交接"])
        self.add("交接前写下当前版本的范围，能减少返工。", candidate_id="d-variant", scope=["交接", "上线前"])
        report = run_pipeline(self.store, "sess-a")
        located = {
            item["id"]: item["proposals"]
            for entry in report["passes"] if entry["pass"] == "locate" for item in entry["ran"]
        }
        self.assertEqual("new", located["d-alone"][0]["type"])
        variant = [item for item in located["d-card"] if item["type"] == "variant"]
        self.assertEqual("d-variant", variant[0]["of"])
        self.assertTrue(alone["id"] in located)

    def test_challenge_proposes_only_where_the_negation_flips(self):
        self.add("交接前写下当前版本的范围，能减少返工。", candidate_id="d-one")
        self.add("交接前写下当前版本的范围，不能减少返工。", candidate_id="d-two")
        report = run_pipeline(self.store, "sess-a")
        proposed = [
            proposal
            for entry in report["passes"] if entry["pass"] == "challenge"
            for item in entry["ran"] for proposal in item["proposals"]
        ]
        # Each card finds the other, so both directions are proposed; neither is applied.
        self.assertEqual(["challenge", "challenge"], [proposal["type"] for proposal in proposed])
        self.assertEqual({"d-one", "d-two"}, {proposal["of"] for proposal in proposed})
        for proposal in proposed:
            self.assertIn("不自动改写", proposal["reason"])
        self.assertEqual("draft", self.store.show("d-one")["candidate"]["status"])
        self.assertEqual("draft", self.store.show("d-two")["candidate"]["status"])

    def test_a_session_that_wrote_nothing_has_nothing_to_process(self):
        report = run_pipeline(self.store, "sess-empty")
        self.assertEqual([], report["cards"])
        self.assertEqual(0, report["events_written"])
        self.assertIn("wrote no cards", report["note"])


if __name__ == "__main__":
    unittest.main()
