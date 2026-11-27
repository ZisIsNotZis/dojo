"""An off-target answer: his words kept, the question not counted as answered.

    python3 docs/evidence/2026-11-28-offtarget-receipt/verify.py

Offline, throwaway library, loopback endpoint. Each check reads the screen, the trace
**and** the library, because the defect this slice is about was a receipt word that
asserted a judgement the program never made -- the class of bug where the screen is
the only thing that is wrong, and a test that reads only the screen cannot see it.

Exit 0 and `全部成立。` when every line below prints OK.
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from dojo.discuss import closing_text, run_discuss  # noqa: E402
from dojo.storage import Store  # noqa: E402

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print("OK     " + label)
    else:
        print("FAIL   " + label + (("  —— " + detail) if detail else ""))
        failures.append(label)


CARD = "持续检查交给系统自己跑，但只在检查结果会打断他时才叫醒他。"
CONCLUSION = {
    "statement": CARD, "kind": "abstract_idea",
    "scope": ["他已经抽身的时候"], "premises": ["系统能自己跑检查"],
    "alternatives": ["把检查留给人"], "contradictions": ["检查必须发生在世界里时"],
    "unknowns": ["他会不会来看回执"],
}

# Substantive, first-person, and off the question. These are the words the slice is
# about: a real contribution the program cannot grade.
OFF_SITUATION = "我觉得这里关键是通知得做好，不然谁都不知道系统跑完了没有。"
ON_TENSION = "照这个做，我那种先自己看一遍的习惯就没机会用了，那是我挺看重的一件好事。"
OFF_PRICE = "这个方案对工程师是好事，反正工程师本来就该多写点自动化。"
OFF_OFF = "每个团队都不一样，有的团队特别需要这个，有的完全不需要。"


def result(answer, candidate=None, user_stance="neutral"):
    return {"answer": answer, "candidate": candidate, "user_stance": user_stance}


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)

    def complete(self, messages):
        return self.responses.pop(0)


def read_lines(lines):
    iterator = iter(lines)

    def read_line(_prompt):
        try:
            return next(iterator)
        except StopIteration:
            raise EOFError
    return read_line


class Library:
    def __init__(self, root: Path):
        self.root = root
        self.store = Store(root / "dojo.sqlite3")

    def run(self, answers, *, no_trace=False):
        output = io.StringIO()
        code = run_discuss(
            self.store,
            client=FakeClient([result("那我们把这句当成现在这一版。", CONCLUSION),
                               result("好，就这句。", CONCLUSION, user_stance="accept")]),
            read_line=read_lines(["讲一条做法", "对，就这么定", *answers]),
            output=output, no_trace=no_trace,
        )
        return code, output.getvalue()

    def rows(self):
        paths = sorted((self.root / "sessions").glob("*.jsonl"))
        if not paths:
            return []
        return [json.loads(line)
                for line in paths[-1].read_text(encoding="utf-8").splitlines()]

    def close(self):
        self.store.close()


def closing(text):
    for line in text.splitlines():
        if not line.startswith("主持人> "):
            continue
        body = line[len("主持人> "):]
        if body.startswith(("四件问完了", "问到这里停了")):
            return body
    return None


def main() -> int:
    temp = tempfile.TemporaryDirectory()
    root = Path(temp.name)
    library = Library(root / "a")
    try:
        code, text = library.run([OFF_SITUATION, ON_TENSION, OFF_PRICE, OFF_OFF])
        rows = {row["part"]: row for row in library.rows()
                if row.get("event") == "elicitation" and row.get("turn") == 1}
        line = closing(text)
        end = [row for row in library.rows() if row.get("event") == "session_end"][-1]
        saved = end["saved"][0]
        shown = library.store.show(saved)
    finally:
        library.close()

    check("C1 这一场正常跑完", code == 0, str(code))
    check("C2 三句答偏的话按原话留在轨迹里，没有被改写或摘要",
          all(rows[part]["answer"] == words and rows[part]["reading"] == "answer"
              and rows[part]["collected"] is True
              for part, words in (("情境", OFF_SITUATION), ("代价", OFF_PRICE),
                                  ("失效", OFF_OFF))),
          json.dumps({part: rows[part]["answer"] for part in rows}, ensure_ascii=False))
    check("C3 回执不再说「你答了」或「四件你都答了」",
          "你答了" not in line and "四件你都答了" not in line, line)
    check("C4 回执用的是「说了原话」",
          "说了原话" in line, line)
    # The receipt itself, printed once, so a reader can see the sentence this slice is
    # about instead of taking the checkbox on trust.
    print("\n回执原文：")
    print("  " + (line or "（没有回执）"))
    print()
    check("C5 回执在屏幕上明说它不判有没有答到点上",
          "答没答到点上，这句不判" in line and "原话在上面" in line, line)
    check("C6 回执说这些原话没有写进卡片",
          "没有写进卡片" in line, line)
    check("C7 卡片仍是提问前那句，回答一个字都没进去",
          shown["candidate"]["statement"] == CARD
          and OFF_PRICE not in json.dumps(shown, ensure_ascii=False),
          shown["candidate"]["statement"])

    # The other direction: do not let the word creep onto parts that were not said.
    second = Library(root / "b")
    try:
        code2, text2 = second.run(["先跳过这一题", "", "", "有一次我照着做反而漏了"])
        line2 = closing(text2)
    finally:
        second.close()
    check("C8 说跳过的那件不会被打上「说了原话」",
          code2 == 0 and "你说跳过 情境" in line2
          and "情境 上说了原话" not in line2, line2)
    check("C9 没答出来的那件保留自己的词",
          "没答出来 张力" in line2, line2)
    check("C10 真说了原话的那件照常点名",
          "你在 代价 上说了原话" in line2, line2)

    third = Library(root / "c")
    try:
        code3, text3 = third.run(("",) * 8)
        line3 = closing(text3)
    finally:
        third.close()
    check("C11 一句没说时不印那句判语",
          code3 == 0 and "答没答到点上" not in line3 and "说了原话" not in line3, line3)

    fourth = Library(root / "d")
    try:
        code4, text4 = fourth.run([OFF_SITUATION, ON_TENSION, OFF_PRICE, OFF_OFF],
                                  no_trace=True)
        line4 = closing(text4)
    finally:
        fourth.close()
    check("C12 关掉轨迹时不说「留在本场记录」",
          code4 == 0 and "这场不留原文" in line4 and "留在本场记录" not in line4, line4)

    # The pure function, so the contract is checkable without a session.
    pure = closing_text(["情境", "失效"], ["张力"], ["代价"])
    check("C13 纯函数把「说了原话」与「跳过」「没答出来」分得开",
          "你在 情境、失效 上说了原话" in pure and "你说跳过 张力" in pure
          and "没答出来 代价" in pure and "你答了" not in pure, pure)

    print()
    if failures:
        print("%d 项不成立。" % len(failures))
        for label in failures:
            print("  - " + label)
        return 1
    print("全部成立。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
