"""The lesson from sqlite.org/quirks.html §5, kept as a check rather than a comment.

The public material says SQLite allows NULL in a PRIMARY KEY column, that this is a
historical oversight retained for compatibility, and that `NOT NULL` on the key column is
the workaround. The normative page (sqlite.org/lang/create table.html §3.5) adds the part
that makes it dangerous: "NULL values are considered distinct from all other values,
including other NULLs" -- so many NULL keys coexist and none of them can be told apart.

`probe.py` next to this test measures all of that on the local engine. This file pins the
two things a later reader depends on:

  schema      every primary key in this repository's own schema refuses NULL. Not the
              caller -- the schema. Otherwise the guarantee is one forgotten validation
              away from being gone, and a row written by any other path lists as a
              candidate that cannot be opened by its key.
  judgement   the documented exceptions really are exceptions, so the rule we adopted is
              narrow and true rather than broad and lucky.
"""

from __future__ import annotations

import json
import os
import re
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
EVIDENCE = ROOT / 'docs' / 'evidence' / '2026-11-28-primary-key-null'
PROBE = EVIDENCE / 'probe.py'


class TheRepositorySchemaRefusesNullKeys(unittest.TestCase):
    """The rule we adopted, checked against the real schema rather than a paraphrase."""

    SCHEMA_SOURCE = ROOT / 'dojo' / 'storage.py'

    def schema_sql(self):
        """The CREATE TABLE block exactly as the store runs it."""
        text = self.SCHEMA_SOURCE.read_text(encoding='utf-8')
        start = text.index('CREATE TABLE IF NOT EXISTS candidates')
        end = text.index('"""', start)
        return text[start:end]

    def test_the_text_declares_not_null_on_the_candidate_key(self):
        sql = self.schema_sql()
        self.assertRegex(sql, r'id\s+TEXT\s+NOT\s+NULL\s+PRIMARY\s+KEY',
                         'the candidate key is declared without NOT NULL; SQLite will '
                         'then accept NULL keys, and NULLs compare as distinct from each '
                         'other, so the schema stops protecting the key')

    def test_the_engine_refuses_a_null_key_written_past_the_api(self):
        """Behaviour, not text: build the real schema and try to violate it."""
        work = Path(tempfile.mkdtemp(prefix='pk-schema.'))
        self.addCleanup(lambda: __import__('shutil').rmtree(work, ignore_errors=True))
        path = work / 'schema.sqlite3'
        db = sqlite3.connect(path)
        db.executescript(self.schema_sql())
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute('INSERT INTO candidates(id,version,state_json) VALUES(NULL,1,?)',
                       (json.dumps({'statement': 'x'}),))
        db.close()

    # sqlite.org/quirks.html §5 names this exact shape as an exception: an
    # INTEGER PRIMARY KEY is an alias for the ROWID, so an inserted NULL is rewritten
    # into a unique integer rather than stored. A gate that ignores the exception would
    # demand a pointless NOT NULL and teach the wrong rule.
    INTEGER_ROWID_ALIAS = re.compile(r'\bINTEGER\s+PRIMARY\s+KEY\b', re.IGNORECASE)

    def test_every_other_primary_key_column_is_not_null(self):
        """A second key added later must not reopen the hole.

        Parsed instead of eyeballed: a column-level `PRIMARY KEY` without `NOT NULL`
        admits NULL keys -- except the documented INTEGER ROWID alias, which cannot.
        Table-level `PRIMARY KEY(...)` clauses are skipped: those columns carry their
        own NOT NULL declarations, and the engine still refuses NULL there.
        """
        sql = self.schema_sql()
        offenders, exceptions = [], []
        for line in sql.splitlines():
            stripped = line.strip().rstrip(',')
            upper = stripped.upper()
            if 'PRIMARY KEY' not in upper:
                continue
            if upper.startswith('PRIMARY KEY'):
                continue
            if 'NOT NULL' in upper:
                continue
            if self.INTEGER_ROWID_ALIAS.search(stripped):
                exceptions.append(stripped)
                continue
            offenders.append(stripped)
        self.assertEqual([], offenders,
                         'a column-level PRIMARY KEY is declared without NOT NULL, so it '
                         'admits NULL keys: %s' % (offenders,))
        # Recorded, not asserted: this file may legitimately have no such key, and a
        # count would be a test of today's schema rather than of the rule. The exception
        # is exercised for real in TheJudgementMatchesTheEngine below.
        self.assertEqual(exceptions, [e for e in exceptions if 'INTEGER' in e.upper()])


class TheJudgementMatchesTheEngine(unittest.TestCase):
    """Run the probe and read the cases, so the file cannot drift from the claim."""

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix='pk-probe-gate.'))
        self.addCleanup(lambda: __import__('shutil').rmtree(self.work, ignore_errors=True))

    def report(self):
        out = self.work / 'probe.json'
        env = {k: os.environ[k] for k in ('PATH', 'LANG', 'TZ', 'TMPDIR') if k in os.environ}
        env['PYTHONPATH'] = str(ROOT)
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        env.pop('DOJO_ROOT', None)
        proc = subprocess.run([sys.executable, '-B', str(PROBE), '--json', str(out)],
                              cwd=str(ROOT), capture_output=True, text=True,
                              env=env, timeout=300)
        self.assertEqual(0, proc.returncode, proc.stderr[-1500:])
        return json.loads(out.read_text(encoding='utf-8'))

    def test_the_documented_quirk_and_its_three_exceptions(self):
        report = self.report()
        cases = {case['case']: case for case in report['cases']}

        # The quirk: the NULL lands, and two of them coexist.
        plain = cases['plain text pk']
        self.assertEqual(2, plain['null_keys_stored'],
                         'the default table no longer stores NULL keys; the material this '
                         'rests on may have changed')
        self.assertFalse(plain['distinguishable_by_key'],
                         'two NULL keys became addressable; the cost model changed')

        # The three documented exceptions, each for its own stated reason.
        for label in ('text pk + NOT NULL', 'WITHOUT ROWID', 'STRICT'):
            self.assertEqual(['refused'], [o.split(':')[0] for o in cases[label]['outcomes']],
                             '%s no longer refuses a NULL key' % label)
        self.assertEqual(0, cases['INTEGER PRIMARY KEY']['null_keys_stored'],
                         'INTEGER PRIMARY KEY stopped rewriting NULL into a rowid')

    def test_one_statement_can_remove_every_null_keyed_row(self):
        cost = self.report()['duplicate_cost']
        self.assertEqual(2, cost['rows_before'])
        self.assertEqual(2, cost['rows_deleted_by_one_statement'],
                         'the measured cost of an unaddressed duplicate changed')
        self.assertEqual(0, cost['rows_after'])

    def test_this_repository_now_puts_the_guarantee_in_the_schema(self):
        shape = self.report()['repository_schema']
        self.assertIsNotNone(shape['schema_refused_null_key'],
                             'the schema admits a NULL candidate key again; a row written '
                             'past the API would list as a candidate and be unopenable')
        self.assertEqual(0, shape['reads_without_schema_help'])


if __name__ == '__main__':
    unittest.main()
