#!/usr/bin/env python3
"""一条道的一生：六件套进，三格回执出，一张道图还给那个人。

这一条命令把三层接起来，不调模型、不碰网络：

1. 事件层（`episodes.json`）：一个人的具体经历，原话 + 路径。它只记报告。
2. 提炼层（`daos.json`）：从案例里拔出来的道，六件套齐全，动作写成一条可判的规则。
3. 检验层（本文件）：网络自己跑三道检查，留下只追不改的回执——
   - 自洽（结构，确定性）：六件套是否互相咬合，套话过不过得去；
   - 可反驳（模拟）：从案例取一个域内处境，再从每条失效条件各造一个越界处境，
     看这条道给不给出不同的动作；失效条件是装饰的，这一格就不过；
   - 落地（观察）：有没有一条晚于案例、不是被问出来的观察；没有就写「未跑」。

回执只追不改：版本一动，旧回执留在旧版本上，新版本要重新拿到自己的回执。
「未检」是这一层要印出来的东西，不是要藏起来的东西。
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

BENCH = "scripts/dao_life.py"
BENCH_VERSION = 1
COST_UNITS = ("时间", "关系", "机会", "能力")
CLICHES = (
    "因人而异",
    "注意平衡",
    "要自律",
    "具体情况具体分析",
    "看情况",
    "适当",
    "保持平衡",
    "顺其自然",
    "把握分寸",
)
OBSERVATION_KINDS = {
    "later_session": ("他人的后续·弱（不是对照）", "验过（弱：后续，非对照）"),
    "agent_self": ("自验·弱一档（agent）", "验过（弱一档：自验）"),
    "controlled": ("有意的对照（量过）", "量过"),
}
OBSERVATION_STRENGTH = {"agent_self": 1, "later_session": 2, "controlled": 3}
VERDICT_WORD = {"pass": "过", "fail": "不过", "not_run": "未跑", "uncertain": "不确定"}
ATTRIBUTION_CLASSES = ("person", "relayed", "synthetic", "unverified")
SOURCE_WORD = {"person": "自述", "relayed": "自述（转述）", "synthetic": "模拟", "unverified": "传闻"}
PART_NAMES = ("situation", "tension", "move", "price", "off", "provenance")
PART_SOURCES = ("记录", "转述", "推断")
REFUSAL_PARTS = ("情境", "张力", "动作", "代价", "失效", "归属", "重复")
RECEIPT_PATHS = ("structure", "falsifiable", "field")


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def evaluate(rule: list[dict[str, Any]], situation: dict[str, Any]) -> dict[str, Any] | None:
    """First rule row whose named axes all hold in this situation."""
    for row in rule:
        wanted = row.get("when") or {}
        if wanted and all(situation.get(key) == value for key, value in wanted.items()):
            return row
    return None


def later(observation_at: str, case_at: str) -> bool:
    """案例多为日粒度；观察要严格晚于它。同一天时，观察必须写到时间。"""
    if not observation_at or not case_at:
        return False
    if observation_at[:10] != case_at[:10]:
        return observation_at[:10] > case_at[:10]
    return len(observation_at) > 10 and len(case_at) == 10


def source_classes(dao: dict[str, Any], episodes: dict[str, dict[str, Any]]) -> set[str]:
    return {
        (episodes.get(item.get("episode")) or {}).get("attribution", "")
        for item in dao.get("provenance") or []
    } - {""}


def base_word(dao: dict[str, Any], episodes: dict[str, dict[str, Any]]) -> str:
    """The strongest word the entry's own sources earn, before any receipt."""
    classes = source_classes(dao, episodes)
    for name in ("person", "relayed", "synthetic"):
        if name in classes:
            return SOURCE_WORD[name]
    return SOURCE_WORD["unverified"]


def _add(checks: list[dict[str, Any]], name: str, ok: Any, detail: str = "") -> None:
    checks.append({"name": name, "ok": bool(ok), "detail": detail})


def check_structure(
    dao: dict[str, Any],
    episodes: dict[str, dict[str, Any]],
    window: dict[str, Any],
    vocabulary: dict[str, Any],
    at: str | None,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    situation = dao.get("situation") or {}
    tension = dao.get("tension") or {}
    move = dao.get("move") or {}
    price = dao.get("price") or []
    off = dao.get("off") or []
    provenance = dao.get("provenance") or []
    axes = dao.get("axes") or {}
    rule = dao.get("rule") or []

    _add(checks, "情境三件都有", situation.get("who") and situation.get("when") and situation.get("constraints"))
    _add(
        checks,
        "张力正好两侧",
        tension.get("name") and isinstance(tension.get("sides"), list) and len(tension.get("sides")) == 2,
        f"读了 {len(tension.get('sides') or [])} 侧",
    )
    _add(
        checks,
        "动作落在它自己命名的张力上",
        move.get("on_tension") == tension.get("name"),
        f"动作挂在 {move.get('on_tension')!r}，张力叫 {tension.get('name')!r}",
    )
    _add(checks, "动作有方向与作用点", move.get("direction") and move.get("locus"))
    _add(
        checks,
        "代价至少一条，且每条写得出一条真正花掉的资源",
        price
        and all(p.get("unit") in COST_UNITS and p.get("what") and p.get("who") for p in price),
        f"单位闭集是 {COST_UNITS}",
    )
    _add(checks, "失效条件至少一条", bool(off))
    bad_axis = [
        item.get("axis")
        for item in off
        if item.get("axis") not in axes or item.get("value") not in (axes.get(item.get("axis")) or [])
    ]
    _add(checks, "每条失效条件都写成一个可改的轴与取值", bool(off) and not bad_axis, f"改不动的：{bad_axis}")
    part_sources = dao.get("part_sources") or {}
    undeclared = [name for name in PART_NAMES if part_sources.get(name) not in PART_SOURCES]
    _add(
        checks,
        "六件各自写明了是从记录来、转述来，还是读出来的",
        not undeclared,
        f"没写的：{undeclared}；读法写在 part_sources 里，不写就等于把推断冒充成记录",
    )
    _add(
        checks,
        "失效条件给出的是「反转」或「停」，不是一句劝告",
        off and all(item.get("then_kind") in {"reverse", "withhold"} and item.get("then") for item in off),
    )
    hits = [word for word in CLICHES if word in canonical(dao)]
    _add(checks, "没有抽掉一句就通不过的套话", not hits, f"命中：{hits}")
    covers = situation.get("covers") or []
    _add(
        checks,
        "案例在事件层里存在",
        bool(covers) and all(episode in episodes for episode in covers),
        f"缺：{[e for e in covers if e not in episodes]}",
    )
    loose = [item.get("episode") for item in provenance if item.get("episode") not in episodes]
    _add(checks, "归属边指向真实事件", bool(provenance) and not loose, f"悬空：{loose}")
    supported = [
        item for item in provenance if (episodes.get(item.get("episode")) or {}).get("attribution") != "unverified"
    ]
    _add(
        checks,
        "至少一条出处不是署名未核",
        bool(supported),
        "署名未核的那条只能当旁证，不能是唯一支撑",
    )
    unknown_class = [
        item.get("episode")
        for item in provenance
        if (episodes.get(item.get("episode")) or {}).get("attribution") not in ATTRIBUTION_CLASSES
    ]
    _add(checks, "每条出处都写明了来源类别", bool(provenance) and not unknown_class, f"类别没写：{unknown_class}")
    tension_keys = {term["key"] for term in vocabulary.get("tensions") or []}
    move_keys = {term["key"] for term in vocabulary.get("moves") or []}
    _add(
        checks,
        "张力键在受控词表里",
        dao.get("tension_key") in tension_keys,
        f"{dao.get('tension_key')!r} 不在 {sorted(tension_keys)} 里；新词要先写进 docs/dao/vocabulary.json 并写理由",
    )
    _add(
        checks,
        "动作键在受控词表里",
        dao.get("move_key") in move_keys,
        f"{dao.get('move_key')!r} 不在 {sorted(move_keys)} 里",
    )
    _add(
        checks,
        "规则只改它自己声明的轴",
        bool(rule)
        and all(row.get("action") and row.get("when") for row in rule)
        and all(
            key in axes and value in (axes.get(key) or [])
            for row in rule
            for key, value in (row.get("when") or {}).items()
        ),
    )
    late = [
        episode_id
        for episode_id in {*covers, *(item.get("episode") for item in provenance)}
        if (episodes.get(episode_id) or {}).get("at", "") > window.get("last_person_input", "")
    ]
    _add(
        checks,
        "没有窗口之后的输入（第一场之后不再要人补）",
        not late,
        f"窗口最后一天 {window.get('last_person_input')}；晚了：{late}",
    )
    failures = [c for c in checks if not c["ok"]]
    return {
        "kind": "structure",
        "ran": {
            "by": f"{BENCH}/structure-v{BENCH_VERSION}",
            "at": at,
            "on_version": dao.get("version"),
            "on_digest": digest(dao)[:12],
        },
        "verdict": "pass" if not failures else "fail",
        "checks": checks,
        "failures": [f"{c['name']}（{c['detail']}）" if c["detail"] else c["name"] for c in failures],
    }


def check_falsifiable(
    dao: dict[str, Any],
    episodes: dict[str, dict[str, Any]],
    at: str | None,
) -> dict[str, Any]:
    """Two situations, two actions, one conclusion — from the case and from each 失效条件."""
    inside_id = (dao.get("provenance") or [{}])[0].get("episode")
    inside_episode = episodes.get(inside_id) or {}
    inside_situation = dict(inside_episode.get("conditions") or {})
    rule = dao.get("rule") or []
    inside_row = evaluate(rule, inside_situation) if inside_situation else None

    cases: list[dict[str, Any]] = [
        {
            "side": f"域内（案例 {inside_id}）",
            "situation": inside_situation,
            "action": (inside_row or {}).get("action"),
            "action_kind": (inside_row or {}).get("kind"),
            "recorded": inside_episode.get("observed_action"),
        }
    ]
    notes: list[str] = []
    if inside_row is None:
        notes.append("案例的处境落不进这条道的规则：要么规则没写全，要么案例不在它的适用域里。")

    for index, item in enumerate(dao.get("off") or [], 1):
        axis = item.get("axis")
        outside = dict(inside_situation)
        outside[axis] = item.get("value")
        if inside_situation.get(axis) == item.get("value"):
            notes.append(f"失效条件 #{index} 在案例的处境里已经成立，翻不动任何东西。")
        outside_row = evaluate(rule, outside)
        differs = bool(outside_row and inside_row and outside_row.get("action") != inside_row.get("action"))
        kind_matches = bool(outside_row and outside_row.get("kind") == item.get("then_kind"))
        if not differs:
            notes.append(f"失效条件 #{index} 改到越界，动作没变：那是一句装饰。")
        elif not kind_matches:
            notes.append(
                f"失效条件 #{index} 说要做「{item.get('then_kind')}」，规则却给了「{(outside_row or {}).get('kind')}」。"
            )
        cases.append(
            {
                "side": f"越界（{axis}={item.get('value')}）",
                "situation": outside,
                "action": (outside_row or {}).get("action"),
                "action_kind": (outside_row or {}).get("kind"),
                "expected_kind": item.get("then_kind"),
                "differs_from_inside": differs,
                "when": item.get("when"),
            }
        )

    verdict = "pass" if inside_row is not None and not notes else "fail"
    return {
        "kind": "falsifiable",
        "ran": {
            "by": f"{BENCH}/simulate-v{BENCH_VERSION}",
            "at": at,
            "on_version": dao.get("version"),
            "on_digest": digest(dao)[:12],
        },
        "verdict": verdict,
        "cases": cases,
        "notes": notes,
        "limit": "这一格证明的是结构：边界一改，动作就变。两个处境在世界上是否真的不同，还要读回执的人判。",
    }


def check_field(
    dao: dict[str, Any],
    episodes: dict[str, dict[str, Any]],
    observations: list[dict[str, Any]],
    at: str | None,
) -> dict[str, Any]:
    latest_case = max((episodes.get(item.get("episode"), {}).get("at", "") for item in dao.get("provenance") or []), default="")
    rows = [row for row in observations if row.get("dao") == dao.get("id")]
    eligible: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for row in rows:
        reason = ""
        if row.get("kind") not in OBSERVATION_KINDS:
            reason = f"来源类别 {row.get('kind')!r} 不在三种里"
        elif row.get("elicited", False):
            reason = "是被问出来的，不是自然出现的"
        elif not later(row.get("at", ""), latest_case):
            reason = f"不晚于案例（案例 {latest_case}，观察 {row.get('at')}）"
        elif row.get("kind") == "agent_self" and not (
            row.get("applied_in") and row.get("result") and row.get("could_have_gone_otherwise")
        ):
            reason = "自验没写清「在哪件真实活里用过、结果是什么、本来可能怎样」，所以不算观察"
        if reason:
            rejected.append({"id": row.get("id"), "kind": row.get("kind"), "reason": reason})
        else:
            eligible.append(row)
    if not eligible:
        return {
            "kind": "field",
            "ran": None,
            "verdict": "not_run",
            "observation": None,
            "rejected": rejected,
            "note": "没有一条晚于案例、也不是被问出来的观察；不拿「他说过很多次」顶替。",
        }
    best = sorted(eligible, key=lambda row: OBSERVATION_STRENGTH[row["kind"]])[-1]
    verdict = "pass" if best.get("matched") is True else ("fail" if best.get("matched") is False else "uncertain")
    label, _word = OBSERVATION_KINDS[best["kind"]]
    return {
        "kind": "field",
        "ran": {
            "by": f"{BENCH}/field-v{BENCH_VERSION}",
            "at": at,
            "on_version": dao.get("version"),
            "on_digest": digest(dao)[:12],
        },
        "verdict": verdict,
        "strength": label,
        "observation": best,
        "rejected": rejected,
        "note": "观察晚于案例，且不是被问出来的；它证明的是一条相符或相悖的观察存在，不是这条道为真。",
    }


def status_of(
    dao: dict[str, Any],
    receipts: dict[str, dict[str, Any]],
    episodes: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    structure = receipts["structure"]["verdict"]
    falsifiable = receipts["falsifiable"]["verdict"]
    field = receipts["field"]
    passed = sum(1 for verdict in (structure, falsifiable, field["verdict"]) if verdict == "pass")
    base = base_word(dao, episodes)
    if field["verdict"] == "not_run":
        word, mark = base, "未检"
    elif field["verdict"] == "pass" and structure == "pass" and falsifiable == "pass":
        word, mark = OBSERVATION_KINDS[field["observation"]["kind"]][1], "检"
    else:
        word, mark = base, "未检"
    cells = [
        ("自洽", structure),
        ("可反驳", falsifiable),
        ("落地", field["verdict"]),
    ]
    cell_text = " / ".join(f"{name} {VERDICT_WORD[verdict]}" for name, verdict in cells)
    return {
        "word": word,
        "mark": mark,
        "count": passed,
        "cells": cells,
        "line": f"{word} · {mark}（{passed}/3：{cell_text}）",
    }


def missing_receipts(dao: dict[str, Any], receipts: dict[str, dict[str, Any]]) -> list[str]:
    """A receipt belongs to a version and a digest; a moved entry has none."""
    missing = []
    for kind in RECEIPT_PATHS:
        receipt = receipts.get(kind) or {}
        ran = receipt.get("ran") or {}
        if receipt.get("verdict") == "not_run":
            continue
        if ran.get("on_version") != dao.get("version") or ran.get("on_digest") != digest(dao)[:12]:
            missing.append(kind)
    return missing


def run_bench(
    data: dict[str, Any],
    at: str | None,
    vocabulary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    episodes = {episode["id"]: episode for episode in data["episodes"]["episodes"]}
    window = data["episodes"]["window"]
    observations = data["observations"]["observations"]
    vocabulary = vocabulary or {"tensions": [], "moves": []}
    receipts: dict[str, dict[str, Any]] = {}
    for dao in data["daos"]["daos"]:
        receipts[dao["id"]] = {
            "structure": check_structure(dao, episodes, window, vocabulary, at),
            "falsifiable": check_falsifiable(dao, episodes, at),
            "field": check_field(dao, episodes, observations, at),
        }
    return receipts


def independent_groups(data: dict[str, Any]) -> dict[str, Any]:
    """不同的人 × 不同的情境出处 × 无同源传递 × 各有案例；缺一不算一组。"""
    people: set[str] = set()
    classes: set[str] = set()
    episodes_by_id = {episode["id"]: episode for episode in data["episodes"]["episodes"]}
    for dao in data["daos"]["daos"]:
        for item in dao.get("provenance") or []:
            episode = episodes_by_id.get(item.get("episode")) or {}
            if episode.get("attribution") == "unverified":
                continue
            people.add(item.get("person"))
            classes.add(episode.get("attribution", ""))
    exposures = data["exposures"].get("rows") or []
    synthetic_only = bool(people) and classes == {"synthetic"}
    if synthetic_only:
        line = (
            f"来源是模拟材料（{len(people)} 个来源 id，曝光账本 {len(exposures)} 行）："
            "它不是一个人的道理，也不是共识，只能用来测这张库装不装得下第二个来源。"
        )
    else:
        line = (
            f"独立来源 {len(people)} 组（不同的人 {len(people)} 个；曝光账本 {len(exposures)} 行）。"
            "曝光未知按「不独立」算：这里是一个人的道理，不是共识。"
        )
    return {
        "people": sorted(people),
        "groups": len(people),
        "exposures": len(exposures),
        "line": line,
    }


def _situation_text(situation: dict[str, Any]) -> str:
    if not situation:
        return "（没有写条件）"
    return "；".join(f"{key}={value}" for key, value in situation.items())


def _ordinal(index: int) -> str:
    names = "一二三四五六七八九十"
    return names[index] if index < len(names) else str(index + 1)


def render(
    data: dict[str, Any],
    receipts: dict[str, Any],
    at: str | None,
    inputs: dict[str, str],
    vocabulary: dict[str, Any],
) -> str:
    episodes = {episode["id"]: episode for episode in data["episodes"]["episodes"]}
    daos = data["daos"]["daos"]
    needed = {item.get("dao"): item for item in data["observations"].get("needed") or []}
    groups = independent_groups(data)
    classes: set[str] = set()
    for dao in daos:
        classes |= source_classes(dao, episodes)
    synthetic = classes and classes.issubset({"synthetic", "unverified"})
    tension_gloss = {term["key"]: term["gloss"] for term in vocabulary.get("tensions") or []}
    move_gloss = {term["key"]: term["gloss"] for term in vocabulary.get("moves") or []}
    root_name = data.get("root", "docs/dao/person-dojo")
    lines: list[str] = []
    add = lines.append

    add(f"<!-- 这一页由命令生成，不要手改：python3 {BENCH} {root_name} --at <ISO8601> -->")
    add("")
    if synthetic:
        add("# 道图（模拟来源）：一条道——这不是一个人的道图")
        add("")
        add("这一页的来源是模拟材料，作者与我们是同一只手。它能测这张库装不装得下第二个来源，")
        add("不能当某个人的道图读，也不能用来回答「不同人的道会不会落在同一批张力上」。")
    else:
        add(f"# 道图：{_ordinal(len(daos) - 1)}条道（{', '.join(sorted(groups['people'])) or 'person'}）")
        add("")
        add("这几条道说的是同一件事：你要我把「活」拿走，但要先把「样子」和「价」摆在你面前。")
        add("其中有一条边界是我读出来的、你没说过；一句话就能推翻它，见「连接与边界」。")
    add("")
    real_people = set()
    for dao in daos:
        for item in dao.get("provenance") or []:
            episode = episodes.get(item.get("episode")) or {}
            if episode.get("attribution") in {"person", "relayed"}:
                real_people.add(item.get("person"))
    if not synthetic:
        if len(real_people) <= 1:
            add("**这张图是一个人的。**记录里只有一位真人的具体经历，所以它证明的是这张库能把一个人的经历收成一张带边界的地图，")
            add("不证明它装得下第二个人的道理。目标仍是「人类的道」；要走到那儿，需要一个真实第二人的一场会话（`docs/probe/tension-convergence.md`）。")
        else:
            add(f"**这张图有 {len(real_people)} 个人的材料，仍不够说「人类的道」**：按探针页的判分规则，至少三场、且按事先写下的规则判过，才算一个读数。")
        add("")

    states = {dao["id"]: status_of(dao, receipts[dao["id"]], episodes) for dao in daos}
    landed = [dao["id"] for dao in daos if receipts[dao["id"]]["field"]["verdict"] != "not_run"]
    add("## 这张图里有什么")
    add("")
    add(f"{len(daos)} 条道，每条六件套齐全；{len(daos)} 条都有自洽与可反驳两张回执，落地那一格 {len(landed)} 条有观察、{len(daos) - len(landed)} 条是「未跑」。")
    if not synthetic:
        library_failures, summary = check_library(data)
        counts = summary["refusal_counts"]
        add(
            f"另有 {summary['refused']} 条材料写不成道（按缺的那一件：情境 {counts['情境']}、张力 {counts['张力']}、"
            f"动作 {counts['动作']}、代价 {counts['代价']}、失效 {counts['失效']}、归属 {counts['归属']}、重复 {counts['重复']}），"
            f"{summary['candidates']} 条候选，{summary['contradictions']} 对互相打架；它们都在「没进库的东西」一节。"
        )
        tally: dict[str, dict[str, int]] = {name: {} for name in PART_NAMES}
        for dao in daos:
            for name in PART_NAMES:
                source = (dao.get("part_sources") or {}).get(name, "（没写）")
                tally[name][source] = tally[name].get(source, 0) + 1
        labels = {"situation": "情境", "tension": "张力", "move": "动作", "price": "代价", "off": "失效", "provenance": "归属"}
        add(
            "六件按来源合计："
            + "；".join(
                f"{labels[name]} " + "、".join(f"{source} {count}" for source, count in sorted(tally[name].items()))
                for name in PART_NAMES
            )
            + "。"
        )
        add("这一行是这张图最该被读的一句话：他给得出「做什么」和「从哪来」，给不出「什么处境」「哪两个好处在打架」「谁付什么」——那些是我读出来的，标着「推断」。")
    add(groups["line"])
    add("提炼是这次会话的 manager 从记录里读出来的（凡读法处标「推断」），不是模型判定：这一包 0 次模型调用。")
    add("")

    add("## 一条道长什么样")
    add("")
    add("在 S 里，宁可 A 不 B，代价是 C；当出现 D 时，反过来。S 是适用域，A/B 是张力，C 是价格，D 是失效条件。")
    add("")

    for dao in daos:
        state = states[dao["id"]]
        receipt = receipts[dao["id"]]
        add(f"## 道{_ordinal(daos.index(dao))}　{dao['id']}　{dao['title']}")
        add("")
        add(f"> {dao['one_line']}")
        add("")
        add("| 件 | 内容 |")
        add("|---|---|")
        situation = dao["situation"]
        add(f"| 情境 | 谁：{situation['who']}；何时：{situation['when']}；约束：{'、'.join(situation['constraints'])}；领域：{'、'.join(situation['domain'])} |")
        tension = dao["tension"]
        add(
            f"| 张力 | {tension['name']}——两头是「{tension['sides'][0]}」与「{tension['sides'][1]}」。{tension['why']}"
            f"（词表键：{dao.get('tension_key')}——{tension_gloss.get(dao.get('tension_key'), '词表里没有这个词')}）|"
        )
        move = dao["move"]
        add(
            f"| 动作 | {move['direction']}；作用在：{move['locus']}；幅度：{move['magnitude']}"
            f"（动作键：{dao.get('move_key')}——{move_gloss.get(dao.get('move_key'), '词表里没有这个词')}）|"
        )
        price = "；".join(f"{item['what']}（{item['unit']}，{item['who']}付）" for item in dao["price"])
        add(f"| 代价 | {price} |")
        off = "；".join(f"当{item['when']}——{item['then']}" for item in dao["off"])
        add(f"| 失效 | {off} |")
        prov = "；".join(
            f"{item['person']} · {item['episode']} · {item['status']} · {item['learned_from']}" for item in dao["provenance"]
        )
        add(f"| 归属 | {prov} |")
        add("")

        anchors = []
        for item in dao["provenance"]:
            episode = episodes.get(item["episode"]) or {}
            anchor = f"- 「{episode.get('quote', '（没有原话）')}」（`{episode.get('source', {}).get('path')}` {episode.get('source', {}).get('ref')}）"
            if episode.get("attribution") == "unverified":
                anchor += "　— 署名未核，只当旁证，不计入独立性"
            elif episode.get("attribution") == "synthetic":
                anchor += "　— 模拟材料，不是某个人说过的"
            anchors.append(anchor)
        add("原话：" if not synthetic else "原话（模拟材料，写死的台词）：")
        add("")
        lines.extend(anchors)
        add("")
        sources = dao.get("part_sources") or {}
        add(
            "六件的来源："
            + "、".join(f"{label} {sources.get(name, '（没写）')}" for name, label in (
                ("situation", "情境"), ("tension", "张力"), ("move", "动作"),
                ("price", "代价"), ("off", "失效"), ("provenance", "归属"),
            ))
            + "（记录＝他从那句原话里写的；转述＝别人记下的他的话；推断＝提炼时读出来的）"
        )
        add("")
        add(f"回执：{state['line']}")
        add("")
        add(f"自洽 {VERDICT_WORD[receipt['structure']['verdict']]}（v{receipt['structure']['ran']['on_version']}，摘要 {receipt['structure']['ran']['on_digest']}）")
        add(f"可反驳 {VERDICT_WORD[receipt['falsifiable']['verdict']]}（两个处境、两个动作见「回执」一节）")
        field = receipt["field"]
        if field["verdict"] == "not_run":
            add("落地 未跑——没有一条晚于案例、也不是被问出来的观察；这一格就印成这样，不拿「他说过很多次」顶替。")
        else:
            observation = field["observation"]
            if observation.get("kind") == "agent_self":
                def _sentence(text: str) -> str:
                    return text.rstrip("。；;\n")

                add(
                    f"落地 {VERDICT_WORD[field['verdict']]}（{field['strength']}）：这条道被用在一件真实活上——{_sentence(observation['applied_in'])}。"
                )
                add(f"结果是：{_sentence(observation['result'])}。")
                add(f"本来可能：{_sentence(observation['could_have_gone_otherwise'])}。")
            else:
                add(
                    f"落地 {VERDICT_WORD[field['verdict']]}（{field['strength']}）：{observation['prediction']} "
                    f"混杂未排除：{observation.get('confound', '（没写）')}"
                )
        grounding = needed.get(dao["id"])
        if grounding:
            add(f"要什么才能{'给这一格一条观察' if field['verdict'] == 'not_run' else '把这一格变强'}：{grounding['what']}（现在拿不到：{grounding['why_not']}；谁能补：{grounding['who']}）")
        add("")

    add("## 连接与边界（你没说过的那一处）" if not synthetic else "## 连接与边界（这份材料内部的）")
    add("")
    if not data["map"].get("connections") and not data["map"].get("boundaries"):
        add("这一页没有连接或边界提案。")
        add("")
    for connection in data["map"].get("connections") or []:
        add(f"**{connection['id']}　连接**：{connection['says']}")
        add("")
        add(f"为什么算新的：{connection['why_it_may_be_new']}　状态：`{connection['status']}`")
        add("")
    for boundary in data["map"].get("boundaries") or []:
        add(f"**{boundary['id']}　边界**：{boundary['says']}　状态：`{boundary['status']}`")
        add("")
        add(boundary["detail"])
        add("")
        add(f"落到产品上的一句话：{boundary['line_for_him']}")
        add("")
        add(f"你一句话就能确认或推翻：**{boundary['test_line']}**")
        add("")
        add(f"所有者：{boundary['owner']}；什么时候重开：{boundary['reopen']}；{boundary['where_not_written']}")
        add("")

    contradictions = data["map"].get("contradictions") or []
    if contradictions:
        add("## 同一份记录里互相打架的两条")
        add("")
        add("这不是错误，是数据：它说明这个人前后变了，或者两件事他都没说清。两条都留在库里，谁也没被删；裁决是他的，不是我的。")
        add("")
        for item in contradictions:
            add(f"**{item['id']}**（{'、'.join(item['between'])}）在同一处卡住：{item['on']}。")
            add("")
            add(f"左边：{item['left']}")
            add("")
            add(f"右边：{item['right']}")
            add("")
            add(f"现在怎么读：{item['how_it_reads_now']}")
            add("")
            add(f"状态：{item['state']}　什么能定：{item['what_would_settle_it']}")
            add("")

    refusals = (data.get("refusals") or {}).get("items") or []
    if refusals:
        counts = check_library(data)[1]["refusal_counts"]
        add("## 没进库的东西：写不成道的材料")
        add("")
        add(
            "「候选」是六件写得全、但案例撑不住；这里不同——这里每一行都是六件里有一件从这份材料里根本写不出来。"
            f"按缺的那一件数：情境 {counts['情境']}、张力 {counts['张力']}、动作 {counts['动作']}、"
            f"代价 {counts['代价']}、失效 {counts['失效']}、归属 {counts['归属']}、重复 {counts['重复']}。"
        )
        add("")
        add("| 材料 | 缺 | 为什么写不成 |")
        add("|---|---|---|")
        for item in refusals:
            add(f"| {item['id']}：{item['material']} | {'、'.join(item['missing'])} | {item['why']} |")
        add("")

    candidates = data["map"].get("candidates") or []
    if candidates:
        add("## 候选（还不成立，所以没进库）")
        add("")
        add("这些是这几条道指出来、但那几件具体经历还撑不住的道。它们不进库，也不计进任何数目；写成候选是为了让「我们还不知道」有一个位置。")
        add("")
        for candidate in candidates:
            add(f"**{candidate['id']}**　{candidate['one_line']}")
            add("")
            add(f"指出来的是：{'、'.join(candidate['suggested_by'])}。状态：`{candidate.get('status', '候选')}`")
            add("")
            add(f"为什么没进库：{candidate['why_not_entered']}")
            add("")
            add(f"什么能支持它：{candidate['what_would_support_it']}")
            add("")

    add("## 回执（三格，一条道一条道读）")
    add("")
    for dao in daos:
        receipt = receipts[dao["id"]]
        add(f"### {dao['id']}")
        add("")
        add("| 处境 | 从哪来 | 这条道推出来的动作 |")
        add("|---|---|---|")
        for case in receipt["falsifiable"]["cases"]:
            add(f"| {_situation_text(case['situation'])} | {case['side']} | {case['action']} |")
        add("")
        if receipt["falsifiable"]["notes"]:
            add("不过的原因：" + "；".join(receipt["falsifiable"]["notes"]))
        else:
            add("结论：两个处境给出不同动作，失效条件不是装饰。")
        add(receipt["falsifiable"]["limit"])
        add("")

    add("## 未检清单（原样印出来，不藏）")
    add("")
    unrun = [dao["id"] for dao in daos if receipts[dao["id"]]["field"]["verdict"] == "not_run"]
    if unrun:
        add(f"落地 未跑：{'、'.join(unrun)}。没跑就是没跑，这一格不拿话填；也没有一条被写成建议。")
    else:
        add("落地这一格每条都有观察；它们的强弱写在每条道下面。")
    rejected_lines = []
    for dao in daos:
        for item in receipts[dao["id"]]["field"].get("rejected") or []:
            rejected_lines.append(f"{dao['id']}：观察 {item['id']}（{item['kind']}）不计入——{item['reason']}")
    if rejected_lines:
        add("")
        add("被拒的观察（拒的理由写在这儿，不静默丢掉）：" + "；".join(rejected_lines))
    boundaries = data["map"].get("boundaries") or []
    if boundaries:
        add(f"组织性（A2）没有人替你确认：`{boundaries[0]['id']}` 标的是 `待确认`，不是 `已确认`。")
    add("")

    add("## 重跑与证据")
    add("")
    add(f"重跑：`python3 {BENCH} {root_name} --at <ISO8601>`；不带 `--at` 也能跑，回执里的时间会写成 null。")
    add("")
    add("输入（按排序后的 JSON 算内容 sha256，取前 12 位；不随排版变）：")
    add("")
    for name, value in inputs.items():
        add(f"- `{name}` sha256 {value[:12]}")
    add("")
    add(f"四份数据与生成物都在 `{root_name}/`；回执在 `receipts.json`，这一页与它是同一条命令的产物。")
    return "\n".join(lines) + "\n"


def compare_libraries(
    a_data: dict[str, Any],
    a_receipts: dict[str, Any],
    b_data: dict[str, Any],
    b_receipts: dict[str, Any],
    vocabulary: dict[str, Any],
) -> dict[str, Any]:
    """Two libraries, compared on the controlled keys only — never on wording."""
    pairs: list[dict[str, Any]] = []
    for da in a_data["daos"]["daos"]:
        for db in b_data["daos"]["daos"]:
            same = da.get("tension_key") == db.get("tension_key")
            if same and da.get("move_key") == db.get("move_key"):
                relation = "变体（同一张力、同一方向，动作落在不同处）"
            elif same:
                relation = "相反（同一张力、不同方向）"
            else:
                relation = "无关（不同张力）"
            pairs.append(
                {
                    "a": da["id"],
                    "b": db["id"],
                    "a_tension": da.get("tension_key"),
                    "b_tension": db.get("tension_key"),
                    "a_move": da.get("move_key"),
                    "b_move": db.get("move_key"),
                    "relation": relation,
                }
            )
    a_tensions = [dao.get("tension_key") for dao in a_data["daos"]["daos"]]
    b_tensions = [dao.get("tension_key") for dao in b_data["daos"]["daos"]]
    episodes_a = {episode["id"]: episode for episode in a_data["episodes"]["episodes"]}
    episodes_b = {episode["id"]: episode for episode in b_data["episodes"]["episodes"]}
    return {
        "pairs": pairs,
        "shared": sorted(set(a_tensions) & set(b_tensions)),
        "only_a": sorted(set(a_tensions) - set(b_tensions)),
        "only_b": sorted(set(b_tensions) - set(a_tensions)),
        "changed": [],
        "a_status": {dao["id"]: status_of(dao, a_receipts[dao["id"]], episodes_a)["line"] for dao in a_data["daos"]["daos"]},
        "b_status": {dao["id"]: status_of(dao, b_receipts[dao["id"]], episodes_b)["line"] for dao in b_data["daos"]["daos"]},
    }


def render_compare(
    comparison: dict[str, Any],
    result: dict[str, Any],
    a_data: dict[str, Any],
    b_data: dict[str, Any],
    vocabulary: dict[str, Any],
    at: str | None,
) -> str:
    gloss = {term["key"]: term["gloss"] for term in vocabulary.get("tensions") or []}
    lines: list[str] = []
    add = lines.append
    same_pairs = [row for row in result["pairs"] if row["relation"].startswith(("变体", "相反"))]
    unrelated = [row for row in result["pairs"] if row["relation"].startswith("无关")]

    add(
        f"<!-- 这一页由命令生成，不要手改：python3 {BENCH} {a_data['root']} --compare {b_data['root']} --at <ISO8601> -->"
    )
    add("")
    add(f"# 对比：{a_data['root']} vs {b_data['root']}（{comparison.get('as_of')}）")
    add("")
    add("## 结论先说")
    add("")
    add(
        f"逐对比较 {len(result['pairs'])} 对：{len(same_pairs)} 对落在同一个张力上，{len(unrelated)} 对无关。"
        "对比只读：它不改任何一条道，所以第二个来源没有改动任何一条道。"
    )
    add("")
    add(f"两个库共有的张力：{'、'.join(result['shared']) if result['shared'] else '一个也没有'}。")
    if result["only_b"]:
        add("")
        add(f"第二个来源带来了第一个库没有的张力：{'、'.join(f'{key}（{gloss.get(key, '没写释义')}）' for key in result['only_b'])}。")
        add("这是第一个库的空白，不是一条能加进去的道——加不加由它的来源类别决定，不由它读起来有没有用决定。")
    if result["only_a"]:
        add("")
        add(f"第一个库有、第二个来源没有的张力：{'、'.join(result['only_a'])}。")
    add("")

    add("## 逐对关系（只按受控键比，不按措辞比）")
    add("")
    add("| 甲 | 乙 | 甲的张力键 | 乙的张力键 | 甲的动作键 | 乙的动作键 | 关系 |")
    add("|---|---|---|---|---|---|---|")
    for row in result["pairs"]:
        add(
            f"| {row['a']} | {row['b']} | {row['a_tension']} | {row['b_tension']} | {row['a_move']} | {row['b_move']} | {row['relation']} |"
        )
    add("")

    reading = comparison.get("reading") or {}
    add("## 读法（写的人读出来的，不是算出来的）")
    add("")
    add(f"标注：{reading.get('label', '（没标）')}")
    add("")
    for sentence in reading.get("says") or []:
        add(sentence)
        add("")

    add("## 这个对比不能证明什么")
    add("")
    add(comparison.get("limit", "（没写）"))
    add("")
    add(f"要回答那个问题，需要的是：{comparison.get('what_would_answer_it', '（没写）')}")
    add("")
    add(f"在它之前：{comparison.get('consequence_if_absent', '（没写）')}")
    add("")

    add("## 两个库现在的状态")
    add("")
    for dao_id, line in result["a_status"].items():
        add(f"- {a_data['root']} · {dao_id}：{line}")
    for dao_id, line in result["b_status"].items():
        add(f"- {b_data['root']} · {dao_id}：{line}")
    add("")
    add(
        f"重跑：`python3 {BENCH} {a_data['root']} --compare {b_data['root']} --at <ISO8601>`；"
        "这一页与两个库的 `receipts.json` 是同一条命令的产物。"
    )
    return "\n".join(lines) + "\n"


class NoteError(Exception):
    """A probe note that cannot enter the loop, with the reason named."""


NOTE_HEADER = ("person", "date", "minutes", "sample")
NOTE_SECTIONS = ("逐字", "张力")
TENSION_ID = re.compile(r"^[-*]\s*\[(?P<id>[^\]]+)\]\s*(?P<pair>.+?)\s*$")
TENSION_FIELD = re.compile(r"^(情境|方向|原话|锚)\s*:\s*(?P<value>.*)$")
NOTE_STAMP = re.compile(r"^\[(?P<stamp>\d{2}:\d{2})\]")


def _parse_note(path: Path) -> dict[str, Any]:
    """The probe page's format, read strictly. Every refusal names what is wrong."""
    if not path.exists():
        raise NoteError(f"{path.parent} 里既没有 episodes.json，也没有 note.md")
    text = path.read_text(encoding="utf-8")
    header: dict[str, str] = {}
    sections: dict[str, list[str]] = {name: [] for name in NOTE_SECTIONS}
    current = None
    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("<!--"):
            continue
        if line.startswith("## "):
            name = line[3:].strip()
            if name not in sections:
                raise NoteError(f"不认识的节「{name}」：探针笔记只有「## 逐字」与「## 张力」两节")
            current = name
            continue
        if current is None:
            if ":" not in line:
                raise NoteError(f"头部行「{line}」不是 key: value 的形状")
            key, value = line.split(":", 1)
            header[key.strip()] = value.strip()
            continue
        sections[current].append(line)

    for key in NOTE_HEADER:
        if not header.get(key):
            raise NoteError(f"笔记缺头部行 {key}:（探针页要求四行头：person / date / minutes / sample）")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", header["date"]):
        raise NoteError(f"date 写成「{header['date']}」；探针页要求 YYYY-MM-DD")
    if not header["minutes"].isdigit():
        raise NoteError(f"minutes 写成「{header['minutes']}」；要一个整数分钟")
    if header["sample"] not in {"acquaintances", "strangers"}:
        raise NoteError(f"sample 写成「{header['sample']}」；只能是 acquaintances 或 strangers")
    if not sections["逐字"]:
        raise NoteError("「## 逐字」是空的：没有原话，张力就没有锚")
    stamps = {match.group("stamp") for line in sections["逐字"] if (match := NOTE_STAMP.match(line.strip()))}
    if not stamps:
        raise NoteError("「## 逐字」里没有一条带 [MM:SS] 时间戳的行")
    if not sections["张力"]:
        raise NoteError("「## 张力」是空的：没有张力，就没有什么可以进库")

    tensions = []
    for index, line in enumerate(sections["张力"], 1):
        stripped = line.strip()
        if not stripped.startswith(("-", "*")):
            raise NoteError(f"「## 张力」第 {index} 行不是一条张力（要以 - 开头）：{stripped[:40]}")
        chunks = [chunk.strip() for chunk in stripped.split("|")]
        head = TENSION_ID.match(chunks[0])
        if not head:
            raise NoteError(f"「## 张力」第 {index} 行的开头不是「- [pX-T1] A ↔ B」：{chunks[0][:40]}")
        fields: dict[str, str] = {}
        for chunk in chunks[1:]:
            match = TENSION_FIELD.match(chunk)
            if not match:
                raise NoteError(f"张力 {head.group('id')} 有一格读不出来：「{chunk[:30]}」（五格是 情境/方向/原话/锚）")
            fields[match.group(1)] = match.group("value").strip()
        for name in ("情境", "方向", "原话", "锚"):
            if not fields.get(name):
                raise NoteError(f"张力 {head.group('id')} 少了「{name}」这一格")
        pair = head.group("pair")
        sides = [side.strip() for side in pair.split("↔")]
        if len(sides) != 2 or not all(sides):
            raise NoteError(f"张力 {head.group('id')} 的「{pair}」不是一个 ↔ 两边的名词短语")
        quote = fields["原话"]
        if len(quote) < 2 or not (quote.startswith('"') and quote.endswith('"')):
            raise NoteError(f"张力 {head.group('id')} 的原话必须逐字带引号：{quote[:30]}")
        anchor = fields["锚"]
        if not re.fullmatch(r"\d{2}:\d{2}", anchor):
            raise NoteError(f"张力 {head.group('id')} 的锚「{anchor}」不是 MM:SS")
        if anchor not in stamps:
            raise NoteError(f"张力 {head.group('id')} 的锚 {anchor} 在「## 逐字」里找不到；没有锚的行不能进库")
        tensions.append(
            {
                "id": head.group("id"),
                "pair": pair,
                "sides": sides,
                "situation": fields["情境"],
                "direction": fields["方向"],
                "quote": quote[1:-1],
                "anchor": anchor,
            }
        )
    return {"header": header, "tensions": tensions, "text": text, "path": path}


def _require(author: dict[str, Any], keys: tuple[str, ...], where: str) -> None:
    for key in keys:
        value = author.get(key)
        if isinstance(value, str):
            ok = bool(value.strip())
        else:
            ok = value not in (None, [], {})
        if not ok:
            raise NoteError(f"{where} 少了「{key}」：笔记只记到情境/张力/方向/原话/锚，其余要人写，本命令不替你决定")


def build_library_from_note(root: Path) -> dict[str, Any]:
    """One probe session in, one library out — the same loop, no code change per person."""
    note = _parse_note(root / "note.md")
    extraction_path = root / "extraction.json"
    if not extraction_path.exists():
        raise NoteError(
            "note.md 旁边没有 extraction.json：笔记只记到情境/张力/方向/原话/锚，"
            "动作的落点、代价、失效条件与规则表要人写；本命令不替你决定"
        )
    extraction = json.loads(extraction_path.read_text(encoding="utf-8"))
    attribution = extraction.get("attribution")
    if attribution not in ATTRIBUTION_CLASSES:
        raise NoteError(
            "extraction.json 没写来源类别（person / relayed / synthetic / unverified）："
            "这个命令不猜一个人是不是真的坐在那儿"
        )
    authored = {item.get("tension"): item for item in extraction.get("daos") or []}
    person = note["header"]["person"]
    person_slug = re.sub(r"[^0-9A-Za-z_-]", "-", person) or "p"

    episodes = []
    daos = []
    needed = []
    for tension in note["tensions"]:
        author = authored.get(tension["pair"])
        if author is None:
            raise NoteError(
                f"extraction.json 里没有「{tension['pair']}」这一条：笔记里有、提炼里没有，不半途入库"
            )
        where = f"extraction.json 的「{tension['pair']}」"
        _require(author, ("title", "one_line", "tension_key", "move_key", "tension_why", "conditions", "price", "off", "axes", "rule", "move", "situation"), where)
        _require(author["move"], ("locus", "magnitude"), where + " 的 move")
        _require(author["situation"], ("who", "when", "constraints", "domain"), where + " 的 situation")
        tid_slug = re.sub(r"[^0-9A-Za-z_-]", "-", tension["id"])
        episode_id = f"ep-{tid_slug}"
        dao_id = f"dao-{tid_slug}"
        episodes.append(
            {
                "id": episode_id,
                "at": note["header"]["date"],
                "at_basis": "探针笔记头部的 date:",
                "attribution": attribution,
                "attribution_note": extraction.get("attribution_note", ""),
                "quote": tension["quote"],
                "source": {
                    "path": str(note["path"]),
                    "ref": f"张力 {tension['id']}（锚 {tension['anchor']}）",
                },
                "observed_action": f"笔记记下的偏向：{tension['direction']}（锚 {tension['anchor']}）",
                "conditions": author["conditions"],
                "reading": author.get("reading", "读法是提炼那一步写的，不是笔记本身。"),
            }
        )
        daos.append(
            {
                "id": dao_id,
                "version": 1,
                "title": author["title"],
                "tension_key": author["tension_key"],
                "move_key": author["move_key"],
                "one_line": author["one_line"],
                "situation": {
                    "who": author["situation"]["who"],
                    "when": author["situation"].get("when") or tension["situation"],
                    "constraints": author["situation"]["constraints"],
                    "domain": author["situation"]["domain"],
                    "covers": [episode_id],
                },
                "tension": {"name": tension["pair"], "sides": tension["sides"], "why": author["tension_why"]},
                "move": {
                    "on_tension": tension["pair"],
                    "direction": author["move"].get("direction") or tension["direction"],
                    "locus": author["move"]["locus"],
                    "magnitude": author["move"]["magnitude"],
                },
                "price": author["price"],
                "off": author["off"],
                "axes": author["axes"],
                "rule": author["rule"],
                "provenance": [
                    {
                        "person": person,
                        "episode": episode_id,
                        "status": author.get("status") or "自述",
                        "learned_from": "亲历",
                        "exposure": "none-at-time",
                    }
                ],
                "part_sources": author.get("part_sources")
                or {
                    "situation": "推断",
                    "tension": "记录",
                    "move": "记录",
                    "price": "推断",
                    "off": "推断",
                    "provenance": "记录",
                },
            }
        )
        if author.get("needed"):
            needed.append({"dao": dao_id, **author["needed"]})

    window = {
        "first_session": note["header"]["date"],
        "last_person_input": note["header"]["date"],
        "rule": "笔记只有一场。出现更晚的材料说明还有另一场，本库不收它：一场一个库。",
    }
    data = {
        "episodes": {"layer": "events", "owner": "探针笔记", "window": window, "episodes": episodes},
        "daos": {"layer": "extraction", "owner": extraction.get("owner", "提炼那一步"), "daos": daos},
        "observations": {
            "layer": "checks",
            "observations": extraction.get("observations") or [],
            "needed": needed,
        },
        "exposures": {"layer": "checks", "rows": extraction.get("exposures") or []},
        "map": {
            "layer": "extraction",
            "connections": (extraction.get("map") or {}).get("connections") or [],
            "boundaries": (extraction.get("map") or {}).get("boundaries") or [],
            "candidates": (extraction.get("map") or {}).get("candidates") or [],
        },
        "root": str(root),
        "derived_from_note": str(note["path"]),
        "note_sha256": hashlib.sha256(note["text"].encode("utf-8")).hexdigest(),
    }
    return data


def load_library(root: Path) -> dict[str, Any]:
    if not (root / "episodes.json").exists():
        return build_library_from_note(root)
    data = {
        "episodes": load(root / "episodes.json"),
        "daos": load(root / "daos.json"),
        "observations": load(root / "observations.json"),
        "exposures": load(root / "exposures.json"),
        "map": load(root / "map.json"),
        "refusals": load(root / "refusals.json") if (root / "refusals.json").exists() else {"items": []},
        "root": str(root),
    }
    return data


def within_library_relations(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Two entries in one library, judged by the substitution test's two keys only."""
    relations = []
    daos = data["daos"]["daos"]
    for index, left in enumerate(daos):
        for right in daos[index + 1:]:
            if left.get("tension_key") != right.get("tension_key"):
                continue
            kind = "同一条" if left.get("move_key") == right.get("move_key") else "相反"
            relations.append({"a": left["id"], "b": right["id"], "kind": kind, "on": left.get("tension_key")})
    return relations


def check_library(data: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    """What a single entry cannot see: duplicates, self-contradictions, and what was refused."""
    failures: list[str] = []
    dao_ids = {dao["id"] for dao in data["daos"]["daos"]}
    relations = within_library_relations(data)
    contradictions = {
        tuple(sorted(item.get("between") or [])): item for item in data["map"].get("contradictions") or []
    }
    for relation in relations:
        if relation["kind"] == "同一条":
            failures.append(
                f"{relation['a']} 与 {relation['b']} 按替换试验是同一条（张力与方向都相同）：留一条，另一条退回 refusals"
            )
        elif tuple(sorted([relation["a"], relation["b"]])) not in contradictions:
            failures.append(
                f"{relation['a']} 与 {relation['b']} 在同一张力上方向相反，但没有写进 map.json 的 contradictions"
            )
    for pair, item in contradictions.items():
        if len(pair) != 2 or any(dao_id not in dao_ids for dao_id in pair):
            failures.append(f"contradictions 里的 {item.get('id')} 指的 {pair} 不是库里的一对道")
        for key in ("on", "state", "what_would_settle_it"):
            if not item.get(key):
                failures.append(f"contradictions 的 {item.get('id')} 少了「{key}」")

    refusals = data.get("refusals") or {}
    items = refusals.get("items") or []
    episodes_by_id = {episode["id"]: episode for episode in data["episodes"]["episodes"]}
    real_source = any(
        (episodes_by_id.get(item.get("episode")) or {}).get("attribution") in {"person", "relayed"}
        for dao in data["daos"]["daos"]
        for item in dao.get("provenance") or []
    )
    if not items and real_source:
        failures.append("refusals.json 是空的：一份只收得进东西的库证明不了这个形状会挑")
    for item in items:
        if not item.get("why"):
            failures.append(f"refusal {item.get('id')} 没写为什么写不成")
        if not (item.get("source") or {}).get("path"):
            failures.append(f"refusal {item.get('id')} 没写材料在哪")
        missing = item.get("missing") or []
        if not missing:
            failures.append(f"refusal {item.get('id')} 没写缺哪一件：拒收的意义就在这一栏")
        unknown = [name for name in missing if name not in REFUSAL_PARTS]
        if unknown:
            failures.append(f"refusal {item.get('id')} 缺的那件不在六件里：{unknown}")
        if "重复" in missing and item.get("duplicate_of") not in dao_ids:
            failures.append(f"refusal {item.get('id')} 说是重复，但没写它重复的是哪一条道")

    counts: dict[str, int] = {name: 0 for name in REFUSAL_PARTS}
    for item in items:
        for name in item.get("missing") or []:
            counts[name] = counts.get(name, 0) + 1
    summary = {
        "entered": len(data["daos"]["daos"]),
        "refused": len(items),
        "refusal_counts": counts,
        "relations": relations,
        "contradictions": len(contradictions),
        "candidates": len(data["map"].get("candidates") or []),
    }
    return failures, summary


def report_library(root: Path, data: dict[str, Any], receipts: dict[str, Any]) -> list[str]:
    """Print one library's state; return what judged against it failed."""
    episodes = {episode["id"]: episode for episode in data["episodes"]["episodes"]}
    needed = {item.get("dao") for item in data["observations"].get("needed") or []}
    failures: list[str] = []
    origin = f"由 {data['derived_from_note']} 推出" if data.get("derived_from_note") else "落盘库"
    print(f"dao-life：{len(data['daos']['daos'])} 条道（{root}，{origin}）")
    for dao in data["daos"]["daos"]:
        receipt = receipts[dao["id"]]
        state = status_of(dao, receipt, episodes)
        print(f"  {dao['id']}  v{dao['version']}  {state['line']}")
        for kind in ("structure", "falsifiable"):
            if receipt[kind]["verdict"] == "fail":
                failures.append(
                    f"{dao['id']} {kind}：" + "；".join(receipt[kind].get("failures") or receipt[kind].get("notes") or [])
                )
        missing = missing_receipts(dao, receipt)
        if missing:
            failures.append(f"{dao['id']}：这些格的回执还是旧版本的，得重跑——{missing}")
        if receipt["field"]["verdict"] == "not_run" and dao["id"] not in needed:
            failures.append(f"{dao['id']}：落地未跑，但没写「要什么才能给这一格一条观察」")
    for dao_id in needed - {dao["id"] for dao in data["daos"]["daos"]}:
        failures.append(f"needed 里有一条指向不存在的道：{dao_id}")
    library_failures, summary = check_library(data)
    failures += library_failures
    counts = summary["refusal_counts"]
    print(
        "  入道 {entered} 条；拒收 {refused} 条（"
        "情境 {situation} / 张力 {tension} / 动作 {move} / 代价 {price} / 失效 {off} / 归属 {provenance} / 重复 {dup}）；"
        "候选 {candidates} 条；库内同张力 {same} 对同一条、{opp} 对相反".format(
            entered=summary["entered"],
            refused=summary["refused"],
            candidates=summary["candidates"],
            situation=counts.get("情境", 0),
            tension=counts.get("张力", 0),
            move=counts.get("动作", 0),
            price=counts.get("代价", 0),
            off=counts.get("失效", 0),
            provenance=counts.get("归属", 0),
            dup=counts.get("重复", 0),
            same=len([r for r in summary["relations"] if r["kind"] == "同一条"]),
            opp=len([r for r in summary["relations"] if r["kind"] == "相反"]),
        )
    )
    dao_ids = {dao["id"] for dao in data["daos"]["daos"]}
    for candidate in (data.get("map") or {}).get("candidates") or []:
        if candidate.get("id") in dao_ids:
            failures.append(f"候选 {candidate.get('id')} 与库里的道同 id：候选不能既是道又是候选")
        for key in ("one_line", "why_not_entered", "what_would_support_it", "suggested_by"):
            if not candidate.get(key):
                failures.append(f"候选 {candidate.get('id')} 少了「{key}」：候选要写明它为什么还不成立")
        for source in candidate.get("suggested_by") or []:
            if source not in dao_ids:
                failures.append(f"候选 {candidate.get('id')} 指向不存在的道：{source}")
    print(independent_groups(data)["line"])
    return failures


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__.strip().splitlines()[0])
        print(f"用法：python3 {BENCH} <数据目录> [--at ISO8601] [--check] [--compare 另一个数据目录] [--vocabulary 词表]")
        return 2
    root = Path(argv[1])
    at = None
    write = True
    compare_dir = None
    vocabulary_path = None
    rest = argv[2:]
    index = 0
    while index < len(rest):
        token = rest[index]
        if token in {"--at", "--compare", "--vocabulary"} and index + 1 < len(rest):
            value = rest[index + 1]
            if token == "--at":
                at = value
            elif token == "--compare":
                compare_dir = Path(value)
            else:
                vocabulary_path = Path(value)
            index += 2
            continue
        if token == "--check":
            write = False
            index += 1
            continue
        print(f"不认识的参数：{token}")
        return 2

    vocabulary_file = vocabulary_path or (root.parent / "vocabulary.json")
    try:
        vocabulary = load(vocabulary_file)
    except (OSError, json.JSONDecodeError) as error:
        print(f"拒收（{root.parent}）：词表读不出来：{error}")
        print("词表默认取数据目录上一层的 vocabulary.json，可用 --vocabulary 指定。没有写任何文件。")
        return 1
    try:
        data = load_library(root)
        inputs = {
            name: digest(data[name])
            for name in ("episodes", "daos", "observations", "exposures", "map", "refusals")
            if name in data
        }
        if data.get("note_sha256"):
            inputs["note"] = data["note_sha256"]
        receipts = run_bench(data, at, vocabulary)
        failures = report_library(root, data, receipts)
        other = None
        if compare_dir is not None:
            other = load_library(compare_dir)
    except NoteError as error:
        print(f"拒收（{root}）：{error}")
        print("没有写任何文件。")
        return 1
    if compare_dir is not None:
        other_receipts = run_bench(other, at, vocabulary)
        failures += report_library(compare_dir, other, other_receipts)
        other_inputs = {name: digest(other[name]) for name in ("episodes", "daos", "observations", "exposures", "map")}
        comparison = load(root.parent / "comparison.json")
        given = (str(root.resolve()), str(compare_dir.resolve()))
        declared = (
            str((root.parent / comparison["a"]).resolve()),
            str((root.parent / comparison["b"]).resolve()),
        )
        if given != declared:
            failures.append(f"comparison.json 说的是 {declared}，这次跑的是 {given}；先改那一条再跑")
        result = compare_libraries(data, receipts, other, other_receipts, vocabulary)
        print(f"对比：{len(result['pairs'])} 对；同一张力 {len([r for r in result['pairs'] if r['relation'][:2] in {'变体', '相反'}])} 对；"
              f"共有的张力 {result['shared'] or '无'}；第二个来源带来的张力 {result['only_b'] or '无'}")

    if failures:
        print("判不过：")
        for line in failures:
            print(f"  - {line}")
    if not write:
        print("--check：不写盘")
        return 1 if failures else 0
    if failures:
        return 1

    for target, payload_data, payload_receipts, payload_inputs in (
        (root, data, receipts, inputs),
    ):
        target_episodes = {episode["id"]: episode for episode in payload_data["episodes"]["episodes"]}
        payload = {
            "layer": "checks",
            "bench": BENCH,
            "bench_version": BENCH_VERSION,
            "at": at,
            "inputs": payload_inputs,
            "daos": {
                dao["id"]: {
                    "id": dao["id"],
                    "version": dao["version"],
                    "digest": digest(dao),
                    "receipts": payload_receipts[dao["id"]],
                    "status": status_of(dao, payload_receipts[dao["id"]], target_episodes),
                }
                for dao in payload_data["daos"]["daos"]
            },
        }
        (target / "receipts.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (target / "道图.md").write_text(
            render(payload_data, payload_receipts, at, payload_inputs, vocabulary), encoding="utf-8"
        )
        print(f"写入 {target / 'receipts.json'}")
        print(f"写入 {target / '道图.md'}")

    if other is not None:
        other_episodes = {episode["id"]: episode for episode in other["episodes"]["episodes"]}
        payload = {
            "layer": "checks",
            "bench": BENCH,
            "bench_version": BENCH_VERSION,
            "at": at,
            "inputs": other_inputs,
            "daos": {
                dao["id"]: {
                    "id": dao["id"],
                    "version": dao["version"],
                    "digest": digest(dao),
                    "receipts": other_receipts[dao["id"]],
                    "status": status_of(dao, other_receipts[dao["id"]], other_episodes),
                }
                for dao in other["daos"]["daos"]
            },
        }
        (compare_dir / "receipts.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (compare_dir / "道图.md").write_text(render(other, other_receipts, at, other_inputs, vocabulary), encoding="utf-8")
        print(f"写入 {compare_dir / 'receipts.json'}")
        print(f"写入 {compare_dir / '道图.md'}")
        (root / "对比.md").write_text(
            render_compare(comparison, result, data, other, vocabulary, at), encoding="utf-8"
        )
        print(f"写入 {root / '对比.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
