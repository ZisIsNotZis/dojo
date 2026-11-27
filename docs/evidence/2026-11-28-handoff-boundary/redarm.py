"""Does `verify.py` go red when the behaviour it checks is put back?

    python3 docs/evidence/2026-11-28-handoff-boundary/redarm.py [worktree]

A green check proves nothing on its own: it may be looking at something the fix never
touched. Each arm below restores exactly one earlier behaviour in a copy of the tree and
runs the real `verify.py` there, which is the entry a reader re-runs. An arm is only
counted when the named check fails -- and when the run fails for that reason rather than
by crashing.

Two arms have already been caught lying by this design: a check that passed because the
probe hand-wrote its own command instead of pasting the printed one, and an arm that went
red through a `NameError` (a crash is not a check seeing the defect).
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1
            else Path(__file__).resolve().parents[3]).resolve()
VERIFY = "docs/evidence/2026-11-28-handoff-boundary/verify.py"

# (name, file, exact old text, exact new text, the check that must go red)
ARMS = [
    (
        "limits-only-for-the-model",
        "dojo/discuss.py",
        "    limits = boundary_lines(candidate)\n    if limits:\n        block += \"\\n\" + \"\\n\".join(limits)\n",
        "",
        "开场屏幕印出「什么时候成立」",
    ),
    (
        "draft-asserts-nobody-agreed",
        "dojo/discuss.py",
        '    "draft": "草稿",',
        '    "draft": "草稿（这一句还没有人认可）",',
        # The draft card, not the confirmed one: `confirm` moves the status to
        # `discussable` and would have hidden this wording entirely.
        "草稿状态的卡不再说没人认可过它",
    ),
    (
        "no-record-reads-as-no-agreement",
        "dojo/discuss.py",
        '        return ("  库里没有这套说法（句子连同它写的条件）的认可记录；"\n                "这不等于没人认可过它，只等于这个库里没记下。")',
        '        return "  这一句还没有人认可。"',
        "质疑之后，认可记录说的是「库里没有」而不是「没人认可」",
    ),
    (
        "revision-always-narrower",
        "dojo/discuss.py",
        '        block += "\\n  库里记着这一句换过说法，之前是：「" + left + "」"',
        '        block += "\\n  它比更早那句窄：原来是「" + left + "」"',
        "开场不再印旧句式「它比更早那句窄」",
    ),
    (
        "source-claims-left-out-of-the-screen",
        "dojo/discuss.py",
        "        detail = source_lines(candidate)\n        if detail:\n            block += \"\\n\" + \"\\n\".join(detail)\n",
        "",
        "来源记录说的是什么也印在屏幕上",
    ),
    (
        "confirm-claims-acceptance",
        "dojo/discuss.py",
        '    "discussable": "可讨论（有人把它标成值得讨论，不表示为真）",',
        '    "discussable": "可讨论（有人认可它值得讨论，不表示为真）",',
        "可讨论的括号不冒用「认可」这个字",
    ),
    (
        "alternatives-on-the-screen",
        "dojo/discuss.py",
        '    ("unknowns", "还没定的是"),\n',
        '    ("unknowns", "还没定的是"),\n    ("alternatives", "另一条路是"),\n',
        "另一条路不上开场屏幕（刻意的取舍）",
    ),
    (
        "acceptance-fact-not-on-the-handout-row",
        "dojo/discuss.py",
        '                "acceptance": handed_acceptance or None,',
        '                "acceptance": None,',
        # The resume path rebuilds the handout from the trace row. This card is a draft
        # with an acceptance record, so the row's `acceptance` fact is what is being
        # tested; the confirmed card's resume line could pass without it.
        "续跑仍印出认可记录（从轨迹行重建）",
    ),
]


def main() -> int:
    baseline = subprocess.run([sys.executable, "-B", str(ROOT / VERIFY), str(ROOT)],
                              cwd=str(ROOT), text=True, capture_output=True, timeout=1800)
    if baseline.returncode != 0:
        print("baseline verify.py is not green; arms would prove nothing")
        print(baseline.stdout[-2000:])
        return 1
    print("baseline: verify.py green (" + str(len(ARMS)) + " arms)")
    broken = 0
    for name, target, old, new, expected in ARMS:
        work = Path(tempfile.mkdtemp(prefix="verify-arm-"))
        try:
            for entry in ("dojo", "tests", "docs"):
                shutil.copytree(ROOT / entry, work / entry)
            path = work / target
            source = path.read_text(encoding="utf-8")
            if old not in source:
                print("  %-44s ARM BROKEN: anchor not found" % name)
                broken += 1
                continue
            path.write_text(source.replace(old, new, 1), encoding="utf-8")
            done = subprocess.run([sys.executable, "-B", str(work / VERIFY), str(work)],
                                  cwd=str(work), text=True, capture_output=True, timeout=1800)
            lines = [line for line in done.stdout.splitlines() if line.strip().startswith("FAIL ")]
            failed = [line.strip()[5:] for line in lines]
            if done.returncode == 0:
                print("  %-44s GREEN (the fix is not tested)" % name)
                broken += 1
            elif expected not in " ".join(failed):
                print("  %-44s red, but not on 「%s」 (%s)"
                      % (name, expected, ", ".join(failed) or "no FAIL line"))
                broken += 1
            else:
                print("  %-44s red on 「%s」" % (name, expected))
        finally:
            shutil.rmtree(work, ignore_errors=True)
    print("结论：" + ("每条臂都红在它对应的检查上" if not broken
                    else str(broken) + " 条臂不成立"))
    return 0 if not broken else 1


if __name__ == "__main__":
    raise SystemExit(main())
