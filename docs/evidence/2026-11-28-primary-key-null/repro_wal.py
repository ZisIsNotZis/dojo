#!/usr/bin/env python3
"""Reproduce the hazard that got the first in-place upgrade rejected.

Sequence:
  1. a legacy library (weak key declaration), in WAL mode
  2. a connection stays OPEN and commits a row, so the committed bytes are in the
     -wal file, not yet checkpointed into the main file
  3. `upgrade.py` runs: it copies the main file as a "backup" and rewrites sqlite_master
  4. what the backup holds, and what `--restore` would put back

Run: python3 repro_wal.py
It prints the readings; it does not fail the build. The gate that matters is
tests/test_legacy_library_key.py.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
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
CREATE TABLE pipeline_marks (
    session TEXT NOT NULL,
    pass_name TEXT NOT NULL,
    candidate_id TEXT NOT NULL REFERENCES candidates(id),
    version INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(session, pass_name, candidate_id)
);
"""


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix='wal-repro.'))
    library = work / 'library.sqlite3'
    seed = sqlite3.connect(library)
    seed.executescript(LEGACY_SCHEMA)
    seed.commit()
    seed.close()

    # Keep a writer open, in WAL mode, with a committed row that is not checkpointed.
    writer = sqlite3.connect(str(library), isolation_level=None)
    print('journal_mode ->', writer.execute('PRAGMA journal_mode=WAL').fetchone()[0])
    writer.execute('INSERT INTO candidates VALUES(?,1,?)',
                   ('d-keepme', json.dumps({'id': 'd-keepme', 'statement': 'keep-me'})))
    print('committed d-keepme through the open connection')
    print('sidecar files present:', sorted(p.name for p in work.iterdir()
                                          if p.name.startswith('library.sqlite3')))
    print('main file size:', library.stat().st_size,
          ' wal size:', (work / 'library.sqlite3-wal').stat().st_size)

    before = subprocess.run(
        [sys.executable, '-B', str(HERE / 'upgrade.py'), str(library)],
        capture_output=True, text=True)
    print('upgrade rc=%d' % before.returncode)
    print(json.dumps(json.loads(before.stdout) if before.stdout.strip() else {}, indent=1)[:600])

    backup = library.with_suffix(library.suffix + '.pre-not-null.bak')
    side = sqlite3.connect(str(library), isolation_level=None)
    print('original still has keep-me:', side.execute(
        "SELECT count(*) FROM candidates WHERE id='d-keepme'").fetchone()[0])
    side.close()

    if backup.exists():
        # What `--restore` would put back. Copy it somewhere isolated first so reading
        # it cannot perturb the original.
        probe = work / 'what-restore-would-put-back.sqlite3'
        shutil.copy2(backup, probe)
        # A WAL-mode copy may also need its sidecars; report what is actually there.
        print('backup bytes readable:', end=' ')
        try:
            db = sqlite3.connect(str(probe))
            print(db.execute('SELECT count(*) FROM candidates').fetchone()[0], 'rows')
            db.close()
        except sqlite3.DatabaseError as error:
            print('unreadable: %s' % error)

    writer.close()
    print('workdir:', work)
    return 0


if __name__ == '__main__':
    sys.exit(main())
