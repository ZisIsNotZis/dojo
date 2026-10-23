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


def classify_answer(text: str) -> str:
    """A crude, declared reading: does this answer count as an answer at all?

    It does not judge whether the answer *fills* the part (that is `to_fill`, judged by a reader);
    it only separates a real attempt from an empty one, a declared non-answer, or a form-like reply.
    """
    value = (text or "").strip()
    if not value:
        return "none"
    if value.lower() in STRUCTURED:
        return "structured"
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
