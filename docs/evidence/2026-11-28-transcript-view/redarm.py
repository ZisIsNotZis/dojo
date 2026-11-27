#!/usr/bin/env python3
"""Break each behaviour this slice added; both witnesses must go red, arm by arm.

    python3 docs/evidence/2026-11-28-transcript-view/redarm.py [tree]

Each arm copies the tree, edits one thing, then runs *two* witnesses: this directory's
`verify.py` (the real CLI) and the three unit-test files this slice added. An arm caught
by neither means nothing is watching that behaviour; an arm caught by only one is printed
as HALF, because that layer is blind to it. Both are failures of this script, and it
exits 1 when any arm is not caught twice.

Two lessons from the previous review are built in. Every arm edits the file that owns the
behaviour -- one of them edits `cli.py`, where the command is registered, not the view
module -- because an earlier set of arms only ever touched `discuss.py` and so could not
catch a regression in `elicit.py` or in the CLI. And the witnesses include a test file
per behaviour rather than one file, for the same reason.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TREE = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
ENTRY = Path("docs/evidence/2026-11-28-transcript-view/verify.py")

ARMS: list[tuple[str, str, str, str]] = [
    (
        "A 回执不再点名回看命令",
        "dojo/discuss.py",
        'look = ("要回看这一场的原话和它们各自的下场，运行：" + where + "（只读，不改本场。）") if where else ""',
        'look = ""',
    ),
    (
        "B --no-trace 时也点名命令",
        "dojo/discuss.py",
        'if trace_path is not None and kept_now is not False else None',
        'if True else None',
    ),
    (
        "C 回看不再说「材料，不是结论」",
        "dojo/transcript.py",
        'lines.append("这些话是材料，不是结论：回看只说你说过什么，不判哪句答到了点上，也不代表你认可了哪条结论。")',
        'lines.append("回看完毕。")',
    ),
    (
        "D 截断时谎称没写下卡片",
        "dojo/transcript.py",
        'elif view["complete"]:',
        'elif True:',
    ),
    (
        "E 截断时仍印一条会被拒的续跑命令",
        "dojo/transcript.py",
        'if view.get("resumable"):',
        'if False:',
    ),
    (
        # The view keeps two readings of the same part (the last row's verdict and the
        # last answer said). Both have to point at the end of the append-only list, so
        # the arm moves both -- an arm that only moved one would stay green because the
        # other one still produced the right sentence, which is not a bug in the arm but
        # the whole reason to write it down.
        "F 只取每件的第一行（撤回后看不见最后那句）",
        "dojo/transcript.py",
        "        last = events[-1]\n        said = next((row[\"answer\"] for row in reversed(events)",
        "        last = events[0]\n        said = next((row[\"answer\"] for row in events",
    ),
    (
        "G 回看时偷偷开一个库",
        "dojo/cli.py",
        '            from .transcript import TranscriptError, load, render',
        '            from .transcript import TranscriptError, load, render\n            Store(db_path).close()',
    ),
    (
        "H 停止点名「收作原话」，改回「你答了」",
        "dojo/transcript.py",
        '    "answer": "收作原话",',
        '    "answer": "你答了",',
    ),
    (
        # The five-version fault the reviewer measured at 4cd8905: the resumed request
        # reads the card's current version out of the library instead of the handout row.
        "J 续跑时从库里取卡的最新版（同一请求两个版本）",
        "dojo/discuss.py",
        '    if (saved_candidate_id is not None and isinstance(handed_row, dict)\n            and handed_row.get("id") == saved_candidate_id):',
        '    if False:',
    ),
    (
        "K 回执又说「之后没改过」（说了库里的事）",
        "dojo/discuss.py",
        '"卡片是提问前写下的那句，这场问答没有改过它，字这一版仍全算我写的。" + look)',
        '"卡片是提问前写下的那句，之后没改过，字这一版仍全算我写的。" + look)',
    ),
    (
        # The codec has two halves and each has to be watched on its own: a writer that
        # stops escaping, and a reader that splits on more than `\n`. Fixing only one
        # leaves the other open, which is how the supervisor's pasted answer got through.
        "L 写的时候不再转义 U+0085/U+2028/U+2029",
        "dojo/tracefile.py",
        "    return escape_line_breaks(\n        json.dumps(value, ensure_ascii=False, separators=(\",\", \":\"))\n    ) + \"\\n\"",
        "    return json.dumps(value, ensure_ascii=False, separators=(\",\", \":\")) + \"\\n\"",
    ),
    (
        "M 读的时候又用 splitlines()（按 U+2028 断行）",
        "dojo/tracefile.py",
        "    lines = text.split(\"\\n\")",
        "    lines = text.splitlines()",
    ),
    (
        "I 不承认最后一行写了一半",
        "dojo/transcript.py",
        '        lines.append("最后一行只写了一半（写的时候断了），这一行没有算进来。")',
        '        lines.append("记录完整。")',
    ),
]


def clean_env() -> dict[str, str]:
    import os
    env = {k: v for k, v in os.environ.items() if not k.startswith("DOJO_")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def main() -> int:
    green = 0
    for name, relative, old, new in ARMS:
        work = Path(tempfile.mkdtemp(prefix="arm."))
        try:
            for part in ("dojo", "docs", "tests", "scripts", "fixtures"):
                if (TREE / part).is_dir():
                    shutil.copytree(TREE / part, work / part)
            for part in ("README.md", "README.zh-CN.md"):
                shutil.copy2(TREE / part, work / part)
            target = work / relative
            source = target.read_text(encoding="utf-8")
            if old not in source:
                print("BROKEN %s：锚点没找到（%s）" % (name, relative))
                green += 1
                continue
            target.write_text(source.replace(old, new, 1), encoding="utf-8")
            # Two witnesses, because a defect can live in either layer: the evidence
            # script walks the real CLI, and the unit tests reach assertions the script
            # does not make (the request body, the library claim). Requiring both keeps
            # an arm from going green just because it broke something the other one
            # happens not to look at -- the exact gap the previous review found in arms
            # that only ever ran one file.
            done = subprocess.run([sys.executable, "-B", str(ENTRY)], cwd=str(work),
                                  text=True, capture_output=True, env=clean_env(), timeout=900)
            units = subprocess.run(
                [sys.executable, "-B", "-m", "unittest",
                 "tests.test_transcript_view", "tests.test_one_card_version",
                 "tests.test_non_answer_words", "tests.test_trace_line_breaks"],
                cwd=str(work), text=True, capture_output=True, env=clean_env(), timeout=900)
            if done.returncode == 0 and units.returncode == 0:
                print("GREEN  %s —— 没有人在看这个" % name)
                green += 1
            elif done.returncode != 0 and units.returncode != 0:
                failed = [line for line in done.stdout.splitlines() if line.startswith("FAIL")]
                print("RED    %s（两层都红：%s）" % (name, failed[0].strip() if failed
                                                    else "exit %d" % done.returncode))
            else:
                # Exactly one witness noticed. That is worth keeping as a finding: the
                # other layer is blind to this behaviour, which is how the previous slice
                # shipped a defect its 1188 green tests could not see.
                blind = "证据脚本" if done.returncode == 0 else "单元测试"
                source = done.stdout if done.returncode else units.stderr
                failed = [line for line in source.splitlines()
                          if line.startswith(("FAIL", "ERROR:"))]
                print("HALF   %s（%s没在看这个；%s）" % (
                    name, blind, failed[0].strip() if failed else ""))
                green += 1
        finally:
            shutil.rmtree(work, ignore_errors=True)
    print()
    if green:
        print("%d 条臂没咬住。" % green)
        return 1
    print("%d 条臂全部真红。" % len(ARMS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
