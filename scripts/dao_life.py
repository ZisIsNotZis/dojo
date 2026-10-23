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


def _add(checks: list[dict[str, Any]], name: str, ok: Any, detail: str = "") -> None:
    checks.append({"name": name, "ok": bool(ok), "detail": detail})


def check_structure(
    dao: dict[str, Any],
    episodes: dict[str, dict[str, Any]],
    window: dict[str, Any],
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
        f"没有 {window.get('last_person_input')} 之后的 person 输入（第一场之后不再要他补）",
        not late,
        f"晚了：{late}",
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
    eligible = [
        row
        for row in rows
        if row.get("kind") in OBSERVATION_KINDS and not row.get("elicited", False) and row.get("at", "") > latest_case
    ]
    if not eligible:
        return {
            "kind": "field",
            "ran": None,
            "verdict": "not_run",
            "observation": None,
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
        "note": "观察晚于案例，且不是被问出来的；它证明的是一条相符或相悖的观察存在，不是这条道为真。",
    }


def status_of(dao: dict[str, Any], receipts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    structure = receipts["structure"]["verdict"]
    falsifiable = receipts["falsifiable"]["verdict"]
    field = receipts["field"]
    passed = sum(1 for verdict in (structure, falsifiable, field["verdict"]) if verdict == "pass")
    base = ((dao.get("provenance") or [{}])[0].get("status")) or "自述"
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


def run_bench(data: dict[str, Any], at: str | None) -> dict[str, Any]:
    episodes = {episode["id"]: episode for episode in data["episodes"]["episodes"]}
    window = data["episodes"]["window"]
    observations = data["observations"]["observations"]
    receipts: dict[str, dict[str, Any]] = {}
    for dao in data["daos"]["daos"]:
        receipts[dao["id"]] = {
            "structure": check_structure(dao, episodes, window, at),
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
    return {
        "people": sorted(people),
        "groups": len(people),
        "exposures": len(exposures),
        "line": f"独立来源 {len(people)} 组（不同的人 {len(people)} 个；曝光账本 {len(exposures)} 行）。"
        "曝光未知按「不独立」算：这里是一个人的道理，不是共识。",
    }


def _situation_text(situation: dict[str, Any]) -> str:
    if not situation:
        return "（没有写条件）"
    return "；".join(f"{key}={value}" for key, value in situation.items())


def render(data: dict[str, Any], receipts: dict[str, Any], at: str | None, inputs: dict[str, str]) -> str:
    episodes = {episode["id"]: episode for episode in data["episodes"]["episodes"]}
    daos = data["daos"]["daos"]
    groups = independent_groups(data)
    lines: list[str] = []
    add = lines.append

    add(f"<!-- 这一页由命令生成，不要手改：python3 {BENCH} docs/dao/person-dojo --at <ISO8601> -->")
    add("")
    add("# 道图：一个人的三条道（person，2026-10-23）")
    add("")
    add("三条道说的是同一件事：你要我把「活」拿走，但要先把「样子」和「价」摆在你面前。")
    add("其中有一条边界是我读出来的、你没说过；一句话就能推翻它，见「连接与边界」。")
    add("")

    states = {dao["id"]: status_of(dao, receipts[dao["id"]]) for dao in daos}
    landed = [dao["id"] for dao in daos if receipts[dao["id"]]["field"]["verdict"] != "not_run"]
    add("## 这张图里有什么")
    add("")
    add(f"{len(daos)} 条道，每条六件套齐全；{len(daos)} 条都有自洽与可反驳两张回执，落地那一格 {len(landed)} 条有观察、{len(daos) - len(landed)} 条是「未跑」。")
    add(f"{groups['line']}")
    add("提炼是这次会话的 manager 从记录里读出来的（凡读法处标「推断」），不是模型判定：这一包 0 次模型调用。")
    add("")

    add("## 一条道长什么样")
    add("")
    add("在 S 里，宁可 A 不 B，代价是 C；当出现 D 时，反过来。S 是适用域，A/B 是张力，C 是价格，D 是失效条件。")
    add("")

    for dao in daos:
        state = states[dao["id"]]
        receipt = receipts[dao["id"]]
        add(f"## 道{['一', '二', '三', '四', '五'][daos.index(dao)]}　{dao['id']}　{dao['title']}")
        add("")
        add(f"> {dao['one_line']}")
        add("")
        add("| 件 | 内容 |")
        add("|---|---|")
        situation = dao["situation"]
        add(f"| 情境 | 谁：{situation['who']}；何时：{situation['when']}；约束：{'、'.join(situation['constraints'])}；领域：{'、'.join(situation['domain'])} |")
        tension = dao["tension"]
        add(f"| 张力 | {tension['name']}——两头是「{tension['sides'][0]}」与「{tension['sides'][1]}」。{tension['why']} |")
        move = dao["move"]
        add(f"| 动作 | {move['direction']}；作用在：{move['locus']}；幅度：{move['magnitude']} |")
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
            anchors.append(f"- 「{episode.get('quote', '（没有原话）')}」（`{episode.get('source', {}).get('path')}` {episode.get('source', {}).get('ref')}）")
            if episode.get("attribution") == "unverified":
                anchors[-1] += "　— 署名未核，只当旁证，不计入独立性"
        add("原话：")
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
            add(f"落地 {VERDICT_WORD[field['verdict']]}（{field['strength']}）：{observation['prediction']} 混杂未排除：{observation.get('confound', '（没写）')}")
        add("")

    add("## 连接与边界（你没说过的那一处）")
    add("")
    for connection in data["map"]["connections"]:
        add(f"**{connection['id']}　连接**：{connection['says']}")
        add("")
        add(f"为什么算新的：{connection['why_it_may_be_new']}　状态：`{connection['status']}`")
        add("")
    for boundary in data["map"]["boundaries"]:
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
        add("落地这一格每条都有观察。")
    add(f"组织性（A2）没有人替你确认：`{data['map']['boundaries'][0]['id']}` 标的是 `待确认`，不是 `已确认`。")
    add("")

    add("## 重跑与证据")
    add("")
    add(f"重跑：`python3 {BENCH} docs/dao/person-dojo --at <ISO8601>`；不带 `--at` 也能跑，回执里的时间会写成 null。")
    add("")
    add("输入（按排序后的 JSON 算内容 sha256，取前 12 位；不随排版变）：")
    add("")
    for name, value in inputs.items():
        add(f"- `{name}` sha256 {value[:12]}")
    add("")
    add("事件、道、观察、曝光四份数据在 `docs/dao/person-dojo/`；回执在 `receipts.json`，这一页与它是同一条命令的产物。")
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__.strip().splitlines()[0])
        print(f"用法：python3 {BENCH} <数据目录> [--at ISO8601] [--check]")
        return 2
    root = Path(argv[1])
    at = None
    write = True
    rest = argv[2:]
    index = 0
    while index < len(rest):
        token = rest[index]
        if token == "--at" and index + 1 < len(rest):
            at = rest[index + 1]
            index += 2
            continue
        if token == "--check":
            write = False
            index += 1
            continue
        print(f"不认识的参数：{token}")
        return 2

    data = {
        "episodes": load(root / "episodes.json"),
        "daos": load(root / "daos.json"),
        "observations": load(root / "observations.json"),
        "exposures": load(root / "exposures.json"),
        "map": load(root / "map.json"),
    }
    inputs = {
        name: digest(data[name])
        for name in ("episodes", "daos", "observations", "exposures", "map")
    }
    receipts = run_bench(data, at)

    failures: list[str] = []
    print(f"dao-life：{len(data['daos']['daos'])} 条道（{root}）")
    for dao in data["daos"]["daos"]:
        receipt = receipts[dao["id"]]
        state = status_of(dao, receipt)
        print(f"  {dao['id']}  v{dao['version']}  {state['line']}")
        for kind in ("structure", "falsifiable"):
            if receipt[kind]["verdict"] == "fail":
                failures.append(f"{dao['id']} {kind}：" + "；".join(receipt[kind].get("failures") or receipt[kind].get("notes") or []))
        missing = missing_receipts(dao, receipt)
        if missing:
            failures.append(f"{dao['id']}：这些格的回执还是旧版本的，得重跑——{missing}")

    print(independent_groups(data)["line"])
    if failures:
        print("判不过：")
        for line in failures:
            print(f"  - {line}")
    if not write:
        print("--check：不写盘")
        return 1 if failures else 0

    payload = {
        "layer": "checks",
        "bench": BENCH,
        "bench_version": BENCH_VERSION,
        "at": at,
        "inputs": inputs,
        "daos": {
            dao["id"]: {
                "id": dao["id"],
                "version": dao["version"],
                "digest": digest(dao),
                "receipts": receipts[dao["id"]],
                "status": status_of(dao, receipts[dao["id"]]),
            }
            for dao in data["daos"]["daos"]
        },
    }
    (root / "receipts.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (root / "道图.md").write_text(render(data, receipts, at, inputs), encoding="utf-8")
    print(f"写入 {root / 'receipts.json'}")
    print(f"写入 {root / '道图.md'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
