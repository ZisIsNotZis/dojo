"""The end-of-session pipeline: ordered passes over what one session wrote.

A pass sees only cards it has not yet processed at their current version, so
re-running the pipeline for the same session writes no second event and changes
nothing. A pass proposes; it never merges, rewrites or deletes a person's
conclusion (design.md 6: 合并留人, 对抗性 pass 只能提议).

`classify` needs a model judgement about what kind of claim a card is. It is
declared here and reports itself unavailable rather than guessing, because a
guessed `kind` is worse than a missing one: the sampling that M2 acceptance ①
asks for cannot sample an invention.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from .storage import (
    NEGATIONS, Store, content_key, normalize_wording, wording_equivalent,
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


def pass_classify(store: Store, card: dict[str, Any]) -> PassResult:
    return PassResult(unavailable=(
        "classify 需要对这条主张做一次模型判定（kind 归属）；本轮没有可用端点，"
        "所以不猜也不写。它属于 M2 的 m2b，抽检对象是它的输出，不是它的名义。"
    ))


def pass_locate(store: Store, card: dict[str, Any]) -> PassResult:
    """新 / 变体 / 重复, as proposals a person can act on."""
    proposals: list[dict[str, Any]] = []
    mine = content_key(card["statement"], card["kind"], card)
    for other in _neighbours(store, card):
        theirs = content_key(other["statement"], other["kind"], other)
        if theirs == mine:
            proposals.append({
                "type": "duplicate", "of": other["id"],
                "reason": "同一内容已有一张卡；不产生新版本",
            })
            continue
        if other["kind"] != card["kind"]:
            continue
        if wording_equivalent(card["statement"], other["statement"]):
            proposals.append({
                "type": "variant", "of": other["id"],
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
    "classify": pass_classify,
    "locate": pass_locate,
    "challenge": pass_challenge,
}


def run_pipeline(store: Store, session: str, *, dry_run: bool = False) -> dict[str, Any]:
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
    if not cards:
        report["note"] = "this session wrote no cards; nothing to process"
        return report
    for pass_name in PASS_ORDER:
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
