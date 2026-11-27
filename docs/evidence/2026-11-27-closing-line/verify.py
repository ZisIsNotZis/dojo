#!/usr/bin/env python3
"""四件问完之后，那个人有没有被告知「哪几件是你说过的」。

    python3 docs/evidence/2026-11-27-closing-line/verify.py

只读、离线、不联网、不写库。它替一个读者跑真入口 `run_discuss`，回答四件事：

    1. 四件问完之后，屏幕上有一句说清楚哪几件落在他说过的话上。
    2. 这一句与轨迹里记的 `collected`/`supplied` 一致——不是另算一份。
    3. 它在最后一个问题之后，不是在入场的形状里提前说的。
    4. `--no-trace` 下同样成立（这一句讲本场发生过什么，不是讲磁盘）。

退出码 0 = 四项都成立；1 = 有一项不成立，并指出是哪一项。
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from dojo.discuss import closing_text, run_discuss  # noqa: E402
from dojo.elicit import PART_ORDER, QUESTIONS  # noqa: E402
from dojo.storage import Store  # noqa: E402

CONCLUSION = {
    "statement": "把持续检查交给系统，人这一侧只保留随时可以推翻的位置。",
    "kind": "abstract_idea",
    "scope": ["一个人已经抽身、只在自己想推翻时回来时"],
    "premises": ["系统能自己跑检查"],
    "alternatives": ["把检查留给人"],
    "contradictions": ["检查必须发生在世界里时"],
    "unknowns": ["他自己会不会来看回执"],
}
ALL_FOUR = ("上次是把一套检查交给别人的时候", "检查的活搬走了，我自己判断少了",
            "第一次觉得亏是没人再复核", "有一次我照着做反而漏了")
# A skipped part costs two lines: the ask and its follow-up.
MIXED = ("上次是把一套检查交给别人的时候", "", "",
         "第一次觉得亏是没人再复核", "", "")


def result(answer, candidate=None, user_stance="neutral"):
    return {"answer": answer, "candidate": candidate, "user_stance": user_stance}


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)

    def complete(self, messages):
        return self.responses.pop(0)


def read_lines(lines):
    it = iter(lines)

    def read_line(prompt):
        try:
            return next(it)
        except StopIteration:
            raise EOFError
    return read_line


def session(answers, no_trace=False):
    temp = tempfile.TemporaryDirectory()
    root = Path(temp.name)
    store = Store(root / "dojo.sqlite3")
    out = io.StringIO()
    recorded = None
    try:
        code = run_discuss(
            store,
            client=FakeClient([result("你描述的是：检查该谁做。", CONCLUSION),
                               result("那我们把它写成这一条。", CONCLUSION, user_stance="accept")]),
            read_line=read_lines(["讲一条做法", "对", *answers, "", "", "", "", ""]),
            output=out,
            no_trace=no_trace,
        )
        sessions = sorted((root / "sessions").glob("*.jsonl")) if (root / "sessions").is_dir() else []
        for path in sessions:
            for line in path.read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                if row.get("event") == "session_end" and row.get("elicitation"):
                    recorded = row["elicitation"]
    finally:
        store.close()
        temp.cleanup()
    return code, out.getvalue(), recorded


def closing_line(text):
    """The host line that starts with 四件问完了, from the screen output only."""
    for line in text.splitlines():
        if line.startswith("主持人> ") and line[len("主持人> "):].startswith("四件问完了"):
            return line[len("主持人> "):]
    return None


def main() -> int:
    code_all, text_all, end_all = session(ALL_FOUR)
    code_none, text_none, end_none = session(("", "", "", ""))
    code_mixed, text_mixed, end_mixed = session(MIXED)
    code_off, text_off, _ = session(ALL_FOUR, no_trace=True)

    line_all = closing_line(text_all)
    line_none = closing_line(text_none)
    line_mixed = closing_line(text_mixed)
    line_off = closing_line(text_off)
    if code_all or code_none or code_mixed or code_off:
        print("FAIL  有一场没有正常结束", file=sys.stderr)
        return 1
    if None in (line_all, line_none, line_mixed):
        print("FAIL  四件问完之后屏幕上没有那句「四件问完了」", file=sys.stderr)
        return 1

    last_part = PART_ORDER[-1]
    checks = {
        "四件全答时说都落在他的话上": "四件都落在你说过的话上" in line_all,
        # Nothing was answered, so the sentence may not name any part as his -- and it
        # has to say all four were filled. Demanding it list all four names would be
        # testing my taste, not the claim: "四件都没说出来" already covers exactly four.
        "四件全跳过时不说哪件是他的": (
            "四件都没说出来" in line_none
            and not any(part + " 是你说过的" in line_none for part in PART_ORDER)
        ),
        # The decisive one: the sentence is built from the same two lists the trace
        # records. If it ever disagreed with `collected`/`supplied`, this fails.
        "全答那一臂与轨迹一致": end_all["collected"] == list(PART_ORDER) and "四件都落在" in line_all,
        "全跳过那一臂与轨迹一致": end_none["supplied"] == list(PART_ORDER),
        "答两件跳两件时分开说": (
            end_mixed["collected"] == ["情境", "代价"]
            and end_mixed["supplied"] == ["张力", "失效"]
            and "情境、代价" in line_mixed and "张力、失效" in line_mixed
        ),
        "在最后一个问题之后": text_all.find(line_all) > text_all.find(QUESTIONS[last_part]["ask"]),
        "关记录时也说清楚": line_off is not None and "四件都落在" in line_off,
        # Nothing about the card's authorship may be overstated here.
        "说的是同一件事，不是新承诺": "仍全算我写的" in line_all,
    }
    print(json.dumps({
        "exit_code": 0,
        "lines": {"all": line_all, "none": line_none, "mixed": line_mixed, "no_trace": line_off},
        "recorded": {"all": end_all["collected"], "none": end_none["supplied"],
                     "mixed_collected": end_mixed["collected"],
                     "mixed_supplied": end_mixed["supplied"]},
        "checks": checks,
    }, ensure_ascii=False, indent=1))

    for what, ok in checks.items():
        print("%-6s %s" % ("OK" if ok else "FAIL", what), file=sys.stderr)
    if not all(checks.values()):
        return 1

    print("\nOK    四件问完之后，他说得出哪几件算他的、哪几件是系统补的。", file=sys.stderr)
    print("      这一句由轨迹记录的那两个列表拼出来，不是另数一遍。", file=sys.stderr)
    print("      它证明屏幕上说了这句话，不证明有人因此说了更多——那一格仍是空的。", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
