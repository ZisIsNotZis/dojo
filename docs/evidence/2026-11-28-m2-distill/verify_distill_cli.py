#!/usr/bin/env python3
"""Synthetic, offline real-CLI M2 walk: verify_distill_cli.py WORKTREE NEW_ARTIFACT_DIR.

No private input or endpoint. --discussion-only reproduces the old baseline's
reader output without requiring the new classifier arguments.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import queue
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


TURNS = [
    "我在社区桌游夜做布置交接，想试在桌面放一张卡，只写接班人下一步该摆什么。只限常规收桌后、交班人还在场的时候；我没试过两组同时收桌。我们先把这说成试法，不是结论。",
    "补一条我亲眼看到的：同一间活动室的两次彩排，第一次把下一步拆在两张便签上，接手的人问我从哪儿开始；第二次并在一张桌面卡上，接手的人没问。这只是两次，不知道是不是卡片造成的。",
    "把还没有答案的事单独留下：如果两组同时收桌，一张卡会不会把两组的下一步混在一起？我没试过，不主张它可行或不可行。",
    "另一种试法也先摆出来看看：两组各用一种颜色，但这些卡只在光线充足的桌面用；别先把它当成已认可的做法。",
]


def card(statement, kind, scope, premises=(), alternatives=(), contradictions=(), unknowns=()):
    return {"statement": statement, "kind": kind, "scope": list(scope), "premises": list(premises),
            "alternatives": list(alternatives), "contradictions": list(contradictions), "unknowns": list(unknowns)}


CARDS = [
    card("用一张桌面卡只标出接班人的下一步布置。", "application",
         ["社区桌游夜常规收桌后，交班人还在场"],
         alternatives=["用两张便签分别提示"],
         unknowns=["没试过两组同时收桌"]),
    card("两次彩排里，分写两张便签时接班人问从哪儿开始，合写一张时没问。", "experience_claim",
         ["同一间活动室，仅两次彩排"],
         premises=["是发言者亲眼看到的两次交接"],
         unknowns=["不知道差别是否由卡片造成"]),
    card("如果两组同时收桌，一张卡会不会混淆两组各自的下一步？", "question",
         ["两组同时收桌"], unknowns=["没有试过，不主张可行或不可行"]),
    card("两组可以各用一种颜色的卡。", "application", ["两组同时收桌，桌面光线充足"],
         unknowns=["仅供讨论，尚未试过"]),
]
ANSWERS = [
    "可以先把它限定为常规收桌之后试一下：卡上只留下一步，不认为所有交接都适用。",
    "值得分开保留这两次观察；没人提问不等于卡片起了作用，更不能外推到别的活动。",
    "那就保留成一个问题：两组的下一步会不会被当成同一组的？两次单组彩排答不了它。",
    "分颜色是一种待比较的试法；光线足够也是边界。现在没有数据可以说哪种更好。",
]
QUOTES = [
    "想试在桌面放一张卡，只写接班人下一步该摆什么",
    "第二次并在一张桌面卡上，接手的人没问",
    "如果两组同时收桌，一张卡会不会把两组的下一步混在一起？",
]
REASONS = [
    "发言者提议在常规交接时试一个具体动作，不是报告效果。",
    "发言者报告两次亲眼所见，明确没有归因。",
    "这一版保留未回答的问题，没有断言结果。",
]
MISSING = ["没有对两组同时收桌的试用记录。", "没有对照保证只有卡片的写法改变。", "没有实际的双组交接观察。"]
BASELINE_OLD = {**CARDS[0], "scope": ["社区印刷角收拾打印工具后，前一班还在场"],
                "unknowns": ["没和桌游夜的布置交接比较过"]}
OLD_ID = "older-print-corner"
DRIFT = "事后编辑：在所有交班环境中都只用一张卡，不必留例外。"


def same(result, expected, why):
    if result != expected:
        raise AssertionError(f"{why}\nactual: {result!r}\nexpected: {expected!r}")


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_helper(repo):
    path = repo / "docs/evidence/2026-11-28-review-before-accept/verify_review_cli.py"
    spec = importlib.util.spec_from_file_location("review_cli", path)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    return helper


@contextmanager
def loopback(reply):
    calls, errors = [], []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            try:
                assert self.path == "/v1/chat/completions", self.path
                request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                calls.append(request)
                content = reply(request, len(calls) - 1)
                payload = json.dumps({"choices": [{"message": {"role": "assistant",
                    "content": json.dumps(content, ensure_ascii=False)}, "finish_reason": "stop"}]}).encode()
            except Exception as exc:
                errors.append(repr(exc))
                self.send_error(400, "Synthetic fixture disagreement")
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}/v1", calls, errors
        finally:
            server.shutdown()
            thread.join(timeout=5)


class Run:
    def __init__(self, repo, out, temp):
        self.repo, self.out, self.temp = repo, out, temp
        self.db = temp / "library.sqlite3"
        self.helper = read_helper(repo)
        self.env = {"PATH": os.environ["PATH"], "HOME": str(temp), "LANG": "C.UTF-8", "PYTHONUTF8": "1",
                    "NO_PROXY": "127.0.0.1", "DOJO_SESSIONS": str(temp / "sessions"),
                    "DOJO_LLM_API_KEY": "fixture-only", "DOJO_LLM_MODEL": "synthetic-loopback"}

    def cmd(self, *args):
        return [sys.executable, "-B", "-u", "-m", "dojo", "--db", str(self.db), *map(str, args)]

    def invoke(self, *args, endpoint=None):
        env = {**self.env, "DOJO_LLM_BASE_URL": endpoint} if endpoint else self.env
        return subprocess.run(self.cmd(*args), cwd=self.repo, env=env, text=True, encoding="utf-8",
                              capture_output=True, timeout=30)

    def cli(self, *args, endpoint=None):
        result = self.invoke(*args, endpoint=endpoint)
        same(result.returncode, 0, f"{args}: {result.stdout}\n{result.stderr}")
        return json.loads(result.stdout)

    def seed(self):
        data = BASELINE_OLD
        args = ["add", "--id", OLD_ID, "--statement", data["statement"], "--kind", data["kind"],
                "--session", "earlier-print-corner", "--source-json", json.dumps({
                    "id": "print-corner-source", "type": "claimed_firsthand", "verification": "unverified",
                    "independence_group": "earlier-print-corner", "claim": "曾用过同样的提醒办法整理打印角"})]
        for field, flag in (("scope", "scope"), ("premises", "premise"), ("alternatives", "alternative"),
                            ("contradictions", "contradiction"), ("unknowns", "unknown")):
            for value in data[field]:
                args.extend(["--" + flag, value])
        self.cli(*args)
        return self.old()

    def old(self):
        return {"show": self.cli("show", OLD_ID, "--history"), "events": self.cli("events", "--id", OLD_ID)}

    def discussion(self):
        def reply(request, index):
            assert any(TURNS[index] in msg["content"] for msg in request["messages"] if msg["role"] == "user")
            return {"answer": ANSWERS[index], "candidate": CARDS[index], "user_stance": "neutral", "person_updates": []}

        with loopback(reply) as (endpoint, calls, errors):
            env = {**self.env, "DOJO_LLM_BASE_URL": endpoint}
            with (self.out / "discuss.stderr.txt").open("w", encoding="utf-8") as err:
                proc = subprocess.Popen(self.cmd("discuss", "--no-profile"), cwd=self.repo, env=env,
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err, text=True, encoding="utf-8")
                received, screen = queue.Queue(), []

                def reader():
                    for line in proc.stdout:
                        screen.append(line)
                        received.put(line)
                    received.put(None)

                worker = threading.Thread(target=reader, daemon=True)
                worker.start()

                def send(text):
                    proc.stdin.write(text + "\n")
                    proc.stdin.flush()

                def expect(needle):
                    while True:
                        line = received.get(timeout=20)
                        if line is None:
                            raise AssertionError(f"CLI ended before {needle!r}")
                        if needle in line:
                            return line

                try:
                    for i, (turn, expected) in enumerate(zip(TURNS, CARDS)):
                        send(turn)
                        expect("【写入前核对 · 尚未认可】")
                        review = ["【写入前核对 · 尚未认可】"]
                        while True:
                            line = received.get(timeout=20)
                            if line is None:
                                raise AssertionError("CLI ended during review")
                            review.append(line.rstrip("\r\n"))
                            if self.helper.REVIEW_END in line:
                                break
                        same(self.helper.parse_review(review), (expected, turn), f"rendered exact review {i+1}")
                        if i == 3:
                            break  # Real EOF on the visible, never-approved fourth proposal.
                        send("/认可")
                        expect("已记下对屏上这一版的认可")
                        if i == 0:
                            # Individual skips end each part, not the session.
                            for _ in range(4):
                                send("跳过")
                    proc.stdin.close()
                    same(proc.wait(timeout=20), 0, "discuss exit")
                finally:
                    if proc.poll() is None:
                        proc.kill()
                        proc.wait(timeout=5)
                    proc.stdin.close()
                    worker.join(timeout=5)
                    proc.stdout.close()
                    (self.out / "discuss.stdout.txt").write_text("".join(screen), encoding="utf-8")
            same(errors, [], "discussion stub was satisfied")
            same(len(calls), 4, "one request per synthetic user turn, none for review/approval/skips/EOF")
        paths = [line.strip().split(self.helper.PREFIX, 1)[1] for line in screen if self.helper.PREFIX in line]
        trace = self.out / "discuss.jsonl"
        shutil.copyfile(Path(paths[-1]), trace)  # Keep reader citations openable after the temporary library is gone.
        rows = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
        same(rows[-1]["event"], "session_end", "closed trace")
        same(rows[-1]["reason"], "eof", "unapproved ending was EOF")
        ident, = rows[-1]["saved"]
        events = self.cli("events", "--id", ident)
        approvals = [e for e in events if e["event"] in {"wording_accepted", "draft_accepted"}]
        same([e["details"]["version"] for e in approvals], [1, 2, 3], "three actual approvals of distinct versions")
        session, = {e["details"]["session"] for e in approvals}
        user_seq = {row["user"]: row["seq"] for row in rows if row.get("user") in TURNS}
        same(set(user_seq), set(TURNS), "all source words present in real discuss trace")
        dump(self.out / "approval-events.json", approvals)
        return trace, session, ident, user_seq


def verify_close(run, trace, session, ident):
    """A person closes stdin, then copies commands from the screens. No pipeline yet."""
    screen = (run.out / "discuss.stdout.txt").read_text(encoding="utf-8")
    assert "本场留下：3 个已认可版本，1 份未认可草稿" in screen, screen
    path, = [Path(line.split(run.helper.PREFIX, 1)[1]) for line in screen.splitlines()
             if line.startswith(run.helper.PREFIX) and not line.endswith("（--no-trace）。")][-1:]
    same(path.read_bytes(), trace.read_bytes(), "original trace matches the archived transcript")
    digests = [hashlib.sha256(p.read_bytes()).digest() for p in (run.db, path)]
    events = run.cli("events")
    workdir = run.temp / "later terminal"
    workdir.mkdir()
    other_library = workdir / "different default.sqlite3"

    def unexpected(*_):
        raise AssertionError("no model request belongs to the local reader")

    with loopback(unexpected) as (endpoint, calls, _):
        # Copy the visible command (including --db) from another working directory.
        env = {**run.env, "DOJO_LLM_BASE_URL": endpoint, "DOJO_DB": str(other_library),
               "PYTHONPATH": str(run.repo), "PYTHONDONTWRITEBYTECODE": "1"}

        def paste(text, label, artifact):
            command, = [line.split("：", 1)[1] for line in text.splitlines() if line.startswith(label)]
            result = subprocess.run(shlex.split(command), env=env, cwd=workdir, text=True,
                                    encoding="utf-8", capture_output=True, timeout=20)
            (run.out / artifact).write_text(result.stdout, encoding="utf-8")
            same(result.returncode, 0, f"pasting {command}: {result.stderr}")
            return result.stdout

        label = "稍后看本场留下的版本和草稿"
        local = paste(screen, label, "close-reader.txt")
        transcript = paste(screen, "回看这一场说了什么", "close-transcript.txt")
        same(paste(transcript, "看本场留下的版本和草稿", "close-reader-via-transcript.txt"),
             local, "transcript leads to the same session and reader output")
        same(paste(screen, label, "close-reader-repeat.txt"), local, "open command can be repeated")
        same(calls, [], "none of these routes calls a model")
    assert not other_library.exists(), "copying the command created the other default library"
    same([hashlib.sha256(p.read_bytes()).digest() for p in (run.db, path)], digests,
         "reading never changes original library or trajectory bytes")
    same(run.cli("events"), events, "reading does not add events")
    assert session in local and "模型提议）" not in local, local
    for i, (card, label) in enumerate(zip(CARDS, ("可试做法", "经验陈述", "待确认问题")), 1):
        assert f"{ident} v{i} {label}（讨论时拟写） [本场认可快照]：{card['statement']}" in local, local
        assert all(value in local for value in (*card["scope"], *card["unknowns"])), local
    draft = CARDS[-1]
    for value in ("[未认可草稿]：" + draft["statement"], *draft["scope"], *draft["unknowns"]):
        assert value in local, local
    data = run.cli("distill", "--session", session)
    assert all(card["classification"] is None for card in data["cards"]), data
    print("PASS ordinary EOF: pasted both readback paths, 3 approved versions and 1 draft, zero model calls or writes.")


def verify_pipeline(run, old, trace, session, ident, user_seq):
    out = run.out
    command = ["pipeline", "--session", session, "--classify", "--trace", trace]
    show_before = run.cli("show", ident, "--history")
    approved_versions = show_before["history"]["versions"]
    same([(v["version"], {key: v["state"][key] for key in CARDS[0]}) for v in approved_versions],
         list(enumerate(CARDS[:3], 1)), "historical snapshots match all three rendered approval versions")
    for v in approved_versions:
        sources = v["state"]["sources"]
        same([(s["type"], s["independence_group"], s["verification"]) for s in sources],
             [("unknown", session, "unknown")], "each approval kept one unverified source")
    cli_args = ("distill", "--session", session)
    before_broadcast = run.cli("broadcast", CARDS[2]["statement"])
    same(any(x["id"] == ident for x in before_broadcast["results"]), False, "single-session card never broadcasts")
    suppressed = [x for x in before_broadcast["suppressed"] if x["id"] == ident]
    same(len(suppressed), 1, "broadcast actually found the overlapping card but suppressed it")
    assert "single-session" in suppressed[0]["reason"], suppressed
    dump(out / "broadcast.json", before_broadcast)

    draft_id = json.loads(trace.read_text(encoding="utf-8").splitlines()[-1])["draft"]
    assert draft_id != ident
    rows = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
    local_approvals = [r["seq"] for r in rows if r.get("user") == "/认可" and r.get("decision") == "written"]
    same(len(local_approvals), 3, "three local approval trace receipts")

    def classify(request, _, *, bad_quote=False):
        packet = json.loads([m["content"] for m in request["messages"] if m["role"] == "user"][-1])
        same(packet["session"], session, "classifier packet belongs to the requested session")
        results = []
        for item in packet["cards"]:
            same(item["id"], ident, "classifier must not see seeded material or EOF draft as an approval")
            version = item["version"]
            assert version in (1, 2, 3), version
            i = version - 1
            same({key: item[key] for key in CARDS[i]}, CARDS[i], "classifier received exactly the approved fields")
            same(item["approval_seq"], local_approvals[i], "classifier receipt points to actual approving turn")
            turns = {t["seq"]: t["text"] for t in item["turns"]}
            same(turns.get(user_seq[TURNS[i]]), TURNS[i], "message evidence is exact original user testimony")
            for seq, value in turns.items():
                assert seq < local_approvals[i], ("quote may not see later words", seq)
                same(next(r.get("user") for r in rows if r.get("seq") == seq), value, "packet is grounded in trace word-for-word")
            results.append({"id": ident, "version": version, "kind": item["kind"],
                            "reason": REASONS[i], "missing": MISSING[i],
                            "quotes": [{"seq": user_seq[TURNS[i]], "quote": (
                                "编出来的那句：每次交接都没问题。" if bad_quote else QUOTES[i])}]})
        same(len(results), 3, "one small request covers all three approved versions")
        return {"classifications": results}

    wrong = run.temp / "wrong-session.jsonl"
    wrong.write_text("\n".join(json.dumps({**r, "session": "different-session"} if r.get("event") == "session_end" else r,
                                         ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")

    def unexpected(*_):
        raise AssertionError("no classifier request belongs to this path")

    with loopback(unexpected) as (endpoint, calls, _errors):
        rejected = run.cli(*command[:-1], wrong, endpoint=endpoint)
        same(calls, [], "a trace ending in a different session sends no excerpts to any model")
    dump(out / "pipeline-wrong-trace.json", rejected)

    def bad(request, index):
        return classify(request, index, bad_quote=True)
    with loopback(bad) as (endpoint, calls, errors):
        result = run.invoke(*command, endpoint=endpoint)
        (out / "bad-quote.stdout.txt").write_text(result.stdout, encoding="utf-8")
        (out / "bad-quote.stderr.txt").write_text(result.stderr, encoding="utf-8")
        same(errors, [], "bad-quote fixture reached and understood valid input")
        assert calls, "bad-quote fixture must actually reach classifier"
    invalid = run.cli(*cli_args)
    same([c.get("classification") for c in invalid["cards"]], [None] * 4, "made-up words never produce a classification")
    dump(out / "distill-after-bad-quote.json", invalid)

    # Deliberately edit the shared library before the honest classifier sees it.
    # It must ask about v1–v3, not classify an unapproved mutable v4.
    revised = run.cli("revise", ident, "--statement", DRIFT, "--reason", "synthetic later editor")
    same(revised["version"], 4, "drift created a real new version")
    with loopback(classify) as (endpoint, calls, errors):
        first = run.cli(*command, endpoint=endpoint)
        same(errors, [], "honest classifier stub was satisfied")
        same(len(calls), 1, "classification uses one capped batch on the fixture")
        dump(out / "classification-packet.json", json.loads(calls[0]["messages"][-1]["content"]))
    dump(out / "pipeline.json", first)
    before_read = run.cli("events")
    before_db = hashlib.sha256(run.db.read_bytes()).digest()
    opened = run.cli(*cli_args)
    same(run.cli(*cli_args), opened, "repeat-open returns the same reader output")
    text = run.invoke(*cli_args, "--text")
    same(text.returncode, 0, f"distill --text opens at the real CLI: {text.stderr}")
    same(hashlib.sha256(run.db.read_bytes()).digest(), before_db, "opening both forms leaves every database byte unchanged")
    same(run.cli("events"), before_read, "opening cannot create ledger events")
    lookup = {(c["id"], c["version"]): c for c in opened["cards"]}
    same(set(lookup), {(ident, 1), (ident, 2), (ident, 3), (draft_id, 1)}, "reader distinguishes each approved revision and the draft")
    for i, approved in enumerate(CARDS[:3], 1):
        entry = lookup[(ident, i)]
        same(entry["approval_status"], "approved", "historical approval is reported explicitly")
        same({key: entry[key] for key in approved}, approved, "report card is exactly its approved review")
        classification = entry["classification"]
        same({key: classification[key] for key in ("kind", "reason", "missing", "quotes")}, {
            "kind": approved["kind"], "reason": REASONS[i - 1], "missing": MISSING[i - 1],
            "quotes": [{"seq": user_seq[TURNS[i - 1]], "quote": QUOTES[i - 1]}]}, "reader exposes grounded result, not label alone")
        same(Path(classification["trace"]), trace, "reader citations point to an existing exact trace")
    same((lookup[(ident, 1)]["verdict"], lookup[(ident, 1)]["of"]), ("variant", OLD_ID), "same statement but earlier print scope is a variant, not duplicate")
    draft = lookup[(draft_id, 1)]
    same((draft["approval_status"], draft["classification"]), ("unaccepted_draft", None), "the untouched proposal never gets an approved classification")
    lines = text.stdout
    same(lines.splitlines()[1:], opened["lines"], "real reader screen exposes the checked report lines")
    same(DRIFT in lines, False, "reader never prints unapproved library drift as session conclusion")
    for i, approved in enumerate(CARDS[:3], 1):
        for text in (f"v{i}", approved["statement"], *approved["scope"], *approved["unknowns"], QUOTES[i - 1]):
            assert text in lines, ("reader lines omit a review/evidence field", text, lines)
    assert "未认可" in lines and CARDS[3]["statement"] in lines
    (out / "distill-reader.txt").write_text(lines, encoding="utf-8")
    dump(out / "distill.json", opened)

    with loopback(unexpected) as (endpoint, calls, _errors):
        rerun = run.cli(*command, endpoint=endpoint)
        same(calls, [], "rerun sends no classifier request")
    dump(out / "pipeline-rerun.json", rerun)
    same(run.cli("events"), before_read, "rerun writes no new ledger events")
    same(run.cli(*cli_args), opened, "rerun leaves the opened result unchanged")
    same(run.old(), old, "earlier neighbor, source and history remain unchanged")
    same(run.cli("show", ident, "--history")["candidate"], revised, "reader and pipeline did not rewrite the library card")
    print(f"PASS real CLI: 3 exact approvals, 1 separate EOF draft, rejected bad quotes, no broadcast, no mutable drift or rerun side effect. Artifacts: {out}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("worktree", type=Path)
    parser.add_argument("output", type=Path, help="new artifact directory")
    parser.add_argument("--discussion-only", action="store_true", help="capture old CLI's baseline; no classifier commands")
    args = parser.parse_args()
    repo, out = args.worktree.resolve(), args.output.resolve()
    if repo == out or repo in out.parents:
        parser.error("write artifacts outside the checked-out worktree")
    out.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix="dojo-distill-fixture-") as name:
        run = Run(repo, out, Path(name))
        old = run.seed()
        trace, session, ident, user_seq = run.discussion()
        dump(out / "current-before.json", run.cli("show", ident, "--history"))
        if args.discussion_only:
            before = run.cli("distill", "--session", session)
            dump(out / "baseline-distill.json", before)
            run.cli("revise", ident, "--statement", DRIFT, "--reason", "synthetic later editor")
            after = run.cli("distill", "--session", session)
            dump(out / "baseline-distill-after-drift.json", after)
            same(run.old(), old, "earlier neighbor stays unchanged")
            print(f"Discussion CLI: three approvals {ident} v1–v3, one EOF draft. Readouts: {out}")
        else:
            verify_close(run, trace, session, ident)
            verify_pipeline(run, old, trace, session, ident, user_seq)


if __name__ == "__main__":
    main()
