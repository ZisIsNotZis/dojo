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
import shlex
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
# The stub proposes once; the next input approves the version shown on screen locally.
OPENING = ["聊一下值班提醒", "/认可"]
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
    reading("每条回答的 trace 是一个真存在、能打开的记录文件",
            bool(carried) and all(item.get("trace") and Path(item["trace"]).is_file()
                                  for item in carried.values()),
            json.dumps({key: item.get("trace") for key, item in carried.items()},
                       ensure_ascii=False))
    # On fdd55ff this field was `datetime.now().isoformat()`: a timestamp where a reader
    # expected a place, so the one thing it was for -- getting back to the session -- was
    # impossible (found in review). The screen has to turn it into a command that runs.
    back = dojo(["--db", str(db), "search", HIS_QUERY], env=env).stderr
    back_line = next((line.split("回看说这句的那一场：", 1)[1].strip()
                      for line in back.splitlines() if "回看说这句的那一场：" in line), "")
    reading("屏幕给每条原话印出回看那一场的命令", bool(back_line), back[:400])
    if back_line:
        # Pasted as printed, from a directory that is not the library's: the same test
        # #3419 established for every printed command.
        pasted = subprocess.run(shlex.split(back_line), cwd=str(root), env=env,
                                text=True, capture_output=True, timeout=120)
        reading("照抄那条命令能打开那一场，且里面有他的话",
                pasted.returncode == 0 and all(words in pasted.stdout
                                               for words in ANSWERS.values()),
                pasted.stderr[-400:])
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

    # ---- D1b: the way back survives moving the library ------------------------------
    # Review: with the library and `sessions/` moved together and the session directory
    # repointed, `search` still found the card and the answers were still on it, but the
    # freshly printed command pointed at the old directory and exited 2.
    heading("D1b. 库和 sessions 一起搬走之后，回看命令仍能打开")
    # A real move, not a copy: the old directory has to be gone, or the stored path still
    # works and the reading would be green for the wrong reason (my first version copied,
    # and the old path resolved). The library this scene uses is a dedicated one so the
    # earlier scenes are not disturbed.
    moved_root = root / "moved"
    moved_root.mkdir()
    moved_db = moved_root / "library.sqlite3"
    moved_sessions = moved_root / "sessions"
    shutil.copy2(db, moved_db)
    original_sessions = db.parent / "sessions"
    stashed: Path | None = None
    if original_sessions.is_dir():
        shutil.copytree(original_sessions, moved_sessions)
        # Hidden for the length of this reading, then restored: the stored absolute paths
        # must really be stale (a copy leaves them readable), and the later scenes need
        # this directory back.
        stashed = db.parent / "sessions-away"
        original_sessions.rename(stashed)
    moved_env = dict(env, DOJO_SESSIONS=str(moved_sessions))
    moved_screen = dojo(["--db", str(moved_db), "search", HIS_QUERY], env=moved_env).stderr
    moved_line = next((line.split("回看说这句的那一场：", 1)[1].strip()
                       for line in moved_screen.splitlines()
                       if "回看说这句的那一场：" in line), "")
    if moved_line:
        moved_run = subprocess.run(shlex.split(moved_line), cwd=str(root), env=moved_env,
                                   text=True, capture_output=True, timeout=120)
        reading("搬走之后屏幕上那条命令仍存在且能跑",
                Path(shlex.split(moved_line)[-1]).is_file() and moved_run.returncode == 0
                and all(words in moved_run.stdout for words in ANSWERS.values()),
                moved_run.stderr[-400:])
    else:
        reading("搬走之后屏幕上那条命令仍存在且能跑", False, "没有印出命令")
    if stashed is not None:
        stashed.rename(original_sessions)

    # ---- D1c: a relative session directory -------------------------------------------
    # Review: `DOJO_SESSIONS=meeting notes` is a normal thing to type, and the command
    # printed from it carried that relative path -- pasting it in another terminal opened
    # a different (or absent) directory and exited 2. A printed line has to mean one file
    # wherever it lands.
    heading("D1c. 会话目录写成相对路径时，打印出来的命令仍是绝对路径")
    from dojo import commands as commands_module  # noqa: E402
    relative_root = root / "relative-home"
    relative_root.mkdir()
    relative_record = relative_root / "meeting notes" / "discuss-abc.jsonl"
    relative_record.parent.mkdir()
    relative_record.write_text("{}\n", encoding="utf-8")
    previous_cwd = Path.cwd()
    previous_env = os.environ.get("DOJO_SESSIONS")
    try:
        os.chdir(relative_root)
        os.environ["DOJO_SESSIONS"] = "meeting notes"
        found, where = commands_module.locate_record("meeting notes/discuss-abc.jsonl", None)
    finally:
        os.chdir(previous_cwd)
        if previous_env is None:
            os.environ.pop("DOJO_SESSIONS", None)
        else:
            os.environ["DOJO_SESSIONS"] = previous_env
    reading("相对路径也解析成绝对路径", found is not None and found.is_absolute()
            and Path(found).is_file(), str(found))

    # ---- D2: the way back is promised only for a sentence that is really in the file --
    # Review: with the second answer's write failing, all four lines still said 回看说这句
    # 的那一场, and the command opened a record holding only the first answer. The trace is
    # broken the same way `tests/test_offtarget_receipt.py` breaks it -- at the file object,
    # which is the path a real OSError takes -- so the answers themselves still land on the
    # card and only the record loses them.
    heading("D2. 记录中途写不进去时，那条回看命令不再给出")
    broken_db = root / "broken.sqlite3"
    broken_env = dict(env, DOJO_SESSIONS=str(root / "broken-sessions"))
    REQUESTS.clear()
    REPLIES.extend([{"answer": "那我们把这句当成现在这一版。", "candidate": CONCLUSION,
                     "user_stance": "neutral"}])
    # In a child process, because `dojo(...)` here is a subprocess: a monkeypatch in this
    # interpreter would never reach the session under test (my first version of this scene
    # patched here and reported all four answers as recorded -- a green that proved nothing).
    # The failure is injected where a real one happens, at the file object's write path.
    breaker = (
        "import sys\n"
        "sys.path.insert(0, %r)\n"
        "from dojo import discuss as d\n"
        "from dojo.storage import Store\n"
        "real = d._SessionTrace.append\n"
        "kept = {'n': 0}\n"
        "def dying(self, value):\n"
        "    if value.get('event') == 'elicitation' and value.get('answer'):\n"
        "        kept['n'] += 1\n"
        "        if kept['n'] >= 2:\n"
        "            self._warn(OSError('no space left on device'))\n"
        "            return\n"
        "    real(self, value)\n"
        "d._SessionTrace.append = dying\n"
        "sys.exit(d.run_discuss(Store(%r), read_line=lambda prompt: input()))\n"
    ) % (str(ROOT), str(broken_db))
    broken = subprocess.run([sys.executable, "-c", breaker],
                            input="\n".join(OPENING + list(ANSWERS.values())) + "\n",
                            text=True, capture_output=True, env=broken_env, cwd=str(ROOT),
                            timeout=300)
    reading("记录写坏的那一场仍跑完了", broken.returncode == 0, broken.stderr[-600:])
    broken_cards = json.loads(dojo(["--db", str(broken_db), "list", "--history"],
                                   env=broken_env).stdout or "[]")
    broken_id = broken_cards[0]["id"] if broken_cards else ""
    broken_rows = (json.loads(dojo(["--db", str(broken_db), "show", broken_id],
                                   env=broken_env).stdout).get("answers") or {}) if broken_id else {}
    missing = [key for key, item in broken_rows.items() if item.get("recorded") == 0]
    reading("哪些回答真的没写进记录，是查文件看出来的", bool(missing), str({
        key: item.get("recorded") for key, item in broken_rows.items()}))
    broken_screen = dojo(["--db", str(broken_db), "search", "冷库温度报警"],
                         env=broken_env).stderr if broken_id else ""
    # The property is a match, not a count of zero: the first answer *is* in the file and
    # deserves its command; the rest are not. Every command printed must land on a record
    # that really contains the sentence printed above it -- that is what review found
    # broken, and it is the only version of this check that can tell the two apart.
    offered, unmatched, pending = 0, 0, None
    for line in broken_screen.splitlines():
        if "：「" in line and "他的话" not in line:
            pending = line.split("：「", 1)[1].split("」", 1)[0]
        elif "回看说这句的那一场：" in line and pending:
            offered += 1
            opened = subprocess.run(shlex.split(line.split("回看说这句的那一场：", 1)[1].strip()),
                                    text=True, capture_output=True, cwd=str(root), env=broken_env,
                                    timeout=120)
            if pending not in opened.stdout:
                unmatched += 1
    reading("每条回看命令打开的记录都真的有那句原话",
            offered > 0 and unmatched == 0, f"{offered} 条命令，{unmatched} 条对不上")
    reading("记录里没有的那几句，屏幕说出原因而不是给一条命令",
            "没有写进那一场的记录文件" in broken_screen, broken_screen[-700:])

    # ---- D3: the first upgrade of an old library, by two writers at once -------------
    # Review's finding: the column check ran outside the write lock, so two sessions
    # upgrading the same library both ran the ALTER and the second died on `duplicate
    # column name` -- losing that person's answer. The window is microseconds wide, so the
    # durable form of this is `tests/test_answers_upgrade.py` (two threads, a barrier);
    # this reading checks the same property end to end, that a read-only look changes no
    # byte and that an upgraded library keeps both answers.
    heading("D3. 旧库第一次升级：只读不改字节，两个写入都留下")
    old_db = root / "old.sqlite3"
    import sqlite3  # noqa: E402
    seed_store = Store(old_db)
    try:
        old_card = seed_store.add("旧库里的那张卡。", "abstract_idea", scope=["x"])["id"]
    finally:
        seed_store.close()
    connection = sqlite3.connect(old_db)
    connection.execute("DROP TABLE IF EXISTS answers")
    connection.executescript(
        "CREATE TABLE answers (candidate_id TEXT NOT NULL, field TEXT NOT NULL,\n"
        "    answer TEXT NOT NULL, session TEXT, at TEXT, question TEXT, trace TEXT,\n"
        "    promoted_at TEXT NOT NULL, PRIMARY KEY(candidate_id, field));")
    connection.commit()
    connection.close()
    old_bytes = old_db.read_bytes()
    look = Store(old_db, readonly=True)
    try:
        look.answers_for(old_card)
    finally:
        look.close()
    reading("只读回看旧库，一个字节都不改", old_db.read_bytes() == old_bytes,
            "bytes changed while looking")
    import threading  # noqa: E402
    outcomes: dict[str, object] = {}
    gate = threading.Barrier(2)

    def upgrade(part: str, answer: str, key: str) -> None:
        gate.wait()
        writer = Store(old_db)
        try:
            writer.promote_answers(old_card, [{"part": part, "answer": answer,
                                               "provenance": "discussion",
                                               "session": "s-1"}], session="s-1")
            outcomes[key] = None
        except Exception as exc:  # noqa: BLE001
            outcomes[key] = exc
        finally:
            writer.close()

    pair = [threading.Thread(target=upgrade, args=("situation", ANSWERS["situation"], "a")),
            threading.Thread(target=upgrade, args=("price", ANSWERS["price"], "b"))]
    for thread in pair:
        thread.start()
    for thread in pair:
        thread.join()
    reading("两个写入同时给旧库补列，都没有报错",
            outcomes == {"a": None, "b": None},
            str({key: repr(value) for key, value in outcomes.items()}))
    after = Store(old_db, readonly=True)
    try:
        both = after.answers_for(old_card)
    finally:
        after.close()
    reading("两条回答都留下来了", set(both) == {"situation", "price"}, str(sorted(both)))

    # ---- E: the flag that decides whether anything is kept --------------------------
    # `--no-trace` says the session keeps nothing. The card is a file on the same disk,
    # so the answers must not reach it either -- measured before this was fixed: the
    # receipt said 这场不留原文, no trace file existed, and `show` returned all four
    # sentences verbatim (`.scratch/3480/probe_notrace.py`, scene B).
    heading("E. 选了不留记录的一场，什么文件里都没有他的话")
    quiet_db = root / "quiet.sqlite3"
    quiet_sessions = root / "quiet-sessions"
    quiet_env = dict(env, DOJO_SESSIONS=str(quiet_sessions))
    REQUESTS.clear()
    REPLIES.extend([{"answer": "那我们把这句当成现在这一版。", "candidate": CONCLUSION,
                     "user_stance": "neutral"}])
    quiet = dojo(["--db", str(quiet_db), "discuss", "--no-trace"],
                 stdin_text="\n".join(OPENING + list(ANSWERS.values())) + "\n", env=quiet_env)
    quiet_receipt = next((line for line in quiet.stdout.splitlines()
                          if line.startswith("主持人> ") and "四件问完了" in line), "")
    print("回执：\n  " + (quiet_receipt or "（没有回执）"))
    reading("不留记录的一场正常跑完", quiet.returncode == 0, quiet.stderr[-600:])
    reading("回执说这场不留原文", "这场不留原文" in quiet_receipt, quiet_receipt)
    reading("回执说原话没有附到卡片上", "没有附到卡片上" in quiet_receipt, quiet_receipt)
    reading("回执没有说原话留在本场记录里", "留在本场记录" not in quiet_receipt, quiet_receipt)
    reading("盘上真的没有轨迹文件",
            not (quiet_sessions.exists() and any(quiet_sessions.iterdir())),
            str(quiet_sessions))
    quiet_cards = json.loads(dojo(["--db", str(quiet_db), "list", "--history"],
                                  env=quiet_env).stdout or "[]")
    quiet_id = quiet_cards[0]["id"] if quiet_cards else ""
    quiet_shown = json.loads(dojo(["--db", str(quiet_db), "show", quiet_id],
                                  env=quiet_env).stdout) if quiet_id else {}
    reading("show 读不到任何一条他的原话",
            quiet_shown.get("answers") in (None, {}),
            json.dumps(quiet_shown.get("answers"), ensure_ascii=False))
    # The sentences must not have leaked into the card itself either: the sentence, the
    # scope and the boundary fields are the pre-question ones.
    quiet_body = json.dumps(quiet_shown.get("candidate") or {}, ensure_ascii=False)
    # Review: the promise was wider than the code. The four answers are not attached (just
    # checked), but a card the person accepts is still written -- and its sentence may be
    # their own words tidied up. Saying "nothing is kept" was false, so the screen has to
    # say which is which before the person types a word.
    reading("开场就说清楚哪部分不存、哪部分仍会留下",
            "不保存会话原文" in quiet.stdout and "不会附到卡片上" in quiet.stdout
            and "卡片仍会像平常一样留在库里" in quiet.stdout, quiet.stdout[:600])
    reading("他的话也没有漏进卡片的句子或条件",
            not any(words in quiet_body for words in ANSWERS.values()), quiet_body[:300])
    # And a person who does want one kept can still say so, in a command they typed.
    if quiet_id:
        kept = dojo(["--db", str(quiet_db), "confirm", quiet_id, "--basis", "值得讨论"],
                    env=quiet_env)
        reading("（准备）能把那张卡标成可讨论", kept.returncode == 0, kept.stderr[-300:])
        pushed = dojo(["--db", str(quiet_db), "promote", quiet_id,
                       "--answer", "情境=" + ANSWERS["situation"]], env=quiet_env)
        after = json.loads(dojo(["--db", str(quiet_db), "show", quiet_id],
                                env=quiet_env).stdout)
        reading("显式 promote 之后那句才在卡上",
                (after.get("answers") or {}).get("situation", {}).get("answer")
                == ANSWERS["situation"], pushed.stderr[-300:])
        hand_row = (after.get("answers") or {}).get("situation") or {}
        # Review's finding: a session number typed into `promote` made the card claim a
        # `--no-trace` discussion that never happened. Provenance is stored, not guessed.
        reading("手工附上的那句记着自己的来源是手工，没有冒充那场讨论",
                hand_row.get("provenance") == "manual",
                json.dumps(hand_row, ensure_ascii=False))
        sessioned = dojo(["--db", str(quiet_db), "promote", quiet_id,
                          "--answer", "张力=盯现场的踏实感就只能选一个",
                          "--session", "s-hand"], env=quiet_env)
        typed = (json.loads(dojo(["--db", str(quiet_db), "show", quiet_id],
                                 env=quiet_env).stdout).get("answers") or {}).get("tension") or {}
        typed_screen = dojo(["--db", str(quiet_db), "search", "盯现场的踏实感"],
                            env=quiet_env).stderr
        reading("手工 promote 顺手给了会话号，也没有被说成一场 --no-trace 讨论",
                typed.get("provenance") == "manual"
                and "手工附上的" in typed_screen
                and "没有留下记录文件" not in typed_screen,
                typed_screen[:400] or sessioned.stderr[-300:])
        reading("手工附上的那句不带会话和时刻，也不假装有记录文件",
                not hand_row.get("session") and not hand_row.get("at")
                and not hand_row.get("trace"), json.dumps(hand_row, ensure_ascii=False))
        hand_screen = dojo(["--db", str(quiet_db), "search", "冷库温度报警"],
                           env=quiet_env).stderr
        reading("屏幕说这句是手工附上的，不是某场讨论里说的",
                "手工附上的" in hand_screen
                and "回看说这句的那一场" not in hand_screen, hand_screen[:400])
        quiet_hit = dojo(["--db", str(quiet_db), "search", "冷库温度报警"], env=quiet_env)
        reading("显式 promote 之后能用自己的话搜回它",
                any(row.get("id") == quiet_id
                    for row in json.loads(quiet_hit.stdout or "{}").get("results") or []),
                quiet_hit.stdout[:200])
    return finish()


def finish() -> int:
    failures = [item for item in READINGS if not item[1]]
    print("\n" + str(len(READINGS)) + " 项读数：" + str(len(READINGS) - len(failures))
          + " 成立，" + str(len(failures)) + " 不成立。")
    print("模型是本地回环桩，回答是写死的常量；这不是真人会话，也不是模型的判断。")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
