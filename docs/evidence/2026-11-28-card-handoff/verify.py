#!/usr/bin/env python3
"""A card from one session, really changing what a later session is given.

Every claim in this slice's SUMMARY is checked here, offline, in a throwaway library.
Where a line is printed, the same run also reads the record and the model's request,
because the defect this line of work keeps finding is a screen that says something the
payload or the trace does not support.

    python3 docs/evidence/2026-11-28-card-handoff/verify.py
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from dojo.discuss import (  # noqa: E402
    NEW_SESSION_LIMIT_NOTE, handoff_block, handoff_for_model, run_discuss,
)
from dojo.storage import Store  # noqa: E402

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print("OK     " + label)
    else:
        print("FAIL   " + label + (("  —— " + detail) if detail else ""))
        failures.append(label)


LEFT = "持续检查交给系统自己跑，人只在想推翻的时候回来。"
NARROW = "持续检查交给系统自己跑，但只在检查结果会打断他时才叫醒他。"
REASON = "原来那句没写清楚什么时候该叫醒他，所以第三次更糟。"
DOUBT = "第三次在同一团队反而更糟：检查结果他根本没看。"


def conclusion(statement=NARROW):
    return {
        "statement": statement, "kind": "abstract_idea",
        "scope": ["他已经抽身的时候"], "premises": ["系统能自己跑检查"],
        "alternatives": ["把检查留给人"], "contradictions": [DOUBT],
        "unknowns": ["他会不会来看回执"],
    }


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete(self, messages):
        self.calls.append(messages)
        return self.responses.pop(0)


def read_lines(lines):
    iterator = iter(lines)

    def read_line(_prompt):
        try:
            return next(iterator)
        except StopIteration:
            raise EOFError
    return read_line


def last_context(calls):
    for message in reversed(calls[-1]):
        if message["role"] == "user":
            return message["content"]
    return ""


def _cli_run(root, args, *, stdin=""):
    """Run the real `python3 -m dojo` against a loopback endpoint.

    Returns the exit code, both streams, the request bodies the endpoint received, and
    the first body as text. The endpoint is a thread in this process; nothing leaves the
    machine, and no model is involved.
    """
    import os
    import subprocess
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    reply = {"choices": [{"message": {
        "role": "assistant", "content": json.dumps({
            "answer": "那我们接着这句谈。", "candidate": None,
            "user_stance": "neutral"}, ensure_ascii=False)},
        "finish_reason": "stop"}]}

    class Handler(BaseHTTPRequestHandler):
        bodies: list[str] = []

        def do_POST(self):  # noqa: N802
            Handler.bodies.append(
                self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode())
            payload = json.dumps(reply, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *arguments):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        environment = {k: v for k, v in os.environ.items() if not k.startswith("DOJO_")}
        environment.update({
            "DOJO_DB": str(root / "dojo.sqlite3"),
            "DOJO_LLM_BASE_URL": "http://127.0.0.1:%d/v1" % server.server_address[1],
            "DOJO_LLM_MODEL": "loopback",
            "PYTHONPATH": str(ROOT),
            "PYTHONDONTWRITEBYTECODE": "1",
        })
        done = subprocess.run(
            [sys.executable, "-B", "-m", "dojo", *args], cwd=str(ROOT), env=environment,
            input=stdin, text=True, capture_output=True, timeout=180,
        )
    finally:
        server.shutdown()
        server.server_close()
    return {
        "code": done.returncode, "stdout": done.stdout, "stderr": done.stderr,
        "requests": len(Handler.bodies),
        "request": Handler.bodies[0] if Handler.bodies else "",
    }


def main() -> int:
    temp = tempfile.TemporaryDirectory()
    root = Path(temp.name)
    store = Store(root / "dojo.sqlite3")
    card = store.add(
        statement=LEFT, kind="abstract_idea",
        scope=["他已经抽身的时候"], premises=["系统能自己跑检查"],
        alternatives=["把检查留给人"], contradictions=[DOUBT],
        unknowns=["他会不会来看回执"],
        sources=[{"id": "s1", "type": "claimed_firsthand", "verification": "unverified",
                  "independence_group": "gA", "claim": "他这样做过两次",
                  "scope_note": "两次都在同一团队"}],
        session="sess-A",
    )
    cid = card["id"]
    store.record_acceptance(cid, "sess-A", path="discuss_conclusion")
    store.confirm(cid, "他在会话里认可了这句；不表示为真", session="sess-A")
    store.challenge(cid, DOUBT)
    store.revise(cid, NARROW, REASON, scope=["他已经抽身的时候"],
                 premises=["系统能自己跑检查"], alternatives=["把检查留给人"],
                 contradictions=[DOUBT], unknowns=["打断多少次会变成骚扰"], session="sess-B")
    store.record_acceptance(cid, "sess-C", path="discuss_conclusion")
    store.confirm(cid, "新一场里他认可了改写后的这句", session="sess-C")
    shown = store.show(cid)

    # C1--C3: the two functions, before any session runs. An absent fact gets no line.
    block = handoff_block(shown["candidate"], shown.get("revision_basis"))
    model_text = handoff_for_model(shown["candidate"], shown.get("revision_basis"))
    check("C1 屏幕把现在这句、被改掉的那句、他改主意的理由都说了",
          all(piece in block for piece in (NARROW, LEFT, REASON)), block)
    check("C2 给模型的资料里也有同样三件，并写明它是资料不是本轮输入",
          all(piece in model_text for piece in (NARROW, LEFT, REASON))
          and "资料，不是用户本轮说的话" in model_text)
    plain = store.add(statement="一句没改过的话。", kind="abstract_idea",
                      scope=["某个场合"], session="sess-A")
    plain_shown = store.show(plain["id"])
    plain_block = handoff_block(plain_shown["candidate"], plain_shown.get("revision_basis"))
    check("C3 没改过的卡不说「原来是」也不编理由",
          "原来是" not in plain_block and "改主意" not in plain_block, plain_block)

    # C4--C5: a new session with no card is unchanged.
    bare = FakeClient([{"answer": "先说你想解决的。", "candidate": None, "user_stance": "neutral"}])
    bare_out = io.StringIO()
    run_discuss(store, client=bare, read_line=read_lines(["我想想"]), output=bare_out, environ={})
    check("C4 不带 --card 时仍说「不自动带上」，且请求里没有这张卡",
          bare_out.getvalue().count(NEW_SESSION_LIMIT_NOTE) == 1
          and NARROW not in last_context(bare.calls))
    check("C5 不带 --card 时不写读记录",
          store.reads(cid)["rows"] == [])
    bare_trace = sorted((root / "sessions").glob("*.jsonl"))
    check("C5b 不带 --card 时轨迹里没有 handout 行",
          all('"event": "handout"' not in path.read_text(encoding="utf-8")
              for path in bare_trace))

    # C6--C7: handed, on screen and in the request.
    client = FakeClient([{"answer": "那我们接着这句谈。", "candidate": None, "user_stance": "neutral"}])
    output = io.StringIO()
    code = run_discuss(store, client=client, card=cid, read_line=read_lines(["接着上次那条说"]),
                       output=output, environ={})
    screen = output.getvalue()
    check("C6 退出 0，屏幕点名这张卡、这句话、被改掉的那句和他的理由",
          code == 0 and cid in screen and all(piece in screen for piece in (NARROW, LEFT, REASON)),
          screen)
    check("C6b 交了卡就不再印「不自动带上」", NEW_SESSION_LIMIT_NOTE not in screen)
    check("C7 模型的请求里真的带着这句和理由",
          all(piece in last_context(client.calls) for piece in (NARROW, REASON)))
    print()
    print("这一场开头，人看到的：")
    for line in screen.splitlines():
        if line.startswith("这一场带上") or line.startswith("  "):
            print("    " + line)
    print()

    # C8: the read log and the echo gate.
    check("C8 交卡时写了读记录（surface=discuss）",
          [row["surface"] for row in store.reads(cid)["rows"]] == ["discuss"],
          json.dumps(store.reads(cid)["rows"], ensure_ascii=False))

    echo_card = store.add(
        statement="检查交给系统跑，只在结果会打断他时叫醒他。", kind="abstract_idea",
        scope=["他已经抽身的时候"], premises=["系统能自己跑检查"],
        alternatives=["把检查留给人"], contradictions=[DOUBT],
        unknowns=["他会不会来看回执"],
        sources=[{"id": "s9", "type": "claimed_firsthand", "verification": "unverified",
                  "independence_group": "gA", "claim": "他这样做过两次",
                  "scope_note": "两次都在同一团队"}],
        session="sess-A",
    )
    store.record_acceptance(echo_card["id"], "sess-A", path="discuss_conclusion")
    store.confirm(echo_card["id"], "认可；不表示为真", session="sess-A")
    restated = conclusion("检查交给系统跑，只在结果会打断他时叫醒他。")
    echo = FakeClient([
        {"answer": "这句就是以前那条。", "candidate": restated, "user_stance": "neutral"},
        {"answer": "那我记成你同意。", "candidate": restated, "user_stance": "accept"},
    ])
    echo_out = io.StringIO()
    run_discuss(store, client=echo, card=echo_card["id"],
                read_line=read_lines(["就是以前那条，我同意", "对"]),
                output=echo_out, environ={})
    state = store.show(echo_card["id"])["candidate"]
    check("C9 只是把交过来的话重复一遍，本场不算第二个独立来源",
          not any(name.startswith("discuss-") for name in state["sessions"]),
          json.dumps(state["sessions"], ensure_ascii=False))
    check("C9b 屏幕当面说了这件事",
          "本场不算第二个独立来源" in echo_out.getvalue(), echo_out.getvalue())

    # C10--C11: the record, and the refusals.
    handouts = []
    for path in sorted((root / "sessions").glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            if record.get("event") == "handout":
                handouts.append(record)
    # Two sessions were handed a card, and file order is not card order: pick the row by
    # id. Reading `handouts[0]` asserted about whichever session's filename sorted first.
    narrowed = [row for row in handouts if row["candidate"] == cid]
    check("C10 轨迹里留下的是交出去的那一版措辞与理由",
          len(handouts) == 2 and len(narrowed) == 1
          and narrowed[0]["statement"] == NARROW
          and narrowed[0]["revision_basis"]["reason"] == REASON
          and narrowed[0]["revision_basis"]["left_wording"] == LEFT,
          json.dumps(handouts, ensure_ascii=False))

    empty = FakeClient([])
    bad_out = io.StringIO()
    bad_code = run_discuss(store, client=empty, card="no-such-card",
                           read_line=read_lines(["你好"]), output=bad_out, environ={})
    check("C11 读不出来的卡：退出 2、不发请求、不说端点的事",
          bad_code == 2 and empty.calls == []
          and "这张卡读不出来" in bad_out.getvalue()
          and "DOJO_LLM_BASE_URL" not in bad_out.getvalue(), bad_out.getvalue())

    trace = sorted((root / "sessions").glob("*.jsonl"))[0]
    both = FakeClient([])
    both_out = io.StringIO()
    both_code = run_discuss(store, client=both, card=cid, resume=trace,
                            read_line=read_lines(["继续"]), output=both_out, environ={})
    check("C12 --card 与 --resume 同时给：退出 2 且不发请求",
          both_code == 2 and both.calls == [] and "不能同时使用" in both_out.getvalue())
    resumed = FakeClient([{"answer": "继续说。", "candidate": None, "user_stance": "neutral"}])
    resumed_out = io.StringIO()
    resumed_code = run_discuss(store, client=resumed, resume=trace,
                               read_line=read_lines(["继续"]), output=resumed_out, environ={})
    check("C13 带过卡的那一场仍能续跑（handout 行不会让轨迹读不出来）",
          resumed_code == 0 and "历史与待处理内容已恢复" in resumed_out.getvalue(),
          resumed_out.getvalue())

    store.close()

    # C14--C17: the path the supervisor walked and this script had never taken -- the
    # real CLI process, with a real endpoint configured, on the card-named path. Every
    # check above runs `run_discuss` in-process with a store and a client handed to it,
    # so the branch that owns the store was never exercised: it passed a `store` that was
    # still None and died at the first `store.show` after 0 requests. A verifier that
    # cannot fail on that is not watching the entry point people use.
    cli = _cli_run(root, ["discuss", "--card", cid], stdin="接着上次那条说\n")
    check("C14 真实 CLI + 回环端点：退出 0，端点收到恰好 1 个请求",
          cli["code"] == 0 and cli["requests"] == 1
          and "Traceback" not in cli["stderr"],
          cli["stderr"] or cli["stdout"])
    check("C15 真实 CLI 屏幕上印的是这张卡的现在这句",
          cli["code"] == 0 and NARROW in cli["stdout"], cli["stdout"])
    request = cli["request"]
    check("C16 模型请求里真有旧措辞、新措辞和改主意的理由",
          all(piece in request for piece in (LEFT, NARROW, REASON)), request[:800])
    check("C17 卡的来源记录也到了模型请求里（类型与核验状态都没被改写）",
          all(piece in request for piece in ("claimed_firsthand", "unverified",
                                             "他这样做过两次", "两次都在同一团队")),
          request[:800])
    typed = _cli_run(root, ["discuss", "--card", "no-such-card"], stdin="")
    check("C18 真实 CLI 上打错卡号：仍是本地拒绝，0 请求"
          , typed["code"] == 2 and typed["requests"] == 0
          and "这张卡读不出来" in typed["stderr"], typed["stderr"])

    # C19--C22: the second half of a session, at the real entry point. The supervisor
    # resumed a session that had been handed a card and the outbound request carried
    # none of it: `_load_resume_trace` validated the handout row and dropped it. Every
    # check above stopped at the live first turn, which is exactly why nothing caught it.
    #
    # The card is revised between the halves on purpose. One conversation is about one
    # sentence; if resume reached into `store.show`, it would hand the model a version
    # this session never saw and leave "这一段说的是哪句" unanswerable from the record.
    # Identified by set difference, not by filename sort: session ids are random uuids,
    # so "the last file" is whichever sorts last, not whichever was just written.
    before = set((root / "sessions").glob("*.jsonl"))
    halves = _cli_run(root, ["discuss", "--card", cid], stdin="接着上次那条说\n")
    new_traces = sorted(set((root / "sessions").glob("*.jsonl")) - before)
    check("C19a 第一半写下了自己的轨迹",
          halves["code"] == 0 and len(new_traces) == 1,
          str([path.name for path in new_traces]))
    first_half_trace = new_traces[0] if new_traces else sorted(
        (root / "sessions").glob("*.jsonl"))[-1]
    LATER = "持续检查交给系统自己跑，只在他说停的时候才停。"
    store_later = Store(root / "dojo.sqlite3")
    store_later.revise(cid, LATER, "后来觉得叫醒的门槛还是太低。",
                       scope=["他已经抽身的时候"], premises=["系统能自己跑检查"],
                       alternatives=["把检查留给人"], contradictions=[DOUBT],
                       unknowns=["他会不会来看回执"], session="sess-D")
    rows_before = len(store_later.reads(cid)["rows"])
    store_later.close()
    resumed = _cli_run(root, ["discuss", "--resume", str(first_half_trace)],
                       stdin="继续\n")
    resumed_request = resumed["request"]
    check("C19 真实 CLI 续跑：退出 0，端点收到请求，屏幕说历史已恢复",
          halves["code"] == 0 and resumed["code"] == 0 and resumed["requests"] >= 1
          and "历史与待处理内容已恢复" in resumed["stdout"],
          resumed["stderr"] or resumed["stdout"])
    check("C20 续跑的请求带着旧措辞、新措辞、改主意的理由",
          all(piece in resumed_request for piece in (LEFT, NARROW, REASON)),
          resumed_request[:800])
    check("C21 续跑的请求带着来源的类型与核验状态",
          all(piece in resumed_request for piece in (
              "claimed_firsthand", "unverified", "他这样做过两次", "两次都在同一团队")),
          resumed_request[:800])
    check("C22 续跑沿用这一场原先收到的那一版，而不是库里后来改的那一版",
          NARROW in resumed_request and LATER not in resumed_request,
          resumed_request[:800])
    store_after = Store(root / "dojo.sqlite3")
    check("C22b 续跑没有为同一场再记一次读卡",
          len(store_after.reads(cid)["rows"]) == rows_before,
          json.dumps(store_after.reads(cid)["rows"], ensure_ascii=False)[:400])
    store_after.close()

    # C23: `dojo seed` is the first command the README gives a person. The seed pack
    # writes no `contradictions`, and `_candidate_fields` subscripted it, so handing one
    # of those cards over died on the first turn with `KeyError: 'contradictions'`.
    seed_root = Path(tempfile.mkdtemp(dir=str(root)))
    from dojo.storage import load_simulated_seeds  # noqa: E402
    seed_store = Store(seed_root / "dojo.sqlite3")
    load_simulated_seeds(seed_store)
    seed_client = FakeClient([{"answer": "这几条是模拟材料。", "candidate": None,
                               "user_stance": "neutral"}])
    seed_out = io.StringIO()
    seed_code = run_discuss(seed_store, client=seed_client, card="seed-m01",
                            read_line=read_lines(["我们谈谈这一条"]),
                            output=seed_out, environ={})
    seed_context = last_context(seed_client.calls) if seed_client.calls else ""
    check("C23 种子卡（没有 contradictions 字段）也能交给一场讨论",
          seed_code == 0 and "环境与流程的设计" in seed_context
          and "abstract_reasoning" in seed_context,
          seed_out.getvalue() or "no request sent")
    seed_store.close()

    temp.cleanup()
    print()
    if failures:
        print(f"{len(failures)} 项不成立。")
        return 1
    print("全部成立。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
