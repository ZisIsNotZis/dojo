#!/usr/bin/env python3
"""Re-run this slice's claims. Exits non-zero if any of them is false.

    python3 docs/evidence/2026-11-27-typed-stop/verify.py

Offline, standard library only, no model calls, throwaway database.

Every screen claim is checked against the trace of the same session, because the defect
this slice removes was a receipt that described something the trace plainly did not
contain.
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from dojo.discuss import run_discuss  # noqa: E402
from dojo.elicit import (  # noqa: E402
    PART_ORDER, QUESTIONS, classify_answer, is_stop_statement,
)
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
ANSWER_1 = "上次是把一套检查交给别人的时候"
WIND_DOWN = ("算了，先不说了", "先到这吧", "不想聊了", "就说这么多吧",
             "我没什么要补充的", "就这样吧")
# Short material: the length gate cannot protect these, only the whole-sentence match.
SHORT_MATERIAL = ("算了，没谈拢", "到这儿为止都顺利", "就这样吧，后来改了",
                  "先到这的人少", "说到这儿就够了", "先撤的人是他")
LONG_MATERIAL = ("说到这儿我想起来，那次是周三", "就这样吧，我们当时是这么定的",
                 "我算了吧，这事我后来没再提", "剩下的流程我都不讲给新人听")
KEEPS_SKIPPING = ("跳过", "这题先跳过", "先跳过这一题", "不想说", "不说了", "下一题")

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print("OK     " + label)
    else:
        print("FAIL   " + label + (("  —— " + detail) if detail else ""))
        failures.append(label)


class FakeClient:
    def __init__(self) -> None:
        self.responses = [
            {"answer": "你描述的是：检查该谁做。", "candidate": CONCLUSION,
             "user_stance": "neutral"},
        ]

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


def session(answers) -> tuple[int, str, list[dict], Path, tempfile.TemporaryDirectory]:
    temp = tempfile.TemporaryDirectory()
    root = Path(temp.name)
    store = Store(root / "dojo.sqlite3")
    output = io.StringIO()
    code = run_discuss(
        store,
        client=FakeClient(),
        read_line=read_lines(["讲一条做法", "/认可", *answers]),
        output=output,
    )
    store.close()
    paths = sorted((root / "sessions").glob("*.jsonl"))
    records = [json.loads(line) for line in paths[0].read_text(encoding="utf-8").splitlines()]
    return code, output.getvalue(), records, paths[0], temp


def closing(text: str) -> str:
    for line in text.splitlines():
        body = line[len("主持人> "):] if line.startswith("主持人> ") else ""
        if body.startswith("四件问完了") or body.startswith("问到这里停了"):
            return body
    return ""


def end_record(records: list[dict]) -> dict:
    for row in records:
        if row.get("event") == "session_end":
            return row["elicitation"]
    return {}


def events(records: list[dict]) -> list[dict]:
    return [row for row in records if row.get("event") == "elicitation"]


def main() -> int:
    # S1--S3: the declared reading, on a corpus, before any session runs.
    check("S1 六句收场话都读成「说到这儿为止」",
          all(classify_answer(p) == "stop" and is_stop_statement(p) for p in WIND_DOWN),
          repr([(p, classify_answer(p)) for p in WIND_DOWN]))
    check("S2 短的、带内容的话（只有整句匹配能护住）仍是材料",
          all(classify_answer(p) == "answer" for p in SHORT_MATERIAL),
          repr([(p, classify_answer(p)) for p in SHORT_MATERIAL if classify_answer(p) != "answer"]))
    check("S3 长一点的、带时间/人/结果的收场词句仍是材料",
          all(classify_answer(p) == "answer" for p in LONG_MATERIAL),
          repr([(p, classify_answer(p)) for p in LONG_MATERIAL if classify_answer(p) != "answer"]))
    check("S3b 原有的跳过说法一个没变",
          all(classify_answer(p) == "skip" for p in KEEPS_SKIPPING),
          repr([(p, classify_answer(p)) for p in KEEPS_SKIPPING if classify_answer(p) != "skip"]))
    check("S3c 「不想说」是这一题不答，「不想聊了」是这场不聊了",
          classify_answer("不想说") == "skip" and classify_answer("不想聊了") == "stop")

    # S4--S7: the real entry point, screen against trace.
    seen_screens = []
    for phrase in WIND_DOWN:
        code, text, records, _path, temp = session((ANSWER_1, phrase))
        try:
            end = end_record(records)
            line = closing(text)
            rows = events(records)
            seen_screens.append((phrase, line))
            check(f"S4「{phrase}」没有进材料（collected 只有情境）",
                  end.get("collected") == ["情境"], repr(end.get("collected")))
            check(f"S4b「{phrase}」没有被记成跳过或答不出来",
                  end.get("skipped") == [] and end.get("supplied") == [],
                  repr((end.get("skipped"), end.get("supplied"))))
            check(f"S4c「{phrase}」在轨迹里是 reading=stop，落在张力那题上",
                  bool(rows) and rows[-1].get("reading") == "stop"
                  and rows[-1].get("part") == "张力",
                  repr(rows[-1].get("reading")) if rows else "没有事件")
            check(f"S5「{phrase}」的回执说「说到这儿为止」",
                  "问到 张力 时你说到这儿为止" in line, line)
            check(f"S5b「{phrase}」的回执没有说「你结束了输入」",
                  "你结束了输入" not in line, line)
            check(f"S5c「{phrase}」的回执没有说「你答了 情境、张力」",
                  "你答了 情境、张力" not in line, line)
            check(f"S5d「{phrase}」的回执没有提跳过（他根本没提）",
                  "你提到跳过" not in line, line)
            check(f"S5e「{phrase}」的回执没有说「四件问完了」",
                  "四件问完了" not in line, line)
            host = [l[len("主持人> "):] for l in text.splitlines()
                    if l.startswith("主持人> ")]
            check(f"S6「{phrase}」之后代价那题没有被问出口",
                  QUESTIONS["代价"]["ask"] not in host)
            check(f"S7「{phrase}」以正常退出码结束", code == 0, str(code))
        finally:
            temp.cleanup()

    # S8: the same ending, in words and by end-of-input, gives one story.
    from dojo.discuss import _load_resume_trace  # noqa: E402

    code, text, records, path, temp = session((ANSWER_1, "先到这吧"))
    try:
        end = end_record(records)
        resumed = _load_resume_trace(path)
        check("S8 说出收场话之后留下的轨迹，续跑读出来是同一个结论",
              end.get("collected") == resumed["elicitation_collected"]
              and end.get("supplied") == resumed["elicitation_supplied"]
              and resumed["elicitation_collected"] == ["情境"],
              repr((end.get("collected"), resumed["elicitation_collected"])))
        check("S8b 收场话结束时会话真的结束了",
              "讨论已结束。" in text and any(
                  row.get("event") == "session_end" for row in records))
    finally:
        temp.cleanup()

    # S9--S11: the number he said vs. the number there was.
    code, text, records, path, temp = session((ANSWER_1, "接下来五题都先不答"))
    try:
        end = end_record(records)
        line = closing(text)
        check("S9 declined_count 现在是实际搁下的件数", end.get("declined_count") == 2,
              repr(end.get("declined_count")))
        check("S9b 他说的那个数被单独留下", end.get("declined_stated") == 5,
              repr(end.get("declined_stated")))
        check("S9c 回执把两个事实都说出来",
              "你说接下来 5 题先不答，剩下只有 代价、失效" in line, line)
        resumed = _load_resume_trace(path)
        check("S9d 续跑两个数都在", resumed["elicitation_declined_count"] == 2
              and resumed["elicitation_declined_stated"] == 5,
              repr((resumed["elicitation_declined_count"],
                    resumed["elicitation_declined_stated"])))
    finally:
        temp.cleanup()

    code, text, records, _path, temp = session((ANSWER_1, "接下来两题先不答"))
    try:
        end = end_record(records)
        line = closing(text)
        check("S10 说的数正好等于剩下的数时，两个字段一致且回执只说一遍",
              end.get("declined_count") == 2 and end.get("declined_stated") == 2
              and "你说接下来 2 题先不答 代价、失效" in line and "剩下只有" not in line,
              repr((end.get("declined_count"), end.get("declined_stated"), line)))
    finally:
        temp.cleanup()

    # S11: the card is still not touched by any of this.
    code, text, records, _path, temp = session((ANSWER_1, "先到这吧"))
    try:
        end = end_record(records)
        check("S11 卡片仍是提问前那句，字全算系统写的（这一段没改它）",
              end.get("authorship") == "系统的", repr(end.get("authorship")))
    finally:
        temp.cleanup()

    print()
    if failures:
        print("%d 项不成立。" % len(failures))
        return 1
    print("全部成立。")
    print()
    print("真实入口上六种收场话的回执（可整段对照）：")
    for phrase, line in seen_screens:
        print(f"  「{phrase}」\n    {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
