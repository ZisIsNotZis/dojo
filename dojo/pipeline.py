"""The end-of-session pipeline: ordered passes over what one session wrote.

A pass sees only cards it has not yet processed at their current version, so
re-running the pipeline for the same session writes no second event and changes
nothing. A pass proposes; it never merges, rewrites or deletes a person's
conclusion (design.md 6: 合并留人, 对抗性 pass 只能提议).

`classify` is opt-in and works on approved snapshots rather than current cards.
`distill` reads those proposals without making another request.
"""

from __future__ import annotations

import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Callable

from . import distillation
from .storage import (
    NEGATIONS, Store, content_key, is_unaccepted_draft, normalize_wording, wording_equivalent,
)

PASS_ORDER = ("classify", "locate", "challenge")

LOCATE_VARIANT_RATIO = 0.92


@dataclass
class PassResult:
    """What one pass did with one card. `proposals` are recorded, never applied."""

    proposals: list[dict[str, Any]] = field(default_factory=list)
    unavailable: str | None = None


def _cards_written_by(store: Store, session: str) -> list[dict[str, Any]]:
    cards = []
    for row in store.connection.execute("SELECT state_json FROM candidates ORDER BY id").fetchall():
        state = json.loads(row["state_json"])
        if session in state.get("sessions", []):
            cards.append(state)
    return cards


def _neighbours(store: Store, card: dict[str, Any]) -> list[dict[str, Any]]:
    """Other cards that share wording with this one, most similar first."""
    wanted_terms = normalize_wording(card["statement"])
    scored = []
    for row in store.connection.execute("SELECT state_json FROM candidates ORDER BY id").fetchall():
        other = json.loads(row["state_json"])
        if other["id"] == card["id"] or other.get("redirect_to"):
            continue
        if other["status"] == "withdrawn":
            continue
        other_terms = normalize_wording(other["statement"])
        shared = {
            term for term in _bigrams(wanted_terms) if term in other_terms
        }
        if not shared:
            continue
        scored.append((len(shared), other))
    return [other for _score, other in sorted(scored, key=lambda item: (-item[0], item[1]["id"]))]


def _bigrams(text: str) -> set[str]:
    return {text[index:index + 2] for index in range(len(text) - 1)}


def pass_locate(store: Store, card: dict[str, Any]) -> PassResult:
    """新 / 变体 / 重复, as proposals a person can act on."""
    proposals: list[dict[str, Any]] = []
    mine = content_key(card["statement"], card["kind"], card)
    for other in _neighbours(store, card):
        theirs = content_key(other["statement"], other["kind"], other)
        if theirs == mine:
            proposals.append({
                "type": "duplicate", "of": other["id"], "of_version": other["version"],
                "of_scope": other["scope"],
                "reason": "同一内容已有一张卡；不产生新版本",
            })
            continue
        if other["kind"] != card["kind"]:
            continue
        if wording_equivalent(card["statement"], other["statement"]):
            proposals.append({
                "type": "variant", "of": other["id"], "of_version": other["version"],
                "of_scope": other["scope"],
                "reason": "措辞等价但内容不同（条件、前提或未知不同）；建议 link，不 merge",
            })
    if not proposals:
        proposals.append({"type": "new", "of": None, "reason": "没有措辞等价的邻居；按新主张处理"})
    return PassResult(proposals=proposals)


def pass_challenge(store: Store, card: dict[str, Any]) -> PassResult:
    """Propose a challenge where a neighbour denies what this card asserts."""
    proposals: list[dict[str, Any]] = []
    for other in _neighbours(store, card):
        if other["kind"] != card["kind"]:
            continue
        same_terms = _bigrams(normalize_wording(card["statement"])) & _bigrams(normalize_wording(other["statement"]))
        if len(same_terms) < 3:
            continue
        if wording_equivalent(card["statement"], other["statement"]):
            continue
        if not _negation_flip(card["statement"], other["statement"]):
            continue
        proposals.append({
            "type": "challenge", "of": other["id"],
            "reason": "与邻居用同一批词但肯定/否定相反；建议提出挑战，不自动改写",
        })
    return PassResult(proposals=proposals)


def _negation_flip(first: str, second: str) -> bool:
    first_words = {word for word in NEGATIONS if word in normalize_wording(first)}
    second_words = {word for word in NEGATIONS if word in normalize_wording(second)}
    return bool(first_words) != bool(second_words)


PASSES: dict[str, Callable[[Store, dict[str, Any]], PassResult]] = {
    "locate": pass_locate,
    "challenge": pass_challenge,
}


def run_pipeline(store: Store, session: str, *, dry_run: bool = False, classify_trace: Path | None = None) -> dict[str, Any]:
    """Run the ordered passes over one session's cards, once per card revision.

    Returns what was done: per pass, the cards it processed, the cards it skipped
    as already processed, the proposals, and whether anything was written.
    """
    session = str(session or "").strip()
    if not session:
        raise ValueError("a session ID is required; the pipeline runs over one session's cards")
    cards = _cards_written_by(store, session)
    report: dict[str, Any] = {
        "session": session, "dry_run": dry_run, "cards": [card["id"] for card in cards],
        "passes": [], "events_written": 0,
    }
    if not cards and classify_trace is None:
        report["note"] = "this session wrote no cards; nothing to process"
        return report
    classified = distillation.classify(store, session, classify_trace, dry_run=dry_run)
    report["passes"].append(classified)
    report["events_written"] += len(classified["ran"])
    for pass_name in PASS_ORDER[1:]:
        pass_fn = PASSES[pass_name]
        run: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        unavailable: str | None = None
        for card in cards:
            mark = store.pipeline_mark(session, pass_name, card["id"])
            if mark is not None and mark >= card["version"]:
                skipped.append({"id": card["id"], "processed_version": mark})
                continue
            result = pass_fn(store, card)
            if result.unavailable is not None:
                unavailable = result.unavailable
                continue
            run.append({"id": card["id"], "version": card["version"], "proposals": result.proposals})
            if dry_run:
                continue
            store.record_pipeline_pass(card["id"], pass_name, session, card["version"], result.proposals)
            report["events_written"] += 1
        entry: dict[str, Any] = {"pass": pass_name, "ran": run, "skipped": skipped}
        if unavailable is not None:
            entry["unavailable"] = unavailable
        report["passes"].append(entry)
    return report


DISTILL_LABELS = {"new": "新", "variant": "变体", "duplicate": "重复"}


def _verdict(proposals: list[dict[str, Any]]) -> dict[str, Any]:
    """One verdict per card, by priority: 重复 beats 变体 beats 新."""
    for wanted in ("duplicate", "variant"):
        for proposal in proposals:
            if proposal["type"] == wanted:
                return proposal
    return proposals[0]


def _approved_verdict(store: Store, session: str, card: dict[str, Any]) -> dict[str, Any]:
    # locate excludes the card itself. A discussion can explicitly approve an exact
    # existing card, though, and neither an echo nor an attached source is a new claim.
    snapshots = store.connection.execute(
        "SELECT state_json FROM snapshots WHERE candidate_id=? AND version<=? ORDER BY version",
        (card["id"], card["version"]),
    ).fetchall()
    states = [json.loads(row["state_json"]) for row in snapshots]
    if states and session not in states[0].get("sessions", []):
        exact = next((state for state in states
                      if (state["version"] < card["version"] or session not in card.get("sessions", []))
                      and distillation.fields(state) == distillation.fields(card)), None)
        if exact:
            return {"type": "duplicate", "of": exact["id"], "of_version": exact["version"],
                    "of_scope": exact["scope"], "reason": "本场认可的内容已在这张旧卡中；并非本场新主张"}
    return _verdict(pass_locate(store, card).proposals)


def distill(store: Store, session: str) -> dict[str, Any]:
    """What one session's conclusions amount to, as a list a person reads.

    Approved entries read immutable discussion snapshots, not the current card.
    Locate/challenge compare those snapshots to the current library. Classification
    is a previously saved proposal; this list does not call a model.
    """
    session = str(session or "").strip()
    if not session:
        raise ValueError("a session ID is required; the distillation list is over one session's cards")
    approved, unbound = distillation.approvals(store, session)
    approved_ids = {card["id"] for card, _ in approved}
    entries = [(card, records, "approved") for card, records in approved]
    for card in _cards_written_by(store, session):
        if card["id"] not in approved_ids:
            status = "unaccepted_draft" if is_unaccepted_draft(card) else "unproven"
            entries.append((card, [], status))
    classified = distillation.saved_classifications(store, session)
    report: dict[str, Any] = {
        "session": session, "cards": [], "lines": [],
        "counts": {"new": 0, "variant": 0, "duplicate": 0},
        "unavailable": {},
    }
    if unbound:
        report["unbound_approval_events"] = unbound
        report["lines"].append("有认可事件无法绑定到原版快照；未以当前卡代替。事件：" + "、".join(map(str, unbound)))
    if not entries:
        report["note"] = "this session wrote no cards; nothing to distil"
        return report
    for card, records, status in entries:
        verdict = (_approved_verdict(store, session, card) if status == "approved"
                   else _verdict(pass_locate(store, card).proposals))
        challenges = pass_challenge(store, card).proposals
        classification = classified.get((card["id"], card["version"])) if status == "approved" else None
        if classification is None and status != "unaccepted_draft":
            report["unavailable"]["classify"] = "只读清单没有发请求；未判定不是认可、验证或内容分类。"
        kind = classification["kind"] if classification is not None else None
        kind_label = distillation.LABELS[kind] + "（模型提议）" if kind else "kind 未判定"
        draft = status == "unaccepted_draft"
        report["counts"][verdict["type"]] += 1
        report["cards"].append({
            "id": card["id"], "version": card["version"], **distillation.fields(card),
            "kind_status": "proposed" if kind else "abstained" if classification else "unavailable",
            "approval_status": status, "approval_events": [record["event"] for record in records],
            "classification": classification,
            "verdict": verdict["type"], "of": verdict["of"], "reason": verdict["reason"],
            "of_version": verdict.get("of_version"), "of_scope": verdict.get("of_scope"),
            "unaccepted_draft": draft, "challenges": challenges,
        })
        line = (
            f"[{DISTILL_LABELS[verdict['type']]}] {card['id']} v{card['version']} {kind_label}"
            + (" [未认可草稿]" if draft else " [本场认可快照]" if status == "approved" else "")
            + f"：{card['statement']}"
        )
        if verdict["of"]:
            line += f"（对 {verdict['of']}：{verdict['reason']}）"
        if status == "unproven":
            line += " [没有本场认可记录]"
        report["lines"].append(line)
        if status == "approved":
            if verdict.get("of_scope"):
                report["lines"].append(f"  对照卡 v{verdict['of_version']} 的范围：" + "；".join(verdict["of_scope"]))
            for field, label in (("scope", "范围"), ("premises", "前提"), ("alternatives", "替代解释"),
                                 ("contradictions", "相反情形"), ("unknowns", "认可时留下的未知")):
                if card[field]:
                    report["lines"].append(f"  {label}：" + "；".join(card[field]))
            if classification is None:
                report["lines"].append("  已认可此版本；尚无带原话的分类提议。")
            else:
                report["lines"].append(f"  为什么这样分：{classification['reason']}")
                if classification["missing"]:
                    report["lines"].append(f"  尚缺依据：{classification['missing']}")
                for quote in classification["quotes"]:
                    report["lines"].append(f"  本场原话 · 第 {quote['seq']} 轮：「{quote['quote']}」")
                report["lines"].append(f"  轨迹：{classification['trace']}（第 {classification['approval_seq']} 轮认可）")
        for proposal in challenges:
            report["lines"].append(f"  挑战提议 → {proposal['of']}：{proposal['reason']}")
    return report
