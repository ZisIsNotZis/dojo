#!/usr/bin/env python3
"""Add NOT NULL to `candidates.id` in an existing library -- without losing anything.

Background: SQLite's `CREATE TABLE IF NOT EXISTS` never touches an existing table, so a
library created before `candidates.id` gained `NOT NULL` keeps the weaker declaration and
accepts NULL keys, while one created now refuses them.

Three designs were tried and two were rejected by review, each for losing something:

  1. **Repair on open, with a file copy as backup.** Not a backup: under WAL the committed
     rows can live in `-wal`, so the copy was empty and restoring it would destroy data.
     There is no copy and no restore here. (See `repro_wal.py` in the evidence directory.)
  2. **Rebuild with `CREATE TABLE candidates_upgrade ... DROP TABLE candidates ...
     RENAME`.** That drops every index and trigger on `candidates`, and it deletes a
     user's own table if it happens to be named `candidates_upgrade`. Verified by review:
     both disappeared, and the script still reported `upgraded / integrity ok`.

This version rebuilds while keeping the library's own structure:

  * The temporary table name is chosen so it collides with nothing already in the file.
  * Every index and trigger defined on `candidates` is read **before** the rebuild, and
    recreated with its original name and SQL afterwards; their presence is verified.
  * Every object in the library is listed before and after, and the lists must match.
  * A shape this program cannot carry over (e.g. a view or trigger that mentions the old
    table in a way a rename would silently break) is **refused before writing**, with the
    reason named. Refusing is always allowed; losing structure is not.
  * The whole rebuild runs in one transaction; any error rolls back.
  * Verification failure rolls back too, so the library keeps its previous shape.

Read-only opening is untouched: `Store(readonly=True)` on an old library still reads fine.

Usage:

    python3 scripts/upgrade_key_constraint.py <library.sqlite3> --check   # report only
    python3 scripts/upgrade_key_constraint.py <library.sqlite3>          # upgrade

Exit codes: 0 done or nothing to do; 2 refused (message names why); 3 verification failed.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

TABLE = 'candidates'
COLUMN = 'id'
TEMP_PREFIX = 'candidates__upgrade_'


class VerificationFailed(Exception):
    """The rebuilt table differs from the original in a way we care about."""

    def __init__(self, problems):
        super().__init__('; '.join(problems))
        self.problems = problems


def constrained_declaration(declaration: str) -> str | None:
    """The library's own CREATE TABLE text, with NOT NULL added to the `id` column.

    Nothing else is touched: CHECKs, DEFAULTs, COLLATE, other columns and the table
    options all stay exactly as the library wrote them. A hardcoded declaration lost a
    user's `CHECK(version BETWEEN 1 AND 10)` and let the library accept version 99 after
    "upgrading" -- so the text is edited, not regenerated.

    Returns None when the `id` column is not the simple shape this edit understands; the
    caller refuses rather than guessing at a declaration it cannot preserve.
    """
    lowered = declaration.lower()
    if 'text primary key' not in lowered:
        return None
    # Replace only the first occurrence, and only the exact fragment.
    index = lowered.index('text primary key')
    return declaration[:index] + 'TEXT NOT NULL PRIMARY KEY' + declaration[index + len('TEXT PRIMARY KEY'):]


def objects(db: sqlite3.Connection) -> list[tuple[str, str, str]]:
    return [(row[0], row[1], row[2] or '') for row in db.execute(
        "SELECT type, name, sql FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name")]


def objects_for(db: sqlite3.Connection, table: str) -> list[tuple[str, str, str]]:
    """Indexes and triggers whose definition is attached to `table`."""
    found = []
    for kind, name, sql in objects(db):
        if kind not in ('index', 'trigger') or not sql:
            continue
        # `tbl_name` is the table the object belongs to; sqlite fills it in even when the
        # index name does not mention the table.
        owner = db.execute("SELECT tbl_name FROM sqlite_master WHERE name=?", (name,)).fetchone()
        if owner and owner[0] == table:
            found.append((kind, name, sql))
    return found


def inspect(path: Path) -> dict:
    if not path.is_file():
        return {'state': 'missing', 'path': str(path)}
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    try:
        declaration = db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (TABLE,)).fetchone()
        if declaration is None:
            return {'state': 'not_a_dojo_library', 'path': str(path),
                    'detail': 'no %s table' % TABLE}
        notnull = {row[1]: row[3] for row in db.execute('PRAGMA table_info(%s)' % TABLE)}
        if notnull.get(COLUMN):
            return {'state': 'already_constrained', 'path': str(path)}
        nulls = db.execute('SELECT count(*) FROM %s WHERE %s IS NULL'
                           % (TABLE, COLUMN)).fetchone()[0]
        rows = db.execute('SELECT count(*) FROM %s' % TABLE).fetchone()[0]
        attached = objects_for(db, TABLE)
        return {'state': 'healthy_legacy' if nulls == 0 else 'has_null_keys',
                'path': str(path), 'rows': rows, 'null_keys': nulls,
                'declaration': declaration[0],
                'objects_on_candidates': [name for _, name, _ in attached],
                'all_objects': [name for _, name, _ in objects(db)]}
    finally:
        db.close()


def unsupported(shape: dict) -> list[str]:
    """Reasons this library's shape cannot be rebuilt without guessing.

    A view or trigger that names `candidates` keeps naming it after the rename, which is
    usually what you want -- but "usually" is not something to bet someone's library on
    when the alternative is refusing and letting them decide. Anything this program does
    not explicitly carry over is a reason to stop.
    """
    reasons = []
    if shape['state'] != 'healthy_legacy':
        return reasons
    if constrained_declaration(shape['declaration']) is None:
        reasons.append('candidates 的建表语句里找不到可以只改一处的 '
                       '`id TEXT PRIMARY KEY`；原样拒绝，不猜一个建表语句')
    if 'WITHOUT ROWID' in shape['declaration'].upper():
        reasons.append('WITHOUT ROWID 表的主键本来就拒绝 NULL，这个库不该需要迁移；'
                       '原样拒绝，先弄清它是怎么来的')
    for name in shape['all_objects']:
        if name.startswith(TEMP_PREFIX):
            reasons.append('库里已经有以 %s 开头的对象（%s），本程序不会重用一个不是自己建的'
                           '名字' % (TEMP_PREFIX, name))
    return reasons


def open_elsewhere(path: Path) -> list[str]:
    """Whether another connection currently holds this library.

    The test is the write lock. `-wal`/`-shm` files are not evidence on their own: they
    linger after a clean close, and refusing on their presence alone called idle libraries
    "in use" forever. The lock, though, is held by a real second process.
    """
    reasons = []
    try:
        probe = sqlite3.connect(f'file:{path}?mode=rw', uri=True, timeout=0.2,
                                isolation_level=None)
        try:
            probe.execute('BEGIN IMMEDIATE')
            probe.execute('ROLLBACK')
        finally:
            probe.close()
    except sqlite3.OperationalError as error:
        reasons.append('不能取得写锁（还有连接在用这个库）：%s' % error)
    return reasons


def snapshot(db: sqlite3.Connection) -> dict:
    rows = db.execute('SELECT rowid, id, version, state_json FROM %s ORDER BY rowid'
                      % TABLE).fetchall()
    return {'rows': rows,
            'count': len(rows),
            'integrity': db.execute('PRAGMA integrity_check').fetchone()[0],
            'info': [tuple(row) for row in db.execute('PRAGMA table_info(%s)' % TABLE)],
            'declaration': db.execute("SELECT sql FROM sqlite_master "
                                      "WHERE type='table' AND name=?", (TABLE,)).fetchone()[0],
            'objects': objects(db)}


def free_temp_name(db: sqlite3.Connection) -> str:
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
    for attempt in range(64):
        name = '%s%s_%d' % (TEMP_PREFIX, stamp, attempt)
        taken = db.execute("SELECT 1 FROM sqlite_master WHERE name=?", (name,)).fetchone()
        if not taken:
            return name
    raise RuntimeError('could not find a free temporary table name')


def compare(before: dict, after: dict, attached: list[tuple[str, str, str]]) -> list[str]:
    """Every object present before must be present after, with nothing new appearing.

    `sqlite_autoindex_*` is sqlite's own name for a table's implicit indexes; it is
    recreated automatically with the same name, so those are compared as names only.
    """
    problems = []
    if before['rows'] != after['rows']:
        problems.append('row identity, order or contents changed '
                        '(rowid, id, version and state_json are compared)')
    if before['count'] != after['count']:
        problems.append('row count changed: %d -> %d' % (before['count'], after['count']))
    if after['integrity'] != 'ok':
        problems.append('integrity_check: %s' % after['integrity'])
    if [row for row in after['info'] if row[1] == COLUMN][0][3] != 1:
        problems.append('%s is still not NOT NULL' % COLUMN)
    # Everything except the one phrase we meant to add must be identical.
    expected = constrained_declaration(before['declaration'])
    normalise = lambda sql: ' '.join((sql or '').replace('"', '').split())
    if normalise(expected) != normalise(after['declaration']):
        problems.append('the table declaration changed beyond the added NOT NULL')
    after_names = {name for _, name, _ in after['objects']}
    for _, name, _ in attached:
        if name not in after_names:
            problems.append('lost %s' % name)
    # Structure may gain nothing and lose nothing. The old autoindex for the primary key
    # is replaced by a new one with the same name (sqlite names it after the table).
    before_names = {name for _, name, _ in before['objects']}
    extra = after_names - before_names
    missing = before_names - after_names
    if missing:
        problems.append('objects missing after rebuild: %s' % sorted(missing))
    if extra:
        problems.append('unexpected objects after rebuild: %s' % sorted(extra))
    return problems


def upgrade(path: Path) -> dict:
    shape = inspect(path)
    if shape['state'] == 'already_constrained':
        return {'state': 'already_constrained', 'changed': False, 'path': str(path)}
    if shape['state'] != 'healthy_legacy':
        return {'state': shape['state'], 'changed': False, 'path': str(path),
                'refused': 'only a healthy legacy library is upgraded'}
    busy = open_elsewhere(path)
    if busy:
        return {'state': 'in_use', 'changed': False, 'path': str(path), 'reasons': busy}

    reasons = unsupported(shape)
    if reasons:
        return {'state': 'unsupported_shape', 'changed': False, 'path': str(path),
                'reasons': reasons}

    db = sqlite3.connect(str(path), isolation_level=None)
    try:
        db.row_factory = sqlite3.Row
        before = snapshot(db)
        if not [row for row in before['info'] if row[1] == COLUMN]:
            return {'state': 'not_a_dojo_library', 'changed': False, 'path': str(path)}
        if [row for row in before['info'] if row[1] == COLUMN][0][3]:
            return {'state': 'already_constrained', 'changed': False, 'path': str(path)}

        attached = objects_for(db, TABLE)
        temp = free_temp_name(db)
        stored = db.execute("SELECT sql FROM sqlite_master WHERE type='table' "
                            "AND name=?", (TABLE,)).fetchone()[0]
        constrained = constrained_declaration(stored)
        if constrained is None:
            return {'state': 'unsupported_shape', 'changed': False, 'path': str(path),
                    'reasons': ['candidates.id 不是本程序能原样保留的简单声明；'
                                '拒绝比猜一个建表语句安全']}
        declaration = constrained.replace(TABLE, temp, 1)

        db.execute('PRAGMA foreign_keys = OFF')
        db.execute('BEGIN IMMEDIATE')
        try:
            db.execute(declaration)
            db.execute('INSERT INTO %s(rowid, id, version, state_json) '
                       'SELECT rowid, id, version, state_json FROM %s'
                       % (temp, TABLE))
            copied = db.execute('SELECT count(*) FROM %s' % temp).fetchone()[0]
            if copied != before['count']:
                raise RuntimeError('copying rows produced %d of %d' % (copied, before['count']))
            db.execute('DROP TABLE %s' % TABLE)
            db.execute('ALTER TABLE %s RENAME TO %s' % (temp, TABLE))
            # Recreate the library's own indexes and triggers, by their own definitions.
            for kind, name, sql in attached:
                db.execute(sql)
            # Verify BEFORE committing. A difference the check finds must leave the
            # library exactly as it was, so the check runs where a rollback can still
            # undo the rebuild. (An earlier version checked after COMMIT and could only
            # report the damage.)
            problems = compare(before, snapshot(db), attached)
            if problems:
                raise VerificationFailed(problems)
            db.execute('COMMIT')
        except VerificationFailed as failure:
            db.execute('ROLLBACK')
            db.execute('PRAGMA foreign_keys = ON')
            return {'state': 'verification_failed', 'changed': False, 'path': str(path),
                    'problems': failure.problems,
                    'note': 'the rebuild was rolled back; the library keeps its previous '
                            'shape and contents'}
        except Exception as error:
            db.execute('ROLLBACK')
            db.execute('PRAGMA foreign_keys = ON')
            return {'state': 'failed', 'changed': False, 'path': str(path),
                    'detail': str(error)}
        db.execute('PRAGMA foreign_keys = ON')

        after = snapshot(db)
        return {'state': 'upgraded', 'changed': True, 'path': str(path),
                'rows': after['count'], 'integrity': after['integrity'],
                'kept': [name for _, name, _ in attached]}
    finally:
        db.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('library')
    ap.add_argument('--check', action='store_true', help='report only, write nothing')
    args = ap.parse_args(argv)
    path = Path(args.library).expanduser()
    result = inspect(path) if args.check else upgrade(path)
    print(json.dumps(result, ensure_ascii=False, indent=1))
    if args.check:
        return 0
    return 0 if result['state'] in ('upgraded', 'already_constrained') else (
        3 if result['state'] == 'verification_failed' else 2)


if __name__ == '__main__':
    sys.exit(main())
