"""Two more boundaries a re-check found by using the thing, not by reading it.

  1. **The quote was checked in the working tree, not at the cited revision.**
     Two commits can share a path while the sentence arrives in the second one.
     Pointing the quote at the first still answered `pass`, and a reader who followed
     the citation to that revision would not find the words. The quote and the line
     number now come from the file *at the cited commit*; without a history the
     working tree is all there is and the verdict says `unchecked`, not `pass`.

  2. **The session rule for group-less sources was removed wholesale.** It was too
     broad, not wrong. The public version returned 0 and wrote nothing when a session
     that had already contributed attached another group-less source; my version
     recorded it. A source naming a *fresh* group must still be recorded -- that was
     the original defect.

Both are checked here against a real temporary repository and the real CLI, because
that is how the re-check found them.
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
        if (parent / "dojo" / "cli.py").is_file() and (parent / "scripts" / "dao_life.py").is_file():
            return parent
    raise RuntimeError("cannot locate the dojo repository root")


ROOT = _repo_root()
SPEC = importlib.util.spec_from_file_location("dao_life_boundaries", ROOT / "scripts" / "dao_life.py")
dao_life = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dao_life)


class AQuoteIsCheckedAtTheCitedRevision(unittest.TestCase):
    """Same path in two commits; the sentence arrives in the second one."""

    PATH = "doc/prose.md"
    QUOTE = "the second revision adds this sentence"

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="dojo-rev."))
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.work)
        (self.work / "doc").mkdir()
        (self.work / self.PATH).write_text("# T\n\nthe first revision says this\n", encoding="utf-8")
        self.commit("one")
        self.first = self.head()
        (self.work / self.PATH).write_text(
            "# T\n\nthe first revision says this\n" + self.QUOTE + "\n", encoding="utf-8")
        self.commit("two")
        self.second = self.head()

    def git(self, *argv):
        done = subprocess.run(["git", *argv], cwd=str(self.work), capture_output=True, text=True)
        self.assertEqual(0, done.returncode, done.stderr)
        return done

    def commit(self, message):
        self.git("init", "-q", ".") if not (self.work / ".git").exists() else None
        self.git("add", "-A")
        self.git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", message)

    def head(self):
        return self.git("rev-parse", "--short", "HEAD").stdout.strip()

    def line_of(self, commit):
        text = self.git("show", commit + ":" + self.PATH).stdout.splitlines()
        return [number for number, line in enumerate(text, 1) if self.QUOTE in line][0]

    def reading(self, commit, ref=None):
        ref = ref or "第 %d 行" % self.line_of(self.second)
        episode = {"id": "e1", "at": "2026-01-01", "attribution": "person",
                   "attribution_note": "t", "quote": self.QUOTE,
                   "source": {"path": self.PATH, "ref": ref, "commit": commit},
                   "observed_action": "t", "reading": "t"}
        data = {"episodes": {"layer": "events", "owner": "t", "what": "t",
                             "person": {"id": "p", "label": "p"},
                             "window": {"first_session": "2026-01-01",
                                        "last_person_input": "2026-12-31", "rule": "t"},
                             "episodes": [episode]}}
        return dao_life.check_sources(data, base=self.work, git=True)

    def test_the_revision_that_has_the_sentence_passes(self):
        reading = self.reading(self.second)
        self.assertEqual("pass", reading["verdict"], reading["failures"])
        self.assertEqual("commit", reading["rows"][0]["checked_at"])

    def test_the_earlier_revision_fails_even_though_it_has_the_file(self):
        """The defect: the object held the path, so only that was checked."""
        reading = self.reading(self.first)
        self.assertEqual("fail", reading["verdict"],
                         "the words are not in that revision; a reader following the "
                         "citation would not find them")
        self.assertEqual("commit", reading["rows"][0]["checked_at"],
                         "this must be decided from the revision, not the working tree")

    def test_a_line_number_from_the_other_revision_fails(self):
        """Line numbers are per revision too; the older file is shorter."""
        reading = self.reading(self.first, ref="第 %d 行" % 4)
        self.assertEqual("fail", reading["verdict"], reading["failures"])

    def test_without_a_history_the_verdict_says_unchecked(self):
        """A frozen extract cannot consult a revision, so it must not claim it did."""
        reading = dao_life.check_sources(
            {"episodes": {"layer": "events", "owner": "t", "what": "t",
                          "person": {"id": "p", "label": "p"},
                          "window": {"first_session": "2026-01-01",
                                     "last_person_input": "2026-12-31", "rule": "t"},
                          "episodes": [{"id": "e1", "at": "2026-01-01",
                                        "attribution": "person", "attribution_note": "t",
                                        "quote": self.QUOTE,
                                        "source": {"path": self.PATH,
                                                   "ref": "第 %d 行" % 4,
                                                   "commit": self.second},
                                        "observed_action": "t", "reading": "t"}]}},
            base=self.work, git=False)
        self.assertEqual("unchecked", reading["verdict"])
        self.assertEqual("working-tree", reading["rows"][0]["checked_at"])


class GroupLessSourcesKeepTheirSessionRule(unittest.TestCase):
    """The public behaviour, then the defect it must not reintroduce."""

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="dojo-attach."))
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("DOJO_")}
        self.env["PYTHONPATH"] = str(ROOT)
        self.env["PYTHONDONTWRITEBYTECODE"] = "1"
        self.env["DOJO_DB"] = str(self.work / "ledger.sqlite3")

    def cli(self, *argv):
        return subprocess.run([sys.executable, "-B", "-m", "dojo", *argv],
                              cwd=str(ROOT), capture_output=True, text=True,
                              env=self.env, timeout=120)

    def source(self, ident, claim, group=None):
        value = {"id": ident, "type": "unknown", "claim": claim, "verification": "unknown"}
        if group:
            value["independence_group"] = group
        return json.dumps(value)

    def attach(self, ident, claim, session, group=None):
        return self.cli("attach-source", "k", "--source-json",
                        self.source(ident, claim, group), "--session", session)

    def setUpLedger(self):
        added = self.cli("add", "--id", "k", "--kind", "abstract_idea", "--statement", "句子",
                         "--source-json", self.source("a1", "甲"), "--session", "s1")
        self.assertEqual(0, added.returncode, added.stderr[-800:])
        first = self.attach("b1", "乙", "s2")
        self.assertEqual(0, first.returncode, first.stderr[-800:])

    def sources(self):
        done = self.cli("show", "k")
        self.assertEqual(0, done.returncode, done.stderr[-800:])
        return [item["id"] for item in json.loads(done.stdout)["candidate"]["sources"]]

    def test_two_sessions_with_group_less_sources_are_recorded(self):
        self.setUpLedger()
        self.assertEqual(["a1", "b1"], self.sources())

    def test_a_third_group_less_source_from_a_known_session_is_not_recorded(self):
        """The boundary: the public version returned 0 and left the ledger unchanged."""
        self.setUpLedger()
        before = self.sources()
        done = self.attach("c1", "丙", "s1")
        self.assertEqual(0, done.returncode, done.stderr[-800:])
        self.assertEqual(before, self.sources(),
                         "a group-less source from a session that already contributed is a replay")

    def test_a_fresh_named_group_from_a_known_session_is_still_recorded(self):
        """The defect: gating everything on the session dropped new provenance."""
        self.setUpLedger()
        done = self.attach("g1", "丁", "s1", group="group-new")
        self.assertEqual(0, done.returncode, done.stderr[-800:])
        self.assertIn("g1", self.sources(),
                      "a source naming a group the card does not have must be recorded")

    def test_the_session_attribution_of_an_earlier_source_survives(self):
        """Recording the new group must not cost the existing attribution."""
        self.setUpLedger()
        self.attach("g1", "丁", "s1", group="group-new")
        done = self.cli("show", "k")
        candidate = json.loads(done.stdout)["candidate"]
        groups = [item["independence_group"] for item in candidate["sources"]]
        self.assertEqual(["unknown", "unknown", "group-new"], groups)
        self.assertEqual(["s1", "s2"], candidate["sessions"])


if __name__ == "__main__":
    unittest.main()
