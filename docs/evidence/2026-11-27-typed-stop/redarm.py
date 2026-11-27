#!/usr/bin/env python3
"""Red arms for the typed-stop slice: revert one fix at a time and see the tests go red.

    python3 .scratch/3363/redarm_stop.py <candidate-worktree>

Each arm copies the tree, changes one thing, and runs only the tests that claim the
behaviour. A green run under a reverted fix would mean the test asserts nothing.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SRC = Path(sys.argv[1]).resolve()
TESTS = "tests.test_elicitation_closing"
BASE = ["python3", "-B", "-m", "unittest", TESTS]


def run(tree: Path) -> tuple[int, str]:
    proc = subprocess.run(BASE, cwd=tree, capture_output=True, text=True)
    tail = (proc.stderr or proc.stdout).strip().splitlines()
    return proc.returncode, "\n".join(tail[-14:])


def arm(name: str, edits: list[tuple[str, str, str]]) -> None:
    """edits: (relative file, old text, new text). Old text must appear exactly once."""
    temp = Path(tempfile.mkdtemp(prefix="redarm-stop-"))
    tree = temp / "tree"
    shutil.copytree(SRC, tree, ignore=shutil.ignore_patterns(".git", "__pycache__"))
    for rel, old, new in edits:
        path = tree / rel
        body = path.read_text(encoding="utf-8")
        if body.count(old) != 1:
            print(f"!! {name}: anchor appears {body.count(old)} times in {rel}")
            shutil.rmtree(temp)
            return
        path.write_text(body.replace(old, new), encoding="utf-8")
    code, tail = run(tree)
    print("=" * 78)
    print(f"{name}  ->  {'RED as expected' if code else 'STILL GREEN (the tests assert nothing)'}")
    print(tail)
    shutil.rmtree(temp)


# 1. The stop branch is gone: his wind-down becomes an answer again.
arm(
    "A no `stop` branch in the loop",
    [("dojo/discuss.py",
      '                    if reading == "stop":\n',
      '                    if False and reading == "stop":\n')],
)

# 2. The recognizer is gone: nothing is ever read as a wind-down.
arm(
    "B `is_stop_statement` always False",
    [("dojo/elicit.py",
      'STOP_PATTERNS = (\n',
      'STOP_PATTERNS = ()\n_DEAD_STOP_PATTERNS = (\n')],
)

# 3. The receipt word is gone: a spoken stop is reported as ended input.
arm(
    "C receipt says 结束了输入 for a spoken stop",
    [("dojo/discuss.py",
      '(" 时你说到这儿为止" if spoken_stop else " 时你结束了输入")',
      '" 时你结束了输入"')],
)

# 4. declined_count goes back to the number he spoke.
arm(
    "D declined_count back to the number he said",
    [("dojo/discuss.py",
      '        "declined_count": len(declined), "declined_stated": declined_stated,',
      '        "declined_count": declined_stated, "declined_stated": declined_stated,')],
)

print("=" * 78)
# 5. The recognizer is too wide: it matches by prefix instead of whole sentence, so
#    material that merely starts with a wind-down word is swallowed.
arm(
    "E recognizer matches any sentence starting with a wind-down word",
    [("dojo/elicit.py",
      "    return any(re.fullmatch(pattern, core) for pattern in STOP_PATTERNS)",
      "    return any(re.search(pattern.lstrip('^').split('$')[0], core) for pattern in STOP_PATTERNS)")],
)

# 6. The old lie: a wind-down is kept as an answer, so the skip-mention detector fires.
arm(
    "F wind-down falls back to the old answer reading",
    [("dojo/elicit.py",
      '    if is_stop_statement(value):\n        return "stop"',
      '    if False and is_stop_statement(value):\n        return "stop"')],
)

print("=" * 78)
print("baseline (unchanged) ->", run(SRC)[0], "(0 = green)")
