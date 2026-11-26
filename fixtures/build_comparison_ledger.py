"""Materialize the synthetic comparison ledger from committed text; no model, no network.

`*.sqlite3` is ignored by this repository, so a checkout cannot carry the database
itself. This builder turns the authored scenario text into the library the guide and
`tests/test_comparison_lookup.py` read. Every row is copied verbatim from the spec --
including `at` -- so content, not file layout, is the thing that reproduces.

Two shapes, both offline:

    python3 -B fixtures/build_comparison_ledger.py /tmp/ledger.sqlite3
        事件 #5 有一份比较记录（checked）；#23 没有（open）。

    python3 -B fixtures/build_comparison_ledger.py /tmp/ledger.sqlite3 --revision
        在上面那份里追加 #5 -> #27 的一版后续提议；#5 会指向 #27。
"""
from pathlib import Path
import argparse
import json
import sqlite3

HERE = Path(__file__).resolve().parent
SPEC = HERE / 'comparison-ledger.json'
SUCCESSOR = HERE / 'comparison-ledger-successor.json'

SCHEMA = """
CREATE TABLE inquiry_events (seq INTEGER PRIMARY KEY, run TEXT, kind TEXT, payload TEXT, at TEXT);
CREATE TABLE inquiry_dependencies (
  conclusion INTEGER NOT NULL, premise INTEGER NOT NULL,
  relation TEXT NOT NULL DEFAULT 'context',
  PRIMARY KEY(conclusion,premise), CHECK(conclusion != premise));
CREATE INDEX inquiry_dependency_premises ON inquiry_dependencies(premise);
CREATE TABLE inquiry_revisions (
  old_event INTEGER PRIMARY KEY, new_event INTEGER NOT NULL, reason TEXT NOT NULL,
  CHECK(old_event != new_event));
CREATE TABLE inquiry_review_queue (
  event INTEGER NOT NULL, cause INTEGER NOT NULL,
  state TEXT NOT NULL DEFAULT 'pending',
  PRIMARY KEY(event,cause));
"""


def spec(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def merged(successor=False, base=None):
    """Fold the base spec, and optionally the revision spec, into one ledger."""
    parts = [spec(base or SPEC)]
    if successor:
        parts.append(spec(SUCCESSOR))
    events, dependencies, revisions, queue = [], [], [], []
    for part in parts:
        events.extend(part['events'])
        dependencies.extend(part['dependencies'])
        revisions.extend(part['revisions'])
        queue.extend(part['review_queue'])
    events.sort(key=lambda event: event['seq'])
    seqs = [event['seq'] for event in events]
    if len(set(seqs)) != len(seqs):
        raise ValueError('场景说明里的 seq 重复，拒绝拼出一份自相矛盾的账本')
    return {'events': events, 'dependencies': dependencies,
            'revisions': revisions, 'review_queue': queue}


def build(path, *, successor=False, base=None):
    """Write the ledger at `path`; refuse to clobber an existing file."""
    path = Path(path)
    if path.exists():
        raise FileExistsError(f'{path} 已存在；先删掉它，或换一个路径')
    data = merged(successor=successor, base=base)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    try:
        db.executescript(SCHEMA)
        with db:
            for event in data['events']:
                db.execute('INSERT INTO inquiry_events(seq,run,kind,payload,at) VALUES(?,?,?,?,?)',
                           (event['seq'], event['run'], event['kind'],
                            json.dumps(event['payload'], ensure_ascii=False, sort_keys=True),
                            event['at']))
            db.executemany('INSERT INTO inquiry_dependencies(conclusion,premise,relation) VALUES(?,?,?)',
                           data['dependencies'])
            db.executemany('INSERT INTO inquiry_revisions(old_event,new_event,reason) VALUES(?,?,?)',
                           data['revisions'])
            db.executemany('INSERT INTO inquiry_review_queue(event,cause,state) VALUES(?,?,?)',
                           data['review_queue'])
        db.commit()
    finally:
        db.close()
    return path


def rows(path):
    """Content fingerprint: every table's rows, decoded, so two builds can be compared."""
    db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    try:
        return {
            'events': [(seq, run, kind, json.loads(payload), at) for seq, run, kind, payload, at
                       in db.execute('SELECT seq,run,kind,payload,at FROM inquiry_events ORDER BY seq')],
            'dependencies': db.execute('SELECT conclusion,premise,relation FROM inquiry_dependencies ORDER BY 1,2').fetchall(),
            'revisions': db.execute('SELECT old_event,new_event,reason FROM inquiry_revisions ORDER BY 1').fetchall(),
            'review_queue': db.execute('SELECT event,cause,state FROM inquiry_review_queue ORDER BY 1,2').fetchall(),
        }
    finally:
        db.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('dest', help='要写出的 .sqlite3 路径（不能已存在）')
    parser.add_argument('--revision', action='store_true',
                        help='追加一版后续提议（#5 -> #27），用来走「已替代」那一态')
    parser.add_argument('--spec', default=None, help='基础场景说明；默认用同目录的 comparison-ledger.json')
    args = parser.parse_args(argv)
    target = build(args.dest, successor=args.revision, base=args.spec)
    print(f'{target}  events={len(rows(target)["events"])}  revision={args.revision}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
