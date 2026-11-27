#!/usr/bin/env python3
"""How the classifier reads wind-down sentences vs. real material.

    python3 docs/evidence/2026-11-27-typed-stop/probe_winddown_corpus.py [tree]

`tree` defaults to the repository this file lives in, which is what the SUMMARY's
advice ("先把候选句放进这里跑一遍") assumes. This copy lives beside that SUMMARY: the
earlier version pointed at a `.scratch` script that is not in the tree, so the advice
could not be followed by anyone reading the repository.

No model, no network: only the declared reading.
"""
from __future__ import annotations

import sys
from pathlib import Path

if len(sys.argv) > 1:
    ROOT = Path(sys.argv[1]).resolve()
else:
    ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import dojo.elicit as elicit  # noqa: E402
from dojo.elicit import classify_answer, skip_scope, is_skip_request, reads_like_a_skip_request  # noqa: E402

assert Path(elicit.__file__).resolve().is_relative_to(ROOT), "导入的不是被测那棵树"

WIND_DOWN = [
    "算了，先不说了",
    "算了",
    "算了，不聊了",
    "先到这吧",
    "就到这吧",
    "到这吧",
    "先到这里",
    "就到这里吧",
    "到这里为止",
    "不想聊了",
    "不聊了",
    "先不聊了",
    "就说这么多吧",
    "就说这些",
    "说到这儿吧",
    "先这样吧",
    "就这样吧",
    "今天先这样",
    "我没什么要补充的",
    "没什么要补充的了",
    "先撤了",
    "我得走了",
]

# Sentences that must keep being read as his material: the fix must not swallow these.
MATERIAL = [
    "上一次为了做到它，我推掉了两个会",
    "我跳过这一步的时候就会出错",
    "剩下的流程我都不讲给新人听",
    "那天下雨，我就没去成",
    "记不清了，大概耽误了半天",
    "我算了吧，这事我后来没再提",
    "就这样吧，我们当时是这么定的",
    "聊了半小时才说服他",
    "说到这儿我想起来，那次是周三",
    "我不想说了这句话本身是我当时的原话",
]

# Existing behaviour that must not change: these are single-question skips.
SKIPS = [
    "跳过",
    "这题先跳过",
    "先跳过这一题",
    "不想说",
    "不说了",
    "下一题",
    "能先跳过这一题吗",
]


def show(title, phrases):
    print("=" * 78)
    print(title)
    for phrase in phrases:
        print(
            f"  {phrase:<28} reading={classify_answer(phrase):<9}"
            f" scope={str(skip_scope(phrase)):<5}"
            f" skip_req={str(is_skip_request(phrase)):<5}"
            f" mentions={reads_like_a_skip_request(phrase)}"
        )


show("收场话（现在被读成回答，正是缺陷）", WIND_DOWN)
show("材料（必须仍是 answer）", MATERIAL)
show("已有的跳过（行为不能变）", SKIPS)
