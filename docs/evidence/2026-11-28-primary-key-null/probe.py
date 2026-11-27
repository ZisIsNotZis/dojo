#!/usr/bin/env python3
"""Does a NULL primary key actually cost you anything? Ask the engine, don't argue.

The material this checks is public and cited in ../LOOP.md:

  https://sqlite.org/quirks.html                 §5 "PRIMARY KEYs Can Sometimes Contain NULLs"
                                                 (written as history: an oversight kept for
                                                 compatibility, with three exceptions)
  https://sqlite.org/lang_createtable.html       §3.5, the normative statement, including
                                                 "NULL values are considered distinct from
                                                 all other values, including other NULLs"
  https://www.postgresql.org/docs/current/ddl-constraints.html  §5.5.4
                                                 "requires that the values be both unique and
                                                 not null"
  https://dev.mysql.com/doc/refman/8.0/en/create-table.html     "PRIMARY KEY ... all key
                                                 columns must be defined as NOT NULL"

What the reading gives you is a belief: "NULL primary keys are a SQLite quirk". What a
person building on it needs is a judgement: *when does it bite, when is it harmless, and
what do I write so it cannot happen to me?* This script answers that by running the
cases, and it prints the cost of each one rather than a verdict.

Offline. Uses an in-memory SQLite database and one temporary file; touches nothing else.

    python3 probe.py [--json out.json]

Exit code 0 always: this is an observation tool, not a test with an opinion. The gate that
reads its output is tests/test_primary_key_null.py.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

CLAIM = ('A NULL primary key is a documented SQLite quirk that is kept for compatibility '
         'and that nothing in practice depends on.')

CASES = [
    # (label, ddl, inserts, what this case is asking)
    ('plain text pk',
     'CREATE TABLE t(k TEXT PRIMARY KEY, v TEXT);',
     [("INSERT INTO t VALUES(NULL,'first')",), ("INSERT INTO t VALUES(NULL,'second')",)],
     'the documented default: does the NULL land, and can two of them coexist?'),
    ('text pk + NOT NULL',
     'CREATE TABLE t(k TEXT NOT NULL PRIMARY KEY, v TEXT);',
     [("INSERT INTO t VALUES(NULL,'first')",)],
     'the documented workaround: does it actually refuse?'),
    ('composite pk, plain',
     'CREATE TABLE t(a TEXT, b TEXT, v TEXT, PRIMARY KEY(a,b));',
     [("INSERT INTO t VALUES(NULL,'x','first')",), ("INSERT INTO t VALUES(NULL,'x','second')",)],
     'a multi-column key: is only one column needed to be NULL to duplicate?'),
    ('INTEGER PRIMARY KEY',
     'CREATE TABLE t(k INTEGER PRIMARY KEY, v TEXT);',
     [("INSERT INTO t VALUES(NULL,'first')",), ("INSERT INTO t VALUES(NULL,'second')",)],
     'the documented exception: NULL is rewritten, so what lands?'),
    ('WITHOUT ROWID',
     'CREATE TABLE t(k TEXT PRIMARY KEY, v TEXT) WITHOUT ROWID;',
     [("INSERT INTO t VALUES(NULL,'first')",)],
     'the second documented exception'),
    ('STRICT',
     'CREATE TABLE t(k TEXT PRIMARY KEY, v TEXT) STRICT;',
     [("INSERT INTO t VALUES(NULL,'first')",)],
     'the third documented exception'),
]


def run_case(label, ddl, inserts, question):
    db = sqlite3.connect(':memory:')
    db.executescript(ddl)
    outcomes = []
    for (statement,) in inserts:
        try:
            db.execute(statement)
            outcomes.append('accepted')
        except sqlite3.IntegrityError as error:
            outcomes.append('refused: %s' % error)
    rows = db.execute('SELECT * FROM t').fetchall()
    null_keys = db.execute('SELECT count(*) FROM t WHERE k IS NULL').fetchone()[0] \
        if 'k' in ddl else db.execute('SELECT count(*) FROM t WHERE a IS NULL').fetchone()[0]
    # A key you cannot address is a key you cannot use. `= NULL` is never true in SQL,
    # so the practical question is whether a lookup by key can single out one row.
    lookup = db.execute('SELECT count(*) FROM t WHERE k IS NULL').fetchone()[0] \
        if 'k' in ddl else db.execute('SELECT count(*) FROM t WHERE a IS NULL').fetchone()[0]
    db.close()
    return {
        'case': label, 'question': question, 'ddl': ddl,
        'outcomes': outcomes, 'rows': [list(row) for row in rows],
        'null_keys_stored': null_keys,
        'rows_matched_by_IS_NULL_lookup': lookup,
        'distinguishable_by_key': lookup <= 1,
    }


def cost_of_duplicates():
    """What one unaddressed duplicate actually costs, measured.

    The interesting harm is not "a NULL exists". It is: two rows that a person would call
    the same key, one statement that the engine treats as covering both.
    """
    db = sqlite3.connect(':memory:')
    db.executescript('CREATE TABLE t(k TEXT PRIMARY KEY, v TEXT);')
    db.execute("INSERT INTO t VALUES(NULL,'first')")
    db.execute("INSERT INTO t VALUES(NULL,'second')")
    before = db.execute('SELECT count(*) FROM t').fetchone()[0]
    per_row = db.execute("DELETE FROM t WHERE k IS NULL").rowcount
    after = db.execute('SELECT count(*) FROM t').fetchone()[0]
    db.close()
    return {'rows_before': before, 'rows_deleted_by_one_statement': per_row,
            'rows_after': after,
            'note': '`DELETE ... WHERE k IS NULL` is a single statement that removes every '
                    'row whose key is NULL; per-row addressing is impossible by that key.'}


def repo_shape():
    """The same question asked of this repository's own schema, not a toy table."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from dojo.storage import Store, DojoError

    work = tempfile.mkdtemp(prefix='pk-probe.')
    path = Path(work) / 'store.sqlite3'
    store = Store(str(path))
    store.add('第一条', 'abstract_idea')
    store.close()

    # Reach past the API on purpose: the question is whether the *schema* protects the
    # key or whether the guarantee lives only in the caller. Either answer is a valid
    # reading of the repository; what matters is which one it is, and that the schema
    # is what says so rather than the caller.
    db = sqlite3.connect(path)
    try:
        db.execute('INSERT INTO candidates(id,version,state_json) VALUES(NULL,1,?)',
                   (json.dumps({'id': None, 'statement': 'written straight through sqlite',
                                'kind': 'abstract_idea', 'version': 1, 'status': 'draft'}),))
        db.commit()
        schema_refused = None
    except sqlite3.IntegrityError as error:
        schema_refused = str(error)
    db.close()

    store = Store(str(path))
    listed = store.list_candidates()
    readable = {}
    for row in listed:
        try:
            store._get(row.get('id'))
            readable[repr(row.get('id'))] = 'ok'
        except DojoError as error:
            readable[repr(row.get('id'))] = 'refused: %s' % error
    store.close()
    return {
        'schema_refused_null_key': schema_refused,
        'listed_rows': len(listed),
        'listed_ids': [repr(row.get('id')) for row in listed],
        'read_back': readable,
        'reads_without_schema_help': sum(1 for value in readable.values() if value != 'ok'),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--json')
    args = ap.parse_args()

    report = {
        'engine': sqlite3.sqlite_version,
        'claim_under_test': CLAIM,
        'cases': [run_case(*case) for case in CASES],
        'duplicate_cost': cost_of_duplicates(),
        'repository_schema': repo_shape(),
    }
    if args.json:
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=1) + '\n',
                                   encoding='utf-8')

    print('engine %s' % report['engine'])
    for case in report['cases']:
        print('%-20s %-14s stored_null_keys=%d matched_by_IS_NULL=%d %s'
              % (case['case'], '/'.join(o.split(':')[0] for o in case['outcomes']),
                 case['null_keys_stored'], case['rows_matched_by_IS_NULL_lookup'],
                 'distinguishable' if case['distinguishable_by_key'] else 'NOT distinguishable'))
    cost = report['duplicate_cost']
    print('duplicate cost: %d rows -> one DELETE ... WHERE k IS NULL removes %d'
          % (cost['rows_before'], cost['rows_deleted_by_one_statement']))
    shape = report['repository_schema']
    if shape['schema_refused_null_key']:
        print('this repo: schema refuses a NULL key (%s), so the guarantee is in the '
              'schema, not in the caller' % shape['schema_refused_null_key'])
    else:
        print('this repo: schema ADMITS a NULL key; listed=%d unreadable=%d ids=%s'
              % (shape['listed_rows'], shape['reads_without_schema_help'],
                 ','.join(shape['listed_ids'])))
    return 0


if __name__ == '__main__':
    sys.exit(main())
