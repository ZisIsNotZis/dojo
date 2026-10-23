#!/usr/bin/env python3
"""一场跑在真讨论循环里的脚本化会话：零模型调用，被访者的每句都标出处。

它不测「答得好不好」，只测三件：四句问法是不是真的接在写入之后、问不出来是不是真的不填、
以及一场会话要花几轮。被访者是脚本：两句讨论是这场会话里他的话（由 harness 写、标明模拟），
四句回答里凡是能引到记录的原话都带出处，别的是「没答」。
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dojo.discuss import run_discuss  # noqa: E402
from dojo.elicit import QUESTIONS  # noqa: E402
from dojo.storage import Store  # noqa: E402

CONCLUSION = {
    "statement": "把持续检查交给系统，人这一侧只保留「随时可以推翻」的位置。",
    "kind": "abstract_idea",
    "scope": ["一个人已经抽身、只在自己想推翻时回来时"],
    "premises": ["系统能自己写下预测并跑"],
    "alternatives": ["把检查和提醒留给人"],
    "contradictions": ["检查必须发生在世界里时，这一格只能印未检"],
    "unknowns": ["他自己会不会来看回执"],
}

# 会话里他说的话。前两句是这场对话里的他（模拟，harness 写）；四句回答见下面的出处。
DISCUSSION = [
    ("讲一条做法", "把检查交给系统，我这边只留一个随时可以推翻的位置。"),
    ("对", "对，就这条。"),
]

ANSWERS = [
    ("情境", "user is already detached", "他的原话｜`docs/proposal-knowledge-network.md` 第 104 行"),
    ("张力", "He CAN challenge later, e.g. 'did you do simulation?', but not responsible for reminding that.",
     "他的原话｜同上"),
    ("代价", "", "没答"),
    ("失效", "", "没答"),
]


class ScriptedHost:
    """两轮模型回答：提出候选、接受并写入。零网络。"""

    def __init__(self):
        self.responses = [
            {"answer": "你讲的是「检查该谁做」：把它交给系统，人留一个推翻的位置。", "candidate": CONCLUSION, "user_stance": "neutral"},
            {"answer": "那就把这一条记成你现在的判断。", "candidate": CONCLUSION, "user_stance": "accept"},
        ]

    def complete(self, messages):
        return self.responses.pop(0)


def main(argv: list[str]) -> int:
    out = Path(argv[1]) if len(argv) > 1 else Path("docs/dao/elicitation/live-session-1.md")
    lines = []
    for _, text in DISCUSSION:
        lines.append(text)
    for _, answer, _ in ANSWERS:
        lines.append(answer)
        if not answer:
            lines.append("")  # 一问一答；没答的那一件再问一次换问法，也是空
    iterator = iter(lines)
    transcript_lines: list[str] = []

    def read_line(prompt: str) -> str:
        try:
            value = next(iterator)
        except StopIteration:
            raise EOFError
        transcript_lines.append(f"{prompt.strip()} {value}")
        return value

    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        store = Store(root / "dojo.sqlite3")
        output = io.StringIO()
        try:
            code = run_discuss(store, client=ScriptedHost(), read_line=read_line, output=output)
        finally:
            store.close()
        trace_path = next((root / "sessions").glob("*.jsonl"))
        records = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]

    events = [row for row in records if row.get("event") == "elicitation"]
    end = [row for row in records if row.get("event") == "session_end"][-1]
    summary = end.get("elicitation") or {}

    lines_out: list[str] = []
    add = lines_out.append
    add("<!-- 这一页由命令生成：python3 scripts/dao_live_session.py docs/dao/elicitation/live-session-1.md -->")
    add("")
    add("# 一场跑在真讨论循环里的会话（脚本化被访者，零模型调用）")
    add("")
    add("这一场不是在讲一个新故事，是看四句问法接进 `python3 -m dojo discuss` 之后会发生什么：")
    add("结论在同意那一轮写进库（和以前一样），之后主持人接着问四件；问不出来的那几件停在系统补。")
    add("")
    add("## 会话")
    add("")
    add("```")
    for line in transcript_lines:
        add(line)
    add("```")
    add("")
    add("被访者的话，逐句标出处：")
    add("")
    add("| 他说的 | 出处 |")
    add("|---|---|")
    for _, text, source in ANSWERS:
        add(f"| {text or '（没答）'} | {source} |")
    add("")
    add("前两句讨论（「把检查交给系统…」「对，就这条。」）是这场会话里的他，由 harness 写成、标明模拟；四句回答里能引到记录的都带行号，不能引的是「没答」。")
    add("")
    add("## 结果")
    add("")
    add(f"- 结束原因：`{end['reason']}`；模型请求：{end['requests_sent']} 次（全部来自脚本化的主持人，未联网）。")
    add(f"- 四件的问答：{summary.get('turns')} 轮；变成他的话的：{'、'.join(summary.get('promoted') or []) or '无'}；停在系统补的：{'、'.join(summary.get('supplied') or []) or '无'}。")
    add(f"- 这场会话产出的条目（投影）：「{CONCLUSION['statement']}」——**{summary.get('line')}**。")
    add("")
    add("## 轨迹里逐件记了什么")
    add("")
    add("| 件 | 轮 | 问的什么 | 他答的 | 变成他的？ |")
    add("|---|---|---|---|---|")
    for row in events:
        add(f"| {row['part']} | {row['turn']} | {QUESTIONS[row['part']]['ask'] if row['turn'] == 1 else QUESTIONS[row['part']]['follow_ups']['none']} | {row['answer'] or '（空）'} | {'是' if row['promoted'] else '否'} |")
    add("")
    add("## 这一场说明什么")
    add("")
    add("- **写作规则没变**：结论在他说「对」的那一轮就写进去了；四句问法是那之后的事（测试钉住：问第一件时库里的结论已经在了）。")
    add("- **问不出来就不填**：代价与失效没有回答，条目的这两件仍是系统补，所以它是**合写**，不是「他的」。")
    add("- **代价**：这一场 6 轮问答换来两件变成他的；另外两件问了两轮也没有，条目停在合写。")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines_out) + "\n", encoding="utf-8")
    print(f"写入 {out}")
    print(f"  {summary.get('turns')} 轮；promoted={summary.get('promoted')}；supplied={summary.get('supplied')}")
    print(f"  条目：{summary.get('line')}")
    return 0 if code == 0 else code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
