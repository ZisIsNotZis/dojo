"""How one discussion trace record is written, and how a trace file is read back.

The format is JSON Lines: one record per `\\n`-terminated line. Two independent programs
have to agree on that, and they stopped agreeing at three code points.

`json.dumps(..., ensure_ascii=False)` leaves U+0085 (NEL), U+2028 (LINE SEPARATOR) and
U+2029 (PARAGRAPH SEPARATOR) raw, because they are legal inside a JSON string. Python's
`str.splitlines()` treats all three as line breaks, so a person who pastes an answer from
a document carrying U+2028 gets a trace that the writer wrote correctly and the reader
cuts in half: the supervisor measured exactly that -- four answers in the file, and
`transcript` refusing it as "第 2 行不是 JSON". The program's own session, unreadable by
the program's own view.

Both halves are fixed here, in one module, because fixing only one leaves the other open:

  write   those three code points are escaped to their `\\uXXXX` form, so a record is one
          physical line for any reader -- `splitlines()`, `readline()`, `grep`, an editor.
  read    records are split on `\n` alone, so a trace written before the fix, or written
          by anything else, still parses: its JSON string already contains the character,
          which `json.loads` accepts.

Nothing here validates a record's shape; that belongs to the reader that knows what it is
looking at (`_load_resume_trace`, `transcript`, `dao_session`).
"""
from __future__ import annotations

import json
from typing import Any

MAX_TRACE_BYTES = 16_000_000

# The three code points `str.splitlines()` counts as a line break that are legal unescaped
# inside a JSON string. `\v`, `\f` and `\x1c`-`\x1e` are also line breaks for
# `splitlines()`, but `json.dumps` already escapes them as control characters.
LINE_BREAK_CODEPOINTS = ("\u0085", "\u2028", "\u2029")


def escape_line_breaks(text: str) -> str:
    """Replace U+0085 / U+2028 / U+2029 with their `\\uXXXX` spellings.

    `json.dumps` already does this for control characters; it leaves these three raw
    because JSON allows them inside a string. Any format whose readers use
    `str.splitlines()` needs them gone.
    """
    for codepoint in LINE_BREAK_CODEPOINTS:
        if codepoint in text:
            text = text.replace(codepoint, "\\u%04x" % ord(codepoint))
    return text


def encode_record(value: dict[str, Any]) -> str:
    """One trace record, as a single line that ends with `\\n`."""
    return escape_line_breaks(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    ) + "\n"


def split_lines(text: str) -> list[str]:
    """The lines of a trace file: `\\n` is the only thing that ends a record.

    A trailing newline does not produce an empty last line, and blank lines are kept so a
    reader can decide what to do with them (the resume validator refuses them by name).
    """
    if text == "":
        return []
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def read_records(path) -> list[dict[str, Any]]:
    """Parse every record of a trace. Raises `ValueError` with the line number."""
    text = path.read_text(encoding="utf-8")
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(split_lines(text), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"第 {number} 行不是记录对象")
        rows.append(value)
    return rows


__all__ = [
    "LINE_BREAK_CODEPOINTS", "encode_record", "escape_line_breaks", "split_lines",
    "read_records",
]
