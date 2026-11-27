"""Can a reader see the conditions before deciding whether an old sentence transfers?

    python3 docs/evidence/2026-11-28-handoff-boundary/verify.py [worktree]

Offline: a loopback HTTP server stands in for the model, so nothing leaves the machine and
no library of yours is touched. The model's replies are scripted constants -- this file
measures what the program *shows*, not what a model makes of it.

Every check prints what it measured. Exit 0 when all hold, 1 otherwise. Nothing here reads
a number from memory: each line is produced by running the program now.
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
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

STATEMENT = "值班通知都先等两次失败再呼叫负责人。"
NARROWER = "只有普通日报才等两次失败再呼叫负责人。"
SCOPE = "只适用已经失去一个采样周期的日报。"
COUNTER = "冷库温度超过安全线时不能等待第二次。"
UNKNOWN = "交接班期间能否容忍这段延迟还没有测。"
PREMISE = "系统能自己判定连续失败"
REASON = "这次想把做法试着推广到所有值班通知。"
SOURCE_CLAIM = "操作员的合成样例，未经过值班记录核验。"

CANDIDATE = {"statement": STATEMENT, "kind": "experience_claim", "scope": [SCOPE],
             "premises": [PREMISE], "alternatives": ["把提醒留给人手"],
             "contradictions": [COUNTER], "unknowns": [UNKNOWN]}

REQUESTS: list[str] = []
REPLIES: list[dict] = []


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


CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, held: bool, detail: str = "") -> None:
    CHECKS.append((name, bool(held), detail))


class Walk:
    """One temporary library, driven through the standard CLI."""

    def __init__(self, base: str, root: Path) -> None:
        self.root = root
        self.home = root / "home"
        self.home.mkdir()
        self.db = root / "dojo.sqlite3"
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("DOJO_")}
        self.env.update({
            "HOME": str(self.home), "DOJO_DB": str(self.db),
            "DOJO_LLM_BASE_URL": base, "DOJO_LLM_MODEL": "loopback",
            "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1",
        })

    def cli(self, *args: str, stdin: str = "") -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-B", "-m", "dojo", *args],
                              cwd=str(ROOT), env=self.env, input=stdin, text=True,
                              capture_output=True, timeout=180)

    def traces(self) -> list[Path]:
        return sorted((self.root / "sessions").glob("*.jsonl"))


def opening_of(screen: str, stop: str = "你可以直接讲") -> str:
    """Only the part printed before the model's first reply.

    The point of this slice is that the person reads the conditions *before* deciding to
    trust the session, so a line appearing after the model spoke would not count.
    """
    return screen.split(stop, 1)[0]


def main() -> int:
    socket.setdefaulttimeout(10)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}/v1"
    temp = tempfile.TemporaryDirectory()
    walk = Walk(base, Path(temp.name))

    # ---- set up a card that came out of a discussion, with all four limits ----
    source = json.dumps({"id": "src-1", "type": "claimed_firsthand",
                         "verification": "unverified", "independence_group": "g1",
                         "claim": SOURCE_CLAIM, "scope_note": "两个班次都在同一个组"},
                        ensure_ascii=False)
    done = walk.cli("add", "--id", "c1", "--kind", "experience_claim",
                    "--statement", NARROWER, "--scope", SCOPE, "--premise", PREMISE,
                    "--alternative", "把提醒留给人手", "--contradiction", COUNTER,
                    "--unknown", UNKNOWN, "--source-json", source, "--session", "sess-one")
    check("建卡成功", done.returncode == 0, done.stderr[-200:])
    done = walk.cli("confirm", "c1", "--basis", "他在讨论里认可了这一版；不表示为真",
                    "--session", "sess-one")
    check("标记可讨论成功", done.returncode == 0, done.stderr[-200:])

    # A record that somebody accepted this exact content, which is what the screen has to
    # report instead of guessing from the status word.
    accepted = subprocess.run(
        [sys.executable, "-B", "-c",
         "import sys,json;from dojo.storage import Store;"
         "s=Store(sys.argv[1]);s.record_acceptance('c1','sess-one',"
         "path='discuss_conclusion');s.close()", str(walk.db)],
        cwd=str(ROOT), env=walk.env, text=True, capture_output=True, timeout=60)
    check("写入一条认可记录", accepted.returncode == 0, accepted.stderr[-300:])

    # ---- 1. the limits reach the person, before the model speaks ----
    REQUESTS.clear()
    REPLIES[:] = [{"answer": "接着说。", "candidate": None, "user_stance": "neutral"}]
    done = walk.cli("discuss", "--card", "c1", stdin="换了个团队，我想看看这条还成不成立\n")
    screen = done.stdout
    opening = opening_of(screen)
    request = REQUESTS[0] if REQUESTS else ""
    for label, value in (("什么时候成立", SCOPE), ("什么时候不成立", COUNTER),
                         ("还没定的是", UNKNOWN), ("它靠这些前提", PREMISE)):
        check("开场屏幕印出「" + label + "」", label in opening and value in opening)
        check("同样的「" + label + "」也发给了模型", value in request)
    check("来源记录说的是什么也印在屏幕上", SOURCE_CLAIM in opening)
    check("来源的自我限定也印在屏幕上", "两个班次都在同一个组" in opening)
    check("来源条数不是人数（那句限制还在）", "不是人数" in opening)
    check("另一条路不上开场屏幕（刻意的取舍）", "把提醒留给人手" not in opening)
    check("另一条路仍然发给模型", "把提醒留给人手" in request)

    # ---- 2. the status word does not assert an acceptance fact ----
    check("状态词不再声称没人认可", "还没有人认可" not in opening)
    check("认可记录按库里的事实印出", "库里有这套说法" in opening and "讨论里认可" in opening)
    # 认可 is reserved for the ledger's acceptance record. `confirm` is a different act and
    # writes no such record, so one screen carrying both facts must not use the word for
    # both -- the first version of this fix did, and read as a contradiction.
    check("可讨论的括号不冒用「认可」这个字", "有人认可它值得讨论" not in opening)
    check("可讨论说的是它自己那个动作", "标成值得讨论" in opening)

    # ---- 3. a doubt arrives as a limit, and is visible before the model speaks ----
    done = walk.cli("challenge", "c1", "--text", "第三个团队里更糟：提醒他根本没看")
    check("质疑写入成功", done.returncode == 0, done.stderr[-200:])
    REQUESTS.clear()
    REPLIES[:] = [{"answer": "这条被质疑过。", "candidate": None, "user_stance": "neutral"}]
    done = walk.cli("discuss", "--card", "c1", stdin="接着这条再想想\n")
    opening = opening_of(done.stdout)
    check("质疑原话在开场屏幕的「什么时候不成立」下面",
          "第三个团队里更糟：提醒他根本没看" in opening
          and "什么时候不成立" in opening)
    check("质疑之后，认可记录说的是「库里没有」而不是「没人认可」",
          "库里没有这套说法" in opening and "不等于没人认可过它" in opening)
    check("被质疑的卡不再说自己可讨论", "可讨论" not in opening)

    # ---- 3b. a card that stays `draft` while carrying an acceptance record ----
    #
    # The defect that started this slice was exactly this state: a conclusion agreed to
    # in conversation is `draft` until somebody marks it discussable, and the status word
    # used to read "这一句还没有人认可" over a ledger that said otherwise. The confirmed
    # card above cannot show it, because `confirm` moves the status to `discussable` --
    # an arm that restored the old draft wording stayed green until this card existed.
    draft_source = json.dumps({"id": "src-d2", "type": "claimed_firsthand",
                               "verification": "unverified", "independence_group": "g2",
                               "claim": "第二张样例，同样是合成材料"}, ensure_ascii=False)
    done = walk.cli("add", "--id", "c2", "--kind", "experience_claim",
                    "--statement", "交接班的提醒可以在群里挂半小时。",
                    "--scope", SCOPE, "--contradiction", COUNTER,
                    "--source-json", draft_source, "--session", "sess-two")
    check("建第二张卡（保持草稿）", done.returncode == 0, done.stderr[-200:])
    subprocess.run(
        [sys.executable, "-B", "-c",
         "import sys;from dojo.storage import Store;"
         "s=Store(sys.argv[1]);s.record_acceptance('c2','sess-two',"
         "path='discuss_conclusion');s.close()", str(walk.db)],
        cwd=str(ROOT), env=walk.env, text=True, capture_output=True, timeout=60)
    REQUESTS.clear()
    done = walk.cli("discuss", "--card", "c2", stdin="这条我熟\n")
    draft_opening = opening_of(done.stdout)
    check("草稿状态的卡仍印着「草稿」", "状态：草稿" in draft_opening, draft_opening[:80])
    check("草稿状态的卡不再说没人认可过它", "还没有人认可" not in draft_opening)
    check("草稿状态的卡照样印出认可记录", "库里有这套说法" in draft_opening)

    # ---- 3c. resume rebuilds that fact from the trace, not from the library ----
    draft_trace = next(
        path for path in walk.traces()
        if any(json.loads(line).get("event") == "handout"
               and json.loads(line).get("candidate") == "c2"
               for line in path.read_text(encoding="utf-8").splitlines())
    )
    REQUESTS.clear()
    REPLIES[:] = [{"answer": "继续。", "candidate": None, "user_stance": "neutral"}]
    done = walk.cli("discuss", "--resume", str(draft_trace), stdin="继续\n")
    check("续跑仍印出认可记录（从轨迹行重建）", "库里有这套说法" in done.stdout)
    check("续跑不说没人认可", "还没有人认可" not in done.stdout)

    # ---- 4. a revision reports the record, not a direction or an author ----
    done = walk.cli("revise", "c1", "--statement", STATEMENT, "--reason", REASON)
    check("改说法成功", done.returncode == 0, done.stderr[-200:])
    REQUESTS.clear()
    REPLIES[:] = [{"answer": "嗯。", "candidate": None, "user_stance": "neutral"}]
    done = walk.cli("discuss", "--card", "c1", stdin="这条现在更宽了\n")
    opening = opening_of(done.stdout)
    # This particular revision widened the claim, so a screen that says "narrower" is
    # stating something the ledger never recorded.
    # Named exactly, and the claim is the one this revision makes: it went from 只有普通
    # 日报才等到 值班通知都等，i.e. wider. A screen that says 窄 here is stating a
    # direction the `revise` row never records.
    for stale in ("它比更早那句窄", "比更早", "原来是", "他后来改主意时说的是"):
        check("开场不再印旧句式「" + stale + "」", stale not in opening)
    check("印出换掉的那句", NARROWER in opening)
    check("印出库里的改动理由", REASON in opening)
    check("改动理由不归给某个人", "改主意" not in opening and "他的理由" not in opening)

    # ---- 5. resume prints the same handout, rebuilt from the trace ----
    #
    # Chosen by the card the trace handed over, not by recency: two more sessions ran
    # between this one and the end of the script, and "the newest trace" silently became
    # the draft card's. That is exactly how a check starts measuring the wrong file while
    # staying green.
    trace = next(
        path for path in walk.traces()
        if any(json.loads(line).get("event") == "handout"
               and json.loads(line).get("candidate") == "c1"
               for line in path.read_text(encoding="utf-8").splitlines())
    )
    REQUESTS.clear()
    REPLIES[:] = [{"answer": "继续。", "candidate": None, "user_stance": "neutral"}]
    resumed = walk.cli("discuss", "--resume", str(trace), stdin="继续\n")
    resumed_opening = opening_of(resumed.stdout, stop="重新发送")
    if not resumed_opening.strip() or "这一场带上了" not in resumed.stdout:
        resumed_opening = resumed.stdout.split("你可以直接讲", 1)[0]
    for label, value in (("什么时候成立", SCOPE), ("还没定的是", UNKNOWN),
                         ("它靠这些前提", PREMISE)):
        check("续跑开场仍印出「" + label + "」", value in resumed.stdout)
    check("续跑开场不重复印「没人认可」", "还没有人认可" not in resumed.stdout)

    # ---- 6. the records themselves say what the screen said ----
    shown = json.loads(walk.cli("show", "c1").stdout)
    basis = shown.get("time_basis") or {}
    check("库里确实有这次改动的记录", bool((shown.get("revision_basis") or {}).get("reason")))
    check("改动后不再有内容绑定（质疑与改说法都撤了它）",
          basis.get("acceptance_path") is None)
    check("sentinel 用的边界字段都在库里",
          (shown["candidate"].get("contradictions") and shown["candidate"].get("scope")))

    # ---- report ----
    failures = [item for item in CHECKS if not item[1]]
    for name, held, detail in CHECKS:
        print(("  ok   " if held else "  FAIL ") + name + ("   " + detail if detail else ""))
    print()
    print(str(len(CHECKS)) + " 项检查：" + str(len(CHECKS) - len(failures)) + " 成立，"
          + str(len(failures)) + " 不成立。")
    print("用到的模型是本地回环桩，回答是写死的常量；这里量的是程序印了什么，"
          "不是模型的判断，也不是真人结果。")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
