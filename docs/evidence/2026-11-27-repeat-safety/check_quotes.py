#!/usr/bin/env python3
"""Every quoted block must appear verbatim in the source text.

    python3 -B docs/evidence/2026-11-27-repeat-safety/check_quotes.py \
        <rfc9110.txt> [<rfc9112.txt> ...]

The RFC files are not committed: they are the publisher's, and they are large.
Fetch them from the URLs named in source-excerpt.txt, then point this script at
the copies you fetched.

Comparison is exact, including blank lines and leading spaces. Trailing spaces
are ignored because they carry no meaning in the source.

This script exists because the first version of the excerpt was transcribed from
what the text was remembered to say. It was wrong in two places: a dropped blank
line, and a paraphrased paragraph in the second block. This check is what caught
it. Anything quoted from a source in this directory has to go through here.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXCERPT = HERE / "source-excerpt.txt"


def blocks(text):
    """Split the excerpt into quoted blocks, dropping the banner lines."""
    out, current = [], []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("Source excerpt.", "Retrieved 2026")):
            current = []
            continue
        if stripped and set(stripped) == {"="}:
            out.append(current)
            current = []
            continue
        current.append(line.rstrip())
    out.append(current)
    return [block for block in out if any(line.strip() for line in block)]


def find(block, hay):
    size = len(block)
    for start in range(len(hay) - size + 1):
        if hay[start:start + size] == block:
            return start + 1
    return None


def main(argv):
    if len(argv) < 2:
        print("usage: check_quotes.py <source.txt> [<source.txt> ...]", file=sys.stderr)
        return 2
    haystacks = {
        path: [line.rstrip() for line in Path(path).read_text(encoding="utf-8").splitlines()]
        for path in argv[1:]
    }
    parsed = blocks(EXCERPT.read_text(encoding="utf-8"))
    found = 0
    for index, block in enumerate(parsed):
        for path, hay in haystacks.items():
            line = find(block, hay)
            if line is not None:
                print(f"block {index}: verbatim in {path} at line {line}")
                found += 1
                break
        else:
            print(f"block {index}: NOT FOUND -- first line {block[0]!r}", file=sys.stderr)
            return 1
    print(f"every block appears verbatim ({found} blocks, "
          f"{sum(len(b) for b in parsed)} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
