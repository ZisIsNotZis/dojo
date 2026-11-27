"""A third re-check, using the gate: two ways its reading was not faithful.

Both were found by citing a real quote, not by reading the code.

  1. **A sentence that appears twice, cited at the second occurrence.**
     One file, the same words on lines 3 and 5, `ref` says line 5. The gate compared
     the ref against the *first* occurrence and answered `stale-ref` -- it called a
     reader-accurate line number a stale map. A record that points precisely at the
     second occurrence is right, and the gate has to say so.

  2. **The cited revision cannot yield text, so the working tree answered instead.**
     Two shapes, one lie:
       * the cited commit resolves but does not hold the path, while the working
         tree does. `git show` returned nothing and the file was read from disk, so
         the quote row said `found` for words that were never read at that revision;
       * the cited blob is not UTF-8. `git show` succeeded, the decode failed, and
         that fell into the same branch as "no blob" -- a `pass`, the strongest word,
         on the weakest evidence. One Latin-1 byte in an old revision bought it.

     Now the working tree answers only where no revision can be asked at all (a
     frozen extract, `git=False`, a synthetic episode). A revision that exists but
     will not yield the file makes the row say `no-revision` and the verdict says
     `unchecked` or `fail` -- never `pass`.

Each case is built in a real temporary repository, because the defect lives in the
seam between git and the fallback, and only git reproduces it.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


def _repo_root():
    for parent in Path(__file__).resolve().parents:
        if (parent / "scripts" / "dao_life.py").is_file() and (parent / "docs" / "dao").is_dir():
            return parent
    raise RuntimeError("cannot locate the dojo repository root")


ROOT = _repo_root()
SPEC = importlib.util.spec_from_file_location("dao_life_occurrences", ROOT / "scripts" / "dao_life.py")
dao_life = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dao_life)

# Line 3 and line 5 hold the same sentence; line 1 is different text.
TWICE = "alpha one\nblank\nquote line seven\nblank2\nquote line seven\n"


def document(episodes):
    return {"episodes": {"layer": "events", "owner": "t", "what": "t",
                         "person": {"id": "p", "label": "t"},
                         "window": {"first_session": "2026-01-01",
                                    "last_person_input": "2026-12-31", "rule": "t"},
                         "episodes": episodes}}


class ASentenceMayAppearMoreThanOnce(unittest.TestCase):
    """Defect 1: the ref selects the occurrence; the gate used to ignore it."""

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="dojo-twice."))
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        self.git("init", "-q", ".")
        (self.work / "notes.md").write_text(TWICE, encoding="utf-8")
        self.git("add", "-A")
        self.git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "twice")
        self.commit = self.head()

    def git(self, *argv):
        done = subprocess.run(["git", *argv], cwd=str(self.work), capture_output=True, text=True)
        self.assertEqual(0, done.returncode, done.stderr)
        return done

    def head(self):
        return self.git("rev-parse", "HEAD").stdout.strip()

    def reading(self, ref, quote="quote line seven", path="notes.md"):
        episode = {"id": "e1", "at": "2026-01-01", "attribution": "person",
                   "attribution_note": "t", "quote": quote,
                   "source": {"path": path, "ref": ref, "commit": self.commit},
                   "observed_action": "t", "reading": "t"}
        return dao_life.check_sources(document([episode]), base=self.work, git=True)

    def test_the_occurrence_the_ref_names_is_the_one_checked(self):
        reading = self.reading("第 5 行")
        self.assertEqual("pass", reading["verdict"], reading["failures"])
        self.assertEqual("found", reading["rows"][0]["quote"])
        self.assertEqual([5, 5], reading["rows"][0]["lines"],
                         "the ref names the second occurrence and the file has it there")

    def test_the_first_occurrence_still_passes(self):
        """The control: accepting the second must not cost the first."""
        reading = self.reading("第 3 行")
        self.assertEqual("pass", reading["verdict"], reading["failures"])
        self.assertEqual([3, 3], reading["rows"][0]["lines"])

    def test_a_number_on_neither_occurrence_is_still_a_stale_map(self):
        """Widening the check must not turn every ref into a pass."""
        reading = self.reading("第 2 行")
        self.assertEqual("fail", reading["verdict"])
        self.assertEqual("stale-ref", reading["rows"][0]["quote"])
        self.assertEqual([3, 3], reading["rows"][0]["lines"],
                         "a stale ref still has to hand the reader the true location")

    def test_the_row_says_the_sentence_appears_twice(self):
        """A reader should learn the ambiguity from the row, not from a surprise."""
        row = self.reading("第 5 行")["rows"][0]
        self.assertEqual([[3, 3], [5, 5]], row["occurrences"])
        self.assertIn("2 次", row["occurrence_note"])
        self.assertIn("5", row["occurrence_note"])

    def test_the_earliest_wins_only_when_no_number_is_written(self):
        reading = self.reading("见上文")
        self.assertEqual("pass", reading["verdict"], reading["failures"])
        self.assertEqual([3, 3], reading["rows"][0]["lines"])
        self.assertIn("未写行号", reading["rows"][0]["occurrence_note"])

    def test_a_single_occurrence_carries_no_note(self):
        """The note means something only if it stays quiet in the ordinary case."""
        reading = self.reading("第 1 行", quote="alpha one")
        row = reading["rows"][0]
        self.assertEqual("pass", reading["verdict"], reading["failures"])
        self.assertEqual([[1, 1]], row["occurrences"])
        self.assertNotIn("occurrence_note", row)


class TheCitedRevisionIsTheOnlyThingRead(unittest.TestCase):
    """Defect 2: a revision that cannot yield text used to borrow the working tree."""

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="dojo-norev."))
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        self.git("init", "-q", ".")

    def git(self, *argv):
        done = subprocess.run(["git", *argv], cwd=str(self.work), capture_output=True, text=True)
        self.assertEqual(0, done.returncode, done.stderr)
        return done

    def commit_all(self, message):
        self.git("add", "-A")
        self.git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", message)
        return self.git("rev-parse", "HEAD").stdout.strip()

    def reading(self, commit, path="notes.md", quote="alpha one", ref="第 1 行", git=True):
        episode = {"id": "e1", "at": "2026-01-01", "attribution": "person",
                   "attribution_note": "t", "quote": quote,
                   "source": {"path": path, "ref": ref, "commit": commit},
                   "observed_action": "t", "reading": "t"}
        return dao_life.check_sources(document([episode]), base=self.work, git=git)

    def test_a_revision_without_the_file_does_not_borrow_the_working_tree(self):
        """The cited commit deleted the file; today's copy still has the sentence."""
        (self.work / "notes.md").write_text(TWICE, encoding="utf-8")
        self.commit_all("has the file")
        self.git("rm", "-q", "notes.md")
        gone = self.commit_all("deleted the file")
        # Put it back on disk without committing: the working tree is not the revision.
        (self.work / "notes.md").write_text(TWICE, encoding="utf-8")

        reading = self.reading(gone)
        row = reading["rows"][0]
        self.assertEqual("fail", reading["verdict"])
        self.assertEqual("missing-path", row["commit_state"])
        self.assertEqual("no-revision", row["checked_at"],
                         "the row must not claim it read today's file for that revision")
        self.assertNotEqual("found", row["quote"])
        self.assertTrue(any("notes.md" in line and "没有" in line for line in reading["failures"]))

    def test_a_revision_whose_bytes_are_not_utf8_is_not_a_pass(self):
        """One Latin-1 word was enough to buy `pass` before this test existed."""
        (self.work / "doc.md").write_bytes(b"caf\xe9 latin one\n")
        latin = self.commit_all("latin-1 bytes")
        # The working tree holds a UTF-8 version that does contain the quote.
        (self.work / "doc.md").write_text("cafe latin one\n", encoding="utf-8")

        reading = self.reading(latin, path="doc.md", quote="cafe latin one")
        row = reading["rows"][0]
        self.assertEqual("fail", reading["verdict"],
                         "an unreadable revision must not answer `pass` by reading the disk")
        self.assertEqual("unreadable-at-revision", row["quote"])
        self.assertEqual("no-revision", row["checked_at"])
        self.assertEqual("resolved", row["commit_state"],
                         "the commit is there; it is the text that cannot be read")
        self.assertIn("UTF-8", row["revision_note"])

    def test_a_frozen_extract_still_reads_the_only_text_it_has(self):
        """The unchanged contract: no repository, no revision, and the verdict says so."""
        (self.work / "notes.md").write_text(TWICE, encoding="utf-8")
        reading = self.reading("deadbeef", git=False)
        row = reading["rows"][0]
        self.assertEqual("unchecked", reading["verdict"])
        self.assertEqual("working-tree", row["checked_at"])
        self.assertEqual("found", row["quote"],
                         "with no history the working tree is the only text that exists")

    def test_a_commit_that_is_absent_from_this_repository_is_not_read_off_disk(self):
        """A rewritten history must not be papered over with today's file."""
        (self.work / "notes.md").write_text(TWICE, encoding="utf-8")
        self.commit_all("only commit")
        reading = self.reading("0" * 40)
        row = reading["rows"][0]
        self.assertEqual("unchecked", reading["verdict"])
        self.assertEqual(["e1"], reading["unresolved_commits"])
        self.assertEqual("no-revision", row["checked_at"])
        self.assertEqual([], reading["failures"],
                         "a citation that cannot be asked is unchecked, not wrong")

    def test_the_control_revision_is_read_and_passes(self):
        (self.work / "notes.md").write_text(TWICE, encoding="utf-8")
        head = self.commit_all("has the file")
        reading = self.reading(head)
        self.assertEqual("pass", reading["verdict"], reading["failures"])
        self.assertEqual("commit", reading["rows"][0]["checked_at"])
        self.assertEqual(1, reading["checked_at_commit"])


class TheReadingLineSaysWhichOfTheFourHappened(unittest.TestCase):
    """The summary a reader sees must count the states apart, not add them up."""

    def test_the_line_names_unverifiable_revisions_separately(self):
        work = Path(tempfile.mkdtemp(prefix="dojo-line."))
        self.addCleanup(shutil.rmtree, work, ignore_errors=True)
        subprocess.run(["git", "init", "-q", str(work)], capture_output=True)
        (work / "notes.md").write_text(TWICE, encoding="utf-8")
        subprocess.run(["git", "-C", str(work), "add", "-A"], capture_output=True)
        subprocess.run(["git", "-C", str(work), "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-qm", "seed"], capture_output=True)
        head = subprocess.run(["git", "-C", str(work), "rev-parse", "HEAD"],
                              capture_output=True, text=True).stdout.strip()
        episode = {"id": "e1", "at": "2026-01-01", "attribution": "person",
                   "attribution_note": "t", "quote": "quote line seven",
                   "source": {"path": "notes.md", "ref": "第 5 行", "commit": head},
                   "observed_action": "t", "reading": "t"}
        reading = dao_life.check_sources(document([episode]), base=work, git=True)
        self.assertEqual(1, reading["checked_at_commit"])
        self.assertIn("按所指版本核对 1 条", reading["line"])
        self.assertIn("引语没能在这个版本上核对 0 条", reading["line"])
        self.assertIn("commit 是会动的名字 0 条", reading["line"])
        self.assertIn("sources-v4", reading["ran"]["by"])


class NoShippedVerdictRestsOnTheWorkingTree(unittest.TestCase):
    """The invariant across every real library, not one fixture.

    `pass` is the one word a reader is meant to act on, so it must never be earned
    by reading today's file. Stated as a property of the whole tree: for every
    shipped episode whose verdict is `pass`, that row was read at the cited
    revision -- and the two counts the reading reports must agree with the rows
    rather than be asserted separately.
    """

    def setUp(self):
        # A frozen extract has no `.git`, so these commits cannot be looked up at
        # all. That is a different fact from "a row passed on a working-tree
        # reading", and it must not read as the defect: skip where the question
        # cannot be asked, exactly as the shipped suite already does.
        if not (ROOT / ".git").exists():
            self.skipTest("no .git here: a frozen extract cannot resolve commits")

    def libraries(self):
        base = ROOT / "docs" / "dao"
        return tuple(sorted(p for p in base.iterdir()
                            if p.is_dir() and (p / "episodes.json").is_file()))

    def test_every_passing_row_was_read_at_its_cited_revision(self):
        """Synthetic rows are excluded: that corpus is authored here and owes no revision."""
        for library in self.libraries():
            episodes = json.loads((library / "episodes.json").read_text(encoding="utf-8"))
            reading = dao_life.check_sources({"episodes": episodes}, base=ROOT, git=True)
            with self.subTest(library=library.name):
                self.assertEqual("pass", reading["verdict"], reading["failures"])
                owed = [row for row in reading["rows"] if row["commit_state"] != "not-required"]
                readable = [row for row in owed if row["quote"] == "found"]
                if not owed:
                    # A wholly synthetic library: the corpus is authored here, so it
                    # owes no revision and this property has nothing to say about it.
                    self.assertEqual(0, reading["checked_at_commit"])
                    continue
                self.assertTrue(readable, "%s owes revisions but read none" % library.name)
                for row in readable:
                    self.assertEqual("commit", row["checked_at"],
                                     "%s passed with a %s reading" % (row["id"], row["checked_at"]))
                self.assertEqual(len(readable), reading["checked_at_commit"])
                self.assertEqual([], reading["unchecked_at_revision"])

    def test_a_passing_reading_never_reports_an_unchecked_quote(self):
        """The two counters must account for every row, or the line is decoration."""
        for library in self.libraries():
            episodes = json.loads((library / "episodes.json").read_text(encoding="utf-8"))
            reading = dao_life.check_sources({"episodes": episodes}, base=ROOT, git=True)
            with self.subTest(library=library.name):
                rows = reading["rows"]
                owed = [row for row in rows if row["commit_state"] != "not-required"]
                self.assertEqual(
                    len(owed), reading["checked_at_commit"] + len(reading["unchecked_at_revision"]),
                    "every row that owes a revision was either read at it or flagged")
                counted = sum(1 for row in rows if row["quote"] == "found")
                self.assertIn(f"引语 {counted} 条逐字落在它写的行内", reading["line"])


class TheReceiptKeepsItsOwnReading(unittest.TestCase):
    """The stored projection must be what this code produces, not an older reading.

    A receipt that says `sources-v2` while the code reads revisions differently is
    how a reader ends up trusting a number nobody recomputed. The shipped
    `repeat-safety` receipt is regenerated in this round for exactly that reason.
    """

    def setUp(self):
        if not (ROOT / ".git").exists():
            self.skipTest("no .git here: a frozen extract cannot re-derive the reading")

    def test_the_shipped_receipt_carries_the_current_reading(self):
        path = ROOT / "docs" / "dao" / "repeat-safety" / "receipts.json"
        receipts = json.loads(path.read_text(encoding="utf-8"))
        episodes = json.loads((path.parent / "episodes.json").read_text(encoding="utf-8"))
        fresh = dao_life.check_sources({"episodes": episodes}, base=ROOT, git=True)
        stored = receipts["daos"]["repeat-d-001"]["receipts"]["sources"]
        self.assertEqual(fresh["ran"]["by"], stored["ran"]["by"])
        self.assertEqual(fresh["line"], stored["line"])
        self.assertEqual(fresh["checked_at_commit"], stored["checked_at_commit"])
        self.assertEqual(fresh["unchecked_at_revision"], stored["unchecked_at_revision"])


if __name__ == "__main__":
    unittest.main()
