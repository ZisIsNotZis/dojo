"""Read back what one discussion trace kept -- and only that.

The receipt at the end of the four questions says his words stay in the session record.
Until this existed, acting on that sentence meant opening `sessions/discuss-<id>.jsonl`
and decoding it by hand. A promise the reader cannot keep without learning the trace
format is a promise about the disk, not about anything he can use -- the same defect as
"原话在上面" pointing at a line the screen never printed, one layer out. `--resume` is not
it either: resuming prints "历史与待处理内容已恢复" and none of his words.

Three things this view refuses to do:

  claim agreement   the trace holds what he said and what the host said. Whether a
                    wording was accepted is a separate fact, carried by the round's
                    `stance`/`decision` and by the library; this view names those and
                    never turns material into consent.
  hide a truncation a session whose trace died mid-write leaves a shorter file. The
                    missing tail is reported as missing, not as "he said nothing more".
  rewrite anything  the file is opened read-only. The view is a projection, never a
                    repair: a trace that is broken stays broken on disk.
"""
from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Any

from .elicit import PART_KEYS, PART_ORDER, classify_answer
from .tracefile import split_lines


def reclassify(said: str) -> str:
    """What today's rule makes of the same words. Named so a caller can tell why."""
    return classify_answer(said)


class TranscriptError(ValueError):
    """The file cannot be shown as this program's discussion session."""


# What each `reading` on an elicitation row means, in the words a reader of the trace
# would use. The receipt uses its own phrasing for the same facts; these are the trace's
# vocabulary, because this view reports the record, not the screen.
PART_READINGS = {
    "answer": "收作原话",
    "none": "不是回答，没有收下",
    "skip": "跳过",
    "skip_rest": "跳过，并说剩下的先不问",
    "stop": "说到这儿为止",
    "eof": "问到这儿时输入结束了",
    "too_large": "这句太长，没有收录",
    "undo": "退回了上一题",
}


def load(path: Path) -> dict[str, Any]:
    """Parse one trace into the facts this view shows. Read-only, no store needed."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise TranscriptError(f"读不出来：{exc}") from None
    except UnicodeDecodeError:
        raise TranscriptError("不是 UTF-8 文本，不是本程序的轨迹") from None
    # `\n` is the record separator, not whatever `str.splitlines()` counts: U+0085,
    # U+2028 and U+2029 are legal raw inside a JSON string and are written by documents
    # people paste answers from. This reader used to split on them and refuse a trace
    # this program had written itself.
    lines = split_lines(raw)
    rows: list[dict[str, Any]] = []
    partial_tail = False
    for index, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            # A write that died mid-line leaves a fragment at the end. That is a real
            # state of a real session (the receipt already has a sentence for it), and
            # the reader came here for the part that was written. A malformed line
            # anywhere else is not a truncation and is refused.
            if index == len(lines):
                partial_tail = True
                break
            raise TranscriptError(f"第 {index} 行不是 JSON，不是本程序的轨迹") from None
        if not isinstance(value, dict):
            raise TranscriptError(f"第 {index} 行不是记录对象")
        rows.append(value)
    if not rows:
        # A real state: the file was created and the very first write died. The receipt
        # for that session says the words were not kept and names no view, so this is
        # reached by someone who went looking anyway. Say what the file is, not that
        # their path was wrong.
        raise TranscriptError(
            "这份轨迹是空的：这一场没有写下任何一行（可能轨迹刚开就没写成）"
            if not partial_tail else
            "这份轨迹只有半行、没有一条完整记录：这一场没有写成任何一条"
        )
    if not any(row.get("event") in {"elicitation", "session_end", "handout"}
               or "reason" in row for row in rows):
        raise TranscriptError("记录形状不是本程序的讨论轨迹")

    rounds = [row for row in rows if isinstance(row.get("user"), str)]
    elicitations = [row for row in rows if row.get("event") == "elicitation"]
    ends = [row for row in rows if row.get("event") == "session_end"]
    handouts = [row for row in rows if row.get("event") == "handout"]
    end = ends[-1] if ends else None

    # One row per part, the last one written: the trace is append-only and every ending
    # (including taking a part back) is a row, so the last row is what the session ended
    # with. This is the same rule `elicitation_state` replays for the live receipt and
    # for resume; a view that picked the first row would show a part he later undid.
    parts: list[dict[str, Any]] = []
    by_part: dict[str, list[dict[str, Any]]] = {}
    for row in elicitations:
        part = row.get("part")
        if isinstance(part, str) and part in PART_KEYS:
            by_part.setdefault(part, []).append(row)
    for part in PART_ORDER:
        events = by_part.get(part)
        if not events:
            continue
        last = events[-1]
        said = next((row["answer"] for row in reversed(events)
                     if isinstance(row.get("answer"), str)), None)
        reading = last.get("reading") if isinstance(last.get("reading"), str) else None
        # The row records what the session decided at the time. `--resume` and the live
        # receipt instead replay the answers through `classify_answer` as it is *now*, and a
        # later slice changed that rule. The review measured the split: on a trace written
        # before the change, this view said 收作原话 for four parts while `--resume` replayed
        # the same file into "nothing was collected". Neither is wrong about its own input,
        # so the screen says both.
        now = reclassify(said) if said else None
        parts.append({
            "part": part,
            "question": last.get("question") if isinstance(last.get("question"), str) else None,
            "said": said,
            "reading": reading,
            "reclassified": now if (now is not None and now != reading) else None,
            "uncertain": bool(last.get("uncertain")),
            "rewritten": len(events) > 1,
        })

    # Whether `--resume` would accept this file. Asking the same validator keeps this
    # view from printing a command that is going to be refused: a truncated tail, a name
    # that is not a session id, or a trace with no ending are all readable here and none
    # of them is resumable, and the reader should learn that from this screen, not from
    # a second refusal after copying the command.
    try:
        from .discuss import _load_resume_trace

        _load_resume_trace(path)
        resumable: str | None = None
    except ValueError as exc:
        resumable = str(exc)
    except Exception as exc:  # pragma: no cover - a validator crash is not a verdict
        resumable = f"无法续跑轨迹：{exc}"

    return {
        "session": path.stem,
        "path": path,
        "resumable": resumable,
        "complete": end is not None and not partial_tail,
        "records": len(rows),
        "partial_tail": partial_tail,
        "ended": end.get("reason") if isinstance(end, dict) else None,
        "saved": [item for item in (end.get("saved") or []) if isinstance(item, str)]
        if isinstance(end, dict) else [],
        # A session that ended with a wording nobody accepted writes it as an unaccepted
        # draft (`_draft_conclusion`). The row that says so is `draft`, not `saved`; the
        # review found this view printing "这一场没有写下卡片" while the library held the
        # very sentence the session had just talked through.
        "draft": end.get("draft") if isinstance(end, dict) and isinstance(end.get("draft"), str) else None,
        "handed": handouts[0] if handouts else None,
        "turns": [
            {"seq": row.get("seq"), "said": row["user"],
             "reply": row.get("answer") if isinstance(row.get("answer"), str) else None}
            for row in rounds
        ],
        "parts": parts,
    }


def command(path: Path) -> str:
    """The copyable command that shows this trace again."""
    return "python3 -m dojo transcript " + shlex.quote(str(path))


ENDINGS = {
    "eof": "输入结束了",
    "limit": "到了本场请求上限",
    "cancel": "你取消了这一场",
    "failure": "模型请求失败，这一场停在那里",
    "declined": "你说剩下的先不问",
}


def render(view: dict[str, Any]) -> str:
    """The screen a person reads. Facts first; the one judgement this view makes is
    that it does not make one about whether an answer fit its question."""
    lines: list[str] = []
    lines.append(f"会话 {view['session']} 的原话回看（{view['records']} 条记录）")
    lines.append("这是这一场留下的记录，不是库里的结论。")
    handed = view["handed"]
    if isinstance(handed, dict) and isinstance(handed.get("statement"), str):
        lines.append(
            f"这一场是带着一张以前的卡开的：{handed.get('candidate')}「{handed['statement']}」"
        )
    lines.append("")

    if view["turns"]:
        lines.append("你在讨论里说的话：")
        for turn in view["turns"]:
            prefix = f"  [{turn['seq']}] " if turn["seq"] is not None else "  "
            lines.append(prefix + "你说：" + turn["said"])
            if turn["reply"]:
                lines.append("      主持人：" + turn["reply"])
        lines.append("")

    if not view["parts"] and not view["complete"]:
        lines.append("四件追问：这份记录里没有留下追问的行（记录在追问之前就断了，或者这一场没走到追问）。")
        lines.append("")
    if view["parts"]:
        lines.append("四件追问（下面每句都是你当时说的原话）：")
        for part in view["parts"]:
            lines.append(f"  {part['part']}")
            if part["question"]:
                lines.append("    问的是：" + part["question"])
            if part["said"] is not None:
                lines.append("    你说：" + part["said"])
            reading = part["reading"]
            label = PART_READINGS.get(reading, f"记录里的读数是 {reading!r}")
            if part["rewritten"]:
                lines.append("    记录最后记的是：" + label + "（这一件问过不止一轮，上面是最后留下的那句）")
            else:
                lines.append("    记录里记的是：" + label)
            # A stored reading is what the rule said *then*. Saying so keeps this screen
            # from disagreeing silently with `--resume`, which replays the same words
            # through the rule as it is now (the review found the two diverging on traces
            # written before the rule changed).
            if part["reclassified"]:
                lines.append(
                    "      这一行是当时的读法；按现在的规则重算，是「"
                    + PART_READINGS.get(part["reclassified"], part["reclassified"])
                    + "」。续跑会按后者算。"
                )
            if part["uncertain"]:
                lines.append("      这一句里像在说跳过，但按原话收下了（记录里的 uncertain）。")
        lines.append("")

    if view["saved"]:
        lines.append("这一场写下的卡片：" + "、".join(view["saved"]))
        lines.append("这几张卡是写下的那几句；四件回答没有改写它们，回看也不说它们已被认可。")
    elif view["draft"]:
        lines.append("这一场没有写下被认可的卡片；结束时留了一张未认可的草稿：" + view["draft"] + "。")
        lines.append("草稿是系统按你的话整理的那一版，没有人认可过它——它恰恰是最该你自己看一眼的那张。")
    elif view["complete"]:
        lines.append("这一场没有写下卡片。")
    else:
        # The record stops before any ending row, so `saved: []` is not evidence that
        # nothing was written -- the row that would have said so is the one missing.
        lines.append("这份记录没有写到结尾，所以看不出这一场有没有写下卡片；不要据此当成没写过。")

    ended = view["ended"]
    if ended is None:
        lines.append("记录里没有结尾那一条：这一场没有正常收尾，下面的话只到写下的部分为止。")
    else:
        lines.append("结尾：" + ENDINGS.get(ended, ended) + "。")
    if view["partial_tail"]:
        lines.append("最后一行只写了一半（写的时候断了），这一行没有算进来。")

    lines.append("")
    lines.append("这些话是材料，不是结论：回看只说你说过什么，不判哪句答到了点上，也不代表你认可了哪条结论。")
    if view.get("resumable"):
        # Never print a command that is going to be refused.
        lines.append("这一份不能接着谈：" + view["resumable"] + "。")
    else:
        lines.append("接着谈这一场：python3 -m dojo discuss --resume " + shlex.quote(str(view["path"])))
    return "\n".join(lines) + "\n"


def load_and_render(path: Path) -> str:
    return render(load(path))


__all__ = ["TranscriptError", "PART_READINGS", "load", "render", "command", "load_and_render"]
