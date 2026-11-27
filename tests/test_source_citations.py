"""`source` was printed beside every quote and never read.

The event layer in `docs/dao/*/episodes.json` names a path, a line reference and a
commit for each quote. Nothing verified any of the three, so the three were
decorative. Measured on the tree that shipped this gate: all 20 episodes named a
commit that does not resolve here (the history was rebuilt), one quote did not
appear at its cited path at all -- it had joined two bullets into one sentence --
and one cited line number pointed nine lines above the sentence it claimed.

These tests refuse four shapes:

  * a gate that passes a quote that is not in the file it names;
  * a gate that passes a line number pointing away from the quote, which sends the
    reader to the wrong paragraph;
  * a gate that calls an unresolvable commit `pass`. `unchecked` is a different word
    on purpose: the quote was found, the revision was not;
  * a repo that quietly stops checking. Every library in `docs/dao` is run through
    the real command here, so a later edit to the event files cannot pass unnoticed.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


def _repo_root():
    for parent in Path(__file__).resolve().parents:
        if (parent / "scripts" / "dao_life.py").is_file() and (parent / "docs" / "dao").is_dir():
            return parent
    raise RuntimeError("cannot locate the dojo repository root")


ROOT = _repo_root()
SPEC = importlib.util.spec_from_file_location("dao_life_citations", ROOT / "scripts" / "dao_life.py")
dao_life = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dao_life)

LIBRARIES = tuple(sorted(p.name for p in (ROOT / "docs" / "dao").iterdir()
                         if p.is_dir() and (p / "episodes.json").is_file()))


def document(episodes, window=None):
    """A minimal library: `check_sources` reads the event layer only."""
    return {
        "episodes": {
            "layer": "events", "owner": "test", "what": "test",
            "person": {"id": "p", "label": "test"},
            "window": window or {"first_session": "2026-01-01",
                                 "last_person_input": "2026-12-31", "rule": "test"},
            "episodes": episodes,
        }
    }


class ACitationMustLandWhereItSays(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="dojo-cite."))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.addCleanup(os.chdir, os.getcwd())
        (self.root / "doc").mkdir()
        (self.root / "doc" / "prose.md").write_text(
            "# Sample\n\nfirst paragraph here\nsecond paragraph here\n", encoding="utf-8")
        os.chdir(self.root)

    def episode(self, quote, ref="第 3 行", commit="deadbee", attribution="person", path="doc/prose.md"):
        return {"id": "ep-x", "at": "2026-01-01", "attribution": attribution,
                "attribution_note": "test", "quote": quote,
                "source": {"path": path, "ref": ref, "commit": commit},
                "observed_action": "test", "reading": "test"}

    def test_a_quote_that_is_in_the_file_passes_its_quote_check(self):
        reading = dao_life.check_sources(document([self.episode("second paragraph here",
                                                               ref="第 4 行")]),
                                         base=self.root, git=False)
        self.assertEqual("found", reading["rows"][0]["quote"])

    def test_a_quote_that_is_not_in_the_file_fails(self):
        """The shipped tree had one of these, and it was not a wrapping artefact.

        `ep-2026-10-18-pref` cited two separate bullets as one sentence; the words
        it quoted were not there, in any wrapping.
        """
        reading = dao_life.check_sources(
            document([self.episode("a sentence nobody wrote in this file")]),
            base=self.root, git=False)
        self.assertEqual("absent", reading["rows"][0]["quote"])
        self.assertEqual("fail", reading["verdict"])
        self.assertTrue(any("找不到" in line for line in reading["failures"]))

    def test_wrapping_across_lines_is_not_a_missing_quote(self):
        """The gate squashes whitespace, and this states the limit that buys.

        Joining the end of one paragraph to the start of the next is accepted: the
        file does contain those words in that order, one line break apart. That is
        what lets a quote spanning a wrapped sentence pass, and it is also why this
        gate cannot by itself tell a quoted paragraph from a quoted seam. The
        limit is written down rather than left to be rediscovered; the line
        reference is what makes a seam visible to a reader who follows it.
        """
        reading = dao_life.check_sources(
            document([self.episode("first paragraph here second paragraph here")]),
            base=self.root, git=False)
        self.assertEqual("found", reading["rows"][0]["quote"])

    def test_a_line_number_pointing_away_from_the_quote_fails(self):
        """A stale map is worse than no map: the reader lands on the wrong paragraph."""
        reading = dao_life.check_sources(document([self.episode("second paragraph here",
                                                               ref="第 3 行")]),
                                         base=self.root, git=False)
        self.assertEqual("stale-ref", reading["rows"][0]["quote"])
        self.assertEqual("fail", reading["verdict"])

    def test_the_tightest_span_decides_not_the_widest(self):
        """A wide window would let a neighbouring line pass; measure the tight one."""
        reading = dao_life.check_sources(
            document([self.episode("second paragraph here", ref="第 3 行")]),
            base=self.root, git=False)
        self.assertEqual([4, 4], reading["rows"][0]["lines"])

    def test_an_unresolvable_commit_is_unchecked_not_passed(self):
        """Two words, because they are two facts: quote found, revision not checked."""
        reading = dao_life.check_sources(document([self.episode("first paragraph here")]),
                                         base=self.root, git=True)
        self.assertEqual("unchecked", reading["verdict"])
        self.assertEqual(["ep-x"], reading["unresolved_commits"])
        self.assertEqual([], reading["failures"], "an unchecked commit is not a quote failure")

    def test_found_quotes_and_resolved_commits_pass(self):
        done = subprocess.run(["git", "init", "-q", str(self.root)], capture_output=True)
        if done.returncode != 0:
            self.skipTest("git unavailable")
        subprocess.run(["git", "-C", str(self.root), "add", "-A"], capture_output=True)
        subprocess.run(["git", "-C", str(self.root), "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-qm", "seed"], capture_output=True)
        head = subprocess.run(["git", "-C", str(self.root), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True).stdout.strip()
        reading = dao_life.check_sources(
            document([self.episode("first paragraph here", commit=head)]),
            base=self.root, git=True)
        self.assertEqual("pass", reading["verdict"])
        self.assertEqual("resolved", reading["rows"][0]["commit_state"])

    def test_a_missing_path_fails_rather_than_passing_quietly(self):
        reading = dao_life.check_sources(
            document([self.episode("first paragraph here", path="doc/nope.md")]),
            base=self.root, git=False)
        self.assertEqual("unreadable", reading["rows"][0]["quote"])
        self.assertEqual("fail", reading["verdict"])

    def test_a_synthetic_episode_still_has_to_land_its_quote(self):
        """"We wrote it" does not make a mis-citation harmless."""
        reading = dao_life.check_sources(
            document([self.episode("words nobody wrote", attribution="synthetic")]),
            base=self.root, git=False)
        self.assertEqual("fail", reading["verdict"])


class EveryShippedLibraryIsChecked(unittest.TestCase):
    """The real command, over the real libraries. No fixtures: the files under test."""

    def run_check(self, library):
        env = {k: v for k, v in os.environ.items() if not k.startswith("DOJO_")}
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run(
            [sys.executable, "-B", str(ROOT / "scripts" / "dao_life.py"),
             str(ROOT / "docs" / "dao" / library), "--check"],
            cwd=str(ROOT), capture_output=True, text=True, env=env, timeout=300)

    def test_every_library_passes_its_own_citation_check(self):
        for library in LIBRARIES:
            with self.subTest(library=library):
                done = self.run_check(library)
                self.assertEqual(0, done.returncode,
                                 "%s does not pass --check:\n%s" % (library, done.stdout[-2000:]))
                self.assertNotIn("找不到", done.stdout)
                self.assertNotIn("行号是旧地图", done.stdout)

    def test_the_reading_is_printed_so_a_reader_sees_what_was_verified(self):
        done = self.run_check(LIBRARIES[0])
        self.assertIn("出处核对", done.stdout,
                      "the citation reading is not printed; a reader cannot see it happened")

    def test_no_shipped_episode_is_left_unverified(self):
        """Every episode resolves its commit -- where a history exists to resolve it against.

        A frozen extract has no `.git`, so the commits cannot be looked up there. That
        is a different fact from "the commits are gone", and this test must not turn
        it into a pass: it checks the working tree, and says so by skipping where the
        question cannot be asked.
        """
        if not (ROOT / ".git").exists():
            self.skipTest("no .git here: a frozen extract cannot resolve commits")
        for library in LIBRARIES:
            data = {"episodes": json.loads(
                (ROOT / "docs" / "dao" / library / "episodes.json").read_text(encoding="utf-8"))}
            reading = dao_life.check_sources(data, base=ROOT, git=True)
            with self.subTest(library=library):
                self.assertEqual([], reading["failures"], reading["failures"])
                self.assertEqual([], reading["unresolved_commits"],
                                 "these episodes name a commit that is not in this repository")

    def test_the_new_library_records_the_chain_it_claims(self):
        """The slice's own library: one episode, one dao, three landings."""
        library = ROOT / "docs" / "dao" / "repeat-safety"
        self.assertTrue(library.is_dir(), "the chain library is missing")
        daos = json.loads((library / "daos.json").read_text(encoding="utf-8"))["daos"]
        observations = json.loads((library / "observations.json").read_text(encoding="utf-8"))
        self.assertEqual(1, len(daos))
        self.assertEqual({"repeat-d-001"}, {dao["id"] for dao in daos})
        self.assertEqual(3, len(observations["observations"]),
                         "the chain claims three landings; the record has a different number")
        for observation in observations["observations"]:
            # Each landing must carry a reading a re-run can reproduce, not a verdict alone.
            self.assertTrue(observation.get("result"), observation["id"])
            self.assertTrue(observation.get("could_have_gone_otherwise"), observation["id"])
            self.assertIs(True, observation.get("matched"), observation["id"])


class AReaderCanReachTheChain(unittest.TestCase):
    """A page nobody is pointed at is a page nobody reads.

    Checked as routes rather than as sentences: each front page must link to the
    narrative, the narrative must name both uses, and the library it describes must
    be the one the command actually reads.
    """

    CHAIN = "docs/dao/repeat-safety/LOOP.md"

    def page(self, name):
        return (ROOT / name).read_text(encoding="utf-8")

    def test_both_front_pages_link_to_the_chain(self):
        for page in ("README.md", "README.zh-CN.md"):
            with self.subTest(page=page):
                self.assertIn(self.CHAIN, self.page(page))

    def test_the_dao_index_links_to_the_chain_and_says_what_check_now_reads(self):
        index = self.page("docs/dao/README.md")
        self.assertIn("repeat-safety/LOOP.md", index)
        self.assertIn("--check", index)
        self.assertIn("source", index, "the index does not say that source is now read")

    def test_the_two_uses_are_named_where_a_reader_starts(self):
        """The supervisor asked for the judgement and its two uses from the normal entry."""
        for page in ("README.md", "README.zh-CN.md"):
            text = self.page(page)
            with self.subTest(page=page):
                self.assertIn("attach-source", text)
                self.assertIn("3", text)

    def test_the_narrative_names_the_three_readings_and_the_correction(self):
        loop = self.page(self.CHAIN)
        for marker in ("决定 A", "决定 B", "决定 C"):
            self.assertIn(marker, loop, "the narrative dropped %s" % marker)
        # The correction is the part a reader is most likely to want to check first.
        self.assertIn("我自己错在哪", loop)
        self.assertIn("test_attaching_the_same_session_twice_is_a_no_op", loop)

    def test_the_narrative_does_not_claim_more_than_the_readings(self):
        """It must keep its own limits, including the one the gate cannot cover."""
        loop = self.page(self.CHAIN)
        self.assertIn("还证明不了什么", loop)
        self.assertIn("不是「他的看法」", loop)
        self.assertIn("同一只手", loop)
        self.assertIn("空白压平", loop, "the squashing limit is not written down")
        # A re-check found two regressions through the ordinary CLI; the record has to
        # carry them, or the next reader believes the first version was right.
        self.assertIn("两个反例", loop)
        self.assertIn("test_recheck_counterexamples", loop)



if __name__ == "__main__":
    unittest.main()
