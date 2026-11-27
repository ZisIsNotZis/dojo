#!/usr/bin/env python3
"""Where the judgement landed: one defect fixed, two corrections accepted.

The judgement says a repeat is decided by the *request*, not by something adjacent
to it. Three places are read here, all offline, all on private libraries built in a
temp directory. None reads the repository's own database.

  attach     `dojo attach-source` gated on the *session*: a second source carrying a
             fresh independence group was dropped whenever the session had spoken
             before -- rc 0, no event, no source. Same shape as the defect the
             judgement was written for.
  replay     My first repair recorded an exact source replay as
             `attach_source.repeat`. Two published tests refused it: they pin that
             attaching the same provenance twice is a silent no-op, unchanged state
             *and* unchanged events. The contract wins; the record says so.
  distill    `pass_locate` judges "duplicate" with `content_key`, which leaves
             `sources` out on purpose. The judgement's failure condition says that is
             right: a card has no state to compare there, so effect decides.

Run: python3 -B docs/evidence/2026-11-27-repeat-safety/check_landing.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

STATEMENT = "降低无关摩擦能让重复行为更容易持续"
KIND = "abstract_idea"


def source(group, claim):
    return {"id": "src-" + group, "type": "abstract_reasoning", "claim": claim,
            "independence_group": group, "verification": "not_evidence"}


def fresh_store():
    """A private library. `DOJO_DB` is never consulted: a probe must not write to one."""
    from dojo.storage import Store

    return Store(str(Path(tempfile.mkdtemp(prefix="dojo-landing-")) / "landing.sqlite3"))


def measure() -> dict:
    from dojo.pipeline import distill

    # ---- attach: a second group under a session that already contributed.
    store = fresh_store()
    store.add(STATEMENT, KIND, candidate_id="card", session="s-one",
              sources=[source("group-a", "第一次推演")])
    after = store.attach_source("card", source("group-b", "第二次推演"), "s-one")
    events = [row["event"] for row in store.history("card")["events"]]
    kept = [item["id"] for item in after.get("sources", [])]

    # ---- replay: the same provenance again, and the same named group again.
    state_before = store.show("card")["candidate"]
    events_before = len(store.history("card")["events"])
    store.attach_source("card", source("group-b", "第二次推演"), "s-one")
    exact_replay = store.show("card")["candidate"]
    exact_replay_events = len(store.history("card")["events"])

    other_group_same_session = fresh_store()
    other_group_same_session.add(STATEMENT, KIND, candidate_id="c2", session="s-two",
                                sources=[source("group-a", "第一次推演")])
    other_group_same_session.attach_source("c2", source("group-a", "不同说法"), "s-two")
    same_group_kept = len(other_group_same_session.show("c2")["candidate"]["sources"])

    # ---- distill: the same sentence under two sources.
    distilled = fresh_store()
    distilled.add(STATEMENT, KIND, candidate_id="first", session="s-three",
                  sources=[source("group-a", "第一次推演")])
    distilled.attach_source("first", source("group-b", "第二次推演"), "s-three")
    report = distill(distilled, "s-three")
    verdicts = {card["id"]: card["verdict"] for card in report["cards"]}
    cards = len(distilled.list_candidates())

    return {
        "attach_second_group_is_recorded": len(kept) == 2,
        "attach_sources_after_second_group": kept,
        "attach_events": events,
        "exact_replay_leaves_state_unchanged": state_before == exact_replay,
        "exact_replay_writes_no_event": events_before == exact_replay_events,
        "same_group_under_one_session_is_one_provenance": same_group_kept == 1,
        "distill_verdicts": verdicts,
        "distill_source_change_is_not_a_second_card": cards == 1,
        "result": (
            "第二个来源（新 group、同一会话）：事件 {events}，卡上来源 {kept}。"
            "同一个来源再来一次：状态不变 {state}，事件也不加 {no_event}——"
            "这是已发布的契约（两条测试钉住），我第一版改成写 .repeat 被它们挡了回来。"
            "同一 group 的第二个来源仍是一条 provenance（来源数 {same}）。"
            "distill：同一句话配两个来源仍是 {cards} 张卡，判定 {verdicts}。"
        ).format(events=events, kept=kept,
                 state=state_before == exact_replay,
                 no_event=events_before == exact_replay_events,
                 same=same_group_kept, cards=cards, verdicts=verdicts),
    }


if __name__ == "__main__":
    # A probe must not inherit a caller's library.
    for key in [key for key in os.environ if key.startswith("DOJO_")]:
        del os.environ[key]
    print(json.dumps(measure(), ensure_ascii=False, indent=2))
