#!/usr/bin/env python3
"""四句问法跑一场模拟会话：哪一件能变成他的，哪一件问不出来，各花几轮。

被访者的话必须逐字来自事件层（带 episode），否则拒收——这一条让「演练」不会变成「编造」。
仪器不判语义：一句回答算不算回答了那一件，是人的判断，写在脚本的 kind 里，可被复核。
它只投影，不写库：跑完 daos.json 一个字节都不变。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

BENCH = "scripts/dao_elicit.py"
PARTS = ("情境", "张力", "代价", "失效")
PART_KEY = {"情境": "situation", "张力": "tension", "代价": "price", "失效": "off"}
FILLING = ("his", "relayed")
KINDS = ("his", "relayed", "another-rule", "story", "vague", "none")
SOURCE_OF = {"his": "他的原话", "relayed": "转述"}


class ElicitError(Exception):
    """A session that cannot be replayed, with the reason named."""


def load(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def parse_script(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise ElicitError(f"{path} 不存在")
    entries: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    part: dict[str, Any] | None = None
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("entry:"):
            entry_id = line.split(":", 1)[1].strip()
            current = {"id": entry_id, "parts": [], "line": number}
            entries.append(current)
            part = None
            continue
        if current is None:
            raise ElicitError(f"第 {number} 行：条目之外出现了内容：{line[:40]}")
        if line.startswith("ask "):
            name = line.split(None, 1)[1].strip()
            if name not in PARTS:
                raise ElicitError(f"第 {number} 行：不认识的件「{name}」；只有 {'、'.join(PARTS)}")
            if any(item["part"] == name for item in current["parts"]):
                raise ElicitError(f"第 {number} 行：{current['id']} 的「{name}」问了两遍")
            part = {"part": name, "answers": [], "line": number}
            current["parts"].append(part)
            continue
        if line.startswith("answer "):
            if part is None:
                raise ElicitError(f"第 {number} 行：还没有 ask 就出现了 answer")
            body = line[len("answer "):].strip()
            kind, _, rest = body.partition(" ")
            if kind not in KINDS:
                raise ElicitError(f"第 {number} 行：不认识的 kind「{kind}」；只有 {'、'.join(KINDS)}")
            answer: dict[str, Any] = {"kind": kind, "line": number}
            if kind == "none":
                answer.update({"episode": None, "quote": None})
            else:
                episode_id, _, quote = rest.partition("|")
                answer.update({"episode": episode_id.strip(), "quote": quote.strip()})
                if not answer["episode"] or not answer["quote"]:
                    raise ElicitError(f"第 {number} 行：kind={kind} 的 answer 要写「episode | 逐字引文」")
            part["answers"].append(answer)
            if len(part["answers"]) > 2:
                raise ElicitError(f"第 {number} 行：{current['id']} 的「{part['part']}」问了第三遍——两轮就停")
            continue
        raise ElicitError(f"第 {number} 行：读不出来：{line[:40]}")
    if not entries:
        raise ElicitError("脚本里没有一条 entry")
    return entries


def run(library_dir: Path, script_path: Path, questions_path: Path, at: str | None) -> dict[str, Any]:
    library = {
        "episodes": load(library_dir / "episodes.json"),
        "daos": load(library_dir / "daos.json"),
    }
    episodes = {episode["id"]: episode for episode in library["episodes"]["episodes"]}
    daos = {dao["id"]: dao for dao in library["daos"]["daos"]}
    questions = {item["part"]: item for item in load(questions_path)["parts"]}
    script = parse_script(script_path)

    results = []
    for entry in script:
        dao = daos.get(entry["id"])
        if dao is None:
            raise ElicitError(f"脚本里的 {entry['id']} 不在库里")
        sources = dict(dao.get("part_sources") or {})
        asked = {item["part"] for item in entry["parts"]}
        for name in PARTS:
            if name not in asked and sources.get(PART_KEY[name]) == "系统补":
                raise ElicitError(f"{entry['id']} 的「{name}」还是系统补，脚本却没问——一场会话要问满四件")
        parts_out = []
        turns = 0
        for item in entry["parts"]:
            name = item["part"]
            key = PART_KEY[name]
            if sources.get(key) != "系统补":
                raise ElicitError(f"{entry['id']} 的「{name}」已经是「{sources.get(key)}」，不该再问")
            answers = item["answers"]
            for index, answer in enumerate(answers):
                if answer["kind"] in FILLING:
                    episode = episodes.get(answer["episode"])
                    if episode is None:
                        raise ElicitError(
                            f"第 {answer['line']} 行：{answer['episode']} 不在事件层里——说不出处的话不能算他的"
                        )
                    if answer["quote"] not in (episode.get("quote") or ""):
                        raise ElicitError(
                            f"第 {answer['line']} 行：引文不在 {answer['episode']} 的原话里（逐字才算）："
                            f"「{answer['quote'][:24]}」"
                        )
                if index > 0 and answer["kind"] in FILLING and any(
                    earlier["kind"] in FILLING for earlier in answers[:index]
                ):
                    raise ElicitError(f"第 {answer['line']} 行：这一件已经填上了，不该再答")
            filled_answer = next((answer for answer in answers if answer["kind"] in FILLING), None)
            turns += 1  # 第一次问
            if filled_answer is None and answers:
                turns += 1  # 换了问法再问一次
            parts_out.append(
                {
                    "part": name,
                    "turns": 1 if filled_answer is not None else (2 if answers else 1),
                    "answers": [
                        {
                            "kind": answer["kind"],
                            "episode": answer["episode"],
                            "quote": answer["quote"],
                            "line": answer["line"],
                        }
                        for answer in answers
                    ],
                    "filled": filled_answer is not None,
                    "becomes": SOURCE_OF.get(filled_answer["kind"]) if filled_answer else "系统补",
                    "to_fill": questions[name]["to_fill"],
                }
            )
            if filled_answer is not None:
                sources[key] = SOURCE_OF[filled_answer["kind"]]
        results.append(
            {
                "id": entry["id"],
                "turns": turns,
                "parts": parts_out,
                "before": dict(dao.get("part_sources") or {}),
                "after": sources,
                "supplied_after": [
                    PART_KEY[name] for name in PARTS if sources.get(PART_KEY[name]) == "系统补"
                ],
            }
        )

    total_parts = sum(len(result["parts"]) for result in results)
    filled = sum(1 for result in results for item in result["parts"] if item["filled"])
    turns = sum(result["turns"] for result in results)
    return {
        "layer": "elicitation",
        "at": at,
        "script": str(script_path),
        "questions": str(questions_path),
        "entries": results,
        "totals": {
            "entries": len(results),
            "parts": total_parts,
            "filled": filled,
            "unfilled": total_parts - filled,
            "turns": turns,
            "turns_per_rule": round(turns / len(results), 2) if results else 0,
            "turns_per_filled": round(turns / filled, 2) if filled else None,
        },
    }


def render(report: dict[str, Any], script_path: Path, questions: dict[str, Any]) -> str:
    lines: list[str] = []
    add = lines.append
    totals = report["totals"]
    add(f"<!-- 这一页由命令生成：python3 {BENCH} --library docs/dao/person-dojo --script {script_path} --at <ISO8601> -->")
    add("")
    add("# 一场模拟会话：四句问法跑一遍")
    add("")
    add("被访者的话全部逐字来自事件层（每句带 episode 与出处）；提问与重问是 harness 的台词。这一份不写库，只投影：")
    add("如果这些话真被他说出来，哪一件会从「系统补」变成他的，哪一件问不出来。")
    add("")
    add(
        f"这一场：{totals['entries']} 条道、问了 {totals['parts']} 件；填上 {totals['filled']} 件、"
        f"没填上 {totals['unfilled']} 件；共 {totals['turns']} 轮，平均每条道 {totals['turns_per_rule']} 轮。"
    )
    add("")
    for entry in report["entries"]:
        add(f"## {entry['id']}（{entry['turns']} 轮）")
        add("")
        add("| 件 | 轮 | 他答了什么 | 结果 |")
        add("|---|---|---|---|")
        for item in entry["parts"]:
            said = "；".join(
                f"{answer['kind']}「{(answer['quote'] or '（没答）')[:40]}」" for answer in item["answers"]
            ) or "（没答）"
            add(f"| {item['part']} | {item['turns']} | {said} | {item['becomes']} |")
        add("")
        filled = [item for item in entry["parts"] if item["filled"]]
        if filled:
            add("这一场里变成他的话的：" + "、".join(f"{item['part']}（{item['becomes']}）" for item in filled) + "。")
        unfilled = [item for item in entry["parts"] if not item["filled"]]
        if unfilled:
            add("")
            add("问不出来的：" + "、".join(item["part"] for item in unfilled) + "。它们停「系统补」，条目停「合写」；")
            add("要变成他的，还得听他说出这样一句：" + "；".join(f"{item['part']}——{item['to_fill']}" for item in unfilled))
        add("")
    add("## 四句问法，和它们会招来什么")
    add("")
    for item in questions["parts"]:
        add(f"**{item['part']}**：{item['ask']}")
        add("")
        add(f"会招来：{item['failure_mode']}")
        add("")
        add(f"他答成另一条做法时接：{item['follow_ups']['another_rule']}")
        add("")
        add(f"答不出时接：{item['follow_ups']['none']}")
        add("")
    add("## 这一场不证明什么")
    add("")
    add("它不证明他的答案会是这样——这些话是他过去说的，被拿来当答案，不是被问到才说的。它证明的是：")
    add("照这四句问，哪一件能落在他真说过的话上（填得进）、哪一件必须等他新说一句（填不进），以及要花几轮。")
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(f"用法：python3 {BENCH} --library <库> --script <会话脚本> [--at ISO8601] [--check] [--out <文件名前缀>]")
        return 2
    library = script = out_prefix = None
    at = None
    write = True
    index = 1
    while index < len(argv):
        token = argv[index]
        if token in {"--library", "--script", "--at", "--out"} and index + 1 < len(argv):
            value = argv[index + 1]
            if token == "--library":
                library = Path(value)
            elif token == "--script":
                script = Path(value)
            elif token == "--out":
                out_prefix = value
            else:
                at = value
            index += 2
            continue
        if token == "--check":
            write = False
            index += 1
            continue
        print(f"不认识的参数：{token}")
        return 2
    if library is None or script is None:
        print("要给 --library 和 --script")
        return 2
    questions_path = library.parent / "elicitation" / "questions.json"
    try:
        questions = load(questions_path)
        report = run(library, script, questions_path, at)
    except ElicitError as error:
        print(f"拒收（{script}）：{error}")
        print("没有写任何文件。")
        return 1
    totals = report["totals"]
    print(f"一场会话：{totals['entries']} 条道、{totals['parts']} 件；填上 {totals['filled']}、没填上 {totals['unfilled']}；共 {totals['turns']} 轮")
    for entry in report["entries"]:
        filled = [item["part"] for item in entry["parts"] if item["filled"]]
        print(f"  {entry['id']}  {entry['turns']} 轮  填上：{'、'.join(filled) or '无'}；仍系统补：{len(entry['supplied_after'])} 件")
    if not write:
        print("--check：不写盘")
        return 0
    prefix = out_prefix or "run-1"
    out_dir = script.parent
    (out_dir / f"{prefix}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (out_dir / f"{prefix}.md").write_text(render(report, script, questions), encoding="utf-8")
    print(f"写入 {out_dir / (prefix + '.json')}")
    print(f"写入 {out_dir / (prefix + '.md')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
