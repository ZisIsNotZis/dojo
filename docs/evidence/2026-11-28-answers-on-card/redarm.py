"""Does `verify.py` go red when the behaviour it checks is put back?

    python3 docs/evidence/2026-11-28-answers-on-card/redarm.py [worktree]

A green check proves nothing on its own. Each arm restores exactly one earlier behaviour
in a copy of the tree and runs the real `verify.py` there -- the same entry a reader
re-runs. An arm counts only when the *named* check fails.

The first arm is the released behaviour this slice exists to change: nothing ever moved
an answer from the session record onto the card. The second and third are the two defects
my own walk found after I thought the slice was finished -- the matcher reading answers
from a dict that does not hold them, and the handout forgetting them -- kept as arms
because each produced a screen that looked fine and claimed something false.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1
            else Path(__file__).resolve().parents[3]).resolve()
VERIFY = "docs/evidence/2026-11-28-answers-on-card/verify.py"

ARMS = [
    (
        # The whole slice, undone: the questions are asked and nothing reaches the card.
        "answers-never-reach-the-card",
        "dojo/discuss.py",
        "            if rows:\n"
        "                try:\n",
        "            if False:\n"
        "                try:\n",
        "四件的原话都在卡上，各在自己的那一栏",
    ),
    (
        # My first walk: the matcher looked for the answers in the card's state dict.
        "the-matcher-looks-for-answers-in-the-card-state",
        "dojo/storage.py",
        '                extra = " ".join(str(item.get("answer", ""))\n'
        '                                 for item in self.answers_for(canonical["id"]).values())\n',
        '                extra = str(canonical.get("answers") or "")\n',
        "用他的失效例子能找回这张卡",
    ),
    (
        # My first walk: `show` carries the answers, but the handout was built from the
        # candidate alone, so a later session was handed the card without his words.
        "a-handed-over-card-loses-his-answers",
        "dojo/discuss.py",
        '        if shown.get("answers"):\n'
        '            handed["answers"] = shown["answers"]\n',
        '',
        "开场屏幕上就有他的话",
    ),
    (
        # His words reach the model but unlabelled: the model may cite them as the card.
        "his-words-reach-the-model-as-the-cards-own",
        "dojo/discuss.py",
        '            "\\n这张卡上还附着他本人对这几件的原话（是材料，不是这张卡的措辞，也不是对它的"\n'
        '            "赞同；引用时要说成「他说过」，不能说成卡片这么写，也不能当成第二个独立来源）：\\n"\n',
        '            "\\n" + \n',
        "发给模型时标明了这是他的话，不是卡片措辞，也不是对它的赞同",
    ),
    (
        # The receipt keeps saying the answers stayed out of the card, which is now false.
        "the-receipt-still-says-the-answers-stayed-out",
        "dojo/discuss.py",
        '                   + "、".join(promoted) + "），照你说的字存，没有改写成卡片的措辞。")\n',
        '                   + "、".join(promoted) + "）。")\n',
        "回执说卡片那句没有被改写成他的话",
    ),
    (
        # `part_sources` starts claiming he wrote fields he never wrote.
        "the-field-authorship-is-claimed-for-him",
        "dojo/discuss.py",
        '        part_sources = {key: "系统补" for key in PART_KEYS.values()}\n',
        '        part_sources = {key: "他的原话" for key in PART_KEYS.values()}\n',
        "字段的作者没有被冒认成他（part_sources 仍是系统补）",
    ),
    (
        # The answers leak onto the model-facing search row, widening what a model gets.
        "the-answers-widen-what-the-model-can-retrieve",
        "dojo/storage.py",
        "        ordered = self._matches(terms, include_withheld=for_reading,\n"
        "                                include_answers=for_reading)\n",
        "        ordered = self._matches(terms, include_withheld=for_reading,\n"
        "                                include_answers=True)\n",
        "给模型的那次检索没有因为回答而多出命中",
    ),
    (
        # A card's version moves when a sentence he said is attached, which would turn
        # finished pipeline work back into pending work.
        "attaching-an-answer-bumps-the-card-version",
        "dojo/storage.py",
        '            for key in changed:\n',
        '            state["version"] = int(state["version"]) + 1\n'
        '            self.connection.execute("UPDATE candidates SET version=?, state_json=? "\n'
        '                                    "WHERE id=?", (state["version"], _json(state), state["id"]))\n'
        '            for key in changed:\n',
        "卡片的版本没有因为附上回答而变动（流水线标记不会被打回）",
    ),
    (
        # The screen finds the card but does not say the words were his.
        "the-screen-does-not-say-the-words-were-his",
        "dojo/finding.py",
        '    if answers_part:\n',
        '    if False:\n',
        "命中来自他的话，不是碰巧对上正文",
    ),
]


def main() -> int:
    baseline = subprocess.run([sys.executable, "-B", str(ROOT / VERIFY), str(ROOT)],
                              cwd=str(ROOT), text=True, capture_output=True, timeout=1800)
    if baseline.returncode != 0:
        print("baseline verify.py is not green; arms would prove nothing")
        print(baseline.stdout[-3000:])
        return 1
    print("baseline: verify.py green (" + str(len(ARMS)) + " arms)")
    broken = 0
    for name, target, old, new, expected in ARMS:
        work = Path(tempfile.mkdtemp(prefix="answers-arm-"))
        try:
            for entry in ("dojo", "tests", "docs"):
                shutil.copytree(ROOT / entry, work / entry)
            path = work / target
            source = path.read_text(encoding="utf-8")
            if old not in source:
                print("  %-46s ARM BROKEN: anchor not found" % name)
                broken += 1
                continue
            path.write_text(source.replace(old, new, 1), encoding="utf-8")
            done = subprocess.run([sys.executable, "-B", str(work / VERIFY), str(work)],
                                  cwd=str(work), text=True, capture_output=True, timeout=1800)
            failed = [line.strip()[5:].strip() for line in done.stdout.splitlines()
                      if line.strip().startswith("FAIL ")]
            if done.returncode == 0:
                print("  %-46s GREEN (the fix is not tested)" % name)
                broken += 1
            elif expected not in " ".join(failed):
                print("  %-46s red, but not on 「%s」 (%s)"
                      % (name, expected, ", ".join(failed) or "no FAIL line"))
                broken += 1
            else:
                print("  %-46s red on 「%s」" % (name, expected))
        finally:
            shutil.rmtree(work, ignore_errors=True)
    print("结论：" + ("每条臂都红在它对应的检查上" if not broken
                    else str(broken) + " 条臂不成立"))
    return 0 if not broken else 1


if __name__ == "__main__":
    raise SystemExit(main())
