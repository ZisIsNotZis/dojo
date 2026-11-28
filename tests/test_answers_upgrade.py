"""Two sessions upgrading the same old library at once must both keep their answer.

Review found this on the first version of the column upgrade: the column check ran outside
the write lock, so two writers both read "no such column", both ran the ALTER, and the
second died on `duplicate column name` -- losing that person's answer for a reason that had
nothing to do with their answer.

The window is naturally microseconds wide, which is why the probe for this was green on the
broken code until the window was widened (`tests/test_answers_upgrade.py` keeps the barrier;
`.scratch/3480/regress_upgrade.py` is the run that showed a widened window failing on the
old shape). Here the two writers are threads in one process, each with its own connection,
released together -- the same contention, without depending on process scheduling.
"""
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from dojo.storage import Store

OLD_SCHEMA = """
CREATE TABLE answers (
    candidate_id TEXT NOT NULL,
    field TEXT NOT NULL,
    answer TEXT NOT NULL,
    session TEXT,
    at TEXT,
    question TEXT,
    trace TEXT,
    promoted_at TEXT NOT NULL,
    PRIMARY KEY(candidate_id, field)
);
"""


class TwoWritersUpgradeTogether(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / "old.sqlite3"
        seed = Store(self.db)
        self.card = seed.add("把持续检查交给系统跑。", "abstract_idea", scope=["x"])["id"]
        seed.close()
        # Put the library back in the shape the earlier build wrote: an `answers` table
        # without the two columns this slice added.
        connection = sqlite3.connect(self.db)
        connection.execute("DROP TABLE IF EXISTS answers")
        connection.executescript(OLD_SCHEMA)
        connection.commit()
        connection.close()

    def promote(self, part, answer, results, key):
        store = Store(self.db)
        try:
            store.promote_answers(
                self.card,
                [{"part": part, "answer": answer, "provenance": "discussion",
                  "session": "s-1"}],
                session="s-1")
            results[key] = None
        except Exception as exc:  # noqa: BLE001 -- the failure is the assertion
            results[key] = exc
        finally:
            store.close()

    def test_both_writers_keep_their_answer_and_the_columns_appear_once(self):
        results = {}
        barrier = threading.Barrier(2)

        def run(part, answer, key):
            barrier.wait()
            self.promote(part, answer, results, key)

        threads = [
            threading.Thread(target=run, args=("situation", "上周二夜里冷库温度报警", "a")),
            threading.Thread(target=run, args=("price", "两个同事要多跑一趟", "b")),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual({"a": None, "b": None}, results,
                         "a writer failed while upgrading a shared library: "
                         + str({key: repr(value) for key, value in results.items()}))
        store = Store(self.db, readonly=True)
        try:
            held = store.answers_for(self.card)
        finally:
            store.close()
        self.assertEqual({"situation", "price"}, set(held))
        self.assertEqual("上周二夜里冷库温度报警", held["situation"]["answer"])
        self.assertEqual("两个同事要多跑一趟", held["price"]["answer"])
        self.assertEqual("discussion", held["price"]["provenance"])

    def test_a_read_only_view_of_an_old_library_changes_no_byte(self):
        before = self.db.read_bytes()
        store = Store(self.db, readonly=True)
        try:
            self.assertEqual({}, store.answers_for(self.card))
        finally:
            store.close()
        self.assertEqual(before, self.db.read_bytes(),
                         "looking at an old library must not upgrade it")


if __name__ == "__main__":
    unittest.main()
