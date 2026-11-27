#!/usr/bin/env python3
"""Re-run this slice's claims. Exits non-zero if any of them is false.

    python3 docs/evidence/2026-11-27-lesson-loop/verify.py

Offline, standard library only, no model calls, throwaway database.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from dojo.storage import Store  # noqa: E402

OLD = "持续检查交给系统自己跑，人只在想推翻的时候回来。"
NEW = "持续检查交给系统自己跑，但只在检查结果会打断他时才叫醒他。"
DOUBT = "第三次在同一团队反而更糟：检查结果他根本没看。"
WHY = "原来那句没写清楚什么时候该叫醒他，所以第三次更糟。"
QUERY = "持续检查 系统 自己 跑 回来 推翻"

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print("OK     " + label)
    else:
        print("FAIL   " + label + (("  —— " + detail) if detail else ""))
        failures.append(label)


def walk(store: Store, root: Path) -> str:
    """The whole story at the real storage surface: arrived, doubted, narrowed, accepted."""
    added = store.add(
        OLD, "abstract_idea",
        scope=["他抽身之后"], premises=["系统能自己跑检查"],
        alternatives=["把检查留给人"], contradictions=["检查必须发生在世界里时"],
        unknowns=["他会不会来看回执"],
        sources=[{"id": "s1", "type": "claimed_firsthand", "verification": "unverified",
                  "independence_group": "gA", "claim": "他这样做过两次",
                  "scope_note": "两次都在同一团队"}],
        session="sess-A",
    )
    cid = added["id"]
    store.record_acceptance(cid, "sess-A", path="discuss_conclusion")
    store.confirm(cid, "他在会话里认可了这句", session="sess-A")
    store.challenge(cid, DOUBT, source={
        "id": "s2", "type": "claimed_firsthand", "verification": "unverified",
        "independence_group": "gB", "claim": "第三次照做反而更糟",
        "scope_note": "同一团队的第三次"})
    store.revise(cid, NEW, WHY, scope=["他抽身之后"], premises=["系统能自己跑检查"],
                 alternatives=["把检查留给人"], contradictions=[DOUBT],
                 unknowns=["打断多少次会变成骚扰"], session="sess-B")
    store.record_acceptance(cid, "sess-C", path="discuss_conclusion")
    store.confirm(cid, "他在新一场里认可了改写后的这句", session="sess-C")
    return cid


def main() -> int:
    temp = tempfile.TemporaryDirectory()
    root = Path(temp.name)
    store = Store(root / "dojo.sqlite3")
    try:
        cid = walk(store, root)

        # L1: the later reader is handed the reason.
        rows = store.retrieve(QUERY)["results"]
        basis = rows[0].get("revision_basis", {}) if rows else {}
        check("L1 检索到的这一行带着他改主意的理由", basis.get("reason") == WHY,
              repr(basis.get("reason")))
        check("L1b 也带着被改掉的那句", basis.get("left_wording") == OLD,
              repr(basis.get("left_wording")))

        # L2: the same fact on all three reader exits.
        cast = store.broadcast(QUERY)["results"]
        check("L2a 跨会话的那条出口也带着它",
              bool(cast) and cast[0].get("revision_basis", {}).get("reason") == WHY)
        shown = store.show(cid)
        check("L2b `show` 也带着它", shown.get("revision_basis", {}).get("reason") == WHY)
        check("L2c `show` 的 candidate 本体没有被改写",
              "revision_basis" not in shown["candidate"])

        # L3: the frozen prompt.
        exported = store.export_prompt("c", [cid], 8000, root / "exports")
        prompt = Path(exported["path"]).read_text(encoding="utf-8")
        check("L3a 冻结的提示词里写着理由", WHY in prompt)
        check("L3b 也写着被改掉的那句，并说明它已被取代",
              OLD in prompt and "这句是他后来改掉的，不是现在的说法。" in prompt)
        check("L3c 现在这句仍然在", NEW in prompt)

        # L4: it speaks only for the wording the card holds now.
        store.revise(cid, "持续检查交给系统自己跑，但每天至多叫醒他一次。",
                     "第二次的理由：天天打断他受不了。", session="sess-D")
        second = store.revision_basis(cid).get("revision_basis", {})
        check("L4 再改一次之后，附在当前措辞上的是新的那个理由",
              second.get("reason") == "第二次的理由：天天打断他受不了。",
              repr(second.get("reason")))
        check("L4b 上一次的理由没有被删掉，仍在账本里",
              WHY in [event["details"].get("reason") for event in store.history(cid)["events"]
                      if event["event"] == "revise"])
    finally:
        store.close()
        temp.cleanup()

    # L5: a card he never revised keeps exactly the bytes it had.
    temp = tempfile.TemporaryDirectory()
    root = Path(temp.name)
    store = Store(root / "dojo.sqlite3")
    try:
        added = store.add(
            "没有改过主意的这句话", "abstract_idea", scope=["a"], premises=["b"],
            alternatives=["c"], contradictions=["d"], unknowns=["e"],
            sources=[{"id": "t1", "type": "claimed_firsthand", "verification": "unverified",
                      "independence_group": "gT", "claim": "他只说过一次"}],
            session="sess-T",
        )
        store.record_acceptance(added["id"], "sess-T", path="discuss_conclusion")
        store.confirm(added["id"], "认可", session="sess-T")
        check("L5a 没改过主意的卡没有这个键", "revision_basis" not in store.show(added["id"]))
        row = store.retrieve("没有改过主意的这句话")["results"][0]
        check("L5b 检索行里也没有", "revision_basis" not in row)
        prompt = Path(store.export_prompt(
            "c", [added["id"]], 8000, root / "exports")["path"]).read_text(encoding="utf-8")
        check("L5c 导出里也没有这两行", "revision_reason" not in prompt
              and "revision_left_wording" not in prompt)
    finally:
        store.close()
        temp.cleanup()

    # L6: a replay states no new reason.
    temp = tempfile.TemporaryDirectory()
    root = Path(temp.name)
    store = Store(root / "dojo.sqlite3")
    try:
        added = store.add(
            "重放用的话", "abstract_idea", scope=["a"], premises=["b"], alternatives=["c"],
            contradictions=["d"], unknowns=["e"],
            sources=[{"id": "r1", "type": "claimed_firsthand", "verification": "unverified",
                      "independence_group": "gR", "claim": "x"}],
            session="sess-R",
        )
        cid = added["id"]
        store.record_acceptance(cid, "sess-R", path="discuss_conclusion")
        store.confirm(cid, "认可", session="sess-R")
        store.revise(cid, "重放后的那一句", "同一个理由", session="sess-R2")
        before = store.revision_basis(cid)
        store.revise(cid, "重放后的那一句", "同一个理由", session="sess-R2")
        events = [event["event"] for event in store.history(cid)["events"]]
        check("L6a 同一请求再来一次被记成重放", "revise.repeat" in events, repr(events))
        check("L6b 理由没有因为重放而变化", before == store.revision_basis(cid))
    finally:
        store.close()
        temp.cleanup()

    print()
    if failures:
        print("%d 项不成立。" % len(failures))
        return 1
    print("全部成立。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
