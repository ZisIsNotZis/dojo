"""Walk the whole slice at the real entry: find a sentence you only half remember.

    python3 docs/evidence/2026-11-28-find-remembered/verify.py [worktree]

Five scenes, all through `python3 -m dojo`, all offline:

  A  a night-shift sentence is agreed in a discussion, and the library also holds a
     card that says the opposite about the same practice -- these are the two cards a
     person would confuse;
  B  somebody doubts the first one, and the same words are searched again: the screen
     must still show his card, say why retrieval will not hand it over, and print its
     conditions next to the card that argues with it;
  C  he types only the gist, in his own words, and no word overlaps: the screen says
     what it did (only words), and offers the newest cards as a different method;
  D  he remembers the wording a card used to have: the earlier sentence is findable,
     and the screen says it is not what the card says now;
  E  a topic the library never held: nothing is invented, and the recent-cards offer
     still says it is not a match by meaning.

Every model reply is a constant written in this file behind a loopback stub: **these
are not real sessions, not a real person's words, and not a model's judgement.** What
is measured is what the program printed and what it sent.

Exit 0 when every reading holds, 1 otherwise. No network beyond 127.0.0.1.
"""
from __future__ import annotations

import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1
            else Path(__file__).resolve().parents[3]).resolve()

# ---- the two cards a person would confuse -------------------------------------------
CLOSE = "冷库越限就立刻打电话叫醒负责人，不等第二次。"
CLOSE_WHEN = "越限会当场损坏货物、人来得及接手时"
CLOSE_UNLESS = "夜里越限只是温度探头抖一下、并不会真的坏货时"
SLOW = "值班通知交系统跑，只在结果会打断他时才叫醒他。"
SLOW_WHEN = "他已经抽身、这条提醒的失败不会当场伤人时"
SLOW_UNLESS = "提醒必须发生在值班当场、人来不及时接手时"
DOUBT = "第三个团队里更糟：提醒他根本没看"
GIST = "半夜别老把人叫起来"
ABSENT = "量子色动力学里的渐近自由"

CONCLUSION = {"statement": SLOW, "kind": "abstract_idea", "scope": [SLOW_WHEN],
              "premises": ["系统能自己跑检查"], "alternatives": ["把提醒留给人"],
              "contradictions": [SLOW_UNLESS], "unknowns": ["他会不会真的回来看提醒"]}

REQUESTS: list[str] = []
REPLIES: list[dict] = []
READINGS: list[tuple[str, bool, str]] = []
SCREENS: dict[str, str] = {}


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


def sqlite_tables(path: Path) -> set[str]:
    """The tables in a file, read by a separate connection so nothing is cached."""
    connection = sqlite3.connect(path)
    try:
        return {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        connection.close()


def _reads_rows(done: subprocess.CompletedProcess) -> int:
    """How many read rows `dojo reads` printed, from its JSON."""
    try:
        return len(json.loads(done.stdout).get("rows") or [])
    except ValueError:
        return -1


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

    def screen(args: tuple[str, ...], stdin: str = "") -> tuple[str, str, int]:
        done = cli(*args, stdin=stdin)
        return done.stdout, done.stderr, done.returncode

    # ---- A: the sentence is agreed, and the opposite card is in the same library ----
    heading("A. 一场讨论里认可一句值夜的边界，库里还有一条相反的")
    REQUESTS.clear()
    REPLIES[:] = [
        {"answer": "先把它写成一句带边界的话：" + SLOW, "candidate": CONCLUSION,
         "user_stance": "neutral"},
        {"answer": "记下了。", "candidate": CONCLUSION, "user_stance": "accept"},
        {"answer": "嗯。", "candidate": None, "user_stance": "neutral"},
        {"answer": "嗯。", "candidate": None, "user_stance": "neutral"},
        {"answer": "嗯。", "candidate": None, "user_stance": "neutral"},
        {"answer": "嗯。", "candidate": None, "user_stance": "neutral"},
    ]
    out, err, code = screen(("discuss",), stdin="提醒太多了，我想让系统盯着\n对，就是这个\n"
                            "他下班以后就不看群了\n团队就我们几个\n有一次半夜没人看\n就这些\n")
    if code:
        print(out[-1500:], err[-1500:])
        return 1
    # The id is read from what the session printed, and only from there: a fallback to
    # "the only card in the library" would silently verify a different card than the one
    # this session wrote (#3363 measured that class of mistake on the earlier slice).
    mine = None
    for line in out.splitlines():
        if "本场结论卡片 ID" in line or "卡片 ID" in line:
            # The id follows the label with no space, so it is found by its prefix
            # anywhere in the line rather than by splitting on whitespace.
            for piece in line.replace("、", " ").replace("：", " ").split():
                if piece.startswith("d-"):
                    mine = piece.rstrip("。，,.;；")
    if mine is None:
        print("第一场没有写出卡片；后面的场面无从谈起")
        print(out[-2000:])
        print(err[-2000:])
        return 1
    shown = json.loads(cli("show", mine).stdout)
    reading("第一场后库里有这套说法的认可记录",
            bool((shown.get("time_basis") or {}).get("accepted_at")),
            str((shown.get("time_basis") or {}).get("acceptance_path")))

    # The opposite card, through the same commands a person has.
    out, err, code = screen((
        "add", "--statement", CLOSE, "--kind", "application",
        "--scope", CLOSE_WHEN, "--contradiction", CLOSE_UNLESS,
        "--premise", "越限的后果会在几分钟内发生", "--id", "d-close",
    ))
    reading("相反的那条也写进了同一个库", code == 0, err[-200:])
    out, err, code = screen(("confirm", "d-close", "--basis", "值得讨论，不表示为真"))
    reading("它可讨论（所以检索会交出去）", code == 0, err[-200:])

    # ---- B: a doubt, then the same words again -------------------------------------
    heading("B. 有人质疑之后，用同样几个词再找一次")
    words = ("值班", "通知", "打电话")
    before_out, before_err, code = screen(("search", " ".join(words)))
    SCREENS["before"] = before_err
    reading("质疑前，这几个词同时找到两条（一条是被认可的，一条可讨论）",
            mine in before_err and "d-close" in before_err, before_err[:0])
    out, err, code = screen(("challenge", mine, "--text", DOUBT))
    reading("质疑写入成功", code == 0, err[-200:])

    after_out, after_err, code = screen(("search", " ".join(words)))
    SCREENS["after"] = after_err
    print(after_err)
    reading("同样的词仍然列出我那条（不是只剩相反那条）", mine in after_err)
    reading("屏幕上它那一行说了「不会把它当答案交出去」", "不会把它当答案交出去" in after_err)
    # The reason has to be inside the refusal sentence. "被人质疑过" alone is also the
    # status word in the card's first line, so a check for the bare phrase passed on a
    # tree where the refusal line had lost its reasons -- caught by this slice's own
    # `refusal-reason-not-on-the-screen` arm, which is why the parenthesis is asserted.
    reading("并且说了为什么：被人质疑过", "（这张卡被人质疑过）" in after_err)
    reading("质疑的原话印在它的「什么时候不成立」下面", DOUBT in after_err)
    reading("它的「什么时候成立」也印出来了", SLOW_WHEN in after_err)
    reading("相反那条也在，且它自己的条件也在",
            "d-close" in after_err and CLOSE_UNLESS in after_err)
    reading("没有说「没有一张卡的字和这些词重叠」", "没有一张卡的字和这些词重叠" not in after_err)
    # The refused line has to name the confusion it is refusing: "retrieval will not
    # hand it over" must not read as "the library does not have it". A bare substring
    # check for "库里没有它" would match its own denial, so the denial is asserted as the
    # exact sentence and the bare claim as absent.
    reading("并明说「这不等于库里没有它」", "这不等于库里没有它" in after_err)
    reading("没有把检索的拒绝说成库里的空缺", "这个库里没有它" not in after_err
            and "库里没有这张卡" not in after_err)

    # The command for the card in question, not merely the first one printed: the
    # ordering is by word overlap, so "first" is the opposite card's line whenever it
    # shares one more word. Selecting by id is what this reading is about.
    printed = [line for line in after_err.splitlines()
               if line.strip().startswith("带进一场新讨论：") and ("--card " + mine) in line]
    command = printed[0].split("：", 1)[1].strip() if printed else ""
    reading("给出的命令带绝对 --db 和这张卡的 id",
            command.startswith("python3 -m dojo --db ") and str(db) in command
            and ("--card " + mine) in command, command[-60:])

    # The printed command has to run, and the opening screen has to say what it is.
    REQUESTS.clear()
    REPLIES[:] = [{"answer": "嗯。", "candidate": None, "user_stance": "neutral"}]
    parts = command.split()
    run = subprocess.run([sys.executable, "-B"] + parts[1:] + ["--no-trace"],
                         cwd=str(root), env={**env, "DOJO_DB": str(root / "nope.sqlite3")},
                         input="", text=True, capture_output=True, timeout=180)
    opening = run.stdout.split("你可以直接讲", 1)[0]
    SCREENS["opening"] = opening
    reading("把那条命令原样执行，开场先印这张卡的状态", "被人质疑过" in opening, run.stderr[-200:])
    reading("开场也印出那句质疑（程序从库里读的）", DOUBT in opening)
    reading("命令拷到别的目录、换掉 DOJO_DB 也读同一个库",
            run.returncode == 0 and "d-close" not in opening, run.stderr[-200:])

    # ---- B2: the reader's terminal, not the script's ------------------------------
    heading("B2. 用相对路径指定库，再从另一个目录粘贴命令")
    elsewhere = root / "elsewhere"
    elsewhere.mkdir()
    relative = subprocess.run(
        [sys.executable, "-B", "-m", "dojo", "--db", "dojo.sqlite3", "search", "值班"],
        cwd=str(root), env=env, text=True, capture_output=True, timeout=180,
    )
    printed_here = [line for line in relative.stderr.splitlines()
                    if line.strip().startswith("带进一场新讨论：")]
    reading("用相对路径指定库时，屏幕给出的仍是绝对路径",
            bool(printed_here) and all(str(root / "dojo.sqlite3") in line for line in printed_here),
            printed_here[0][-60:] if printed_here else relative.stderr[-200:])
    pasted = printed_here[0].split("：", 1)[1].strip().split() if printed_here else []
    moved = subprocess.run([sys.executable, "-B"] + pasted[1:] + ["--no-trace"],
                           cwd=str(elsewhere), env=env, input="", text=True,
                           capture_output=True, timeout=180) if pasted else None
    reading("在那个命令里换到别的目录粘贴它，仍读得到同一张卡",
            moved is not None and moved.returncode == 0 and "d-" in moved.stdout,
            (moved.stderr[-200:] if moved is not None else "没有命令"))

    # ---- B3: a terminal reads the screen; a pipe gets the JSON -------------------
    heading("B3. 在终端上，再好看的屏幕也不该被 JSON 淹掉")
    import pty
    read_fd, write_fd = pty.openpty()
    terminal = subprocess.run(
        [sys.executable, "-B", "-m", "dojo", "--db", str(db), "search", "值班"],
        cwd=str(ROOT), env=env, text=True, timeout=180,
        stdin=subprocess.DEVNULL, stdout=write_fd, stderr=write_fd,
    )
    os.close(write_fd)
    chunks = []
    try:
        while True:
            try:
                chunk = os.read(read_fd, 65536)
            except OSError:
                break
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        os.close(read_fd)
    terminal_text = b"".join(chunks).decode("utf-8", "replace").replace("\r\n", "\n")
    SCREENS["terminal"] = terminal_text
    reading("终端上能读到屏幕", "在这个库里找：" in terminal_text)
    reading("终端上没有把整块 JSON 倒在屏幕上", '"matched_terms"' not in terminal_text)
    reading("终端上告诉读者 JSON 怎么拿", "json.tool" in terminal_text, terminal_text[-120:])
    piped = subprocess.run(
        [sys.executable, "-B", "-m", "dojo", "--db", str(db), "search", "值班"],
        cwd=str(ROOT), env=env, text=True, capture_output=True, timeout=180,
    )
    parsed_pipe = json.loads(piped.stdout) if piped.stdout.strip() else None
    reading("接管道时 stdout 仍是完整的 JSON（宿主脚本的入口不变）",
            isinstance(parsed_pipe, dict) and "results" in parsed_pipe,
            piped.stdout[:0])

    # ---- B4: a library that is not there is not an empty library -------------------
    heading("B4. 指到一个不存在的库")
    absent_db = root / "missing" / "nope.sqlite3"
    missing = subprocess.run(
        [sys.executable, "-B", "-m", "dojo", "--db", str(absent_db), "search", "值班"],
        cwd=str(ROOT), env=env, text=True, capture_output=True, timeout=180,
    )
    # The wording itself is asserted, not just "it failed": the read-only store refuses a
    # missing path too, with a message that recommends `seed` -- a command this screen's
    # reader did not ask for and should not be sent to. The refusal this slice owns says
    # search will not create a library.
    reading("不存在的库上检索会拒绝，而不是报成空结果",
            missing.returncode != 0 and absent_db.exists() is False
            and "检索不会替你建库" in missing.stderr, missing.stderr[-160:])
    reading("也没有把它说成「没有一张卡的字和这些词重叠」",
            "没有一张卡的字和这些词重叠" not in missing.stderr)

    # ---- B5: reading must not change the file it reads -----------------------------
    heading("B5. 只想看一眼，不能改动那个文件（权限、别人的库、读记录）")
    readable = root / "readonly.sqlite3"
    for command in (("add", "--statement", "值班通知交系统跑。", "--kind", "abstract_idea",
                     "--id", "d-ro"),
                    ("confirm", "d-ro", "--basis", "值得讨论")):
        subprocess.run([sys.executable, "-B", "-m", "dojo", "--db", str(readable), *command],
                       cwd=str(ROOT), env=env, text=True, capture_output=True, timeout=180)
    tables_before = sqlite_tables(readable)
    bytes_before = readable.read_bytes()
    readable.chmod(0o444)
    looked = subprocess.run([sys.executable, "-B", "-m", "dojo", "--db", str(readable),
                             "search", "值班"], cwd=str(ROOT), env=env, text=True,
                            capture_output=True, timeout=180)
    reading("对一个 0444 的库检索仍然成功", looked.returncode == 0, looked.stderr[-160:])
    reading("检索后文件权限仍是 0444", (readable.stat().st_mode & 0o777) == 0o444,
            oct(readable.stat().st_mode & 0o777))
    reading("只读文件的内容一个字节都没变", readable.read_bytes() == bytes_before)
    readable.chmod(0o644)
    # Same question on a writable library, where "no permission error" cannot be what
    # keeps the file unchanged: a search without --session must not create the read log.
    plain = root / "plain.sqlite3"
    for command in (("add", "--statement", "值班通知交系统跑。", "--kind", "abstract_idea",
                     "--id", "d-plain"),
                    ("confirm", "d-plain", "--basis", "值得讨论")):
        subprocess.run([sys.executable, "-B", "-m", "dojo", "--db", str(plain), *command],
                       cwd=str(ROOT), env=env, text=True, capture_output=True, timeout=180)
    plain_before = sqlite_tables(plain)
    subprocess.run([sys.executable, "-B", "-m", "dojo", "--db", str(plain), "search", "值班"],
                   cwd=str(ROOT), env=env, text=True, capture_output=True, timeout=180)
    reading("没有请求记阅读时，不建读记录表，也不改表结构",
            sqlite_tables(plain) == plain_before and "reads" not in sqlite_tables(plain),
            str(sorted(sqlite_tables(plain))))

    foreign = root / "foreign.sqlite3"
    connection = sqlite3.connect(foreign)
    connection.execute("CREATE TABLE stock(id INTEGER)")
    connection.commit()
    connection.close()
    before_bytes = foreign.read_bytes()
    refused = subprocess.run([sys.executable, "-B", "-m", "dojo", "--db", str(foreign),
                              "search", "值班"], cwd=str(ROOT), env=env, text=True,
                             capture_output=True, timeout=180)
    reading("指到别的应用的 SQLite 库时拒绝，而不是往里建表",
            refused.returncode == 2 and sqlite_tables(foreign) == {"stock"},
            str(sorted(sqlite_tables(foreign))))
    reading("那个文件的内容一个字节都没变", foreign.read_bytes() == before_bytes)

    # The log is the one write this command can make, and only when asked for.
    logged = root / "logged.sqlite3"
    for command in (("add", "--statement", "值班通知交系统跑。", "--kind", "abstract_idea",
                     "--id", "d-word"),
                    ("confirm", "d-word", "--basis", "值得讨论")):
        subprocess.run([sys.executable, "-B", "-m", "dojo", "--db", str(logged), *command],
                       cwd=str(ROOT), env=env, text=True, capture_output=True, timeout=180)
    subprocess.run([sys.executable, "-B", "-m", "dojo", "--db", str(logged),
                    "search", "值班", "--session", "reader-1"],
                   cwd=str(ROOT), env=env, text=True, capture_output=True, timeout=180)
    logged_reads = subprocess.run([sys.executable, "-B", "-m", "dojo", "--db", str(logged),
                                   "reads", "--id", "d-word"], cwd=str(ROOT), env=env,
                                  text=True, capture_output=True, timeout=180)
    reading("点名了一个读者时，阅读才被记进账本",
            _reads_rows(logged_reads) == 1, logged_reads.stderr[-160:])

    # ---- C: only the gist ----------------------------------------------------------
    heading("C. 只记得大意，说的词库里一个都没有")
    gist_out, gist_err, code = screen(("search", GIST))
    SCREENS["gist"] = gist_err
    print(gist_err)
    reading("没有字词重叠时，屏幕说清方法：只比字词，不认意思",
            "只比字词，不认意思" in gist_err)
    reading("没有把它说成「库里没有这句」", "库里没有这句" not in gist_err)
    reading("给出另一个办法：最近写下的卡", "最近写下的" in gist_err)
    reading("并说明那不是按意思找的", "不是按意思找出来的" in gist_err)
    reading("最近那几张里能看到我这条", mine in gist_err)
    reading("程序不替我认定哪条是你要找的", "由你看" in gist_err and "不替你挑" in gist_err)

    # ---- D: the wording it used to have -------------------------------------------
    heading("D. 记得的是它换掉之前那句话")
    out, err, code = screen(("add", "--statement", "只有普通日报才等两次失败再呼叫负责人。",
                             "--kind", "application", "--id", "d-report"))
    reading("再写一条日报卡", code == 0, err[-200:])
    out, err, code = screen(("confirm", "d-report", "--basis", "值得讨论"))
    # The new sentence deliberately drops the word 日报: the point of this scene is that
    # the *earlier* wording can be found even when it shares nothing with the current
    # one. A rewrite that keeps most of the words would be findable without this slice's
    # fix and would make the reading -- and its red arm -- meaningless (this slice's
    # `earlier-wording-unsearchable` arm went green on exactly that, first try).
    out, err, code = screen(("revise", "d-report",
                             "--statement", "值班通知一律先等两次失败再呼叫负责人。",
                             "--reason", "想把做法推广到所有值班通知。"))
    reading("它换过一次说法", code == 0, err[-200:])
    # The words have to be ones ONLY the earlier sentence holds. "等两次失败再呼叫负责人"
    # survives the rewrite, so a query built from it is found without this slice's fix and
    # the reading -- and its arm -- proved nothing on the first two attempts. 只有普通日报
    # is in the old sentence and in no bigram of the new one.
    out, err, code = screen(("search", "只有普通日报"))
    SCREENS["earlier"] = err
    print(err)
    # It is not enough for the id to appear: when nothing overlaps, the no-hit fallback
    # also lists the newest cards, so `d-report in err` was true on the old code and this
    # arm stayed green twice. What has to be true is that the *words* matched it.
    by_words = [line for line in err.splitlines() if line.startswith("1. d-report") and "对上" in line]
    reading("用换掉之前那句还能找到它", bool(by_words)
            and "张卡的字和这些词重叠" in err, by_words[0] if by_words else err[:0])
    # The supervisor read the first version on a terminal: the current sentence sat ABOVE
    # the note, and the note said "下面这句是它现在的说法" -- pointing the reader back at
    # the note. A direction word is a claim about layout; the note now names the entry's
    # opening sentence instead, and this reading refuses both direction words.
    reading("旧说法那条注不说「上面」「下面」",
            "本条目开头引的那句" in err and "下面这句" not in err and "在上面" not in err)
    # "以前的说法" alone also appears in a refusal reason ("有人认可过它以前的说法"),
    # so the check names the line this slice added. This arm went green before the fix.
    reading("屏幕说这是它以前的说法", "你记得的字对上的是它以前的说法" in err and "只有普通日报" in err)
    reading("同时给出它现在的说法", "值班通知一律先等两次失败" in err)

    reading("同时给出它现在的说法", "值班通知一律先等两次失败" in err)

    # ---- D2: the words were found, but not in the sentence -------------------------
    # Measured at 560a07d, three ways, all one defect: the screen told the reader the
    # *sentence* matched when the words came from somewhere else. An entry reading
    # "对上 8 个词：会当、场损…" over a sentence sharing none of them is the reader's
    # "this is what I remember" being false with no line saying so.
    heading("D2. 字对上了，但不在那句话里")
    out, err, code = screen(("add", "--statement", "值班通知交系统跑。", "--kind", "abstract_idea",
                             "--id", "d-cond", "--scope", "越限会当场损坏货物时"))
    reading("写一条句子和条件无关的卡", code == 0, err[-200:])
    screen(("confirm", "d-cond", "--basis", "值得讨论"))
    # The query is the card's *condition*, verbatim. The sentence shares no bigram with it.
    out, cond_err, code = screen(("search", "越限会当场损坏货物"))
    SCREENS["condition"] = cond_err
    print(cond_err)
    # Selected by id, not by position: this library already holds the d-close card from
    # scene A, whose *own* condition also says 越限会当场损坏货物, so the entry for this
    # card is not necessarily the first line. The first version of this reading asked for
    # `1. d-cond` and went red for that reason, not for the defect.
    cond_entry = cond_err.split("d-cond", 1)[-1]
    cond_entry = cond_entry.split("\n\n", 1)[0]
    reading("条件里的字对上时，屏幕不把这句当成对上的那句",
            "d-cond" in cond_err and "你记得的字不在本条目开头引的那句里" in cond_entry,
            cond_entry[:200])
    reading("并说清字在哪个部分（条件或反例）", "它写的条件或反例" in cond_err)
    out, same_err, code = screen(("search", "值班通知交系统跑"))
    reading("那句话自己对上时不印这条注", "你记得的字不在本条目开头引的那句里" not in same_err)

    # An alias is another wording of the same claim. At 560a07d it reported itself as
    # `current`, so the screen printed no note at all -- the reader was told the sentence
    # matched when it shared 0 bigrams and the alias shared 5 (measured).
    out, err, code = screen(("add", "--statement", "值班通知交系统跑，只在结果会打断他时才叫醒他。",
                             "--kind", "abstract_idea", "--id", "d-alias"))
    screen(("confirm", "d-alias", "--basis", "值得讨论"))
    out, err, code = screen(("alias", "d-alias", "--wording", "冷库越限就立刻打电话叫醒负责人。",
                             "--reason", "换场景的说法"))
    reading("给这张卡加一种说法（alias）", code == 0, err[-200:])
    out, alias_err, code = screen(("search", "冷库越限打电话"))
    SCREENS["alias"] = alias_err
    print(alias_err)
    reading("别名对上时，不谎称卡片现在那句对上",
            "卡片现在写的那句和这些词没有重叠" in alias_err)
    reading("并把对上的那种说法原样印出来",
            "冷库越限就立刻打电话叫醒负责人。" in alias_err)

    # Ordering: at 560a07d both cards scored 16 and id order put the one that only
    # *quotes* the sentence above the one that says it.
    screen(("add", "--statement", "值班通知只在结果会打断他时才叫醒他，其余交系统跑。",
            "--kind", "abstract_idea", "--id", "d-says", "--scope", "他已经抽身时"))
    screen(("confirm", "d-says", "--basis", "值得讨论"))
    screen(("add", "--statement", "冷库越限先发消息。", "--kind", "application", "--id", "d-quotes",
            "--scope", "值班通知只在结果会打断他时才叫醒他，其余交系统跑，并且失败不会当场伤人"))
    screen(("confirm", "d-quotes", "--basis", "值得讨论"))
    out, order_err, code = screen(("search", "值班通知只在结果会打断他时才叫醒他"))
    SCREENS["order"] = order_err
    print(order_err)
    first = next((line for line in order_err.splitlines() if line.startswith(("1. d-", "2. d-"))), "")
    reading("说这句话的卡排在那张只引用了它的卡前面",
            first.startswith("1. d-says"), first or order_err[:0])
    reading("屏幕自己说了这个顺序", "本条目写的那句先排" in order_err)
    heading("E. 库里从来没有过的题目")
    absent_out, absent_err, code = screen(("search", ABSENT))
    SCREENS["absent"] = absent_err
    print(absent_err)
    reading("没有字词重叠时如实说", "没有一张卡的字和这些词重叠" in absent_err)
    reading("没有凭空造出一条命中", ABSENT not in absent_err.split("在这个库里找：", 1)[-1].split("\n", 1)[-1])
    reading("最近卡片仍然标明不是按意思找的", "不是按意思找出来的" in absent_err)

    # ---- F: the JSON stays the contract the model sees -----------------------------
    heading("F. 机器读的那一面没有被屏幕改变")
    payload = json.loads(absent_out)
    reading("stdout 仍是 JSON（这次读是在同一命令上的另一次运行）",
            isinstance(payload.get("results"), list))
    model_out, model_err, code = screen(("search", "值班"))
    # The row keys have to be compared whole, not by naming the keys we remember adding.
    # The supervisor caught `matched_in` on stdout by piping the output into a program:
    # this section checked `set(published) == {four keys}` and then looked for two named
    # keys per row, so a new reading key sailed through both. Now the published row is
    # compared to the row the model-facing call returns for the same card -- the
    # definition of "unchanged", rather than a list that has to be kept in step by hand.
    hit_out, hit_err, code = screen(("search", "值班通知只在结果会打断他时才叫醒他"))
    hits = json.loads(hit_out)
    reading("同一组词同时命中正文和条件两张卡",
            {row["id"] for row in hits["results"]} >= {"d-says", "d-quotes"},
            str(sorted(row["id"] for row in hits["results"])))
    reading("命令行 stdout 仍是四个旧键（屏幕的键不进 stdout）",
            set(hits) == {"query", "method", "matched_terms", "results"})
    sys.path.insert(0, str(ROOT))
    from dojo.storage import Store as _Store  # noqa: E402  (proved importable above)
    store = _Store(db, readonly=True)
    try:
        plain_hits = store.retrieve("值班通知只在结果会打断他时才叫醒他")
        plain = store.retrieve("值班")
        shipped = json.dumps(plain, sort_keys=True)
    finally:
        store.close()
    model_rows = {row["id"]: row for row in plain_hits["results"]}
    published_rows = {row["id"]: row for row in hits["results"]}
    reading("两条命中的 stdout 每行与给模型的那行逐键相同",
            published_rows.keys() == model_rows.keys()
            and all(published_rows[key] == model_rows[key] for key in published_rows),
            "stdout 多出的键：" + str(sorted(
                set().union(*(set(row) for row in published_rows.values()))
                - set().union(*(set(row) for row in model_rows.values()))))
            if published_rows and model_rows else "没有行可比")
    sys.path.insert(0, str(ROOT))
    reading("给模型的那次检索仍只有四个键",
            set(plain) == {"query", "method", "matched_terms", "results"}, shipped[:0])
    reading("给模型的每一行也没有多出屏幕用的键",
            all("matched_on" not in row and "refused" not in row and "matched_in" not in row
                for row in plain["results"]))

    failures = [item for item in READINGS if not item[1]]
    print("\n" + str(len(READINGS)) + " 项读数：" + str(len(READINGS) - len(failures))
          + " 成立，" + str(len(failures)) + " 不成立。")
    print("模型是本地回环桩，回答是写死的常量；这不是真人会话，也不是模型的判断。")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
