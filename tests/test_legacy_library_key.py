"""Existing libraries, and the two ways an earlier version of this change lost data.

`CREATE TABLE IF NOT EXISTS` never touches an existing table, so a library created before
`candidates.id` gained `NOT NULL` keeps the weaker declaration: it accepts NULL keys while
a library created now refuses them, and nothing visible says so.

Two designs were rejected by review, and both are pinned here so they cannot come back:

  1. **Repairing on open.** Opening a library modified it. Worse, the "backup" it kept was
     a copy of the main file only: in WAL mode committed rows can live in `-wal`, so the
     copy was empty, and the restore path would have put that empty file back over a live
     library. Opening now only reports; `scripts/upgrade_key_constraint.py` is the
     migration, and it keeps no copy and has no restore.
  2. **Refusing on the presence of `-wal`/`-shm`.** Those sidecars linger after a clean
     close, so that test called idle libraries "in use" forever. The migration tests the
     write lock instead, held by a genuinely separate process.

What people need, in their words: normal history stays readable, and after the migration
it is constrained too.
"""

from __future__ import annotations

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


def _repo_root():
    if os.environ.get('DOJO_ROOT'):
        return Path(os.environ['DOJO_ROOT']).resolve()
    for parent in Path(__file__).resolve().parents:
        if (parent / 'dojo' / 'cli.py').is_file() and (parent / 'docs' / 'cli-guide.md').is_file():
            return parent
    raise RuntimeError('cannot locate the dojo repository root')


ROOT = _repo_root()
sys.path.insert(0, str(ROOT))
from dojo.storage import Store, DojoError  # noqa: E402

UPGRADE = ROOT / 'scripts' / 'upgrade_key_constraint.py'

# The schema as it stood before the NOT NULL was added, written out so this test does not
# need a git checkout.
LEGACY_SCHEMA = """
CREATE TABLE candidates (
    id TEXT PRIMARY KEY,
    version INTEGER NOT NULL CHECK(version > 0),
    state_json TEXT NOT NULL
);
CREATE TABLE snapshots (
    candidate_id TEXT NOT NULL REFERENCES candidates(id),
    version INTEGER NOT NULL,
    state_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(candidate_id, version)
);
CREATE TABLE events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id TEXT REFERENCES candidates(id),
    event TEXT NOT NULL,
    details_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX events_by_candidate ON events(candidate_id, seq);
CREATE TABLE pipeline_marks (
    session TEXT NOT NULL,
    pass_name TEXT NOT NULL,
    candidate_id TEXT NOT NULL REFERENCES candidates(id),
    version INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(session, pass_name, candidate_id)
);
"""


def legacy_state(identifier, statement):
    return {'id': identifier, 'statement': statement, 'kind': 'abstract_idea',
            'version': 1, 'status': 'draft', 'sources': [], 'premises': [], 'scope': [],
            'alternatives': [], 'contradictions': [], 'unknowns': []}


class ExistingLibraries(unittest.TestCase):
    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix='legacy-key.'))
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)

    def legacy_library(self, *, with_null_key: bool = False, rows: int = 3) -> Path:
        path = self.work / ('broken.sqlite3' if with_null_key else 'healthy.sqlite3')
        db = sqlite3.connect(path)
        db.executescript(LEGACY_SCHEMA)
        for index in range(rows):
            identifier = 'd-legacy%04d' % index
            state = legacy_state(identifier, '旧库的第 %d 条' % index)
            db.execute('INSERT INTO candidates VALUES(?,?,?)',
                       (identifier, 1, json.dumps(state)))
            db.execute('INSERT INTO snapshots VALUES(?,?,?,?)',
                       (identifier, 1, json.dumps(state), '2026-01-01T00:00:00Z'))
        if with_null_key:
            db.execute('INSERT INTO candidates VALUES(NULL,1,?)',
                       (json.dumps(legacy_state(None, '直接写入的 NULL 主键行')),))
        db.commit()
        db.close()
        return path

    def digest(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def columns(self, path: Path) -> dict:
        db = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
        try:
            return {row[1]: row[3] for row in db.execute('PRAGMA table_info(candidates)')}
        finally:
            db.close()

    def run_upgrade(self, path: Path, *args):
        env = {k: os.environ[k] for k in ('PATH', 'LANG', 'TZ', 'TMPDIR') if k in os.environ}
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        proc = subprocess.run([sys.executable, '-B', str(UPGRADE), str(path), *args],
                              cwd=str(ROOT), capture_output=True, text=True, env=env,
                              timeout=300)
        return proc.returncode, (json.loads(proc.stdout) if proc.stdout.strip() else {})

    def test_a_new_library_has_the_constraint(self):
        path = self.work / 'new.sqlite3'
        Store(str(path)).close()
        self.assertEqual(1, self.columns(path)['id'])

    # --- opening must not repair, and must not need a backup -------------------------

    def test_opening_a_legacy_library_for_writing_refuses_and_never_modifies_it(self):
        """Design 1: the repair-on-open that had to be removed."""
        path = self.legacy_library()
        before = self.digest(path)
        with self.assertRaises(DojoError) as caught:
            Store(str(path))
        message = str(caught.exception)
        self.assertIn('candidates.id', message)
        self.assertIn('upgrade_key_constraint.py', message)
        self.assertEqual(before, self.digest(path), 'opening a library modified it')
        self.assertFalse(path.with_suffix(path.suffix + '.pre-not-null.bak').exists(),
                         'a sidecar copy was taken by a read; that copy is exactly what '
                         'was empty under WAL and could have been restored over live data')

    def test_reading_a_legacy_library_with_plain_sqlite_still_works(self):
        path = self.legacy_library()
        db = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
        try:
            self.assertEqual(3, db.execute('SELECT count(*) FROM candidates').fetchone()[0])
        finally:
            db.close()

    # --- the explicit migration ----------------------------------------------------

    def test_the_migration_constrains_the_library_and_keeps_every_row(self):
        path = self.legacy_library(rows=3)
        code, result = self.run_upgrade(path)
        self.assertEqual(0, code, result)
        self.assertEqual('upgraded', result['state'])
        self.assertEqual(1, self.columns(path)['id'])

        db = sqlite3.connect(path)
        try:
            ids = [row[0] for row in db.execute('SELECT id FROM candidates ORDER BY rowid')]
            statements = [json.loads(row[0])['statement']
                          for row in db.execute('SELECT state_json FROM candidates ORDER BY rowid')]
            snapshots = db.execute('SELECT count(*) FROM snapshots').fetchone()[0]
            integrity = db.execute('PRAGMA integrity_check').fetchone()[0]
            refusal = None
            try:
                db.execute('INSERT INTO candidates VALUES(NULL,1,?)', (json.dumps({'x': 1}),))
                db.commit()
            except sqlite3.IntegrityError as error:
                refusal = str(error)
        finally:
            db.close()
        self.assertEqual(['d-legacy0000', 'd-legacy0001', 'd-legacy0002'], ids,
                         'rows were renumbered or lost')
        self.assertEqual(['旧库的第 0 条', '旧库的第 1 条', '旧库的第 2 条'], statements,
                         'row contents changed')
        self.assertEqual(3, snapshots, 'another table was touched')
        self.assertEqual('ok', integrity)
        self.assertIsNotNone(refusal, 'the migrated library still accepts a NULL key')

        # Idempotent, and it must not claim to have changed anything the second time.
        before = self.digest(path)
        code, again = self.run_upgrade(path)
        self.assertEqual(0, code)
        self.assertEqual('already_constrained', again['state'])
        self.assertEqual(before, self.digest(path))

    def test_the_migration_refuses_while_another_process_holds_the_library(self):
        """The supervisor's reproduction, with a genuinely separate process."""
        path = self.legacy_library(rows=0)
        holder = subprocess.Popen(
            [sys.executable, '-c', (
                'import json, sqlite3, sys, time\n'
                'db = sqlite3.connect(sys.argv[1], isolation_level=None)\n'
                'db.execute("PRAGMA journal_mode=WAL")\n'
                'db.execute("BEGIN IMMEDIATE")\n'
                'db.execute("INSERT INTO candidates VALUES(?,1,?)",\n'
                '           ("d-keepme", json.dumps({"id": "d-keepme", "statement": "keep-me"})))\n'
                'print("held", flush=True)\n'
                'time.sleep(3)\n'
                'db.execute("COMMIT")\n'
                'print("committed", flush=True)\n'
                'time.sleep(1)\n'
                'db.close()\n'), str(path)],
            stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual('held', holder.stdout.readline().strip())
            code, result = self.run_upgrade(path)
        finally:
            holder.wait(timeout=30)
        self.assertEqual(2, code, result)
        self.assertEqual('in_use', result['state'])
        self.assertFalse(result['changed'])

        db = sqlite3.connect(path)
        try:
            self.assertEqual(1, db.execute(
                "SELECT count(*) FROM candidates WHERE id='d-keepme'").fetchone()[0],
                'the row committed by the other connection was lost')
        finally:
            db.close()

        # Once nobody holds it, the same command goes through and keeps the row.
        code, result = self.run_upgrade(path)
        self.assertEqual(0, code, result)
        self.assertEqual('upgraded', result['state'])
        self.assertEqual(1, self.columns(path)['id'])

    def test_the_migration_keeps_the_library_own_structure(self):
        """Review case: a rebuild that drops indexes, or eats a user table it reused.

        Both happened in the previous version and it still reported `upgraded /
        integrity ok`, which is why structure is now compared before and after rather
        than assumed.
        """
        path = self.legacy_library(rows=2)
        db = sqlite3.connect(path)
        db.execute('CREATE INDEX user_idx_on_candidates ON candidates(version)')
        db.execute('CREATE TRIGGER user_trg AFTER INSERT ON candidates '
                   'BEGIN SELECT 1; END')
        db.execute('CREATE TABLE candidates_upgrade(note TEXT)')
        db.execute("INSERT INTO candidates_upgrade VALUES('user data')")
        db.commit()
        before_objects = sorted(name for (name,) in db.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','index','trigger') "
            "AND name NOT LIKE 'sqlite_%'"))
        db.close()

        code, result = self.run_upgrade(path)
        self.assertEqual(0, code, result)
        self.assertEqual('upgraded', result['state'])

        db = sqlite3.connect(path)
        try:
            after_objects = sorted(name for (name,) in db.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','index','trigger') "
                "AND name NOT LIKE 'sqlite_%'"))
            user_rows = db.execute('SELECT count(*) FROM candidates_upgrade').fetchone()[0]
            ids = [row[0] for row in db.execute('SELECT id FROM candidates ORDER BY rowid')]
            integrity = db.execute('PRAGMA integrity_check').fetchone()[0]
        finally:
            db.close()
        self.assertEqual(before_objects, after_objects,
                         'the migration changed the set of tables/indexes/triggers')
        self.assertEqual(['candidates', 'candidates_upgrade', 'events',
                          'events_by_candidate', 'pipeline_marks', 'snapshots',
                          'user_idx_on_candidates', 'user_trg'], after_objects)
        self.assertEqual(1, user_rows, 'the user table named candidates_upgrade was reused '
                                       'as a scratch table and its row was lost')
        self.assertEqual(['d-legacy0000', 'd-legacy0001'], ids)
        self.assertEqual('ok', integrity)

    def test_the_migration_keeps_constraints_on_other_columns(self):
        """Review case: a hardcoded declaration silently widened a CHECK.

        The library had `CHECK(version > 0 AND version BETWEEN 1 AND 10)`. After the
        migration it accepted version 99, because the new declaration was generated
        instead of derived from the library's own text.
        """
        path = self.work / 'checked.sqlite3'
        db = sqlite3.connect(path)
        db.executescript(LEGACY_SCHEMA)
        db.execute('DROP TABLE candidates')
        db.execute('CREATE TABLE candidates (id TEXT PRIMARY KEY, '
                   'version INTEGER NOT NULL CHECK(version > 0 AND version BETWEEN 1 AND 10), '
                   'state_json TEXT NOT NULL)')
        db.execute('INSERT INTO candidates VALUES(?,1,?)',
                   ('d-checked', json.dumps(legacy_state('d-checked', 'x'))))
        db.commit()
        db.close()

        code, result = self.run_upgrade(path)
        self.assertEqual(0, code, result)
        db = sqlite3.connect(path)
        try:
            with self.assertRaises(sqlite3.IntegrityError,
                                   msg='the CHECK on version was lost or widened'):
                db.execute("UPDATE candidates SET version=99")
            db.rollback()
            declaration = db.execute("SELECT sql FROM sqlite_master WHERE name='candidates'"
                                     ).fetchone()[0]
        finally:
            db.close()
        self.assertIn('BETWEEN 1 AND 10', declaration,
                      'the column declaration was regenerated instead of carried over')

    def test_the_migration_keeps_row_identity(self):
        """Review case: rowid 77 came back as 1, changing what a rowid reference means."""
        path = self.work / 'rowids.sqlite3'
        db = sqlite3.connect(path)
        db.executescript(LEGACY_SCHEMA)
        db.execute('INSERT INTO candidates(rowid,id,version,state_json) VALUES(77,?,1,?)',
                   ('d-seventy-seven', json.dumps(legacy_state('d-seventy-seven', 'x'))))
        db.commit()
        db.close()

        code, result = self.run_upgrade(path)
        self.assertEqual(0, code, result)
        db = sqlite3.connect(path)
        try:
            rows = db.execute('SELECT rowid, id FROM candidates').fetchall()
        finally:
            db.close()
        self.assertEqual([(77, 'd-seventy-seven')], rows,
                         'row identity changed; a rowid reference in another table would '
                         'now point at a different row')

    def test_the_migration_refuses_a_shape_it_cannot_preserve(self):
        """An unknown declaration is refused, not regenerated."""
        path = self.work / 'odd.sqlite3'
        db = sqlite3.connect(path)
        db.executescript(LEGACY_SCHEMA)
        db.execute('DROP TABLE candidates')
        db.execute('CREATE TABLE candidates (id TEXT COLLATE NOCASE PRIMARY KEY, '
                   'version INTEGER NOT NULL, state_json TEXT NOT NULL)')
        db.execute('INSERT INTO candidates VALUES(?,1,?)',
                   ('d-odd', json.dumps(legacy_state('d-odd', 'x'))))
        db.commit()
        db.close()
        before = self.digest(path)
        code, result = self.run_upgrade(path)
        self.assertEqual(2, code, result)
        self.assertEqual('unsupported_shape', result['state'])
        self.assertEqual(before, self.digest(path), 'a refusal modified the library')

    def test_a_failed_verification_rolls_back_before_committing(self):
        """The requirement is explicit: if the check finds a difference, undo it.

        This is exercised by construction: the comparison runs inside the transaction
        here, so a mismatch raises before COMMIT and the library keeps its old shape.
        """
        import importlib.util
        spec = importlib.util.spec_from_file_location('upgrade', UPGRADE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        path = self.legacy_library(rows=2)
        before = self.digest(path)

        original = module.compare
        module.compare = lambda *args, **kwargs: ['injected difference']
        try:
            result = module.upgrade(path)
        finally:
            module.compare = original
        self.assertEqual('verification_failed', result['state'])
        self.assertEqual(before, self.digest(path),
                         'a failed verification left the library changed; it must be '
                         'rolled back so the previous shape survives')
        self.assertEqual(0, self.columns(path)['id'])

    def test_the_migration_refuses_a_library_that_already_has_null_keys(self):
        path = self.legacy_library(with_null_key=True)
        before = self.digest(path)
        code, result = self.run_upgrade(path)
        self.assertEqual(2, code, result)
        self.assertEqual('has_null_keys', result['state'])
        self.assertEqual(before, self.digest(path), 'a refusal modified the library')
        self.assertEqual(0, self.columns(path)['id'])

    def test_read_only_opening_an_old_library_still_reads_it(self):
        """`Store(readonly=True)` is how packets describe a library; it must keep working."""
        path = self.legacy_library(rows=2)
        store = Store(str(path), readonly=True)
        try:
            self.assertEqual(2, len(store.list_candidates()))
            shown = store.show('d-legacy0000')
            self.assertEqual('d-legacy0000', shown['resolved_id'])
            self.assertEqual('旧库的第 0 条', shown['candidate']['statement'])
        finally:
            store.close()
        # And it must still be exactly as it was: no repair happened behind the read.
        self.assertEqual(0, self.columns(path)['id'])

    def test_check_mode_writes_nothing(self):
        path = self.legacy_library()
        before = self.digest(path)
        code, result = self.run_upgrade(path, '--check')
        self.assertEqual(0, code)
        self.assertEqual('healthy_legacy', result['state'])
        self.assertEqual(3, result['rows'])
        self.assertEqual(before, self.digest(path))

    # --- what a user sees ----------------------------------------------------------

    def test_the_cli_reports_the_gap_instead_of_a_traceback(self):
        path = self.legacy_library()
        env = {k: os.environ[k] for k in ('PATH', 'LANG', 'TZ', 'TMPDIR') if k in os.environ}
        env['PYTHONPATH'] = str(ROOT)
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        env.pop('DOJO_ROOT', None)
        proc = subprocess.run([sys.executable, '-B', '-m', 'dojo', '--db', str(path), 'list'],
                              cwd=str(ROOT), capture_output=True, text=True, env=env, timeout=180)
        self.assertNotEqual(0, proc.returncode)
        self.assertIn('candidates.id', proc.stderr)
        self.assertIn('upgrade_key_constraint.py', proc.stderr)
        self.assertNotIn('Traceback', proc.stderr)

    def test_the_cli_reports_normally_after_the_migration(self):
        path = self.legacy_library()
        code, _ = self.run_upgrade(path)
        self.assertEqual(0, code)
        env = {k: os.environ[k] for k in ('PATH', 'LANG', 'TZ', 'TMPDIR') if k in os.environ}
        env['PYTHONPATH'] = str(ROOT)
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        env.pop('DOJO_ROOT', None)
        proc = subprocess.run([sys.executable, '-B', '-m', 'dojo', '--db', str(path), 'list'],
                              cwd=str(ROOT), capture_output=True, text=True, env=env, timeout=180)
        self.assertEqual(0, proc.returncode, proc.stderr[-1200:])
        self.assertEqual(3, len(json.loads(proc.stdout)))
        self.assertNotIn('旧', proc.stderr)


if __name__ == '__main__':
    unittest.main()
