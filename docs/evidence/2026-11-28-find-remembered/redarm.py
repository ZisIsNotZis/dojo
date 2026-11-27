"""Does `verify.py` go red when the behaviour it checks is put back?

    python3 docs/evidence/2026-11-28-find-remembered/redarm.py [worktree]

A green check proves nothing on its own: it may be watching something the fix never
touched. Each arm restores exactly one earlier behaviour in a copy of the tree and runs
the real `verify.py` there -- the same entry a reader re-runs. An arm counts only when
the *named* check fails, and only when the run fails because a check saw the defect
rather than because the program crashed.

The arm that matters most here is the first one, because it is the supervisor's report
from the released build: with the gate's answer left off the screen, the same words show
his card next to the one that argues with it and say nothing about which is which.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1
            else Path(__file__).resolve().parents[3]).resolve()
VERIFY = "docs/evidence/2026-11-28-find-remembered/verify.py"

# (name, file, exact current text, exact restored text, the check that must go red)
ARMS = [
    (
        "refused-cards-vanish-again",
        "dojo/cli.py",
        "for_reading=True)\n",
        "for_reading=False)\n",
        "同样的词仍然列出我那条（不是只剩相反那条）",
    ),
    (
        "refusal-reason-not-on-the-screen",
        "dojo/finding.py",
        '    return head, ["  也因为这个：" + reason for reason in rest]',
        '    return "  检索不会把它当答案交出去。", []',
        "并且说了为什么：被人质疑过",
    ),
    (
        "refusal-reads-as-absence",
        "dojo/finding.py",
        '            "这不等于库里没有它：它就在这里，条件照原样印在下面。")\n',
        '            "这个库里没有它。")\n',
        "没有把检索的拒绝说成库里的空缺",
    ),
    (
        "miss-says-the-library-is-empty",
        "dojo/finding.py",
        '        lines.append("  没有一张卡的字和这些词重叠。检索只比字词，不认意思，"\n'
        '                     "所以换个说法（你记得的原话、人名、场合、当时的说法）再找一次，可能就对上了。")\n',
        '        lines.append("  库里没有这句。")\n',
        "没有把它说成「库里没有这句」",
    ),
    (
        "no-way-in-when-nothing-overlaps",
        "dojo/storage.py",
        "                payload[\"recent\"] = self._recent_rows(3)",
        "                payload[\"recent\"] = []",
        "给出另一个办法：最近写下的卡",
    ),
    (
        "earlier-wording-unsearchable",
        "dojo/storage.py",
        "            found = terms.intersection(lexical_terms(searchable_text(canonical, accepts)))",
        "            found = terms.intersection(lexical_terms(candidate_text(canonical)))",
        "用换掉之前那句还能找到它",
    ),
    (
        "earlier-match-not-declared",
        "dojo/finding.py",
        '    if row.get("matched_on") not in ("earlier", "current_and_earlier"):\n',
        '    if True:\n',
        "屏幕说这是它以前的说法",
    ),
    (
        "printed-command-drops-the-library",
        "dojo/finding.py",
        '    lines.append("  带进一场新讨论：" + commands.dojo("discuss", "--card", row.get("id"), db=database))\n    return lines',
        '    lines.append("  带进一场新讨论：" + commands.dojo("discuss", "--card", row.get("id")))\n    return lines',
        "给出的命令带绝对 --db 和这张卡的 id",
    ),
    (
        "recent-cards-claim-to-be-a-search",
        "dojo/finding.py",
        '        "  换个办法：下面是这个库里最近写下的 " + str(len(recent)) + " 张卡，"\n'
        '        "按写入时间排的，不是按意思找出来的。",\n',
        '        "  换个办法：下面是这个库里最近写下的 " + str(len(recent)) + " 张卡。",\n',
        "并说明那不是按意思找的",
    ),
    (
        "printed-command-keeps-the-relative-path",
        "dojo/finding.py",
        "    database = library(database)\n",
        "",
        "用相对路径指定库时，屏幕给出的仍是绝对路径",
    ),
    (
        "json-buried-under-the-screen-on-a-terminal",
        "dojo/cli.py",
        "    if sys.stdout.isatty():\n",
        "    if False:\n",
        "终端上没有把整块 JSON 倒在屏幕上",
    ),
    (
        "earlier-wording-note-points-by-position",
        "dojo/finding.py",
        '            + "；库里这一句后来换过，卡片现在写的是本条目开头引的那句。")',
        '            + "；库里这一句后来换过，下面这句是它现在的说法。")',
        "旧说法那条注不说「上面」「下面」",
    ),
    (
        "a-read-changes-the-file-it-reads",
        "dojo/cli.py",
        "        with closing(Store(db_path, readonly=True)) as store:",
        "        with closing(Store(db_path)) as store:\n            db_path.chmod(0o600)\n",
        # Both halves of the old behaviour: the writer `Store` and the chmod it was
        # followed by. The mode is what a person can see, so that is the reading.
        "检索后文件权限仍是 0444",
    ),
    (
        "reading-somebody-elses-database",
        "dojo/cli.py",
        "        with closing(Store(db_path, readonly=True)) as store:",
        "        with closing(Store(db_path)) as store:",
        "指到别的应用的 SQLite 库时拒绝，而不是往里建表",
    ),
    (
        "a-read-is-logged-without-being-asked-for",
        "dojo/cli.py",
        '        if getattr(args, "session", None) is not None:\n',
        '        if True:\n',
        "没有请求记阅读时，不建读记录表，也不改表结构",
    ),
    (
        "a-missing-library-is-reported-as-an-empty-one",
        "dojo/cli.py",
        '        if not db_path.exists():\n            raise DojoError(',
        '        if False:\n            raise DojoError(',
        "不存在的库上检索会拒绝，而不是报成空结果",
    ),
    (
        "screen-keys-leak-into-stdout",
        "dojo/cli.py",
        '            published = {key: value for key, value in result.items()\n'
        '                         if key not in ("withheld", "recent")}\n',
        '            published = dict(result)\n',
        "命令行 stdout 仍是四个旧键（屏幕的键不进 stdout）",
    ),
    # ---- where the words were found (#3436's second round) ---------------------------
    # These restore 560a07d's behaviour, where any overlap anywhere in the card was
    # reported as the *sentence* matching. The published tree measured it three ways.
    (
        "every-match-is-called-the-sentence",
        "dojo/storage.py",
        '        in_sentence = bool(found & lexical_terms(statement_text(state)))\n'
        '        in_aliases = bool(found & lexical_terms(aliases_text(state)))\n',
        '        in_sentence = bool(found & lexical_terms(candidate_text(state)))\n'
        '        in_aliases = False\n',
        "条件里的字对上时，屏幕不把这句当成对上的那句",
    ),
    (
        "alias-match-reported-as-the-current-sentence",
        "dojo/storage.py",
        '        if in_aliases:\n            matched_in.append("alias")\n',
        '        if in_aliases:\n            matched_in.append("sentence")\n',
        "别名对上时，不谎称卡片现在那句对上",
    ),
    (
        "the-screen-does-not-say-where-the-words-were",
        "dojo/finding.py",
        '    location = _where_the_words_are(row)\n    if location:\n        lines.append(location)\n',
        '',
        "条件里的字对上时，屏幕不把这句当成对上的那句",
    ),
    (
        # The supervisor's catch, restored exactly: `cli.py` strips only the two keys it
        # knew about, so the new reading key reaches every published row.
        "a-new-reading-key-leaks-into-every-published-row",
        "dojo/cli.py",
        '                 if key not in READING_ROW_KEYS}\n',
        '                 if key not in ("matched_on", "matched_wording")}\n',
        "两条命中的 stdout 每行与给模型的那行逐键相同",
    ),
    (
        "a-card-that-only-quotes-the-sentence-ranks-first",
        "dojo/finding.py",
        '        0 if "sentence" in (row.get("matched_in") or []) else 1,\n',
        '        0,\n',
        "说这句话的卡排在那张只引用了它的卡前面",
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
        work = Path(tempfile.mkdtemp(prefix="find-arm-"))
        try:
            for entry in ("dojo", "tests", "docs"):
                shutil.copytree(ROOT / entry, work / entry)
            path = work / target
            source = path.read_text(encoding="utf-8")
            if old not in source:
                print("  %-40s ARM BROKEN: anchor not found" % name)
                broken += 1
                continue
            path.write_text(source.replace(old, new, 1), encoding="utf-8")
            done = subprocess.run([sys.executable, "-B", str(work / VERIFY), str(work)],
                                  cwd=str(work), text=True, capture_output=True, timeout=1800)
            failed = [line.strip()[5:].strip() for line in done.stdout.splitlines()
                      if line.strip().startswith("FAIL ")]
            if done.returncode == 0:
                print("  %-40s GREEN (the fix is not tested)" % name)
                broken += 1
            elif expected not in " ".join(failed):
                print("  %-40s red, but not on 「%s」 (%s)"
                      % (name, expected, ", ".join(failed) or "no FAIL line"))
                broken += 1
            else:
                print("  %-40s red on 「%s」" % (name, expected))
        finally:
            shutil.rmtree(work, ignore_errors=True)
    print("结论：" + ("每条臂都红在它对应的检查上" if not broken
                    else str(broken) + " 条臂不成立"))
    return 0 if not broken else 1


if __name__ == "__main__":
    raise SystemExit(main())
