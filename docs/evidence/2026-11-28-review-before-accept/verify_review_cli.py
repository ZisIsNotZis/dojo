#!/usr/bin/env python3
"""Offline exact-approval acceptance walk: python3 verify_review_cli.py WORKTREE OUTPUT.

All discussion, review/approval, seeding, mutation and reads use python -m dojo.
Pipe the approval only after receiving and parsing the flushed review block.
Artifacts: both CLI streams, CLI snapshots and unmodified session JSONL.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FIELDS = {
    "适用条件与边界": "scope",
    "依赖的前提与主持人推断": "premises",
    "其它解释或做法": "alternatives",
    "反例或不适用情形": "contradictions",
    "还没覆盖或核实": "unknowns",
}
ORIGINAL = '我想把报警交给系统，  但要先说清楚只在哪种夜班成立。  '
NEW = {
    "statement": "让系统先检查冷库，只有确实需要交接时才叫醒人。",
    "kind": "abstract_idea",
    "scope": ["夜班已经下班且有人接手", "冷库有第二只温度探头"],
    "premises": ["两只探头会独立记录"],
    "alternatives": ["让夜班人员一直盯着仪表"],
    "contradictions": ["备用探头也失效时不适用"],
    "unknowns": ["远程通知是否会被静音"],
}
OLD = {**NEW, "scope": ["白班人员还在现场时"]}
DRIFT = "另一位编辑改成了只听主探头。"
PREFIX = '本场会话轨迹：'
REVIEW_END = '认可上面这一版，单独输入「/认可」。'


def same(actual, expected, message):
    if actual != expected:
        raise AssertionError(f"{message}\n  actual: {actual!r}\nexpected: {expected!r}")


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def parse_review(lines):
    block = lines[lines.index("【写入前核对 · 尚未认可】") + 1:]
    proposal, original = {}, None
    for line in block:
        label, _, value = line.strip().partition("：")
        if label == "你在提出这版的那一轮说（逐字）":
            original = json.loads(value)
        elif label == "主持人拟写（不是你的原话，也未经独立核验）":
            proposal["statement"] = json.loads(value)
        elif label == "卡片类型":
            proposal["kind"] = value
        elif label in FIELDS:
            values = []
            while value and value != "这版未列出":
                item, end = json.JSONDecoder().raw_decode(value)
                values.append(item)
                value = value[end:]
                if value:
                    same(value[0], "、", "list separator")
                    value = value[1:]
            proposal[FIELDS[label]] = values
    return proposal, original


class Walk:
    def __init__(self, repo, artifacts, temp, endpoint):
        self.repo, self.artifacts = repo, artifacts
        self.temp, self.db = temp, temp / "library.sqlite3"
        self.env = {
            "PATH": os.environ["PATH"], "HOME": str(temp), "LANG": "C.UTF-8",
            "PYTHONUTF8": "1", "NO_PROXY": "127.0.0.1", "DOJO_SESSIONS": str(temp / "sessions"),
            "DOJO_LLM_BASE_URL": endpoint, "DOJO_LLM_API_KEY": "local-test-only", "DOJO_LLM_MODEL": "stub",
        }

    def command(self, *args):
        return [sys.executable, "-B", "-u", "-m", "dojo", "--db", str(self.db), *args]

    def cli(self, *args):
        result = subprocess.run(self.command(*args), cwd=self.repo, env=self.env,
                                text=True, encoding="utf-8", capture_output=True, timeout=20)
        same(result.returncode, 0, f"{args!r} failed: {result.stderr}")
        return json.loads(result.stdout)

    def seed(self, content, ident="old-card", *, challenge=True, document_case=False):
        args = ["add", "--statement", content["statement"], "--kind", content["kind"],
                "--id", ident, "--session", "earlier-session", "--source-json", json.dumps({
                    "id": "earlier-source", "type": "claimed_firsthand", "verification": "unverified",
                    "independence_group": "earlier-group",
                    "claim": "旧会话只谈了文档草稿" if document_case else "白班交接本的第一人称记载",
                    "scope_note": "没讨论过订单导出" if document_case else "不是夜班观察",
                }, ensure_ascii=False)]
        for field, flag in zip(FIELDS.values(), ("scope", "premise", "alternative", "contradiction", "unknown")):
            for value in content[field]:
                args.extend([f"--{flag}", value])
        self.cli(*args)
        self.cli("confirm", ident, "--basis", "只供讨论，不是真伪核验", "--session", "earlier-session")
        if challenge:
            self.cli("challenge", ident, "--text", "没比较过其他任务。" if document_case else "旧卡的交接本没有第二人复核。")
        self.cli("promote", ident, "--answer",
                 "情境=正在准备文档草稿" if document_case else "情境=之前在白班的交接本里记过这句",
                 "--session", "earlier-session")
        return ident

    def snapshot(self, ident, name):
        value = {
            "show": self.cli("show", ident, "--history"),
            "events": self.cli("events", "--id", ident),
            "reads": self.cli("reads", "--id", ident),
        }
        dump(self.artifacts / f"{name}.json", value)
        return value

    def discuss(self, name, *, replies, steps, resume=None, handout=None):
        args = ["discuss", "--no-profile"]
        if resume:
            args += ["--resume", str(resume)]
        if handout:
            args += ["--card", handout]
        pending = queue.Queue()
        requests = []
        for content in replies:
            pending.put({"answer": "这版请当面核对。", "candidate": content,
                         # Model says accept deliberately: without a local action it must remain provisional.
                         "user_stance": "accept", "person_updates": []})

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                try:
                    reply = pending.get_nowait()
                except queue.Empty:
                    self.send_error(400, "Unexpected request")
                    return
                payload = json.dumps({"choices": [{"message": {"role": "assistant",
                    "content": json.dumps(reply, ensure_ascii=False)}, "finish_reason": "stop"}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *_):
                pass

        with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as stub:
            server = threading.Thread(target=stub.serve_forever, daemon=True)
            server.start()
            env = {**self.env, "DOJO_LLM_BASE_URL": f"http://127.0.0.1:{stub.server_port}/v1"}
            with (self.artifacts / f"{name}.stderr.txt").open("w", encoding="utf-8") as err:
                proc = subprocess.Popen(self.command(*args), cwd=self.repo, env=env,
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err, text=True, encoding="utf-8")
                received = queue.Queue()
                screen = []

                def reader():
                    for line in proc.stdout:
                        screen.append(line)
                        received.put(line)
                    received.put(None)

                thread = threading.Thread(target=reader, daemon=True)
                thread.start()
                try:
                    for kind, value in steps:
                        if kind == "send":
                            proc.stdin.write(value + "\n")
                            proc.stdin.flush()
                            continue
                        lines = []
                        while True:
                            line = received.get(timeout=20)
                            if line is None:
                                raise AssertionError("CLI ended before rendering expected review")
                            if "【写入前核对 · 尚未认可】" in line:
                                lines.append("【写入前核对 · 尚未认可】")
                            elif lines:
                                lines.append(line.rstrip("\r\n"))
                            if REVIEW_END in line:
                                break
                        same(parse_review(lines), value, "rendered review (all fields, including original words)")
                    proc.stdin.close()
                    same(proc.wait(timeout=20), 0, f"CLI exit ({name})")
                finally:
                    if proc.poll() is None:
                        proc.kill()
                        proc.wait(timeout=5)
                    proc.stdin.close()
                    thread.join(timeout=5)
                    proc.stdout.close()
                    (self.artifacts / f"{name}.stdout.txt").write_text("".join(screen), encoding="utf-8")
                    dump(self.artifacts / f"{name}.requests.json", requests)
                    stub.shutdown()
                    server.join(timeout=5)
        same(len(requests), len(replies), "ordinary turns sent exactly once; approval takes no model request")
        trace = next(Path(line.strip()[len(PREFIX):]) for line in reversed(screen)
                     if line.strip().startswith(PREFIX))
        shutil.copyfile(trace, self.artifacts / f"{name}.jsonl")
        return trace, "".join(screen)


def talk(content=NEW, original=ORIGINAL):
    return [("send", original), ("review", (content, original))]


APPROVE = [("send", "/认可")]


def trace_rows(trace):
    return [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]


def check_saved(walk, trace, expected, name="accepted", prior_ids=()):
    rows = trace_rows(trace)
    receipts = [row for row in rows if row.get("event") == "session_end"]
    card_ids = [ident for ident in receipts[-1]["saved"] if ident not in prior_ids]
    same(len(card_ids), 1, "receipt points to one new accepted card")
    ident, = card_ids
    snapshot = walk.snapshot(ident, name)
    actual = snapshot["show"]["candidate"]
    same({key: actual[key] for key in expected}, expected, "saved content is byte-for-byte what the review showed")
    accepted = [event for event in snapshot["events"] if event["event"] in {"wording_accepted", "draft_accepted"}]
    same(len(accepted), 1, "one durable acceptance event on the identified card")
    event = accepted[0]["details"]
    same(event["candidate_id"], ident, "event owns the saved ID")
    same(actual["sessions"][-1], event["session"], "approval belongs to this session")
    same(actual["sources"][-1]["independence_group"], event["session"], "accepted source belongs to this session")
    same(actual["sources"][-1]["verification"], "unknown", "approval is not verification")
    same(bool(event.get("statement_digest")), True, "approval has a content digest")
    same(event.get("version"), actual["version"], "approval points to the exact stored snapshot")
    basis = snapshot["show"].get("time_basis", {})
    same(basis.get("acceptance_path"), event["path"], "reader resolves acceptance for the current snapshot")
    same(basis.get("agreed_at"), event.get("agreed_at"), "reader resolves the same approval instant")
    same(rows[-1]["event"], "session_end", "trace closes cleanly")
    local = [row for row in rows if row.get("user") == "/认可"][-1]
    same(local["decision"], "written", "local approval trace records a successful write")
    same(local["candidate"], expected, "local approval trace records the exact candidate")
    return ident


def empty(walk):
    trace, _ = walk.discuss("empty", replies=[NEW], steps=talk() + APPROVE)
    ident = check_saved(walk, trace, NEW)
    same([card["id"] for card in walk.cli("list", "--history")], [ident], "empty library got only the approved card")


def seeded(walk):
    original = "只是新建的订单导出页，想留一个能迈出第一步的暂定做法。"
    proposal = {
        "statement": "把任务缩成一个能执行的第一步，可能减轻启动阻力",
        "kind": "abstract_idea",
        "scope": ["只用于新建的订单导出页"],
        "premises": [], "alternatives": [], "contradictions": [], "unknowns": [],
    }
    old = walk.seed({**proposal, "scope": ["先用于文档草稿"]}, document_case=True)
    before = walk.snapshot(old, "old.before")
    trace, _ = walk.discuss("seeded", replies=[proposal], steps=talk(proposal, original) + APPROVE)
    new = check_saved(walk, trace, proposal)
    same(new == old, False, "same text with different scope must not reuse the old card")
    same(walk.snapshot(old, "old.after"), before, "the entire seeded card and ledger stayed untouched")


def resumed(walk, *, drift=False):
    old = walk.seed(OLD)
    old_before = walk.snapshot(old, "old.before")
    trace, _ = walk.discuss("before-resume", replies=[NEW], steps=talk())
    first = trace_rows(trace)[-1]
    same(first["saved"], [], "model stance alone must not accept")
    draft = first["draft"]
    original = walk.snapshot(draft, "draft.original")
    same(original["show"]["candidate"]["scope"], NEW["scope"], "draft starts with the new scope")
    same(original["show"]["candidate"]["sources"][0]["type"], "model_generated", "draft is unaccepted")
    if drift:
        walk.cli("revise", draft, "--statement", DRIFT, "--reason", "Separate library edit between legs")
    before = walk.snapshot(draft, "draft.before-resume")
    resumed_trace, _ = walk.discuss("resume", replies=[], resume=trace,
                                   steps=[("review", (NEW, ORIGINAL))] + APPROVE)
    same(resumed_trace, trace, "resume appended to the same trace")
    new = check_saved(walk, trace, NEW)
    same(new == draft, not drift, "reuse only the unchanged exact session draft")
    after = walk.snapshot(draft, "draft.after-resume")
    if drift:
        same(after, before, "resume must not overwrite or accept the drifted library draft")
    same(walk.snapshot(old, "old.after"), old_before, "the seeded earlier scope is untouched through both legs")


def shared_followup(walk):
    old = walk.seed(OLD, challenge=False)
    seeded = walk.snapshot(old, "old.seeded")
    trace, _ = walk.discuss("shared-echo", replies=[OLD], steps=talk(OLD) + APPROVE, handout=old)
    same(trace_rows(trace)[-1]["saved"], [old], "an exact approval of the handed card reuses it")
    before = walk.snapshot(old, "old.before-followup")
    for field in ("sources", "sessions", "scope", "version", "status"):
        same(before["show"]["candidate"][field], seeded["show"]["candidate"][field],
             "approving the handed echo does not add provenance or revise")
    trace, _ = walk.discuss("shared-followup", replies=[NEW], steps=talk(NEW) + APPROVE, resume=trace)
    after = walk.snapshot(old, "old.after-followup")
    same(after == before, True, "new scope rewrote the formerly approved shared card or its events: "
         f"scope {before['show']['candidate']['scope']!r} → {after['show']['candidate']['scope']!r}; "
         f"events {[row['event'] for row in before['events']]} → {[row['event'] for row in after['events']]}")
    check_saved(walk, trace, NEW, prior_ids=(old,))


def normalized_collision(walk):
    collision = {**NEW, "scope": list(reversed(NEW["scope"]))}
    old = walk.seed(collision, challenge=False)
    before = walk.snapshot(old, "collision.before")
    trace, screen = walk.discuss("collision", replies=[NEW], steps=talk() + APPROVE)
    after = walk.snapshot(old, "collision.after")
    rows = trace_rows(trace)
    actual = {"saved": rows[-1]["saved"], "untouched": before == after,
              "has_questions": any(row.get("event") == "elicitation" for row in rows),
              "reported_failure": ("没有写下认可" in screen or "本场结论未能写入" in screen),
              "reported_collision": "不等于屏上这一版" in screen}
    expected = {"saved": [], "untouched": True, "has_questions": False,
                "reported_failure": True, "reported_collision": True}
    same(actual, expected, "a collision on reordered scope cannot approve the card with the other list order")


def main():
    repo, artifacts = map(lambda item: Path(item).resolve(), sys.argv[1:3])
    scenarios = {"empty": empty, "seeded": seeded, "resume": resumed,
                 "resume-drift": lambda walk: resumed(walk, drift=True),
                 "normalized-collision": normalized_collision, "shared-followup": shared_followup}
    failures = []
    for name in (sys.argv[3:] or scenarios):
        dest = artifacts / name
        dest.mkdir(parents=True, exist_ok=False)
        with tempfile.TemporaryDirectory(prefix="review-cli-") as temp:
            walk = Walk(repo, dest, Path(temp), "http://127.0.0.1:1")
            try:
                scenarios[name](walk)
            except (AssertionError, queue.Empty) as exc:
                failures.append(name)
                print(f"FAIL {name}: {exc}", flush=True)
            else:
                print(f"OK   {name}", flush=True)
    return int(bool(failures))


if __name__ == "__main__":
    sys.exit(main())
