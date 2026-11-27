#!/usr/bin/env python3
"""四件问法：他做了什么，回执就说什么。

    python3 docs/evidence/2026-11-27-receipt-truth/verify.py

只读、离线、不联网、不写库。替一个读者跑真入口 `run_discuss`，回答六件事：

    1. 答完一件、在下一问结束输入：回执说「问到 X 时你结束了输入」，
       不说「没答出来 X」（那是在说他答不上来）。
    2. 「这几题我想先跳过」：不记为他的回答，后面几件不再问，回执单列它们。
    3. 「接下来两题先跳过」：按他说的数字只搁下两件，剩下的照问。
    4. 「剩下的流程我都不讲给新人听」：仍算他的原话，四件照问。
    5. 每一件在回执里只出现一次，且只用一种结局词。
    6. 卡片在问答前后逐行相同，回执不声称回答进了卡片。

退出码 0 = 六项都成立；1 = 有一项不成立，并指出是哪一项。
判成败只看 shell 退出码；JSON 只给人看。
"""
from __future__ import annotations

import io
import json
import re
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from dojo.discuss import run_discuss  # noqa: E402
from dojo.elicit import PART_ORDER, QUESTIONS, classify_answer, skip_scope  # noqa: E402
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
STOPPED = ("上次是把一套检查交给别人的时候",)
DROP_REST = ("上次是把一套检查交给别人的时候", "这几题我想先跳过")
DROP_TWO = ("上次是把一套检查交给别人的时候", "接下来两题先跳过")
MATERIAL = ("上次是把一套检查交给别人的时候：剩下的流程我都不讲给新人听",
            "检查的活搬走了，我自己判断少了",
            "第一次觉得亏是没人再复核",
            "有一次我照着做反而漏了")
OUTCOME_WORDS = ("你答了", "你说跳过", "时你结束了输入", "先不答", "没答出来", "没问到")


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


def session(answers):
    temp = tempfile.TemporaryDirectory()
    root = Path(temp.name)
    database = root / "dojo.sqlite3"
    store = Store(database)
    out = io.StringIO()
    rows = []
    inner = read_lines(["讲一条做法", "对", *answers])

    def read_line(prompt):
        rows.append(snapshot(database))
        return inner(prompt)

    try:
        code = run_discuss(
            store,
            client=FakeClient([result("你描述的是：检查该谁做。", CONCLUSION),
                               result("那我们把它写成这一条。", CONCLUSION, user_stance="accept")]),
            read_line=read_line,
            output=out,
        )
        rows.append(snapshot(database))
        events, end = [], None
        for path in sorted((root / "sessions").glob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                if row.get("event") == "elicitation":
                    events.append(row)
                elif row.get("event") == "session_end":
                    end = row
    finally:
        store.close()
        temp.cleanup()
    return code, out.getvalue(), events, end, rows


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


def part_counts(line):
    return {part: sum(part in named(line, word) for word in OUTCOME_WORDS)
            for part in PART_ORDER}


def main() -> int:
    code_stop, text_stop, events_stop, end_stop, rows_stop = session(STOPPED)
    code_rest, text_rest, events_rest, end_rest, rows_rest = session(DROP_REST)
    code_two, text_two, events_two, end_two, rows_two = session(DROP_TWO)
    code_mat, text_mat, events_mat, end_mat, rows_mat = session(MATERIAL)

    if any((code_stop, code_rest, code_two, code_mat)):
        print("FAIL  有一场没有正常结束", file=sys.stderr)
        return 1

    line_stop, line_rest = closing(text_stop), closing(text_rest)
    line_two, line_mat = closing(text_two), closing(text_mat)
    for label, line in (("提前结束", line_stop), ("这几题先跳过", line_rest),
                        ("接下来两题", line_two), ("讲一条做法", line_mat)):
        if line is None:
            print("FAIL  %s那一场屏幕上没有回执" % label, file=sys.stderr)
            return 1

    summary_stop = end_stop["elicitation"]
    summary_rest = end_rest["elicitation"]
    summary_two = end_two["elicitation"]
    summary_mat = end_mat["elicitation"]

    with_card = [row for row in rows_stop if row.get("candidates")]
    card_fixed = bool(with_card) and all(row == with_card[0] for row in with_card)

    checks = {
        "停在一问上不说他不会答": (
            summary_stop["collected"] == ["情境"]
            and summary_stop["supplied"] == []
            and "问到 张力 时你结束了输入" in line_stop
            and "没答出来" not in line_stop
        ),
        "「这几题先跳过」不是回答，剩下的不再问": (
            summary_rest["collected"] == ["情境"]
            and summary_rest["skipped"] == ["张力"]
            and summary_rest["declined"] == ["代价", "失效"]
            and summary_rest["supplied"] == []
            and "你答了 情境" in line_rest and "你答了 情境、张力" not in line_rest
            and QUESTIONS["代价"]["ask"] not in host(text_rest)
            and QUESTIONS["失效"]["ask"] not in host(text_rest)
        ),
        "「接下来两题」只搁下两件": (
            summary_two["declined"] == ["代价", "失效"]
            and "你说接下来 2 题先不答 代价、失效" in line_two
            # The request is kept in the trace as what it was (a skip_rest event), never
            # as material: it must not land in collected/supplied, and its event must
            # carry collected=False and the skip_rest reading.
            and all(row["answer"] != "这几题我想先跳过"
                    for row in events_rest if row["reading"] == "answer")
            and any(row["answer"] == "这几题我想先跳过"
                    and row["reading"] == "skip_rest" and row["collected"] is False
                    for row in events_rest)
        ),
        "讲一条做法仍算他的原话": (
            summary_mat["collected"] == list(PART_ORDER)
            and summary_mat["declined"] == []
            and events_mat[0]["reading"] == "answer"
            and events_mat[0]["answer"] == MATERIAL[0]
            and "四件你都答了" in line_mat
        ),
        "每件只有一个结局词": all(
            all(count <= 1 for count in part_counts(line).values())
            for line in (line_stop, line_rest, line_two, line_mat)
        ),
        "不声称回答进了卡片": (
            card_fixed and "没有写进卡片" in line_mat
            and "卡片是提问前写下的那句" in line_mat
        ),
    }
    print(json.dumps({
        "lines": {"stopped": line_stop, "drop_rest": line_rest,
                  "drop_two": line_two, "material": line_mat},
        "recorded": {
            "stopped": {"collected": summary_stop["collected"],
                        "supplied": summary_stop["supplied"]},
            "drop_rest": {"collected": summary_rest["collected"],
                          "skipped": summary_rest["skipped"],
                          "declined": summary_rest["declined"]},
            "drop_two": {"declined": summary_two["declined"]},
            "material": {"collected": summary_mat["collected"]},
        },
        "scope_readings": {
            "这几题我想先跳过": skip_scope("这几题我想先跳过"),
            "接下来两题先跳过": skip_scope("接下来两题先跳过"),
            "剩下的流程我都不讲": classify_answer("剩下的流程我都不讲"),
        },
        "card_unchanged_during_questions": card_fixed,
        "checks": checks,
    }, ensure_ascii=False, indent=1))

    for what, ok in checks.items():
        print("%-6s %s" % ("OK" if ok else "FAIL", what), file=sys.stderr)
    if not all(checks.values()):
        return 1
    print("\nOK    每一件在回执里只用一种结局词，且与轨迹里记的那一件对得上。", file=sys.stderr)
    print("      它不证明有人因此多答了一件，也不证明识别覆盖了真人的说法——", file=sys.stderr)
    print("      这两格仍然是空的，见 SUMMARY.md。", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
