#!/usr/bin/env python3
"""Count how far three people's tension sets overlap, by the rule written in advance.

Reads the notes written with docs/probe/tension-convergence.md, applies the merges a
human registered in merges.md, and prints the counts plus the pre-registered verdict.
It calls no model and writes nothing.
"""

from __future__ import annotations

import re
import statistics
import sys
from pathlib import Path

TENSION = re.compile(r"^-\s*\[(?P<id>[^\]]+)\]\s*(?P<body>.+)$")
FIELD = re.compile(r"^(?P<key>[^:|]+):\s*(?P<value>.*)$")


def norm(text: str) -> str:
    return " ".join(text.replace("<->", "↔").split())


def pair_key(pair: str) -> str:
    sides = [side.strip() for side in pair.split("↔")]
    if len(sides) != 2 or not all(sides):
        return ""
    return " ↔ ".join(sorted(sides))


def read_header(lines: list[str]) -> dict[str, str]:
    header: dict[str, str] = {}
    for line in lines:
        match = FIELD.match(line.strip())
        if not match:
            break
        header[match.group("key").strip().lower()] = match.group("value").strip()
    return header


def read_merges(path: Path) -> dict[str, str]:
    """Map every registered spelling onto one representative key."""
    parent: dict[str, str] = {}

    def find(key: str) -> str:
        parent.setdefault(key, key)
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    def union(left: str, right: str) -> None:
        left, right = find(left), find(right)
        if left != right:
            parent[right] = left

    if not path.exists():
        return {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or "=" not in line:
            continue
        left, right = (pair_key(part) for part in line.split("=", 1))
        if left and right:
            union(left, right)
    return {key: find(key) for key in list(parent)}


def read_note(path: Path) -> dict:
    lines = path.read_text(encoding="utf-8").splitlines()
    header = read_header(lines)
    tensions: list[dict] = []
    in_tensions = False
    for line in lines:
        if line.strip().startswith("## 张力"):
            in_tensions = True
            continue
        if line.strip().startswith("## "):
            in_tensions = False
            continue
        if not in_tensions:
            continue
        match = TENSION.match(line.strip())
        if not match:
            continue
        parts = [part.strip() for part in match.group("body").split("|")]
        pair = pair_key(parts[0])
        if not pair:
            continue
        fields: dict[str, str] = {}
        for part in parts[1:]:
            field_match = FIELD.match(part)
            if field_match:
                fields[field_match.group("key").strip()] = field_match.group("value").strip()
        tensions.append({
            "key": pair,
            "id": match.group("id").strip(),
            "anchored": bool(fields.get("锚", "").strip()),
            "direction": fields.get("方向", ""),
        })
    return {
        "name": path.stem,
        "person": header.get("person", path.stem),
        "sample": header.get("sample", "").strip().lower(),
        "minutes": header.get("minutes", ""),
        "tensions": tensions,
    }


def jaccard(left: set[str], right: set[str]) -> float | None:
    union = left | right
    if not union:
        return None
    return len(left & right) / len(union)


def verdict(core: int, median: float, persons: int, sample: str) -> str:
    if persons < 3:
        return "不判：少于 3 场"
    if core >= 3 and median >= 0.30:
        base = "收敛"
    elif core <= 1 or median < 0.10:
        base = "不收敛"
    else:
        base = "说不准"
    if sample == "acquaintances":
        if base == "收敛":
            return "值得去问陌生人（相熟者样本的收敛不算结论）"
        if base == "说不准":
            return "说不准（相熟者样本：去问陌生人才可能变成结论）"
        return "不收敛"
    if sample not in ("acquaintances", "strangers"):
        return f"{base}（样本类型未写：sample 须为 acquaintances 或 strangers）"
    return base


def main(argv: list[str]) -> int:
    notes_dir = Path(argv[1]) if len(argv) > 1 else Path("docs/probe/notes")
    if not notes_dir.is_dir():
        print(f"没有这个目录：{notes_dir}")
        return 1
    paths = sorted(
        path for path in notes_dir.glob("*.md")
        if not path.name.startswith("_") and path.name != "merges.md"
    )
    notes = [read_note(path) for path in paths]
    if not notes:
        print("没有笔记（0 场）")
        return 0

    merges = read_merges(notes_dir / "merges.md")
    print(f"笔记：{len(notes)} 场（{', '.join(note['person'] for note in notes)}）")
    samples = {note["sample"] for note in notes}
    print(f"样本类型：{', '.join(sorted(samples)) or '未写'}")

    sets: dict[str, set[str]] = {}
    unanchored = 0
    for note in notes:
        keys: set[str] = set()
        for tension in note["tensions"]:
            if not tension["anchored"]:
                unanchored += 1
                continue
            key = tension["key"]
            keys.add(merges.get(key, key))
        sets[note["person"]] = keys
        directions = {tension["direction"] for tension in note["tensions"] if tension["direction"]}
        print(f"  {note['person']}: {len(note['tensions'])} 条张力"
              f"（计入 {len(keys)}，无锚 {sum(1 for t in note['tensions'] if not t['anchored'])}）"
              f"{'，方向不同的有 ' + str(len(directions)) + ' 种' if directions else ''}")

    names = list(sets)
    scores: list[float] = []
    for index, left in enumerate(names):
        for right in names[index + 1:]:
            score = jaccard(sets[left], sets[right])
            if score is None:
                print(f"  {left} & {right}: 两边都空，跳过")
                continue
            scores.append(score)
            shared = len(sets[left] & sets[right])
            print(f"  {left} & {right}: 交集 {shared}，Jaccard {score:.3f}")

    core_keys = set.intersection(*sets.values()) if sets else set()
    print(f"所有场次共有：{len(core_keys)} 条{'（' + '、'.join(sorted(core_keys)) + '）' if core_keys else ''}")
    if scores:
        median = statistics.median(scores)
        print(f"两两 Jaccard 中位数：{median:.3f}")
    else:
        median = 0.0
        print("两两 Jaccard 中位数：不可算（没有可比的两人）")

    counts = [len(keys) for keys in sets.values()]
    if len(notes) >= 3 and min(counts) < 2:
        print("结论：访谈不足（有人只出 1 条计入的张力，规则不判）")
    elif unanchored and min(counts) == 0:
        print("结论：访谈不足（张力全部无锚）")
    else:
        sample = "acquaintances" if samples == {"acquaintances"} else (
            "strangers" if samples == {"strangers"} else "")
        print(f"结论：{verdict(len(core_keys), median, len(notes), sample)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
