"""Walk the whole story offline: one sentence, its limits, a doubt, a third session.

    python3 docs/evidence/2026-11-28-handoff-boundary/story.py [worktree]

This is the human-readable companion to `verify.py`: it prints what a person actually saw,
session by session, and ends with the readings. `verify.py` is the strict version -- it
asserts and counts; this one is for reading.

Everything is local. The model is a loopback stub whose replies are constants written in
this file: **these are not real sessions, not a real person's words, and not a model's
judgement.** What is measured is what the program printed and sent.

Exit 0 when every reading matches what the slice claims, 1 otherwise.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1
            else Path(__file__).resolve().parents[3]).resolve()

STATEMENT = "值班提醒交给系统跑，只在结果会打断他时才叫醒他。"
SCOPE = "他已经抽身、这条提醒的失败不会当场伤人时"
COUNTER = "提醒必须发生在值班当场、人来不及时接手时"
UNKNOWN = "他会不会真的回来看提醒"
PREMISE = "系统能自己跑检查"
DOUBT = "第三个团队里更糟：提醒他根本没看"
CONCLUSION = {"statement": STATEMENT, "kind": "abstract_idea", "scope": [SCOPE],
              "premises": [PREMISE], "alternatives": ["把提醒留给人"],
              "contradictions": [COUNTER], "unknowns": [UNKNOWN]}

REQUESTS: list[str] = []
REPLIES: list[dict] = []
READINGS: list[tuple[str, bool, str]] = []


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        REQUESTS.append(self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode())
        reply = REPLIES.pop(0) if REPLIES else {"answer": "嗯。", "candidate": None,
                                                "user_stance": "neutral"}
        body = json.dumps({
            "choices": [{"message": {"role": "assistant",
                                     "content": json.dumps(reply, ensure_ascii=False)},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *arguments):
        pass


def heading(text: str) -> None:
    print("\n" + "=" * 6 + " " + text + " " + "=" * 6)


def reading(label: str, held: bool, detail: str = "") -> None:
    READINGS.append((label, bool(held), detail))
    print(("  ok   " if held else "  FAIL ") + label + ("   " + detail if detail else ""))


def main() -> int:
    socket.setdefaulttimeout(10)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}/v1"
    temp = tempfile.TemporaryDirectory()
    root = Path(temp.name)
    (root / "home").mkdir()
    db = root / "dojo.sqlite3"
    env = {k: v for k, v in os.environ.items() if not k.startswith("DOJO_")}
    env.update({"HOME": str(root / "home"), "DOJO_DB": str(db),
                "DOJO_LLM_BASE_URL": base, "DOJO_LLM_MODEL": "loopback",
                "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"})

    def cli(*args: str, stdin: str = "") -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-B", "-m", "dojo", *args],
                              cwd=str(ROOT), env=env, input=stdin, text=True,
                              capture_output=True, timeout=180)

    def opening(screen: str) -> str:
        return screen.split("你可以直接讲", 1)[0]

    # ---- scene 1: he states the sentence, agrees to it, answers the four questions ----
    heading("第一场：他说出一句带边界的话，并认可它")
    REQUESTS.clear()
    REPLIES[:] = [
        {"answer": "先把它写成一句带边界的话：" + STATEMENT, "candidate": CONCLUSION,
         "user_stance": "neutral"},
        {"answer": "记下了。", "candidate": CONCLUSION, "user_stance": "accept"},
        {"answer": "嗯。", "candidate": None, "user_stance": "neutral"},
        {"answer": "嗯。", "candidate": None, "user_stance": "neutral"},
        {"answer": "嗯。", "candidate": None, "user_stance": "neutral"},
        {"answer": "嗯。", "candidate": None, "user_stance": "neutral"},
    ]
    done = cli("discuss", stdin="提醒太多了，我想让系统盯着\n对，就是这个\n"
               "他下班以后就不看群了\n团队就我们几个\n有一次半夜没人看\n就这些\n")
    if done.returncode:
        print(done.stdout[-1500:], done.stderr[-1500:])
        return 1
    print("\n".join(line for line in done.stdout.splitlines()
                    if line.startswith(("本场结论卡片 ID", "主持人> 这条已经写下来"))))
    card = None
    for token in done.stdout.replace("、", " ").split():
        if token.startswith("d-"):
            card = token
    if card is None:
        cards = json.loads(cli("list").stdout)
        card = cards[0]["id"] if cards else None
    if card is None:
        print("没有写出卡片；后面的场面无从谈起")
        return 1
    written = json.loads(cli("show", card).stdout)
    basis = written.get("time_basis") or {}
    reading("第一场结束时库里有这套说法的认可记录", bool(basis.get("accepted_at")),
            str(basis.get("acceptance_path")))
    reading("库里记着它的四条边界",
            bool(written["candidate"].get("scope")) and bool(written["candidate"].get("contradictions"))
            and bool(written["candidate"].get("unknowns")) and bool(written["candidate"].get("premises")))

    # ---- scene 2: another discussion is handed it ----
    heading("第二场：另一场讨论在模型开口之前读到什么")
    REQUESTS.clear()
    REPLIES[:] = [{"answer": "接着看这条。", "candidate": None, "user_stance": "neutral"},
                  {"answer": "嗯。", "candidate": None, "user_stance": "neutral"}]
    done = cli("discuss", "--card", card, stdin="换了个团队，我想看看这条还成不成立\n就这些\n")
    print(opening(done.stdout))
    screen = opening(done.stdout)
    request = REQUESTS[0] if REQUESTS else ""
    for label, value in (("什么时候成立", SCOPE), ("什么时候不成立", COUNTER),
                         ("还没定的是", UNKNOWN), ("它靠这些前提", PREMISE)):
        reading("开场屏幕印出「" + label + "」", value in screen)
        reading("同样的内容也发给了模型", value in request)
    reading("不声称没人认可过它", "还没有人认可" not in screen)
    reading("按库里的记录说认可", "库里有这套说法" in screen)

    # ---- scene 3: somebody doubts it, and a third session reads that doubt ----
    heading("第三场：有人质疑之后，又一场讨论拿到它")
    out = cli("challenge", card, "--text", DOUBT)
    reading("质疑写入成功", out.returncode == 0, out.stderr[-200:])
    REQUESTS.clear()
    REPLIES[:] = [{"answer": "这条被质疑过，我们看看。", "candidate": None,
                   "user_stance": "neutral"},
                  {"answer": "嗯。", "candidate": None, "user_stance": "neutral"}]
    done = cli("discuss", "--card", card, stdin="接着这条再想想\n就这些\n")
    print(opening(done.stdout))
    screen = opening(done.stdout)
    request = REQUESTS[0] if REQUESTS else ""
    reading("质疑原话印在「什么时候不成立」下面", DOUBT in screen)
    reading("质疑原话也发给了模型", DOUBT in request)
    reading("质疑之后不再说「没人认可」", "还没有人认可" not in screen)
    reading("质疑之后说的是「库里没有这套说法的记录」",
            "库里没有这套说法" in screen and "不等于没人认可过它" in screen)

    failures = [item for item in READINGS if not item[1]]
    print("\n" + str(len(READINGS)) + " 项读数：" + str(len(READINGS) - len(failures))
          + " 成立，" + str(len(failures)) + " 不成立。")
    print("模型是本地回环桩，回答是写死的常量；这不是真人会话，也不是模型的判断。")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
