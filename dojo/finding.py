"""What a person sees when they look for a sentence they only half remember.

The product had one retrieval exit for people (`dojo search`) and it printed the same
JSON block `retrieve` gives a caller: whole cards, every field, sorted by word overlap,
with no line saying what to do next. #3436 measured what that cost on the standard CLI,
three ways:

  missed      he typed the sentence the way he now remembers it, the card said the same
              thing in other words, no row overlapped, and the screen said nothing at
              all -- a bare `"results": []` that reads as "the library has nothing".
  hidden      the card he was thinking of had been `challenge`d since. The gate is
              right to keep it out of the material handed to a model, but the same gate
              printed nothing to the person, so the one card with his sentence *and*
              the doubt on it was the one card he could not find.
  rewritten   the card had been revised; he remembered the wording that was replaced,
              and retrieval matched only what the card says now, so the old wording --
              which the ledger still holds verbatim -- was unsearchable.

The supervisor then reported the fourth and worst shape of the same bug on a released
build: two cards about the same night-shift practice, one of them challenged, and after
the challenge the *only* thing the words found was the card saying the opposite. A list
that silently drops his own sentence next to a card that argues against it is worse than
no list, because what is left looks complete.

So this screen prints one ordered list, and each entry says out loud whether retrieval
would hand it over or not, and why. The refused ones are not a footnote: they are what
he came for when his card changed under him. What the screen does not do is decide for
him -- it prints the stored sentence, its conditions and counterexamples, where its
source records came from, and a command that runs, and it names which of those facts
came from the library and which from this program's own method.

Nothing is inferred here. Every line is a stored value, a count of stored values, or a
statement about this program's own method ("only words that overlap"). Where the library
cannot answer, no line is printed rather than a comfortable one.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import commands
from . import answers as answers_module
from .discuss import (
    HANDOFF_STATUS_WORDS,
    acceptance_line,
    boundary_lines,
    source_lines,
    source_summary,
)

# How many cards the screen itemises before it counts the rest. A reader who remembers
# one sentence does not need a wall of near-misses; the count is a fact about the
# library and says nothing about the ones it does not print.
SCREEN_LIMIT = 6
# How many of the library's most recently written cards are offered when the words match
# nothing. Three is a way in, not a listing: enough to recognise the one he meant, short
# enough not to become a browsing screen with no query behind it.
SCREEN_RECENT = 3


def _quote(value: Any) -> str:
    return "「" + str(value) + "」"


def _acceptance(row: dict[str, Any]) -> dict[str, Any]:
    """The row's own `time_basis` facts, in the shape `acceptance_line` reads."""
    return {
        "accepted": bool(row.get("accepted_at")),
        "path": row.get("acceptance_path"),
        "accepted_at": row.get("accepted_at"),
        "agreed_at": row.get("agreed_at"),
    }


def _where_the_words_are(row: dict[str, Any]) -> str | None:
    """Say which part of the card the words came from, when it was not its sentence.

    The entry's headline already says how many words overlapped, and the sentence is
    printed on the very next line. #3436's second round measured what that reads as when
    the overlap came from somewhere else -- twice:

      outside  a card saying "值班通知交系统跑。" whose *condition* was the searched
               phrase printed "对上 8 个词：会当、场损…" over a sentence sharing none of
               them. The reader's reasonable reading -- "this is the sentence I
               remember" -- was false, and the words were two lines below under a label
               that does say 什么时候成立, so the facts were on screen and the
               connection was not.
      alias    an `alias` match reported itself as `current`, so no note printed at
               all: the reader was told the sentence matched when the sentence shared
               zero bigrams with his words.

    So the note names the part, and quotes the alias when an alias is what matched --
    the same rule as everywhere else here: a stored value, verbatim, or no line.
    """
    parts = [part for part in row.get("matched_in") or [] if isinstance(part, str)]
    if not parts:
        # An older store or a row from before this key: say nothing rather than guess.
        return None
    if "sentence" in parts:
        return None
    aliases = [value for value in row.get("aliases") or [] if isinstance(value, str)]
    if "earlier" in parts:
        # `_matched_note` owns this case: it quotes the earlier wording and says the
        # card now says something else. Two notes about the same fact is how a screen
        # starts contradicting itself.
        return None
    where = []
    if "limits" in parts:
        where.append("它写的条件或反例")
    if "sources" in parts:
        where.append("它的来源记录")
    alias_part = "alias" in parts
    # His own answer, when that is what matched. A distinct sentence, because "this is
    # the card whose story I told" and "this is the sentence I remember" are different
    # finds -- and the answer is printed below under its own heading, so the reader can
    # check it without leaving the screen.
    answers_part = "answers" in parts
    if not where and not alias_part and not answers_part:
        return None
    if answers_part:
        line = ("  你记得的字不在卡片写的那句里，而在附在这张卡上的你的原话里"
                "（原样印在下面的「他的话」）；卡片本身那句和这些词没有重叠。")
        return line
    if where:
        line = ("  你记得的字不在本条目开头引的那句里，而在" + "、".join(where) + "里"
                "（原样印在下面）；卡片本身的那句和这些词没有重叠。")
    else:
        line = "  卡片现在写的那句和这些词没有重叠。"
    if alias_part:
        # Only the aliases that actually share a term: quoting an unrelated one would be
        # a new claim about his words. `matched_terms` is the same set the count line
        # above already printed, so the quote and the count cannot disagree.
        shared = [value for value in aliases if _shares_a_term(value, row)]
        if shared:
            line += "\n  它还有另一种说法，和你记得的字对得上（库里存的原文）：" + _quote(shared[0])
    return line


def _shares_a_term(value: str, row: dict[str, Any]) -> bool:
    """Whether this alias holds one of the terms the row says matched.

    Read from the row's own `matched_terms`, not from a fresh tokenisation of the card:
    the terms on the row are what the count line already printed, so the alias quoted
    here and the count above it cannot disagree.
    """
    from .storage import lexical_terms

    terms = {term for term in row.get("matched_terms") or [] if isinstance(term, str)}
    return bool(terms & lexical_terms(value))


def _matched_note(row: dict[str, Any]) -> str | None:
    """Say which wording the words matched, when it was not the one the card holds now."""
    if row.get("matched_on") not in ("earlier", "current_and_earlier"):
        return None
    earlier = row.get("matched_wording")
    if not isinstance(earlier, str) or not earlier.strip():
        return None
    # Both lines are above this one in the entry (`_entry` prints the sentence first,
    # then this note), so naming a direction is a claim about layout that can silently
    # invert. The supervisor read it on a terminal with the old wording: the current
    # sentence sat above and the note said "下面这句是它现在的说法", which points the
    # reader at the note itself. So it names the sentence's role, not its position.
    return ("  你记得的字对上的是它以前的说法：" + _quote(earlier)
            + "；库里这一句后来换过，卡片现在写的是本条目开头引的那句。")


def _status_note(row: dict[str, Any]) -> str:
    """The stored status, in words -- and the one thing status alone cannot say."""
    status = str(row.get("status") or "")
    words = HANDOFF_STATUS_WORDS.get(status, status)
    if row.get("unaccepted_draft"):
        # `is_unaccepted_draft`: the whole provenance is a model-written wording nobody
        # accepted. This is a shape read from the card, so it is said as a fact about
        # the record, not as "nobody ever agreed" -- he may have agreed elsewhere.
        words += "；这一版是模型写的，库里没有谁认领过它"
    return words


# What each refusal code means, in the words a person uses. Only codes the store emits
# appear here; an unknown one is reported as unreadable rather than guessed at.
REFUSAL_WORDS = {
    "withdrawn": "这张卡被撤回过",
    "no_acceptance_record": "这个库里没有这套说法的认可记录，这不等于没人认可过它",
    "challenged": "这张卡被人质疑过",
    "acceptance_superseded": "有人认可过它以前的说法，后来那句被改掉了，现在这版没有对应的认可记录",
}


def _refusal(row: dict[str, Any]) -> tuple[str, list[str]]:
    """(one line saying whether retrieval hands this card over, plus detail lines)."""
    refused = row.get("refused")
    if not isinstance(refused, dict):
        return "  检索会把这一版交出去（可以带进新讨论）；下面是它自己的条件。", []
    codes = [code for code in refused.get("codes") or [] if isinstance(code, str)]
    reasons = [REFUSAL_WORDS[code] for code in codes if code in REFUSAL_WORDS]
    if "redirected" in codes:
        reasons[0] = "它被合并到了 " + str(refused.get("redirect_to") or "另一张卡")
    if not reasons:
        reasons = ["检索不收它，具体原因这次没有读出来"]
    # One cause is enough on the first line; the rest are named on their own so a card with
    # three reasons does not become a 60-character parenthesis (measured on a terminal).
    head_reason, rest = reasons[0], reasons[1:]
    # No separate "latest doubt" line: `boundary_lines` prints every stored
    # counterexample verbatim, so the doubt that caused the refusal is already the last
    # line under 什么时候不成立. Printing it twice would make the screen look like it
    # found two doubts.
    head = ("  检索不会把它当答案交出去（" + head_reason + "）。"
            "这不等于库里没有它：它就在这里，条件照原样印在下面。")
    return head, ["  也因为这个：" + reason for reason in rest]


def _entry(index: int, row: dict[str, Any], database: str | Any) -> list[str]:
    """One card: what it says, what limits it, what it stands on, and how to take it on."""
    terms = "、".join(row.get("matched_terms") or [])
    lines = [
        str(index) + ". " + str(row.get("id")) + "  " + _status_note(row)
        + "  对上 " + str(row.get("score")) + " 个词" + ("：" + terms if terms else ""),
        "  " + _quote(row.get("statement")),
    ]
    head, extra = _refusal(row)
    lines.append(head)
    lines.extend(extra)
    # Before the rewrite note: "where the words are" answers "did I find the right
    # card", and the rewrite note answers "did it change under me". The two do not both
    # print for the same card (the earlier-wording case is that note's own).
    location = _where_the_words_are(row)
    if location:
        lines.append(location)
    earlier = _matched_note(row)
    if earlier:
        lines.append(earlier)
    lines.extend(boundary_lines(row))
    # His own words, after the card's own boundary and before its provenance: the
    # boundary is what the card claims, this is what he said about it, and keeping them
    # in that order is the difference the whole slice is about. Absent for a card with
    # nothing stored, so every existing entry keeps the bytes it had.
    answered = answers_module.screen_lines(row)
    if answered:
        lines.extend(answered)
    sources = source_summary(row)
    if sources:
        lines.append("  " + sources)
        lines.extend(source_lines(row))
    # The refusal line already states the acceptance fact when that is why it was refused;
    # printing `acceptance_line` under it said the same thing twice on one card (measured on
    # a terminal: "这个库里没有这套说法的认可记录" appeared twice, two lines apart).
    codes = (row.get("refused") or {}).get("codes") if isinstance(row.get("refused"), dict) else []
    said_already = bool({"no_acceptance_record", "acceptance_superseded"} & set(codes or []))
    if not said_already:
        recorded = acceptance_line(_acceptance(row))
        if recorded:
            lines.append(recorded)
    # Not a promise about what the session will do with it: `discuss --card` refuses a
    # redirected or superseded card, and prints this card's status and limits before the
    # model speaks. The command is printed for every entry because it is also the way to
    # look again -- and a person who cannot even open the card is being told to leave.
    lines.append("  带进一场新讨论：" + commands.dojo("discuss", "--card", row.get("id"), db=database))
    return lines


def _recent(result: dict[str, Any], database: str | Any) -> list[str]:
    """Last resort when no words overlap: recent cards, named as a different method."""
    recent = [row for row in result.get("recent") or [] if isinstance(row, dict)]
    if not recent:
        return []
    lines = [
        "",
        "  换个办法：下面是这个库里最近写下的 " + str(len(recent)) + " 张卡，"
        "按写入时间排的，不是按意思找出来的。",
        "  能不能认出你要的那句，由你看；程序不替你挑。",
    ]
    for row in recent:
        head, extra = _refusal(row)
        lines.append("  - " + str(row.get("id")) + "  " + _status_note(row))
        lines.append("    " + _quote(row.get("statement")))
        lines.append("  " + head.strip())
        lines.extend(extra)
        for line in boundary_lines(row):
            lines.append("  " + line)
        for line in answers_module.screen_lines(row):
            lines.append("  " + line)
        lines.append("    带进一场新讨论：" + commands.dojo("discuss", "--card", row.get("id"), db=database))
    return lines


def library(database: str | Any) -> Path | None:
    """The library as an absolute path, or None when the caller did not say.

    #3419 established the rule for every command this program prints: it must mean the
    same file from any directory and any terminal. `Store.path` is the path *as given*,
    so `--db run/dojo.sqlite3` reached this screen as a relative path and the printed
    `--card` line broke the moment the reader pasted it somewhere else -- reproduced by
    the supervisor on the ordinary path, not in a corner. Resolving here, at the moment
    of printing, is the only place that knows what the reader's terminal considered the
    file to be.
    """
    if database is None:
        return None
    return commands.absolute(Path(str(database)))


def search_screen(result: dict[str, Any], *, database: str | Any) -> list[str]:
    """The lines a person reads after `dojo search <words>`, without the JSON.

    Separated from the printing so the readings in `docs/evidence` can assert on the
    lines rather than on the whole stream.
    """
    database = library(database)
    query = str(result.get("query") or "")
    hits = [row for row in result.get("results") or [] if isinstance(row, dict)]
    refused = [row for row in result.get("withheld") or [] if isinstance(row, dict)]
    # One list in one order. Wording first, then how many words overlapped, then id:
    # #3436's second round measured the old order putting a card whose *condition line*
    # was the searched phrase above the card that actually says the sentence (both at 16
    # terms, so id order decided). A reader who remembers a sentence is looking for the
    # sentence, and "the words are in its limits" is the weaker answer -- still worth
    # printing, but not above the stronger one. This is an order of the screen's list
    # only: the store's `results` keep the order they came in, so no caller is affected.
    ordered = sorted(hits + refused, key=lambda row: (
        0 if "sentence" in (row.get("matched_in") or []) else 1,
        -int(row.get("score") or 0), str(row.get("id"))))
    lines = ["在这个库里找：" + _quote(query)]

    if ordered:
        # The order sentence only prints when there are two of them: with one card,
        # "sorted by ..." describes a comparison that never happened.
        ordering = ("本条目写的那句先排，再按重叠的词数；不是按意思或可信程度排的。"
                    if len(ordered) > 1 else
                    "这只是字词的重叠，不是按意思或可信程度找的。")
        if refused:
            lines.append("  " + str(len(ordered)) + " 张卡的字和这些词重叠：" + str(len(hits))
                         + " 张检索会交出去，" + str(len(refused)) + " 张不会"
                         + "（每张下面都说了为什么）。" + ordering)
        else:
            lines.append("  " + str(len(ordered)) + " 张卡的字和这些词重叠：" + ordering)
        for index, row in enumerate(ordered[:SCREEN_LIMIT], start=1):
            lines.extend(_entry(index, row, database))
            lines.append("")
        if len(ordered) > SCREEN_LIMIT:
            lines.append("  还有 " + str(len(ordered) - SCREEN_LIMIT) + " 张没印在这里。")
        if len(ordered) > 1:
            lines.append("  每句都是库里存的原话，可以逐条比；程序不替你挑哪条是你要找的。")
    elif not (result.get("matched_terms") or []):
        # A query with no searchable term is not a miss: there were no words to compare.
        # Printing "没有一张卡的字和这些词重叠" above an empty query would claim a search
        # that never happened (seen on a terminal: `search ''`).
        lines.append("  没有给出可以找的词。写几个字，或者看下面最近写下的卡。")
    else:
        # Deliberately not "库里没有这句": the library was asked about *words*, and the
        # method is the one thing this program can speak for. Saying it plainly is what
        # keeps a miss from reading as a fact about the library.
        lines.append("  没有一张卡的字和这些词重叠。检索只比字词，不认意思，"
                     "所以换个说法（你记得的原话、人名、场合、当时的说法）再找一次，可能就对上了。")
    if not ordered:
        # Both no-word and no-overlap cases get the same way in, because "I cannot name
        # one word" and "none of my words matched" are the same situation to him.
        lines.extend(_recent(result, database))
    return lines
