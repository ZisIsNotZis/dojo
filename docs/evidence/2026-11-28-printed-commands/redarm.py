#!/usr/bin/env python3
"""Put each old behaviour back and show the evidence pack goes red.

    python3 docs/evidence/2026-11-28-printed-commands/redarm.py

Copies the tree, makes one edit, runs `verify.py`. An arm that stays green means the
check it targets does not bite.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
VERIFY = "docs/evidence/2026-11-28-printed-commands/verify.py"

ARMS = [
    (
        "退出的 show 不带库",
        "dojo/discuss.py",
        '+ commands.dojo("show", draft_id, db=commands.library_argument(store.path)),',
        '+ commands.dojo("show", draft_id),',
        "the supervisor's original report: `candidate not found` on a draft this session wrote",
    ),
    (
        "四件问完那行回执不带库",
        "dojo/discuss.py",
        '''                        commands.dojo("transcript", commands.absolute(trace_path),
                                      db=commands.library_argument(store.path))''',
        '''                        commands.dojo("transcript", commands.absolute(trace_path))''',
        "the receipt for the four questions then names a view with no library to pass on",
    ),
    (
        "退出的 transcript 不带库（早退时）",
        "dojo/discuss.py",
        '''                + commands.dojo("transcript", commands.absolute(trace_path),
                                db=commands.library_argument(store.path)),''',
        '''                + commands.dojo("transcript", commands.absolute(trace_path)),''',
        "the other exit line, for a session that ends before the questions",
    ),
    (
        "回看不把库传给卡片命令",
        "dojo/transcript.py",
        '''    return commands.dojo("show", candidate_id, db=commands.library_argument(database))''',
        '''    return commands.dojo("show", candidate_id)''',
        "`transcript --db` still reads the record, but its `show` line is short",
    ),
    (
        "把库路径写进轨迹",
        "dojo/discuss.py",
        '''                "event": "session_end", "reason": reason, "saved": saved_ids,
                "draft": draft_id,''',
        '''                "event": "session_end", "reason": reason, "saved": saved_ids,
                "draft": draft_id, "database": str(store.path),''',
        "a host file path becomes part of the record of what he said",
    ),
    (
        "路径不加引号",
        "dojo/commands.py",
        '''    if _BARE.fullmatch(text):
        return text
    if not any(character in text for character in _DOUBLE_UNSAFE):
        return '"' + text + '"'
    return "'" + text.replace("'", "'\\\\''") + "'"''',
        # (kept in sync with dojo/commands.py; the arm is a whole-function replacement)
        '''    return text''',
        "a path with a space arrives as two arguments",
    ),
    (
        "默认库重新用短形式（第一、四次报告）",
        "dojo/commands.py",
        '''    if database is None:
        return None
    return absolute(database)''',
        '''    if database is None:
        return None
    path = absolute(database)
    default = Path.home() / ".local" / "share" / "dojo" / "dojo.sqlite3"
    return None if path == default else path''',
        "the line means \"the default library\", which a terminal with DOJO_DB disagrees "
        "about -- measured: show failed there and --resume wrote into that other library",
    ),
    (
        "用环境变量判断「已经对了」（第二、三、四次报告）",
        "dojo/commands.py",
        '''    if database is None:
        return None
    return absolute(database)''',
        '''    if database is None:
        return None
    import os
    path = absolute(database)
    bare = Path(os.environ["DOJO_DB"]).expanduser() if os.environ.get("DOJO_DB") else (
        Path.home() / ".local" / "share" / "dojo" / "dojo.sqlite3")
    if not bare.is_absolute():
        bare = Path.cwd() / bare
    return None if path.resolve() == bare.resolve() else path''',
        "correct where it was printed, wrong where it was pasted",
    ),
    (
        "回看印相对 DOJO_SESSIONS 路径",
        "dojo/discuss.py",
        '''                + commands.dojo("transcript", commands.absolute(trace_path),
                                db=commands.library_argument(store.path)),''',
        '''                + commands.dojo("transcript", trace_path,
                                db=commands.library_argument(store.path)),''',
        "the view is started with a path that only resolves in the directory it was printed in",
    ),
]


def main() -> int:
    failures = 0
    for label, relative, old, new, why in ARMS:
        work = Path(tempfile.mkdtemp(prefix="redarm."))
        try:
            for name in ("dojo", "docs"):
                shutil.copytree(ROOT / name, work / name)
            path = work / relative
            source = path.read_text(encoding="utf-8")
            if old not in source:
                print("SKIP  %-26s anchor not found in %s" % (label, relative))
                failures += 1
                continue
            path.write_text(source.replace(old, new, 1), encoding="utf-8")
            done = subprocess.run([sys.executable, "-B", str(work / VERIFY)],
                                  cwd=str(work), capture_output=True, text=True,
                                  timeout=600,
                                  env={"PYTHONPATH": str(work), "PATH": "/usr/bin:/bin",
                                       "PYTHONDONTWRITEBYTECODE": "1"})
            lines = [line.strip() for line in done.stdout.splitlines()
                     if "不成立" in line]
            verdict = "RED  " if done.returncode else "GREEN"
            if not done.returncode:
                failures += 1
            print("%s %-26s %s" % (verdict, label, "；".join(lines) or "(no failing check)"))
            print("      %s" % why)
        finally:
            shutil.rmtree(work, ignore_errors=True)
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
