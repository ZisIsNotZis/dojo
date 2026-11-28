"""Local, evented SQLite storage for the dojo CLI."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import sys
import uuid
from contextlib import contextmanager
from difflib import SequenceMatcher
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from .commands import quote


KINDS = {"abstract_idea", "experience_claim", "application", "question", "counterexample"}
STATUSES = {"draft", "discussable", "challenged", "withdrawn", "superseded"}
# `derived_from` is the edge the *program* writes, and it says less than the others on
# purpose. When a session is handed a card and ends by writing a different version of it,
# the library knew that fact at that moment and threw it away: `discuss` wrote the new
# draft as an unrelated card, so a later search listed two nearly identical sentences with
# nothing saying one came out of the other (`.scratch/3490/walk.py`, scene C). The program
# does not know which way the wording changed -- `narrows` and `generalizes` are the
# reader's judgement -- so the edge says only "this version was written in a discussion
# that was holding that card".
#
# It is NOT a `link`: nothing here is the person's assertion that two cards are related.
# The supervisor measured what letting the two share a name cost on a hand-tended
# library -- two cards written and confirmed separately, joined by `link`, and the reader
# screen announced "后来有一场带着这条继续谈" about a discussion that never happened
# (`/var/tmp/dojo-lineage-provenance.3dtLjtD6`). So the type name is the *only*
# evidence a discussion put these two together, and `link` refuses it.
RELATIONS = {
    "supports", "challenges", "narrows", "generalizes", "conflicts",
    "instantiates", "duplicates",
}
# What a card wrote about itself: written by the program in the same transaction as the
# card, never by a person through `link`. Separate from `RELATIONS` so no surface can
# mistake one for the other -- see the comment above.
PROGRAM_RELATIONS = {"derived_from"}
SOURCE_TYPES = {
    "abstract_reasoning", "claimed_firsthand", "artifact_observation",
    "secondhand_report", "model_generated", "synthetic_roleplay", "unknown",
}
VERIFICATIONS = {"not_evidence", "unverified", "independently_checked", "disputed", "unknown"}
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


class DojoError(Exception):
    """An expected, user-correctable POC operation error."""


class DuplicateContent(DojoError):
    """The store already holds this claim; the existing card is named, none is written."""

    def __init__(self, message: str, candidate_id: str) -> None:
        super().__init__(message)
        self.candidate_id = candidate_id


class MergeRefused(DojoError):
    """A merge that would have quietly cost a recorded acceptance, and did not happen.

    A `DojoError`, so every existing caller keeps treating it as the refusal it is; the
    `details` ride along so a caller that needs to say *which card, which direction* does
    not have to parse the sentence back out of `str(exc)`.
    """

    def __init__(self, message: str, details: dict[str, Any]) -> None:
        super().__init__(message)
        self.details = details


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _command_path(path: Path) -> str:
    """A path as it can be pasted into the command an error message prints.

    #1921: a hint is only useful if following it works. A path with a space, pasted
    unquoted into `--db <path>`, arrives as two arguments and fails on a different
    error than the one it was meant to fix. The old body wrapped every such path in
    double quotes, which is not enough for `$`, a backtick or a quote in the name, and
    disagreed with every other command the program prints; the rules now live in
    `dojo/commands.py` (#3419).
    """
    return quote(str(path))


def _seed_command(path: Path) -> str:
    """`seed`, naming this library, for a refusal that tells the reader to create one."""
    return f"python3 -m dojo --db {_command_path(path)} seed"


def _agreed_at(value: str | None) -> str | None:
    """Normalize a caller's "when the agreement happened" to this ledger's timestamp shape.

    Returns None for "the caller did not say", so a missing moment stays missing instead
    of being filled with the write time -- that substitution is the defect the field
    exists to prevent. A value that is not an ISO instant is refused rather than stored:
    a reader comparing times would otherwise meet a string that only looks like one.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise DojoError("agreed_at must be an ISO 8601 timestamp")
    try:
        moment = datetime.fromisoformat(value)
    except ValueError as exc:
        raise DojoError(f"agreed_at must be an ISO 8601 timestamp: {value!r}") from exc
    if moment.tzinfo is None:
        # Stored times carry an offset; a naive string would compare as earlier than
        # everything on some platforms and later on others.
        raise DojoError("agreed_at must carry a timezone offset")
    # Seconds, matching `_now()`: the ledger's own timestamps are second-resolution, and
    # a field that keeps microseconds invites "agreed_at > created_at" by rounding error
    # alone when the two are the same moment.
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _id(value: str, label: str = "ID") -> str:
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise DojoError(f"{label} must use 1-80 letters, numbers, dot, underscore, or hyphen")
    return value


def _text(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DojoError(f"{label} cannot be empty")
    return value.strip()


def _strings(values: list[str] | None, label: str) -> list[str]:
    result = []
    for value in values or []:
        clean = _text(value, label)
        if clean not in result:
            result.append(clean)
    return result


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


# The keys `retrieve(for_reading=True)` adds to a *result row*, which the model-facing
# call does not have and the published stdout must not carry. Named once, here, because
# the list drifted the moment it was written out twice: `matched_in` was added to the
# reading payload and `cli.py` kept stripping only the two keys it already knew, so
# every row on stdout grew a key. The supervisor caught that by piping the output into
# a program and diffing the rows -- a check on the four top-level keys cannot see it,
# which is why the readings now compare whole row key sets on a library holding both a
# sentence-match and a limits-match.
# `derived_later` is the same kind of key: the cards the ledger says were written out of
# a discussion holding this one (see `Store.later_versions`). The model gets the edge on
# the new card (it is inside `relations`, which every row already carried) but not this
# reverse list, because it is the person's way back to what came after.
# `derived_later` and `derivation` are the same kind of key: which card the ledger says
# this one was written out of, and which cards it says were written out of this one (see
# `Store.derivation` / `Store.later_versions`). The model gets the edge on the newer card
# (it is inside `relations`, which every row already carried) but not either basis, because
# the two facts it adds are how to *read* the edge, and that wording belongs to the
# screen -- `handoff_for_model` says the same thing in the session where it matters.
READING_ROW_KEYS = (
    "matched_on", "matched_wording", "matched_in", "answers", "derived_later",
    "derived_later_total", "derivation",
)
# How many later versions one entry itemises. Each one costs a `time_basis` read (its own
# wording's date and acceptance), and a library that really holds many edges would otherwise
# pay that for every edge on every row: measured at 0/200/600 edges on 600 cards, one search
# went 56 -> 96 -> 149 ms with the count of statements growing by ~12 per edge
# (`.scratch/3490/edge_scaling.py`). Five is what a reader can take in beside one sentence;
# the rest is **counted**, never silently dropped, the same rule `SCREEN_SOURCE_LINES` uses.
SCREEN_LATER = 5
# The four parts `discuss` asks, by the field key the card stores. Declared beside the
# reading keys because three layers have to agree on the vocabulary: `discuss` writes the
# answers, `storage` orders and searches them, and `finding`/`discuss` print them. The
# Chinese name is what the trace calls a part; the key is what the card stores.
PART_KEYS_BY_FIELD = {
    "situation": "情境",
    "tension": "张力",
    "price": "代价",
    "off": "失效",
}
# The same mapping the other way, for a caller holding the name `discuss` uses.
PART_FIELD_BY_NAME = {name: key for key, name in PART_KEYS_BY_FIELD.items()}


class Store:
    """Single-database storage boundary; all mutations are SQLite transactions."""

    def __init__(self, path: str | Path, *, readonly: bool = False):
        """Open the library. `readonly=True` describes an existing one instead of making it.

        #1893: `freeze-materials` used to describe a library it had just invented in
        a temporary directory, which is how a packet-time came to be printed as an
        entry time. It now describes a library that already exists, and describing a
        library must not be able to change it -- not by creating it when the path is
        wrong, not by running DDL, and not by opening it for writing at all. A missing
        file is an error here; a writer would have silently created an empty library
        and then complained about the seeds, which points at the wrong thing.
        """
        self.path = Path(path).expanduser()
        self.readonly = readonly
        if readonly:
            if not self.path.exists():
                # #1904: the old message was just the path, which tells a person the file
                # is absent and nothing about the step they skipped. Creating a library is
                # a command; name it.
                raise DojoError(
                    f"database does not exist: {self.path}\n"
                    "这个库还不存在。先创建并写入四条模拟 seed（只写这个路径，不会碰其他库）：\n"
                    "  " + _seed_command(self.path)
                )
            # #1921: `--db <a directory>` reached sqlite, which answered
            # `unable to open database file` -- no path in it, and no way to tell which
            # of the reader's paths that was. A directory is never a library, so it is
            # refused here by name, before sqlite is asked to open it.
            if self.path.is_dir():
                raise DojoError(
                    f"这个路径是个目录，不是 dojo 库文件: {self.path}\n"
                    "--db 要的是库文件本身（例如 <目录>/dojo.sqlite3），不是它所在的目录。"
                )
            uri = self.path.resolve().as_uri() + "?mode=ro"
            try:
                self.connection = sqlite3.connect(uri, uri=True, timeout=10, isolation_level=None)
                self.connection.row_factory = sqlite3.Row
                self.connection.execute("PRAGMA foreign_keys = ON")
            except sqlite3.DatabaseError as exc:
                # #1921: `file is not a database` names neither the path nor the state.
                # Retrying `seed` on such a file fails identically, so the honest instruction
                # is to repoint `--db`, not to run a command that would find the same bytes.
                # `connect` may have succeeded before the pragma failed, and the caller's
                # `finally` cannot close a store it never received. It may also have failed
                # first, in which case there is no connection to close.
                if getattr(self, "connection", None) is not None:
                    self.connection.close()
                raise DojoError(
                    f"这个文件不是 sqlite 数据库，读不出事件账本: {self.path}\n"
                    f"（sqlite 的原文：{exc}）\n"
                    "换一个已有的 dojo 库文件，或换一个还不存在的路径重新建库；"
                    "不要用这个路径，对它跑 seed 会得到同样的错。"
                ) from exc
            # An existing file that is not a dojo library, or an empty one, otherwise
            # fails later as `no such table: candidates` -- the same dead end one step
            # further in. #1904: refused here, with the command that makes it one.
            # sqlite reads the file header lazily, so a file that is not a database
            # first fails here rather than at connect(); the same refusal is used for both.
            try:
                has_candidates = self.connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='candidates'"
                ).fetchone() is not None
            except sqlite3.DatabaseError as exc:
                self.connection.close()
                raise DojoError(
                    f"这个文件不是 sqlite 数据库，读不出事件账本: {self.path}\n"
                    f"（sqlite 的原文：{exc}）\n"
                    "换一个已有的 dojo 库文件，或换一个还不存在的路径重新建库；"
                    "不要用这个路径，对它跑 seed 会得到同样的错。"
                ) from exc
            if not has_candidates:
                # #1921: this used to be one branch -- "no candidates table, so run seed
                # on it" -- and `seed` writes candidates/events/pipeline_marks/snapshots
                # into whatever file it is pointed at. Measured on a healthy SQLite file
                # from another application: following that hint took it from 8192 to
                # 61440 bytes and added four tables to somebody else's database. So the
                # question is not "does it have a candidates table" but "may this file be
                # written to at all", and the answer is no exactly when the file already
                # holds tables that are not ours.
                others = [row["name"] for row in self.connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite\\_%' ESCAPE '\\' ORDER BY name"
                )]
                self.connection.close()
                command = _seed_command(self.path)
                if not others:
                    # No tables at all: this file is a new (or emptied) library, and
                    # seeding it is the step that makes it one. The names it will create
                    # are stated, because "seed" alone does not say it writes.
                    raise DojoError(
                        f"这个库还是空的（没有任何表）: {self.path}\n"
                        "先建表并写入四条模拟 seed（会在**这个文件**里新建 candidates / events / "
                        "pipeline_marks / snapshots 四张表）：\n"
                        f"  {command}"
                    )
                # A working database that belongs to something else. Seeding it would
                # add this project's tables to another application's file; the only
                # honest next step is to point `--db` somewhere else.
                raise DojoError(
                    f"这个文件是别的应用的 SQLite 库，不是 dojo 库: {self.path}\n"
                    f"它已经有这些表：{', '.join(others)}\n"
                    "对它跑 seed 会在这个文件里**加上** candidates / events / pipeline_marks / "
                    "snapshots 四张表，改动别人的库。所以这里不给 seed 命令。二选一：\n"
                    "  1) 换成一个现成的 dojo 库（里面有 candidates 表）；\n"
                    "  2) 换一个全新的路径（不要选别人的目录）作为新库，再对那个新路径跑 seed。\n"
                    "这里不给可执行的命令：能跑的命令要么写别人的库，要么必须由你决定写到哪。"
                )
            # #1929: a dojo-shaped library whose ledger has no time column at all -- an
            # import that dropped it, a schema from before this field existed. Every
            # time read is `events.created_at`, so the first one raises
            # `no such column: created_at` from somewhere deep in a query, which names
            # neither the library nor the fact the reader needs: **this library never
            # stored times**, so no packet from it can date anything. Refused here, by
            # name, before a packet is half written.
            columns = {row["name"] for row in self.connection.execute("PRAGMA table_info(events)")}
            if "created_at" not in columns:
                self.connection.close()
                raise DojoError(
                    f"这个库没有时刻记录（events 表没有 created_at 列）: {self.path}\n"
                    "所以包里每条来源都拿不到入库时刻。这不是本程序漏印，是这个库从来没存过；"
                    "补不了——没有可回填的原始时刻。二选一：\n"
                    "  1) 把记录重新导入一个带时刻的库（导入工具必须写 events.created_at）；\n"
                    "  2) 只把它当素材，不冻结成带时刻的包。"
                )
            # A read-only open must describe the library, not gate it: reading an old
            # library is exactly how someone finds out what is in it. The gap is a
            # statement about writes, so it is reported on the write path only.
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = DELETE")
        self.connection.execute("PRAGMA synchronous = FULL")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS candidates (
                -- NOT NULL is not redundant here. In SQLite a PRIMARY KEY on a column is
                -- only a UNIQUE constraint, and NULLs are distinct from each other for
                -- uniqueness, so without this the schema admits many rows whose key is
                -- NULL (sqlite.org/quirks.html §5). `Store.add` rejects such ids, but
                -- then the guarantee lives in the caller, and a row written by any other
                -- path lists as a candidate and cannot be opened by its key.
                id TEXT NOT NULL PRIMARY KEY,
                version INTEGER NOT NULL CHECK(version > 0),
                state_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS snapshots (
                candidate_id TEXT NOT NULL REFERENCES candidates(id),
                version INTEGER NOT NULL,
                state_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(candidate_id, version)
            );
            CREATE TABLE IF NOT EXISTS events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_id TEXT REFERENCES candidates(id),
                event TEXT NOT NULL,
                details_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS events_by_candidate ON events(candidate_id, seq);
            CREATE TABLE IF NOT EXISTS pipeline_marks (
                session TEXT NOT NULL,
                pass_name TEXT NOT NULL,
                candidate_id TEXT NOT NULL REFERENCES candidates(id),
                version INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(session, pass_name, candidate_id)
            );
            """
        )
        self._check_candidate_key_is_not_null()

    def _check_candidate_key_is_not_null(self) -> None:
        """Report a library that predates the NOT NULL on `candidates.id`. Never repairs it.

        `CREATE TABLE IF NOT EXISTS` does not touch a table that already exists, so a
        library created by an earlier release keeps the weaker declaration: it accepts
        NULL keys while a library created now refuses them. Nothing visible says so.

        Opening a library must not change it -- the same rule as #1893 above, which is why
        the read-only path checks this too. An earlier attempt rewrote `sqlite_master`
        here, on open, and kept a copy of the main file as a backup. That was wrong in a
        way worth recording: with another connection open in WAL mode the committed rows
        are in `-wal`, so the copy was empty, and restoring it would have destroyed data.
        Constraining an old library is a real migration; it is a command a person runs
        (`scripts/upgrade_key_constraint.py`), on a library nobody has open, and it is
        verified by sqlite before it keeps anything.
        """
        if not self._candidate_key_has_not_null():
            raise DojoError(self._legacy_key_message())

    def _candidate_key_has_not_null(self) -> bool:
        columns = {row["name"]: row for row in
                   self.connection.execute("PRAGMA table_info(candidates)")}
        key = columns.get("id")
        return key is None or bool(key["notnull"])

    def _legacy_key_message(self) -> str:
        """One sentence per situation, ending in the command that changes it."""
        try:
            broken = self.connection.execute(
                "SELECT count(*) FROM candidates WHERE id IS NULL").fetchone()[0]
        except sqlite3.DatabaseError:
            broken = 0
        head = (f"这个库的 candidates.id 没有 NOT NULL：{self.path}\n"
                "它是旧版本建的库：SQLite 里主键只是 UNIQUE，而 NULL 彼此算不同，"
                "所以这种库能存下多个 NULL 主键，按主键查或删时无法分辨。\n")
        if broken:
            body = (f"这个库里已经有 {broken} 行主键是 NULL。一条 "
                    "`DELETE ... WHERE id IS NULL` 会把它们一起删掉。\n"
                    "哪几行该留、该补什么 id 只有你知道，所以这里不动它。\n"
                    f"  python3 scripts/upgrade_key_constraint.py {self.path} --check\n"
                    "会列出这些行；补好 id 之后再跑一次不带 --check 的同一命令。")
        else:
            body = ("库里没有 NULL 主键行，历史是健康的；这条约束只是没写进表里。\n"
                    "  关闭所有正在使用这个库的程序，然后运行：\n"
                    f"  python3 scripts/upgrade_key_constraint.py {self.path}\n"
                    "它会在一个事务里重建这张表并逐项核对；核对不过就整体回滚，不动数据。")
        return head + body

    def close(self) -> None:
        self.connection.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        # A compound write can hold the writer lock across Store operations.
        # Nested scopes must neither commit nor roll back their caller's transaction.
        nested = self.connection.in_transaction
        self.connection.execute("SAVEPOINT store_operation" if nested else "BEGIN IMMEDIATE")
        try:
            yield
            if nested:
                self.connection.execute("RELEASE store_operation")
            else:
                self.connection.commit()
        except BaseException:
            if nested:
                self.connection.execute("ROLLBACK TO store_operation")
                self.connection.execute("RELEASE store_operation")
            else:
                self.connection.rollback()
            raise

    def _event(self, candidate_id: str | None, event: str, details: dict[str, Any]) -> int:
        cursor = self.connection.execute(
            "INSERT INTO events(candidate_id,event,details_json,created_at) VALUES(?,?,?,?)",
            (candidate_id, event, _json(details), _now()),
        )
        return int(cursor.lastrowid)

    def _insert_candidate(self, state: dict[str, Any], event: str, details: dict[str, Any]) -> None:
        candidate_id = state["id"]
        payload = _json(state)
        now = _now()
        self.connection.execute(
            "INSERT INTO candidates(id,version,state_json) VALUES(?,?,?)",
            (candidate_id, state["version"], payload),
        )
        self.connection.execute(
            "INSERT INTO snapshots(candidate_id,version,state_json,created_at) VALUES(?,?,?,?)",
            (candidate_id, state["version"], payload, now),
        )
        self._event(candidate_id, event, details)

    def _get(self, candidate_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT state_json FROM candidates WHERE id=?", (candidate_id,)
        ).fetchone()
        if row is None:
            raise DojoError(f"candidate not found: {candidate_id}")
        return json.loads(row["state_json"])

    def _write(
        self, state: dict[str, Any], event: str, details: dict[str, Any],
        request: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist a new version unless this request would change nothing.

        Two questions that look like one, kept apart here because merging them lost
        a reason:

        *Did the stored card change?* Version numbers are what the pipeline's
        "processed to version N" marks compare against, so inflating one over an
        unchanged card turns finished work back into pending work. Only a change in
        the stored state moves the version.

        *Is this the same request again?* Two different requests can leave the card
        in the same state. `revise` a card to the same sentence for a second, new
        reason is the case that made this necessary: the wording is already there,
        so nothing moves, but the reason is a fact the reader needs. Recording it as
        `<event>.repeat` of the first one would file a new argument under an old
        one. A repeat is the same request (same event, same ask) arriving twice, not
        merely the same resulting state.

        The ask is passed in whole as `request` and stored under that one key, so the
        comparison cannot fall behind the writer: this used to subtract a hand-written
        list of "bookkeeping" keys from whatever `details` happened to contain, and
        that list was wrong twice -- once when `revise` recorded the wording it left
        but not the one it asked for, once when it recorded which fields it changed
        but not the values it asked for. Each time the fix was to add one more key to
        the subtraction or one more field to `details`; the subtraction itself was the
        bug. Two requests are the same when their recorded asks are equal, and an ask
        is equal only if it names every input the caller supplied.

        Either way the version stays put and the ledger keeps a row: RFC 9110
        section 9.2.2 permits logging each request, and refuses to leave a replay
        and a real second action indistinguishable.
        """
        candidate_id = state["id"]
        current = self._get(candidate_id)
        state = dict(state)
        if request is not None:
            # Stored with the row, not only compared here: a later reader asking "was
            # this a replay of that?" needs the ask that was actually made, and a row
            # without one cannot answer.
            details = {**details, "request": request}
        unchanged = {key: value for key, value in state.items() if key != "version"} == {
            key: value for key, value in current.items() if key != "version"}
        if unchanged:
            repeat_of, uncompared = self._same_request(candidate_id, event, request)
            if repeat_of is not None:
                self._event(candidate_id, event + REPEAT_EVENT_SUFFIX, {
                    **details, "version": current["version"],
                    "repeat_of": repeat_of,
                    "effect": "unchanged",
                })
                return current
            # A different request with the same effect: the card does not move, but
            # this is not a replay, so it is written under its own name with the
            # version it left in place. When an earlier row of this event cannot be
            # compared (it predates `request`), the row says so rather than implying
            # the question was settled: "no earlier match" and "no earlier row to
            # compare with" are different facts, and only the first one is an answer.
            note = {} if not uncompared else {
                "earlier_rows_without_a_recorded_request": uncompared}
            self._event(candidate_id, event, {
                **details, "version": current["version"], "effect": "unchanged", **note,
            })
            return current
        state["version"] = current["version"] + 1
        payload = _json(state)
        now = _now()
        self.connection.execute(
            "UPDATE candidates SET version=?,state_json=? WHERE id=?",
            (state["version"], payload, candidate_id),
        )
        self.connection.execute(
            "INSERT INTO snapshots(candidate_id,version,state_json,created_at) VALUES(?,?,?,?)",
            (candidate_id, state["version"], payload, now),
        )
        self._event(candidate_id, event, {**details, "version": state["version"]})
        return state

    def _same_request(
        self, candidate_id: str, event: str, request: dict[str, Any] | None,
    ) -> tuple[int | None, int]:
        """(the seq of an earlier row recording this same ask, count of rows that
        cannot be asked).

        Compared on the ask itself -- every input the caller supplied, stored whole
        under `request` -- and not on the state it produced, which two different asks
        can share. Nothing is subtracted here, because the ledger no longer has to
        guess which of a writer's fields were intent: the writer says.

        Rows written before asks were stored have no `request`. They are counted, not
        skipped silently: their existence means "no match" is not the same answer as
        "nothing comparable", and a caller that cannot tell the two would be free to
        present a guess as a verdict. See the caller for what it does with the count.
        """
        if not request:
            return None, 0
        rows = self.connection.execute(
            "SELECT seq,details_json FROM events WHERE candidate_id=? AND event=? ORDER BY seq DESC",
            (candidate_id, event),
        ).fetchall()
        uncompared = 0
        for row in rows:
            earlier = json.loads(row["details_json"])
            if "request" not in earlier:
                uncompared += 1
                continue
            if earlier["request"] == request:
                return int(row["seq"]), uncompared
        return None, uncompared
    def _source(self, source: dict[str, Any]) -> dict[str, str]:
        if not isinstance(source, dict):
            raise DojoError("each source must be a JSON object")
        source_id = _id(source.get("id") or _new_id("src"), "source ID")
        source_type = source.get("type", "unknown")
        verification = source.get("verification", "unknown")
        if source_type not in SOURCE_TYPES:
            raise DojoError(f"unknown source type: {source_type}")
        if verification not in VERIFICATIONS:
            raise DojoError(f"unknown source verification: {verification}")
        return {
            "id": source_id,
            "type": source_type,
            "claim": _text(source.get("claim", "source details not supplied"), "source claim"),
            "independence_group": _text(source.get("independence_group", "unknown"), "independence group"),
            "verification": verification,
            "scope_note": str(source.get("scope_note", "")).strip(),
        }

    def _source_ids_available(self, sources: list[dict[str, str]]) -> None:
        seen: dict[str, dict[str, str]] = {}
        for source in sources:
            if source["id"] in seen and seen[source["id"]] != source:
                raise DojoError(f"conflicting source ID in operation: {source['id']}")
            seen[source["id"]] = source
        for source_id, source in seen.items():
            rows = self.connection.execute("SELECT state_json FROM candidates").fetchall()
            for row in rows:
                state = json.loads(row["state_json"])
                existing = next((item for item in state.get("sources", []) if item["id"] == source_id), None)
                if existing is not None and existing != source:
                    raise DojoError(f"source ID already belongs to different provenance: {source_id}")
                if existing is not None:
                    raise DojoError(f"source ID already exists: {source_id}")

    def add(
        self,
        statement: str,
        kind: str,
        *,
        candidate_id: str | None = None,
        premises: list[str] | None = None,
        scope: list[str] | None = None,
        alternatives: list[str] | None = None,
        contradictions: list[str] | None = None,
        unknowns: list[str] | None = None,
        sources: list[dict[str, Any]] | None = None,
        session: str | None = None,
        derived_from: str | None = None,
    ) -> dict[str, Any]:
        """Write a new card, optionally recording which card it came out of.

        `derived_from` exists because one fact was known and dropped: a discussion opened
        with `--card X` that ends on a different wording wrote that wording as an
        unrelated card, so `search` later listed both with nothing joining them. The edge
        is written into the new card's own `relations` in the same transaction and the
        same version as the card, so there is no moment where one exists without the
        other. It adds no source, moves no status and changes no wording digest.

        Deliberately not a direction: see `RELATIONS`. The target must exist, and a card
        cannot come out of itself.
        """
        statement = _text(statement, "statement")
        if kind not in KINDS:
            raise DojoError(f"kind must be one of: {', '.join(sorted(KINDS))}")
        candidate_id = _id(candidate_id or _new_id("d"))
        source_values = [self._source(source) for source in sources or []]
        fields = {
            "premises": _strings(premises, "premise"),
            "scope": _strings(scope, "scope"),
            "alternatives": _strings(alternatives, "alternative"),
            "contradictions": _strings(contradictions, "contradiction"),
            "unknowns": _strings(unknowns, "unknown"),
        }
        wanted = content_key(statement, kind, fields)
        for row in self.connection.execute("SELECT state_json FROM candidates ORDER BY id").fetchall():
            existing = json.loads(row["state_json"])
            same = content_key(existing["statement"], existing["kind"], existing)
            if same == wanted:
                raise DuplicateContent(
                    f"duplicate content already stored as {existing['id']} "
                    f"(status {existing['status']}, v{existing['version']}); no new version was created",
                    existing["id"],
                )
        with self.transaction():
            if self.connection.execute("SELECT 1 FROM candidates WHERE id=?", (candidate_id,)).fetchone():
                raise DojoError(f"candidate ID already exists: {candidate_id}")
            self._source_ids_available(source_values)
            relations: list[dict[str, Any]] = []
            if derived_from is not None:
                # Resolved, not stored as given: a card that was merged into another is
                # reachable only through its redirect, and an edge pointing at the merged
                # id would stop resolving the moment the redirect chain grew.
                origin, _ = self.resolve(derived_from)
                if origin["id"] == candidate_id:
                    raise DojoError("a card cannot be derived from itself")
                relations.append({
                    "type": "derived_from",
                    "target": origin["id"],
                    "note": ("写在这一场讨论里；那一场开始前带着 " + origin["id"]
                             + "（不表示变窄或变宽）"),
                })
            state = {
                "id": candidate_id,
                "version": 1,
                "status": "draft",
                "statement": statement,
                "kind": kind,
                **fields,
                "sources": source_values,
                "aliases": [],
                "relations": relations,
                "sessions": [_text(session, "session")] if session else [],
                "confirmation": {"active": False},
            }
            # #1831b: the creating event names the sources it attached. Without this,
            # a group-less source added here could never be attributed to the session
            # that brought it (`independence()` reads the ledger, and the ledger never
            # said which source this write introduced), so its card fell to
            # `unidentified` and was admitted -- absence passing as a pass. The key is
            # absent from events written before this change, and nothing backfills it:
            # those cards keep the answer they had rather than getting a guessed one.
            details: dict[str, Any] = {
                "session": session,
                "sources": [source["id"] for source in source_values],
            }
            if relations:
                # On the creating row so a reader of the ledger sees the edge without
                # having to diff two card states.
                details["derived_from"] = relations[0]["target"]
            self._insert_candidate(state, "add", details)
        return state

    def attach_source(self, candidate_id: str, source: dict[str, Any], session: str | None = None) -> dict[str, Any]:
        """Add provenance to an existing card without restating it.

        This is what a second independent session reaching the same claim does: the
        content is a duplicate, so no new version of the wording is written, but the
        card gains an independence group and can then be broadcast as two sessions'
        compatible claim. The evidence needed to say that is the source itself.
        """
        with self.transaction():
            state = self._get(_id(candidate_id))
            source_value = self._source(source)
            # What makes a second source worth recording is a new *independence
            # group*, not a new session. Independence is counted per group
            # (`independent_groups`), so a source whose group the card already has
            # adds no provenance and this is a genuine no-op -- including the case a
            # published test pins, two sources under one session sharing one group.
            #
            # The gate used to ask about the session instead, which dropped a source
            # carrying a fresh group whenever the session had spoken before: on the
            # CLI, `attach-source` with a second group under the same session gave
            # rc 0, wrote no event and kept no source. The case `attach-source`
            # exists for was the one case it silently discarded.
            events = [event for event in self.history(candidate_id)["events"]
                      if event.get("event") in ("add", "attach_source")]
            if any(_same_provenance(item, source_value, session, state, events)
                   for item in state.get("sources", [])):
                return state
            # A group-less source has no key of its own, so the acquiring session is
            # its only identity: a session that already contributed is replaying,
            # which is what the public version did and what a published test pins. A
            # source naming a group is keyed by that group, so a fresh one is recorded
            # even when the session has spoken before -- that was the defect.
            named = source_value.get("independence_group")
            if (not named or named == "unknown") and session and session in state.get("sessions", []):
                return state
            self._source_ids_available([source_value])
            state["sources"] = list(state.get("sources", [])) + [source_value]
            if session:
                state["sessions"] = _strings(state.get("sessions", []) + [session], "session")
            state = self._write(state, "attach_source", {"source": source_value["id"], "session": session},
                                {"source": source_value, "session": session})
        return state

    def accept_draft(
        self, candidate_id: str, session: str | None = None, *, agreed_at: str | None = None,
        draft_review: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """The session that left an unaccepted draft now accepts that exact wording.

        A draft written at session end says, in its own source, that the user did not
        accept this wording. If the user later resumes the conversation and accepts it
        verbatim, storing that as "nothing new" leaves the card asserting something
        false, and reporting it as a write would be a write that did not happen. So the
        single draft source is rewritten in place to the accepted shape, in one versioned
        event, and only when the whole provenance is that one draft from that one session.
        """
        with self.transaction():
            state = self._get(_id(candidate_id))
            sources = list(state.get("sources", []))
            if len(sources) != 1:
                raise DojoError("only a card with a single source can be accepted from draft")
            source = sources[0]
            if source.get("type") != "model_generated" or source.get("verification") != "unverified":
                raise DojoError("card is not an unaccepted draft")
            if session is not None and source.get("independence_group") != session:
                raise DojoError("only the session that wrote the draft can accept it")
            state["sources"] = [{
                **source,
                "type": "unknown",
                "verification": "unknown",
                "claim": "本次讨论会话形成的结论；完整会话原文保存在本地轨迹文件，内容未经独立核验。",
                "scope_note": "单一会话来源；不构成独立佐证。",
            }]
            if draft_review is not None:
                state["sources"][0]["claim"] = (f"本场第 {draft_review['turn']} 轮的拟写，经会后本地复核留下；"
                                                 "内容未经独立核验。")
            else:
                state["confirmation"] = self._confirmation_off(state, "accepted after the session resumed")
            # r112b: the acceptance is an action, so it is recorded as one. Retrieval
            # reads this event instead of inferring acceptance from the source's shape;
            # `dojo add --source-json` can produce the accepted shape by hand, and a
            # shape is not somebody agreeing to the sentence.
            details = {
                "session": session, ACCEPTANCE_EVENT: True, "path": "accept_draft",
                DIGEST_FIELD: wording_digest(state), CARD_FIELD: candidate_id,
            }
            if draft_review is not None:
                details.update(path="review_draft", draft_review=draft_review)
            # Same fact as `record_acceptance`'s: when the agreement happened, not when
            # this row is written. Omitted when the caller does not know it.
            agreed = _agreed_at(agreed_at)
            if agreed is not None:
                details[AGREED_AT_FIELD] = agreed
            state = self._write(state, "draft_accepted", details, {
                "session": session, "statement": state["statement"],
                "agreed_at": details.get(AGREED_AT_FIELD),
            })
        return state

    def record_pipeline_pass(
        self, candidate_id: str, pass_name: str, session: str, version: int, proposals: list[dict[str, Any]],
    ) -> int:
        """One pass's outcome for one card, and the marker that stops a rerun repeating it."""
        with self.transaction():
            event_id = self._event(candidate_id, "pipeline_pass", {
                "pass": pass_name, "session": session, "version": version, "proposals": proposals,
            })
            self.set_pipeline_mark(session, pass_name, candidate_id, version)
        return event_id

    def pipeline_mark(self, session: str, pass_name: str, candidate_id: str) -> int | None:
        """The version a pass last processed for this session, or None if never."""
        row = self.connection.execute(
            "SELECT version FROM pipeline_marks WHERE session=? AND pass_name=? AND candidate_id=?",
            (session, pass_name, candidate_id),
        ).fetchone()
        return None if row is None else int(row["version"])

    def set_pipeline_mark(self, session: str, pass_name: str, candidate_id: str, version: int) -> None:
        self.connection.execute(
            "INSERT INTO pipeline_marks(session,pass_name,candidate_id,version,created_at) VALUES(?,?,?,?,?) "
            "ON CONFLICT(session,pass_name,candidate_id) DO UPDATE SET version=excluded.version, created_at=excluded.created_at",
            (session, pass_name, candidate_id, version, _now()),
        )

    def list_candidates(self, include_history: bool = False) -> list[dict[str, Any]]:
        """The listing screen. A row says `unaccepted_draft: true` when the card's
        whole provenance is one model-written, unverified wording nobody accepted.

        r110 stored a session's landing point as exactly that and left it
        unreadable here: `status` is `draft` both for that and for a conclusion the
        user agreed to, so someone scanning `list` could take the version they never
        agreed to as settled. The key appears only when it is true -- a conclusion's
        row keeps the same five keys and bytes it had before -- and the draft is not
        filtered out, which would put it back where nobody sees it.
        """
        rows = self.connection.execute("SELECT state_json FROM candidates ORDER BY id").fetchall()
        values = [json.loads(row["state_json"]) for row in rows]
        if include_history:
            # r111b: `--history` is the same listing command's other path, and it had
            # the same blind spot. A draft and a conclusion the user agreed to both
            # read `status: draft` there with nothing else to tell them apart, so the
            # person who asked for the fuller view got less signal than the short one.
            # The marker sits beside the record; `status` is the ledger's value and is
            # not rewritten.
            for state in values:
                if is_unaccepted_draft(state):
                    state["unaccepted_draft"] = True
            return values
        listing = []
        for state in values:
            row = {key: state[key] for key in ("id", "version", "status", "statement", "kind")}
            if is_unaccepted_draft(state):
                row["unaccepted_draft"] = True
            listing.append(row)
        return listing

    def history(self, candidate_id: str) -> dict[str, Any]:
        candidate_id = _id(candidate_id)
        snapshots = self.connection.execute(
            "SELECT version,state_json,created_at FROM snapshots WHERE candidate_id=? ORDER BY version",
            (candidate_id,),
        ).fetchall()
        if not snapshots:
            raise DojoError(f"candidate not found: {candidate_id}")
        events = self.connection.execute(
            "SELECT seq,event,details_json,created_at FROM events WHERE candidate_id=? ORDER BY seq",
            (candidate_id,),
        ).fetchall()
        return {
            "candidate_id": candidate_id,
            "versions": [
                {"version": row["version"], "state": json.loads(row["state_json"]), "created_at": row["created_at"]}
                for row in snapshots
            ],
            # `sequence` is the same number `repeat_of` carries, so a reader holding a
            # repeat row can find the row it names without a second command.
            "events": [
                {"sequence": row["seq"], "event": row["event"],
                 "details": json.loads(row["details_json"]), "created_at": row["created_at"]}
                for row in events
            ],
        }

    def resolve(self, candidate_id: str) -> tuple[dict[str, Any], list[str]]:
        requested = _id(candidate_id)
        path: list[str] = []
        current_id = requested
        while True:
            if current_id in path:
                raise DojoError(f"redirect loop detected: {' -> '.join(path + [current_id])}")
            path.append(current_id)
            state = self._get(current_id)
            target = state.get("redirect_to")
            if not target:
                return state, path
            current_id = _id(target, "redirect target")

    def _present_state(self, state: dict[str, Any]) -> dict[str, Any]:
        """Resolve stored relation targets for display without rewriting history."""
        result = dict(state)
        relations = []
        for relation in state.get("relations", []):
            displayed = dict(relation)
            target, chain = self.resolve(relation["target"])
            if len(chain) > 1:
                displayed["redirected_from"] = relation["target"]
            displayed["target"] = target["id"]
            relations.append(displayed)
        if "relations" in result:
            result["relations"] = relations
        return result

    def _link_endpoint(self, candidate_id: str, version: Any) -> dict[str, Any]:
        endpoint = {"id": candidate_id, "version": None}
        if type(version) is not int or version < 1:
            return endpoint
        endpoint["version"] = version
        row = self.connection.execute(
            "SELECT state_json FROM snapshots WHERE candidate_id=? AND version=?",
            (candidate_id, version),
        ).fetchone()
        if row is not None:
            snapshot = json.loads(row["state_json"])
            endpoint.update({key: snapshot[key] for key in (
                "statement", "kind", "scope", "sessions", "sources",
            ) if key in snapshot})
        return endpoint

    def _link_from_event(self, row: sqlite3.Row, target_id: str) -> dict[str, Any] | None:
        try:
            details = json.loads(row["details_json"])
        except (TypeError, json.JSONDecodeError):
            return None
        if not isinstance(details, dict) or details.get("target") != target_id:
            return None
        relation, source_id = details.get("type"), row["candidate_id"]
        if not isinstance(relation, str) or relation not in RELATIONS or not source_id:
            return None
        return {
            "relation": relation,
            "reason": details.get("note"),
            "sequence": row["seq"],
            "recorded_at": row["created_at"],
            "source": self._link_endpoint(source_id, details.get("version")),
            "target": self._link_endpoint(target_id, details.get("target_version")),
        }

    def incoming_links(self, candidate_id: str) -> list[dict[str, Any]]:
        """Read human link decisions addressed to this exact ID, not inherited edges.

        The event belongs to the source card. Its post-link snapshot retains the
        wording and sources at the decision (link only changes relations). A merge
        can copy a relation to another card, but cannot copy the decision that made it.
        Legacy events did not record the target version; do not guess from timestamps.
        """
        found = []
        for row in self.connection.execute(
            "SELECT candidate_id, seq, details_json, created_at FROM events "
            "WHERE event='link' ORDER BY seq"
        ):
            link = self._link_from_event(row, candidate_id)
            if link is not None:
                found.append(link)
        return found

    def _adoptable_link(self, state: dict[str, Any], sequence: int) -> None:
        """Check under the same writer lock as the new revision."""
        row = self.connection.execute(
            "SELECT seq,candidate_id,details_json,created_at FROM events WHERE seq=? AND event='link'",
            (sequence,),
        ).fetchone()
        if row is None:
            raise DojoError(f"找不到关联事件 #{sequence}；请使用 show 的 incoming_links.sequence")
        link = self._link_from_event(row, state["id"])
        if link is None:
            raise DojoError(f"关联 #{sequence} 不是明确登记到 {state['id']} 的关联")
        source, target = link["source"], link["target"]
        if "statement" not in source or "statement" not in target:
            raise DojoError(f"关联 #{sequence} 的登记版本未留存或无法读取，不能采纳")
        if target["version"] != state["version"]:
            raise DojoError(f"关联 #{sequence} 指向 v{target['version']}，当前是 v{state['version']}；"
                            "请重新核对并登记对当前版本的关联")

    def _link_adoption_events(self, candidate_id: str) -> Iterator[tuple[int, dict[str, Any]]]:
        for row in self.connection.execute(
            "SELECT seq,details_json FROM events WHERE candidate_id=? AND event='revise' ORDER BY seq",
            (candidate_id,),
        ):
            try:
                details = json.loads(row["details_json"])
            except (TypeError, json.JSONDecodeError):
                continue
            if (isinstance(details, dict) and type(details.get("adopt_link_sequence")) is int
                    and type(details.get("version")) is int and isinstance(details.get("reason"), str)
                    and details.get("effect") != "unchanged"):
                yield row["seq"], details

    def _link_adoptions(self, candidate_id: str) -> dict[int, dict[str, Any]]:
        return {
            details["adopt_link_sequence"]: {
                "sequence": seq, "version": details["version"], "reason": details["reason"],
            }
            for seq, details in self._link_adoption_events(candidate_id)
        }

    def _replay_link_adoption(
        self, state: dict[str, Any], sequence: int, request: dict[str, Any],
    ) -> dict[str, Any] | None:
        # Find a committed adoption on this exact card, not just wording that
        # happens to match. Never infer a request from older, partial ledger rows.
        for seq, details in self._link_adoption_events(state["id"]):
            if details["adopt_link_sequence"] != sequence:
                continue
            if details.get("request") != request:
                raise DojoError(f"关联 #{sequence} 已在修订 #{seq} 用于 v{details['version']}；"
                                "这次不是原请求。若要另作改写，请重新核对当前版本")
            receipt = {"link_sequence": sequence, "repeat_of": seq,
                       "adopted_version": details["version"], "current_version": state["version"]}
            self._event(state["id"], "revise" + REPEAT_EVENT_SUFFIX, {
                **details, "version": state["version"], "effect": "unchanged",
                "repeat_of": seq, "adopted_version": details["version"],
            })
            # Receipt metadata is command output only; it is not part of the card.
            return {**state, "adoption_replay": receipt}
        return None

    def show(self, candidate_id: str, *, include_incoming_links: bool = False) -> dict[str, Any]:
        state, path = self.resolve(candidate_id)
        payload = {
            "requested_id": candidate_id,
            "resolved_id": state["id"],
            "redirect_chain": path,
            "candidate": self._present_state(state),
        }
        # r1721: `show` answered "what does this say" and "where did it come from" but
        # not "when", while `search`, the chat context and `export` all answered it --
        # the same reading was inconsistent across two exits. The times go beside
        # `candidate`, never inside it: `candidate` is the stored state, byte for byte,
        # and a test compares it to that (`test_storage.py`, the full-listing case).
        # Absent fact means an absent key, so a card with no acceptance keeps exactly
        # the bytes it had.
        basis = self.time_basis(state["id"], state)
        if basis:
            payload["time_basis"] = basis
        # #1801: `time_basis` dates the wording and says nothing about the provenance
        # rows beside it, so a reader could date the sentence and not the evidence. The
        # key is added only when a source record really has a readable entry; a card
        # with no sources keeps exactly the bytes it had.
        provenance = self.source_basis(state["id"], state)
        if provenance:
            payload["source_basis"] = provenance
        # #1929: the same gap on the surface a person opens directly. Beside `candidate`
        # for the same reason the two above are: `candidate` is the stored state, and a
        # test compares it byte for byte.
        payload.update(self.revision_basis(state["id"], state))
        # His own words, for the surface a person opens directly. Beside `candidate` for
        # the same reason the keys above are: `candidate` is the stored state byte for
        # byte, and the answers are a different table.
        answers, local_answers = self._answer_views(state["id"])
        if answers:
            payload["answers"] = answers
        if local_answers:
            payload["local_answers"] = local_answers
        if include_incoming_links:
            incoming = self.incoming_links(path[0])
            if incoming:
                payload["incoming_links"] = incoming
                adoptions = self._link_adoptions(path[0])
                for link in incoming:
                    adoption = adoptions.get(link["sequence"])
                    if adoption:
                        link["adopted_by"] = {**adoption, "is_current": (
                            path[0] == state["id"] and adoption["version"] == state["version"]
                        )}
                payload["incoming_link_summary"] = _summarize_incoming_links(incoming, state)
        return payload

    def _active(self, state: dict[str, Any]) -> None:
        if state.get("redirect_to") or state["status"] == "superseded":
            raise DojoError("redirected/superseded candidates cannot be changed")
        if state["status"] == "withdrawn":
            raise DojoError("withdrawn candidate must be revised before confirmation or linking")

    def _confirmation_off(self, state: dict[str, Any], reason: str) -> dict[str, Any]:
        confirmation = dict(state.get("confirmation") or {})
        confirmation["active"] = False
        confirmation["revoked_reason"] = reason
        return confirmation

    def confirm(self, candidate_id: str, basis: str, session: str | None = None) -> dict[str, Any]:
        basis = _text(basis, "confirmation basis")
        with self.transaction():
            state = self._get(_id(candidate_id))
            if state.get("redirect_to") or state["status"] in {"withdrawn", "superseded"}:
                raise DojoError("only a current, non-withdrawn candidate can be confirmed discussable")
            state["status"] = "discussable"
            state["confirmation"] = {
                "active": True, "confirmed_by": "facilitator-role", "session": session,
                "basis": basis, "not_truth_claim": True,
            }
            if session:
                # r111: confirming is not a second sighting of the claim. Until this
                # change the confirmer went into `sessions`, which `independence()`
                # reads as a provenance group, so one facilitator marking a card
                # discussable raised a single-session card to cross_session and
                # `broadcast` handed it back as another session's compatible word.
                # The confirmer is recorded in its own field and counted by nothing.
                state["confirmed_sessions"] = _strings(
                    state.get("confirmed_sessions", []) + [session], "confirmed session"
                )
            state = self._write(state, "confirm_discussable",
                                {"basis": basis, "session": session, "not_truth_claim": True},
                                {"basis": basis, "session": session})
        return state

    def revoke(self, candidate_id: str, reason: str, session: str | None = None) -> dict[str, Any]:
        reason = _text(reason, "revocation reason")
        with self.transaction():
            state = self._get(_id(candidate_id))
            if not state.get("confirmation", {}).get("active") or state["status"] != "discussable":
                raise DojoError("candidate has no active discussability confirmation")
            state["status"] = "draft"
            state["confirmation"] = self._confirmation_off(state, reason)
            if session:
                # r111: revoking is the mirror of confirming -- also not provenance.
                state["confirmed_sessions"] = _strings(
                    state.get("confirmed_sessions", []) + [session], "confirmed session"
                )
            state = self._write(state, "revoke_confirmation", {"reason": reason, "session": session},
                                {"reason": reason, "session": session})
        return state

    def challenge(self, candidate_id: str, text: str, source: dict[str, Any] | None = None) -> dict[str, Any]:
        text = _text(text, "challenge")
        with self.transaction():
            state = self._get(_id(candidate_id))
            self._active(state)
            if source:
                source_value = self._source(source)
                self._source_ids_available([source_value])
                state["sources"].append(source_value)
            state["contradictions"] = _strings(state.get("contradictions", []) + [text], "challenge")
            state["status"] = "challenged"
            if state.get("confirmation", {}).get("active"):
                state["confirmation"] = self._confirmation_off(state, "candidate challenged")
            state = self._write(state, "challenge", {"text": text}, {"text": text})
        return state

    def revise(
        self,
        candidate_id: str,
        statement: str,
        reason: str,
        *,
        kind: str | None = None,
        premises: list[str] | None = None,
        scope: list[str] | None = None,
        alternatives: list[str] | None = None,
        contradictions: list[str] | None = None,
        unknowns: list[str] | None = None,
        session: str | None = None,
        adopt_link_sequence: int | None = None,
    ) -> dict[str, Any]:
        statement, reason = _text(statement, "statement"), _text(reason, "revision reason")
        if kind is not None and kind not in KINDS:
            raise DojoError(f"kind must be one of: {', '.join(sorted(KINDS))}")
        revised_fields = {
            "premises": premises,
            "scope": scope,
            "alternatives": alternatives,
            "contradictions": contradictions,
            "unknowns": unknowns,
        }
        # The whole ask, not the state it produces or merely the field names.
        request = {"statement": statement, "reason": reason, "kind": kind,
                   **revised_fields, "session": session}
        if adopt_link_sequence is not None:
            if type(adopt_link_sequence) is not int or not 1 <= adopt_link_sequence <= 2**63 - 1:
                raise DojoError("--adopt-link 需要正整数关联事件编号（sequence）")
            request["adopt_link_sequence"] = adopt_link_sequence
        with self.transaction():
            state = self._get(_id(candidate_id))
            if adopt_link_sequence is not None:
                # Serialize lookup and first adoption behind the same writer lock.
                # An exact retry acknowledges history even if the card changed.
                replay = self._replay_link_adoption(state, adopt_link_sequence, request)
                if replay is not None:
                    return replay
            self._active(state)
            old_statement = state["statement"]
            if adopt_link_sequence is not None:
                self._adoptable_link(state, adopt_link_sequence)
                if statement == old_statement:
                    raise DojoError("采纳关联须写出不同的新措辞；原样保留不是一次改写")
            state["statement"] = statement
            if kind is not None:
                state["kind"] = kind
            for field, values in revised_fields.items():
                if values is not None:
                    state[field] = _strings(values, field)
            if session:
                state["sessions"] = _strings(state.get("sessions", []) + [session], "session")
            state["status"] = "draft"
            state["confirmation"] = self._confirmation_off(state, "candidate revised")
            # Both ends of the request: the wording being left is bookkeeping (a card
            # may arrive here from anywhere), the wording being asked for is the ask
            # itself. Recording only the departure made a second target for one reason
            # indistinguishable from a replay.
            changed_fields = [field for field, values in revised_fields.items() if values is not None]
            details = {"from_statement": old_statement, "to_statement": statement,
                       "reason": reason}
            if kind is not None or changed_fields or session is not None:
                details["changed_fields"] = ["statement", *changed_fields]
                if kind is not None:
                    details["changed_fields"].append("kind")
                if session is not None:
                    details["session"] = session
            if adopt_link_sequence is not None:
                details["adopt_link_sequence"] = adopt_link_sequence
            state = self._write(state, "revise", details, request)
        return state

    def promote_answers(
        self,
        candidate_id: str,
        answers: list[dict[str, Any]],
        *,
        session: str | None = None,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        """Keep his own words on the card, one entry per part, exactly as he said them.

        This is the write `discuss` has never done: four concrete answers came back, the
        receipt said 没有写进卡片, and the card's `part_sources` said 系统补 for all four
        forever (measured at the CLI, `.scratch/3474/probe_promote.py`). The values come
        from trace rows, never from a caller's paraphrase, and each entry keeps the
        session and moment it came from, so a reader can go back to the record.

        Two limits, both deliberate:

        * the sentence and the content fields do not move -- his condition is not silently
          promoted into `scope`, which would hand the model's phrasing back to him as his
          own. `answers` is its own key, shown under its own heading.
        * no source is attached and the status is untouched. An answer is material about
          the claim, not a second arrival at it, so `independence`, `broadcast`, the
          acceptance digest and the discussable gate all read exactly as before.

        A part that already carries an answer is replaced only when the new one differs,
        and the earlier value stays in the ledger's `from` field -- the same rule every
        other write here follows. Passing the same answers again is a repeat, not a new
        version.
        """
        clean = self._answer_entries(answers)
        # Its own table, not the card's state: a state write bumps `version`, and
        # `pipeline_marks` compares against versions, so keeping a sentence he said would
        # turn finished work back into pending work -- the exact rule `_write` documents.
        # It would also change `wording_digest` if the key were part of content, which
        # would invalidate a recorded acceptance of the wording. Neither is acceptable for
        # a fact that is about his material, not about the claim.
        self._ensure_answers_table()
        with self.transaction():
            state = self._get(_id(candidate_id))
            self._active(state)
            if expected_version is not None and state["version"] != expected_version:
                raise DojoError("卡片已不是问答针对的那一版，未附任何原话")
            current = self.answers_for(candidate_id)
            merged: dict[str, Any] = dict(current)
            changed: list[str] = []
            replaced: dict[str, Any] = {}
            for entry in clean:
                key = entry["field"]
                previous = current.get(key)
                if (isinstance(previous, dict) and self._answer_selected(previous)
                        and previous.get("answer") == entry["answer"]):
                    # A version-bound discussion decision names this session's exact
                    # utterance, not just equivalent text from an earlier speaker.
                    if expected_version is None or all(previous.get(k) == v for k, v in entry.items()):
                        continue
                if isinstance(previous, dict):
                    replaced[key] = previous
                merged[key] = entry
                changed.append(key)
            if not changed:
                # Same answers again: a row in the ledger so a reader can tell a replay
                # from a second action, and no version move (nothing on the card changed).
                self._event(state["id"], "promote_answers.repeat", {
                    "fields": [], "session": session, "effect": "unchanged",
                })
                return state
            for key in changed:
                entry = merged[key]
                self.connection.execute(
                    "INSERT INTO answers(candidate_id,field,answer,session,at,question,trace,"
                    "promoted_at,provenance,recorded,selected) VALUES(?,?,?,?,?,?,?,?,?,?,1) "
                    "ON CONFLICT(candidate_id,field) DO UPDATE SET answer=excluded.answer, "
                    "session=excluded.session, at=excluded.at, question=excluded.question, "
                    "trace=excluded.trace, promoted_at=excluded.promoted_at, "
                    "provenance=excluded.provenance, recorded=excluded.recorded, selected=excluded.selected",
                    (
                        state["id"], key, entry["answer"], entry.get("session"),
                        entry.get("at"), entry.get("question"), entry.get("trace"),
                        _now(), entry.get("provenance"), entry.get("recorded"),
                    ),
                )
            details: dict[str, Any] = {"fields": changed, "session": session}
            if replaced:
                details["from"] = replaced
            # The ledger row names the session that said it; the card's `sessions` is not
            # touched, because `independence()` counts it as a provenance group and his
            # answer is material about the claim, not a second arrival at it.
            self._event(state["id"], "promote_answers", details)
        return state

    def unpromote_answer(
        self, candidate_id: str, part: str, reason: str, *, session: str | None = None,
    ) -> dict[str, Any]:
        """Take one stored answer off the card, keeping what it was in the ledger.

        Reversible by design: a person who decides his sentence was about something else
        takes it back without a new card and without losing what was said. The wording,
        the content fields and the status do not move.
        """
        reason = _text(reason, "unpromote reason")
        field = str(part or "").strip()
        # Both the Chinese part name the discussion uses and the field key the card
        # stores are accepted; refusing the first would make the CLI ask a person to learn
        # the storage vocabulary to undo their own answer.
        field = PART_FIELD_BY_NAME.get(field, field)
        if field not in PART_KEYS_BY_FIELD:
            raise DojoError("part must be one of: " + ", ".join(PART_KEYS_BY_FIELD))
        self._ensure_answers_table()
        with self.transaction():
            state = self._get(_id(candidate_id))
            self._active(state)
            answers = self.answers_for(candidate_id)
            if field not in answers:
                raise DojoError(f"this card carries no answer for {field}")
            removed = answers.pop(field)
            self.connection.execute(
                "DELETE FROM answers WHERE candidate_id=? AND field=?",
                (state["id"], field),
            )
            self._event(state["id"], "unpromote_answer",
                        {"field": field, "reason": reason, "session": session,
                         "from": removed})
        return state

    ANSWERS_SCHEMA = """
        CREATE TABLE IF NOT EXISTS answers (
            candidate_id TEXT NOT NULL REFERENCES candidates(id),
            field TEXT NOT NULL,
            answer TEXT NOT NULL,
            session TEXT,
            at TEXT,
            question TEXT,
            trace TEXT,
            promoted_at TEXT NOT NULL,
            provenance TEXT,
            recorded INTEGER,
            selected INTEGER,
            PRIMARY KEY(candidate_id, field)
        );
    """
    # Columns added after the first version of this table. A library written by the
    # earlier build has the table but not these, and the review found two screens reading
    # facts that were never stored: a hand-kept answer was reported as a discussion, and
    # an answer whose trace write failed was given a record path anyway.
    ANSWERS_ADDED_COLUMNS = {
        # 'discussion' (a `discuss` row) or 'manual' (a typed `promote`). NULL on rows
        # written before this column existed: unknown, and said as unknown, not guessed.
        "provenance": "TEXT",
        # 1 when this sentence was found in the record file after the session ended, 0
        # when it was not. NULL means nothing was ever going to be recorded (a hand-kept
        # answer). This is what lets the screen promise a way back only for a sentence
        # that is really in the file.
        "recorded": "INTEGER",
        # No inferred consent for automatic or ambiguous attachments in old libraries.
        "selected": "INTEGER",
    }

    def _ensure_answers_table(self) -> None:
        """Create the answers table if it is not there.

        Not in `__init__`: opening a library must describe it, not change it (#1893), and
        a read-only search may not run DDL. `executescript` commits, so this stays outside
        the caller's transaction, the same way `ensure_reads_table` does.
        """
        # The decision and the write happen inside one `BEGIN IMMEDIATE`. Checking
        # outside it was a real race, found by review: two sessions upgrading the same
        # old library at the same moment both read "no such column", both ran the ALTER,
        # and the second one died on `duplicate column name` -- losing that person's own
        # answer for a reason that had nothing to do with their answer (see
        # `.scratch/3480/probe_concurrent_upgrade.py`). `BEGIN IMMEDIATE` takes the write
        # lock before the read, so the second writer sees the first one's column and
        # simply proceeds. Distinct columns can then never collide.
        with self.transaction():
            if self.connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='answers'"
            ).fetchone() is None:
                # `executescript` would commit the open transaction; the table is small
                # and fixed, so the statements are run one by one instead.
                for statement in self.ANSWERS_SCHEMA.split(";"):
                    if statement.strip():
                        self.connection.execute(statement)
            self._widen_answers_table()

    def _widen_answers_table(self) -> None:
        """Add the columns a library from an earlier build does not have yet.

        `CREATE TABLE IF NOT EXISTS` does nothing to an existing table, so a reader on an
        older library would otherwise get `no such column: provenance` the first time a
        screen asked. Existing rows keep NULL in both: what they cannot say, they do not
        claim.

        **Call it inside a transaction.** The read of `PRAGMA table_info` and the `ALTER`
        have to be under the same write lock, or two sessions upgrading the same library
        each decide the column is missing and the second fails.

        `duplicate column name` is still treated as success if it arrives: a library
        upgraded by a build that took a different route to the same column is in exactly
        the state this method wants, and refusing there would turn a harmless race into a
        lost answer. Any other error is raised, because a column that silently did not get
        added would turn into `no such column` on the next read.
        """
        # A test seam with a real job: the window between this read and the ALTER below
        # is where the review's race lives, and it is microseconds wide in a real run.
        # `tests/test_answers_upgrade.py` and the evidence red arm widen it here rather
        # than by editing the code under test, so the arm keeps exercising the real
        # method instead of a copy. Production leaves it at zero.
        pause = float(getattr(self, "_widen_pause", 0) or 0)
        if pause:
            import time as _time
            _time.sleep(pause)
        present = {row["name"] for row in
                   self.connection.execute("PRAGMA table_info(answers)")}
        for name, kind in self.ANSWERS_ADDED_COLUMNS.items():
            if name in present:
                continue
            if pause:
                import time as _time
                _time.sleep(pause)
            try:
                self.connection.execute(f"ALTER TABLE answers ADD COLUMN {name} {kind}")
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc):
                    raise
                # Another writer added it between our read and our write. The state we
                # wanted is the state we have.
                continue
            present.add(name)

    @staticmethod
    def _answer_selected(row: dict[str, Any]) -> bool:
        return row.get("selected") == 1 or row.get("provenance") == "manual"

    def _answer_views(self, candidate_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        selected: dict[str, Any] = {}
        local: dict[str, Any] = {}
        for key, item in self.answers_for(candidate_id).items():
            destination = selected if self._answer_selected(item) else local
            fields = ("answer", "session", "at", "provenance", "recorded")
            if destination is local:
                fields += ("question", "promoted_at")
            destination[key] = {field: item[field] for field in fields if field in item}
        return selected, local

    def card_answers(self, candidate_id: str) -> dict[str, dict[str, Any]]:
        """Only expressly attached quotes, without whole-session locators."""
        return self._answer_views(candidate_id)[0]

    def answers_for(self, candidate_id: str) -> dict[str, dict[str, Any]]:
        """His stored answers for one card, by field key, in part order.

        Absent table means "no answers recorded here", not "he said nothing": a library
        written before this table existed simply has nothing to show, and every caller
        prints nothing for it rather than a sentence about his silence.
        """
        if self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='answers'"
        ).fetchone() is None:
            return {}
        # The added columns may not exist yet on a library this build has not written to;
        # read what is there rather than failing the whole screen over two optional facts.
        present = {row["name"] for row in
                   self.connection.execute("PRAGMA table_info(answers)")}
        extra = [name for name in ("provenance", "recorded", "selected") if name in present]
        rows = self.connection.execute(
            "SELECT field,answer,session,at,question,trace,promoted_at"
            + ("" if not extra else "," + ",".join(extra))
            + " FROM answers WHERE candidate_id=?", (_id(candidate_id),)
        ).fetchall()
        found = {
            row["field"]: {
                "field": row["field"],
                "answer": row["answer"],
                "session": row["session"],
                "at": row["at"],
                "provenance": row["provenance"] if "provenance" in extra else None,
                "recorded": row["recorded"] if "recorded" in extra else None,
                **({"selected": row["selected"]} if "selected" in extra and row["selected"] is not None else {}),
                "question": row["question"],
                "trace": row["trace"],
                "promoted_at": row["promoted_at"],
            }
            for row in rows if row["field"] in PART_KEYS_BY_FIELD
        }
        return {key: found[key] for key in PART_KEYS_BY_FIELD if key in found}

    @staticmethod
    def _answer_entries(answers: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Validate answers coming from a caller, keeping the stored value verbatim.

        Accepted shape: a list of `{"part"|"field", "answer", "session"?, "at"?,
        "question"?, "trace"?}`. `part` may be the Chinese part name or the field key --
        both are what the trace and the CLI have to hand. Neither the text nor the moment
        is filled in by this program: an answer with no `at` stays without one rather
        than borrowing the write time, which would make two different answers look
        simultaneous.
        """
        if not isinstance(answers, list) or not answers:
            raise DojoError("answers must be a non-empty list")
        entries: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in answers:
            if not isinstance(item, dict):
                raise DojoError("each answer must be an object")
            field = str(item.get("field") or item.get("part") or "").strip()
            field = PART_FIELD_BY_NAME.get(field, field)
            if field not in PART_KEYS_BY_FIELD:
                raise DojoError("answer part must be one of: " + ", ".join(PART_KEYS_BY_FIELD))
            if field in seen:
                raise DojoError(f"two answers for the same part: {field}")
            seen.add(field)
            answer = item.get("answer")
            if not isinstance(answer, str) or not answer.strip():
                raise DojoError(f"answer for {field} cannot be empty")
            entry: dict[str, Any] = {"field": field, "answer": answer}
            for key in ("session", "at", "question", "trace"):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    entry[key] = value
            # How this sentence got here. A caller that knows says so; `discuss` passes
            # 'discussion' and the CLI passes 'manual'. Anything else is left unset rather
            # than guessed, because the screen would otherwise be inventing a conversation
            # (the review found a hand-kept answer reported as a `--no-trace` discussion).
            provenance = item.get("provenance")
            if provenance in ("discussion", "manual"):
                entry["provenance"] = provenance
            # 1/0 only when the caller actually checked the record file; missing means
            # "nothing was going to record it", which is not the same as "it failed".
            recorded = item.get("recorded")
            if recorded in (True, False):
                entry["recorded"] = 1 if recorded else 0
            entries.append(entry)
        return entries

    def alias(self, candidate_id: str, wording: str, reason: str) -> dict[str, Any]:
        wording, reason = _text(wording, "alias"), _text(reason, "alias reason")
        with self.transaction():
            state = self._get(_id(candidate_id))
            self._active(state)
            if wording == state["statement"] or wording in state["aliases"]:
                raise DojoError("alias is already present or identical to the statement")
            state["aliases"].append(wording)
            state = self._write(state, "alias", {"wording": wording, "reason": reason},
                                {"wording": wording, "reason": reason})
        return state

    def link(self, candidate_id: str, relation: str, target_id: str, reason: str) -> dict[str, Any]:
        if relation not in RELATIONS:
            # `derived_from` is deliberately not in this set: it is the program's record
            # that a discussion produced one card while holding the other, and only
            # `add()` can make that true. Accepting it here let a hand-made link be read
            # as a discussion that never happened (the supervisor's repro on a library
            # with two confirmed cards).
            raise DojoError(f"relation must be one of: {', '.join(sorted(RELATIONS))}")
        reason = _text(reason, "link reason")
        with self.transaction():
            source = self._get(_id(candidate_id))
            self._active(source)
            target, _ = self.resolve(target_id)
            if target["status"] == "superseded" and not target.get("redirect_to"):
                raise DojoError("cannot link to a split/superseded candidate")
            if source["id"] == target["id"]:
                raise DojoError("self-links are not allowed")
            link = {"type": relation, "target": target["id"], "note": reason}
            if link in source.get("relations", []):
                raise DojoError("identical relation already exists")
            source["relations"].append(link)
            source = self._write(source, "link", {**link, "target_version": target["version"]},
                                 {"relation": link["type"], "target": link["target"],
                                  "note": reason})
        return source

    def split(self, candidate_id: str, children: list[dict[str, Any]], reason: str) -> list[dict[str, Any]]:
        reason = _text(reason, "split reason")
        if len(children) < 2:
            raise DojoError("split requires at least two child candidates")
        with self.transaction():
            parent = self._get(_id(candidate_id))
            self._active(parent)
            source_by_id = {source["id"]: source for source in parent.get("sources", [])}
            child_values: list[dict[str, Any]] = []
            child_ids: set[str] = set()
            for raw in children:
                if not isinstance(raw, dict):
                    raise DojoError("each split child must be a JSON object")
                child_id = _id(raw.get("id") or _new_id("d"), "child ID")
                if child_id == parent["id"] or child_id in child_ids or self.connection.execute("SELECT 1 FROM candidates WHERE id=?", (child_id,)).fetchone():
                    raise DojoError(f"child candidate ID already exists: {child_id}")
                child_ids.add(child_id)
                kind = raw.get("kind", parent["kind"])
                if kind not in KINDS:
                    raise DojoError(f"kind must be one of: {', '.join(sorted(KINDS))}")
                requested_sources = raw.get("source_ids")
                if requested_sources is None:
                    child_sources = list(parent.get("sources", []))
                else:
                    if not isinstance(requested_sources, list) or any(item not in source_by_id for item in requested_sources):
                        raise DojoError("split source_ids must refer to source IDs on the parent")
                    if len(set(requested_sources)) != len(requested_sources):
                        raise DojoError("split source_ids must not contain duplicates")
                    child_sources = [source_by_id[item] for item in requested_sources]
                child_values.append({
                    "id": child_id,
                    "version": 1,
                    "status": "draft",
                    "statement": _text(raw.get("statement"), "child statement"),
                    "kind": kind,
                    "premises": _strings(raw.get("premises", parent.get("premises", [])), "premise"),
                    "scope": _strings(raw.get("scope", parent.get("scope", [])), "scope"),
                    "alternatives": _strings(raw.get("alternatives", parent.get("alternatives", [])), "alternative"),
                    "contradictions": _strings(raw.get("contradictions", parent.get("contradictions", [])), "contradiction"),
                    "unknowns": _strings(raw.get("unknowns", parent.get("unknowns", [])), "unknown"),
                    "sources": child_sources,
                    "aliases": [],
                    "relations": [],
                    "sessions": list(parent.get("sessions", [])),
                    "split_from": parent["id"],
                    "confirmation": {"active": False},
                })
            for child in child_values:
                self._insert_candidate(child, "split_child", {"parent": parent["id"], "reason": reason})
            parent["status"] = "superseded"
            parent["confirmation"] = self._confirmation_off(parent, "split into child candidates")
            parent["split_children"] = [child["id"] for child in child_values]
            self._write(parent, "split", {"children": [child["id"] for child in child_values], "reason": reason},
                        {"children": [child["id"] for child in child_values], "reason": reason})
        return child_values

    def _source_union(self, first: list[dict[str, Any]], second: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result = list(first)
        by_id = {item["id"]: item for item in result}
        for source in second:
            previous = by_id.get(source["id"])
            if previous is not None:
                if previous != source:
                    raise DojoError(f"cannot merge conflicting provenance for source ID {source['id']}")
                continue
            result.append(source)
            by_id[source["id"]] = source
        return result

    def _merged_target(self, target: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
        """The canonical record a merge would produce, built in memory and written by nobody.

        Split out of `merge` so the acceptance guards can ask what the merged card would
        *say* before a single row is written. Reading a half-applied merge to decide
        whether the merge was allowed would be the same class of mistake as repairing
        history on read.
        """
        merged = dict(target)
        merged["sources"] = self._source_union(target.get("sources", []), source.get("sources", []))
        aliases = list(target.get("aliases", []))
        for wording in [source["statement"], *source.get("aliases", [])]:
            if wording != target["statement"] and wording not in aliases:
                aliases.append(wording)
        merged["aliases"] = aliases
        changed: list[str] = []
        for key in CONTENT_FIELDS:
            union = _strings(target.get(key, []) + source.get(key, []), key)
            if union != list(target.get(key, [])):
                changed.append(key)
            merged[key] = union
        merged["relations"] = list(target.get("relations", []))
        for relation in source.get("relations", []):
            resolved, _ = self.resolve(relation["target"])
            if resolved["id"] != target["id"]:
                value = {**relation, "target": resolved["id"]}
                if value not in merged["relations"]:
                    merged["relations"].append(value)
        merged[MERGED_CHANGED_FIELDS] = changed  # returned only; stripped before any write
        return merged

    def _acceptance_route(self, candidate_id: str, state: dict[str, Any]) -> str | None:
        """The route that recorded the current-wording acceptance, if the event names one."""
        route = self.time_basis(candidate_id, state).get("acceptance_path")
        return route if isinstance(route, str) and route.strip() else None

    def _merge_acceptance_refusal(
        self, source: dict[str, Any], target: dict[str, Any], merged: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Whether this merge would move or drop a recorded acceptance, and why.

        Two different losses, one guard, because both are the same failure: a reader sees
        the same sentence and a *worse* record, and nothing in the merge output says so.

        - The accepted card is the one being merged away. Its ledger row survives as
          `superseded`, but every reading surface resolves the redirect, so the canonical
          card is now unaccepted while its sentence is unchanged: search drops it, the
          export header loses `accepted_at`. Nothing was rewritten and the merge is still
          a lie about who agreed to what. Refused, and the operator names the direction.
        - The accepted card is the target, but the union changes a field the acceptance's
          digest covers (`premises`/`scope`/...). An acceptance of the old sentence does
          not carry over to a new one -- that is `#1497`, reached through `merge` instead
          of `revise`. Refused unless the wording identity is unchanged.

        Acceptances for an *older* wording on either card are not this guard's business:
        they are already `superseded` to anyone reading, and refusing on them would turn
        an honest audit line into a permanent ban on merging the card.
        """
        source_accepted = self.has_acceptance(source["id"], source)
        target_accepted = self.has_acceptance(target["id"], target)
        wording_changed = wording_digest(merged) != wording_digest(target)
        if not source_accepted and not (target_accepted and wording_changed):
            return None
        changed = list(merged.get(MERGED_CHANGED_FIELDS) or [])
        reasons: list[str] = []
        if source_accepted:
            route = self._acceptance_route(source["id"], source)
            reasons.append(
                f"{source['id']} is a card a user accepted"
                + (f" (route {route})" if route else "")
                + f"; merging it into {target['id']} would leave the merged card with the same"
                f" sentence and no acceptance, and drop it out of search and the export header"
            )
        if target_accepted and wording_changed:
            route = self._acceptance_route(target["id"], target)
            reasons.append(
                f"{target['id']} was accepted on its current wording"
                + (f" (route {route})" if route else "")
                + f", and merging {source['id']} into it would change "
                + (", ".join(changed) if changed else "its wording")
                + "; an acceptance of the old sentence does not cover the new one"
            )
        return {
            "accepted_card": source["id"] if source_accepted else target["id"],
            "source": source["id"], "target": target["id"],
            "wording_changed": wording_changed, "changed_content_fields": changed,
            "reasons": reasons,
            "message": "merge refused: " + "; and ".join(reasons) + ".",
        }

    def merge(self, source_id: str, target_id: str, *, confirmed: bool, reason: str) -> dict[str, Any]:
        if not confirmed:
            raise DojoError("merge requires explicit human acknowledgement (--confirm)")
        reason = _text(reason, "merge reason")
        refusal: dict[str, Any] | None = None
        with self.transaction():
            # Everything is read inside the write transaction: deciding "this merge would
            # cost an acceptance" from a snapshot taken before `BEGIN IMMEDIATE` would let
            # an acceptance land between the check and the write, which is the exact case
            # the guard exists for. A refusal still writes no candidate, no snapshot and
            # no version -- only the refusal event, which is committed with this
            # transaction and raised on afterwards.
            source, source_chain = self.resolve(source_id)
            target, target_chain = self.resolve(target_id)
            if source["id"] == target["id"]:
                raise DojoError("merge source and target resolve to the same candidate")
            self._active(source)
            self._active(target)
            if source["status"] == "withdrawn" or target["status"] == "withdrawn":
                raise DojoError("withdrawn candidates cannot be merged")
            # Resolve both endpoints before installing the new redirect; this rejects loops.
            if source["id"] in target_chain or target["id"] in source_chain:
                raise DojoError("merge would create a redirect cycle")
            before_source, before_target = source, target
            merged = self._merged_target(target, source)
            refusal = self._merge_acceptance_refusal(source, target, merged)
            if refusal is not None:
                self._event(source["id"], MERGE_REFUSED_EVENT, {**refusal, "reason": reason})
            else:
                merged.pop(MERGED_CHANGED_FIELDS, None)
                target = self._write(merged, "merge_received", {"source": source["id"], "reason": reason},
                                     {"source": source["id"], "reason": reason})
                source = dict(source)
                source["status"] = "superseded"
                source["redirect_to"] = target["id"]
                source["confirmation"] = self._confirmation_off(source, "merged into " + target["id"])
                source = self._write(source, "merge_redirect", {"target": target["id"], "reason": reason},
                                     {"target": target["id"], "reason": reason})
                event_id = self._event(source["id"], "merge", {
                    "source": source["id"], "target": target["id"], "reason": reason,
                    "before_source": before_source, "before_target": before_target,
                    "after_source_version": source["version"], "after_target_version": target["version"],
                })
                source["last_merge_event"] = event_id  # returned only; not persisted in candidate state
        if refusal is not None:
            # After the commit, so the refusal row survives the exception.
            raise MergeRefused(refusal["message"], refusal)
        return self._get(target["id"])

    def unmerge(self, source_id: str, reason: str) -> dict[str, Any]:
        reason = _text(reason, "unmerge reason")
        source_id = _id(source_id)
        with self.transaction():
            event_row = self.connection.execute(
                "SELECT seq,details_json FROM events WHERE candidate_id=? AND event='merge' ORDER BY seq DESC LIMIT 1",
                (source_id,),
            ).fetchone()
            if event_row is None:
                raise DojoError(f"no reversible merge found for source candidate {source_id}")
            details = json.loads(event_row["details_json"])
            source_now = self._get(details["source"])
            target_now = self._get(details["target"])
            if source_now.get("redirect_to") != target_now["id"]:
                raise DojoError("merge is no longer current")
            if source_now["version"] != details["after_source_version"] or target_now["version"] != details["after_target_version"]:
                raise DojoError("cannot unmerge after either candidate has changed; review and restore manually")
            source_restored = dict(details["before_source"])
            target_restored = dict(details["before_target"])
            source_restored = self._write(
                source_restored, "unmerge", {"target": target_now["id"], "reason": reason},
                {"target": target_now["id"], "reason": reason})
            target_restored = self._write(
                target_restored, "unmerge", {"source": source_now["id"], "reason": reason},
                {"source": source_now["id"], "reason": reason})
        return {"source": source_restored, "target": target_restored}

    def abstain(self, reason: str, candidate_id: str | None = None, next_question: str | None = None) -> dict[str, Any]:
        reason = _text(reason, "abstain reason")
        if candidate_id:
            candidate_id = _id(candidate_id)
            self._get(candidate_id)
        if next_question is not None:
            next_question = _text(next_question, "next question")
        with self.transaction():
            event_id = self._event(candidate_id, "abstain", {"reason": reason, "next_question": next_question})
        return {"event_id": event_id, "candidate_id": candidate_id, "reason": reason, "next_question": next_question}

    def withdraw(self, candidate_id: str, reason: str) -> dict[str, Any]:
        reason = _text(reason, "withdrawal reason")
        with self.transaction():
            state = self._get(_id(candidate_id))
            self._active(state)
            state["status"] = "withdrawn"
            state["confirmation"] = self._confirmation_off(state, reason)
            state = self._write(state, "withdraw", {"reason": reason}, {"reason": reason})
        return state

    def local_discussion_draft(
        self, state: dict[str, Any], events: list[dict[str, Any]] | None = None,
    ) -> bool:
        """A discussion's proposed wording is local until this wording is accepted."""
        if not is_discussion_material(state):
            return False
        candidate_id = state["id"]
        if events is None:
            events = self._acquisition_events(candidate_id)
        snapshot_digest = self._snapshot_digest(candidate_id)
        if is_accepted_conclusion(state, events, snapshot_digest):
            return False
        if state.get("status") != "challenged":
            return True
        # A manually filed challenge is an explicit addition to reference material,
        # not a new host proposal. Walk back past challenges and content-preserving
        # changes only; a revision of the underlying wording still needs approval.
        challenges = {event["details"].get("version") for event in events
                      if event["event"] == "challenge" and event["details"].get("effect") != "unchanged"}
        digest = wording_digest(state)
        approved = {_accepted_wording_digest(event, snapshot_digest, candidate_id) for event in events} - {None}
        if not approved:
            return True
        for version in range(state["version"], 1, -1):
            previous = snapshot_digest(version - 1)
            if previous is None or (previous != digest and version not in challenges):
                break
            if previous in approved:
                return False
            digest = previous
        return True

    def has_acceptance(self, candidate_id: str, state: dict[str, Any] | None = None) -> bool:
        """Whether some path recorded that a user accepted this card's wording.

        Asked of the ledger, not of the card's shape. A card written with
        `--source-json` can have the same fields as an accepted one and has no such
        event, which is the whole point.

        The event also has to be for *this* wording: an acceptance recorded before a
        rewrite does not speak for the rewritten sentence.
        """
        state = state if state is not None else self._get(_id(candidate_id))
        return is_accepted_conclusion(
            state, self._acquisition_events(_id(candidate_id)), self._snapshot_digest(_id(candidate_id)),
        )

    def _snapshot_digest(self, candidate_id: str) -> Callable[[int], str | None]:
        """Read-only lookup from a stored version to the wording identity it held.

        `snapshots` is written by every `_write`, so a version named by an old
        acceptance event still has its wording. Nothing here writes: the fallback in
        `is_accepted_conclusion` must not repair history, only read it.
        """
        def by_version(version: int) -> str | None:
            row = self.connection.execute(
                "SELECT state_json FROM snapshots WHERE candidate_id=? AND version=?",
                (candidate_id, version),
            ).fetchone()
            if row is None:
                return None
            return wording_digest(json.loads(row["state_json"]))
        return by_version

    def audit_acceptances(self) -> dict[str, Any]:
        """How every acceptance in this library stands, counted rather than assumed.

        Read only. Three counts, because they mean different things and collapsing them
        would hide the one that matters:

        - `bound`: an acceptance names a wording and that wording is the card's now.
        - `superseded`: every acceptance that could be resolved names a wording the
          card no longer holds, which is the honest state after a rewrite.
        - `unbound`: an acceptance exists but its wording cannot be recovered (no
          digest, no usable version, or the snapshot is gone), and nothing else on
          the card binds. Not silently "no acceptance" -- that is the failure this
          report exists to make visible.

        Checked in that order, because that is the order the predicate answers in: a
        card with one resolvable acceptance for the current wording is accepted, and a
        second unresolvable event does not un-accept it. Reporting it as `unbound`
        would contradict the retrieval gate.
        """
        report = {"bound": [], "unbound": [], "superseded": []}
        rows = self.connection.execute(
            "SELECT id,state_json FROM candidates ORDER BY id"
        ).fetchall()
        for row in rows:
            state = json.loads(row["state_json"])
            accepts = [event for event in self._acquisition_events(state["id"]) if _is_acceptance_event(event)]
            if not accepts:
                continue
            wanted = wording_digest(state)
            digests = [
                _accepted_wording_digest(event, self._snapshot_digest(state["id"]), state["id"])
                for event in accepts
            ]
            record = {"id": state["id"], "status": state["status"], "acceptances": len(accepts)}
            if any(digest == wanted for digest in digests):
                report["bound"].append(record)
            elif any(digest is None for digest in digests):
                # Two different failures, kept apart: an acceptance that cannot say
                # what wording it was for, and one that says it was for another card.
                # Collapsing them would hide the second, which is the one whose wording
                # matches perfectly and is still not this card's acceptance.
                foreign = any(
                    _acceptance_names_another_card(event, state["id"]) for event in accepts
                )
                report["unbound"].append({**record, "reason": (
                    "acceptance was written for another card" if foreign
                    else "acceptance names no recoverable wording")})
            else:
                report["superseded"].append({**record, "reason": "accepted wording is not the current one"})
        return {key: value for key, value in report.items()}

    def record_acceptance(
        self, candidate_id: str, session: str | None, *, path: str, agreed_at: str | None = None,
        draft_review: dict[str, Any] | None = None,
    ) -> int:
        """Record that a user accepted this wording verbatim, on any path that can do so.

        Kept separate from `_write` so it does not bump a version: accepting a wording
        already stored changes no content. `path` names which route accepted it, so a
        later reader can tell a resumed draft from a conclusion reached in conversation.
        `version` identifies the immutable snapshot with its exact wording and field order.

        `agreed_at` is when the agreement itself happened, as the caller knew it. It is
        not the same fact as the event's `created_at` -- when this row was written -- and
        the two can be weeks apart: a reader copying an acceptance out of a trace file
        writes it today for a sentence agreed a month ago. Until r1638 the writer had no
        way to pass the moment, so the trace held it and the write dropped it, and every
        backfilled acceptance dated the copy. Omitted by callers that only know now (the
        live conversation passes the moment the accepting line arrived); absent means no
        claim, never "agreed at the record time".
        """
        with self.transaction():
            state = self._get(_id(candidate_id))
            details = {
                "session": session, "path": path, DIGEST_FIELD: wording_digest(state),
                CARD_FIELD: candidate_id, "version": state["version"],
            }
            agreed = _agreed_at(agreed_at)
            if agreed is not None:
                details[AGREED_AT_FIELD] = agreed
            if draft_review is not None:
                details["draft_review"] = draft_review
            return self._event(candidate_id, ACCEPTANCE_EVENT, details)

    def _acquisition_events(self, candidate_id: str) -> list[dict[str, Any]]:
        """The card's event ledger, read only -- used to tell a sighting from a confirmation."""
        rows = self.connection.execute(
            "SELECT event,details_json,created_at FROM events WHERE candidate_id=? ORDER BY seq",
            (candidate_id,),
        ).fetchall()
        return [
            {"event": row["event"], "details": json.loads(row["details_json"]), "created_at": row["created_at"]}
            for row in rows
        ]

    def time_basis(self, candidate_id: str, state: dict[str, Any] | None = None) -> dict[str, str]:
        """When this card's wording was written, and when *that wording* was accepted.

        Two facts, read from two different places, and deliberately not derived from
        each other:

        - `versioned_at`: `snapshots.created_at` of the *first* stored version whose
          `wording_digest` equals the wording on the card now, i.e. when the sentence a
          reader is looking at was written. Not the current version's row: `confirm`,
          `revoke` and `attach_source` all write a new version while leaving the sentence
          byte-identical, and reading the current row made a status change reprint the
          sentence's date as today (r1627 measured it, `bumps2.py`). A wording that is
          restored after a rewrite dates from its first appearance, not the restore.
        - `accepted_at`: `events.created_at` of an acceptance event whose bound wording
          is the wording on the card now. An acceptance recorded before a rewrite is not
          an acceptance of the rewritten sentence, so `c-one-fact` in the meter -- accepted,
          then revised -- has no `accepted_at`.
        - `acceptance_path`: that same event's `details.path` -- the route that recorded
          the acceptance, verbatim as the writer passed it (`discuss_conclusion`,
          `accept_draft`, or whatever a backfill tool names itself). The
          one field that separates "a user agreed in conversation" from "a reader copied
          the agreement in from a text file later"; both print the same `accepted_at`
          shape, and the backfilled one prints the moment of the copy, not of the
          agreement. Omitted when the event carries no path.
        - `agreed_at`: that same event's `details.agreed_at` -- when the agreement itself
          happened, when the accepting caller knew it. r1638: `accepted_at` is the moment
          the row was written, which for a backfill is the copy date; this is the one
          field that can say what the copy is about. Omitted when the event has none,
          which is every event written before r1638. Read as written: this build does not
          infer it from `versioned_at`, from the trace, or from any clock.

        Absent fact means the key is absent, never `None` and never `_now()`. "No key"
        is the honest statement "this build found no such record" and keeps the reading
        of a card with no acceptance exactly as it was.

        Read only. Nothing is written back, no row is repaired, no digest is filled in.
        """
        state = state if state is not None else self._get(_id(candidate_id))
        basis: dict[str, str] = {}
        wanted = wording_digest(state)
        # First version that carried this exact wording, not the version number the card
        # happens to hold now. Read oldest first, so a later status-only bump cannot move
        # the date forward; `snapshots` keeps every version, so this is a read.
        for row in self.connection.execute(
            "SELECT state_json,created_at FROM snapshots WHERE candidate_id=? ORDER BY version",
            (candidate_id,),
        ):
            if wording_digest(json.loads(row["state_json"])) == wanted:
                basis["versioned_at"] = row["created_at"]
                break
        accepted = [
            event for event in self._acquisition_events(candidate_id)
            if _is_acceptance_event(event)
            and _accepted_wording_digest(
                event, self._snapshot_digest(candidate_id), candidate_id) == wanted
        ]
        if accepted:
            # The newest acceptance of this exact wording is the one a reader means by
            # "when was this accepted"; an earlier one for the same sentence is the same
            # fact stated twice.
            basis["accepted_at"] = accepted[-1]["created_at"]
            # r1627: the time alone cannot separate "agreed in conversation" from "copied
            # in from a trace file afterwards". The route is already on the event.
            path = (accepted[-1].get("details") or {}).get("path")
            if isinstance(path, str) and path.strip():
                basis["acceptance_path"] = path
            # r1638: the record time is not the agreement time when the acceptance was
            # copied in later. Printed only when the writer stated it; nothing here
            # substitutes `accepted_at` for it and nothing backfills an old event.
            agreed = (accepted[-1].get("details") or {}).get(AGREED_AT_FIELD)
            if isinstance(agreed, str) and agreed.strip():
                basis["agreed_at"] = agreed
        return basis

    def source_basis(self, candidate_id: str, state: dict[str, Any] | None = None) -> dict[str, Any]:
        """When each source record on this card entered the library, and by what route.

        `time_basis` dates the *wording*; it says nothing about the provenance rows a
        reader is asked to weigh. #1801 measured that gap on every library on disk: 696
        source records, and no surface printed one of their entry times. A reader could
        say when the sentence was written and still not say whether the evidence behind
        it arrived before or after the claim it is meant to support.

        The moment is read, never guessed. A source id can never be reused
        (`_source_ids_available` refuses a second card claiming a different record under
        the same id), so the first version whose state holds the id is the version that
        introduced it, and one event wrote that version:

        - version 1, written by `add` or `load_simulated_seed`: the creating event's own
          `created_at`. Those events store exactly the sources passed in.
        - version 1, written by `split_child` or `merge_received`: the source did not enter
          *here*; it was copied from the card named in the event. The walk continues
          there, so the answer is when it entered the library, not when it was copied.
        - version > 1: the event carrying that `version` in its details. `attach_source`
          names the source itself and is the one event that records an acquisition;
          `merge_received` copies again and is followed back; any other event at that
          version did not bring a new source, so the id is reported undetermined.

        This is not the same question as "which snapshot first mentions the id", which is
        what a hand-written join would do: it answers "when was this record first *stored
        anywhere on this card*". #1801 ran both over the tree and they differ on 11
        records -- the join reports the copy (or a backdated snapshot) as the entry. So
        the copy is reported separately as `entered_on`, and `entered_by` names the event
        kind that did the introducing.

        A source whose entry cannot be pinned appears in `undetermined_source_ids` and
        gets no time at all, rather than inheriting the card's `versioned_at` or today's
        clock. Nothing is written back and no row is repaired.
        """
        state = state if state is not None else self._get(_id(candidate_id))
        here = _id(candidate_id)
        sources: dict[str, dict[str, str]] = {}
        undetermined: list[str] = []
        for source in state.get("sources") or []:
            source_id = source.get("id") if isinstance(source, dict) else None
            if not isinstance(source_id, str) or not source_id:
                continue
            found = self._source_entry(here, source_id, 0)
            if found is None:
                undetermined.append(source_id)
                continue
            entered_at, entered_by, entered_on = found
            entry = {"entered_at": entered_at, "entered_by": entered_by}
            if entered_on != here:
                entry["entered_on"] = entered_on
            sources[source_id] = entry
        payload: dict[str, Any] = {}
        if sources:
            payload["sources"] = sources
        if undetermined:
            payload["undetermined_source_ids"] = sorted(set(undetermined))
        return payload

    def revision_basis(self, candidate_id: str, state: dict[str, Any] | None = None) -> dict[str, Any]:
        """Why this card's current wording exists, when he said why he changed his mind.

        `time_basis` dates the sentence and `source_basis` dates the evidence; neither
        says *why* the sentence is this one. #1929 measured the gap on a card walked
        through accept -> challenge -> revise -> accept: the ledger held
        `{"from_statement": ..., "reason": ..., "to_statement": ...}` and none of
        `retrieve`, `broadcast` or `export` carried the reason, so a later reader was
        handed a narrowed claim with a counterexample beside it and no way to tell that
        the narrowing had happened or what prompted it. `show --history` had the row,
        and nobody reading an export opens it.

        Read, never inferred. Only a `revise` row counts -- `revise.repeat` is the same
        request arriving again and states no new reason -- and only one whose
        `to_statement` is the wording this card holds *now*: a card revised twice carries
        the reason for the current sentence, not the history of every sentence. The
        earlier reason is still in the ledger and `show --history` still prints it; this
        key answers the narrower question a reader of a card is actually asking.

        Absent when the card has no such row, so a card that was never revised keeps
        exactly the bytes it had -- the same rule `time_basis` and `source_basis` follow.
        """
        state = state if state is not None else self._get(_id(candidate_id))
        wanted = wording_digest(state)
        #
        # Match on the sentence only, through the same normalization duplicates use.
        # `wording_digest` would also fold in `kind` and the four content fields, and a
        # revision that keeps the wording while widening `scope` is the same sentence
        # with the same reason for being there -- the wrong key for this question.
        current = normalize_wording(state.get("statement", ""))
        matching = [
            event for event in self._acquisition_events(_id(candidate_id))
            if event["event"] == "revise"
            and isinstance((event.get("details") or {}).get("to_statement"), str)
            and isinstance((event.get("details") or {}).get("reason"), str)
            and normalize_wording(event["details"]["to_statement"]) == current
        ]
        if not matching:
            return {}
        latest = matching[-1]
        details = latest["details"]
        basis: dict[str, Any] = {
            "reason": details["reason"],
            "revised_at": latest["created_at"],
        }
        # The wording it replaced, when the ledger has it. Named `left_wording` rather
        # than `from_statement`, because the export prints it as prose and a reader
        # should not have to know the event's field names to read the line.
        left = details.get("from_statement")
        if isinstance(left, str) and left.strip():
            basis["left_wording"] = left
        return {"revision_basis": basis}

    def _source_entry(self, candidate_id: str, source_id: str, depth: int) -> tuple[str, str, str] | None:
        """(entered_at, event kind, card it entered on) for one source id, or None.

        Split out of `source_basis` because the copy routes recurse: a merged or split
        card holds a source it did not introduce, and the honest answer is on the card
        that did.
        """
        if depth > 12:
            # A merge/split graph that loops would otherwise recurse forever. No stored
            # library reaches this; saying "undetermined" beats a recursion error.
            return None
        version = None
        for row in self.connection.execute(
            "SELECT version,state_json FROM snapshots WHERE candidate_id=? ORDER BY version",
            (candidate_id,),
        ):
            held = json.loads(row["state_json"]).get("sources") or []
            if any(isinstance(item, dict) and item.get("id") == source_id for item in held):
                version = row["version"]
                break
        if version is None:
            return None
        events = self._acquisition_events(candidate_id)
        if version == 1:
            creating = next((e for e in events if e["event"] in SOURCE_CREATING_EVENTS), None)
            if creating is not None:
                return _dated(creating["created_at"], creating["event"], candidate_id)
            copied = next((e for e in events if e["event"] in ("split_child", "merge_received")), None)
            if copied is None:
                return None
            details = copied.get("details") or {}
            parent = details.get("parent") if copied["event"] == "split_child" else details.get("source")
            if not isinstance(parent, str) or not parent:
                return None
            return self._source_entry(parent, source_id, depth + 1)
        writers = [e for e in events if (e.get("details") or {}).get("version") == version]
        for event in writers:
            if event["event"] == "attach_source" and (event.get("details") or {}).get("source") == source_id:
                return _dated(event["created_at"], event["event"], candidate_id)
        for event in writers:
            if event["event"] == "merge_received":
                other = (event.get("details") or {}).get("source")
                if isinstance(other, str) and other:
                    return self._source_entry(other, source_id, depth + 1)
        return None

    READS_SCHEMA = """
        CREATE TABLE IF NOT EXISTS reads (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            wording_digest TEXT NOT NULL,
            reader_session TEXT,
            at TEXT NOT NULL,
            surface TEXT NOT NULL,
            accepted_at_at_read TEXT
        );
        CREATE INDEX IF NOT EXISTS reads_by_candidate ON reads(candidate_id, seq);
    """

    def record_read(self, candidate_id: str, session: str | None, *, surface: str) -> None:
        """Log that this wording left the library towards somebody.

        #1534 established that nothing in this database records a *read*: `search`,
        `show` and `export` returned rows and left no trace, so "was this read before
        or after it was accepted" had no answer on disk. This is that write point.

        Deliberately outside `Store.retrieve` and `export_prompt`: both are pure (the
        three outputs and `distill()` depend on that), and a log written inside them
        would fire for every internal caller too, so the pipeline's own lookups would
        be recorded as somebody reading the card.

        Deliberately not an `events` row: `independence()` reads the sessions on
        `attach_source` events, and a new event kind carrying a session is one reader
        away from counting a *look* as a second sighting -- the defect r111/r112 spent
        two rounds removing.

        The table is created by `ensure_reads_table`, not in `__init__`, on purpose:
        `__init__` runs for every command, so a table declared there would rewrite the
        bytes of the frozen old library merely by opening it.

        `accepted_at_at_read` is what makes two reads orderable against an acceptance
        without trusting a clock comparison: `events.created_at` is second-resolution
        while `at` is microsecond, so within one second "read then accepted" would
        otherwise look like "read after acceptance". Recording the acceptance state as
        it stood at read time keeps the two apart whatever the clock granularity.
        """
        state = self._get(_id(candidate_id))
        basis = self.time_basis(candidate_id, state)
        if self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='reads'"
        ).fetchone() is None:
            # Outside the insert's transaction on purpose: `executescript` commits
            # implicitly, which would end the transaction wrapping the insert.
            self.ensure_reads_table()
        with self.transaction():
            self.connection.execute(
                "INSERT INTO reads(candidate_id,version,wording_digest,reader_session,at,surface,"
                "accepted_at_at_read) VALUES(?,?,?,?,?,?,?)",
                (
                    candidate_id, int(state["version"]), wording_digest(state), session,
                    datetime.now(timezone.utc).isoformat(timespec="microseconds"),
                    surface, basis.get("accepted_at"),
                ),
            )

    def ensure_reads_table(self) -> None:
        """Create the read log if absent. Called by the command layer, not by `__init__`."""
        with self.transaction():
            self.connection.executescript(self.READS_SCHEMA)

    def reads(self, candidate_id: str | None = None, reader_session: str | None = None) -> dict[str, Any]:
        """The read log, or the fact that this library has none. Read only.

        `holds_table: false` is not "nobody read this": a library whose reads were
        never logged has no table at all. The two are reported apart so an empty list
        cannot be mistaken for the stronger claim.

        `reader_session` narrows the log to one reader. Without it, a card that two
        sessions were handed comes back as one list and the second person has to pick
        his own row by `sequence` -- the one thing he does not have. The filter is here
        rather than in a new command because it changes no stored byte and answers the
        question the exit was written for.
        """
        present = self.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='reads'"
        ).fetchone()
        if present is None:
            return {"holds_table": False, "rows": []}
        sql = "SELECT * FROM reads"
        clauses: list[str] = []
        params: list[Any] = []
        if candidate_id is not None:
            clauses.append("candidate_id=?")
            params.append(_id(candidate_id))
        if reader_session is not None:
            # Compared by value, not by column name: an unrecorded reader is stored as
            # NULL, and NULL must not match a named reader.
            clauses.append("reader_session=?")
            params.append(reader_session)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY seq"
        rows = [dict(row) for row in self.connection.execute(sql, tuple(params))]
        payload: dict[str, Any] = {"holds_table": True, "rows": rows}
        if reader_session is not None:
            payload["reader"] = reader_session
        return payload

    def provenance_reading(self, candidate_id: str, session: str | None = None) -> dict[str, Any]:
        """The provenance facts an exit may state, and the one it may not.

        #1774: `broadcast` rows and a discussion's closing line left the reader to turn
        `independence_groups=2 | independent=true` into "two people". #1763 measured that
        the ledger cannot make that turn: an echo and a genuinely independent second
        arrival write byte-identical provenance, so any rendering that reads as "people"
        is unsupported however many entries it adds up. The exits therefore state counts
        -- how many source records the card holds, how many group names those sources
        declared for themselves, and how many handouts the read log holds -- and this
        docstring is the rule for anyone tempted to render those counts as persons.

        `this_session_logged` is None when the question cannot be put: no session was
        given, or the library has no read log at all. None is reported rather than False,
        because "this library never logged a handout" and "logged, and this session is
        not in the log" are different facts and only the second one is about a reader.
        `handout_rows` is None for the same reason and not 0: `reads()` already reports a
        missing table apart from an empty one, and a count of 0 here would put that lie
        back into a field that only ever gets added up. `session` must be a *reader*
        identity; `broadcast`'s `--session` names a writer to exclude, so the broadcast
        row passes no session at all rather than reporting a reader it does not know.
        "Whether the second group is a second arrival" is not among the keys: that is the
        signal #1763 found missing, and inventing one from these counts is the defect.

        `readable` is False when the card declares at most one group name. That is the
        one shape where no key here can be misread: one source record and one group name
        cannot be taken for two people, and the exits that call this keep their exact
        bytes for it (#1774's control cell). A row or line was never added to fix a
        sentence that was already true.
        """
        state = self._get(_id(candidate_id))
        sources = list(state.get("sources") or [])
        groups = {
            source.get("independence_group") for source in sources
            if source.get("independence_group") and source.get("independence_group") != "unknown"
        }
        log = self.reads(candidate_id)
        readers = sorted({row["reader_session"] for row in log["rows"] if row["reader_session"]})
        if session is None or not log["holds_table"]:
            logged: bool | None = None
        else:
            logged = session in readers
        return {
            "readable": len(groups) >= 2,
            "source_records": len(sources),
            "self_declared_groups": len(groups),
            "handout_rows": len(log["rows"]) if log["holds_table"] else None,
            "handout_readers": readers,
            "this_session_logged": logged,
            "counts": (
                "source records and self-declared group names, not people: two group names "
                "can come from one person"
            ),
        }

    def _matches(
        self, terms: set[str], *, include_withheld: bool = False,
        include_answers: bool = False,
    ) -> list[tuple[int, set[str], dict[str, Any], dict[str, Any] | None]]:
        """Every retrievable card whose text overlaps `terms`, best overlap first.

        A conclusion the user accepted sits at `status=draft` (accepting a wording
        does not confirm it), which is also where a card nobody touched sits; a card
        a facilitator merely unblocked is `discussable`. Gating on `discussable`
        alone therefore kept the sentence the user agreed to out of reach.

        The gate is: `discussable`, or `draft` **with a recorded acceptance in the
        event ledger** (`has_acceptance`). The ledger -- not the card's shape -- is
        what separates "somebody accepted this wording" from "written that way".
        Withdrawn, superseded, redirected and challenged cards stay out as before, and
        a card with no acceptance event never gets in, however conclusion-shaped it is.

        `include_withheld=True` is the reading screen's question, not the gate's: the
        gate stays exactly as it is and *also* returns the cards it refused, each with
        a machine-readable reason. #3436 measured why that matters -- a card he
        remembered, `challenge`d since, returned no row at all, so the screen said
        "the library holds nothing about this" when the library held that sentence and
        the doubt. The reason is returned as a code plus counts, never as a sentence:
        what a refusal is called on screen is the screen's decision.
        """
        # Read once, and kept so `retrieve` can search the same snapshot for reverse
        # edges instead of asking the table again per row (the supervisor measured 601
        # full-table reads for one search over 600 cards).
        self.last_scan = [json.loads(row["state_json"]) for row in
                          self.connection.execute("SELECT state_json FROM candidates ORDER BY id").fetchall()]
        matches: dict[str, tuple[int, set[str], dict[str, Any], dict[str, Any] | None]] = {}
        local_only: set[str] = set()
        for state in self.last_scan:
            try:
                canonical, _chain = self.resolve(state["id"])
            except DojoError:
                continue
            if canonical.get("redirect_to"):
                continue
            # Asked through the predicate, not through `has_acceptance` directly: a
            # predicate with no caller is decoration, and a mutant that changes the
            # predicate would then leave every gate green (that is what S1 showed).
            # The `status == "draft"` term is load-bearing on its own: a card that was
            # accepted and then challenged keeps its acceptance event, so the predicate
            # alone would let it back into search. That is S5, and it is why this is an
            # `and`, not just a call.
            accepts = self._acquisition_events(canonical["id"])
            if self.local_discussion_draft(canonical, accepts):
                local_only.add(canonical["id"])
                continue
            kept = canonical["status"] == "discussable" or (
                canonical["status"] == "draft"
                and is_accepted_conclusion(canonical, accepts, self._snapshot_digest(canonical["id"]))
            )
            if not kept and not include_withheld:
                continue
            # The author can see prior versions locally. A current approval is not
            # permission to quote earlier, potentially unapproved wording in search.
            haystack = (candidate_text(canonical) if is_discussion_material(canonical)
                        else searchable_text(canonical, accepts))
            if include_answers:
                # His own answers are on the card now, so the words *he* used have to
                # reach it -- that is the point of keeping them (see `dojo/answers.py`).
                # Kept out of `searchable_text` on purpose: that function is also the
                # model-facing matcher's input, and this slice leaves the material handed
                # to a model exactly as it was. Only the person's own screen asks for this.
                # From the answers table, not from the card's state: the answers are not
                # part of the stored card, and asking the state dict silently matched
                # nothing -- measured on the walk, where a query built from his own
                # counterexample found the card only through the word 系统 in its
                # sentence, scoring 1 instead of 4.
                extra = " ".join(str(item.get("answer", ""))
                                 for item in self.card_answers(canonical["id"]).values())
                if extra:
                    haystack += " " + extra
            found = terms.intersection(lexical_terms(haystack))
            if not found:
                continue
            withheld = None if kept else self._withheld_basis(canonical, accepts)
            previous = matches.get(canonical["id"])
            if previous is None or len(found) > previous[0]:
                matches[canonical["id"]] = (len(found), found, canonical, withheld)
        if local_only:
            self.last_scan = [state for state in self.last_scan if state["id"] not in local_only]
        return sorted(matches.values(), key=lambda item: (-item[0], item[2]["id"]))

    def recently_written(self, limit: int = 3, *, for_reading: bool = False) -> list[dict[str, Any]]:
        """The cards whose wording entered this library most recently, newest first.

        Read from `snapshots.created_at` of the version that first carried each card's
        *current* wording, so a status change does not make an old sentence look new
        (the same rule `time_basis` follows). This is a way in, not a search: it says
        nothing about meaning, and it exists because word overlap cannot answer "I
        remember the gist" -- #3436 measured a query in his own words that matched no
        card at all while the library held it.

        Only cards that could be read at all are returned: redirected cards are shown
        at their target, withdrawn ones are included with their status printed, because
        a person browsing recent work needs to see that a card was withdrawn.
        """
        if limit < 1:
            return []
        rows = self.connection.execute(
            "SELECT id FROM candidates ORDER BY id"
        ).fetchall()
        found: list[tuple[str, dict[str, Any]]] = []
        for row in rows:
            try:
                state, chain = self.resolve(row["id"])
            except DojoError:
                continue
            if state.get("redirect_to") or len(chain) > 1:
                continue
            if for_reading and self.local_discussion_draft(state):
                continue
            basis = self.time_basis(state["id"], state)
            when = basis.get("versioned_at")
            if not isinstance(when, str):
                continue
            found.append((when, state))
        found.sort(key=lambda item: (item[0], item[1]["id"]), reverse=True)
        return [state for _when, state in found[:limit]]

    def _withheld_basis(
        self, state: dict[str, Any], accepts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Why the retrieval gate refused this card, in facts rather than in prose.

        Read from the record, one code per cause, and the causes are not exclusive --
        a card can be challenged and later withdrawn. The order is the order a reader
        would care about: a redirect sends them elsewhere, a withdrawal is his own
        retraction, a doubt is somebody else's, and a stale acceptance is only about
        which wording was agreed to.
        """
        basis: dict[str, Any] = {"codes": []}
        target = state.get("redirect_to")
        if target:
            basis["codes"].append("redirected")
            basis["redirect_to"] = target
        if state.get("status") == "withdrawn":
            basis["codes"].append("withdrawn")
        if state.get("status") == "challenged":
            doubts = [value for value in state.get("contradictions") or [] if isinstance(value, str)]
            basis["codes"].append("challenged")
            # The ledger says how many; the last one is the doubt that made it
            # `challenged` (`challenge` appends). Both are facts, not a reading of them.
            basis["contradiction_count"] = len(doubts)
            if doubts:
                basis["latest_doubt"] = doubts[-1]
        # `accepts` is the card's whole event ledger, not its acceptance events: every
        # card written through `add` has events, so testing it directly labelled an
        # untouched draft "somebody once accepted an earlier wording". Caught by this
        # slice's own test before the screen ever printed it.
        agreements = [event for event in accepts if _is_acceptance_event(event)]
        # Only when it is the whole story: a challenged or withdrawn card is not handed over
        # for that reason already, and stacking "and also no acceptance record" on it made
        # the first line of an entry carry two causes and read like a verdict (seen on a
        # terminal). This code answers "why was a plain draft refused", which is otherwise
        # an unexplained rejection.
        if not agreements and state.get("status") == "draft" and not basis["codes"]:
            # The gate's other refusal, and the commonest one: a `draft` nobody recorded
            # an acceptance for. It has to be named, because "retrieval will not hand it
            # over" with no reason reads as an unexplained rejection -- and the reason is
            # a fact about the ledger, never about the sentence (he may have agreed in a
            # room nobody wrote down).
            basis["codes"].append("no_acceptance_record")
        if "challenged" not in basis["codes"] and agreements and not is_accepted_conclusion(
            state, accepts, self._snapshot_digest(state["id"])
        ):
            # An acceptance exists but binds no wording this card holds now -- the card
            # was rewritten after somebody agreed to it. Not "nobody ever agreed", which
            # is the sentence this whole line of work exists to stop printing.
            basis["codes"].append("acceptance_superseded")
        return basis

    def retrieve(self, query: str, limit: int = 10, *, for_reading: bool = False) -> dict[str, Any]:
        """Cards whose text overlaps the query, plus -- when asked -- what was refused.

        `for_reading` is the person's screen (`dojo search`). It adds two things the
        model's context must not grow: the cards the gate refused, with the record's
        reason for each, and, per result, which of the card's wordings matched. Both
        are additive keys read from rows that already exist; with the flag off every
        byte is what it was.
        """
        query = str(query or "").strip()
        if limit < 1 or limit > 100:
            raise DojoError("limit must be between 1 and 100")
        terms = lexical_terms(query, query=True)
        if not terms:
            empty: dict[str, Any] = {"query": query, "method": "distinct lexical term overlap; no semantic inference", "matched_terms": [], "results": []}
            if for_reading:
                empty["withheld"] = []
                # A query with no searchable term at all is the same situation on screen
                # as a query that matched nothing, so it gets the same way in.
                empty["recent"] = self._recent_rows(3)
            return empty
        ordered = self._matches(terms, include_withheld=for_reading,
                                include_answers=for_reading)
        # The reverse edges are read once for the whole screen, out of the snapshot the
        # matcher just loaded: `later_versions` used to query the whole candidate table
        # per row (601 reads for one search over 600 cards, supervisor's reproducer).
        everything = getattr(self, "last_scan", []) if for_reading else []
        # Tells the lookup that it is being called by a screen, where a missing snapshot is
        # a caller bug to survive rather than a request to read the table 600 times.
        self._reading_scan = bool(for_reading)
        # One reverse index and one event-log read for the whole screen, not one per row.
        # Measured over 2400 cards with no edge at all: per-row walking cost 217 -> 513 ms
        # (supervisor's `/var/tmp/dojo-lineage-recheck.7JZ7o6YE`). Built only on the reading
        # path, so the model-facing call does neither.
        later_index = self.derivation_index(everything) if for_reading else {}
        bases = self.derivations() if for_reading else {}
        results = []
        for score, found, state, withheld in ordered:
            if withheld is not None or len(results) >= limit:
                continue
            row = self._card_row(state, score, found)
            if for_reading:
                row.update(self._matched_wording(state, found))
                # His own words are already on the row (`_card_row` reads the table).
                # This block used to add them from the state; nothing is left to add.
                # `later_index` empty means no card in this library carries such an edge,
                # which is the ordinary case: skip the per-row lookup entirely rather than
                # ask 2400 times for a list that is always empty.
                later = (self.later_versions(state["id"], index=later_index,
                                             derivations=bases)
                         if later_index else [])
                if later:
                    # Only when there is one, so every other row keeps its bytes. The
                    # total is on the row separately because the list is capped: "five more"
                    # and "two more" must not print the same.
                    row["derived_later"] = [item for item in later
                                            if not item.get("counted_only")]
                    row["derived_later_total"] = len(later)
                derivation = bases.get(state["id"])
                if derivation:
                    row["derivation"] = derivation
            results.append(row)
        payload: dict[str, Any] = {
            "query": query,
            "method": "transparent lexical overlap (distinct query terms only); not semantic search or truth ranking",
            "matched_terms": sorted(terms),
            "results": results,
        }
        if for_reading:
            # Same score order as the results, so the one he half-remembers is not
            # buried under the ones he does not.
            refused_rows: list[dict[str, Any]] = []
            for score, found, state, withheld in ordered:
                if withheld is None:
                    continue
                row = {
                    **self._card_row(state, score, found),
                    **self._matched_wording(state, found),
                    # The reason is a record code plus counts; what it is called on
                    # screen is `finding.py`'s decision, not this method's.
                    "refused": withheld,
                }
                # Read once, and only for a card that has one, so every other refused
                # row keeps the bytes it had.
                later = (self.later_versions(state["id"], index=later_index,
                                             derivations=bases)
                         if later_index else [])
                if later:
                    row["derived_later"] = [item for item in later
                                            if not item.get("counted_only")]
                    row["derived_later_total"] = len(later)
                derivation = bases.get(state["id"])
                if derivation:
                    row["derivation"] = derivation
                refused_rows.append(row)
            payload["withheld"] = refused_rows
            if not ordered:
                # No words overlapped at all, so this is the one case where a list is
                # still the useful thing to print: recent cards by ledger entry time,
                # with the reason for each refusal and its conditions, so he can see
                # the one he meant. Named as a different method on screen -- it is not
                # a search result and is never sorted as one.
                payload["recent"] = self._recent_rows(3)
        return payload

    def _recent_rows(self, limit: int) -> list[dict[str, Any]]:
        """Recent cards with the gate's verdict on each, for the screen's fallback."""
        recent = self.recently_written(limit, for_reading=True)
        bases = self.derivations([state["id"] for state in recent]) if recent else {}
        rows: list[dict[str, Any]] = []
        for state in recent:
            row: dict[str, Any] = {
                **self._card_row(state, 0, set()),
                "refused": self._withheld_basis(
                    state, self._acquisition_events(state["id"])
                ) if state["status"] != "discussable" and not self.has_acceptance(state["id"], state)
                else None,
            }
            # Same basis the result rows carry, so the way-in does not describe a
            # discussed card as a hand-written relation (or the reverse).
            derivation = bases.get(state["id"])
            if derivation:
                row["derivation"] = derivation
            rows.append(row)
        return rows

    def _card_row(self, state: dict[str, Any], score: int, found: set[str]) -> dict[str, Any]:
        """Everything a reader (or the model) is told about one matched card.

        Split out of `retrieve` when the refused cards started carrying the same facts: two
        copies of this block would drift, and the one that drifted quietly would be the
        one a person reads about the sentence he was looking for (#3436).
        """
        answers = self.card_answers(state["id"])
        row: dict[str, Any] = {
            "id": state["id"],
            "version": state["version"],
            "status": state["status"],
            "statement": state["statement"],
            "kind": state["kind"],
            "score": score,
            "matched_terms": sorted(found),
            "scope": state.get("scope", []),
            "premises": state.get("premises", []),
            "alternatives": state.get("alternatives", []),
            "contradictions": state.get("contradictions", []),
            "unknowns": state.get("unknowns", []),
            "sources": state.get("sources", []),
            "relations": self._present_state(state).get("relations", []),
            "aliases": state.get("aliases", []),
        }
        # His own words about this card, when the table holds any. Added by value like
        # every key around it, so a card with nothing stored keeps exactly the bytes it
        # had -- and on the model-facing row too, because the answers are part of what
        # makes the card findable only for the person's own screen; a hole there would
        # hand a row over with no visible reason. (The model's reach is unchanged: the
        # matcher only searches answers when the reading screen asks.)
        if answers:
            row["answers"] = {key: dict(item) for key, item in answers.items()}
        # #1929: a card he revised carried the reason it changed only in the ledger,
        # so this row described the sentence and hid how it got that way. Added by
        # value, only when a revision of *this* wording exists.
        if not is_discussion_material(state):
            row.update(self.revision_basis(state["id"], state))
        # r111c: `status` is `discussable` for a conclusion the user accepted and
        # equally for a card a facilitator merely unblocked, so this screen could
        # hand back an unaccepted draft as settled. Judged by the value, and only
        # when true: an accepted conclusion's row keeps the same bytes.
        if is_unaccepted_draft(state):
            row["unaccepted_draft"] = True
        # r115: the ledger holds when the sentence was written and when this exact
        # wording was accepted; this screen showed neither, so a reader could not
        # tell today's card from a fortnight-old one. Two separate keys, added only
        # when the fact exists: a row for a card with no acceptance keeps exactly
        # the bytes it had.
        row.update(self.time_basis(state["id"], state))
        return row

    def derivation(self, candidate_id: str) -> str | None:
        """The card the *program* recorded this one being written out of, or None.

        The relation type alone is not the evidence. `derived_from` means "a discussion
        held that card when this one was written", and only `add()` can make that true —
        it writes the edge into the card's own state in the same transaction and records
        it on the `add` event. A library can still hold a `derived_from` row typed by
        hand through `link` on an older build, and the supervisor measured exactly that:
        two confirmed cards joined by hand, and the reader screen announced a discussion
        that never happened (`/var/tmp/dojo-lineage-provenance.3dtLjtD6`).

        So this reads the ledger, which is where "the program did it" is recorded, and
        the screens say "库里记下的关系" rather than "讨论里写下的" when it is absent.
        """
        try:
            events = self.history(candidate_id)["events"]
        except DojoError:
            return None
        for event in events:
            if event.get("event") != "add":
                continue
            # `history` nests the row's payload under `details`; reading the key off the
            # event itself returned None for every real card, and the first version of
            # this method then told a genuinely discussed card it was a hand-written
            # relation (caught by `.scratch/3490/repro.py`, scene C).
            details = event.get("details") if isinstance(event.get("details"), dict) else {}
            value = details.get("derived_from")
            if isinstance(value, str) and value.strip():
                return value
        return None

    def derivations(
        self, candidate_ids: list[str] | None = None,
    ) -> dict[str, str]:
        """`derivation` for many cards in one query, so a screen is not one read per row.

        The same reason `later_versions` takes the states it was handed: `derivation`
        per row is a full event-log read per result, which is the defect the supervisor
        measured on the reverse lookup (601 candidate reads for one search). This reads
        the `add` rows once and keeps the ones carrying a `derived_from`.

        Passing ids narrows it; passing none answers for the whole library, which is what
        the screen wants. A card absent from the result has no recorded derivation -- the
        distinction from "the library has no events" is `history`, not this.
        """
        sql = ("SELECT candidate_id, details_json FROM events WHERE event='add' "
               "AND details_json LIKE '%\"derived_from\"%'")
        params: tuple[Any, ...] = ()
        if candidate_ids is not None:
            ids = [_id(value) for value in candidate_ids]
            if not ids:
                return {}
            sql += " AND candidate_id IN (" + ",".join("?" for _ in ids) + ")"
            params = tuple(ids)
        found: dict[str, str] = {}
        for row in self.connection.execute(sql + " ORDER BY seq", params):
            try:
                details = json.loads(row["details_json"])
            except (TypeError, json.JSONDecodeError):
                continue
            value = details.get("derived_from") if isinstance(details, dict) else None
            if isinstance(value, str) and value.strip():
                found[row["candidate_id"]] = value
        return found

    @staticmethod
    def derivation_index(states: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        """Resolved target id -> the cards whose state says they came out of it, built once.

        `later_versions` used to walk every card's relations on every call, and the reading
        screen calls it once per result row: 2400 cards x 2400 states turned one search
        into an O(n^2) scan (11.7 million dict lookups, measured with cProfile on the
        supervisor's `fixture-2400`). The per-call `state_json` reads were already gone;
        this is the same defect one layer in, and an index built once per screen removes
        it. Redirected cards are skipped here, as they were there.

        A target that was later merged away is not rewritten in the card's own state (the
        edge is history), so the redirect is followed **here, in memory**, and the entry is
        filed under the card that survived. Resolving through the database per edge was the
        third shape of the same defect: the supervisor's first two reproducers measured a
        full table read and a full state walk per row, and `later_versions` used to add two
        more queries per edge-bearing card (`resolve`, plus `history` for the basis) -- fine
        on the hand-tended libraries this slice was measured on, quadratic on a library that
        actually holds many edges. One pass over the states now answers all of it.
        """
        by_id = {state.get("id"): state for state in states if isinstance(state.get("id"), str)}

        def survivor(identifier: str) -> str:
            seen: set[str] = set()
            current = identifier
            while current in by_id and current not in seen:
                seen.add(current)
                target = by_id[current].get("redirect_to")
                if not isinstance(target, str) or not target:
                    return current
                current = target
            return current

        index: dict[str, list[dict[str, Any]]] = {}
        for state in states:
            if state.get("redirect_to"):
                continue
            for relation in state.get("relations") or []:
                if not isinstance(relation, dict) or relation.get("type") != "derived_from":
                    continue
                target = relation.get("target")
                if isinstance(target, str) and target:
                    index.setdefault(survivor(target), []).append(state)
                    break
        return index

    def later_versions(
        self, candidate_id: str, *, states: list[dict[str, Any]] | None = None,
        index: dict[str, list[dict[str, Any]]] | None = None,
        derivations: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """Cards the ledger records as written out of a discussion that held this one.

        The reverse of the `derived_from` edge, and the half a reader needs when the card
        he is looking at stopped being the newest thing said about it: `search` printed
        two nearly identical cards side by side and neither said the second came out of a
        session holding the first (measured in `.scratch/3490/walk.py`, scene C).

        Read from card states, because relations live inside the card state and a relation
        index on disk would be a second copy of the same fact. Two rounds of the
        supervisor's measurements shaped this:

          * reading the table per row took a 600-card search from ~63 ms to ~636 ms -- 601
            full reads over a library holding no such edge
            (`/var/tmp/dojo-search-lineage-scale.WmglSP`);
          * passing the loaded states fixed the reads and left an O(n^2) walk -- 2400 cards
            x 2400 states, 217 ms -> 513 ms, still with no edge in the library
            (`/var/tmp/dojo-lineage-recheck.7JZ7o6YE`).

        So a screen builds `derivation_index(states)` once and passes `index`; this method
        then touches neither the table nor the other cards. Called without either, it
        falls back to reading and walking, which is what a one-off caller wants.

        Only what is stored: the id, that card's own wording, its status, and whether the
        library holds an acceptance record for *that* wording. Which way the sentence
        changed is not recorded, so it is not said.
        """
        target = _id(candidate_id)
        found: list[dict[str, Any]] = []
        if index is not None:
            # The caller built the map; nothing is walked.
            candidates = list(index.get(target) or [])
        else:
            # Asked without either, read the table. This is the fallback a one-off caller
            # gets, and it is also the shape the supervisor's first reproducer measured:
            # called once per row, it turns one search into 301/601 full reads.
            #
            # No index and no list is a caller error, not a database error: the reading
            # screen guards against it with `self._reading_scan` (see `retrieve`), but a
            # library that never took a snapshot must not make a screen crash. An empty
            # answer there is honest -- nothing was drawn from anything -- and it is what
            # lets a red arm restore the per-row read without turning the run into a
            # traceback that fails every reading for an unrelated reason.
            if states is None and index is None and getattr(self, "_reading_scan", False):
                return []
            if not states:
                states = [json.loads(row["state_json"]) for row in
                          self.connection.execute("SELECT state_json FROM candidates ORDER BY id").fetchall()]
            candidates = states
        for state in candidates:
            if state.get("redirect_to"):
                continue
            for relation in state.get("relations") or []:
                if not isinstance(relation, dict) or relation.get("type") != "derived_from":
                    continue
                # With an index the entry is already filed under the surviving target; only
                # the fallback has to resolve, because only the fallback reads raw states.
                if index is None and self.resolve(relation.get("target"))[0]["id"] != target:
                    continue
                # `basis` is the fact the sentence on screen has to hang on: the
                # ledger's add row says the program wrote this edge, or it does not.
                # A hand-typed relation is still a relation, and still shown -- but as
                # what it is, not as a discussion.
                if len(found) >= SCREEN_LATER:
                    # Counted, not read: the `time_basis` cost is per listed card, and the
                    # caller prints the remainder as a number.
                    found.append({"id": state["id"], "statement": state.get("statement"),
                                  "status": state.get("status"), "version": state.get("version"),
                                  "counted_only": True})
                    continue
                found.append({
                    "id": state["id"],
                    "statement": state.get("statement"),
                    "status": state.get("status"),
                    "version": state.get("version"),
                    "sources": state.get("sources") or [],
                    "acceptance": self.time_basis(state["id"], state),
                    # The caller's one-query map when it has one; `derivation` (a full event
                    # read for this card) only when it does not.
                    "basis": ("discussion"
                              if (derivations.get(state["id"]) if derivations is not None
                                  else self.derivation(state["id"])) == target
                              else "recorded_relation"),
                })
                break
        return found

    def _matched_wording(self, state: dict[str, Any], found: set[str]) -> dict[str, Any]:
        """Which of this card's wordings the query actually overlapped.

        A card that was rewritten keeps its earlier sentence in the ledger, and #3436
        measured that searching for the sentence he remembers returned nothing at all.
        So the earlier wordings are searched too -- and, when one of them is what
        matched, the row says which sentence and that it is not what the card says now.

        `matched_in` says *which part of the card* the words came from, because the
        match runs over all of it at once: the sentence, its aliases, its premises, its
        conditions, its counterexamples and its source claims. #3436's second round
        measured what saying only `matched_on: current` costs, two ways:

          outside  a card saying "值班通知交系统跑。" whose *scope line* was the whole
                   searched phrase. The entry read "对上 8 个词：会当、场损…" over an
                   unrelated quoted sentence, and nothing said the words were in the
                   condition printed two lines below.
          alias    a card matched only through an `alias` shared 5 bigrams with the
                   query while its sentence shared 0. `matched_on` came back `current`,
                   so the screen printed no note at all -- i.e. "this is what the card
                   says".

        The values are names of stored fields, never prose; what a reader is told is
        the screen's decision, and the model-facing call does not ask for this key.
        """
        # The statement alone, not `wording_text`: an alias is a *different* wording of
        # the same claim, and folding the two together would report the measured
        # alias-only match as "the sentence matched", which is exactly the defect.
        in_sentence = bool(found & lexical_terms(statement_text(state)))
        in_aliases = bool(found & lexical_terms(aliases_text(state)))
        in_limits = bool(found & lexical_terms(limits_text(state)))
        in_sources = bool(found & lexical_terms(sources_text(state)))
        # The words may be his own answer rather than any wording of the card. Reported
        # separately because it answers a different question: "this is the card whose
        # story I told", not "this is the sentence I remember".
        in_answers = bool(found & lexical_terms(
            " ".join(str(item.get("answer", ""))
                     for item in self.card_answers(state["id"]).values())
        ))
        matched_in: list[str] = []
        if in_sentence:
            matched_in.append("sentence")
        if in_aliases:
            matched_in.append("alias")
        if in_limits:
            matched_in.append("limits")
        if in_sources:
            matched_in.append("sources")
        if in_answers:
            matched_in.append("answers")
        # `candidate_text` is the whole card, so it is the honest answer to "did the
        # query overlap this card's own current text" -- which is what `matched_on`
        # has always meant and what the rewrite note keys on.
        on_current = bool(found & lexical_terms(candidate_text(state)))
        earlier_hit = None
        history = (() if is_discussion_material(state)
                   else earlier_wordings(state, self._acquisition_events(state["id"])))
        for earlier in history:
            if found & lexical_terms(earlier):
                earlier_hit = earlier
                break
        if earlier_hit is not None:
            matched_in.append("earlier")
        payload: dict[str, Any] = {"matched_on": "current", "matched_in": matched_in}
        if earlier_hit is None:
            return payload
        # Both ends are reported when both matched, because the two facts answer two
        # different questions: "is this the card I mean" and "did it change under me".
        # Saying only `current` here hid the second on a rewritten card whose new
        # sentence shares most of its words with the old one -- measured on the walk
        # library, where the remembered sentence and the current one overlapped on
        # 5 bigrams and the screen then showed no sign of the change.
        payload.update({
            "matched_on": "current_and_earlier" if on_current else "earlier",
            "matched_wording": earlier_hit,
        })
        return payload

    def broadcast(self, query: str, limit: int = 10, exclude_session: str | None = None) -> dict[str, Any]:
        """Retrieval as cross-session broadcasting uses it: what other sessions arrived at.

        Two exclusions, both reported rather than dropped: a card that arrived over
        the network as a raw list is not what the facilitator may say, and a card
        resting on one discussion session is that session's word, not a second
        stranger's compatible or opposing claim. Independence is reported per result
        and is not used to reorder relevance.
        """
        query = str(query or "").strip()
        if limit < 1 or limit > 100:
            raise DojoError("limit must be between 1 and 100")
        terms = lexical_terms(query, query=True)
        method = (
            "transparent lexical overlap (distinct query terms only) over cross-session material; "
            "independence is reported per result and is not a relevance or truth ranking"
        )
        if not terms:
            return {"query": query, "method": method, "matched_terms": [], "results": [], "suppressed": []}
        results = []
        suppressed = []
        for score, found, state, _withheld in self._matches(terms):
            info = independence(state, self._acquisition_events(state["id"]))
            reason = None
            if exclude_session is not None and exclude_session in info["provenance_groups"]:
                reason = "written by the session asking: a session does not broadcast its own word back"
            elif info["single_session"]:
                reason = "single-session provenance: the card's whole provenance is the one session that wrote it"
            if reason is not None:
                suppressed.append({"id": state["id"], "reason": reason})
                continue
            if len(results) >= limit:
                continue
            results.append({
                "id": state["id"],
                "version": state["version"],
                "status": state["status"],
                "statement": state["statement"],
                "kind": state["kind"],
                "score": score,
                "matched_terms": sorted(found),
                "scope": state.get("scope", []),
                "premises": state.get("premises", []),
                "alternatives": state.get("alternatives", []),
                "contradictions": state.get("contradictions", []),
                "unknowns": state.get("unknowns", []),
                "sources": state.get("sources", []),
                "independence": info,
            })
            # r1721: `broadcast` is `search`'s other exit and it dropped the same two
            # facts `search` carries, so a reader who crossed sessions could not say
            # when the wording was written or accepted. Added by value, only when the
            # ledger has the record: a row for a card with no acceptance keeps exactly
            # the bytes it had (the same rule `retrieve` uses).
            results[-1].update(self.time_basis(state["id"], state))
            # #1801: same gap on `search`'s other exit -- the row carried the wording's
            # date and nothing about when each source behind it arrived. Added by the
            # same rule as `time_basis`: only when the ledger pins an entry time, so a
            # row for a card whose sources cannot be dated keeps the bytes it had.
            provenance = self.source_basis(state["id"], state)
            if provenance:
                results[-1]["source_basis"] = provenance
            # #1929: same gap on this exit. Added by the same rule.
            results[-1].update(self.revision_basis(state["id"], state))
            # #1774: a reader of this row saw `independence_groups=2 | independent=true`
            # and read "two people". #1763 measured that the ledger cannot support that
            # reading: an echo and an independent second arrival write identical
            # provenance. The row now states the counts and names what they count; the
            # `independence` block above keeps every byte it had, because the values it
            # reports are unchanged and callers pin them. Only rows that declare two or
            # more group names get the key -- one group name is not a shape anyone reads
            # as two people, and those rows keep exactly the bytes they had.
            # No session is passed: this row's reader is whoever is asking, and the
            # `--session` this call receives names a *writer* to exclude.
            reading = self.provenance_reading(state["id"])
            if reading["readable"]:
                results[-1]["provenance_reading"] = reading
        return {
            "query": query,
            "method": method,
            "matched_terms": sorted(terms),
            "results": results,
            "suppressed": suppressed,
        }

    def export_prompt(self, mode: str, ids: list[str], budget_chars: int, export_dir: str | Path) -> dict[str, Any]:
        if mode not in {"b", "c"}:
            raise DojoError("export mode must be b or c")
        if budget_chars < 100:
            raise DojoError("character budget must be at least 100")
        if mode == "b" and ids:
            raise DojoError("B export is seed-free; do not provide IDs")
        if mode == "c" and not ids:
            raise DojoError("C export requires explicitly selected candidate IDs")
        if len(set(ids)) != len(ids):
            raise DojoError("candidate IDs in an export must be unique")
        target_message = (
            "我在做一个小工具，经常先写代码、后来才发现需求没想清楚，返工很多。我在考虑强迫自己每次先写完整需求文档。"
            "目前没有数据说明哪种做法更有效，也不知道这条路线的效果。别假定我没说过的条件。"
        )
        excerpts = []
        for candidate_id in ids:
            state, _ = self.resolve(candidate_id)
            if state["status"] != "discussable" or state.get("redirect_to"):
                raise DojoError(f"selected candidate is not currently discussable: {candidate_id}")
            info = independence(state, self._acquisition_events(state["id"]))
            if info["single_session"]:
                raise DojoError(
                    f"single-session provenance cannot be exported as cross-session material: {candidate_id}"
                )
            excerpts.append((state, info))
        lines = [
            "This is a simulated decision exercise, not verified evidence.",
            "Distinguish supplied facts, opinions, assumptions, conflicts, and unknowns. Do not invent probabilities or treat discussability as truth.",
            "Keep the delivery constraint visible. Cite source IDs for any selected excerpt used; state when evidence is absent.",
            "",
            "Target case:",
            target_message,
        ]
        if mode == "c":
            lines.extend(["", "Explicitly selected dojo excerpts (not an answer key):"])
            # r117: every excerpt header below prints `independence_groups=N |
            # independent=...`, and nothing in the file said what N counts. #1831d: N is
            # now the provenance count the verdict used (`provenance_groups`), not the
            # named groups alone; the named groups are `named_groups`. The gate refuses only single-session provenance, so a card
            # marked `independent=false` still ships. Appended as its own line, after
            # the existing heading, so every other line keeps its exact bytes and its
            # order -- the same reason r114/r115 appended. Mode b has no excerpts, so
            # it gets no such line: there would be nothing here for it to describe.
            lines.append(
                "Independence in the headers below is self-declared, not verified: independence_groups "
                "counts the provenance entries the verdict was computed from -- a named group, or the "
                "session that brought a source naming none -- so two entries can come from one person, "
                "and one material logged two ways can count twice. The only provenance refused here is "
                "single-session (one session's word standing alone), so a card marked independent=false "
                "can still appear."
            )
            for state, info in excerpts:
                header = (
                    f"\n[{state['id']} v{state['version']} | {state['kind']} | status={state['status']}"
                    f" | independence_groups={len(info['independence_groups'])}"
                    f" | independent={str(info['independent']).lower()}]"
                )
                # r115: the participant receiving this prompt had no way to tell a
                # conclusion reached today from one reached a fortnight ago, though the
                # ledger holds both times. Appended *inside* the closing bracket and
                # only when the ledger has the record, so the bytes every other reader
                # matches on (up to `independent=`) are unchanged.
                basis = self.time_basis(state["id"], state)
                # r1627: `accepted_at` alone cannot tell a reader whether the agreement
                # happened in the conversation or was copied out of a trace file later --
                # the backfilled one dates the copy, and the copy can be weeks after. The
                # route is already in the ledger (`details.path`), so it is appended as
                # one more field inside the same bracket; every byte before it is
                # unchanged and no line is reordered. Omitted when the ledger has no
                # path, so an old acceptance keeps exactly the header it had.
                if basis:
                    header = header[:-1] + "".join(
                        f" | {key}={basis[key]}"
                        for key in HEADER_TIME_FIELDS
                        if key in basis
                    ) + "]"
                lines.append(header)
                lines.append(state["statement"])
                for key in ("premises", "scope", "alternatives", "contradictions", "unknowns"):
                    values = state.get(key, [])
                    if values:
                        lines.append(f"{key}: " + " | ".join(values))
                if state.get("sources"):
                    lines.append("sources:")
                    # #1801: this is the exit a real downstream reads -- the frozen
                    # prompt handed to whoever is asked to weigh the card. Every other
                    # time field in this header dates the wording; not one of them said
                    # when the evidence behind it arrived, so a participant could not
                    # say whether a source predates the claim it is offered for. Read
                    # once per card, and used only for ids the ledger really pins.
                    basis = self.source_basis(state["id"], state)
                    entries = basis.get("sources", {})
                    for source in state["sources"]:
                        line = (
                            f"- {source['id']} | {source['type']} | verification={source['verification']} "
                            f"| independence_group={source['independence_group']} | {source['claim']}"
                        )
                        # r114: `scope_note` is the one field that says how far this
                        # source reaches ("仅此一次，未复测", "两次都在同一团队"). The
                        # export dropped it, so the participant handed the frozen prompt
                        # got five of six fields -- all the provenance, none of the
                        # caveat that bounds it. Appended, not reordered: the prefix
                        # bytes other readers match on are unchanged. Omitted rather
                        # than printed empty when the card has no note, so a blank stub
                        # never reads as "no caveat needed".
                        if source.get("scope_note"):
                            line += f" | scope_note: {source['scope_note']}"
                        # Appended after every existing field, never reordered, so the
                        # prefix other readers match on keeps its bytes. Omitted when the
                        # ledger cannot pin the entry: a `entered_at=<card date>` here
                        # would be the substitution this whole field exists to avoid.
                        entry = entries.get(source["id"])
                        if entry:
                            line += f" | entered_at: {entry['entered_at']}"
                            if entry.get("entered_on"):
                                line += f" | entered_on: {entry['entered_on']}"
                        lines.append(line)
                    # #1929: dropping the field is honest about the value but silent
                    # about the fact. A reader of a six-line block cannot tell "this
                    # source has no entry time" from "this row never had that field",
                    # and the question this header exists to answer is exactly which
                    # evidence can be dated. So the undated ids are named, once, in a
                    # line of their own -- appended after the block so every byte a
                    # reader matches on keeps its place.
                    if basis.get("undetermined_source_ids"):
                        lines.append(
                            "sources_undated: " + ", ".join(basis["undetermined_source_ids"])
                            + " | 这个库的账本里没有这些来源的入库记录；不是省略，是它真的说不出。"
                        )
                # #1929: a participant was handed a narrowed claim with a counterexample
                # beside it and nothing saying the narrowing had happened or why. The
                # ledger held `from_statement` and `reason`; this file printed neither.
                # Appended after the block, in prose, so every byte above keeps its place
                # and a reader who never opens `show --history` still finds out. Omitted
                # for a card he never revised, so those exports keep their exact bytes.
                revision = self.revision_basis(state["id"], state).get("revision_basis")
                if revision:
                    if revision.get("left_wording"):
                        lines.append(
                            "revision_left_wording: " + revision["left_wording"]
                            # "这句是他后来改掉的" named an author the `revise` row does
                            # not store (a reader or a script can revise a card too), and
                            # it named a direction the row does not record either. The
                            # row records that this wording replaced that one, and why.
                            + " | 库里记着现在的说法换掉的是这一句；不是现在的说法。"
                        )
                    lines.append(
                        "revision_reason: " + revision["reason"]
                        + " | 库里记下的改动理由；不是对现在这句的赞同，也不证明它成立。"
                    )
                if state.get("relations"):
                    lines.append("relations: " + " | ".join(
                        f"{item['type']}:{item['target']} ({item['note']})" for item in state["relations"]
                    ))
        lines.extend(["", "Respond with a bounded analysis and explicit remaining unknowns."])
        prompt = "\n".join(lines).strip() + "\n"
        if len(prompt) > budget_chars:
            raise DojoError(f"export would exceed character budget: {len(prompt)} > {budget_chars}; nothing written")
        directory = Path(export_dir).expanduser()
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        name = f"dojo-{mode}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}.txt"
        path = directory / name
        with path.open("x", encoding="utf-8") as stream:
            stream.write(prompt)
        try:
            path.chmod(0o600)
        except OSError:
            pass
        return {"path": str(path), "mode": mode.upper(), "source_candidate_ids": [state["id"] for state, _info in excerpts], "characters": len(prompt), "budget_chars": budget_chars}


def lexical_terms(text: str, *, query: bool = False) -> set[str]:
    """Return inspectable Latin tokens; multi-character CJK queries use bigrams to reduce noise."""
    lowered = text.casefold()
    terms = set(re.findall(r"[a-z0-9]+(?:[._-][a-z0-9]+)*", lowered))
    for run in re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+", lowered):
        if not query or len(run) == 1:
            terms.update(run)
        terms.update(run[index:index + 2] for index in range(len(run) - 1))
    return terms


NEGATIONS = ("不", "无", "未", "非", "不能")
CONTENT_FIELDS = ("premises", "scope", "alternatives", "contradictions", "unknowns")


def normalize_wording(value: str) -> str:
    """Compare wording without letting spacing or punctuation decide."""
    return re.sub(r"[\s\W_]+", "", value.casefold())


def wording_equivalent(first: str, second: str) -> bool:
    """Same claim said differently, with a negation flip treated as a different claim."""
    first_normalized = normalize_wording(first)
    second_normalized = normalize_wording(second)
    if first_normalized == second_normalized:
        return True
    if {word for word in NEGATIONS if word in first_normalized} != {
        word for word in NEGATIONS if word in second_normalized
    }:
        return False
    return SequenceMatcher(None, first_normalized, second_normalized).ratio() >= 0.92


def content_key(statement: str, kind: str, fields: dict[str, list[str]]) -> str:
    """Identity of what a card says, ignoring wording spacing and list order.

    Sources and sessions are excluded on purpose: the same claim reached twice is
    the same claim, and reaching it twice is provenance, not a second card.
    """
    def normalized(value: str) -> str:
        return " ".join(str(value).split())

    return _json({
        "statement": normalized(statement),
        "kind": kind,
        **{field: sorted(normalized(value) for value in fields.get(field, [])) for field in CONTENT_FIELDS},
    })


def is_discussion_material(state: dict[str, Any]) -> bool:
    """Discussion provenance also survives source attachment or a wording revision."""
    return is_unaccepted_draft(state) or any(
        re.fullmatch(r"discuss-[0-9a-f]{32}", str(source.get("independence_group") or ""))
        for source in state.get("sources", [])
    )


def is_unaccepted_draft(state: dict[str, Any]) -> bool:
    """Whether this card's whole provenance is an unaccepted model-written wording.

    One source, and the model wrote it: no session put its word behind this version,
    so nothing here is a conclusion. The condition is the card's *shape*, not one
    verification value -- a model-written wording that was never independently
    checked is equally unaccepted whether it is filed as `unverified` or as
    `not_evidence`, and testing for either one would only pin the label r110 happens
    to write today. `accept_draft` rewrites that one source's type to `unknown`,
    which is why the same card stops matching once the user accepts the wording.
    Confirmation is deliberately not part of this predicate -- being marked
    discussable says nothing about who agreed to the sentence. (Written after a
    mutant showed the extra `verification == "unverified"` conjunct carried no test
    weight; it was narrow for the wrong reason and is gone.)
    """
    sources = list(state.get("sources", []))
    if len(sources) != 1:
        return False
    return sources[0].get("type") == "model_generated"


ACCEPTANCE_EVENT = "wording_accepted"
# A repeated request whose effect was already stored writes `<event>.repeat` and names the
# event it repeats. The version does not move: a repeat must not read as a second action,
# and `pipeline_marks` compares against versions, so moving one would make finished work
# pending again. The row exists so a later reader can tell a replay from a real second
# action -- RFC 9110 section 9.2.2 permits logging each request, not blurring them.
#
# "The same request" is decided by what was asked for, not by the state it produced:
# revising to the same sentence for a new reason leaves the card in the same state and is
# still a new fact, so it is written as its own event (version unchanged, `effect`
# `unchanged`) with no `repeat_of`. "Asked for" is the whole ask: for `revise` that is the
# reason *and* `to_statement`. Comparing only the reason filed a request for a second
# target under the first one that shared its reason. See `_same_request`.
REPEAT_EVENT_SUFFIX = ".repeat"
# There is deliberately no "which keys to ignore" set here any more. It existed for
# one round and was wrong twice: each fix meant adding one more key, because the
# subtraction itself was the bug. Writers now store their whole ask under `request`
# and `_same_request` compares those objects; bookkeeping stays in the sibling keys
# where it cannot be mistaken for intent.
# version -- refusing to do something must not look like doing it -- but it does leave a
# row, so `dojo events --id` can show that the rule fired and on which two cards, instead
# of the command failing with only a message nobody kept.
MERGE_REFUSED_EVENT = "merge_refused"
# Where `_merged_target` leaves the content fields the union would change, between being
# computed and being decided on. Stripped before any write; never persisted.
MERGED_CHANGED_FIELDS = "_merge_changed_content_fields"
# Which field in an acceptance event's details holds the identity of the wording that
# was accepted. Named once so the writer and the reader cannot drift apart -- they did:
# the writer used `draft_accepted` as the event name and the reader matched on the name,
# so `accept_draft`'s acceptance was only found because a SQL query happened to include
# the old name in its IN-list.
DIGEST_FIELD = "statement_digest"
# Which field names the *card* the acceptance was given for. The digest above answers
# "is this the same sentence"; this answers "is this the card". They are different
# questions and only both together are an acceptance: two cards can hold identical
# wording, so a digest alone lets one card's acceptance be read onto the other. The
# digest is therefore a check on an acceptance, not a way to move it between cards.
# Events written before this field existed carry no card identity of their own; for
# those the ledger row (`events.candidate_id`) is the binding and nothing is rewritten.
CARD_FIELD = "candidate_id"
# When the agreement happened, as the accepting caller knew it -- distinct from
# `events.created_at`, which is when the row was written. A backfilled acceptance can be
# weeks later than the agreement it records. Absent on events written before r1638 and
# on acceptances whose caller had no moment to give; absent means "not stated", and the
# export then prints only the record time rather than inventing this one.
AGREED_AT_FIELD = "agreed_at"
# #1801: the two events that create a card together with its sources. A source found on
# version 1 of a card written by one of these entered the library at that event's time.
SOURCE_CREATING_EVENTS = ("add", "load_simulated_seed")


def _dated(when: Any, kind: str, card: str) -> tuple[str, str, str] | None:
    """An entry time the ledger really holds, or None -- never an empty stand-in.

    #1929: every surface prints `entered_at: {value}` and drops the field only when
    the ledger has no entry. A row whose `created_at` is empty (a hand-edited library,
    an import that dropped the column) is *not* an entry: printing `entered_at: ` with
    nothing after it reads as "this source was dated, the date is over there", which is
    the opposite of what the library knows. Such a source is undetermined instead.
    """
    if not isinstance(when, str) or not when.strip():
        return None
    return (when, kind, card)


# The order these appear in an export header, after `independent=`. Appended, never
# interleaved: a reader matching the bytes up to an earlier field keeps matching. Each
# is omitted when the ledger has no such record, so an old card's header is unchanged.
HEADER_TIME_FIELDS = ("versioned_at", "accepted_at", "acceptance_path", "agreed_at")
# Event names that have meant "a user accepted this wording". `accept_draft` writes
# `draft_accepted`; the conversation path writes ACCEPTANCE_EVENT. An older library
# has only the first, and it is what the snapshot fallback has to recognise.
LEGACY_ACCEPTANCE_EVENTS = frozenset({"draft_accepted", ACCEPTANCE_EVENT})


def is_accepted_conclusion(
    state: dict[str, Any],
    accepts: list[dict[str, Any]] | None = None,
    snapshot_digest: Callable[[int], str | None] | None = None,
) -> bool:
    """Whether anyone actually accepted this wording -- read from the event ledger.

    r112b (this version) replaced a shape test. The shape test said yes to any card
    with one non-`model_generated` source whose group was one of its sessions; but
    `dojo add --source-json` writes exactly that shape by hand, so a card nobody had
    accepted was retrivable as an accepted conclusion. A predicate that cannot tell
    "accepted" from "written that way" is not evidence of acceptance.

    So acceptance is now an *action*, recorded as a `wording_accepted` event by the two
    places where a user accepts a wording, and this reads that event. No event, no
    answer: fail-closed, including for every card written before this version (those
    carry no such event, so they stay out of retrieval exactly as they were before B).

    `accepts` is passed explicitly rather than fetched here so this function stays
    pure; `Store._acquisition_events` supplies it. `None` means "the caller did not
    supply the ledger" and returns False -- not "looks fine".

    r112d: an acceptance recorded *before* the digest existed still names the version
    it was given for, and the `snapshots` table holds that version's wording. So the
    identity is recoverable by reading the snapshot and hashing it with the same
    normalization -- read only, nothing written back into the old event. Without this,
    a library written by an earlier version had every acceptance permanently
    unmatched, which discarded real evidence: an accepted, never-touched card is not
    the same thing as a card nobody accepted.

    `snapshot_digest` is that lookup, supplied by the Store because this function does
    no I/O. It returns None when the snapshot is absent, and the event then counts for
    nothing -- fail-closed, as before, but now counted by `Store.audit_acceptances`
    instead of disappearing.
    """
    if not accepts:
        return False
    wanted = wording_digest(state)
    card_id = state.get("id")
    for event in accepts:
        digest = _accepted_wording_digest(event, snapshot_digest, card_id)
        if digest and digest == wanted:
            return True
    return False


def _accepted_wording_digest(
    event: dict[str, Any], snapshot_digest: Callable[[int], str | None] | None = None,
    candidate_id: str | None = None,
) -> str | None:
    """Which wording an acceptance event speaks for, or None if it speaks for none.

    Written by this version: the digest is on the event. Written before it: the event
    carries only the `version` its write produced, so the wording is read from that
    version's snapshot.

    The fallback is gated on the event *being* an acceptance first. Every versioned
    event carries a `version`, so without that gate a `revise` or `confirm` event would
    have its own new wording hashed and read back as an acceptance of itself -- the
    false positive this binding exists to prevent, under a different name. A `revise`
    event's snapshot is the *rewritten* wording, so it would match today's card exactly.
    """
    if not _is_acceptance_event(event):
        return None
    details = event.get("details") or {}
    # The event's own card identity, when it has one, must be the card being asked
    # about. A digest match is a check on an acceptance, so an event that names a
    # different card proves nothing here however well its wording matches -- that is
    # the case where two cards hold the same sentence and one was accepted. Events
    # written before the field existed have only their ledger row, which the caller
    # already scoped to this card; they are read exactly as before.
    if _acceptance_names_another_card(event, candidate_id):
        return None
    digest = details.get(DIGEST_FIELD)
    if digest:
        return digest
    version = details.get("version")
    if not isinstance(version, int) or snapshot_digest is None:
        return None
    return snapshot_digest(version)


def _acceptance_names_another_card(event: dict[str, Any], candidate_id: str | None) -> bool:
    """Whether this acceptance says, in its own details, that it belongs to another card.

    Absent field means the event was written before the binding existed, and then the
    ledger row is the only identity there is -- not a disagreement. A named card that
    differs from the one asked about is a refusal: the case that byte comparison of
    wording cannot detect, because the wording is identical on both cards. A named card
    with nothing to compare it to is also a refusal -- unverifiable is not agreement.
    """
    owner = (event.get("details") or {}).get(CARD_FIELD)
    if owner is None:
        return False
    # No card to compare against is not agreement. An event that names a card can only
    # be checked against the card being asked about; without one there is nothing to
    # check it against, and reading that as "fine" was the same fail-open this function
    # was written to remove (an unnamed state would accept any card's named acceptance).
    return candidate_id is None or owner != candidate_id


def _is_acceptance_event(event: dict[str, Any]) -> bool:
    """Whether this ledger row records a user accepting a wording.

    Two spellings, because the two routes wrote different ones: `accept_draft` writes
    the `draft_accepted` name, the conversation path writes `ACCEPTANCE_EVENT` plus the
    marker field. An older library has only the first.
    """
    details = event.get("details") or {}
    return bool(details.get(ACCEPTANCE_EVENT)) or event.get("event") in LEGACY_ACCEPTANCE_EVENTS


def wording_digest(state: dict[str, Any]) -> str:
    """Identity of the wording this card holds now.

    Content, not `version`: a version bump for something that does not touch the
    sentence (an alias, a relation) must not invalidate an acceptance, and a revision
    that restores the same text must be accepted again by the same identity. It is the
    same normalization duplicates use, so "the same wording" means one thing here.
    """
    return hashlib.sha256(
        content_key(state.get("statement", ""), state.get("kind", ""), state).encode("utf-8")
    ).hexdigest()


def _summarize_incoming_links(links: list[dict[str, Any]], current: dict[str, Any]) -> dict[str, Any]:
    # Group from the recorded source snapshots, never the live card or session ID.
    # One link may have multiple declared groups and an unidentified source at once.
    by_version: dict[int | None, dict[str, Any]] = {}
    all_groups = set()
    for link in links:
        seq, target = link["sequence"], link["target"]
        version = target["version"]
        bucket = by_version.setdefault(version, {
            "target_version": version,
            "is_current": (target["id"] == current["id"] and version == current["version"]
                           and "statement" in target),
            "declared_groups": {}, "unknown_group_link_sequences": [], "relations": {},
        })
        bucket["relations"].setdefault(link["relation"], []).append(seq)
        sources = link["source"].get("sources", [])
        known = set()
        unknown = not sources
        for source in sources:
            group = source.get("independence_group")
            if isinstance(group, str) and group.strip() and group != "unknown":
                known.add(group)
            else:
                unknown = True
        if unknown:
            bucket["unknown_group_link_sequences"].append(seq)
        all_groups.update(known)
        for group in sorted(known):
            bucket["declared_groups"].setdefault(group, []).append(seq)

    return {
        "declared_group_count": len(all_groups),
        "by_target_version": [
            {**bucket, "declared_groups": [
                {"group": group, "link_sequences": seqs}
                for group, seqs in bucket["declared_groups"].items()
            ]}
            for bucket in by_version.values()
        ],
    }


def _same_provenance(
    existing: dict[str, Any], candidate: dict[str, Any], session: str | None,
    state: dict[str, Any], events: list[dict[str, Any]],
) -> bool:
    """Is `candidate` the same provenance the card already carries through `existing`?

    Three ways, and they are the ones the libraries distinguish and the published
    tests pin:

      * **the same source object** (id, type, claim, group, verification). A replay
        of the request, not a second arrival;
      * **a named group the card already carries.** Independence is counted per
        group, so a second source naming that group adds nothing. This is what
        `test_attaching_the_same_session_twice_is_a_no_op` pins, and it holds even
        when the two sources arrive under one session;
      * **a group-less source the same session already handed over.** A group-less
        source has no key of its own, so the acquiring session is the only key there
        is -- which is why two sessions with group-less sources are two provenance
        (`test_a_group_less_source_attached_by_two_sessions_is_two_provenances`), and
        why replaying one of them changes nothing.

    This is deliberately a predicate about one source. The previous version asked
    `independence()` about the whole card with the candidate spliced in, which
    counted the candidate twice (once from `state`, once from a synthetic event) and
    reported provenance that did not exist.
    """
    keys = ("id", "type", "claim", "independence_group", "verification")
    if all(existing.get(key) == candidate.get(key) for key in keys):
        return True
    # `"unknown"` is what a caller who names no group writes, so it is not a name:
    # treating it as one made two group-less sources look like one provenance.
    named = candidate.get("independence_group")
    if named and named != "unknown":
        return existing.get("independence_group") == named
    if not session:
        return False
    return session in _acquired_by(state, events, existing.get("id"))


def _acquired_by(
    state: dict[str, Any], events: list[dict[str, Any]], source_id: str | None,
) -> set[str]:
    """Sessions that handed over `source_id`.

    Read from the `attach_source` events, with the card's own writing session as the
    fallback `independence()` also uses: on a card the `add` call wrote in one
    session, that is the only answer available.
    """
    acquirers = {
        (event.get("details") or {}).get("session")
        for event in events
        if (event.get("details") or {}).get("source") == source_id
    }
    acquirers.discard(None)
    if not acquirers and len(state.get("sessions") or []) == 1:
        acquirers = set(state["sessions"])
    return acquirers


def independence(state: dict[str, Any], events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """What a card's provenance supports, computed from its sources and sessions.

    A session that wrote the card is itself one source of provenance, so it counts
    as a group even when no source names it. That closes the shape the isolation
    guard used to admit: a card written with `--session` and no sources has no
    group list, and reading the empty list as "not single-session" was passing on
    absence. `single_session` is design.md's isolation claim — the card's whole
    provenance is the one session that wrote it. `independent` says two or more
    distinct provenance groups back it. A card whose one group is not a session
    that wrote it (seed and methodology material) is `unidentified`: neither one
    session's word nor two independent ones, reported as such and not guessed.
    Nothing here is stored twice.

    r112: provenance is counted per *source*, not per session.

    - A source that names an independence group contributes that group, and only
      that group. Two sessions citing the same named group are one provenance,
      because the group name is the same key both times. This closes one
      direction and not its mirror: it stops *two citations of one material*
      from reading as two sightings. It does not stop *one material logged two
      ways* -- a named group plus a group-less source the same session brought --
      from reading as two, because those are two different keys and this rule
      never compares them. That shape (a card whose one named group is joined by
      an attributed group-less source) still reports `independent=true`, and its
      header still counted only the named group, printing a 1 beside `true`.
      #1831d measured both: the union-of-groups-and-sessions alternative that
      would close it also merges two distinct declared groups written in one
      call into one provenance, taking the documented two-group broadcast case
      with it. So the header now counts what the verdict counts (below); the
      merge itself is left as a product decision, not silently changed here.
    - `independence_groups` reports the same value `independent` was decided
      from (`provenance_groups`), so a header can no longer print a count smaller
      than the one the verdict used. What it counts is still provenance, not
      people: two group names can come from one person. The raw named-group list
      is kept as `named_groups` for callers that need that distinction.
    - A source that names no group is attributed to the session that attached it,
      taken from the `attach_source` event. Material a second session really
      brought back therefore still counts -- even if that session confirmed the
      card afterwards. Confirming records no acquisition, which is the whole reason
      a confirmation cannot inflate provenance; the confirmer is deliberately not
      subtracted by name, so acquiring-then-confirming keeps its sighting.
    - A source that names no group and has no ledger entry to attribute it is
      reported in `unattributed_source_ids` and counted as nothing. It is not
      guessed from `sessions`, because `sessions` holds every writer, including a
      session whose only other act was to hand the card a group-named source that
      is already counted.
    - A card with no sources at all falls back to its writing sessions, so
      `--session` with no sources reads `single_session` rather than absent.
    """
    # #1831d: this function never reads `verification`, and that is deliberate -- do not
    # turn it into a gate later. Independence and "is this evidence" are two axes: a
    # source can be an unverified second arrival (counts as provenance) or a verified
    # restatement of something the same person already said (does not add one).
    # Filtering on `verification == "not_evidence"` here would make a model-generated
    # source stop counting at all, which silently changes how many sightings a card
    # claims based on a field about content, not about who brought it. It would also
    # make the count disagree with the ledger under a name that still says provenance.
    sources = list(state.get("sources", []))
    sessions = list(state.get("sessions", []))

    def _group(source: dict[str, Any]) -> str | None:
        value = source.get("independence_group")
        return value if value and value != "unknown" else None

    groups = sorted({_group(source) for source in sources if _group(source)})

    # Provenance is counted per *source*, not per session. Two sessions that each
    # attach material from the same named group are citing one provenance, not two:
    # a group name and a session ID are never equal, so subtracting one set from the
    # other can never collapse them, and a session-counting rule reports `independent`
    # for a claim only one source backs. That was the shape still going out in exports.
    #
    # A source that names no group is attributed to the session that attached it, read
    # from the `attach_source` event -- so a session that really brought back different
    # material still counts, even if it confirmed the card afterwards. Confirming writes
    # no acquisition, which is what keeps a confirmation from inflating anything; the
    # confirmer is not subtracted by name, so acquiring-then-confirming keeps its
    # sighting.
    # #1876: the group each source names, so a create event can tell which of the ids
    # it wrote already carry a group name.
    group_by_id = {source.get("id"): _group(source) for source in sources}
    attribution: dict[str, str] = {}
    # Sessions that really handed material over, kept apart from `attribution`: the
    # group-name branch stores a *group* in `attribution`, and calling a group name an
    # attributed session is the same confusion this fix is about.
    acquirers: set[str] = set()
    for event in events or []:
        details = event.get("details") or {}
        if event.get("event") == "attach_source":
            if details.get("source") and details.get("session"):
                attribution[details["source"]] = details["session"]
                acquirers.add(details["session"])
        # #1831b: the creating event names the sources it wrote. Reading it is what
        # makes "attached when the card was written" attributable at all; before this,
        # only `attach_source` carried that fact and a card written in one go with its
        # source fell to `unidentified` and was admitted.
        #
        # #1876: a group-less source written in the SAME call as a named one belongs to
        # that named group, not to the writing session. One witness logging the same
        # material two ways is one provenance: the registration changed, the witness did
        # not. Falling back to the session key there is what made a card written once
        # carry two provenance entries (`['sess-b', 'team-alpha']` for a single source of
        # one group). A session key is never attached to a source that already names a
        # group -- doing that is how the rejected union rule collapsed two genuinely
        # distinct declarations into one, taking the documented two-group case with it.
        elif event.get("event") in SOURCE_CREATING_EVENTS:
            session = details.get("session")
            named = details.get("sources")
            if session and isinstance(named, list):
                # The groups this same call declared, in the order the ids appear.
                declared: list[str] = []
                for source_id in named:
                    if isinstance(source_id, str) and source_id:
                        found = group_by_id.get(source_id)
                        if found and found not in declared:
                            declared.append(found)
                for source_id in named:
                    if isinstance(source_id, str) and source_id:
                        if group_by_id.get(source_id):
                            # group name wins; never also a session key
                            continue
                        if declared:
                            attribution[source_id] = declared[0]
                        else:
                            attribution[source_id] = session
                            acquirers.add(session)
    unattributed: list[str] = []
    provenance: set[str] = set(groups)
    for source in sources:
        if _group(source):
            continue
        session = attribution.get(source.get("id"))
        if session is None and len(sessions) == 1 and not events:
            # No ledger to attribute from (a bare state dict). With exactly one writing
            # session that is the only answer available, and it is the one `add` means.
            session = sessions[0]
        if session is None:
            unattributed.append(source.get("id", "?"))
        else:
            provenance.add(session)
    if not sources:
        # Written with --session and no sources at all: the writing sessions are the
        # only provenance there is, and reading that as "none" would pass the isolation
        # guard on absence.
        provenance |= set(sessions)
    provenance = sorted(provenance)
    acquirers |= {item for item in sessions if not sources}
    if len(provenance) >= 2:
        status = "cross_session"
    elif len(provenance) == 1 and provenance[0] in sessions:
        status = "single_session"
    else:
        status = "unidentified"
    # #1831d: `independence_groups` is what `independent` was decided from, not a
    # narrower count beside it. It used to be the named groups alone, so a card joined
    # by an attributed group-less source printed `independence_groups=1 | independent=true`
    # -- a number the verdict had already stopped using. The raw named-group list is
    # still reported, as `named_groups`: that is a property of the source records, and
    # #1774's "self-declared groups" wording is about it, so it keeps its own name
    # instead of being read out of a field that now means something else.
    return {
        "independence_groups": provenance,
        "named_groups": groups,
        "sessions": sessions,
        "attributed_sessions": sorted(acquirers),
        # Reported rather than guessed: a source that names no group and cannot be tied
        # to a session contributes nothing, and the caller can see that it happened.
        "unattributed_source_ids": sorted(unattributed),
        "provenance_groups": provenance,
        "provenance_status": status,
        "independent": len(provenance) >= 2,
        "single_session": status == "single_session",
    }


# The card's text, split by the part a person would point at. `candidate_text` is their
# union and stays the matcher's input, so what a query can reach is unchanged. The
# pieces exist so the reading screen can say *which* of them the words came from:
# #3436's second round measured an entry claiming "对上 8 个词" over a sentence that
# shared none of them, because its condition line was the phrase being searched.
BOUNDARY_FIELDS = ("premises", "scope", "alternatives", "contradictions", "unknowns")


def answers_text(state: dict[str, Any]) -> str:
    """His own answers as searchable text. Used by the person's retrieval only."""
    from .answers import answers_text as _answers_text
    return _answers_text(state)


def statement_text(state: dict[str, Any]) -> str:
    """The one sentence the entry prints and quotes: exactly what the card says now."""
    return str(state.get("statement") or "")


def aliases_text(state: dict[str, Any]) -> str:
    """The other wordings the library stores for this card.

    Kept apart from the statement because the two answer different questions: an alias
    match means "this is the card you mean, said another way", and the screen has to
    say so. Reporting it as the statement is the defect #3436's second round measured:
    the alias shared 5 bigrams with the query and the sentence 0, and the screen
    printed no note at all.
    """
    return " ".join(str(value) for value in state.get("aliases", []))


def wording_text(state: dict[str, Any]) -> str:
    """Both of the above, which is what "the wordings this card holds" means."""
    return " ".join(part for part in (statement_text(state), aliases_text(state)) if part)


def limits_text(state: dict[str, Any]) -> str:
    """The card's conditions, counterexamples, premises, alternatives and unknowns."""
    values: list[Any] = []
    for key in BOUNDARY_FIELDS:
        values.extend(state.get(key, []))
    return " ".join(str(value) for value in values)


def sources_text(state: dict[str, Any]) -> str:
    """What the card's provenance records say, which is not what the card says."""
    values: list[Any] = []
    for source in state.get("sources", []):
        values.extend([source.get("claim", ""), source.get("type", ""), source.get("scope_note", "")])
    return " ".join(str(value) for value in values)


def candidate_text(state: dict[str, Any]) -> str:
    return " ".join(part for part in (
        wording_text(state), limits_text(state), sources_text(state)) if part)


def earlier_wordings(state: dict[str, Any], events: list[dict[str, Any]]) -> list[str]:
    """The sentences this card used to say, newest first, as the ledger wrote them.

    Read from `revise` rows only -- a `revise.repeat` is the same request arriving
    again, and `from_statement` there is the sentence that was already left. Nothing is
    inferred from a snapshot diff: the event names both ends, so a rewritten-and-
    restored card yields the same list either way. Values are those the writer stored,
    never a paraphrase, because the screen's job is to show what he remembers, not to
    improve on it.
    """
    seen: list[str] = []
    current = str(state.get("statement") or "")
    for event in reversed(events):
        if event.get("event") != "revise":
            continue
        left = (event.get("details") or {}).get("from_statement")
        if not isinstance(left, str) or not left.strip() or left == current or left in seen:
            continue
        seen.append(left)
    return seen


def searchable_text(state: dict[str, Any], events: list[dict[str, Any]]) -> str:
    """What a search may match on: the card now, plus the sentences it used to say.

    Wider than `candidate_text` and used *only* by retrieval's own matcher. What is
    handed to the model, exported or diffed keeps `candidate_text`, so the model never
    sees a sentence the card no longer holds as though the card held it; a result that
    matched on an earlier wording says so in `matched_wording` (#3436).
    """
    return " ".join([candidate_text(state), *earlier_wordings(state, events)])


SEEDS: list[dict[str, Any]] = [
    {
        "id": "seed-m01", "statement": "环境与流程的设计，往往比临时的决心更能稳住重复行为；降低启动摩擦通常比反复下决心更可持续。",
        "kind": "abstract_idea", "scope": ["日常重复行为能否持续（如物品归位、例行整理）"],
        "premises": ["该行为会重复发生", "意愿与摩擦可以在讨论上分开考虑"],
        "alternatives": ["若困难主要来自不知道怎么做，降低操作摩擦帮助有限"],
        "unknowns": ["摩擦要降低多少才算明显有用", "有没有不适用场景"],
        "sources": [{"id": "src-m01", "type": "abstract_reasoning", "claim": "由模拟陌生人场景推理得出的抽象区分", "independence_group": "stranger-methodology-v1", "verification": "not_evidence", "scope_note": "非经验证据"}],
    },
    {
        "id": "seed-m02", "statement": "若只是想维持现状、且这个行为本身没有训练价值，那么减少步骤、把正确动作的准备前置，通常能提高它持续发生的概率。",
        "kind": "application", "scope": ["目标是维持既有状态、行为本身不构成能力练习时"],
        "premises": ["该行为本身没有训练价值", "减少的只是与目标无关的步骤"],
        "alternatives": ["若这个行为本身就是在练习一种能力，减少步骤可能反而有害"],
        "unknowns": ["怎样判断一个行为有没有训练价值"],
        "sources": [{"id": "src-m02", "type": "abstract_reasoning", "claim": "由模拟陌生人场景条件推演得出的路线甲", "independence_group": "stranger-methodology-v1", "verification": "not_evidence", "scope_note": "非经验证据"}],
        "relations": [{"type": "narrows", "target": "seed-m01", "note": "在行为本身没有训练价值时细化降低摩擦的思路"}],
    },
    {
        "id": "seed-m03", "statement": "若一个行为的价值正来自练习过程本身，那么降低难度等于同时去掉练习机会；这时应保留有意义的难度，只去除与目标无关的无谓摩擦。",
        "kind": "application", "scope": ["能力的形成本身依赖练习过程时"],
        "premises": ["存在构成能力本身的练习难度", "可以把无谓摩擦与训练难度分开"],
        "alternatives": ["若某种困难只是习惯性的麻烦，仍应归入可以降低的摩擦"],
        "unknowns": ["怎样判断一份难度是“有意义”还是“只是麻烦”"],
        "sources": [{"id": "src-m03", "type": "abstract_reasoning", "claim": "由模拟陌生人场景条件推演得出的路线乙", "independence_group": "stranger-methodology-v1", "verification": "not_evidence", "scope_note": "非经验证据；与 seed-m02 为不同条件路线"}],
        "relations": [{"type": "narrows", "target": "seed-m01", "note": "在行为价值来自练习本身时限定降低摩擦"}],
    },
    {
        "id": "seed-m04", "statement": "一名模拟角色自述：靠每次只做一件小事，坚持了数月整洁，而没有依赖更强的自律。",
        "kind": "experience_claim", "scope": ["单一模拟角色对自身经历的记忆"],
        "premises": ["该角色相信自己的记忆"],
        "alternatives": ["记忆可能不完整，或存在其他解释"],
        "unknowns": ["时间范围、是否中途失败、是否换了别的做法、有没有独立来源，均缺失"],
        "sources": [{"id": "src-m04", "type": "claimed_firsthand", "claim": "模拟角色声称靠每次只做一件小事坚持了数月整洁", "independence_group": "unknown", "verification": "unverified", "scope_note": "没有记录、时间范围或可独立核验来源；重复传播不构成独立佐证"}],
    },
]


def load_simulated_seeds(store: Store) -> dict[str, Any]:
    """Load the four documented simulated examples once; never overwrite existing IDs."""
    ids = {seed["id"] for seed in SEEDS}
    present = {row["id"] for row in store.list_candidates(include_history=True)}.intersection(ids)
    if present:
        if present == ids:
            return {"loaded": False, "ids": sorted(ids), "message": "simulated seeds already present; nothing changed"}
        raise DojoError("only some seed IDs already exist; refusing partial overwrite: " + ", ".join(sorted(present)))
    with store.transaction():
        for seed in SEEDS:
            state = {
                **seed,
                "version": 1,
                "status": "discussable",
                "aliases": [],
                "sessions": [],
                "confirmation": {
                    "active": True,
                    "confirmed_by": "seed-pack-v1 initializer",
                    "session": None,
                    "basis": "simulated seed supplied for the POC; discussable only, not a truth claim",
                    "not_truth_claim": True,
                },
            }
            store._insert_candidate(state, "load_simulated_seed", {"seed_pack": "seed-pack-v1", "not_truth_claim": True})
    return {"loaded": True, "ids": sorted(ids), "message": "four simulated candidates loaded; none are verified evidence"}
