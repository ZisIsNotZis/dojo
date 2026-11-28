"""His own words, kept beside the card -- and every screen that has to say whose they are.

The product has always said what it is for in one line: four of the six things a dao is
made of (情境、张力、代价、失效) have to come out of his mouth, or the item is 合写 and its
`part_sources` says 系统补. `discuss` asks the four questions, keeps his answers in the
trace -- and then the card records every one of them as 系统补 forever, because nothing
ever moved an answer from the trace onto the card. Measured on the standard CLI
(`.scratch/3474/probe_promote.py`): four concrete answers, `collected: true` on all four,
`part_sources` = 系统补 ×6, `promoted: []`. A later session was handed the model's
boundary and none of his.

Two words were doing one job in that reading, and this module exists to keep them apart:

  收下（kept）      his sentence is on disk, in this session's record. That was already
                    true, and the receipt already said so -- honestly, and uselessly,
                    because it also said 没有写进卡片.
  这一件有材料了      the card now carries that sentence, in his words, with the record of
  （promoted）      which session said it and when. That is a different fact and it needs
                    its own record. Nothing here infers it: `promote_answers` writes it
                    from a trace row, and a part with no such row stays 系统补.

What promotion deliberately does NOT do, because each would make the screen lie:

  rewrite the sentence   his condition does not become the card's `scope`, and his cost
                         does not become its `contradictions`. Moving words into a field
                         would turn the model's phrasing into his, which is the defect in
                         the other direction. The answers sit beside the card under their
                         own heading, quoted verbatim.
  add a source           a source is provenance for the *claim*. His answer is material
                         about the claim, not a second arrival at it, so independence and
                         `broadcast` do not move (and `wording_digest` does not change, so
                         an acceptance of the wording stays valid).
  change the status      a card with answers is not thereby discussable, true, or agreed.

The one thing that does change: the person's own search can now find the card by the words
*he* used, because those words are on the card. That is the whole point of keeping them.
The model-facing retrieval reach is left exactly as it was -- the answers are shown to the
model only when a card is handed to a session, where a person has already chosen it.
"""
from __future__ import annotations

from typing import Any

from .storage import PART_KEYS_BY_FIELD

# The four parts `discuss` asks, by the field key the card stores. The mapping is declared
# once, in `storage`, because that layer orders and searches the answers; this module only
# decides how to say them on a screen. `test_answers.py` pins it against `elicit.PART_KEYS`.
PARTS: dict[str, str] = dict(PART_KEYS_BY_FIELD)

# What a part is called on screen when his answer to it is printed. Short, because the
# answer beside it is the point; the field key is what the ledger stores.
PART_LABELS: dict[str, str] = {
    "situation": "什么时候会这么做",
    "tension": "哪件好事会跟着变差",
    "price": "谁要多花什么",
    "off": "什么时候反而不对",
}


def stored(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The answers this card carries, by field key, with anything malformed dropped.

    Accepts either a stored card state or a retrieval row: `Store` puts the table's rows
    on the row it hands the screen under this one key, so a screen function never has to
    know which of the two it was given.

    A card from an older library has no `answers` key at all, and that is not "he said
    nothing": it is "nothing was recorded here". Callers print nothing for it.
    """
    value = state.get("answers")
    if not isinstance(value, dict):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for key, item in value.items():
        if key not in PARTS or not isinstance(item, dict):
            continue
        answer = item.get("answer")
        if not isinstance(answer, str) or not answer.strip():
            continue
        result[key] = item
    return result


def answers_text(state: dict[str, Any]) -> str:
    """The answers as searchable text, for the person's screen only (see module docstring)."""
    return " ".join(str(item.get("answer", "")) for item in stored(state).values())


def screen_lines(state: dict[str, Any], indent: str = "  ") -> list[str]:
    """Show the attached quote and its origin, never a route into the full session."""
    answers = stored(state)
    if not answers:
        return []
    lines = [indent + "他的话（库里存的原话，附在这张卡上；不是这张卡措辞的一部分）："]
    for key, part in PARTS.items():
        item = answers.get(key)
        if item is None:
            continue
        label = PART_LABELS.get(key, part)
        when = str(item.get("at") or "")[:10]
        # Provenance is recorded, not inferred from a session ID supplied to promote.
        from_discussion = item.get("provenance") == "discussion"
        recorded = item.get("recorded")
        if from_discussion and item.get("session"):
            by = "，".join(value for value in (
                "来自会话 " + str(item["session"]),
                ("记于 " + when) if when else "",
            ) if value)
        elif item.get("provenance") == "manual":
            # No brackets of its own: the caller wraps this in a pair.
            by = "手工附上的，不在任何一场会话记录里"
        else:
            # A row from a library written before provenance was stored. The session id, if
            # there is one, is still a stored fact worth printing -- it is only the claim
            # "this was said in that discussion" that is missing. Said without brackets of
            # its own, so the line does not end in doubled parentheses.
            by = ",".join(value for value in (
                ("会话号 " + str(item["session"])) if item.get("session") else "",
                "来源未记录：这个库比记录来源的版本早",
            ) if value)
        lines.append(
            indent + "  " + label + "（" + part + "）：「" + str(item["answer"]) + "」"
            + ("（" + by.strip("（）") + "）" if by else "")
        )
        if from_discussion and recorded == 0:
            lines.append(indent + "    这句没有写进那一场的记录文件。")
    missing = [PARTS[key] for key in PARTS if key not in answers]
    if missing:
        lines.append(
            indent + "  这几件这张卡上没有他的话：" + "、".join(missing)
            + "；空着就是没有，不等于他没有说过。"
        )
    return lines


def screen_note(state: dict[str, Any], indent: str = "  ") -> str | None:
    """One line saying how much of the card is his, and how much is not.

    Only the count, and only over the four parts `discuss` asks. Attribution of the other
    two (动作/归属) is the dao projection's job, not this card's.
    """
    answers = stored(state)
    if not answers:
        return None
    said = [PARTS[key] for key in PARTS if key in answers]
    missing = [PARTS[key] for key in PARTS if key not in answers]
    line = (indent + "这 " + str(len(said)) + " 件是他说的：" + "、".join(said))
    if missing:
        line += "；" + "、".join(missing) + " 没有他的话"
    return line + "。这些回答有没有答到点上，库里不判；它只记下他说的字。"


def for_model(state: dict[str, Any]) -> dict[str, Any]:
    """The answers as data for a handed-over session, with their own provenance rules.

    Shaped like the source records in `handoff_for_model`: verbatim, keyed, and labelled
    with the one warning that matters -- these are his words about the claim, not the
    claim's wording, so the model may quote them as what he said and may not cite them as
    agreement with, or a second source for, the sentence.
    """
    answers = stored(state)
    if not answers:
        return {}
    return {
        key: {
            "part": PARTS[key],
            "answer": item.get("answer"),
            "session": item.get("session"),
            "at": item.get("at"),
            "is": "他本人在讨论里说过的原话；是这张卡的材料，不是它的措辞，也不是对它的赞同",
        }
        for key, item in answers.items()
    }
