"""The commands this program tells a person to run next.

A hint is only useful if following it works. The supervisor found four ways these did
not (2026-11-28, #3419), all about the same printed line:

  wrong library   `dojo discuss --db <somewhere> ...` ended by printing a bare
                  `python3 -m dojo show <id>`. Pasted, that read the *default* library:
                  `candidate not found` for a draft the session had just written.
  relative env    a line that leaned on `DOJO_DB=chosen.sqlite3` meant a different file
                  in every directory.
  one-shot env    a line that leaned on a `DOJO_DB` set for one command lost it in the
                  next terminal.
  other library   a line that leaned on "the default library" read whatever the pasting
                  terminal calls the default. `--resume` from it exited 0 **and appended
                  the second half of the conversation to that other library**.

  mangled path    a path with a space arrives as two arguments; one with `$`, a backtick
                  or a quote arrives as something else. The old helper in storage.py
                  wrapped spaces in double quotes, which is wrong for every one of those.

What getting it wrong four times taught: a printed line must not depend on anything that
changes between printing it and pasting it -- not the directory, not the environment, not
which terminal it lands in. So one renderer, in one place, and it names the file.

Quoting is chosen to stay readable: a plain name is printed plain, a path with spaces or a
single quote is double-quoted (the common case stays legible), and anything a double-
quoted shell word would still act on is single-quoted with the standard `'\\''` escape.

Nothing here decides *which* library a session used; that is the caller's fact. It only
makes what the caller decided paste-able.
"""
from __future__ import annotations

import os
import re
from pathlib import Path


def library_argument(database: str | Path | None) -> Path | None:
    """The `--db` every printed command carries: the absolute path, or None if unknown.

    There is no short form. A printed line has to mean the same thing in any directory and
    any terminal, and "the default library" does not: `$DOJO_DB` changes what a bare
    command opens, so a line that relied on it pointed at a different file the moment the
    reader pasted it elsewhere. The supervisor measured that four ways before this landed
    (#3419):

      relative  `DOJO_DB=chosen.sqlite3` names A/chosen.sqlite3 in A, B/chosen.sqlite3 in B
      one-shot  `DOJO_DB=/abs/x.sqlite3` for one command is absent in the next terminal
      other lib a terminal that usually works on another library is not this one
      wrong dir `--db run/dojo.sqlite3` is a different file from another directory

    Each of those was reproduced and then fixed in turn, which is what makes the pattern
    clear: any rule that asks the environment has an answer that changes between printing
    the line and pasting it. So this function does not ask. It prints the file.

    The last case is also why an earlier "keep the common case short" rule went away. That
    rule was a preference of mine, not something a reader asked for, and it cost the one
    property that matters: `--resume` from a pasted line silently appended the second half
    of a conversation to a library the session had never touched.

    The path may not live in the trace either -- a host's file layout is not part of what
    he said -- so it comes from the library the caller actually opened.
    """
    if database is None:
        return None
    return absolute(database)


# Unquoted, a shell keeps these bytes as they are. Deliberately excludes `~` (the shell
# would expand it, so a literal directory named `~x` would become a home directory) and
# anything starting with `-` (argparse would take a later `--db` value for an option).
_BARE = re.compile(r"[A-Za-z0-9_@%+=:,./][A-Za-z0-9_@%+=:,./-]*")
# A flag, printed bare. Every value this program prints is either a card/story id
# (`ID_RE` starts with a letter or digit) or a path, and paths go through `absolute()`;
# so no value can be mistaken for a flag here. Quoting them would also be correct, but
# `dojo discuss "--resume" ...` reads like a mistake and invites the reader to "fix" it.
_FLAG = re.compile(r"--?[A-Za-z][A-Za-z0-9-]*")
# Inside a double-quoted word a POSIX shell still acts on these. `!` is here for the
# interactive case: history expansion is on by default in an interactive bash, so a pasted
# line containing `!` is not the line the reader copied.
_DOUBLE_UNSAFE = ('"', "$", "`", "\\", "!", "\n", "\r")


def quote(text: str) -> str:
    """`text` as one shell word, quoted only as much as it needs to be."""
    if _BARE.fullmatch(text):
        return text
    if not any(character in text for character in _DOUBLE_UNSAFE):
        return '"' + text + '"'
    return "'" + text.replace("'", "'\\''") + "'"


def absolute(path: str | Path) -> Path:
    """The same path, not relative to whatever directory happened to be current.

    A command printed into a record outlives the shell that ran it: `--db run/dojo.sqlite3`
    is the right file from one directory and a different file (or a new, empty one) from
    another. The record says which file the session actually used, so it says it absolutely.
    """
    value = Path(path).expanduser()
    return value if value.is_absolute() else Path.cwd() / value


def locate_record(record: str | Path | None,
                  database: str | Path | None = None) -> tuple[Path | None, str]:
    """The session record a stored path names, found again if the library moved.

    A stored path is right when it is written and stale the moment someone moves the
    library and its `sessions/` directory together. Repeated review finding: after such a
    move `search` still found the card and the answers were still on it, but the command
    it printed pointed at the old directory and exited 2.

    A session file's name is unique (`discuss-<32 hex>.jsonl`), so the same name under the
    configured session directory, or beside this library, is the same record rather than a
    guess. Returns the path to use (or None if nothing was found) and which of the three
    it was, so the screen can say "this moved" instead of silently printing a fifth path.
    """
    if not record:
        return None, "none"
    given = Path(record).expanduser()
    if given.is_file():
        # Absolute even when it was relative: `DOJO_SESSIONS=meeting notes` is a perfectly
        # normal thing to type, and a command printed with that path means a different
        # directory in every terminal it is pasted into (#3419's rule, applied here).
        return absolute(given), "as-stored"
    candidates: list[tuple[Path, str]] = []
    configured = os.environ.get("DOJO_SESSIONS", "").strip()
    if configured:
        candidates.append((Path(configured).expanduser() / given.name, "sessions-env"))
    if database is not None:
        candidates.append((absolute(database).parent / "sessions" / given.name,
                           "beside-library"))
    for candidate, where in candidates:
        if candidate.is_file():
            return absolute(candidate), where
    return None, "missing"


def dojo(*arguments: object, db: str | Path | None = None) -> str:
    """`python3 -m dojo [--db LIBRARY] <arguments...>` as one copyable line.

    `--db` is placed before the subcommand because that is where the parser wants it.
    """
    parts = ["python3", "-m", "dojo"]
    if db is not None:
        parts.extend(["--db", quote(str(db))])
    for argument in arguments:
        text = str(argument)
        parts.append(text if _FLAG.fullmatch(text) else quote(text))
    return " ".join(parts)

