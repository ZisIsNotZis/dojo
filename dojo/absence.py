"""Why a read-only listing printed an empty array -- read from the file, not guessed.

r100 did this for `questions`: four situations printed the identical JSON and
nothing else. r102 measured the same defect on `stories` and `knowledge`, plus
a third that `questions` never had because it filters nothing:

    file    the path does not exist
    schema  a readable file that is not a dojo inquiry library
    table   a dojo library without a table this listing reads (knowledge:
            inquiry_dependencies / inquiry_revisions / inquiry_review_queue)
    rows    the table is there and holds nothing this listing can name
    view    rows exist and this --synthetic / --story scope excludes them all
    drop    rows exist and are in scope, but the listing discarded them anyway

The last one is not hypothetical. Swept over every `docs/evidence/**/inquiry
.sqlite3` at r102: 570 runs, 251 stories, 221 listed, 21 discarded with no line
on any screen -- a story whose first user turn is missing has `opening: None`
and `stories.listing` drops it silently. One measured example:
`docs/evidence/2026-11-13-goal-guidance/live/inquiry.sqlite3` holds five stories
and `stories --synthetic` prints four.

Every sentence here is measured against the file it names. None of them says a
readable file is broken; `not_sqlite` is the one case where sqlite itself
refuses to read, and that already exits non-zero with its own message.
"""
import sqlite3
from pathlib import Path


# r103: the tables `Knowledge.proposals` reads once a ledger holds proposals.
# `inquiry_events` carries the rows; the other three are queried per row by
# `DependencyIndex.status` (inquiry_dependencies, inquiry_revisions) and by
# `review_context` / `recent_review_requests` (inquiry_review_queue).
KNOWLEDGE_TABLES = ('inquiry_events', 'inquiry_dependencies',
                    'inquiry_revisions', 'inquiry_review_queue')


def open_layers(path, *, tables_of_interest=None):
    """Read what the file is, without creating it. Never raises for a bad file.

    Returns a dict with:
      'path'    the path as given
      'exists'  bool
      'readable'  True/False/None (None when there was nothing to open)
      'tables'  set of table and view names (empty when unreadable)
      'error'   the sqlite message when it refused to read, else None
    """
    path = Path(path)
    found = {'path': path, 'exists': path.exists(), 'readable': None,
             'tables': set(), 'error': None}
    if not found['exists']:
        return found
    try:
        db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    except sqlite3.Error as error:
        found['readable'] = False
        found['error'] = str(error)
        return found
    try:
        found['tables'] = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
        found['readable'] = True
    except sqlite3.DatabaseError as error:
        found['readable'] = False
        found['error'] = str(error)
        found['tables'] = set()
    finally:
        db.close()
    return found


def count_rows(path, sql, params=()):
    """Count with the given statement on a read-only connection; None if it fails."""
    try:
        db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    except sqlite3.Error:
        return None
    try:
        return db.execute(sql, params).fetchone()[0]
    except sqlite3.DatabaseError:
        return None
    finally:
        db.close()


def describe_tables(tables):
    """Name what the file does hold, so a reader can recognise it."""
    if not tables:
        return '里面没有任何表'
    names = sorted(tables)
    shown = ', '.join(names[:8])
    if len(names) > 8:
        shown += f' 等 {len(names)} 张'
    return f'只有 {shown}'


def stories_absence(path, *, story=None, synthetic=False):
    """(state, sentence) for an empty `stories` listing; None when it is not empty.

    Layers, checked in this order: absent / not_sqlite / schema / table / rows /
    view / drop. `drop` is the one this listing creates by itself: a story whose
    first user turn is gone has `opening: None`, and `stories.listing` discards
    it without a word. Measured across `docs/evidence` at r102: 251 stories in
    570 runs, 221 listed, 21 discarded exactly this way.
    """
    from .stories import run_index, describe

    path = Path(path)
    layers = open_layers(path)
    file_reason = file_layer(layers, 'stories', '故事')
    if file_reason is not None:
        state, why = file_reason
        if state == 'absent':
            return state, why
        # A file sqlite refuses to read already exits non-zero with its own
        # message; this layer never runs for it. Say so rather than pretend.
        return state, why
    tables = layers['tables']
    if 'inquiry_events' not in tables:
        return 'schema', (f'{path} 是一个能打开的 SQLite 文件，但它不是 dojo 的探究库：'
                          f'{describe_tables(tables)}，没有 inquiry_events。'
                          f'下面这份空的列表说的是「这不是那种库」，不是「这个库里没有故事」。')
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    try:
        try:
            index = run_index(db)
        except (sqlite3.Error, ValueError, KeyError, TypeError) as error:
            return 'unreadable_rows', (f'{path} 有 inquiry_events，但读不出运行索引（{error}）；'
                                       f'下面这份空的列表说的是「我读不下去」，不是「这个库里没有故事」。')
        total_starts = db.execute("SELECT count(*) FROM inquiry_events WHERE kind='start'").fetchone()[0]
        if not total_starts:
            users = db.execute("SELECT count(*) FROM inquiry_events WHERE kind='user'").fetchone()[0]
            return 'rows', (f'{path} 是 dojo 的探究库，但里面没有一条 start 记录（inquiry_events 共 '
                            f'{db.execute("SELECT count(*) FROM inquiry_events").fetchone()[0]} 行，user {users} 行）。'
                            f'下面这份空的列表说的是「这个库里还没开始过故事」。')
        if story is not None and not index:
            return 'view', f'{path} 有 {total_starts} 条 start，但 --story {story} 与这次的身份/合成设置对不上，全被排除。'
        visible = [r for r in index.values() if r['story'] == story] if story is not None else list(index.values())
        in_scope = [r for r in visible if synthetic or not r['synthetic']]
        if not in_scope:
            return 'view', (f'{path} 有 {total_starts} 条 start，但这一次的 --synthetic / --story 视图把它们全排除了：'
                            f'下面这份空的列表说的是「这次没让你看」，不是「库里没有」。')
        dropped = []
        for sid in sorted({r['story'] for r in in_scope}):
            try:
                item = describe(db, sid, synthetic=next(r['synthetic'] for r in in_scope if r['story'] == sid))
            except (sqlite3.Error, ValueError, KeyError, TypeError) as error:
                dropped.append(f'{sid}（读不出来：{error}）')
                continue
            if item['opening'] is None:
                dropped.append(f'{sid}（这个故事的第一次用户输入不在库里，所以没有开场白）')
        if dropped:
            return 'drop', (f'{path} 里这次视图能看到的 {len({r["story"] for r in in_scope})} 个故事中，'
                            f'有 {len(dropped)} 个被这份列表丢掉了：' + '；'.join(dropped) +
                            '。它们各有 start 记录，只是没有开场白，所以没进上面那份列表。')
    finally:
        db.close()
    return None


def knowledge_absence(path, *, synthetic=False):
    """(state, sentence) for an empty `knowledge` listing; None when it is not empty.

    Separate from `_knowledge_scope_note`, which speaks only about rows a
    *whole* ledger holds once the table is known to exist. That note has never
    had anything to say about a path that does not exist, a file with another
    schema, or a dojo library whose `inquiry_events` is there but holds no
    proposal rows (it returns None at `'inquiry_events' not in tables`, which
    leaves the caller printing `[]` in silence).
    """
    path = Path(path)
    layers = open_layers(path)
    file_reason = file_layer(layers, 'knowledge', '知识提议')
    if file_reason is not None:
        return file_reason
    tables = layers['tables']
    if 'inquiry_events' not in tables:
        return 'schema', (f'{path} 是一个能打开的 SQLite 文件，但它不是 dojo 的探究库：'
                          f'{describe_tables(tables)}，没有 inquiry_events。'
                          f'下面这份空的列表说的是「这不是那种库」，不是「这个库里没有知识提议」。')
    total = count_rows(path, "SELECT count(*) FROM inquiry_events WHERE kind='knowledge_proposal'")
    if total is None:
        return 'unreadable_rows', (f'{path} 有 inquiry_events，但数不出 knowledge_proposal 行；'
                                   f'下面这份空的列表说的是「我读不下去」，不是「这个库里没有知识提议」。')
    if not total:
        # Keeps r100's sentence verbatim: that test pinned the wording a reader
        # already saw, and moving the fact into a new layer is no reason to
        # change how it reads.
        # r100 pinned this sentence as path-free and digit-free: it must not
        # look like it is promising a count, and a temp directory name is full
        # of digits. The reader already knows which --db they typed.
        return 'rows', ('这个库里没有知识提议记录：下面这份空的列表说的是「这个库还没记过知识提议」，'
                        '不是「这次没让你看」。')
    # r103: the ledger holds proposals, so an empty list can now only mean the
    # read could not finish. `Knowledge.proposals` reads three tables beyond
    # `inquiry_events`: `dependencies.status()` queries inquiry_dependencies,
    # inquiry_revisions and inquiry_review_queue for every row. Measured on a
    # copy of a real library holding 27 proposals: dropping any one of the
    # three raises `OperationalError` from `proposals()`, while the CLI gate on
    # inquiry_dependencies alone printed `[]` and '加 --synthetic 可查看', and
    # --synthetic then printed `[]` again (dependencies) or exited 2 mid-listing
    # (the other two). No library under docs/evidence is in this shape -- 143
    # hold proposals, 0 lack one of the tables -- so this is the damaged or
    # older-ledger case, and it names the missing table instead of promising rows.
    missing = [name for name in KNOWLEDGE_TABLES if name not in tables]
    if missing:
        return 'table', (f'{path} 有 {total} 条知识提议记录，但缺 ' + '、'.join(missing) +
                         ' 这张表，列不出来：下面这份空的列表说的是「我读不下去」，'
                         '不是「这个库里没有知识提议」。加 --synthetic 也读不出来。')
    return None


def file_layer(layers, command, what):
    """One sentence for the file and schema layers, or None when they are fine.

    `command` is the subcommand a reader typed; `what` names the thing the
    empty array was supposed to hold, e.g. '故事' or '知识提议'.
    """
    path = layers['path']
    if not layers['exists']:
        return ('absent',
                f'{path} 这个路径上没有文件：下面这份空的{what}说的是「我看不到这个库」，'
                f'不是「这个库里没有{what}」。')
    if layers['readable'] is False:
        return ('not_sqlite',
                f'{path} 打不开成一个 SQLite 库（{layers["error"]}）：'
                f'下面这份空的{what}说的是「我读不了这个文件」，不是「这个库里没有{what}」。')
    return None
