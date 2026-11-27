"""Two gaps an independent re-check found by using the gate, not by reading it.

Both were pre-existing: they were true of the version before this round as well, so
they are not regressions, they are holes the re-check walked through.

  1. **A cited commit could be a name that moves.** `HEAD`, a branch, `HEAD~1`, a
     lightweight tag all resolve right now, and the gate called that `resolved` and
     read the quote at whatever they pointed at *today*. The re-check reset a branch
     to an older commit, changed not one character of the record, and watched
     `fail / absent` become `pass / found`. A citation is a promise to a reader who
     arrives years later; `HEAD` cannot keep it. Now only a pinned object name (hex,
     abbreviated or full) can be `resolved`; anything else is `moving-name` and fails
     with a message that says what to write instead.

     Nothing shipped is affected -- all twenty episodes cite hex object names -- but
     the rule is what makes "the commit resolves here" mean "at that revision".

  2. **Any number in a `ref` could stand in for the line number.** The old parse took
     every `第 (\\d+)` in the string, so `第 29 行，见第 2 节` passed: 3 was not inside
     the quote, 2 was, and the gate asked only whether *some* number landed. The
     shipped `person-dojo/ep-2026-10-23-detach` really does carry three numbers
     (`第 111 行；§10 第 2 条（第 272 行）`); it resolves correctly today by luck, not
     by construction. Now only `第 N 行` and `N–M 行` count, and a range contributes
     every line between its ends.
"""
import importlib.util
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
SPEC = importlib.util.spec_from_file_location("dao_life_names", ROOT / "scripts" / "dao_life.py")
dao_life = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dao_life)

# The sentence is on line 3. Line 5 holds different words, so a ref to the wrong
# place has to be visible as such.
FILE = "alpha one\nblank\nquote line seven\nblank2\nCHANGED later\n"


class ACommitNameMustNotMove(unittest.TestCase):
    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="dojo-move."))
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        self.git("init", "-q", ".")
        self.git("checkout", "-q", "-b", "main")
        (self.work / "notes.md").write_text(FILE, encoding="utf-8")
        self.git("add", "-A")
        self.git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "one")
        self.first = self.git("rev-parse", "HEAD").stdout.strip()

    def git(self, *argv):
        done = subprocess.run(["git", *argv], cwd=str(self.work), capture_output=True, text=True)
        self.assertEqual(0, done.returncode, done.stderr)
        return done

    def reading(self, commit, quote="quote line seven", ref="第 3 行"):
        episode = {"id": "e1", "at": "2026-01-01", "attribution": "person",
                   "attribution_note": "t", "quote": quote,
                   "source": {"path": "notes.md", "ref": ref, "commit": commit},
                   "observed_action": "t", "reading": "t"}
        data = {"episodes": {"layer": "events", "owner": "t", "what": "t",
                             "person": {"id": "p", "label": "t"},
                             "window": {"first_session": "2026-01-01",
                                        "last_person_input": "2026-12-31", "rule": "t"},
                             "episodes": [episode]}}
        return dao_life.check_sources(data, base=self.work, git=True)

    def test_the_full_hash_is_a_pinned_revision(self):
        reading = self.reading(self.first)
        self.assertEqual("pass", reading["verdict"], reading["failures"])
        self.assertEqual("resolved", reading["rows"][0]["commit_state"])

    def test_an_abbreviated_hash_is_still_pinned(self):
        reading = self.reading(self.first[:8])
        self.assertEqual("pass", reading["verdict"], reading["failures"])

    def test_head_is_not_a_revision(self):
        """The re-check's exact manoeuvre: a reset branch must not change the reading."""
        reading = self.reading("HEAD")
        self.assertEqual("fail", reading["verdict"])
        self.assertEqual("moving-name", reading["rows"][0]["commit_state"])
        self.assertEqual("no-revision", reading["rows"][0]["checked_at"])
        self.assertTrue(any("会动的名字" in line for line in reading["failures"]))
        self.assertEqual(["e1"], reading["moving_names"])

    def test_a_branch_name_is_not_a_revision(self):
        reading = self.reading("main")
        self.assertEqual("fail", reading["verdict"])
        self.assertEqual("moving-name", reading["rows"][0]["commit_state"])

    def test_a_traversal_is_not_a_revision(self):
        """`HEAD~1` is a calculation, not a pin, even when it lands on a real commit."""
        reading = self.reading("HEAD~0")
        self.assertEqual("fail", reading["verdict"])
        self.assertEqual("moving-name", reading["rows"][0]["commit_state"])

    def test_moving_the_branch_cannot_flip_a_pinned_record(self):
        """The property, stated as behaviour: the record names a revision, so it holds.

        The re-check watched an unchanged record go from `fail` to `pass` because the
        branch moved. With the hash written down, the same edit changes nothing.
        """
        before = self.reading(self.first)
        (self.work / "notes.md").write_text(FILE.replace("CHANGED later", "quote line seven"),
                                            encoding="utf-8")
        self.git("add", "-A")
        self.git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "two")
        after = self.reading(self.first)
        self.assertEqual(before["verdict"], after["verdict"])
        self.assertEqual(before["rows"][0]["lines"], after["rows"][0]["lines"])

    def test_a_tag_named_like_a_hash_is_not_a_revision(self):
        """Looking like a hash is not being one.

        Measured: `git tag 1af799f` makes that string resolve to a *different*
        commit, because git prefers a ref name over the object spec. A record could
        therefore name one revision and have its text read from another. The test
        asserts the property directly: the resolved object must be the one the name
        denotes.
        """
        self.git("tag", self.first[:7])
        reading = self.reading(self.first[:7])
        self.assertEqual("fail", reading["verdict"],
                         "a tag can be renamed to point elsewhere; the name must not pass as a pin")
        self.assertEqual("moving-name", reading["rows"][0]["commit_state"])
        self.assertEqual(["e1"], reading["moving_names"])

    def test_an_annotated_tag_named_like_a_hash_is_not_a_revision(self):
        self.git("-c", "user.email=t@t", "-c", "user.name=t",
                 "tag", "-a", self.first[:7], "-m", "looks like a hash")
        reading = self.reading(self.first[:7])
        self.assertEqual("fail", reading["verdict"])
        self.assertEqual("moving-name", reading["rows"][0]["commit_state"])

    def test_the_real_full_hash_still_passes_beside_such_a_tag(self):
        """The control: the strictness must not cost the honest name."""
        self.git("tag", self.first[:7])
        reading = self.reading(self.first)
        self.assertEqual("pass", reading["verdict"], reading["failures"])
        self.assertEqual("resolved", reading["rows"][0]["commit_state"])

    def test_a_missing_commit_and_a_moving_name_are_not_the_same_fact(self):
        gone = self.reading("0" * 40)
        moved = self.reading("HEAD")
        self.assertEqual("unresolved", gone["rows"][0]["commit_state"])
        self.assertEqual("moving-name", moved["rows"][0]["commit_state"])
        self.assertEqual([], gone["moving_names"])
        self.assertEqual(["e1"], moved["moving_names"])


class ARefNumberMustBeALineNumber(unittest.TestCase):
    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="dojo-ref."))
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        self.git("init", "-q", ".")
        (self.work / "notes.md").write_text(FILE, encoding="utf-8")
        self.git("add", "-A")
        self.git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "one")
        self.commit = self.git("rev-parse", "HEAD").stdout.strip()

    def git(self, *argv):
        done = subprocess.run(["git", *argv], cwd=str(self.work), capture_output=True, text=True)
        self.assertEqual(0, done.returncode, done.stderr)
        return done

    def reading(self, ref):
        episode = {"id": "e1", "at": "2026-01-01", "attribution": "person",
                   "attribution_note": "t", "quote": "quote line seven",
                   "source": {"path": "notes.md", "ref": ref, "commit": self.commit},
                   "observed_action": "t", "reading": "t"}
        return dao_life.check_sources({"episodes": {"episodes": [episode]}},
                                      base=self.work, git=True)

    def test_the_right_line_passes(self):
        reading = self.reading("第 3 行")
        self.assertEqual("pass", reading["verdict"], reading["failures"])

    def test_a_section_number_cannot_rescue_a_wrong_line(self):
        """The re-check's counterexample: line 3 is where the words are, not line 29."""
        reading = self.reading("第 29 行，见第 3 节")
        self.assertEqual("fail", reading["verdict"],
                         "a section number is not a line number")
        self.assertEqual("stale-ref", reading["rows"][0]["quote"])
        self.assertEqual([3, 3], reading["rows"][0]["lines"])

    def test_a_wrong_line_with_a_right_section_still_fails(self):
        reading = self.reading("第 4 行；§3 第 3 条")
        self.assertEqual("fail", reading["verdict"])

    def test_the_shipped_three_number_ref_keeps_both_of_its_line_citations(self):
        """`第 111 行；§10 第 2 条（第 272 行）` names two lines, and both are lines.

        272 is not a section number: it is written `第 272 行` and points at the item
        the record is quoting from a second angle. Both stay anchors, which is right
        -- a reader following either number lands where the record said to look. What
        the parse must drop is `第 2 条` and `§10`: those are not lines at all, and
        letting them stand in was the defect.
        """
        self.assertEqual([111, 272],
                         dao_life._cited_lines("第 111 行；§10 第 2 条（第 272 行）"))
        self.assertEqual([29, 30], dao_life._cited_lines("§2 核心原则 1 道无名（第 29–30 行）"))

    def test_a_range_lets_any_line_inside_it_anchor(self):
        """The sentence on line 3 is inside 2–3: the reader's number is not wrong."""
        reading = self.reading("第 2–3 行")
        self.assertEqual("pass", reading["verdict"], reading["failures"])
        self.assertEqual([3, 3], reading["rows"][0]["lines"])

    def test_a_range_that_excludes_the_sentence_still_fails(self):
        reading = self.reading("第 1–2 行")
        self.assertEqual("fail", reading["verdict"])
        self.assertEqual([3, 3], reading["rows"][0]["lines"])

    def test_a_very_wide_range_is_one_comparison_not_an_expansion(self):
        """A coarse record is coarse; it is not a reason to build a huge list.

        The gate asks whether the quote sits inside the range. `第 1–5000 行` is one
        comparison, and the row reports the quote's real position either way.
        """
        reading = self.reading("第 1–5000 行")
        self.assertEqual("pass", reading["verdict"], reading["failures"])
        self.assertEqual([3, 3], reading["rows"][0]["lines"])
        self.assertEqual([(1, 5000)], dao_life._cited_ranges("第 1–5000 行"))

    def test_a_ref_with_no_line_number_falls_back_to_the_tightest_span(self):
        reading = self.reading("§2 核心原则")
        self.assertEqual("pass", reading["verdict"], reading["failures"])
        self.assertEqual([3, 3], reading["rows"][0]["lines"])


class EveryShippedCitationIsPinnedAndParsed(unittest.TestCase):
    """Across the real libraries: no moving names, and every ref has a line number."""

    def tearDown(self):
        pass

    def libraries(self):
        base = ROOT / "docs" / "dao"
        return tuple(sorted(p for p in base.iterdir()
                            if p.is_dir() and (p / "episodes.json").is_file()))

    def test_no_shipped_episode_cites_a_moving_name(self):
        import json
        for library in self.libraries():
            episodes = json.loads((library / "episodes.json").read_text(encoding="utf-8"))
            for episode in episodes["episodes"]:
                commit = (episode.get("source") or {}).get("commit") or ""
                if episode.get("attribution") == "synthetic" or not commit:
                    continue
                with self.subTest(library=library.name, episode=episode["id"]):
                    self.assertTrue(dao_life._pinned_name(commit),
                                    "%s cites %r, which can move" % (episode["id"], commit))

    def test_every_shipped_line_ref_is_read_as_a_line_number(self):
        import json
        for library in self.libraries():
            episodes = json.loads((library / "episodes.json").read_text(encoding="utf-8"))
            for episode in episodes["episodes"]:
                ref = (episode.get("source") or {}).get("ref") or ""
                if not ref:
                    continue
                with self.subTest(library=library.name, episode=episode["id"]):
                    self.assertTrue(dao_life._cited_lines(ref),
                                    "%s has no readable line number in %r" % (episode["id"], ref))


if __name__ == "__main__":
    unittest.main()
