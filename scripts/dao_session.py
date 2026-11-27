#!/usr/bin/env python3
"""Export a completed discuss JSONL trace as a probe note and provenance record."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dao_life import NoteError, _parse_note  # noqa: E402
from dojo.tracefile import (  # noqa: E402
    LINE_BREAK_CODEPOINTS, escape_line_breaks, split_lines,
)

PARTS = ("情境", "张力", "代价", "失效")
KEYS = {"情境":"situation", "张力":"tension", "代价":"price", "失效":"off"}

class Refusal(ValueError):
    pass

def answered(row: dict) -> bool:
    """Whether the trace row itself records that the person's words answered this question.

    Current `discuss` writes `collected: reading == "answer"` on every elicitation row and
    `promoted: False` unconditionally, so `collected`/`reading` are the only honest
    evidence; `promoted` is consulted only on traces written before those fields existed.
    """
    if "collected" in row:
        return row.get("collected") is True
    if "reading" in row:
        return row.get("reading") == "answer"
    return row.get("promoted") is True

def load_trace(path: Path, person: str, sample: str):
    if sample not in {"acquaintances", "strangers"}: raise Refusal("sample: 只能是 acquaintances 或 strangers")
    if not person.strip(): raise Refusal("person: 不得为空")
    try:
        trace_bytes = path.read_bytes()
        raw = trace_bytes.decode("utf-8")
    except (OSError, UnicodeDecodeError) as e: raise Refusal(f"trace: {e}") from None
    if not raw.strip(): raise Refusal("empty trace: 轨迹为空")
    # `\n` ends a record. `splitlines()` also breaks on U+0085/U+2028/U+2029, which
    # `json.dumps` leaves raw inside a string; this exporter was one of the readers that
    # cut the program's own trace in half.
    try: rows = [json.loads(line) for line in split_lines(raw) if line.strip()]
    except json.JSONDecodeError as e: raise Refusal(f"trace JSON: 第 {e.lineno} 行格式错误") from None
    end_rows = [r for r in rows if r.get("event") == "session_end"]
    if not end_rows: raise Refusal("session_end: 缺少会话结束记录")
    end = end_rows[-1]
    elicit_indices = [i for i, r in enumerate(rows) if r.get("event") == "elicitation"]
    if not elicit_indices: raise Refusal("elicitation: 没有逐件回答记录")
    first_elicit = elicit_indices[0]
    written_indices = [i for i, r in enumerate(rows[:first_elicit]) if r.get("decision") == "written"]
    if not written_indices:
        raise Refusal("结论: 出现 elicitation 记录，但之前没有 decision == 'written' 的轮次")
    written_index = written_indices[0]
    written_round = rows[written_index]
    elicits = [rows[i] for i in elicit_indices if i > written_index]
    if len(elicits) != len(elicit_indices):
        raise Refusal("elicitation: 逐件回答出现在已写下的结论之前")
    # This discussion flow elicits exactly the first written conclusion, not later cards.
    candidates = [r.get("candidate") for r in rows[written_index:first_elicit + 1] if isinstance(r.get("candidate"), dict)]
    statement = next((c.get("statement") for c in reversed(candidates) if isinstance(c.get("statement"), str) and c["statement"].strip()), None)
    if not statement:
        raise Refusal("方向: 会话里没有写下这条结论的方向")
    bypart = {}
    for r in elicits:
        if r.get("part") in PARTS: bypart.setdefault(r["part"], []).append(r)
    for p in PARTS:
        events = bypart.get(p, [])
        # A part is exportable only when the trace itself records that the person's words
        # answered it. Use the last such row; if any later row for this part is not
        # collected, refuse rather than resurrect an earlier answer.
        last_answered = next(
            ((index, row) for index, row in reversed(list(enumerate(events))) if answered(row)),
            None,
        )
        if last_answered is None:
            raise Refusal(f"{p}: 未晋升或没有有效回答——轨迹里这件没有一条记成答过的回答（collected 不是 true）")
        last_index, last_row = last_answered
        if last_index != len(events) - 1:
            later = events[last_index + 1]
            raise Refusal(
                f"{p}: 这件最后一条记录没有被记成答过（reading={later.get('reading')!r}），"
                "不把更早的那句当答案"
            )
        answer = last_row.get("answer")
        if not isinstance(answer, str) or not answer.strip():
            raise Refusal(f"{p}: 晋升回答为空")
        if "\n" in answer or "\r" in answer:
            raise Refusal(f"{p}: 回答含换行，探针笔记无法逐字承载")
        # U+0085 / U+2028 / U+2029 are line breaks for `str.splitlines()`, which every
        # note reader uses, and `json.dumps` leaves them raw -- so a pasted answer carrying
        # one was written into a note that then parsed as fields it does not have (measured:
        # "张力 p-T1 少了「方向」这一格" about a sentence that was in the file). Same rule as
        # the trace writer: one record, one line.
        if any(codepoint in answer for codepoint in LINE_BREAK_CODEPOINTS):
            raise Refusal(f"{p}: 回答里带 Unicode 行分隔符（U+0085/U+2028/U+2029），"
                          "探针笔记无法逐字承载")
        if p == "张力" and any(char in answer for char in ('|', '"')):
            raise Refusal('张力: 回答含「|」或引号，原话字段无法逐字承载')
        bypart[p] = last_row
    tension = bypart["张力"]["answer"]
    raw_sides = re.split(r"\s*(?:↔|⇄|<->| vs\. | versus )\s*", tension)
    if len(raw_sides) == 1:
        raise Refusal("张力: 缺少左侧和右侧的分隔表达（需 A ↔ B）")
    if len(raw_sides) != 2:
        raise Refusal("张力: 左右侧超过两边（需正好 A ↔ B）")
    sides = [side.strip() for side in raw_sides]
    missing_sides = [label for label, side in zip(("左侧", "右侧"), sides) if not side]
    if missing_sides:
        raise Refusal(f"张力: {'、'.join(missing_sides)}为空")
    rounds = [r for r in rows if isinstance(r.get("user"), str)]
    # Elicitation answers are the trace's explicit verbatim user-input fields.
    inputs = rounds + [r for r in elicits if isinstance(r.get("answer"), str)]
    if not inputs: raise Refusal("逐字: 轨迹没有用户输入")
    for r in inputs:
        if not r.get("at"): raise Refusal("timestamp: 用户输入记录缺 at")
    def stamp(value):
        try: return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, AttributeError): raise Refusal(f"timestamp: 无效时间 {value!r}") from None
    timed = [(stamp(r["at"]), r) for r in inputs]
    timed.sort(key=lambda x:x[0])
    first,last = timed[0][0],timed[-1][0]
    minutes=max(0, int((last-first).total_seconds() // 60))
    date=first.date().isoformat()
    texts = [r.get("user", r.get("answer", "")) for _,r in timed]
    offsets=[]
    for at,r in timed:
        delta=max(0,int((at-first).total_seconds()))
        offsets.append((f"{delta//60:02d}:{delta%60:02d}",r.get("user", r.get("answer", ""))))
    for part,r in bypart.items():
        answer=r["answer"]
        if not any(answer in text for text in texts) or (isinstance(r.get("user"), str) and answer not in r["user"]):
            raise Refusal(f"逐字: {part} 回答不是该轨迹 user 输入的逐字子串")
    tension_event=bypart["张力"]
    anchor=next((m for m,t in offsets if tension_event["answer"] in t), offsets[0][0])
    sid=Path(path).stem
    card=(end.get("elicitation") or {}).get("entry") or (end.get("saved") or [None])[0]
    note=[f"person: {person}",f"date: {date}",f"minutes: {minutes}",f"sample: {sample}","","## 逐字"]
    note += [f"[{m}] {text}" for m,text in offsets]
    note += ["","## 张力"]
    note.append(f'- [{person}-T1] {sides[0]} ↔ {sides[1]} | 情境: {bypart["情境"]["answer"]} | 方向: {statement} | 原话: "{tension}" | 锚: {anchor}')
    note_text = "\n".join(escape_line_breaks(line) for line in note) + "\n"
    try:
        with tempfile.TemporaryDirectory(prefix="dao-session-check-") as temp_dir:
            note_path = Path(temp_dir) / "note.md"
            note_path.write_text(note_text, encoding="utf-8")
            _parse_note(note_path)
    except NoteError as exc:
        raise Refusal(f"note.md: {exc}") from None
    session={"session_id":sid,"person":person,"date":date,"minutes":minutes,"sample":sample,"card_id":card,"trace_sha256":hashlib.sha256(trace_bytes).hexdigest(),"note_sha256":hashlib.sha256(note_text.encode("utf-8")).hexdigest(),"tensions":[{"id":f"{person}-T1","pair":f"{sides[0]} ↔ {sides[1]}","parts":{KEYS[p]:{"promoted":True,"answer":bypart[p]["answer"]} for p in PARTS}}]}
    return note_text, session

def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument("--trace",required=True,type=Path); parser.add_argument("--out",required=True,type=Path)
    parser.add_argument("--person",required=True); parser.add_argument("--sample",required=True); parser.add_argument("--check",action="store_true")
    args=parser.parse_args(argv)
    try:
        note,session=load_trace(args.trace,args.person,args.sample)
        if not args.check:
            args.out.mkdir(parents=True,exist_ok=True)
            (args.out/"note.md").write_text(note,encoding="utf-8")
            (args.out/"session.json").write_text(json.dumps(session,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print("OK" if args.check else f"写入 {args.out}/note.md 与 session.json")
        if not args.check:
            print(f"下一步：补齐 {args.out}/extraction.json，再运行 python3 scripts/dao_life.py {args.out} --vocabulary docs/dao/vocabulary.json --check")
        return 0
    except Refusal as e:
        print(str(e),file=sys.stderr); return 2
if __name__ == "__main__": raise SystemExit(main())
