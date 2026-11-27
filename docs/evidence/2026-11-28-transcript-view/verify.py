#!/usr/bin/env python3
"""Evidence for `dojo transcript`: the receipt's promise, now something he can do.

    python3 docs/evidence/2026-11-28-transcript-view/verify.py

Every check runs the real program (`python3 -m dojo`) in a throwaway directory, except
the two that need a mid-write failure and drive `run_discuss` in-process so the file
object can die on purpose. Nothing opens a library, calls a model, or touches the repo.

The three claims this slice stands on:

  1. The receipt ends with a command, and running that command as printed shows his words.
  2. The view says the words are material, not consent, and never says a question was
     answered.
  3. A record that stopped mid-write is readable, is reported as truncated, and is not
     offered a `--resume` that would be refused.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from dojo import discuss as discuss_module  # noqa: E402
from dojo.discuss import run_discuss  # noqa: E402
from dojo.storage import Store  # noqa: E402

FAILURES: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(("OK     " if ok else "FAIL   ") + label)
    if not ok:
        FAILURES.append(label)
        if detail:
            print("       " + str(detail).replace("\n", "\n       ")[:1500])


def clean_env(**extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("DOJO_")}
    env["PYTHONPATH"] = str(ROOT)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.update(extra)
    return env


def cli(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-B", "-m", "dojo", *args], cwd=str(ROOT),
                          env=env or clean_env(), input="", text=True,
                          capture_output=True, timeout=300)


CARD = "持续检查交给系统自己跑，但只在检查结果会打断他时才叫醒他。"
CONCLUSION = {
    "statement": CARD, "kind": "abstract_idea",
    "scope": ["他已经抽身的时候"], "premises": ["系统能自己跑检查"],
    "alternatives": ["把检查留给人"], "contradictions": ["检查必须发生在世界里时"],
    "unknowns": ["他会不会来看回执"],
}
SITUATION = "我觉得这里关键是通知得做好，不然谁都不知道系统跑完了没有。"
TENSION = "照这个做，我那种先自己看一遍的习惯就没机会用了，那是我挺看重的一件好事。"
PRICE = "这个方案对工程师是好事，反正工程师本来就该多写点自动化。"
OFF = "每个团队都不一样，有的团队特别需要这个，有的完全不需要。"
ANSWERS = [SITUATION, TENSION, PRICE, OFF]


def receipt_of(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("主持人> ") and ("四件问完了" in line or "问到这里停了" in line):
            return line
    return ""


def run_in_process(read_lines: list[str], *, die_after: int | None = None,
                   no_trace: bool = False) -> tuple[str, Path, Path]:
    """One real session without a process boundary, so the trace file can die."""
    temp = tempfile.TemporaryDirectory()
    root = Path(temp.name)
    store = Store(root / "dojo.sqlite3")

    class Client:
        def __init__(self) -> None:
            self.responses = [
                {"answer": "那我们把这句当成现在这一版。", "candidate": CONCLUSION,
                 "user_stance": "neutral"},
                {"answer": "好，就这句。", "candidate": CONCLUSION,
                 "user_stance": "accept"},
            ]

        def complete(self, _messages):
            return self.responses.pop(0)

    iterator = iter(read_lines)

    def read_line(_prompt):
        try:
            return next(iterator)
        except StopIteration:
            raise EOFError

    output = io.StringIO()
    real_append = discuss_module._SessionTrace.append
    if die_after is not None:
        calls = {"n": 0}

        def dying(trace, value):
            calls["n"] += 1
            if calls["n"] >= die_after:
                trace._warn(OSError("no space left on device"))
                return
            real_append(trace, value)

        discuss_module._SessionTrace.append = dying
    try:
        run_discuss(store, client=Client(), read_line=read_line, output=output,
                    environ={}, no_trace=no_trace)
    finally:
        discuss_module._SessionTrace.append = real_append
        store.close()
    traces = sorted((root / "sessions").glob("*.jsonl")) if not no_trace else []
    temp._dojo_temp = temp  # keep the directory alive for the caller
    return output.getvalue(), traces[0] if traces else root, root


def main() -> int:
    print("A. the receipt names a command, and the command works\n")

    text, trace, root = run_in_process(["讲一条做法", "对，就这么定", *ANSWERS])
    line = receipt_of(text)
    marker = "运行："
    check("A1 回执在说「留在本场记录里」之后点名了一条回看命令",
          marker in line and "python3 -m dojo transcript" in line, line)
    command = line.split(marker, 1)[1].split("（", 1)[0].strip() if marker in line else ""
    check("A2 点名的命令指向这一场的轨迹", str(trace) in command, command)

    env = clean_env(DOJO_DB=str(root / "absent.sqlite3"))
    shown = cli(*command.split()[3:], env=env) if command else None
    check("A3 照抄回执那条命令：退出 0", shown is not None and shown.returncode == 0,
          shown.stderr if shown else "")
    check("A4 四句原话逐字都在屏幕上",
          all(words in (shown.stdout if shown else "") for words in ANSWERS),
          shown.stdout[-1200:] if shown else "")
    check("A5 屏幕把每件当初问的问题也列出来",
          "什么时候你会这么做" in (shown.stdout or "")
          and "照着这条做" in (shown.stdout or ""))
    check("A6 回看没有创建库（读了文件，没碰库）",
          not (root / "absent.sqlite3").exists())

    print("\nB. the view says material, not consent\n")
    body = shown.stdout if shown else ""
    disclaimer = "回看只说你说过什么，不判哪句答到了点上，也不代表你认可了哪条结论。"
    check("B1 屏幕明说这些话是材料、不是结论", "材料，不是结论" in body and disclaimer in body)
    above = body.split(disclaimer)[0]
    check("B2 免责之前的每一行都不声称「答了」「答到了」「认可」",
          not any(word in above for word in ("你答了", "答到了", "你认可", "已认可")), above[-800:])
    check("B3 收下的四件都用同一个中性的词", body.count("收作原话") == 4)
    check("B4 明说卡片是提问前那句、回答没有改写它",
          "四件回答没有改写它" in body)
    # The independent review's second finding: `之后没改过` spoke for the library. If a
    # second terminal runs `revise` while the four questions are being asked, the library
    # holds a newer version and the sentence is false. The claim is now about this
    # session, which is all it can know.
    check("B5 回执末句只说这场问答没改过，不说库里之后没改过",
          "这场问答没有改过它" in line and "之后没改过" not in line, line)

    print("\nC. a record that stopped mid-write\n")
    text2, trace2, _root2 = run_in_process(["讲一条做法", "对，就这么定", *ANSWERS], die_after=2)
    line2 = receipt_of(text2)
    check("C1 半路断盘时回执说中途写入失败，不说原话留在记录里",
          "轨迹中途写入失败" in line2 and "留在本场记录里" not in line2, line2)
    check("C2 那句仍然点名回看命令（先说的几句真在盘上）",
          "python3 -m dojo transcript" in line2, line2)

    # Cut a complete session instead: `die_after=2` leaves a file too short to cut, and
    # the point here is the tail, not how few rows a dying file has.
    rows = trace.read_text(encoding="utf-8").splitlines(keepends=True)
    cut_dir = root / "cut"
    cut_dir.mkdir()
    cut = cut_dir / trace.name
    cut.write_text("".join(rows[:3]) + rows[3][:12], encoding="utf-8")
    cut_shown = cli("transcript", str(cut))
    check("C3 截断的轨迹照样能读：退出 0", cut_shown.returncode == 0, cut_shown.stderr)
    check("C4 屏幕说最后一行只写了一半",
          "最后一行只写了一半" in cut_shown.stdout, cut_shown.stdout)
    check("C5 截断时不谎称「这一场没有写下卡片」",
          "这一场没有写下卡片" not in cut_shown.stdout)
    check("C6 截断时不印一条会被拒的续跑命令",
          "discuss --resume" not in cut_shown.stdout and "不能接着谈" in cut_shown.stdout)
    refused = cli("discuss", "--resume", str(cut))
    check("C7 那句话是真的：这条轨迹确实续跑不了", refused.returncode == 2, refused.stderr)

    # An undo is a row too. The trace is append-only, so "what this part became" is the
    # last row for it -- the same rule the live receipt and `--resume` replay. A view that
    # showed the first row would resurrect a sentence he took back by typing 改回上一题.
    rows_all = [json.loads(line) for line in
                trace.read_text(encoding="utf-8").splitlines()]
    head_rows = [row for row in rows_all if row.get("event") != "elicitation"]
    first = {"event": "elicitation", "part": "情境", "field": "situation", "turn": 1,
             "question": "问的是情境", "answer": "先答的那一句", "promoted": False,
             "collected": True, "reading": "answer", "at": "2026-11-28T00:00:00+00:00"}
    undo = dict(first, answer="改回上一题", reading="undo", collected=False,
                at="2026-11-28T00:00:01+00:00")
    again = dict(first, answer="后来认真答的那一句", at="2026-11-28T00:00:02+00:00")
    undo_dir = root / "undo"
    undo_dir.mkdir()
    undo_trace = undo_dir / trace.name
    undo_trace.write_text("\n".join(json.dumps(row, ensure_ascii=False)
                                    for row in [*head_rows, first, undo, again]) + "\n",
                          encoding="utf-8")
    undo_shown = cli("transcript", str(undo_trace))
    check("C8 一件被退回重答过：屏幕显示最后留下的那句",
          "后来认真答的那一句" in undo_shown.stdout
          and "先答的那一句" not in undo_shown.stdout, undo_shown.stdout)
    check("C9 那一件标出问过不止一轮",
          "问过不止一轮" in undo_shown.stdout, undo_shown.stdout)

    print("\nD. no record, no pointer\n")
    text3, _t3, root3 = run_in_process(["讲一条做法", "对，就这么定", *ANSWERS], no_trace=True)
    line3 = receipt_of(text3)
    check("D1 --no-trace 时回执说这场不留原文",
          "这场不留原文" in line3, line3)
    check("D2 也不点名任何回看命令", "transcript" not in line3)
    check("D3 盘上确实没有轨迹文件",
          not list((root3 / "sessions").glob("*.jsonl")) if (root3 / "sessions").exists() else True)

    print("\nE. the entry refuses what it is not\n")
    junk = root / "junk.jsonl"
    junk.write_text('{"hello": "world"}\n', encoding="utf-8")
    bad = cli("transcript", str(junk))
    check("E1 不是本程序的轨迹：退出 2、本地拒绝、无 traceback",
          bad.returncode == 2 and "无法回看" in bad.stderr and "Traceback" not in bad.stderr,
          bad.stderr)
    check("E2 文件不存在也是退出 2", cli("transcript", str(root / "nope.jsonl")).returncode == 2)
    machine = cli("transcript", str(trace), "--json")
    payload = json.loads(machine.stdout) if machine.returncode == 0 else {}
    check("E3 --json 给出同样的事实：四件、部分截断标记、结尾原因",
          machine.returncode == 0 and len(payload.get("parts", [])) == 4
          and payload.get("partial_tail") is False and payload.get("ended") == "eof",
          machine.stdout[:600])

    print("\nF. one conversation stays about one sentence\n")

    # The independent review's reproduction: a session is handed card X, agrees to
    # exactly X (so its saved id IS X), X is revised in the library, then `--resume`.
    # The resumed request used to carry "本场开始前…" with the opened wording and
    # "本场已有的结论" with the newer library wording -- two versions of one card in
    # one request. The content has to match field for field, or the save mints a
    # second card and the branch is never taken.
    opened = "持续检查交给系统自己跑，但只在检查结果会打断他时才叫醒他。"
    narrowed = "持续检查交给系统自己跑，只在结果会打断他、而且他真的会看时才叫醒他。"
    one = {"statement": opened, "kind": "abstract_idea",
           "scope": ["他已经抽身的时候"], "premises": ["系统能自己跑检查"],
           "alternatives": ["把检查留给人"],
           "contradictions": ["检查必须发生在世界里时"],
           "unknowns": ["他会不会来看回执"]}

    def two_halves() -> tuple[list[str], Path]:
        # Registered with `mkdtemp` rather than a TemporaryDirectory object that could be
        # collected when this function returns.
        home = Path(tempfile.mkdtemp(prefix="one-card."))
        store = Store(home / "dojo.sqlite3")
        added = store.add(statement=opened, kind="abstract_idea", scope=one["scope"],
                          premises=one["premises"], alternatives=one["alternatives"],
                          contradictions=one["contradictions"], unknowns=one["unknowns"],
                          session="sess-A")
        store.record_acceptance(added["id"], "sess-A", path="discuss_conclusion")
        store.confirm(added["id"], "他说值得讨论", session="sess-A")

        class Client:
            def __init__(self, responses):
                self.responses = list(responses)
                self.calls = []

            def complete(self, messages):
                self.calls.append(messages)
                return self.responses.pop(0)

        def reader(lines):
            iterator = iter(lines)

            def read_line(_prompt):
                try:
                    return next(iterator)
                except StopIteration:
                    raise EOFError
            return read_line

        first = Client([
            {"answer": "那我们把这句当成现在这一版。", "candidate": one,
             "user_stance": "neutral"},
            {"answer": "好，就这句。", "candidate": one, "user_stance": "accept"},
            {"answer": "接着说。", "candidate": None, "user_stance": "neutral"},
        ])
        run_discuss(store, client=first, card=added["id"],
                    read_line=reader(["接着上次那条说", "对，就这么定", "还有一点"]),
                    output=io.StringIO(), environ={})
        trace = sorted((home / "sessions").glob("*.jsonl"))[0]
        store.revise(added["id"], narrowed, "后来觉得门槛太低。", scope=one["scope"],
                     premises=one["premises"], session="sess-B")
        second = Client([{"answer": "继续说。", "candidate": None,
                          "user_stance": "neutral"}])
        run_discuss(store, client=second, resume=trace,
                    read_line=reader(["继续"]), output=io.StringIO(), environ={})
        store.close()
        return [message["content"] for message in second.calls[-1]
                if message["role"] == "user"], trace

    sent, _trace = two_halves()
    text = sent[-1] if sent else ""
    check("F1 会话里写下的就是开场那张卡（否则下面测不到那条分支）",
          "本场已有的结论" in text, text[-500:])
    check("F2 续跑的请求只带开场那一版措辞",
          opened in text and narrowed not in text, text[-800:])

    print("\nG. a pasted answer is still one line\n")

    # The supervisor's report at d7fbe00: an answer copied from a document carrying
    # U+2028 went into the trace, and the view refused the session the program had just
    # written with "第 2 行不是 JSON". `json.dumps` leaves U+0085/U+2028/U+2029 raw
    # inside a string and `splitlines()` counts all three as line breaks.
    from dojo.tracefile import LINE_BREAK_CODEPOINTS, encode_record, split_lines

    pasted = "那天我在修数据库\u2028修到一半卡住了\u2029后来我自己翻的日志。"
    encoded = encode_record({"answer": pasted})
    check("G1 写下来的一条记录不会含 U+0085/U+2028/U+2029",
          all(codepoint not in encoded for codepoint in LINE_BREAK_CODEPOINTS)
          and len(encoded.splitlines()) == 1, repr(encoded))
    check("G2 写进去的原话逐字读得回来",
          json.loads(encoded)["answer"] == pasted)
    legacy = json.dumps({"answer": pasted}, ensure_ascii=False) + "\n"
    # The pasted sentence carries two separators, so the old shape really does split into
    # more than one piece; the point is that the new reader still gives back one record.
    check("G3 修之前写下的轨迹（原字符未转义）仍读得出来",
          len(legacy.splitlines()) > 1
          and len(split_lines(legacy)) == 1
          and json.loads(split_lines(legacy)[0])["answer"] == pasted,
          repr(legacy[:120]))

    pasted_text, pasted_trace, _pasted_root = run_in_process(
        ["讲一条做法", "对，就这么定", pasted, "张力那句", "代价那句", "失效那句"])
    raw = pasted_trace.read_text(encoding="utf-8") if pasted_trace.exists() else ""
    check("G4 真会话里粘贴带 U+2028 的回答：轨迹每行都是完整 JSON",
          bool(raw) and all(isinstance(json.loads(line), dict)
                            for line in raw.splitlines()), raw[:400])
    pasted_shown = cli("transcript", str(pasted_trace))
    check("G5 回看这样一场：退出 0，且原话逐字在屏幕上",
          pasted_shown.returncode == 0 and pasted in pasted_shown.stdout,
          pasted_shown.stderr or pasted_shown.stdout[-600:])

    print()
    if FAILURES:
        print("%d 项不成立。" % len(FAILURES))
        for label in FAILURES:
            print("  - " + label)
        return 1
    print("全部成立。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
