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

from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from . import commands
from .elicit import PART_KEYS, PART_ORDER, classify_answer
from .tracefile import MAX_TRACE_BYTES, split_lines


def reclassify(said: str, part: str | None = None) -> str:
    """What today's rule makes of the same words. Named so a caller can tell why."""
    return classify_answer(said, part=part)


class TranscriptError(ValueError):
    """The file cannot be shown as this program's discussion session."""


# What each `reading` on an elicitation row means, in the words a reader of the trace
# would use. The receipt uses its own phrasing for the same facts; these are the trace's
# vocabulary, because this view reports the record, not the screen.
PART_READINGS = {
    "answer": "收作原话",
    "none": "不是回答，没有收下",
    "no_instance": "没有碰到过这样的例子（原话收下了，这一件没有材料）",
    "skip": "跳过",
    "skip_rest": "跳过，并说剩下的先不问",
    "stop": "说到这儿为止",
    "eof": "问到这儿时输入结束了",
    "too_large": "这句太长，没有收录",
    "undo": "退回了上一题",
}


def load(path: Path, *, expected_sha256: str | None = None) -> dict[str, Any]:
    """Parse one trace into the facts this view shows. Read-only, no store needed."""
    try:
        if expected_sha256 is None:
            raw = path.read_text(encoding="utf-8")
        else:
            with path.open("rb") as source:
                data = source.read(MAX_TRACE_BYTES + 1)
            if len(data) > MAX_TRACE_BYTES or sha256(data).hexdigest() != expected_sha256:
                raise TranscriptError("轨迹与清单定位时不同；请重新打开清单核对")
            raw = data.decode("utf-8")
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
        # 「改回上一题」 is an instruction, not something he said about the part, so the
        # words shown are the last *answer* row -- never the undo row that follows it. The
        # review measured the opposite pairing on an undo followed by end-of-input: words
        # from one row, verdict from another, and a rule-change note that was false.
        answered = [row for row in events
                    if isinstance(row.get("answer"), str) and row.get("reading") != "undo"]
        source = answered[-1] if answered else events[-1]
        said = source.get("answer") if isinstance(source.get("answer"), str) else None
        reading = source.get("reading") if isinstance(source.get("reading"), str) else None
        # If the part was taken back after those words, the verdict lives on the later
        # row; say so instead of pairing the words with a verdict about another moment.
        taken_back = any(row.get("reading") == "undo" for row in events)
        if taken_back:
            later = next((row for row in reversed(events)
                          if row.get("reading") not in {None, "undo"}), None)
            reading = (later.get("reading") if later is not None
                       and isinstance(later.get("reading"), str) else "undo")
        # The row records what the session decided at the time. `--resume` and the live
        # receipt instead replay the answers through `classify_answer` as it is *now*, and a
        # later slice changed that rule. The review measured the split: on a trace written
        # before the change, this view said 收作原话 for four parts while `--resume` replayed
        # the same file into "nothing was collected". Neither is wrong about its own input,
        # so the screen says both.
        #
        # Only when the row really stores a reading the replay can be compared with. A row
        # with no reading (the end-of-input row) was never a verdict, so nothing disagrees;
        # and `none` is what the session stores for a form-like reply whose classifier
        # answer was `structured`, which is not a rule change either. The review measured
        # both as false alarms on traces written by this very code.
        now = None
        if said and reading in {"answer", "skip", "skip_rest", "stop", "no_instance"}:
            candidate = reclassify(said, part)
            if candidate == "structured":
                candidate = "none"
            if candidate != reading:
                now = candidate
        parts.append({
            "part": part,
            "question": (source.get("question")
                         if isinstance(source.get("question"), str) else None),
            "said": said,
            "reading": reading,
            "reclassified": now,
            # Any row for the part, because the mark is set on the row whose words were
            # kept -- not necessarily the last row (an undo after it has none).
            "uncertain": any(bool(row.get("uncertain")) for row in events),
            "rewritten": len(events) > 1,
            "taken_back": taken_back,
        })

    # Whether `--resume` would accept this file. Asking the same validator keeps this
    # view from printing a command that is going to be refused: a truncated tail, a name
    # that is not a session id, or a trace with no ending are all readable here and none
    # of them is resumable, and the reader should learn that from this screen, not from
    # a second refusal after copying the command.
    resumable: str | None = None
    if expected_sha256 is None:
        try:
            from .discuss import _load_resume_trace

            _load_resume_trace(path)
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


ENDINGS = {
    "eof": "输入结束了",
    "limit": "到了本场请求上限",
    "cancel": "你取消了这一场",
    "failure": "模型请求失败，这一场停在那里",
    "declined": "你说剩下的先不问",
}


def _card_command(database: str | Path | None, candidate_id: str) -> str:
    """`show <id>`, naming the library when it is not the default one.

    The view is store-free and stays store-free: it cannot check the card. What it can do
    is avoid printing a command that would read a different library than the session used,
    which is what `python3 -m dojo show d-...` did for a session opened with `--db`
    (#3419: measured `candidate not found` on a draft the session had just written).
    """
    return commands.dojo("show", candidate_id, db=commands.library_argument(database))


def render_turns(view: dict[str, Any], numbers: list[int]) -> str:
    """A location in the transcript, not a judgment about what it supports."""
    selected = set(numbers)
    turns = [turn for turn in view["turns"] if type(turn["seq"]) is int and turn["seq"] in selected]
    if len(turns) != len(selected) or {turn["seq"] for turn in turns} != selected:
        raise TranscriptError("指定轮次缺失或编号不唯一；请回到清单核对")
    lines = [f"会话 {view['session']} 的原话定位（仅列指定轮次的用户原话；完整上下文见本场 transcript）"]
    if not view["complete"]:
        lines.append("这份轨迹未完整结束；下面只显示已写下的部分。")
    for turn in turns:
        lines.append(f"  [{turn['seq']}] 你说：{turn['said']}")
    return "\n".join(lines) + "\n"


def render(view: dict[str, Any], *, database: str | Path | None = None) -> str:
    """The screen a person reads. Facts first; the one judgement this view makes is
    that it does not make one about whether an answer fit its question.

    `database` is the library this view was asked about -- the one the caller's command
    line named. It is passed in rather than read out of the trace: the trace records what
    he said, and a host's SQLite path is not part of that. Omitted or equal to the default
    library, the commands print their short form.
    """
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
            if part["taken_back"]:
                lines.append("    你后来退回了这一题（改回上一题）。")
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
        lines.append("    看当前库记录（不是本场认可历史）：" + _card_command(database, view["saved"][0]))
        if view["draft"]:
            lines.append("最后展示的待定版本没有得到本场认可：" + view["draft"] + "。")
    elif view["draft"]:
        # A draft ID may point at an already-stored wording. The trace can speak
        # for this session, not for recognition by any other session.
        handed_id = (view["handed"].get("candidate")
                     if isinstance(view["handed"], dict) else None)
        if handed_id is not None and handed_id == view["draft"]:
            lines.append(
                "这一场结束时桌上仍是 " + view["draft"]
                + " 那句话；本场没有认可这版说法。"
            )
            # What the handout row actually records about the card it was given. The view
            # has no store, so it says only what that row holds -- a status, not a guess
            # about who agreed to what and when.
            status = view["handed"].get("status")
            lines.append(
                "    这张卡是开场交给本场的那一张（记录里的状态：" + str(status or "未记")
                + "）。"
            )
        else:
            lines.append("这份轨迹记录了本场未认可的待定版本；它不是本场的结论。相关卡片："
                         + view["draft"] + "。")
        # A bare id is not something a first-time reader can act on; this view exists
        # because that gap had already shipped once.
        lines.append("    看它：" + _card_command(database, view["draft"]))
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

    # Which library the commands above are about. Named only when `--db` was given: with
    # no library on the command line there is nothing to say, and a sentence about the
    # default location would be noise on the common path.
    if commands.library_argument(database) is not None:
        lines.append("卡片命令带的是这个库：" + str(commands.absolute(database)))
    lines.append("")
    lines.append("这些话是材料，不是结论：回看只说你说过什么，不判哪句答到了点上，也不代表你认可了哪条结论。")
    if view["complete"] and view["session"] and (view["saved"] or view["draft"]):
        lines.append("看本场留下的版本和草稿（需要原库，只读，不请求模型）：" + commands.dojo(
            "distill", "--session", view["session"], "--text", "--trace", commands.absolute(view["path"]),
            db=commands.library_argument(database),
        ))
    if view.get("resumable"):
        # Never print a command that is going to be refused.
        lines.append("这一份不能接着谈：" + view["resumable"] + "。")
    else:
        lines.append(
            "接着谈这一场：" + commands.dojo("discuss", "--resume",
                                              commands.absolute(view["path"]),
                                              db=commands.library_argument(database))
        )
    return "\n".join(lines) + "\n"


def load_and_render(path: Path, *, database: str | Path | None = None) -> str:
    return render(load(path), database=database)


__all__ = ["TranscriptError", "PART_READINGS", "load", "render", "load_and_render"]
