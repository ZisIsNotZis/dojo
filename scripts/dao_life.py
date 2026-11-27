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
import os
import subprocess
import tempfile
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dojo.elicit import (  # noqa: E402  —— 四句问法与「谁写的」只有一份，在 dojo/elicit.py
    PART_LABELS,
    PART_NAMES,
    PART_SOURCES,
    authorship,
    his_parts,
    supplied_parts,
)

BENCH = "scripts/dao_life.py"
# `source.path` is written from the repository root ("idea.md", "mail/…"), not from
# the library directory, and this file is the repository's own script — so it is
# the anchor both the quote lookup and the commit check resolve against.
REPO_ROOT = Path(__file__).resolve().parents[1]
BENCH_VERSION = 2
# The citation reading changed shape (revision-only checking, multiple occurrences), so
# it carries its own version: the other three readings did not change, and bumping the
# shared number would re-version receipts that are still accurate.
SOURCES_VERSION = 4
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
TIME_BASIS_STRENGTH = {"date_convention": 1, "local_times": 2, "exact_instants": 3}
TIME_BASIS_NOTE = {
    "date_convention": "按日粒度约定接纳；实际先后未证实。",
    "local_times": "按未声明时区的本地时间比较接纳；假设两者采用同一时区，实际先后未证实。",
    "exact_instants": "按带时区的精确时刻比较，观察晚于全部来源案例。",
}
VERDICT_WORD = {"pass": "过", "fail": "不过", "not_run": "未跑", "uncertain": "不确定"}
ATTRIBUTION_CLASSES = ("person", "relayed", "synthetic", "unverified")
SOURCE_WORD = {"person": "自述", "relayed": "自述（转述）", "synthetic": "模拟", "unverified": "传闻"}
PROVENANCE_STATUS = {"person": "自述", "relayed": "转述", "synthetic": "模拟", "unverified": "未核"}
PART_NAMES = ("situation", "tension", "move", "price", "off", "provenance")

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


def _parse_time(value: str) -> date | datetime | None:
    """Read explicit ISO dates/minute-or-finer timestamps; malformed values earn nothing."""
    if not isinstance(value, str):
        return None
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return date.fromisoformat(value)
        if re.fullmatch(
            r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?",
            value,
        ):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        pass
    return None


def later(observation_at: str, case_at: str) -> bool:
    """Compare actual instants when available, not date-string order.

    Preserve the library's day-granularity convention: a timed observation on
    the case's date counts as later. For two timestamps, missing timezone on
    only one side is incomparable, not evidence of temporal order.
    """
    observation = _parse_time(observation_at)
    case = _parse_time(case_at)
    if observation is None or case is None:
        return False
    if isinstance(observation, datetime) and isinstance(case, datetime):
        if (observation.tzinfo is None) != (case.tzinfo is None):
            return False
        return observation > case
    observation_date = observation.date() if isinstance(observation, datetime) else observation
    case_date = case.date() if isinstance(case, datetime) else case
    if observation_date != case_date:
        return observation_date > case_date
    return isinstance(observation, datetime) and not isinstance(case, datetime)


def _precision_detail(observation_at: str, case_times: list[str]) -> str:
    """Which side of the weakest accepted pair actually lacks precision.

    The old date_convention note said the reason was 'dates carry no exact
    moment or timezone'. That is false for a timed observation checked against
    a date-only case: the library holds `2026-10-23T13:11:00Z`. Naming the
    coarse side is a measurement; asserting both were coarse was not.
    """
    parsed_obs = _parse_time(observation_at)
    worst_case, worst_at = None, ""
    for case_at in case_times:
        parsed = _parse_time(case_at)
        if not isinstance(parsed, datetime):
            worst_case, worst_at = "case", case_at
            break
        if parsed.tzinfo is None and worst_case is None:
            worst_case, worst_at = "local", case_at
    if worst_case is None and isinstance(parsed_obs, datetime) and parsed_obs.tzinfo is None:
        worst_case, worst_at = "local_observation", observation_at
    if worst_case in ("case", "local"):
        side = "只到日" if worst_case == "case" else "没写时区"
        if not isinstance(parsed_obs, datetime):
            return f"（两侧都粗：案例 {worst_at} {side}，观察 {observation_at} 也只到日）"
        return f"（弱在案例那一侧：案例 {worst_at} {side}" + _obs_phrase(observation_at) + "）"
    if worst_case == "local_observation":
        return f"（弱在观察那一侧：观察 {observation_at} 没写时区）"
    return ""


def _obs_phrase(observation_at: str) -> str:
    parsed = _parse_time(observation_at)
    if not isinstance(parsed, datetime):
        return f"，观察 {observation_at} 也只到日"
    if parsed.tzinfo is None:
        return f"，观察 {observation_at} 写到分但没写时区"
    return f"，观察 {observation_at} 带时区"


def _time_basis(observation_at: str, case_at: str) -> str:
    """Describe an already accepted pair, without upgrading its precision."""
    observation, case = _parse_time(observation_at), _parse_time(case_at)
    if not isinstance(observation, datetime) or not isinstance(case, datetime):
        return "date_convention"
    return "exact_instants" if observation.tzinfo is not None and case.tzinfo is not None else "local_times"


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


def provenance_status_for(episode: dict[str, Any]) -> str:
    """The word a stored provenance row must carry, read off the source event.

    Two vocabularies, deliberately different: the 道图 prints a display word
    (`自述（转述）`, `传闻`) that reads as a sentence, while the stored field keeps
    the short form (`转述`, `未核`). The current tree deleted this table, so every
    relayed or unverified source was stored as `自述` and rendered as lived
    experience -- the defect K2's second review had already fixed upstream.
    """
    return PROVENANCE_STATUS.get(episode.get("attribution"), "来源未声明")


def _add(checks: list[dict[str, Any]], name: str, ok: Any, detail: str = "") -> None:
    checks.append({"name": name, "ok": bool(ok), "detail": detail})


PROVENANCE_KEYS = ("person", "episode", "status", "learned_from")


def missing_provenance_keys(dao: dict[str, Any]) -> list[str]:
    """Which provenance rows cannot be rendered at all, named by the key that is absent.

    #1831: `render` read `item['person']` straight out of the row, so a row without
    that key killed the page with a `TypeError` from inside a `sorted()` call while
    `check_structure` passed the same entry. A judgement that passes the shape the
    renderer crashes on is not judging the same object. Both sides now read this one
    list: the checker fails those rows, the renderer refuses with the same names.
    """
    problems: list[str] = []
    for index, item in enumerate(dao.get("provenance") or []):
        for key in PROVENANCE_KEYS:
            if key not in item or item[key] in (None, ""):
                problems.append(f"{dao.get('id', '?')} 第 {index + 1} 条归属缺键 {key!r}")
    return problems


def require_provenance_keys(dao: dict[str, Any]) -> None:
    """Refuse to render an entry whose provenance rows lack a required key."""
    problems = missing_provenance_keys(dao)
    if problems:
        raise NoteError(
            "; ".join(problems)
            + "；一条归属必须写明谁（person）、哪件事（episode）、什么状态（status）、从哪学的（learned_from）"
        )


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
    # #1831: the same defect the renderer used to crash on (`item['person']` with no
    # key) is judged here too, so a passing entry is one the page can actually print.
    incomplete = missing_provenance_keys(dao)
    _add(checks, "每条归属都有渲染所需的四键", bool(provenance) and not incomplete, f"缺：{incomplete}")
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
    status_errors = [
        f"{item.get('episode')}: {item.get('status')!r} != {provenance_status_for(episode)!r}"
        for item in provenance
        if (episode := episodes.get(item.get("episode")) or {})
        and item.get('status') != provenance_status_for(episode)
    ]
    _add(
        checks,
        "存储归属状态与事件来源一致",
        not status_errors,
        f"状态不匹配：{status_errors}",
    )
    lived_claims = [
        item.get('episode')
        for item in provenance
        if item.get('learned_from') == '亲历'
        and (episodes.get(item.get("episode")) or {}).get("attribution") != "person"
    ]
    _add(
        checks,
        "「亲历」只印在他本人的原话上",
        bool(provenance) and not lived_claims,
        f"不是本人的原话却记成亲历：{lived_claims}",
    )
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
    case_times = [episodes.get(item.get("episode"), {}).get("at", "") for item in dao.get("provenance") or []]
    rows = [row for row in observations if row.get("dao") == dao.get("id")]
    eligible: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for row in rows:
        reason = ""
        if row.get("kind") not in OBSERVATION_KINDS:
            reason = f"来源类别 {row.get('kind')!r} 不在三种里"
        elif row.get("elicited", False):
            reason = "是被问出来的，不是自然出现的"
        elif not case_times or not all(later(row.get("at", ""), case_at) for case_at in case_times):
            reason = f"不晚于全部案例或时间不可比较（案例 {case_times}，观察 {row.get('at')}）"
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
            "time_basis": None,
            "rejected": rejected,
            "note": "没有一条晚于案例、也不是被问出来的观察；不拿「他说过很多次」顶替。",
        }
    best = sorted(eligible, key=lambda row: OBSERVATION_STRENGTH[row["kind"]])[-1]
    verdict = "pass" if best.get("matched") is True else ("fail" if best.get("matched") is False else "uncertain")
    label, _word = OBSERVATION_KINDS[best["kind"]]
    time_basis = min(
        (_time_basis(best["at"], case_at) for case_at in case_times),
        key=TIME_BASIS_STRENGTH.__getitem__,
    )
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
        "time_basis": time_basis,
        "time_basis_detail": _precision_detail(best.get("at", ""), case_times),
        "observation": best,
        "rejected": rejected,
        "note": TIME_BASIS_NOTE[time_basis]
        + (f"依据：{best['at_basis']}" if best.get("at_basis") else "")
        + "观察不是被问出来的；它只记录一条相符或相悖的观察，不证明这条道为真。",
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
    who = authorship(dao.get("part_sources") or {})
    if field["verdict"] == "not_run":
        word, mark = base, "未检"
    elif field["verdict"] == "pass" and structure == "pass" and falsifiable == "pass":
        word, mark = OBSERVATION_KINDS[field["observation"]["kind"]][1], "检"
    else:
        word, mark = base, "未检"
    # 等级被最弱的那一件封顶：有一件是系统补的，这条道就不是「他说的」。
    # 模拟材料不走这条：它的词本来就说明「不是他说的」，换成「合写」只会把「模拟」藏掉。
    if base in {"自述", "自述（转述）", "传闻"}:
        if who == "合写":
            word = "合写"
        elif who == "系统的":
            word = "系统的"
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
        "authorship": who,
        "supplied": supplied_parts(dao.get("part_sources") or {}),
        "his": his_parts(dao.get("part_sources") or {}),
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
    base: Path | None = None,
) -> dict[str, Any]:
    episodes = {episode["id"]: episode for episode in data["episodes"]["episodes"]}
    window = data["episodes"]["window"]
    observations = data["observations"]["observations"]
    vocabulary = vocabulary or {"tensions": [], "moves": []}
    receipts: dict[str, dict[str, Any]] = {}
    # One reading for the whole library: a quote costs the same to verify once.
    sources = check_sources(data, base=base)
    for dao in data["daos"]["daos"]:
        receipts[dao["id"]] = {
            "sources": sources,
            "structure": check_structure(dao, episodes, window, vocabulary, at),
            "falsifiable": check_falsifiable(dao, episodes, at),
            "field": check_field(dao, episodes, observations, at),
        }
    return receipts


def independent_groups(data: dict[str, Any]) -> dict[str, Any]:
    """账本里手写了几个来源 id（去掉 attribution=unverified 的那些）。

    #1792: 这个函数**不是**在数人。它只对 `provenance[].person` 这个手写字符串去重——
    没有实名核验、没有按情境出处分开、没有查同源传递。原来那句 docstring
    「不同的人 × 不同的情境出处 × 无同源传递 × 各有案例」描述的是想要的口径，
    不是这份代码在算的东西，所以出口不能说「不同的人 N 个」：那会把一个手写 id
    读成一个人。

    `storage.independence()`（dojo/storage.py）是另一套口径：它按一张卡的来源组与
    写作会话算 provenance，与这里不同源，两个数不可互换、不可相加。

    #1831: 「案例」的口径取 OA（须有 `observed_action`）。只说「我也是」而拿不出自己
    在什么处境里怎么做的那条，不算一个来源：同意一个命题是廉价的，说出自己做了什么才不廉价
    （docs/proposal-knowledge-network.md:175）。真库 17 条事件 quote 与 observed_action
    都是 17/17，所以这条在真库上不改变任何数字；它咬的是只有引语的那种形状。
    """
    people: set[str] = set()
    classes: set[str] = set()
    episodes_by_id = {episode["id"]: episode for episode in data["episodes"]["episodes"]}
    for dao in data["daos"]["daos"]:
        for item in dao.get("provenance") or []:
            episode = episodes_by_id.get(item.get("episode")) or {}
            if episode.get("attribution") == "unverified":
                continue
            if not episode.get("observed_action"):
                # #1831 案例口径 = OA：没有已观察到的动作，就只有引语，不算一组。
                continue
            if not item.get("person"):
                # #1831: a row with no `person` cannot be counted as an id, and adding
                # None makes the caller's `sorted(people)` raise TypeError. The missing
                # key is reported by `missing_provenance_keys` and fails `--check`; this
                # function only has to stay readable while doing that.
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
        # The relayed clause only belongs on a library that has relayed rows; on a
        # library without them it would describe a class that is not there.
        relayed = (
            "relayed 那一类的措辞是转述或整理的，不是本人的原话（一条 id 下的字也不一定出自那个人）。"
            if "relayed" in classes
            else ""
        )
        line = (
            f"来源 id {len(people)} 个（账本里手写的不同来源 id；曝光账本 {len(exposures)} 行）。"
            "这不是人数：id 是人手填的，系统没核过它后面是不是不同的人。"
            "同一个人的两次自述只留一个 id，所以两个 id 可能是一个人。"
            "只有引语、说不出自己在什么处境里怎么做的来源不计入（案例须有已观察到的动作）。"
            + relayed
            + "曝光未知按「不独立」算：能确定的是这里没有第二个被核过的来源，不是共识。"
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
    # #1831: refuse before any of the page is built. The header below sorts
    # `groups['people']` and `independent_groups()` reads `item['person']`, so a
    # provenance row without that key used to surface as a `TypeError` from inside
    # sorted() -- after part of the page had been assembled. Same helper the checker
    # uses, so the two cannot drift apart.
    for dao in daos:
        require_provenance_keys(dao)
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
        add(
            "这一行是这张图最该被读的一句话：他给得出「做什么」和「从哪来」，给不出「什么处境」「哪两个好处在打架」「谁付什么」——那些是我补的，标着「系统补」。"
        )
        counts_by_author: dict[str, int] = {"他的": 0, "合写": 0, "系统的": 0}
        for dao in daos:
            counts_by_author[authorship(dao.get("part_sources") or {})] = counts_by_author.get(authorship(dao.get("part_sources") or {}), 0) + 1
        add("")
        add(
            f"**按作者分：他的 {counts_by_author.get('他的', 0)} 条、合写 {counts_by_author.get('合写', 0)} 条、"
            f"系统的 {counts_by_author.get('系统的', 0)} 条。**"
        )
        add("")
        add("**「合写」是一个状态，不是一句难听的话。**它说这条道的六件里有一些是系统补的：它只能被读成「他这样做的假设」，不能被读成「他的看法」。")
        add(
            "规则是硬的：只要有一件是系统补的，这条道的词就不会是「自述」「验过」或「量过」——这三个词都在说「这是他的话」，而它有一半不是。"
        )
        add("它的等级被最弱的那一件封顶；要升，只能等他一句新的确认或推翻，走「推断怎么变成他的」那条路。")
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
        # #1831: a row missing `person`/`episode`/`status`/`learned_from` used to reach
        # the f-string below and die as a `TypeError` inside sorted(). Name the entry and
        # the missing key instead.
        require_provenance_keys(dao)
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
            f"{item['person']} · {item['episode']} · {provenance_status_for(episodes.get(item['episode']) or {})} · {item['learned_from']}" for item in dao["provenance"]
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
            "**六件是谁写的：**"
            + "；".join(f"{PART_LABELS[name]} {sources.get(name, '（没写）')}" for name in PART_NAMES)
        )
        add("")
        who = authorship(dao.get("part_sources") or {})
        if who == "合写":
            add(
                f"**读这条能得出什么：**{"、".join(his_parts(dao.get("part_sources") or {}))}是他的，"
                f"{"、".join(supplied_parts(dao.get("part_sources") or {}))}是系统补的。所以这条只能读成「他这样做的假设」，不能读成他的看法；"
                "要用我补的那几件，得等他一句新的确认或推翻（见「推断怎么变成他的」）。"
            )
        elif who == "系统的":
            add("**读这条能得出什么：**六件全是系统补的，没有一句是他的；它只能读成一个待问的假设。")
        else:
            add(f"**读这条能得出什么：**六件都来自他说过的话（{"、".join(his_parts(dao.get("part_sources") or {}))}），没有一个字是我补的。")
        add("")
        for check in (data.get("record_checks") or {}).get("checks") or []:
            if check.get("dao") != dao["id"]:
                continue
            add(
                f"记录对这件**{PART_LABELS.get(check['part'], check['part'])}**说：**{check['status']}**——"
                f"{check['says']}（引文：「{check['against']['quote']}」，`{check['against']['path']}` {check['against']['ref']}）"
            )
            if check.get("handling"):
                add(f"处理：{check['handling']}")
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
            detail = field.get("time_basis_detail") or ""
            add(f"时间依据（{field['time_basis']}）：{field['note']}{detail}")
        grounding = needed.get(dao["id"])
        if grounding:
            add(f"要什么才能{'给这一格一条观察' if field['verdict'] == 'not_run' else '把这一格变强'}：{grounding['what']}（现在拿不到：{grounding['why_not']}；谁能补：{grounding['who']}）")
        add("")

    if not synthetic:
        promotions = (data.get("promotions") or {}).get("promotions") or []
        rs = check_library(data)[1]["record_status"]
        add("## 推断怎么变成他的")
        add("")
        add(
            "一条道里的「系统补」不是永久判决，但它只有一个出口：**他后来自己说了一句话，那句话逐字落进事件层，"
            "要么确认、要么推翻我补的那一件，并且带回执（谁跑的、对哪个版本、跑出什么）。**"
        )
        add(
            "确认的，那一件从「系统补」变成他的话，条目的作者跟着变；推翻的，必须写处理（改适用域或撤回）并把条目升版——"
            "反例不是降级，是改适用域。不是他说的不能晋，引文不在事件里的不能晋。"
        )
        add("")
        recorded = sum(rs.values())
        add(
            f"现在晋升 **{len(promotions)} 条**：他还没就任何一条取舍说过话。"
            f"现有记录对 {recorded} 件「系统补」的回答是：确认 {rs['确认']}、部分 {rs['部分']}、"
            f"收窄 {rs['收窄']}、推翻 {rs['推翻']}、未表态 {rs['未表态']}。"
        )
        add("")
        add("**确认不等于晋升**：确认只说明他写过那两头，不说明他把「两者不能同时拿满」这句话说出来过。取舍要他亲口说，才算他的。")
        add("")
        flags = data["map"].get("red_flags") or []
        if flags:
            add("## 红旗（记录不同意我的地方，和它说明的抽法问题）")
            add("")
            for flag in flags:
                add(f"**{flag['id']}**：{flag['what']}")
                add("")
                add(f"它红的地方：{flag['red_flag_about']}")
                add("")
                add(f"要留住的是：{flag['lesson']}")
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
    # session.json is the conversation's own record of which parts the person answered.
    # It is optional: a hand-written note library has none and keeps working. When present
    # it is bound to this note and to this extraction, and it may not claim a part the
    # note does not carry verbatim, in the order the questions were asked.
    session_path = root / "session.json"
    session_parts: dict[str, dict[str, dict[str, Any]]] = {}
    if session_path.exists():
        try:
            session_bytes = session_path.read_bytes()
            session_record = json.loads(session_bytes.decode("utf-8"))
            if not re.fullmatch(r"[0-9a-f]{64}", session_record.get("trace_sha256", "")):
                raise NoteError("作者冲突：session.json 缺少有效 trace_sha256")
            note_bytes = (root / "note.md").read_bytes()
            note_digest = hashlib.sha256(note_bytes).hexdigest()
            if session_record.get("note_sha256") != note_digest:
                raise NoteError("作者冲突：session.json 的 note_sha256 与当前 note.md 不匹配")
            for item in session_record.get("tensions") or []:
                pair = " ↔ ".join([x.strip() for x in item.get("pair", "").split("↔")]) if item.get("pair") else None
                for part, detail in (item.get("parts") or {}).items():
                    if part in {"situation", "tension", "move", "price", "off", "provenance"}:
                        session_parts.setdefault(pair or item.get("pair") or "*", {})[part] = {
                            "promoted": bool(detail.get("promoted")),
                            "answer": detail.get("answer"),
                        }
        except NoteError:
            raise
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, AttributeError) as exc:
            raise NoteError(f"session.json: 无法读取会话来源：{exc}") from None
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
        sources = dict(
            author.get("part_sources")
            or {
                "situation": "系统补",
                "tension": "系统补",
                "move": "他的原话",
                "price": "系统补",
                "off": "系统补",
                "provenance": "他的原话",
            }
        )
        if session_path.exists():
            promoted = session_parts.get(tension["pair"], {})
            verbatim_lines = []
            in_verbatim = False
            for raw_line in note["text"].splitlines():
                if raw_line.startswith("## "):
                    in_verbatim = raw_line.strip() == "## 逐字"
                    continue
                if in_verbatim:
                    match = NOTE_STAMP.match(raw_line.strip())
                    if match:
                        verbatim_lines.append(raw_line.strip()[match.end():].lstrip())
            labels = {"situation": "情境", "tension": "张力", "price": "代价", "off": "失效"}
            cursor = 0
            for part in ("situation", "tension", "price", "off"):
                evidence = promoted.get(part, {})
                is_promoted = evidence.get("promoted", False)
                if is_promoted:
                    answer = evidence.get("answer")
                    label = labels[part]
                    if not isinstance(answer, str) or not answer:
                        raise NoteError(f"作者冲突：{label} 的回答不在笔记逐字里")
                    match_index = next(
                        (index for index in range(cursor, len(verbatim_lines)) if verbatim_lines[index] == answer),
                        None,
                    )
                    if match_index is None:
                        if any(answer == line for line in verbatim_lines[:cursor]):
                            reason = "逐字行在该件应有顺序之前"
                        elif any(answer in line for line in verbatim_lines):
                            reason = "回答不是完整的逐字行"
                        else:
                            reason = "不在笔记逐字里"
                        raise NoteError(f"作者冲突：{label} 的回答{reason}")
                    cursor = match_index + 1
                elif sources.get(part) == "他的原话":
                    raise NoteError(
                        f"作者冲突：{tension['pair']} 的{labels[part]}在 extraction.json 声称他的原话，"
                        "但 session.json 未晋升"
                    )
                sources[part] = "他的原话" if is_promoted else "系统补"
            # 动作的会话证据是方向陈述；归属的来源本身就是这场 session。
            if sources.get("move") == "他的原话":
                move_direction = author.get("move", {}).get("direction")
                if not isinstance(move_direction, str) or move_direction not in tension["direction"]:
                    raise NoteError(f"作者冲突：{tension['pair']} 的动作方向不在笔记方向里")
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
"status": PROVENANCE_STATUS[attribution],
"learned_from": "亲历" if attribution == "person" else "未记录",
                        "exposure": "none-at-time",
                    }
                ],
                "part_sources": sources,
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
        "extraction_sha256": digest(extraction),
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
        "record_checks": load(root / "record_checks.json") if (root / "record_checks.json").exists() else {"checks": []},
        "promotions": load(root / "promotions.json") if (root / "promotions.json").exists() else {"promotions": []},
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



def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _pinned_name(commit: str) -> bool:
    """Is this a name that always means the same revision?

    Hex object ids do. Everything else -- `HEAD`, `main`, `v1.2`, `HEAD~3`, a remote
    branch -- is a name git resolves *now*, and the record does not say that. A
    citation is a promise to a reader years later; `HEAD` cannot keep it.

    Full 40-character hex and abbreviated hex (at least 4, git's own floor) are both
    accepted. Anything carrying `^`, `~`, `@{` or a path is a traversal, not a pin.
    """
    return bool(re.fullmatch(r"[0-9a-fA-F]{4,40}", commit.strip()))


def _names_the_object(root: Path, commit: str) -> bool:
    """Is `commit` an object id, and does it reach the object it spells?

    Two questions, because a hexadecimal spelling is not enough on its own:

      * is the string also a ref? `git tag 1af799f` creates a label that can later be
        moved with `-f`; nothing about the record would change;
      * does the id resolve to an object whose own id starts with it? That is a
        tautology for a genuine object id and the definition of an abbreviation, and
        it fails for anything git reaches by some other rule.
    """
    name = commit.strip()
    # First: is this string a ref at all? `git tag 1af799f` and `git branch 1af799f`
    # both make a *label* with a hexadecimal spelling. A label can be moved with
    # `-f`, so even when it points at the right object today it is not a promise.
    for namespace in ("refs/tags/", "refs/heads/", "refs/remotes/"):
        try:
            exists = subprocess.run(["git", "show-ref", "--verify", "--quiet", namespace + name],
                                    cwd=str(root), capture_output=True, timeout=120)
        except (OSError, subprocess.SubprocessError):
            return False
        if exists.returncode == 0:
            return False
    # Second: the object the name reaches must be the one the name denotes. This is
    # what catches a name that resolves through some other rule, and it is a
    # tautology for a genuine object id.
    try:
        done = subprocess.run(["git", "rev-parse", "--verify", name + "^{commit}"],
                              cwd=str(root), capture_output=True, timeout=120, text=True)
    except (OSError, subprocess.SubprocessError):
        return False
    if done.returncode != 0:
        return False
    return done.stdout.strip().lower().startswith(name.lower())


def _cited_ranges(ref: str) -> list[tuple[int, int]]:
    r"""The line ranges a `ref` actually points at, as intervals.

    Only the `第 N 行` and `第 N–M 行` forms count. The old scrape took every
    `第 (\d+)` in the string, so a section number could stand in for a wrong line:
    measured, `第 29 行，见第 2 节` passed because 3 held nothing and 2 did not
    matter -- and the shipped `person-dojo/ep-2026-10-23-detach` really does carry
    three numbers (`第 111 行；§10 第 2 条（第 272 行）`). It resolved correctly by
    luck, not by construction.

    A range stays a range. Expanding `第 1–5000 行` into five thousand integers buys
    nothing: the only question is whether the quote sits inside it, and that is one
    comparison. A wide range is a coarse record, not a stronger check, and making the
    gate allocate work in proportion to a plausible typo is the wrong shape.
    """
    ranges: list[tuple[int, int]] = []
    for match in re.finditer(r"第\s*(\d+)\s*(?:[–\-—~]\s*(\d+)\s*)?行", ref):
        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) else start
        ranges.append((min(start, end), max(start, end)))
    return ranges


def _cited_lines(ref: str) -> list[int]:
    """The numbers a ref names, for a message a reader has to read.

    Not used for matching: `_cited_ranges` decides that. This exists so an error can
    say `第 29 行` rather than quoting the whole ref.
    """
    return sorted({number for start, end in _cited_ranges(ref) for number in (start, end)})


def _revision_text(root: Path, commit: str, path: str) -> tuple[str | None, str]:
    """The file's text at `commit`, and when that cannot be had, why not.

    `None` used to be one value for three different facts -- git failed, the path
    is absent, the bytes are not UTF-8 -- and the caller treated all three as
    "read the working tree instead". That made a Latin-1 byte in an old revision
    the cheapest way to buy a `pass`: the sentence was then looked up in today's
    file, which is a different question from the one the citation asks. The reason
    is returned so the row can say which of the three happened.
    """
    try:
        done = subprocess.run(["git", "show", commit + ":" + path],
                              cwd=str(root), capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None, "取不到（git 调用失败）"
    if done.returncode != 0:
        return None, "取不到（git show 失败）"
    try:
        return done.stdout.decode("utf-8"), ""
    except UnicodeDecodeError:
        return None, "不是 UTF-8 文本：这个修订上的字节无法按文本核对"


def check_sources(data: dict[str, Any], *, base: Path | None = None, git: bool = True) -> dict[str, Any]:
    """Does every cited quote actually sit where the record says it does?

    Until this gate existed, `source` was decorative: `path`, `ref` and `commit`
    were printed beside a quote and never read. Measured on this tree before the
    gate: all 20 episodes named a commit that does not resolve here (the history
    was rebuilt, so `41d925a` and friends are gone), and one quote
    (`ep-2026-10-18-pref`) did not appear at its cited path at all -- it had joined
    two separate bullets into one sentence. A reader could not have found it.

    Two questions, kept apart because they fail differently:

      quote   the whitespace-squashed quote must occur in the file at
              `source.path`, and a line number written in `source.ref` must fall
              inside the span the quote occupies. Squashing first is deliberate:
              the fact at stake is the words, and this repo wraps prose. A cited
              number that lands outside the quote is a stale map and fails like a
              missing quote, because the reader who follows it lands on the wrong
              paragraph.
      commit  the named commit must resolve here. When it does not, that is
              recorded as `unresolved` and printed, never folded into a pass: a
              citation whose revision cannot be checked is an unchecked citation.
              A non-git directory gets the same word for the same reason, since
              frozen extracts (where CI and re-checks run) have no `.git`.

    `synthetic` episodes obey the quote rule too -- "we wrote it" does not make a
    mis-citation harmless, the file still has to say what the record claims -- but
    not the commit rule: that corpus is authored here, not received.
    """
    rows: list[dict[str, Any]] = []
    failures: list[str] = []
    root = Path(base) if base is not None else REPO_ROOT

    def has_history() -> bool:
        """Is there a repository here at all?

        The distinction the fallback turns on. No repository (a frozen extract, or
        `git=False`) means the working tree is the only text that exists -- that
        reading is honest as long as the verdict says `unchecked`. A repository that
        simply lacks the cited revision is a different situation: today's file is
        not that revision's file, so substituting it answers a question nobody asked.
        """
        if not git:
            return False
        try:
            done = subprocess.run(["git", "rev-parse", "--git-dir"],
                                  cwd=str(root), capture_output=True, timeout=120)
        except (OSError, subprocess.SubprocessError):
            return False
        return done.returncode == 0

    history = has_history()

    def resolves(commit: str, path: str = "") -> str:
        """`resolved`, `missing-path`, or `unresolved`.

        Reading the commit is not enough. A short SHA that exists proves an object
        is there; it says nothing about whether the file the quote came from existed
        at that revision. Measured: swapping a real citation's commit for another
        commit in this repository -- one that predates the file -- still answered
        `pass`, because only the object was checked. A quote cannot be verified
        against a revision that never contained it, and that is what holding the
        file at the cited commit is for.
        """
        if not git or not commit:
            return "unresolved"
        # A citation promises a *revision*, so the name must be one that cannot move.
        # `HEAD`, a branch and a lightweight tag all resolve today and can point
        # somewhere else tomorrow; a re-check found that a record citing `HEAD` kept
        # passing after the branch was reset, and flipped from `fail` to `pass` when
        # the sentence appeared in a newer commit. Nothing in the shipped libraries
        # does this (all twenty cite hex object names), so this is a guard against a
        # record going stale without anyone editing it.
        if not _pinned_name(commit):
            return "moving-name"
        try:
            there = subprocess.run(
                ["git", "cat-file", "-e", commit + "^{commit}"],
                cwd=str(root), capture_output=True, timeout=120,
            )
            if there.returncode != 0:
                return "unresolved"
            holding = subprocess.run(
                ["git", "cat-file", "-e", commit + ":" + path],
                cwd=str(root), capture_output=True, timeout=120,
            )
        except (OSError, subprocess.SubprocessError):
            return "unresolved"
        if holding.returncode != 0:
            return "missing-path"
        # Looking like a hash is not being one. A tag may be *named* `1af799f`, and
        # git prefers the name over the object spec: measured, `git tag 1af799f` made
        # that string resolve to a different commit entirely, so a record could point
        # at one revision while its text read another. The resolved object has to be
        # the one the name denotes, or the name is a label someone can re-point.
        if not _names_the_object(root, commit):
            return "moving-name"
        return "resolved"

    for episode in data["episodes"]["episodes"]:
        source = episode.get("source") or {}
        path = source.get("path") or ""
        ref = source.get("ref") or ""
        quote = episode.get("quote") or ""
        row: dict[str, Any] = {"id": episode.get("id"), "path": path,
                               "commit": source.get("commit"), "quote": "",
                               "lines": None, "commit_state": ""}
        rows.append(row)
        if not path or not ref:
            row["quote"] = "unrecorded"
            failures.append(f"{row['id']} 没有写清出处（path/ref）：引语无处可查")
            continue
        commit = source.get("commit") or ""
        # Whether the cited revision can answer at all, asked once and reused: the
        # quote check needs it to choose its source, and the commit check needs it
        # for the row. A synthetic episode owes no revision here.
        if episode.get("attribution") == "synthetic":
            row["commit_state"] = "not-required"
        elif not commit:
            row["commit_state"] = "unrecorded"
            # Said here rather than after the quote branch: a record with no commit
            # is unverifiable whether or not its quote happens to land, and an early
            # exit from the quote branch must not be able to swallow this.
            failures.append(f"{row['id']} 没写 commit：这份出处无法固定在某个版本上")
        else:
            row["commit_state"] = resolves(commit, path)
            if row["commit_state"] == "missing-path":
                failures.append(
                    f"{row['id']} 的提交 {commit} 里没有 {path}：引语不可能在这个修订上核对"
                )
            elif row["commit_state"] == "moving-name":
                failures.append(
                    f"{row['id']} 的 commit 写的是 {commit!r}：那是个会动的名字，今天的解析结果不能代表记录的版本；请写对象哈希"
                )
        # The quote is checked against the file *at the cited revision*, when there is
        # one to ask. A working-tree lookup answers a different question: two commits
        # can share a path while the sentence arrives in the second one, and a reader
        # who follows the citation to the first would not find it.
        #
        # Two re-checks by hand, both reproduced here, found the fallback lying:
        #   * the cited revision lacks the path, so `git show` answered nothing and
        #     the file was read from the working tree -- where the sentence happens
        #     to be. The quote's reading said `found` while its own row said
        #     `missing-path`: the verdict was `fail`, but the reader could not tell
        #     that `found` did not come from the cited revision;
        #   * the cited blob is not UTF-8 (any Latin-1 word is enough). `git show`
        #     succeeded and the bytes went unreadable, which fell into the same
        #     branch as "no blob at all" and became a `pass` -- the strongest of the
        #     three verdicts, on the weakest of the evidence.
        # Neither revision can be stood in for. The working tree answers a question
        # nobody asked, so it is used only when the question cannot be put to a
        # revision at all: no `.git`, `git` off, no commit written, or a synthetic
        # episode (that corpus is authored here).
        text = None
        if row["commit_state"] == "resolved":
            blob, why = _revision_text(root, commit, path)
            if blob is None:
                row["checked_at"] = "no-revision"
                row["quote"] = "unreadable-at-revision"
                row["revision_note"] = why
                failures.append(
                    f"{row['id']} 所指的 {commit} 里 {path} 取不出文本（{why}）：引语没有在工作树上代替核对"
                )
            else:
                row["checked_at"] = "commit"
                text = blob
        elif row["commit_state"] in {"missing-path", "moving-name"}:
            # The revision resolves and does not hold the file. The working tree may
            # well hold it -- that is the case that lied -- but a quote checked there
            # is not checked at the citation's revision, so the row says so and the
            # commit failure below carries the verdict.
            row["checked_at"] = "no-revision"
            row["quote"] = "unchecked-at-revision"
        elif row["commit_state"] == "unresolved" and history:
            # There is a repository and it does not have this commit. Safer to leave
            # the quote unread than to read today's file and call it checked.
            row["checked_at"] = "no-revision"
            row["quote"] = "unchecked-at-revision"
        else:
            # No repository to ask (frozen extract, `git=False`), so the working
            # tree is the only text that exists. That reading is honest as long as
            # the verdict says `unchecked`, which the unresolved list does.
            row["checked_at"] = "working-tree"
        if text is None and row["checked_at"] == "working-tree":
            try:
                text = (root / path).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                row["quote"] = "unreadable"
                failures.append(f"{row['id']} 的出处 {path} 读不出来：引语无法核对")
                continue
        if text is None:
            continue
        wanted = _squash(quote)
        lines = text.splitlines()
        found: list[tuple[int, int]] = []
        for start in range(len(lines)):
            window = ""
            for end in range(start, min(start + 15, len(lines))):
                window += _squash(lines[end])
                if wanted and wanted in window:
                    # Each occurrence is recorded at its own tightest span: a wide
                    # window would let a ref pointing at a neighbouring paragraph
                    # pass, and the reader who follows that number would land in the
                    # wrong place. Measured: `ep-2026-10-23-detach` cited line 104
                    # while the sentence begins on 111, and only the tight span
                    # shows that.
                    span = (start + 1, end + 1)
                    if span not in found:
                        found.append(span)
                    break
        # A window that starts earlier than the sentence also contains it, so the
        # raw list holds artefacts like (1,3) for a sentence on line 3. Two
        # occurrences means two *places*, so keep only spans that contain no other
        # span: what survives is the tight reading of each real occurrence.
        found = [span for span in found
                 if not any(other != span and span[0] <= other[0] and other[1] <= span[1]
                            for other in found)]
        found.sort()
        row["occurrences"] = [list(span) for span in found]
        cited_ranges = _cited_ranges(ref)
        cited = _cited_lines(ref) if cited_ranges else []
        if not wanted:
            row["lines"] = None
            row["quote"] = "empty"
            failures.append(f"{row['id']} 没有引语：出处无从核对")
        elif not found:
            row["lines"] = None
            row["quote"] = "absent"
            failures.append(f"{row['id']} 的引语在 {path} 里找不到：出处与引语不符")
        else:
            # A sentence can appear twice in one file, and the record may cite the
            # second one. Measured: a quote at lines 3 and 5 cited as line 5 was
            # called a stale map, because the gate compared the ref against the
            # first occurrence only and the precise number looked wrong. Which
            # occurrence the record means is what `ref` is for, so the ref selects.
            # Overlap, not enumeration: the ref and the quote are both spans, and the
            # only question is whether they meet. A hand-written `第 1–5000 行` is one
            # comparison, not five thousand.
            matching = [span for span in found
                        if any(span[0] <= end and start <= span[1]
                               for start, end in cited_ranges)]
            # No number written, so the tightest occurrence is the best reading.
            selected = min(found, key=lambda s: s[1] - s[0])
            if matching:
                selected = matching[0]
                row["quote"] = "found"
                # Two spans can only both hold the same number if the quote repeats
                # inside itself, so this is a note rather than a second verdict.
                if len(matching) > 1:
                    row["ref_ambiguous"] = True
            elif cited:
                row["quote"] = "stale-ref"
                failures.append(
                    f"{row['id']} 的 ref 指第 {'、'.join(str(n) for n in cited)} 行，"
                    f"引语却在 {path} 第 {'、'.join(f'{a}–{b}' for a, b in found)} 行：行号是旧地图"
                )
            else:
                row["quote"] = "found"
            # `lines` is where the sentence actually is, even when the ref is stale:
            # the reader needs the true location most in exactly that case.
            row["lines"] = list(selected)
            if len(found) > 1:
                if matching:
                    how = f"，按 ref 取第 {selected[0]}–{selected[1]} 行"
                elif cited:
                    how = "，ref 指的行不在任何一处里"
                else:
                    how = "，未写行号，取最紧的一处"
                row["occurrence_note"] = (
                    f"这句话在 {path} 里出现 {len(found)} 次（第 "
                    f"{'、'.join(f'{a}–{b}' for a, b in found)} 行）" + how
                )
    unresolved = [r["id"] for r in rows if r["commit_state"] == "unresolved"]
    moving = [r["id"] for r in rows if r["commit_state"] == "moving-name"]
    not_at_revision = [r["id"] for r in rows if r.get("checked_at") == "no-revision"]
    # Three words, because two would lie. `pass` means every quote landed where it
    # says *and* every one of them was read at the revision it names. `unchecked`
    # means at least one quote could not be put to its revision -- because the
    # revision is not in this repository, or because there is no repository here to
    # ask. Calling either `pass` would let a reader believe the versions were
    # verified. Note that `unchecked` is reachable two ways on purpose: a frozen
    # extract (no history at all) and a record whose SHAs went with a rewritten
    # history are both "nobody read that file at that revision", and the rows say
    # which one happened rather than the verdict swallowing the difference.
    if failures:
        verdict = "fail"
    elif unresolved or not_at_revision:
        verdict = "unchecked"
    else:
        verdict = "pass"
    return {
        "kind": "sources",
        "ran": {"by": f"{BENCH}/sources-v{SOURCES_VERSION}(bench-v{BENCH_VERSION})", "git": bool(git)},
        "verdict": verdict,
        "rows": rows,
        "failures": failures,
        "unresolved_commits": unresolved,
        "unchecked_at_revision": not_at_revision,
        "moving_names": [r["id"] for r in rows if r["commit_state"] == "moving-name"],
        "checked_at_commit": sum(1 for r in rows if r.get("checked_at") == "commit"),
        "line": (
            f"出处核对 {len(rows)} 条：引语 {sum(1 for r in rows if r['quote'] == 'found')} 条逐字落在它写的行内；"
            f"commit 在本仓可解析且含有该文件 {sum(1 for r in rows if r['commit_state'] == 'resolved')} 条，"
            f"按所指版本核对 {sum(1 for r in rows if r.get('checked_at') == 'commit')} 条，"
            f"不可解析 {len(unresolved)} 条，"
            f"commit 是会动的名字 {len(moving)} 条，"
            f"引语没能在这个版本上核对 {len(not_at_revision)} 条"
            + (
                "（这几条只有工作树的读法，或者那个修订上就没有这份文件；版本没被问到，不当作核过）。"
                if not_at_revision
                else "。"
            )
        ),
    }

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

    # 记录对「系统补」的回答：每一件的张力与代价都要有一条
    record_checks = (data.get("record_checks") or {}).get("checks") or []
    by_dao = {dao["id"]: dao for dao in data["daos"]["daos"]}
    covered = {(item.get("dao"), item.get("part")) for item in record_checks}
    episodes_for_source = {episode["id"]: episode for episode in data["episodes"]["episodes"]}
    has_real = any(
        (episodes_for_source.get(item.get("episode")) or {}).get("attribution") in {"person", "relayed"}
        for dao in data["daos"]["daos"]
        for item in dao.get("provenance") or []
    )
    for dao in (data["daos"]["daos"] if has_real else []):
        for part, label in (("tension", "张力"), ("price", "代价")):
            if (dao.get("part_sources") or {}).get(part) == "系统补" and (dao["id"], part) not in covered:
                failures.append(
                    f"{dao['id']} 的{label}是系统补的，但没有一条记录检查（record_checks）说他的其他话同不同意它"
                )
    record_status = {"确认": 0, "部分": 0, "收窄": 0, "推翻": 0, "未表态": 0}
    for item in record_checks:
        if item.get("dao") not in by_dao:
            failures.append(f"record check {item.get('id')} 指向不存在的道：{item.get('dao')}")
        if item.get("part") not in PART_NAMES:
            failures.append(f"record check {item.get('id')} 的 part 不在六件里：{item.get('part')}")
        if item.get("status") not in record_status:
            failures.append(f"record check {item.get('id')} 的状态不在五档里：{item.get('status')}")
        else:
            record_status[item["status"]] += 1
        if not (item.get("against") or {}).get("quote") or not item.get("says"):
            failures.append(f"record check {item.get('id')} 没写引文或没写它说的是什么")
        if item.get("status") in {"收窄", "推翻"}:
            if not item.get("handling"):
                failures.append(f"record check {item.get('id')} 是「{item.get('status')}」，但没写怎么处理")
            dao = by_dao.get(item.get("dao")) or {}
            revisions = dao.get("revisions") or []
            if dao.get("version", 1) <= 1 or not any(item.get("id") in (rev.get("because") or "") for rev in revisions):
                failures.append(
                    f"record check {item.get('id')} 是「{item.get('status')}」，但 {item.get('dao')} 没有升版并写明因为这条检查"
                )

    # 晋升：一条推断件变成他的，只有「他后来真说过一句」这一条路
    promotions = (data.get("promotions") or {}).get("promotions") or []
    episodes = {episode["id"]: episode for episode in data["episodes"]["episodes"]}
    promoted = set()
    for item in promotions:
        dao = by_dao.get(item.get("dao"))
        if dao is None:
            failures.append(f"promotion {item.get('id')} 指向不存在的道：{item.get('dao')}")
            continue
        part = item.get("part")
        if part not in PART_NAMES:
            failures.append(f"promotion {item.get('id')} 的 part 不在六件里：{part}")
            continue
        if item.get("kind") not in {"确认", "推翻"}:
            failures.append(f"promotion {item.get('id')} 的 kind 只能是确认或推翻：{item.get('kind')}")
        episode = episodes.get(item.get("episode")) or {}
        quote = item.get("quote") or ""
        if not episode or not quote or quote not in (episode.get("quote") or ""):
            failures.append(f"promotion {item.get('id')} 的引文不在事件 {item.get('episode')} 的原话里：晋不了")
        ran = item.get("ran") or {}
        if not (ran.get("by") and ran.get("at") and ran.get("on_version") is not None):
            failures.append(f"promotion {item.get('id')} 没有回执（谁跑的、对哪个版本、何时）")
        if item.get("kind") == "确认":
            if (dao.get("part_sources") or {}).get(part) == "系统补":
                failures.append(f"promotion {item.get('id')} 说他确认了 {part}，但那一件还标着「系统补」")
            elif item.get("as") != (dao.get("part_sources") or {}).get(part):
                failures.append(
                    f"promotion {item.get('id')} 说这一件变成 {item.get('as')!r}，但条目上写的是 "
                    f"{(dao.get('part_sources') or {}).get(part)!r}"
                )
            promoted.add((dao["id"], part))
        if item.get("kind") == "推翻":
            if not item.get("handling"):
                failures.append(f"promotion {item.get('id')} 推翻了一件，但没写处理（改适用域或撤回）")
            revisions = dao.get("revisions") or []
            if not any(item.get("id") in (rev.get("because") or "") for rev in revisions):
                failures.append(f"promotion {item.get('id')} 推翻了一件，但 {dao['id']} 没有升版并写明因为这条晋升")

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
        "record_status": record_status,
        "promotions": len(promotions),
        "authorship": {},
    }
    for dao in data["daos"]["daos"]:
        summary["authorship"][authorship(dao.get("part_sources") or {})] = summary["authorship"].get(authorship(dao.get("part_sources") or {}), 0) + 1
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
        # r101: the line above says 落地 过 and nothing about what it stood on.
        # The page carries the basis; a reader who only runs --check saw the
        # verdict alone. Same fact, one line, own indentation -- the row
        # format above is unchanged and still one line per dao.
        landed = receipt["field"]
        if landed["verdict"] != "not_run":
            print(
                "      落地依据（%s）：%s%s"
                % (landed["time_basis"], landed["note"], landed.get("time_basis_detail") or "")
            )
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
    # #1831: an entry whose provenance rows cannot be rendered is a failure here, named
    # before anything tries to print the page.
    for dao in data["daos"]["daos"]:
        failures += missing_provenance_keys(dao)
    library_failures, summary = check_library(data)
    failures += library_failures
    # `source` used to be printed and never read. The reading is printed here so a
    # reader of `--check` sees what was verified and what could not be, and its
    # failures join the library verdict: a record whose quote does not sit where it
    # says it does is not a record a later reader can follow.
    sources = next(iter(receipts.values()))["sources"]
    print("  " + sources["line"])
    failures += sources["failures"]
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
    rs = summary["record_status"]
    print(
        "  作者：" + "、".join(f"{name} {count}" for name, count in summary["authorship"].items())
        + f"；记录检查 {sum(rs.values())} 条（确认 {rs['确认']} / 部分 {rs['部分']} / 收窄 {rs['收窄']} / 推翻 {rs['推翻']} / 未表态 {rs['未表态']}）"
        + f"；晋升 {summary['promotions']} 条"
    )
    print(independent_groups(data)["line"])
    return failures



HISTORY_COVERAGE = {
    "mechanism": "append-only-v1",
    "prior_history": "unknown_or_missing",
}
HISTORY_NOTICE = "追加历史自本机制起保留；之前历史未知或缺失，仅封存可取得的旧回执快照。"


def input_digests(data: dict[str, Any], vocabulary: dict[str, Any]) -> dict[str, str]:
    """Hash all logical inputs, including the previously omitted validation inputs."""
    hashes = {name: digest(data.get(name, default)) for name, default in (
        ("episodes", {}), ("daos", {}), ("observations", {}), ("exposures", {}),
        ("map", {}), ("refusals", {"items": []}),
        ("record_checks", {"checks": []}), ("promotions", {"promotions": []}),
    )}
    hashes["vocabulary"] = digest(vocabulary)
    for name in ("note", "extraction"):
        if data.get(name + "_sha256"):
            hashes[name] = data[name + "_sha256"]
    return hashes


def history_bundle(data, receipts, at, inputs, vocabulary) -> dict[str, Any]:
    episodes = {episode["id"]: episode for episode in data["episodes"]["episodes"]}
    payload = {
        "layer": "checks", "bench": BENCH, "bench_version": BENCH_VERSION,
        "at": at, "inputs": inputs, "history_coverage": HISTORY_COVERAGE,
        "daos": {dao["id"]: {
            "id": dao["id"], "version": dao["version"], "digest": digest(dao),
            "receipts": receipts[dao["id"]], "status": status_of(dao, receipts[dao["id"]], episodes),
        } for dao in data["daos"]["daos"]},
    }
    page = render(data, receipts, at, inputs, vocabulary)
    page += "\n## 回执历史覆盖\n\n" + HISTORY_NOTICE + "\n"
    return {"schema_version": 1, "kind": "dao_receipt_run", "receipts": payload,
            "map_markdown": page, "history_coverage": HISTORY_COVERAGE}


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _stage_bytes(path: Path, content: bytes) -> Path:
    """Stage a complete file on the destination filesystem, never at its final name."""
    fd, name = tempfile.mkstemp(prefix=".dao-pending-", suffix=".tmp", dir=path.parent)
    staged = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if staged.read_bytes() != content:
            raise OSError(f"临时文件校验失败：{staged}")
        return staged
    except BaseException:
        staged.unlink(missing_ok=True)
        raise


def _publish_immutable(path: Path, content: bytes) -> None:
    try:
        existing = path.read_bytes()
    except FileNotFoundError:
        pass
    else:
        if existing != content:
            raise OSError(f"不可变历史冲突或损坏，拒绝覆盖：{path}")
        return
    staged = _stage_bytes(path, content)
    try:
        try:
            os.link(staged, path)
        except FileExistsError:
            if path.read_bytes() != content:
                raise OSError(f"不可变历史冲突或损坏，拒绝覆盖：{path}")
        except OSError as error:
            raise OSError(f"历史原子发布失败（要求同文件系统支持 os.link）：{path}：{error}") from error
    finally:
        staged.unlink(missing_ok=True)


def _atomic_projection(path: Path, content: bytes) -> None:
    if path.exists() and path.read_bytes() == content:
        return
    staged = _stage_bytes(path, content)
    try:
        os.replace(staged, path)
    finally:
        staged.unlink(missing_ok=True)



def _projection_has_history(history: Path, previous: Any) -> bool:
    if not isinstance(previous, dict):
        return False
    for path in history.glob("*.json"):
        if not re.fullmatch(r"[0-9a-f]{64}", path.stem):
            continue
        try:
            recorded = load(path)
        except (OSError, ValueError):
            continue
        if isinstance(recorded, dict) and recorded.get("kind") == "dao_receipt_run" and digest(recorded) == path.stem and recorded.get("receipts") == previous:
            return True
    return False


def commit_history(root: Path, bundle: dict[str, Any]) -> None:
    """Immutable bundle first, replaceable projections second; reruns repair a crash."""
    history = root / "history"
    history.mkdir(exist_ok=True)
    projection = root / "receipts.json"
    if projection.exists():
        original = projection.read_bytes()
        try:
            previous = json.loads(original)
        except (ValueError, UnicodeDecodeError):
            previous = None
        if not _projection_has_history(history, previous):
            old_hash = hashlib.sha256(original).hexdigest()
            legacy = {"schema_version": 1, "kind": "legacy_import",
                      "receipts_sha256": old_hash, "receipts_hex": original.hex(),
                      "history_coverage": HISTORY_COVERAGE}
            _publish_immutable(history / f"legacy-{old_hash}.json", _json_bytes(legacy))
    run_id = digest(bundle)
    _publish_immutable(history / f"{run_id}.json", _json_bytes(bundle))
    _atomic_projection(projection, _json_bytes(bundle["receipts"]))
    _atomic_projection(root / "道图.md", bundle["map_markdown"].encode("utf-8"))

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
        inputs = input_digests(data, vocabulary)
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
        other_inputs = input_digests(other, vocabulary)
        comparison = load(root.parent / "comparison.json")
        inputs["comparison"] = digest(comparison)
        other_inputs["comparison"] = digest(comparison)
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

    # Prepare every output before any commit. Libraries commit independently.
    targets = [(root, data, receipts, inputs)]
    if other is not None:
        targets.append((compare_dir, other, other_receipts, other_inputs))
    prepared = [(target, history_bundle(content, checks, at, hashes, vocabulary))
                for target, content, checks, hashes in targets]
    comparison_text = render_compare(comparison, result, data, other, vocabulary, at) if other is not None else None
    completed: list[str] = []
    try:
        for target, bundle in prepared:
            commit_history(target, bundle)
            completed.append(str(target))
            print(f"已提交历史并更新投影：{target}")
        if comparison_text is not None:
            _atomic_projection(root / "对比.md", comparison_text.encode("utf-8"))
            print(f"写入 {root / '对比.md'}")
    except OSError as error:
        print(f"写盘未完成：{error}")
        print(f"已完成投影的库：{completed or '无'}；各库历史独立提交，未完成库也可能已有完整历史。")
        print("未宣称全部成功；请原命令重跑恢复兼容投影。对比页仅在两库完成后更新。")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
