"""Recover a displayed proposal without resuming the model conversation."""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys

from . import commands, distillation
from .discuss import _print_review, _save_conclusion, validate_conclusion
from .live import LiveError
from .storage import DojoError, Store

_SESSION = re.compile(r"discuss-[0-9a-f]{32}")


def _proposals(rounds):
    """Use full snapshots, not the assistant reply or a statement-only match."""
    result = {}
    for row in rounds:
        original, candidate = row.get("user"), row.get("candidate")
        if (not isinstance(original, str) or not original.strip() or original.strip() == "/认可"
                or not isinstance(row.get("answer"), str) or row.get("decision") != "none"
                or row.get("stance") not in ("neutral", "reject")
                or row.get("reason") not in ("proposed_new_pending", "candidate_changed", "awaiting_accept")
                or not isinstance(candidate, dict) or row.get("pending_snapshot") != candidate
                or row.get("pending_after") != candidate.get("statement")):
            continue
        try:
            checked = _validate(candidate)
        except (LiveError, RecursionError, UnicodeError):
            continue
        if checked == candidate:
            result[row["seq"]] = (original, checked)
    return result


def _validate(candidate):
    return validate_conclusion({"answer": "review", "candidate": candidate, "user_stance": "neutral"})


def review_hint(path, session, database, *, trace_data=None):
    if path.name != session + ".jsonl" or not _SESSION.fullmatch(session):
        return None
    rounds, digest = trace_data if trace_data is not None else distillation.read_trace(path, session)
    if digest and _proposals(rounds):
        return commands.dojo("review-drafts", commands.absolute(path), "--trace-sha256", digest,
                             db=commands.library_argument(database))
    return None


def _known(store, session):
    approved, _ = distillation.approvals(store, session)
    return [(distillation.fields(card), f"{card['id']} v{card['version']}") for card, _ in approved]


def run(path: Path, database: Path, expected_sha256: str, *, read=input, output=None):
    output = output if output is not None else sys.stdout

    def tell(line):
        print(line, file=output, flush=True)

    def ask(prompt):
        try:
            return read(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            return "/退出"

    session = path.stem
    if path.name != session + ".jsonl" or not _SESSION.fullmatch(session):
        raise DojoError("请使用结束回执或提炼清单里的本场轨迹。")
    rounds, digest = distillation.read_trace(path, session)
    if digest is None or digest != expected_sha256:
        raise DojoError("轨迹不完整、无法读取或与入口指纹不同；没有保存任何内容。请重新核对本场清单。")
    proposals = _proposals(rounds)
    with closing(Store(database, readonly=True)) as store:
        known = _known(store, session)
    if not proposals:
        tell("这份轨迹没有可复核的完整拟写；没有写入。")
        return 0

    opening = next((row["user"] for row in rounds
                    if isinstance(row.get("user"), str) and row["user"].strip() not in {"", "/认可"}), None)
    tell("【会后草稿复核】这些是曾经展示的拟写，不是共识。核对再留；不会重开讨论或请求模型。")
    while True:
        available = {}
        for turn, (original, proposal) in proposals.items():
            saved = next((ref for fields, ref in known if fields == proposal), None)
            if saved:
                tell(f"  {turn} · 原拟写已有本场认可：{saved}")
            else:
                available[str(turn)] = (turn, original, proposal)
                tell(f"  {turn} · 当时的拟写：" + json.dumps(proposal["statement"], ensure_ascii=False))
        if not available:
            tell("没有其他可选拟写。")
            return 0
        selected = ask("输入轮次编号核对，或 /退出：")
        if selected == "/退出":
            tell("已退出；未留下的拟写和库里的记录不变。")
            return 0
        if selected not in available:
            tell("请选择列出的可选轮次，或 /退出。")
            continue
        turn, original, proposal = available[selected]
        working = proposal
        tell(f"【第 {turn} 轮拟写】类型沿用当时的拟写；补注只增加范围，不会改写观察或重新判类。")
        while True:
            _print_review(output, working, original, opening, local_draft=True)
            tell("可输入「/补边界 你的补注」；「/留下」将认可屏上这版；「/略过」丢弃本次补注、回到列表。")
            action = ask("选择（/退出 可直接离开）：")
            if action == "/退出":
                tell("已退出；当前拟写和补注未写入。")
                return 0
            if action == "/略过":
                tell(f"已略过第 {turn} 轮；未保存本次补注，也没有改动既有草稿。")
                break
            if action.startswith("/补边界 "):
                note = action.removeprefix("/补边界 ").strip()
                revised = {**working, "scope": [*working["scope"], note]}
                try:
                    checked = _validate(revised)
                except (LiveError, UnicodeError):
                    checked = None
                if checked != revised:
                    tell("补注为空、重复、过长或超出条目上限；草稿未改动。")
                else:
                    working = checked
                continue
            if action != "/留下":
                tell("没有写入。请输入屏上的动作。")
                continue

            # Confirm the reviewed bytes are still the ones we can cite. Do not create
            # a database during inspection, skip, or refusal of a stale trace.
            _, current = distillation.read_trace(path, session)
            if current != digest:
                raise DojoError("复核期间轨迹已变；未保存。请重新打开本场清单核对。")
            if not database.is_file():
                raise DojoError("原库已找不到；没有另建库，也没有保存。")
            agreed_at = datetime.now(timezone.utc).isoformat()
            # Earlier proposals are not library revisions. Only exact existing content
            # can be reused; do not guess a card to overwrite from a later end receipt.
            with closing(Store(database)) as store:
                card, version, error = _save_conclusion(
                    store, working, session, candidate_id=None, trace_enabled=True,
                    agreed_at=agreed_at, draft_review={"turn": turn, "trace_sha256": digest},
                )
            if error is not None:
                tell(f"未写入认可：{error}")
                continue
            tell(f"已留下并认可第 {turn} 轮的屏上版本：{card} v{version}。认可表述，不等于独立验证。")
            tell("看库里的记录：" + commands.dojo("show", card, db=commands.library_argument(database)))
            tell("看认可的准确版本：" + commands.dojo("distill", "--session", session, "--text", "--trace",
                                                  commands.absolute(path), db=commands.library_argument(database)))
            return 0
