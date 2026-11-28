#!/usr/bin/env python3
"""Regression: a same-second A→B→A reapproval points v3 at its actual turn.

Run next to verify_distill_cli.py (the offline shared fixture):
  python3 -B verify_distill_reapproval.py WORKTREE NEW_EVIDENCE_DIR
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile

import verify_distill_cli as fixture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("worktree", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    repo, out = args.worktree.resolve(), args.output.resolve()
    if repo == out or repo in out.parents:
        parser.error("write artifacts outside the checked-out worktree")
    out.mkdir(parents=True)
    fixture.CARDS[2] = fixture.CARDS[0]
    fixture.TURNS[2] = "我刚才又看了一个普通收桌的接班场景；仍然把它说回第一版的那个试法，不推广到两组。"
    fixture.ANSWERS[2] = "回到第一版的限定试法：只限常规收桌，不外推到两组。"
    # The CLI still runs normally. A–B–A is usually approved within the same UTC
    # second over loopback; a bounded retry avoids starting over a second boundary.
    for attempt in range(1, 6):
        artifact = out / f"attempt-{attempt}"
        artifact.mkdir()
        with tempfile.TemporaryDirectory(prefix="dojo-reapproval-") as tmp:
            run = fixture.Run(repo, artifact, Path(tmp))
            run.seed()
            trace, session, ident, _ = run.discussion()
            approvals = json.loads((artifact / "approval-events.json").read_text(encoding="utf-8"))
            if approvals[0]["details"]["agreed_at"] != approvals[2]["details"]["agreed_at"]:
                continue
            rows = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
            actual_source = next(r for r in rows if r.get("user") == fixture.TURNS[2])
            approving_rounds = [r for r in rows if r.get("user") == "/认可" and r.get("decision") == "written"]

            def reply(request, index):
                packet = json.loads(request["messages"][-1]["content"])
                fixture.dump(artifact / "captured-packet.json", packet)
                return {"classifications": [{"id": c["id"], "version": c["version"], "kind": None,
                            "reason": "未作实质模型判断", "missing": "这是协议检查", "quotes": []}
                            for c in packet["cards"]]}

            with fixture.loopback(reply) as (url, calls, errors):
                report = run.cli("pipeline", "--session", session, "--classify", "--trace", trace, endpoint=url)
            fixture.same((len(calls), errors), (1, []), "one bounded classifier batch")
            fixture.dump(artifact / "pipeline.json", report)
            packet = json.loads((artifact / "captured-packet.json").read_text(encoding="utf-8"))
            actual = [(c["id"], c["version"], c["approval_seq"]) for c in packet["cards"]]
            fixture.same(actual, [(ident, i, row["seq"]) for i, row in enumerate(approving_rounds, 1)],
                         "same ID/time/wording must not bind v3 to v1's approval")
            fixture.same([r["approval"]["version"] for r in approving_rounds], [1, 2, 3], "trace received exact versions")
            fixture.same(packet["cards"][2]["turns"][-1], {"seq": actual_source["seq"], "text": fixture.TURNS[2]},
                         "v3 includes the user's latest reason to return to A")
            print(f"PASS same-second A→B→A: {ident} {[(v, seq) for _, v, seq in actual]}; {artifact}")
            return
    raise AssertionError("did not exercise a same-second approval after five loopback attempts")


if __name__ == "__main__":
    main()
