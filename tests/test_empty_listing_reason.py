"""r102: an empty `stories` / `knowledge` listing must name which of six things it is.

Measured before this on real files. `python -m dojo --db X stories` printed the
identical platform-native `[]
` for a missing path, for a healthy sqlite file that is not a
dojo library, for a dojo library with no start rows, and for a view that
filtered everything; `knowledge` printed the same 4 bytes for the first three.
On top of that, `stories` discarded 21 of 251 real stories with no line
anywhere because their opening turn is gone, and raised an uncaught `KeyError`
on two libraries whose `delivered` rows lack `reflection_event`.

Pinned here:
  * each situation prints its own reason line on stderr;
  * stdout is byte-identical to the pre-r102 value in every one of them;
  * a listing that is merely incomplete says so, and says which story;
  * no reason sentence calls a readable library broken;
  * the paths are read-only: no file changes and no file is created.
"""
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'dojo' / 'cli.py').is_file())
ENV = {**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1'}
EMPTY = ('[]' + os.linesep).encode('ascii')


def listing(db, command, *extra):
    proc = subprocess.run(
        [sys.executable, '-X', 'utf8', '-m', 'dojo', '--db', str(db), command, *extra],
        cwd=str(ROOT), capture_output=True, env=ENV)
    return proc.returncode, proc.stdout, proc.stderr.decode('utf-8', 'replace')


class EmptyListingReasonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def dojo_library(self, name, *, starts=0, proposals=0, users=0):
        """A real inquiry schema, built the way the product builds one."""
        target = self.dir / name
        db = sqlite3.connect(target)
        db.execute('CREATE TABLE inquiry_events (seq INTEGER PRIMARY KEY, run TEXT, kind TEXT, payload TEXT, at TEXT)')
        db.execute('CREATE TABLE inquiry_dependencies (premise INTEGER, conclusion INTEGER, relation TEXT)')
        seq = 0
        for _ in range(starts):
            seq += 1
            run = f'run{seq}'
            db.execute('INSERT INTO inquiry_events VALUES(?,?,?,?,?)',
                       (seq, run, 'start', json.dumps({'story': run, 'synthetic': True}), '2026-11-13T00:00:00Z'))
        for _ in range(users):
            seq += 1
            db.execute('INSERT INTO inquiry_events VALUES(?,?,?,?,?)',
                       (seq, 'run1', 'user', json.dumps({'text': '开场', 'synthetic': True}), '2026-11-13T00:01:00Z'))
        for n in range(proposals):
            seq += 1
            db.execute('INSERT INTO inquiry_events VALUES(?,?,?,?,?)',
                       (seq, 'run1', 'knowledge_proposal', json.dumps({'synthetic': True, 'proposal': {'statement': f'p{n}'}}),
                        '2026-11-13T00:02:00Z'))
        db.commit()
        db.close()
        return target

    # --- stories ---------------------------------------------------------

    def test_a_missing_path_says_it_could_not_see_the_library(self):
        for command, what in (('stories', '故事'), ('knowledge', '知识提议')):
            code, out, err = listing(self.dir / 'not-there.sqlite3', command)
            self.assertEqual(0, code, err)
            self.assertEqual(EMPTY, out, command)
            self.assertIn('空列表原因（absent）', err, command)
            self.assertIn('这个路径上没有文件', err)
            self.assertIn(what, err)

    def test_a_file_with_another_schema_is_named_not_called_broken(self):
        target = self.dir / 'store.sqlite3'
        db = sqlite3.connect(target)
        db.execute('CREATE TABLE candidates (id TEXT, version INTEGER)')
        db.execute('CREATE TABLE events (seq INTEGER)')
        db.commit()
        db.close()
        for command in ('stories', 'knowledge'):
            code, out, err = listing(target, command)
            self.assertEqual(0, code, err)
            self.assertEqual(EMPTY, out, command)
            self.assertIn('空列表原因（schema）', err, command)
            self.assertIn('candidates', err)
            self.assertIn('没有 inquiry_events', err)
            for word in ('坏', '损坏', '打不开', 'corrupt', 'malformed'):
                self.assertNotIn(word, err, command)

    def test_a_dojo_library_with_no_start_rows_says_so(self):
        target = self.dojo_library('nothing.sqlite3')
        code, out, err = listing(target, 'stories')
        self.assertEqual(0, code, err)
        self.assertEqual(EMPTY, out)
        self.assertIn('空列表原因（rows）', err)
        self.assertIn('没有一条 start 记录', err)

    def test_a_dojo_library_with_no_proposals_says_so(self):
        target = self.dojo_library('no-proposals.sqlite3', starts=1, users=1)
        code, out, err = listing(target, 'knowledge')
        self.assertEqual(0, code, err)
        self.assertEqual(EMPTY, out)
        self.assertIn('空列表原因（rows）', err)
        self.assertIn('没有知识提议记录', err)

    def test_a_synthetic_only_view_says_it_did_not_show_you_them(self):
        target = self.dojo_library('synthetic-only.sqlite3', starts=1, users=1)
        # starts are written as synthetic above; the default view excludes them.
        code, out, err = listing(target, 'stories')
        self.assertEqual(0, code, err)
        self.assertEqual(EMPTY, out)
        self.assertIn('空列表原因（view）', err)
        self.assertIn('--synthetic', err)
        self.assertIn('不是「库里没有」', err)

    def test_a_story_dropped_for_a_missing_opening_is_named_not_hidden(self):
        """The listing itself discards it; the reason line must not."""
        target = self.dojo_library('dropped.sqlite3', starts=2)
        code, out, err = listing(target, 'stories', '--synthetic')
        self.assertEqual(0, code, err)
        self.assertEqual(EMPTY, out)
        self.assertIn('空列表原因（drop）', err)
        self.assertIn('没有开场白', err)
        self.assertIn('run1', err)

    # --- knowledge: the table layer (r103) -------------------------------

    def full_knowledge_library(self, name):
        """A ledger with proposals and every table `proposals()` reads."""
        target = self.dojo_library(name, starts=1, users=1, proposals=2)
        db = sqlite3.connect(target)
        db.execute('CREATE TABLE inquiry_revisions (old_event INTEGER PRIMARY KEY, new_event INTEGER NOT NULL, reason TEXT NOT NULL)')
        db.execute('CREATE TABLE inquiry_review_queue (event INTEGER NOT NULL, cause INTEGER NOT NULL, state TEXT NOT NULL DEFAULT \'pending\', PRIMARY KEY(event,cause))')
        db.commit()
        db.close()
        return target

    def test_a_ledger_missing_a_table_it_reads_names_that_table(self):
        """Measured on real-library copies: `proposals()` reads four tables."""
        for table in ('inquiry_dependencies', 'inquiry_revisions', 'inquiry_review_queue'):
            target = self.full_knowledge_library(f'missing-{table}.sqlite3')
            db = sqlite3.connect(target)
            db.execute(f'DROP TABLE {table}')
            db.commit()
            db.close()
            # Both views: the false promise ('加 --synthetic 可查看') is only
            # printed by the default view, so --synthetic alone would miss it.
            for extra in ((), ('--synthetic',)):
                code, out, err = listing(target, 'knowledge', *extra)
                label = f'{table} {" ".join(extra) or "default"}'
                self.assertEqual(0, code, f'{label}: {err}')
                self.assertEqual(EMPTY, out, label)
                self.assertIn('空列表原因（table）', err, label)
                self.assertIn(table, err, label)
                # The scope note promised rows this listing cannot produce.
                self.assertNotIn('加 --synthetic 可查看', err, label)
                self.assertIn('不是「这个库里没有知识提议」', err, label)

    def test_the_same_library_lists_normally_once_all_tables_are_present(self):
        target = self.full_knowledge_library('complete.sqlite3')
        code, out, err = listing(target, 'knowledge', '--synthetic')
        self.assertEqual(0, code, err)
        self.assertEqual(2, len(json.loads(out.decode('utf-8'))), err)
        self.assertNotIn('（table）', err)

    def test_an_incomplete_listing_says_which_story_is_missing(self):
        target = self.dojo_library('partial.sqlite3', starts=2, users=1)
        code, out, err = listing(target, 'stories', '--synthetic')
        self.assertEqual(0, code, err)
        self.assertEqual(1, len(json.loads(out.decode('utf-8'))))
        self.assertIn('列表不完整（drop）', err)
        self.assertIn('run2', err)

    def test_a_library_whose_delivered_rows_lack_reflection_event_still_lists(self):
        """Two real libraries raised an uncaught KeyError here before r102."""
        target = self.dojo_library('legacy-delivered.sqlite3', starts=1, users=1)
        db = sqlite3.connect(target)
        nxt = db.execute('SELECT max(seq) FROM inquiry_events').fetchone()[0] + 1
        db.execute("INSERT INTO inquiry_events VALUES(?,'run1','delivered',?, '2026-11-13T00:09:00Z')",
                   (nxt, json.dumps({'by': 'old-writer'})))
        db.commit()
        db.close()
        code, out, err = listing(target, 'stories', '--synthetic')
        self.assertEqual(0, code, err)
        self.assertNotIn('Traceback', err)
        self.assertNotIn('KeyError', err)
        self.assertEqual(1, len(json.loads(out.decode('utf-8'))))

    def test_the_reason_never_replaces_the_json(self):
        """A non-empty listing keeps its stderr quiet about absence."""
        target = self.dojo_library('fine.sqlite3', starts=1, users=1)
        code, out, err = listing(target, 'stories', '--synthetic')
        self.assertEqual(0, code, err)
        self.assertEqual(1, len(json.loads(out.decode('utf-8'))))
        for state in ('absent', 'schema', 'rows', 'view', 'drop'):
            self.assertNotIn(f'（{state}）', err)

    def test_listing_is_read_only_and_creates_nothing(self):
        target = self.dojo_library('ro.sqlite3', starts=1, users=1)
        before = hashlib.sha256(target.read_bytes()).hexdigest()
        names_before = sorted(p.name for p in self.dir.iterdir())
        listing(target, 'stories')
        listing(target, 'knowledge')
        listing(self.dir / 'absent.sqlite3', 'stories')
        self.assertEqual(before, hashlib.sha256(target.read_bytes()).hexdigest())
        self.assertEqual(names_before, sorted(p.name for p in self.dir.iterdir()))
        self.assertFalse((self.dir / 'absent.sqlite3').exists())


if __name__ == '__main__':
    unittest.main()
