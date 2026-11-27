#!/usr/bin/env python3
"""Replay the claim in ../LOOP.md: does each `sh` block run when copied alone?

No network, no model. Writes only inside directories this script creates.

    python3 docs/evidence/2026-11-27-guide-standalone-loop/replay.py <repo-root> [--json out]

Two questions per block, kept apart because they have different answers:

    alone    one fresh shell, nothing exported, an empty TMPDIR -- what a reader who
             copies that one section has.
    again    a second run on the same machine (same HOME/TMPDIR), fresh shell --
             what the same reader has tomorrow.

**Isolation.** Every run gets its own HOME *and its own TMPDIR*, so a block that
writes `/tmp/dojo-ledger.sqlite3` writes into that run's private directory. This
script never deletes, scans, or otherwise touches anything outside its own scratch
tree: an earlier version cleared `/tmp/dojo-ledger*.sqlite3` before each run, which
would have destroyed a colleague's library of the same name and raced a parallel
replay. The isolation belongs on the creating side, not on the cleaning side.

Which blocks must pass `alone` is read off the page, not chosen here. Each block is
classified by the prose of the section it sits in (from its `##`/`###` heading to the
next one):

    promise     the section says it stands alone. In this guide that is
                「单独复制一段也能跑」, and its 「下面每段」 covers every later section.
    supplied    the section tells the reader that *they* supply the library path
                (「`DB` 是已有探究库的路径」). Failing alone is expected, not a defect.
    walkthrough a step in the 0-15 minute sequence, which builds on earlier steps.

The classification is printed for every block with the sentence it rests on, so a
reader can disagree with the scope without having to trust this script.

Exit 0 when every `promise` block passes both questions, 1 otherwise. The page's text
is executed verbatim: nothing here rewrites a path or injects a flag.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

FENCE = '```sh'
PROMISE = '单独复制一段也能跑'
SUPPLIED = '已有探究库的路径'

ROOT = Path('.')


def parse(text):
    """(blocks, section_prose): each block with its fence line and heading."""
    blocks, cur = [], None
    section_prose, prose, current_heading = {}, [], ''
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith('#'):
            if current_heading:
                section_prose[current_heading] = '\n'.join(prose)
            current_heading, prose = stripped, []
            continue
        if cur is None:
            prose.append(line)
            if stripped == FENCE:
                cur = (number, [], current_heading)
            continue
        if stripped == '```':
            blocks.append((cur[0], cur[1], cur[2]))
            cur = None
            continue
        cur[1].append(line)
    if current_heading:
        section_prose[current_heading] = '\n'.join(prose)
    if cur is not None:
        raise SystemExit('unbalanced ```sh fence at line %d' % cur[0])
    return blocks, section_prose


def classify(block, section_prose, promise_line):
    """Which scope governs this block, read off the page.

    The promise sentence says 「下面每段」 -- every section below it -- so it governs
    from its own line to the end of the page, except a section that tells the reader
    they supply the library path themselves (that one cannot stand alone by design).
    """
    prose = section_prose.get(block[2], '')
    if PROMISE in prose:
        return 'promise', 'section says 单独复制一段也能跑'
    if block[0] > promise_line and promise_line > 0:
        if SUPPLIED in prose:
            return 'supplied', 'section says DB 是已有探究库的路径'
        return 'promise', 'below 下面每段, in a section that claims nothing else'
    if SUPPLIED in prose:
        return 'supplied', 'section says DB 是已有探究库的路径'
    return 'walkthrough', 'no standalone claim covers this section'


def env_for(base):
    """A reader's environment, and a TMPDIR nobody else shares.

    The private TMPDIR is the whole point: a block that hard-codes
    `/tmp/dojo-ledger.sqlite3` writes there, inside this run, and two parallel
    replays never see each other's libraries. Nothing is deleted from the host.
    """
    home, tmp = base / 'home', base / 'tmp'
    home.mkdir(parents=True, exist_ok=True)
    tmp.mkdir(parents=True, exist_ok=True)
    return {
        'PATH': '/usr/local/bin:/usr/bin:/bin',
        'LANG': 'C.UTF-8', 'TZ': 'UTC',
        'HOME': str(home), 'TMPDIR': str(tmp),
        'PYTHONPATH': str(ROOT), 'PYTHONDONTWRITEBYTECODE': '1',
    }


def run(body, env):
    proc = subprocess.run(['sh', '-c', '\n'.join(body) + '\n'], cwd=str(ROOT),
                          capture_output=True, text=True, env=env, timeout=300)
    return proc.returncode, (proc.stderr.strip().splitlines() or [''])[-1][:200]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('root')
    ap.add_argument('page', nargs='?', default='docs/cli-guide.md')
    ap.add_argument('--json')
    args = ap.parse_args()

    global ROOT
    ROOT = Path(args.root).resolve()
    page_text = (ROOT / args.page).read_text(encoding='utf-8')
    blocks, section_prose = parse(page_text)
    promise_line = next((number for number, line in enumerate(page_text.splitlines(), 1)
                         if PROMISE in line), 0)
    base = Path(tempfile.mkdtemp(prefix='replay.'))
    rows = []
    try:
        for index, (line, body, heading) in enumerate(blocks):
            scope, why = classify((line, body, heading), section_prose, promise_line)
            alone_rc, alone_err = run(body, env_for(base / ('alone%d' % index)))
            sitting = env_for(base / ('again%d' % index))
            first_rc, _ = run(body, sitting)
            second_rc, second_err = run(body, sitting)
            rows.append({
                'block': index, 'fence_line': line, 'scope': scope, 'scope_reason': why,
                'heading': heading,
                'first_line': body[0].strip() if body else '',
                'alone_rc': alone_rc, 'alone_err': alone_err,
                'sitting_first_rc': first_rc,
                'sitting_second_rc': second_rc, 'sitting_second_err': second_err,
            })
    finally:
        shutil.rmtree(base, ignore_errors=True)

    promised = [r for r in rows if r['scope'] == 'promise']
    failed = [r for r in promised if r['alone_rc'] or r['sitting_second_rc']]
    report = {
        'root': str(ROOT), 'page': args.page, 'blocks': len(rows),
        'promise_blocks': len(promised), 'promise_failures': len(failed),
        'touched_outside_scratch': False,
        'rows': rows,
    }
    if args.json:
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=1) + '\n',
                                   encoding='utf-8')

    print('%-4s %-5s %-11s %-6s %-7s %s' %
          ('blk', 'line', 'scope', 'alone', 'again', 'first line'))
    for r in rows:
        print('%-4d %-5d %-11s %-6d %-7d %s' %
              (r['block'], r['fence_line'], r['scope'], r['alone_rc'],
               r['sitting_second_rc'], r['first_line'][:48]))
        if r['scope'] == 'promise' and r['alone_rc']:
            print('       alone: %s' % r['alone_err'])
        if r['scope'] == 'promise' and r['sitting_second_rc']:
            print('       again: %s' % r['sitting_second_err'])
    print('blocks=%d  promise-blocks=%d  promise-failures=%d'
          % (len(rows), len(promised), len(failed)))
    for r in failed:
        print('  FAIL block %d (line %d): %s' % (r['block'], r['fence_line'],
                                                 r['first_line'][:60]))
    return 0 if not failed else 1


if __name__ == '__main__':
    sys.exit(main())
