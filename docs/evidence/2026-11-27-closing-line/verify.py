#!/usr/bin/env python3
"""四件问完之后，屏幕上那句话说的是不是真的。

    python3 docs/evidence/2026-11-27-closing-line/verify.py

只读、离线、不联网、不写库。它替一个读者跑真入口 `run_discuss`，回答五件事：

    1. 四种结局（全答 / 全跳 / 答跳过答 / 全部空着）屏幕上分得开，且与轨迹里记的
       `collected`/`skipped`/`supplied` 逐件对上。
    2. 「跳过」是普通话里的跳过请求，被当成跳过，而不是被当成回答。
    3. 这句话不声称回答进了卡片——库的每张表在问答前后逐行相同，卡片是提问前写下的。
    4. 提前结束输入的人（开场就邀请的那条路）也拿到回执，且不谎称四件问完了。
    5. `--no-trace` 下不说「留在本场记录里」。

退出码 0 = 五项都成立；1 = 有一项不成立，并指出是哪一项。
JSON 只用来给人看；判成败只看 shell 退出码（上一版把 `exit_code: 0` 写死在 JSON 里）。
"""
from __future__ import annotations

import io
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from dojo.discuss import run_discuss  # noqa: E402
from dojo.elicit import PART_ORDER, QUESTIONS, classify_answer  # noqa: E402
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
SKIP = "先跳过这一题"
MIXED = ("上次是把一套检查交给别人的时候", SKIP, "", "", "有一次我照着做反而漏了")


def result(answer, candidate=None, user_stance="neutral"):
    return {"answer": answer, "candidate": candidate, "user_stance": user_stance}


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)

    def complete(self, messages):
        return self.responses.pop(0)


def read_lines(lines):
    iterator = iter(lines)

    def read_line(prompt):
        try:
            return next(iterator)
        except StopIteration:
            raise EOFError
    return read_line


def snapshot(database):
    connection = sqlite3.connect(database)
    try:
        tables = [row[0] for row in connection.execute(
            "select name from sqlite_master where type='table' order by name")]
        return {table: connection.execute(f"select * from {table}").fetchall()
                for table in tables}
    finally:
        connection.close()


def session(answers, no_trace=False, record_rows=False):
    temp = tempfile.TemporaryDirectory()
    root = Path(temp.name)
    database = root / "dojo.sqlite3"
    store = Store(database)
    out = io.StringIO()
    recorded = None
    rows = []
    inner = read_lines(["讲一条做法", "对", *answers])

    def read_line(prompt):
        if record_rows:
            rows.append(snapshot(database))
        return inner(prompt)

    try:
        code = run_discuss(
            store,
            client=FakeClient([result("你描述的是：检查该谁做。", CONCLUSION),
                               result("那我们把它写成这一条。", CONCLUSION, user_stance="accept")]),
            read_line=read_line,
            output=out,
            no_trace=no_trace,
        )
        if record_rows:
            rows.append(snapshot(database))
        for path in sorted((root / "sessions").glob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                if row.get("event") == "session_end" and row.get("elicitation"):
                    recorded = row["elicitation"]
    finally:
        store.close()
        temp.cleanup()
    return code, out.getvalue(), recorded, rows


def host(text):
    return [line[len("主持人> "):] for line in text.splitlines()
            if line.startswith("主持人> ")]


def closing(text):
    for body in host(text):
        if body.startswith("四件问完了") or body.startswith("问到这里停了"):
            return body
    return None


def named(line, marker):
    """The parts named right after `marker`, in the order they appear on screen."""
    if marker not in line:
        return []
    rest = line.split(marker, 1)[1]
    for stop in ("；", "。"):
        rest = rest.split(stop, 1)[0]
    return [part for part in PART_ORDER if part in rest]


def main() -> int:
    code_all, text_all, end_all, rows = session(ALL_FOUR, record_rows=True)
    code_skip, text_skip, end_skip, _ = session((SKIP,) * 4)
    code_mixed, text_mixed, end_mixed, _ = session(MIXED)
    code_blank, text_blank, end_blank, _ = session(("",) * 8)
    code_stop, text_stop, end_stop, _ = session(("上次是把一套检查交给别人的时候",))
    code_off, text_off, _, _ = session((SKIP,) * 4, no_trace=True)

    if any((code_all, code_skip, code_mixed, code_blank, code_stop, code_off)):
        print("FAIL  有一场没有正常结束", file=sys.stderr)
        return 1

    line_all, line_skip = closing(text_all), closing(text_skip)
    line_mixed, line_blank = closing(text_mixed), closing(text_blank)
    line_stop, line_off = closing(text_stop), closing(text_off)
    for label, line in (("全答", line_all), ("全跳", line_skip), ("答/跳/没答", line_mixed),
                        ("全部空着", line_blank), ("提前结束", line_stop),
                        ("--no-trace", line_off)):
        if line is None:
            print("FAIL  %s那一场结束时屏幕上没有那句回执" % label, file=sys.stderr)
            return 1

    # The card exists before the first question and never changes afterwards.
    with_card = [row for row in rows if row.get("candidates")]
    card_fixed = bool(with_card) and all(row == with_card[0] for row in with_card)

    checks = {
        "全答时与轨迹一致": (
            end_all["collected"] == list(PART_ORDER) and end_all["skipped"] == []
            and "四件你都答了" in line_all
        ),
        "全跳时与轨迹一致且不说答了": (
            end_skip["collected"] == [] and end_skip["skipped"] == list(PART_ORDER)
            and "你说跳过" in line_skip and "你答了" not in line_skip
            and "四件都落在你说过的话上" not in text_skip
        ),
        "答/跳/没答三种结局分得开": (
            end_mixed["collected"] == ["情境", "失效"]
            and end_mixed["skipped"] == ["张力"]
            and end_mixed["supplied"] == ["代价"]
            and named(line_mixed, "你答了") == ["情境", "失效"]
            and named(line_mixed, "你说跳过") == ["张力"]
            and named(line_mixed, "没答出来") == ["代价"]
        ),
        "全部空着时不谈回答去了哪": (
            end_blank["collected"] == [] and end_blank["supplied"] == list(PART_ORDER)
            and "你答了" not in line_blank and "这些回答" not in line_blank
        ),
        "跳过请求被识别为跳过而不是回答": (
            classify_answer(SKIP) == "skip"
            and classify_answer("我跳过这一步的时候就会出错") == "answer"
        ),
        "不声称回答写进了卡片": (
            card_fixed and "没有写进卡片" in line_all
            and "卡片是提问前写下的那句" in line_all and "补上了" not in line_all
        ),
        "提前结束也拿得到回执，且不说四件问完了": (
            end_stop["collected"] == ["情境"]
            and "你答了 情境" in line_stop and "没问到" in line_stop
            and "四件问完了" not in line_stop
        ),
        "关记录时不说留在本场记录里": (
            "你说跳过" in line_off and "留在本场记录" not in line_off
        ),
        "问法没有被重复": (
            [line for line in host(text_skip)
             if line in [QUESTIONS[part]["ask"] for part in PART_ORDER]]
            == [QUESTIONS[part]["ask"] for part in PART_ORDER]
        ),
    }
    print(json.dumps({
        "lines": {"all": line_all, "skip": line_skip, "mixed": line_mixed,
                  "blank": line_blank, "stopped": line_stop, "no_trace": line_off},
        "recorded": {
            "all": end_all["collected"], "skip": end_skip["skipped"],
            "mixed_collected": end_mixed["collected"],
            "mixed_skipped": end_mixed["skipped"],
            "mixed_supplied": end_mixed["supplied"],
            "stopped_collected": end_stop["collected"],
        },
        "card_unchanged_during_questions": card_fixed,
        "checks": checks,
    }, ensure_ascii=False, indent=1))

    for what, ok in checks.items():
        print("%-6s %s" % ("OK" if ok else "FAIL", what), file=sys.stderr)
    if not all(checks.values()):
        return 1

    print("\nOK    四件问完之后，屏幕上说得出每一件怎么了、回答去了哪、卡片动没动。", file=sys.stderr)
    print("      它证明这句话与轨迹、与库三方对得上。", file=sys.stderr)
    print("      它不证明有人因此多说了一件——那一格仍然是空的。", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
