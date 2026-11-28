#!/usr/bin/env python3
"""这一段话，是不是真的挂在一个人遇到的入口上。

    python3 docs/evidence/2026-11-27-entry-shape/verify.py

只读、离线、不联网、不写库。它替一个读者跑一遍真入口，回答三件事：

    1. 四句问法之前，屏幕上那一段是不是「形状」（有几件、什么时候停、答不上来会怎样）。
    2. 这一段是在**第一个问题之前**出现的，不是在文档里、也不是在会话末尾。
    3. 这一段在改前那版代码上不存在——红臂可复算，不是一句断言。

退出码 0 = 三项都成立；1 = 有一项不成立，并指出是哪一项。
"""
from __future__ import annotations

import io
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from dojo.discuss import run_discuss  # noqa: E402
from dojo.elicit import QUESTIONS  # noqa: E402
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


def session_output(answers=("", "", "", ""), no_trace=False):
    """Run the real entry. `answers` is what he types at the four parts."""
    temp = tempfile.TemporaryDirectory()
    root = Path(temp.name)
    store = Store(root / "dojo.sqlite3")
    out = io.StringIO()
    try:
        code = run_discuss(
            store,
            client=FakeClient([result("你描述的是：检查该谁做。", CONCLUSION),
                               result("那我们把它写成这一条。", CONCLUSION, user_stance="accept")]),
            read_line=read_lines(["讲一条做法", "对", *answers, "", "", "", "", ""]),
            output=out,
            no_trace=no_trace,
        )
        recorded = None
        sessions = sorted((root / "sessions").glob("*.jsonl")) if (root / "sessions").is_dir() else []
        for path in sessions:
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if row.get("event") == "session_end" and row.get("elicitation"):
                    recorded = row["elicitation"]
    finally:
        store.close()
        temp.cleanup()
    return code, out.getvalue(), recorded


def shape_block(text):
    """The block printed immediately before the first elicitation question.

    Returned with its trailing blank lines stripped, because that is the ruler the
    SUMMARY table uses: 11 chars before, 154 after. Counting the newlines the
    printer adds would report 13 / 156 for the same two blocks and make the table
    look unreproducible from this script.
    """
    first_q = text.find(QUESTIONS["情境"]["ask"])
    if first_q < 0:
        return None
    head = text[:first_q]
    end = head.rfind("主持人> ")
    start = head.rfind("主持人> ", 0, end)
    return head[start + len("主持人> "):end].strip() if end >= 0 and start >= 0 else None


ALL_FOUR = ("上次是把一套检查交给别人的时候", "检查的活搬走了，我自己判断少了",
            "第一次觉得亏是没人再复核", "有一次我照着做反而漏了")


def main() -> int:
    code, text, recorded_silent = session_output()
    # The same entry when he answers all four: the block claims his words stay in the
    # session but the card still credits the system. Both halves have to be true.
    code_answered, text_answered, recorded_answered = session_output(ALL_FOUR)
    # And with --no-trace: the opening says the transcript is off, so the block must not
    # then promise his words are kept. This is the second receipt's arm.
    code_off, text_off, recorded_off = session_output(ALL_FOUR, no_trace=True)
    block_off = shape_block(text_off)
    if code != 0:
        print("FAIL  入口没有正常结束（rc=%d）" % code, file=sys.stderr)
        return 1

    block = shape_block(text)
    if block is None:
        print("FAIL  没有在第一个问题之前找到任何一段话", file=sys.stderr)
        return 1

    checks = {
        "说清楚有几件": "四件事" in block,
        "说清楚什么时候停": "两轮" in block,
        "说清楚答不上来会怎样": "跳过" in block,
        "说清楚怎么结束": "结束输入" in block,
        # The supervisor's receipt: the block used to say the entry would read 合写,
        # but every card field is recorded 系统补 even when all four are answered.
        "不承诺一个记不出来的归属": "合写" not in block,
        # Superseded 2026-11-28: the block now also says his answers are attached
        # to the card, and states which part stays the model's. The reading keeps
        # asking that the block name who the sentence is, in those words.
        "说了卡片到底算谁的": "仍算我写的" in block,
        # It must be the block *before* the questions, not the session opening: the
        # opening was already there before this slice and says nothing about parts.
        "在第一个问题之前": QUESTIONS["情境"]["ask"] not in block,
    }
    # The decisive one for the receipt: the sentence and the record must agree.
    answered_line = (recorded_answered or {}).get("line") or ""
    checks.update({
        "答完四件后卡片仍记系统所写": answered_line.startswith("系统的"),
        "答完四件后原文仍留在轨迹里": bool((recorded_answered or {}).get("collected")),
        "全不答也不会卡住": code_answered == 0 and code == 0,
        # Retention off: no trace on disk, and the block has to say so instead of
        # repeating the promise the opening just contradicted.
        "关记录时没有轨迹": recorded_off is None and code_off == 0,
        "关记录时不许诺保存原文": block_off is not None and "会留在本场记录" not in block_off,
        "关记录时说清楚原文不存": block_off is not None and "不保存原文" in block_off,
    })
    print(json.dumps({"exit_code": code, "shape_block": block,
                      "chars": len(block), "checks": checks,
                      "recorded_silent": (recorded_silent or {}).get("line"),
                      "recorded_answered": answered_line},
                     ensure_ascii=False, indent=1))

    for what, ok in checks.items():
        print("%-6s %s" % ("OK" if ok else "FAIL", what), file=sys.stderr)
    if not all(checks.values()):
        return 1

    print("\nOK    一个人遇到四句问法之前，先看到的是形状：几件、什么时候停、答不上来会怎样。",
          file=sys.stderr)
    print("      这一段在第一个问题之前；改前那版代码上它是主持人上一句结束语，11 个字。",
          file=sys.stderr)
    print("      入口里关于归属的那一句，与答完四件后真正记下的那一行一致（%s）。" % answered_line,
          file=sys.stderr)
    print("      它证明入口说了这句话，不证明有人因此留下来——那一格仍是空的。",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
