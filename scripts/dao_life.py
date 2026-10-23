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
    "later_session": ("他人的后续会话（弱：不是对照）", "验过（弱：后续，非对照）"),
    "agent_self": ("自验（agent，弱一档）", "验过（弱一档：自验）"),
    "controlled": ("有意的对照（量过）", "量过"),
}
OBSERVATION_STRENGTH = {"agent_self": 1, "later_session": 2, "controlled": 3}
VERDICT_WORD = {"pass": "过", "fail": "不过", "not_run": "未跑", "uncertain": "不确定"}
ATTRIBUTION_CLASSES = ("person", "relayed", "synthetic", "unverified")
SOURCE_WORD = {"person": "自述", "relayed": "自述（转述）", "synthetic": "模拟", "unverified": "传闻"}
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
    people = set()
    for dao in data["daos"]["daos"]:
        for item in dao.get("provenance") or []:
            episode = next((e for e in data["episodes"]["episodes"] if e["id"] == item.get("episode")), {})
            if episode.get("attribution") == "unverified":
                continue
            people.add(item.get("person"))
    exposures = data["exposures"].get("rows") or []
    synthetic_only = bool(people) and all(person.startswith("synthetic") for person in people)
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

    states = {dao["id"]: status_of(dao, receipts[dao["id"]], episodes) for dao in daos}
    landed = [dao["id"] for dao in daos if receipts[dao["id"]]["field"]["verdict"] != "not_run"]
    add("## 这张图里有什么")
    add("")
    add(f"{len(daos)} 条道，每条六件套齐全；{len(daos)} 条都有自洽与可反驳两张回执，落地那一格 {len(landed)} 条有观察、{len(daos) - len(landed)} 条是「未跑」。")
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


def load_library(root: Path) -> dict[str, Any]:
    data = {
        "episodes": load(root / "episodes.json"),
        "daos": load(root / "daos.json"),
        "observations": load(root / "observations.json"),
        "exposures": load(root / "exposures.json"),
        "map": load(root / "map.json"),
        "root": str(root),
    }
    return data


def report_library(root: Path, data: dict[str, Any], receipts: dict[str, Any]) -> list[str]:
    """Print one library's state; return what judged against it failed."""
    episodes = {episode["id"]: episode for episode in data["episodes"]["episodes"]}
    needed = {item.get("dao") for item in data["observations"].get("needed") or []}
    failures: list[str] = []
    print(f"dao-life：{len(data['daos']['daos'])} 条道（{root}）")
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

    vocabulary = load(vocabulary_path or (root.parent / "vocabulary.json"))
    data = load_library(root)
    inputs = {name: digest(data[name]) for name in ("episodes", "daos", "observations", "exposures", "map")}
    receipts = run_bench(data, at, vocabulary)
    failures = report_library(root, data, receipts)

    other = None
    if compare_dir is not None:
        other = load_library(compare_dir)
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
