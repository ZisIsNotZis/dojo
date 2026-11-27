"""Two counterexamples a re-check found by using the CLI, not by reading the code.

Both were retry/verification paths, which is exactly what this slice's judgement is
about, and both were mine:

  1. `attach-source` replaying a *group-less* source exited 2 with
     "source ID already exists". The public version returned 0 and wrote nothing.
     A replay of the same provenance must be the same no-op it always was, whatever
     the source names -- the judgement says a repeat is decided by the request, and
     the request here was identical.

  2. A citation whose commit *exists* but predates the cited file was reported
     `pass`. Checking that the object is a commit says nothing about whether the
     file the quote came from was in that revision, so a quote could be "verified"
     against a revision that never contained it.

Both are pinned at the level the re-check used them: the CLI for the first, the
gate's own reading for the second.
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
SPEC = importlib.util.spec_from_file_location("dao_life_recheck", ROOT / "scripts" / "dao_life.py")
dao_life = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dao_life)


class ReplayingAGroupLessSourceIsANoOp(unittest.TestCase):
    """The CLI, verbatim: two sessions, no group named, then the second one again."""

    SOURCE_A = {"id": "src-a", "type": "unknown", "claim": "甲先说的", "verification": "unknown"}
    SOURCE_B = {"id": "src-b", "type": "unknown", "claim": "乙再说的", "verification": "unknown"}

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="dojo-replay."))
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("DOJO_")}
        self.env["PYTHONPATH"] = str(ROOT)
        self.env["PYTHONDONTWRITEBYTECODE"] = "1"
        self.env["DOJO_DB"] = str(self.work / "ledger.sqlite3")

    def cli(self, *argv):
        return subprocess.run([sys.executable, "-B", "-m", "dojo", *argv],
                              cwd=str(ROOT), capture_output=True, text=True,
                              env=self.env, timeout=120)

    def setUpLedger(self):
        added = self.cli("add", "--id", "c1", "--kind", "abstract_idea",
                         "--statement", "句子", "--source-json", json.dumps(self.SOURCE_A),
                         "--session", "s1")
        self.assertEqual(0, added.returncode, added.stderr[-800:])
        first = self.cli("attach-source", "c1", "--source-json", json.dumps(self.SOURCE_B),
                         "--session", "s2")
        self.assertEqual(0, first.returncode, first.stderr[-800:])

    def events(self):
        done = self.cli("events", "--id", "c1")
        self.assertEqual(0, done.returncode, done.stderr[-800:])
        return [row["event"] for row in json.loads(done.stdout)]

    def sources(self):
        done = self.cli("show", "c1")
        self.assertEqual(0, done.returncode, done.stderr[-800:])
        return [item["id"] for item in json.loads(done.stdout)["candidate"]["sources"]]

    def test_the_second_session_still_adds_provenance(self):
        self.setUpLedger()
        self.assertEqual(["src-a", "src-b"], self.sources())

    def test_replaying_it_exits_zero_and_writes_nothing(self):
        """The defect: exit 2, "source ID already exists", on an exact replay."""
        self.setUpLedger()
        before, events_before = self.sources(), self.events()
        again = self.cli("attach-source", "c1", "--source-json", json.dumps(self.SOURCE_B),
                         "--session", "s2")
        self.assertEqual(0, again.returncode,
                         "a replay of the same provenance is a no-op, not an error:\n%s"
                         % again.stderr[-800:])
        self.assertEqual(before, self.sources())
        self.assertEqual(events_before, self.events(),
                         "a no-op replay must not write an event either")

    def test_the_same_named_group_under_the_same_session_is_still_a_no_op(self):
        """The published contract this must not break while fixing the one above."""
        self.setUpLedger()
        same_group = dict(self.SOURCE_B, id="src-c", claim="同一组里的另一句话",
                          independence_group="src-a")
        done = self.cli("attach-source", "c1", "--source-json", json.dumps(same_group),
                        "--session", "s2")
        self.assertEqual(0, done.returncode, done.stderr[-800:])


class ACitedFileMustExistAtTheCitedCommit(unittest.TestCase):
    """A resolvable commit is not enough; the file has to be in that revision."""

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="dojo-cite-commit."))
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.work)
        self.git("init", "-q", ".")
        (self.work / "a.txt").write_text("other\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "one")
        self.older = self.git("rev-parse", "--short", "HEAD").stdout.strip()
        (self.work / "doc").mkdir()
        (self.work / "doc" / "prose.md").write_text("# T\n\nthe quoted sentence lives here\n",
                                                    encoding="utf-8")
        self.git("add", "-A")
        self.git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "two")
        self.newer = self.git("rev-parse", "--short", "HEAD").stdout.strip()

    def git(self, *argv):
        done = subprocess.run(["git", *argv], cwd=str(self.work), capture_output=True, text=True)
        self.assertEqual(0, done.returncode, done.stderr)
        return done

    def reading(self, commit):
        episode = {"id": "e1", "at": "2026-01-01", "attribution": "person",
                   "attribution_note": "t", "quote": "the quoted sentence lives here",
                   "source": {"path": "doc/prose.md", "ref": "第 3 行", "commit": commit},
                   "observed_action": "t", "reading": "t"}
        data = {"episodes": {"layer": "events", "owner": "t", "what": "t",
                             "person": {"id": "p", "label": "p"},
                             "window": {"first_session": "2026-01-01",
                                        "last_person_input": "2026-12-31", "rule": "t"},
                             "episodes": [episode]}}
        return dao_life.check_sources(data, base=self.work, git=True)

    def test_the_commit_that_holds_the_file_passes(self):
        reading = self.reading(self.newer)
        self.assertEqual("pass", reading["verdict"], reading["failures"])
        self.assertEqual("resolved", reading["rows"][0]["commit_state"])

    def test_a_real_commit_that_predates_the_file_fails(self):
        """The defect: a genuine commit, so the object check said `pass`."""
        reading = self.reading(self.older)
        self.assertEqual("fail", reading["verdict"],
                         "a quote cannot be verified against a revision that never had the file")
        self.assertEqual("missing-path", reading["rows"][0]["commit_state"])
        self.assertTrue(any("没有" in line and "doc/prose.md" in line
                            for line in reading["failures"]), reading["failures"])

    def test_a_commit_that_does_not_exist_is_unchecked_not_failed(self):
        """Keep the three words apart: gone, wrong revision, verified."""
        reading = self.reading("deadbee")
        self.assertEqual("unchecked", reading["verdict"])
        self.assertEqual("unresolved", reading["rows"][0]["commit_state"])


if __name__ == "__main__":
    unittest.main()
