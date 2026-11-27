"""四句问法，和「谁写的」这条规则——产品里唯一的一份。

一条道里他说的是动作；另外四件（情境、张力、代价、失效）得从他嘴里出来，否则就是系统补、
条目就是「合写」。这四句在讨论里被真的问出来（`dojo/discuss.py`），也被演练工具引用
（`scripts/dao_elicit.py`）——所以它们放在这里，而不是一份文档里。

问法的三条硬规则：
- 一次只问一件；每件最多两轮（一问，加一次换问法），两轮没有就停，不问第三遍。
- 问不出来不填：那一件留「系统补」，条目留「合写」。这是产品的一个状态，不是失败。
- 不给表单、不给编号、不给进度条；他是在谈话，不是在填表。
"""

from __future__ import annotations

import re
from typing import Any

PART_NAMES = ("situation", "tension", "move", "price", "off", "provenance")
PART_LABELS = {
    "situation": "情境",
    "tension": "张力",
    "move": "动作",
    "price": "代价",
    "off": "失效",
    "provenance": "归属",
}
PART_ORDER = ("情境", "张力", "代价", "失效")
PART_KEYS = {"情境": "situation", "张力": "tension", "代价": "price", "失效": "off"}
PART_SOURCES = ("他的原话", "转述", "系统补")

QUESTIONS: dict[str, dict[str, Any]] = {
    "情境": {
        "ask": "什么时候你会这么做、什么时候不会？先说上一次：那天你手上是什么事，卡在哪一步？",
        "failure_mode": (
            "问「在什么情境下？」他会答一个领域名（「工作里」「生活里」），那是词不是处境；"
            "只问「上次」会得到一个故事，而没有他说的条件。所以一句里要同时要条件和一次具体的事。"
        ),
        "follow_ups": {
            "another_rule": "这条我记下了。我要的不是还要做什么，而是：那天是什么情况让你这么做？没那种情况，你会不会也这么做？",
            "none": "那换个问法：上一次你差点没这么做，是因为什么？",
        },
        "to_fill": "一句带「什么时候/什么时候不会」的话，外加一次能对上日期或场合的事；只有场合没有条件，按「答了半句」处理，仍不填。",
    },
    "张力": {
        "ask": "照着这条做，哪件本来也挺好的事会变得差一点？",
        "failure_mode": (
            "问「张力是什么？」是给他上术语课；问「有什么代价？」他会讲一个倒霉的故事；"
            "他也会用「要注意平衡」「因人而异」逃掉——那正是提案里写过的坏写法。所以问「哪件好事会变差」，把两头都摆在他面前。"
        ),
        "follow_ups": {
            "another_rule": "这不是第二件要做的事，是同一件事的另一面：照它做，你手里会少掉什么？",
            "none": "那反过来问：你不想失去的是什么？",
        },
        "to_fill": "一句说出「另一件好事」的话，而且他承认两件不能同时拿满（「要么……要么……」或「只能选一个」）；只说出另一件好事、没说不能同时要，按「半句」处理。",
    },
    "代价": {
        "ask": "这件事落下去，谁要多花时间、谁会不高兴？第一次觉得亏，是什么时候？",
        "failure_mode": (
            "问「代价是什么？」会得到「没什么代价」（因为在他眼里这是建议），或者一句政策。"
            "只问「谁不高兴」他会只想到人、想不到时间；所以一句里同时给时间和人两个槽，再要一次具体的事。"
        ),
        "follow_ups": {
            "another_rule": "这不是代价，是另一条做法。我问的是：照它做，谁的日子变难一点？",
            "none": "那就说一件小事：上一次你为了做到它，耽误了什么？",
        },
        "to_fill": "一句能指出「谁」和「多花了什么」的话（时间、钱、别人的耐心、一次机会）；只说「费劲」而说不出谁、什么，按「半句」处理。",
    },
    "失效": {
        "ask": "有没有一次你这么做，结果反而不对？那次和平时差在哪？",
        "failure_mode": (
            "问「什么情况下不成立？」他会答「因人而异」——这个库自己写过这是坏写法。"
            "先要一次「反着做也对」的经历，失效条件才会落在一个真事上；空想的反例他会顺着你的话编一个。"
        ),
        "follow_ups": {
            "another_rule": "不是再给一条做法。我问的是：一个人处境跟你差不多，照这条做完反而更糟，你觉得最可能是哪里不一样？",
            "none": "那如果换成另一个人来用这条，你最担心哪一点被它带坏？",
        },
        "to_fill": "一句能指认「看到什么就该停/反过来」的话，最好挂在一次真事上；只说「看情况」不算。",
    },
}

NON_ANSWERS = ("不知道", "没有", "不清楚", "说不清", "说不好", "不好说", "因人而异", "看情况", "没什么", "想不起来", "忘了")
STRUCTURED = {"y", "n", "yes", "no", "是", "否", "q", "1", "2", "3", "4", "ok"}

# 「这一题跳过」是一句决定，不是一句回答。以前它被读成 `answer`：屏幕最后说四件都落在
# 他说过的话上，而他在四次里说的是「先跳过这一题」。识别的边界要窄——只认整句就是
# 跳过请求（或后面只跟一句「还没想好」这类交代），因为「我跳过这一步的时候就会出错」
# 是失效那件要的原话，不能当成跳过。
SKIP_PATTERNS = (
    # 跳过 / 先跳过 / 跳过这一题 / 这题先跳过 ...
    r"^(?:那|就|先|我|麻烦|请)*(?:先)?(?:跳过|略过)(?:这|那|这一|这一个|此)?(?:一)?(?:题|件|个|步|条)?(?:吧|了|一下|啦)?$",
    r"^(?:这|那|这一|这一个|此)?(?:一)?(?:题|件|个|步|条)(?:就|先)?(?:跳过|略过)(?:吧|了|一下)?$",
    r"^(?:下一|换一|另)(?:题|个|件|条|步|问)$",
    r"^(?:不想说|不想回答|不想讲|不说了|不答了|不回答|答不上来)(?:了|吧|啦)?$",
    # Asking is how people ask. "能先跳过这一题吗" is the same request with a question
    # mark; it used to be recorded as his answer to the part (measured at the entry
    # point). Only a request whose whole clause *starts* with the asking is allowed.
    r"^(?:能|可以|可不可以|能否|能不能|可以不可以|让我|容我)?"
    r"(?:先|就|我|麻烦|请)*(?:先)?(?:跳过|略过)"
    r"(?:这|那|这一|这一个|此)?(?:一)?(?:题|件|个|步|条)?(?:吗|么|嘛|吧|呢)?$",
    # "这题先跳过，下一题吧" -- a skip followed by a move-on is still a skip of this one.
    r"^(?:这|那|这一|这一个)?(?:一)?(?:题|件|个|步|条)?(?:就|先)?(?:跳过|略过)"
    r"(?:吧|了|一下)?，?(?:下一|换一|另|下)(?:题|个|件|条|步|问)(?:吧|了|啊)?$",
)
# 「算了，先不说了」「先到这吧」「就说这么多吧」不是回答，也不是「答不出来」：他是
# 在说他不想再聊了。以前这类句子被读成 `answer` 存进材料，屏幕还说「你答了 张力」，
# 于是回执描述了一件没发生的事——这不是跳过某一题，也不该被记成他答不出。所以它
# 单列一种结局：`stop`，会话到此为止，回执说「说到这儿为止」，而不是「没答出来」。
#
# 边界必须窄到只认整句。收场话的词很少（到这儿、算了、就这样、这么多），而这些词在
# 真材料里也常出现：「说到这儿我想起来，那次是周三」「就这样吧，我们当时是这么定的」
# 「我算了吧，这事我后来没再提」。所以一律整句匹配，且只允许收场词加语气词，句子里
# 还有别的内容（时间、谁、结果）就不算。
#
# 与 `skip` 的分界：`不想说`「不说了」是这一题不答（已有的跳过），而 `不想聊了`
# 「先到这吧」是这场不聊了。前者说的是问题，后者说的是谈话。
STOP_PATTERNS = (
    # 算了／算了，先不说了／算了不聊了
    r"^(?:那|好|还是)?算了(?:，?(?:就|先|也)?(?:别|不)?(?:说|聊|讲|谈|问)(?:了|吧|啦)?)?$",
    # 先到这吧／就到这儿／到这里为止／说到这儿吧
    r"^(?:那|就|先|我)?(?:先|就)?(?:说)?(?:到|至)这(?:里|儿|块)?(?:为止|就|吧|了|啦)*$",
    r"^(?:那|就|先)?(?:先|就)?(?:说)?到这(?:里|儿)?(?:为止|吧|了|啦)+$",
    # 就说这么多吧／就说这些／就聊到这儿
    r"^(?:那|就|先)?(?:就|先|不)?(?:说|聊|讲)(?:这|那|这么|那么)?(?:多|些|点)(?:吧|了|啦|就行|就好)?$",
    # 先这样吧／就这样吧／今天先这样
    r"^(?:那|好|今天|今晚|现在)?(?:就|先)(?:这样|这么着)(?:吧|了|啦)?$",
    # 我没什么要补充的／没什么可说的了
    r"^(?:我)?(?:也)?(?:没什么|没有)(?:要|可|想)?(?:补充|说|讲|聊|问)的(?:了|吧|啦)?$",
    # 先撤了／我得走了／我先走了／先走一步
    r"^(?:那|好|我|今天|今晚)?(?:先|就)?(?:撤了|撤|走了|走一步|得走|要走了|得走了)(?:吧|了)?$",
    # 不想聊了／先不聊了／不聊了：他说的是谈话，不是这一题
    r"^(?:那|好|我)?(?:先|就|今天|今晚)?(?:不|别)想?(?:再)?聊(?:了|吧|啦)?$",
)

# "用不着" plus a verb is a skip written as a lack of need, e.g. "这题用不着答了".
SKIP_NEEDLESS = "用不着"
# "这题先跳过吧，然后我们下一个" -- the move-on may carry a particle in between.
SKIP_MOVE_ON = ("下一题", "下一个", "换一个", "换一题", "下一个问题", "下一问")
SKIP_HEDGES = ("我还没想好", "还没想好", "没想好", "想不起来", "不确定", "以后再说", "先这样", "回头再说", "暂时不")

# A request about *the questions still to come* is not an answer to the one on screen,
# and it is not the single-question skip either. Two rules keep it honest, both learned by
# putting real sentences through the entry point:
#
# 1. The thing being laid down has to be **the asking**, not a topic. "剩下的流程我都不讲给
#    新人听" is a sentence about a rule -- the rest of a process, told to newcomers -- and it
#    was classified as a stop request, so his material was thrown away and the session
#    ended early. So instead of looking for "skipping" words anywhere, the prefix in front
#    of the verb is read token by token; if anything but scope words and particles is left
#    over (流程, 新人听), it is material.
# 2. How many questions it covers is **parsed, not assumed**. "接下来两题先跳过" covers two,
#    so exactly two are dropped; the old version dropped all of them, which is a bigger
#    decision than he made. When the count cannot be read, the whole rest is *asked* -- an
#    unclear request must not end the session on his behalf.
SKIP_PREFIX_TOKENS = (
    # sentence particles and pronouns
    "好", "那", "那么", "我", "我们", "咱", "咱们", "你", "也", "还是", "而且", "并且",
    # aspect words that carry no count
    "先", "就", "都", "全", "一起", "想", "要", "打算", "继续", "接着", "先不",
    # the remainder itself
    "接下来", "下面", "后面", "之后", "剩下", "剩的", "其余的", "其他", "其它的", "别的",
    "全部", "所有的", "这些", "那些", "这几", "那几", "这", "那", "其", "余", "的", "些",
    # question-shaped measure words -- the only nouns allowed here
    "个", "件", "题", "问", "问题", "几", "多", "两", "这", "那",
)
SKIP_SCOPE_TOKENS = (
    "接下来", "下面", "后面", "之后", "剩下", "剩的", "其余", "其他", "别的", "全部",
    "所有", "这几", "那几", "几", "多", "都", "全",
)
# "however many are left" -- every part after this one. A parsed count is always smaller
# and is used when it is readable.
SKIP_REST_ALL = 99
# Counts above what can be left are read as "all of them": the instruction is still clear,
# it just covers more than the asking has.
SKIP_PREFIX_DIGITS = {"一": 1, "二": 2, "两": 2, "俩": 2, "三": 3, "四": 4,
                      "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
SKIP_REST_VERBS = (
    "跳过去", "略过去", "跳过", "略过", "不答了", "不答", "不说了", "不说", "不讲了", "不讲", "不聊了", "不聊",
    "不回答", "不想答", "不想说", "不想讲", "不想聊", "不想问", "不想停", "免了",
)
SKIP_VERB_TAIL = ("了", "吧", "啦", "一下", "先")
# 「我跳过的这几题」「跳过的那几件」是在描述已经发生的事，不是对还没问的几件下的决定。
SKIP_REST_MATERIAL_PATTERN = re.compile(
    r"(?:跳过|略过|不答|没说|不讲|不回答|不说)的(?:这|那|剩|其余|其他|别的)"
)
SKIP_REST_STORY = (
    "的时候", "那次", "有一次", "因为", "所以", "结果", "上次", "上周", "昨天",
    "那天", "当时", "如果", "要是", "以免", "就会", "总会", "经常", "每次",
)
SKIP_REST_MAX_CHARS = 32


def _normalize_skip(text: str) -> str:
    return "".join(ch for ch in (text or "") if not ch.isspace()).strip("。！？…，,、~～!?.；;")


def _strip_skip_verb(core: str) -> tuple[str, str] | None:
    """Split a request into (prefix, verb). The verb has to end the sentence."""
    if SKIP_NEEDLESS in core and SKIP_NEEDLESS not in SKIP_VERB_TAIL:
        # "这题用不着答了": the lack of need is the verb, and what follows is the manner.
        prefix, _sep, rest = core.partition(SKIP_NEEDLESS)
        rest = rest.rstrip("了啦吧")
        if rest in ("答", "说", "讲", "聊", "问", "回答", ""):
            return prefix, SKIP_NEEDLESS
        return None
    for tail in SKIP_VERB_TAIL:
        if core.endswith(tail) and len(core) > len(tail):
            core = core[: -len(tail)]
    for verb in sorted(SKIP_REST_VERBS, key=len, reverse=True):
        if core.endswith(verb):
            return core[: -len(verb)], verb
    return None


def _consume_tokens(prefix: str) -> str:
    """Remove only scope words and particles, longest first. Whatever is left is content."""
    for token in sorted(set(SKIP_PREFIX_TOKENS) | set(SKIP_PREFIX_DIGITS), key=len, reverse=True):
        prefix = prefix.replace(token, "")
    return prefix


# "改回上一题" -- take back the last thing he did with a part. An explicit instruction, not
# an inference: the shape text tells him to say exactly this, so it has to work.
# Every group is optional except the verb: with all of them optional the pattern matched the
# empty string, so every blank line was read as "take that back" and the part looped forever
# (caught by the all-blank test).
SKIP_BACK_PATTERN = re.compile(
    r"^(?:那|好|还是|算了|不对)?(?:我)?(?:想)?(?:改回|改到|回到|退到)"
    r"(?:刚才|上|上一|前一|前面)?(?:个|件|题|问)?(?:吧|了)?$"
)


def is_back_request(text: str) -> bool:
    """Whether he asked to take back the last part.

    Never true for a blank line. Not to check the pattern but the input: an empty reply is
    "none" in every other reading, and letting it match here silently reopened the same
    part forever (found by the all-blank test, not by reading the regex).
    """
    core = _normalize_skip(text)
    if not core:
        return False
    return bool(SKIP_BACK_PATTERN.fullmatch(core))


def skip_scope(text: str) -> int | None:
    """How many of the questions still to come he asked to lay down, if he asked at all.

    ``None`` means "not a whole-sentence request about the remaining questions": either it
    is an answer, or it is about one question only (that is ``is_skip_request``), or the
    count cannot be read. ``SKIP_REST_ALL`` means "the rest, however many that is".
    """
    core = _normalize_skip(text)
    if not core or len(core) > SKIP_REST_MAX_CHARS:
        return None
    if SKIP_REST_MATERIAL_PATTERN.search(core):
        return None
    if any(marker in core for marker in SKIP_REST_STORY):
        return None
    # A trailing hedge ("这几题先跳过，我还没想好") or a move-on ("…，下一题吧") is
    # allowed and nothing else is: a second clause carrying a claim is material.
    for separator in ("，", ",", "；", ";"):
        if core.count(separator) == 1:
            first, rest = core.split(separator)
            if rest in SKIP_HEDGES or rest.rstrip("了啦吧") in SKIP_HEDGES:
                core = first
                break
            if any(rest.startswith(move_on) for move_on in SKIP_MOVE_ON):
                core = first
                break
    else:
        if any(separator in core for separator in ("，", ",", "；", ";")):
            return None
    split = _strip_skip_verb(core)
    if split is None:
        return None
    prefix, _verb = split
    if not any(token in prefix for token in SKIP_SCOPE_TOKENS) and not any(
        digit in prefix for digit in SKIP_PREFIX_DIGITS
    ):
        return None
    # Content left over means he is talking about something, not asking to stop.
    if _consume_tokens(prefix):
        return None
    for digit, count in SKIP_PREFIX_DIGITS.items():
        if digit in prefix:
            return count
    return SKIP_REST_ALL


def is_skip_request(text: str) -> bool:
    """Whether the person asked to skip *this question*, in plain speech.

    Whole-sentence only: a clause that merely mentions skipping ("我跳过这一步的时候就会
    出错") is material, not a request. A trailing hedge ("先跳过这一题，我还没想好") is allowed.
    A request that covers more than one question is ``skip_scope``'s business, not this
    one's -- but a request for exactly one is still a single-question skip.
    """
    core = _normalize_skip(text)
    if not core:
        return False
    if any(re.fullmatch(pattern, core) for pattern in SKIP_PATTERNS):
        return True
    for separator in ("，", ",", "；", ";"):
        if core.count(separator) == 1:
            first, rest = core.split(separator)
            if any(re.fullmatch(pattern, first) for pattern in SKIP_PATTERNS):
                if rest in SKIP_HEDGES or rest.rstrip("了啦吧") in SKIP_HEDGES:
                    return True
                if any(rest.startswith(move_on) for move_on in SKIP_MOVE_ON):
                    return True
    if SKIP_NEEDLESS in core:
        # "这题用不着答了": the lack of need is a decline. Only accepted when what is
        # left in front of it is this-question material, never a wider scope -- a wider
        # scope needs a count or a remainder word, which `skip_scope` reads.
        prefix, _sep, rest = core.partition(SKIP_NEEDLESS)
        if rest.rstrip("了啦吧") in ("答", "说", "讲", "聊", "问", "回答", ""):
            if not _consume_tokens(prefix):
                return True
    return skip_scope(text) == 1


def reads_like_a_skip_request(text: str) -> bool:
    """Whether a sentence that was kept as material mentions skipping at all.

    This is not a second parser and it decides nothing. It exists so the conversation can
    **say what it understood** when the answer is kept: any whole-clause mention of a skip
    verb that no story marker explains. "剩下那几个我都没讲" is still kept as his words,
    and the screen says so, which is the only thing the person can act on. Replying
    "跳过" then ends the part item for real.
    """
    core = _normalize_skip(text)
    if not core:
        return False
    if any(marker in core for marker in SKIP_REST_STORY):
        return False
    mentions = list(SKIP_REST_VERBS) + [SKIP_NEEDLESS, "跳过去", "略过去"]
    return any(verb in core for verb in mentions)


def is_stop_statement(text: str) -> bool:
    """Whether he said the conversation was over, rather than answering or failing.

    Whole-sentence only, and only the few forms in `STOP_PATTERNS`. Nothing that carries a
    time, a person or a result is a wind-down: that is material (see the corpus test).
    """
    core = _normalize_skip(text)
    if not core or len(core) > 12:
        return False
    return any(re.fullmatch(pattern, core) for pattern in STOP_PATTERNS)


def classify_answer(text: str) -> str:
    """A crude, declared reading: does this answer count as an answer at all?

    It does not judge whether the answer *fills* the part (that is `to_fill`, judged by a reader);
    it only separates a real attempt from an empty one, a declared non-answer, a request to
    skip this one, a request to skip the next few, a wind-down that ends the conversation, or
    a form-like reply.
    """
    value = (text or "").strip()
    if not value:
        return "none"
    if value.lower() in STRUCTURED:
        return "structured"
    scope = skip_scope(value)
    if scope is not None and scope != 1:
        return "skip_rest"
    if is_skip_request(value):
        return "skip"
    if is_stop_statement(value):
        return "stop"
    if value.strip("。！？…，, ") in NON_ANSWERS:
        return "none"
    return "answer"


def authorship(part_sources: dict[str, str]) -> str:
    sources = [(part_sources or {}).get(name, "") for name in PART_NAMES]
    if all(source == "系统补" for source in sources):
        return "系统的"
    if any(source == "系统补" for source in sources):
        return "合写"
    return "他的"


def supplied_parts(part_sources: dict[str, str]) -> list[str]:
    return [PART_LABELS[name] for name in PART_NAMES if (part_sources or {}).get(name) == "系统补"]


def his_parts(part_sources: dict[str, str]) -> list[str]:
    return [PART_LABELS[name] for name in PART_NAMES if (part_sources or {}).get(name) in {"他的原话", "转述"}]


def draft_line(part_sources: dict[str, str]) -> str:
    """What may be said about a draft built from one session."""
    who = authorship(part_sources)
    if who == "他的":
        return "他的（六件都来自他这次说的）"
    if who == "系统的":
        return "系统的（六件都是系统补的）"
    return f"合写（他写了 {'、'.join(his_parts(part_sources))}；系统补了 {'、'.join(supplied_parts(part_sources))}）"
