#!/usr/bin/env python3
"""Does every command this program prints work when pasted, on the library it used?

    python3 docs/evidence/2026-11-28-printed-commands/verify.py

Offline: a loopback HTTP server stands in for the model, so nothing leaves the machine.
The library path deliberately carries a space, a single quote, `$` and a backtick -- the
characters that turn a printed command into a different command.

Each check prints what it measured. Exit 0 when every one holds, 1 otherwise.
"""
from __future__ import annotations

import json
import os
import shlex
import socket
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
# The checks below ask the program's own renderer what it prints; running this script
# directly means the repository root is not on the path yet.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CARD = "持续检查交给系统自己跑，但只在检查结果会打断他时才叫醒他。"
CONCLUSION = {
    "statement": CARD, "kind": "abstract_idea",
    "scope": ["他已经抽身的时候"], "premises": ["系统能自己跑检查"],
    "alternatives": ["把检查留给人"], "contradictions": ["检查必须发生在世界里时"],
    "unknowns": ["他会不会来看回执"],
}
REPLIES: list[dict] = []


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        body = json.dumps({
            "choices": [{"message": {"role": "assistant",
                                     "content": json.dumps(REPLIES.pop(0), ensure_ascii=False)},
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


def shell_words(command: str) -> list[str] | None:
    """The command as a shell would split it, or None when it cannot be split.

    A printed line that does not close its quotation is a *failed check*, and the reader
    should be told which line and why. Letting `shlex` raise would end the whole run at
    that line and hide every check after it -- measured on the arm that removes quoting.
    """
    try:
        return shlex.split(command)
    except ValueError:
        return None


def commands_detail(tokens: list[str] | None, line: str) -> str:
    """What to print beside a check on one printed command."""
    if tokens is None:
        return "这条命令引号没闭合，shell 分不开：" + line
    if "--db" not in tokens:
        return "没有 --db：" + line
    return "库参数：" + tokens[tokens.index("--db") + 1]


def printed_commands(text: str) -> list[str]:
    found = []
    for line in text.splitlines():
        if "python3 -m dojo" not in line:
            continue
        command = line[line.index("python3 -m dojo"):]
        if "（" in command:
            command = command.split("（", 1)[0]
        found.append(command.strip().rstrip("。"))
    return found


class Checks:
    def __init__(self, root: Path, env: dict, home: Path, default_db: Path,
                 library: Path, cli, paste) -> None:
        self.root = root
        self.env = env
        self.home = home
        self.default_db = default_db
        self.tear_down = lambda: None
        self.default_snapshot = self._default_bytes()
        self.library = library
        self.cli = cli
        self.paste = paste
        self.screens: list[tuple[str, str]] = []
        self.failures: list[str] = []
        self.checks = 0

    def remember(self, label: str, text: str) -> str:
        """Keep a screen so the final sweep can read every command on it."""
        self.screens.append((label, text))
        return text

    # -- helpers --------------------------------------------------------------

    def _default_bytes(self):
        return self.default_db.read_bytes() if self.default_db.is_file() else None

    def check(self, label: str, condition: bool, detail: str) -> None:
        self.checks += 1
        print(("  成立  " if condition else "  不成立 ") + label)
        print("        " + detail)
        if not condition:
            self.failures.append(label)

    def session(self, *extra):
        REPLIES[:] = [{"answer": "那我们把这句当成现在这一版。",
                       "candidate": CONCLUSION, "user_stance": "neutral"}]
        done = self.cli("--db", str(self.library), "discuss", "--card", "c1",
                        *extra, stdin="我想接着说\n")
        assert done.returncode == 0, done.stdout + done.stderr
        self.remember("early exit" + (" --no-trace" if "--no-trace" in extra else ""),
                      done.stdout)
        return done

    # -- A0. the receipt that follows the four questions ----------------------

    def a0_question_receipt(self):
        """The other exit line: the receipt printed after the four questions.

        A session that ends early prints a card command; one that gets through all four
        questions prints this receipt instead, and it names the read-back view in a
        sentence of its own. Both are exit lines a reader copies, so both are measured
        here (#3419: the earlier slice only checked the early exit).
        """
        REPLIES[:] = [
            {"answer": "那我们把这句当成现在这一版。", "candidate": CONCLUSION,
             "user_stance": "neutral"},
        ]
        stdin = "\n".join(["我想接着上次那张卡继续想", "/认可",
                           "那天我把检查交出去了", "我少了判断的机会",
                           "没人再复核", "没有。"]) + "\n"
        done = self.cli("--db", str(self.library), "discuss", "--card", "c1", stdin=stdin)
        self.remember("four-question receipt", done.stdout)
        receipt = [line for line in done.stdout.splitlines()
                   if line.startswith("主持人> ") and "四件问完了" in line]
        self.check("A0a 四件问完后印出了回执", bool(receipt),
                   receipt[0][:120] if receipt else done.stdout[-300:])
        if not receipt:
            return
        commands_here = printed_commands(receipt[0])
        self.check("A0b 回执点名了回看命令", bool(commands_here),
                   commands_here[0] if commands_here else "回执里没有命令")
        if not commands_here:
            return
        tokens = shell_words(commands_here[0])
        self.check("A0c 回执里的回看命令带着这一场的库",
                   tokens is not None and "--db" in tokens
                   and tokens[tokens.index("--db") + 1] == str(self.library),
                   commands_here[0] if tokens is not None
                   else "这条命令引号没闭合，shell 分不开：" + commands_here[0])
        pasted = self.paste(commands_here[0])
        self.check("A0d 粘贴回执里的命令能读回原话",
                   pasted.returncode == 0 and "没人再复核" in pasted.stdout,
                   "exit=%d" % pasted.returncode)

    # -- A. a session that keeps a trace --------------------------------------

    def a_exit_commands(self):
        done = self.session()
        card = [c for c in printed_commands(done.stdout) if " show " in c]
        self.check("A1 退出屏幕点名了打开草稿的命令", bool(card),
                   card[0] if card else "屏幕上没有 show 命令")
        if not card:
            return
        tokens = shell_words(card[0])
        self.check("A2 那条命令带着这一场的库，且能被 shell 分成一个参数",
                   tokens is not None and "--db" in tokens
                   and tokens[tokens.index("--db") + 1] == str(self.library),
                   commands_detail(tokens, card[0]))
        pasted = self.paste(card[0])
        self.check("A3 原样粘贴能打开草稿",
                   pasted.returncode == 0 and '"candidate"' in pasted.stdout,
                   "exit=%d" % pasted.returncode)
        self.check("A4 粘贴后默认库仍不存在", self._default_bytes() == self.default_snapshot,
                   "默认库：" + ("不存在" if self._default_bytes() is None else "多出来了"))

        back = [c for c in printed_commands(done.stdout) if " transcript " in c]
        words = shell_words(back[0]) if back else None
        self.check("A5 退出屏幕点名了回看命令，且带着同一个库",
                   words is not None and len(words) > 4 and words[4] == str(self.library),
                   back[0] if back else "没有 transcript 命令")
        if not back:
            return
        view = self.paste(back[0])
        self.check("A6 粘贴回看命令能读回原话",
                   view.returncode == 0 and "我想接着说" in view.stdout,
                   "exit=%d" % view.returncode)
        inner = printed_commands(view.stdout)
        shows = [c for c in inner if " show " in c]
        self.check("A7 回看里的卡片命令也带着那个库",
                   bool(shows) and (shell_words(shows[0]) or []) and
                   "--db" in shell_words(shows[0]),
                   shows[0] if shows else "回看里没有 show 命令")
        if shows:
            opened = self.paste(shows[0])
            self.check("A8 回看里的卡片命令粘贴后打开草稿",
                       opened.returncode == 0 and '"candidate"' in opened.stdout,
                       "exit=%d" % opened.returncode)
        resumes = [c for c in inner if " --resume " in c]
        self.check("A9 接着谈的命令也带着那个库",
                   bool(resumes) and "--db" in (shell_words(resumes[0]) or []),
                   resumes[0] if resumes else "回看里没有 --resume 命令")

        trace = sorted((self.library.parent / "sessions").glob("*.jsonl"))[-1]
        raw = trace.read_text(encoding="utf-8")
        self.check("A10 库路径没有写进原话记录",
                   str(self.library) not in raw and self.library.name not in raw,
                   "轨迹 %s：%d 字节" % (trace.name, len(raw.encode())))
        self.check("A11 全程默认库仍不存在", self._default_bytes() == self.default_snapshot,
                   "默认库：" + ("不存在" if self._default_bytes() is None else "多出来了"))

    # -- B. a session that keeps no trace -------------------------------------

    def b_no_trace(self):
        done = self.session("--no-trace")
        card = [c for c in printed_commands(done.stdout) if " show " in c]
        self.check("B1 不开轨迹时退出屏幕仍点名打开草稿的命令", bool(card),
                   card[0] if card else "屏幕上没有 show 命令")
        if not card:
            return
        tokens = shell_words(card[0])
        self.check("B2 那条命令带着这一场的库，且能被 shell 分成一个参数",
                   tokens is not None and "--db" in tokens
                   and tokens[tokens.index("--db") + 1] == str(self.library),
                   commands_detail(tokens, card[0]))
        pasted = self.paste(card[0])
        self.check("B3 原样粘贴能打开草稿",
                   pasted.returncode == 0 and '"candidate"' in pasted.stdout,
                   "exit=%d" % pasted.returncode)
        self.check("B4 不开轨迹时不点名回看命令",
                   not [c for c in printed_commands(done.stdout) if " transcript " in c],
                   "本场没有记录可看")
        self.check("B5 默认库仍不存在", self._default_bytes() == self.default_snapshot,
                   "默认库：" + ("不存在" if self._default_bytes() is None else "多出来了"))

    # -- B2. the same lines, pasted from another directory -------------------

    def b_relative_env(self):
        """`DOJO_DB` is a *relative* path, and the reader changes directory.

        Measured by the supervisor on c9f3fa2: in A with `DOJO_DB=chosen.sqlite3` the exit
        line printed `python3 -m dojo show d-...`; pasted in B that read B/chosen.sqlite3,
        exited 2, and created an empty library there. Same environment, different
        directory, different file -- so a relative `DOJO_DB` is never "already right".
        """
        where = self.root / "relative"
        first, second = where / "A", where / "B"
        for path in (first, second):
            path.mkdir(parents=True)
        env = dict(self.env)
        env["DOJO_DB"] = "chosen.sqlite3"

        def run_in(cwd, argv, stdin=""):
            return subprocess.run(argv, cwd=str(cwd), env=env, input=stdin, text=True,
                                  capture_output=True, timeout=180)

        def cli_in(cwd, *args, stdin=""):
            return run_in(cwd, [sys.executable, "-B", "-m", "dojo", *args], stdin)

        for args in (("add", "--id", "c1", "--kind", "abstract_idea",
                      "--statement", CARD, "--scope", "他已经抽身的时候",
                      "--premise", "系统能自己跑检查"),
                     ("confirm", "c1", "--basis", "他在会话里认可了这句；不表示为真",
                      "--session", "sess-A")):
            cli_in(first, *args)
        REPLIES[:] = [{"answer": "那我们把这句当成现在这一版。",
                       "candidate": CONCLUSION, "user_stance": "neutral"}]
        done = cli_in(first, "discuss", "--card", "c1", stdin="我想接着说\n")
        self.check("B2a 相对 DOJO_DB 下也能开场", done.returncode == 0,
                   "exit=%d" % done.returncode)
        if done.returncode:
            return

        shows = [c for c in printed_commands(done.stdout) if " show " in c]
        lines = (shell_words(shows[0]) or []) if shows else []
        named = lines[lines.index("--db") + 1] if "--db" in lines else None
        self.check("B2b 退出命令写的是绝对路径（不是靠相对 DOJO_DB）",
                   named is not None and named.startswith(str(first)),
                   (shows[0] if shows else "屏幕上没有 show 命令")
                   + ("（没有 --db）" if shows and named is None else ""))
        stray = second / "chosen.sqlite3"
        for command in shows:
            result = run_in(second, ["sh", "-c", command])
            self.check("B2c 换到另一个目录粘贴，仍打开那个草稿",
                       result.returncode == 0 and '"candidate"' in result.stdout,
                       "exit=%d" % result.returncode)
        self.check("B2d 换目录粘贴没有在那里新建库", not stray.is_file(),
                   str(stray))

        back = [c for c in printed_commands(done.stdout) if " transcript " in c]
        view = run_in(second, ["sh", "-c", back[0]]) if back else None
        self.check("B2e 回看也在另一个目录里可用",
                   bool(view) and view.returncode == 0 and "我想接着说" in view.stdout,
                   ("exit=%d" % view.returncode) if view else "没有回看命令")
        if view and view.returncode == 0:
            resumes = [c for c in printed_commands(view.stdout) if " --resume " in c]
            self.check("B2f 续谈命令带着同一个库",
                       bool(resumes) and str(first) in resumes[0],
                       resumes[0] if resumes else "回看里没有续谈命令")


    def b_relative_sessions(self):
        """`DOJO_SESSIONS` relative: the trace path a printed line names must survive a
        `cd` too. It is the same class as the library path and was fixed the same way."""
        where = self.root / "relative-sessions"
        first, second = where / "A", where / "B"
        for path in (first, second):
            path.mkdir(parents=True)
        env = dict(self.env)
        env["DOJO_SESSIONS"] = "sessions"
        library = first / "dojo.sqlite3"
        env["DOJO_DB"] = str(library)

        def cli_in(cwd, *args, stdin=""):
            return subprocess.run([sys.executable, "-B", "-m", "dojo", *args],
                                  cwd=str(cwd), env=env, input=stdin, text=True,
                                  capture_output=True, timeout=180)

        for args in (("add", "--id", "c1", "--kind", "abstract_idea",
                      "--statement", CARD, "--scope", "他已经抽身的时候",
                      "--premise", "系统能自己跑检查"),
                     ("confirm", "c1", "--basis", "他在会话里认可了这句；不表示为真",
                      "--session", "sess-A")):
            cli_in(first, *args)
        REPLIES[:] = [{"answer": "那我们把这句当成现在这一版。",
                       "candidate": CONCLUSION, "user_stance": "neutral"}]
        done = cli_in(first, "discuss", "--card", "c1", stdin="我想接着说\n")
        back = [c for c in printed_commands(done.stdout) if " transcript " in c]
        self.check("B3a 相对 DOJO_SESSIONS 下也点名了回看命令", bool(back),
                   back[0] if back else "屏幕上没有回看命令")
        if not back:
            return
        tokens = shell_words(back[0]) or []
        self.check("B3b0 回看命令能被 shell 分成参数", bool(tokens), back[0])
        if not tokens:
            return
        trace = tokens[tokens.index("transcript") + 1]
        self.check("B3b 回看命令里的轨迹路径是绝对路径", trace.startswith(str(first)), trace)
        pasted = subprocess.run(["sh", "-c", back[0]], cwd=str(second), env=env,
                                text=True, capture_output=True, timeout=180)
        self.check("B3c 换一个目录粘贴回看，仍能读到这一场",
                   pasted.returncode == 0 and "我想接着说" in pasted.stdout,
                   "exit=%d" % pasted.returncode)

    # -- B4. the same lines, pasted in a terminal without the variable ---------

    def b_fresh_shell(self):
        """`DOJO_DB` set for one command; the hint pasted in a second terminal.

        Supervisor's third report (#3419). A terminal that was not given the variable does
        not have it, so a line that relied on `$DOJO_DB` read the default library: exit 2,
        and an empty library created there. This is what rules out "does a bare run read
        this file right now" as the test -- the answer changes with the shell.
        """
        where = self.root / "fresh-shell"
        work, home2 = where / "work", where / "home"
        work.mkdir(parents=True)
        home2.mkdir()
        chosen = where / "chosen.sqlite3"
        default2 = home2 / ".local" / "share" / "dojo" / "dojo.sqlite3"
        with_var = dict(self.env, HOME=str(home2), DOJO_DB=str(chosen))
        fresh = dict(self.env, HOME=str(home2))
        fresh.pop("DOJO_DB", None)

        def cli_in(env, *args, stdin=""):
            return subprocess.run([sys.executable, "-B", "-m", "dojo", *args],
                                  cwd=str(work), env=env, input=stdin, text=True,
                                  capture_output=True, timeout=180)

        for args in (("add", "--id", "c1", "--kind", "abstract_idea",
                      "--statement", CARD, "--scope", "他已经抽身的时候",
                      "--premise", "系统能自己跑检查"),
                     ("confirm", "c1", "--basis", "他在会话里认可了这句；不表示为真",
                      "--session", "sess-A")):
            cli_in(with_var, *args)
        REPLIES[:] = [{"answer": "那我们把这句当成现在这一版。",
                       "candidate": CONCLUSION, "user_stance": "neutral"}]
        done = cli_in(with_var, "discuss", "--card", "c1", stdin="我想接着说\n")
        self.check("B4a 一次性 DOJO_DB 下也能开场", done.returncode == 0,
                   "exit=%d" % done.returncode)
        if done.returncode:
            return
        shows = [c for c in printed_commands(done.stdout) if " show " in c]
        self.check("B4b 屏幕上的命令没靠那个变量",
                   bool(shows) and "--db" in (shell_words(shows[0]) or []),
                   shows[0] if shows else "屏幕上没有 show 命令")
        for command in shows:
            pasted = subprocess.run(["sh", "-c", command], cwd=str(work), env=fresh,
                                    text=True, capture_output=True, timeout=180)
            self.check("B4c 在没有那个变量的终端里粘贴，仍打开草稿",
                       pasted.returncode == 0 and '"candidate"' in pasted.stdout,
                       "exit=%d" % pasted.returncode)
        self.check("B4d 新终端里没有新建默认库", not default2.is_file(), str(default2))

    # -- B5. started on the default library, pasted where another one is usual -----

    def b_default_to_other_library(self):
        """The case the supervisor found last, and the worst one (#3419).

        A session on the default library prints its lines; the reader pastes them in a
        terminal whose `DOJO_DB` points at the library they normally work on. Before the
        short form was removed, `show` failed there -- and `--resume` exited 0 and appended
        the second half of the conversation to that other library, so a pasted line quietly
        wrote into a library this session never touched.
        """
        where = self.root / "default-to-other"
        work, home2, other_dir = where / "work", where / "home", where / "other"
        for path in (work, home2, other_dir):
            path.mkdir(parents=True)
        default2 = home2 / ".local" / "share" / "dojo" / "dojo.sqlite3"
        other_db = other_dir / "mine.sqlite3"
        plain = dict(self.env, HOME=str(home2))
        plain.pop("DOJO_DB", None)
        elsewhere = dict(plain, DOJO_DB=str(other_db))

        def cli_in(env, *args, stdin=""):
            return subprocess.run([sys.executable, "-B", "-m", "dojo", *args],
                                  cwd=str(work), env=env, input=stdin, text=True,
                                  capture_output=True, timeout=180)

        for env in (plain, elsewhere):
            for args in (("add", "--id", "c1", "--kind", "abstract_idea",
                          "--statement", CARD, "--scope", "他已经抽身的时候",
                          "--premise", "系统能自己跑检查"),
                         ("confirm", "c1", "--basis", "他在会话里认可了这句；不表示为真",
                          "--session", "sess-A")):
                cli_in(env, *args)

        REPLIES[:] = [{"answer": "那我们把这句当成现在这一版。",
                       "candidate": CONCLUSION, "user_stance": "neutral"}]
        done = cli_in(plain, "discuss", "--card", "c1", stdin="我想接着说\n")
        self.check("B5a 默认库上能开场", done.returncode == 0, "exit=%d" % done.returncode)
        if done.returncode:
            return

        shows = [c for c in printed_commands(done.stdout) if " show " in c]
        for command in shows:
            pasted = subprocess.run(["sh", "-c", command], cwd=str(work), env=elsewhere,
                                    text=True, capture_output=True, timeout=180)
            self.check("B5b 在另一个库的终端里粘贴，仍打开本场的草稿",
                       pasted.returncode == 0 and '"candidate"' in pasted.stdout,
                       "exit=%d" % pasted.returncode)

        back = [c for c in printed_commands(done.stdout) if " transcript " in c]
        if not back:
            self.check("B5c 屏幕上点名了回看命令", False, "没有 transcript 命令")
            return
        view = subprocess.run(["sh", "-c", back[0]], cwd=str(work), env=elsewhere,
                              text=True, capture_output=True, timeout=180)
        resumes = [c for c in printed_commands(view.stdout) if " --resume " in c]
        self.check("B5c 回看里点名了续谈命令", bool(resumes),
                   resumes[0] if resumes else "没有续谈命令")
        if not resumes:
            return
        before = other_db.read_bytes() if other_db.is_file() else None
        REPLIES[:] = []
        resumed = subprocess.run(["sh", "-c", resumes[0]], cwd=str(work), env=elsewhere,
                                 input="", text=True, capture_output=True, timeout=180)
        after = other_db.read_bytes() if other_db.is_file() else None
        self.check("B5d 粘贴续谈没有把这一场写进另一个库",
                   not (resumed.returncode == 0 and before != after),
                   "exit=%d，另一个库被改写：%s" % (resumed.returncode, before != after))

    # -- C. the one rule, stated three ways -----------------------------------

    def c_one_rule(self):
        """One rule with no exceptions: every card and view command names the file.

        Four reported cases came down to the same thing -- a line whose meaning depended
        on where it was pasted:

          explicit    `--db run/x.sqlite3` is a different file from another directory
          relative    `DOJO_DB=chosen.sqlite3` likewise
          one-shot    `DOJO_DB=/abs/x.sqlite3` is absent in the next terminal
          other lib   a terminal that usually works on another library is not this one

        The last was worse than the others: `--resume` from the pasted line exited 0 and
        appended the second half of the conversation to that other library. That is why
        the earlier "keep the common case short" rule is gone -- it was a preference, and
        it cost the property that matters.
        """
        from dojo import commands

        # A stand-in for the default location, not this machine's real one: the renderer
        # no longer looks at HOME at all, and evidence should not print the operator's
        # home directory either.
        default = self.root / "default-home" / ".local" / "share" / "dojo" / "dojo.sqlite3"
        named = self.library
        other = self.root / "elsewhere" / "other.sqlite3"
        other.parent.mkdir(exist_ok=True)

        def rendered(database):
            return commands.dojo("show", "c1", db=commands.library_argument(database))

        def names(line, path):
            tokens = shell_words(line) or []
            return "--db" in tokens and tokens[tokens.index("--db") + 1] == str(path)

        old = os.environ.pop("DOJO_DB", None)
        try:
            for label, database in (("C1 默认库也写全", default),
                                    ("C1a 显式库写全", named),
                                    ("C1b 另一个库写全", other)):
                line = rendered(database)
                self.check(label, names(line, database), line)

            # Now with the environment pointing at several different things. None of them
            # may change a single character of what gets printed: that is the whole point.
            baseline = {database: rendered(database)
                        for database in (default, named, other)}
            for value in (str(named), "chosen.sqlite3", str(default), str(other)):
                os.environ["DOJO_DB"] = value
                for database, expected in baseline.items():
                    line = rendered(database)
                    self.check("C1c DOJO_DB=%s 时 %s 的印法不变"
                               % (value, database.name), line == expected, line)
        finally:
            if old is None:
                os.environ.pop("DOJO_DB", None)
            else:
                os.environ["DOJO_DB"] = old

    def c_no_line_omits_the_library(self):
        """The whole point, swept over every screen this run produced.

        Each check above looks at a line it knows about. This one reads *every* command on
        every screen this run collected, so a surface that forgets the flag cannot pass by
        not being listed.
        """
        seen = 0
        for label, text in self.screens:
            for command in printed_commands(text):
                words = shell_words(command)
                if words is None:
                    self.check("C0 %s 里的命令能被 shell 分开" % label, False, command)
                    continue
                if not {"show", "transcript", "discuss"} & set(words):
                    continue
                seen += 1
                self.check("C0 %s 里的命令带着库" % label, "--db" in words, command)
        self.check("C0 至少扫到一条命令", seen > 0, "共扫到 %d 条" % seen)

    def c_quoting(self):
        """Every path this program might print arrives as one argument in a real shell.

        The strings are passed through `dojo.commands.quote`, the renderer the program
        itself uses -- quoting them here by hand would test this file, not the program."""
        from dojo import commands

        for text in (str(self.library), "a b", "it's", '$HOME/x', "back`tick`",
                     'both " and \' plus $x', "trailing space "):
            line = ("python3 -c 'import sys;print(len(sys.argv)-1)' "
                    + commands.quote(text))
            done = self.paste(line)
            self.check("C3 带 %r 的路径是一个参数" % text[:14],
                       done.stdout.strip() == "1",
                       "参数个数：%s（原字：%r）" % (done.stdout.strip() or done.stderr.strip(), text))


def main() -> int:
    socket.setdefaulttimeout(10)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}/v1"

    temp = tempfile.TemporaryDirectory()
    root = Path(temp.name)
    home = root / "home"
    home.mkdir()
    default_db = home / ".local" / "share" / "dojo" / "dojo.sqlite3"
    library_dir = root / "a library's $HOME `x`"
    library_dir.mkdir()
    library = library_dir / "my dojo's.sqlite3"

    env = {k: v for k, v in os.environ.items() if not k.startswith("DOJO_")}
    env.update({"HOME": str(home), "DOJO_LLM_BASE_URL": base, "DOJO_LLM_MODEL": "loopback",
                "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"})

    def cli(*args, stdin=""):
        return subprocess.run([sys.executable, "-B", "-m", "dojo", *args], cwd=str(ROOT),
                              env=env, input=stdin, text=True, capture_output=True, timeout=180)

    def paste(command):
        return subprocess.run(["sh", "-c", command], cwd=str(ROOT), env=env, text=True,
                              capture_output=True, timeout=180)

    for args in (["--db", str(library), "add", "--id", "c1", "--kind", "abstract_idea",
                  "--statement", CARD, "--scope", "他已经抽身的时候",
                  "--premise", "系统能自己跑检查"],
                 ["--db", str(library), "confirm", "c1", "--basis",
                  "他在会话里认可了这句；不表示为真", "--session", "sess-A"]):
        done = cli(*args)
        if done.returncode:
            print("准备失败：", args, done.stdout, done.stderr)
            return 1

    print("库：%s" % library)
    print("默认库（应当一直不存在）：%s" % default_db)
    print()
    checks = Checks(root, env, home, default_db, library, cli, paste)

    print("A0. 四件问完之后的回执")
    checks.a0_question_receipt()
    print()
    print("A. 开轨迹的一场（早退，留草稿）")
    checks.a_exit_commands()
    print()
    print("B. 用 --no-trace 退出的一场")
    checks.b_no_trace()
    print()
    print("B2. 相对 DOJO_DB，换一个目录再粘贴")
    checks.b_relative_env()
    print()
    print("B3. 相对 DOJO_SESSIONS，轨迹路径也要经得起换目录")
    checks.b_relative_sessions()
    print()
    print("B4. 一次性的 DOJO_DB，换一个没有这个变量的终端")
    checks.b_fresh_shell()
    print()
    print("B5. 默认库上谈完，粘到平常用另一个库的终端")
    checks.b_default_to_other_library()
    print()
    print("C. 一条规则：每条命令都写全库")
    checks.c_one_rule()
    checks.c_no_line_omits_the_library()
    checks.c_quoting()

    print()
    if checks.failures:
        print("%d 项不成立：%s" % (len(checks.failures), "、".join(checks.failures)))
        return 1
    print("全部成立（%d 项）。" % checks.checks)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
