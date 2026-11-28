#!/usr/bin/env python3
"""Offline real-CLI reader replay. Usage: replay.py WORKTREE NEW_OUTPUT_DIR."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "walk", HERE.parent / "2026-11-28-m2-distill/verify_distill_cli.py")
walk = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(walk)


def main(repo, out, *, baseline=False):
    out.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory() as tmp:
        run = walk.Run(repo, out, Path(tmp))
        old = run.seed()
        trace, session, ident, seqs = run.discussion()
        args = ("distill", "--session", session)
        approved = run.cli(*args)
        walk.same([c.get("classification") for c in approved["cards"]], [None] * 4,
                  "approval and opening the list do not classify")

        def classify(request, _):
            packet = json.loads(request["messages"][-1]["content"])
            walk.same(packet["session"], session, "bound classifier session")
            walk.same([(c["id"], c["version"]) for c in packet["cards"]],
                      [(ident, 1), (ident, 2), (ident, 3)], "draft never sent")
            walk.dump(out / "packet.json", packet)
            results = []
            for c in packet["cards"]:
                i = c["version"] - 1
                results.append({"id": ident, "version": i + 1,
                    "kind": "experience_claim" if i == 0 else c["kind"],
                    "reason": "发言者以交班人身份描述了一张桌面卡的实际用法，可当作一次小范围实践经验。" if i == 0 else walk.REASONS[i],
                    "missing": "还没有两组同时收桌的观察。" if i == 0 else walk.MISSING[i],
                    "quotes": [{"seq": seqs[walk.TURNS[i]], "quote":
                        "在桌面放一张卡，只写接班人下一步该摆什么" if i == 0 else walk.QUOTES[i]}]})
            return {"classifications": results}

        with walk.loopback(classify) as (endpoint, calls, errors):
            walk.dump(out / "pipeline.json", run.cli("pipeline", "--session", session, "--classify",
                                                     "--trace", trace, endpoint=endpoint))
            walk.same(errors, [], "fixture accepted request")
            walk.same(len(calls), 1, "one explicit classification request")
            before = hashlib.sha256(run.db.read_bytes()).digest()
            opened = run.cli(*args, endpoint=endpoint)
            text = run.invoke(*args, "--text", endpoint=endpoint)
            walk.same(text.returncode, 0, text.stderr)
            walk.same(run.cli(*args, endpoint=endpoint), opened, "repeat opens identically")
            walk.same(len(calls), 1, "opens do not send material")
            walk.same(hashlib.sha256(run.db.read_bytes()).digest(), before, "opens do not change DB")
            if not baseline:
                # Review remains possible even if the trace moves after explicit classification.
                moved = Path(trace).with_suffix(".moved")
                Path(trace).rename(moved)
                try:
                    walk.same(run.invoke(*args, "--text", endpoint=endpoint).stdout, text.stdout,
                              "local context is frozen, not re-read from the trace on open")
                    walk.same(len(calls), 1, "opening without the trace still does not send material")
                    walk.same(hashlib.sha256(run.db.read_bytes()).digest(), before,
                              "opening without the trace still does not change DB")
                finally:
                    moved.rename(trace)
        walk.same([c["classification"]["kind"] if c.get("classification") else None for c in opened["cards"]],
                  ["experience_claim", "experience_claim", "question", None], "fixture proposals present")
        if not baseline:
            walk.same([c["kind_conflict"] for c in opened["cards"]], [True, False, False, False],
                      "only the wrong stronger label is flagged in this scenario")
            lines = text.stdout.strip().splitlines()[1:]
            headers = [i for i, line in enumerate(lines) if line.startswith("[")]
            walk.same(len(headers), 4, "four visible entries")
            first, observation, question, draft = [
                "\n".join(lines[a:b]) for a, b in zip(headers, [*headers[1:], len(lines)])
            ]
            for evidence in ("v1 判类待核", "讨论时为可试做法；后续模型提议为经验陈述", "认可表述不等于认可判类",
                             "模型摘录", "原话整轮", "想试在桌面放一张卡", "试法，不是结论",
                             "模型指出的依据缺口：还没有两组同时收桌的观察。"):
                assert evidence in first, (evidence, first)
            assert "v2 经验陈述（模型提议）" in observation and walk.TURNS[1] in observation
            assert "v3 待确认问题（模型提议）" in question and walk.TURNS[2] in question
            assert "[未认可草稿]" in draft and "模型摘录" not in draft and "判类待核" not in draft
            for card in opened["cards"][:3]:
                turn = walk.TURNS[card["version"] - 1]
                walk.same(card["classification"]["cited_turns"], [{"seq": seqs[turn], "text": turn}],
                          "each saved context is the cited local user turn only")
        broadcast = run.cli("broadcast", walk.CARDS[2]["statement"])
        assert all(x["id"] != ident for x in broadcast["results"])
        assert any(x["id"] == ident and "single-session" in x["reason"] for x in broadcast["suppressed"])
        walk.same(run.old(), old, "old near neighbor is unchanged")
        walk.dump(out / "distill.json", opened)
        (out / "distill.txt").write_text(text.stdout, encoding="utf-8")
        print(out / "distill.txt")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("worktree", type=lambda value: Path(value).resolve())
    parser.add_argument("output", type=lambda value: Path(value).resolve())
    parser.add_argument("--baseline", action="store_true", help="emit the old reader output without new assertions")
    args = parser.parse_args()
    main(args.worktree, args.output, baseline=args.baseline)
