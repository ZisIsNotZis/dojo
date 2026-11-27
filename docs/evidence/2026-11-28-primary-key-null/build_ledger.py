#!/usr/bin/env python3
"""Materialize this evidence into a real (non-synthetic) dojo inquiry library.

Why this exists: ../LOOP.md is prose. Prose about a knowledge chain is not a
knowledge chain -- you cannot ask it which version replaced which, or read the
comparison record that changed it. This builder turns the same authored text
(`ledger.json`) into the library `dojo stories` / `stories --context` /
`stories --comparison` / `knowledge` already know how to read, so the evidence can be
entered the way any other inquiry is.

Offline, no model, no network. Refuses to clobber an existing path (same rule as
fixtures/build_comparison_ledger.py): a fixed path that silently overwrites is how a
reader loses the library they were reading.

    python3 -B docs/evidence/2026-11-27-guide-standalone-loop/build_ledger.py <new-path.sqlite3>

Then:

    DB=<that path>
    python3 -m dojo --db "$DB" stories
    python3 -m dojo --db "$DB" stories <STORY> --context
    python3 -m dojo --db "$DB" stories <STORY> --comparison 3

`synthetic` is false for every row here, so none of these views needs `--synthetic`:
this is not role-play material, and the CLI must not present it as such. It is also
not user research -- `record_provenance` says on every run what it actually is.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

SPEC = Path(__file__).with_name('ledger.json')

SCHEMA = """
CREATE TABLE inquiry_events (
  seq INTEGER PRIMARY KEY, run TEXT NOT NULL, kind TEXT NOT NULL,
  payload TEXT NOT NULL, at TEXT NOT NULL);
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


def build(path: Path, *, spec: Path = SPEC) -> Path:
    if path.exists():
        raise SystemExit('%s 已存在；先删掉它，或换一个路径' % path)
    data = json.loads(spec.read_text(encoding='utf-8'))
    events = data['events']
    seqs = [event['seq'] for event in events]
    if len(set(seqs)) != len(seqs):
        raise SystemExit('ledger.json 的 seq 重复')

    # Dependencies come from the proposals' own premises, so the library cannot
    # claim a quote that no event holds. A premise pointing at a missing event is a
    # broken transcript, not a gap to paper over.
    by_seq = {event['seq']: event for event in events}
    dependencies, revisions = [], []
    for event in events:
        if event['kind'] != 'knowledge_proposal':
            continue
        proposal = event['payload']['proposal']
        for premise in proposal.get('premises', []):
            target = premise['event']
            if target not in by_seq:
                raise SystemExit('提案 #%d 引用了不存在的事件 #%d' % (event['seq'], target))
            body = json.dumps(by_seq[target]['payload'], ensure_ascii=False)
            if premise['quote'] not in body:
                raise SystemExit('提案 #%d 的引文在事件 #%d 里找不到：%r'
                                 % (event['seq'], target, premise['quote']))
            dependencies.append((event['seq'], target, 'premise'))
        if proposal.get('revises') is not None:
            if proposal['revises'] not in by_seq:
                raise SystemExit('提案 #%d 声称替代不存在的事件 #%d'
                                 % (event['seq'], proposal['revises']))
            revisions.append((proposal['revises'], event['seq'],
                              '同一说法在反例之后被收窄；旧版保留'))

    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    try:
        db.executescript(SCHEMA)
        with db:
            for event in events:
                db.execute('INSERT INTO inquiry_events(seq,run,kind,payload,at) VALUES(?,?,?,?,?)',
                           (event['seq'], event['run'], event['kind'],
                            json.dumps(event['payload'], ensure_ascii=False, sort_keys=True),
                            event['at']))
            db.executemany('INSERT INTO inquiry_dependencies(conclusion,premise,relation) '
                           'VALUES(?,?,?)', dependencies)
            db.executemany('INSERT INTO inquiry_revisions(old_event,new_event,reason) '
                           'VALUES(?,?,?)', revisions)
    finally:
        db.close()
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('dest', help='要写出的 .sqlite3 路径（不能已存在）')
    ap.add_argument('--spec', default=str(SPEC))
    args = ap.parse_args(argv)
    target = build(Path(args.dest), spec=Path(args.spec))
    print('%s  events=%d' % (target, len(json.loads(Path(args.spec).read_text(
        encoding='utf-8'))['events'])))
    return 0


if __name__ == '__main__':
    sys.exit(main())
