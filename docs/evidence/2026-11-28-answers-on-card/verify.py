"""Do the four answers a person gives ever reach the card they are about?

    python3 docs/evidence/2026-11-28-answers-on-card/verify.py [worktree]

One scene, all through `python3 -m dojo`, all offline (a loopback stub answers in this
file's constants; the constants are not a real session and not a model's judgement):

  A  a rule is agreed in a discussion and the four questions are answered with concrete
     sentences -- one condition with an occasion, one "another good thing I would lose",
     one "who pays", one "a time it went the other way";
  B  the person comes back and searches with the words *he* used for the failure. The card
     is found, the screen says the words came from his answer rather than the card's
     sentence, and it prints all four answers verbatim;
  C  a later session is opened on that card. Both what the person sees and what the model
     receives carry his answers, labelled as his words and not as the card's wording;
  D  the things that must NOT move: the sentence, its boundary fields, the card's version,
     the field authorship, independence, and the machine-facing search payload.

Before this slice, B and C could not happen at all: measured on the released build, four
concrete answers came back, the trace said `collected: true` for all four, the summary
said `系统补` for all six parts, and the receipt said 没有写进卡片. A later reader got the
model's boundary and none of his -- which is the one thing this product says it is for.

Exit 0 when every reading holds, 1 otherwise. No network beyond 127.0.0.1.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1
            else Path(__file__).resolve().parents[3]).resolve()

STATEMENT = "把持续检查交给系统跑，人只在结果会打断他时才被叫醒。"
WHEN = "他已经抽身、这条提醒的失败不会当场伤人时"
UNLESS = "提醒必须发生在值班当场、人来不及时接手时"
UNKNOWN = "他会不会来看回执"
PREMISE = "系统能自己跑检查"

CONCLUSION = {"statement": STATEMENT, "kind": "abstract_idea", "scope": [WHEN],
              "premises": [PREMISE], "alternatives": ["把检查留给人"],
              "contradictions": [UNLESS], "unknowns": [UNKNOWN]}

# One concrete answer per part, in the order `discuss` asks them. Each is the first thing
# he says for that question, so the mapping is 1:1 and a reading can name the part a
# sentence should have landed in.
ANSWERS = {
    "situation": "上周二夜里冷库温度报警，我已经回家了，手机响了我才回去",
    "tension": "盯现场的踏实感就只能选一个",
    "price": "负责夜班的两个同事要多花时间跑一趟",
    "off": "有一次系统没发出来，我在路上才发现，那次就不该靠它",
}
OPENING = ["聊一下值班提醒", "对，就这么定"]
# None of these three words appears in the card's own sentence, so a match on them can only
# have come from his answer -- which is what makes the search reading meaningful.
HIS_QUERY = "没发出来 路上 才发现"

REQUESTS: list[dict] = []
REPLIES: list[dict] = []
READINGS: list[tuple[str, bool, str]] = []


class Stub(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        try:
            REQUESTS.append(json.loads(body.decode("utf-8")))
        except (UnicodeDecodeError, json.JSONDecodeError):
            REQUESTS.append({})
        reply = REPLIES.pop(0) if REPLIES else {"answer": "嗯。", "candidate": None,
                                               "user_stance": "neutral"}
        encoded = json.dumps({
            "choices": [{"message": {"role": "assistant",
                                     "content": json.dumps(reply, ensure_ascii=False)},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, *arguments):
        pass


def reading(name: str, ok: bool, detail: object = "") -> None:
    READINGS.append((name, bool(ok), str(detail)))
    print(("OK    " if ok else "FAIL  ") + name + (("  —— " + str(detail)) if detail and not ok else ""))


def heading(text: str) -> None:
    print("\n" + text)


def clean_env(**extra: str) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("DOJO_") and not key.startswith("DEEPSEEK")}
    env["PYTHONPATH"] = str(ROOT)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.update(extra)
    return env


def dojo(argv: list[str], *, stdin_text: str = "", env: dict[str, str] | None = None):
    return subprocess.run([sys.executable, "-m", "dojo", *argv], input=stdin_text,
                          text=True, capture_output=True, cwd=str(ROOT),
                          env=env or clean_env(), timeout=300)


def main() -> int:
    REPLIES.extend([
        {"answer": "那我们把这句当成现在这一版。", "candidate": CONCLUSION,
         "user_stance": "neutral"},
        {"answer": "好，就这句。", "candidate": CONCLUSION, "user_stance": "accept"},
    ])
    server = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    root = Path(tempfile.mkdtemp(prefix="answers-on-card-"))
    db = root / "lib.sqlite3"
    env = clean_env(DOJO_LLM_BASE_URL=f"http://127.0.0.1:{port}/v1",
                    DOJO_LLM_MODEL="stub", DOJO_LLM_API_KEY="not-a-real-key",
                    DOJO_SESSIONS=str(root / "sessions"))
    try:
        return walk(db, env, root)
    finally:
        server.shutdown()
        shutil.rmtree(root, ignore_errors=True)


def walk(db: Path, env: dict[str, str], root: Path) -> int:
    # ---- A: the session -----------------------------------------------------------
    heading("A. 一场讨论，四件都答了")
    first = dojo(["--db", str(db), "discuss"],
                 stdin_text="\n".join(OPENING + list(ANSWERS.values())) + "\n", env=env)
    receipt = next((line for line in first.stdout.splitlines()
                    if line.startswith("主持人> ") and "四件问完了" in line), "")
    print("回执：\n  " + (receipt or "（没有回执）"))
    reading("这一场正常跑完", first.returncode == 0, first.stderr[-800:])
    reading("回执说他的原话现在附在卡片上了", "附在卡片" in receipt, receipt)
    reading("回执说卡片那句没有被改写成他的话",
            "没有改写成卡片的措辞" in receipt, receipt)

    cards = json.loads(dojo(["--db", str(db), "list", "--history"]).stdout or "[]")
    reading("这场写下了一张卡", len(cards) == 1, str(len(cards)))
    if len(cards) != 1:
        return finish()
    card = cards[0]["id"]
    shown = json.loads(dojo(["--db", str(db), "show", card]).stdout)
    carried = shown.get("answers") or {}
    reading("四件的原话都在卡上，各在自己的那一栏",
            {key: item.get("answer") for key, item in carried.items()} == ANSWERS,
            json.dumps({key: item.get("answer") for key, item in carried.items()},
                       ensure_ascii=False))
    reading("每条回答都带着它是哪个会话说的",
            all(item.get("session") for item in carried.values()),
            json.dumps(carried, ensure_ascii=False)[:300])
    reading("句子和边界字段仍是提问前那句，回答没有被写进措辞或条件",
            shown["candidate"]["statement"] == STATEMENT
            and shown["candidate"]["scope"] == [WHEN]
            and shown["candidate"]["contradictions"] == [UNLESS]
            and not any(words in json.dumps(shown["candidate"], ensure_ascii=False)
                        for words in ANSWERS.values()))
    reading("卡片的版本没有因为附上回答而变动（流水线标记不会被打回）",
            shown["candidate"]["version"] == 1, str(shown["candidate"]["version"]))

    # The trace is the record these sentences came from, so it has to agree.
    traces = sorted((root / "sessions").glob("*.jsonl"))
    rows = [json.loads(line) for line in traces[-1].read_text(encoding="utf-8").splitlines()
            if line.strip()] if traces else []
    end = [row for row in rows if row.get("event") == "session_end"]
    summary = (end[-1].get("elicitation") if end else {}) or {}
    reading("轨迹的总结说这四件都附上了",
            summary.get("promoted") == ["情境", "张力", "代价", "失效"],
            str(summary.get("promoted")))
    # `part_sources` answers a different question -- who wrote the *field* -- and it must
    # not claim he wrote a field he never wrote. This is the distinction the receipt draws.
    reading("字段的作者没有被冒认成他（part_sources 仍是系统补）",
            all(value == "系统补" for key, value in (summary.get("part_sources") or {}).items()
                if key in {"situation", "tension", "price", "off"}),
            str(summary.get("part_sources")))

    # ---- B: days later, in his own words -------------------------------------------
    heading("B. 过几天，用他自己说过的话去找")
    found = dojo(["--db", str(db), "search", HIS_QUERY])
    print(found.stderr)
    # `card in stderr` is too weak: the empty-result fallback lists recent cards, so the
    # id appears even when nothing matched. The hit has to be a *result*, which is what
    # stdout carries -- and the row has to say how many of his words it found.
    hit_rows = [row for row in json.loads(found.stdout or "{}").get("results") or []
                if row.get("id") == card]
    reading("用他的失效例子能找回这张卡",
            bool(hit_rows) and (hit_rows[0].get("score") or 0) >= 3,
            json.dumps(json.loads(found.stdout or "{}").get("results"),
                       ensure_ascii=False)[:400])
    reading("命中来自他的话，不是碰巧对上正文",
            "在附在这张卡上的你的原话里" in found.stderr, found.stderr[:300])
    reading("屏幕把他的回答逐字印出来",
            all(words in found.stderr for words in ANSWERS.values()),
            "缺：" + str([words for words in ANSWERS.values() if words not in found.stderr]))
    reading("屏幕说这些话不是卡片措辞的一部分",
            "不是这张卡措辞的一部分" in found.stderr, found.stderr[:300])
    published = json.loads(found.stdout or "{}")
    reading("命令行 stdout 仍是四个旧键（屏幕的键不进 stdout）",
            set(published) == {"query", "method", "matched_terms", "results"}, str(sorted(published)))
    reading("机器读的每一行没有多出屏幕用的键",
            all(not ({"answers", "matched_in", "matched_on", "matched_wording"}
                     & set(row)) for row in published.get("results") or []),
            str(sorted(set().union(*(set(row) for row in published.get("results") or [])))))

    # The model's reach did not grow: the same query with the flag off must not find the
    # card through his answers, or a person's own screen would be widening what a model
    # can retrieve without anyone choosing it.
    sys.path.insert(0, str(ROOT))
    from dojo.storage import Store  # noqa: E402  (proved importable by the CLI above)
    store = Store(db, readonly=True)
    try:
        plain = store.retrieve(HIS_QUERY)
        as_read = store.retrieve(HIS_QUERY, for_reading=True)
    finally:
        store.close()
    reading("给模型的那次检索没有因为回答而多出命中",
            [row["id"] for row in plain["results"]] == [], str(plain["results"]))
    reading("人的那次检索命中，且行里写明字在他的回答里",
            any(row["id"] == card and "answers" in (row.get("matched_in") or [])
                for row in as_read["results"]),
            json.dumps([{row["id"]: row.get("matched_in")} for row in as_read["results"]],
                       ensure_ascii=False))

    # ---- C: a later session opened on that card ------------------------------------
    heading("C. 后来的一场把这张卡带进讨论")
    REQUESTS.clear()
    REPLIES.extend([{"answer": "接着说。", "candidate": None, "user_stance": "neutral"}])
    later = dojo(["--db", str(db), "discuss", "--card", card],
                 stdin_text="再说说那条\n", env=env)
    sent = json.dumps(REQUESTS[0], ensure_ascii=False) if REQUESTS else ""
    opening = later.stdout.split("你> ", 1)[0]
    print(opening)
    reading("后来那一场正常跑完", later.returncode == 0, later.stderr[-600:])
    reading("开场屏幕上就有他的话",
            all(words in opening for words in ANSWERS.values()),
            "缺：" + str([words for words in ANSWERS.values() if words not in opening]))
    reading("开场说这些话不是这张卡措辞的一部分",
            "不是这张卡措辞的一部分" in opening, opening[-400:])
    reading("发给模型的请求里真的有他的话",
            bool(sent) and all(words in sent for words in ANSWERS.values()),
            "缺：" + str([words for words in ANSWERS.values() if words not in sent]))
    reading("发给模型时标明了这是他的话，不是卡片措辞，也不是对它的赞同",
            "不是它的措辞" in sent and "不是对它的赞同" in sent, sent[:400])

    # ---- D: what must not move ------------------------------------------------------
    heading("D. 不该动的没有动")
    reading("附上回答没有给它添一条来源（记录条数不变）",
            len(shown["candidate"]["sources"]) == 1,
            str(len(shown["candidate"]["sources"])))
    reading("卡的状态没有因为附上回答而变成可讨论",
            shown["candidate"]["status"] == "draft", shown["candidate"]["status"])
    return finish()


def finish() -> int:
    failures = [item for item in READINGS if not item[1]]
    print("\n" + str(len(READINGS)) + " 项读数：" + str(len(READINGS) - len(failures))
          + " 成立，" + str(len(failures)) + " 不成立。")
    print("模型是本地回环桩，回答是写死的常量；这不是真人会话，也不是模型的判断。")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
