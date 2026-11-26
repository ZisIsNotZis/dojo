"""docs/evaluation.md §4 的 source trace：把 C 条件下每条主张追回 seed，追不到就记 untraced。

这不是判真假。一个主张能追到 seed，只说明它没有超出被给的材料；
seed 本身可能是模拟材料或未核验报告，这一点由 verification 原样带出，不在此处升级。

两条硬判据（无阈值、无启发式）：
  - 必须给 seed_id，且该 ID 必须真的存在于 seed 包里；
  - 必须给 quote，且去掉空白后的 quote 必须真的出现在那条 seed 里。

一条软判据（保守近似，会偏向报异常）：当主张声明 `extends=False`（没超出原句）时，
用它有多少字符能按顺序在 seed 原文里找到来判「是不是真的在改述」。找不到的越多，
越像把模型推断伪装成 seed 原句。阈值 0.9 是为了放过少数虚词差异（如「有人」对
「一名模拟角色」），而不是让重写通过；阈值写在这里，改它要当改判据处理。

刻意不用字面相似度给 status 打分：与 seed 几乎同构却没给 ID 的主张必须判 untraced。
靠重合度算分会把「复述」当成「可追溯」，那正是 §4 明令禁止的伪造引用。
"""
from __future__ import annotations

TRACED = "traced"
UNTRACED = "untraced"
RESTATEMENT_THRESHOLD = 0.9


def _normalise(text: str) -> str:
    """去空白后再比，避免排版差异被当成引文不符。"""
    return "".join(str(text).split())


def _ordered_coverage(claim: str, source: str) -> float:
    """claim 有多少比例的字符能按原顺序在 source 里找到（子序列匹配）。"""
    if not claim:
        return 1.0
    cursor = 0
    matched = 0
    for char in claim:
        found = source.find(char, cursor)
        if found >= 0:
            matched += 1
            cursor = found + 1
    return matched / len(claim)


def _field(item: dict, name: str) -> str:
    value = item.get(name)
    return value if isinstance(value, str) else ""


def audit_claim(item: dict, seeds: dict[str, str], verification: dict[str, str] | None) -> dict:
    reasons: list[str] = []
    notes: list[str] = []
    seed_id = _field(item, "seed_id")
    quote = _field(item, "quote")
    statement = _field(item, "text")
    extends = item.get("extends")

    seed_text = None
    if not seed_id:
        reasons.append("no_seed_id")
    elif seed_id not in seeds:
        reasons.append("unknown_seed_id")
    else:
        seed_text = seeds[seed_id]

    normal_quote = _normalise(quote) if quote else ""
    if not quote:
        reasons.append("no_quote")
    elif seed_text is not None and normal_quote not in _normalise(seed_text):
        reasons.append("quote_not_in_seed")

    if seed_text is not None and not reasons:
        if extends is True:
            notes.append("extends_seed_sentence")
        elif extends is False:
            coverage = _ordered_coverage(_normalise(statement), _normalise(seed_text))
            if coverage < RESTATEMENT_THRESHOLD:
                reasons.append("undeclared_extension")
                notes.append(f"restatement_coverage={coverage:.2f}")
        else:
            reasons.append("extension_flag_missing")

    status_level = (verification or {}).get(seed_id) if seed_id else None
    if item.get("as_verified") and status_level in {"unverified", "not_evidence", "unknown", "disputed"}:
        reasons.append("unverified_report_stated_as_fact")

    return {"text": statement, "seed_id": seed_id or None, "quote": quote or None,
            "status": TRACED if not reasons else UNTRACED,
            "reasons": reasons, "notes": notes, "verification": status_level}


def audit_traces(claims, seeds: dict[str, str], *, verification: dict[str, str] | None = None) -> list[dict]:
    """逐条给 status + 理由。只读：不改 claims，不写任何存储。"""
    if not isinstance(claims, list):
        raise ValueError("claims must be a list")
    for item in claims:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str) or not item["text"].strip():
            raise ValueError("each claim needs a non-empty text")
    return [audit_claim(item, seeds, verification) for item in claims]


def coverage(results: list[dict]) -> str:
    """§5 的「全/部分/无」三态，不接受别的写法。"""
    if not results:
        return "none"
    traced = sum(1 for r in results if r["status"] == TRACED)
    if traced == len(results):
        return "full"
    return "partial" if traced else "none"
