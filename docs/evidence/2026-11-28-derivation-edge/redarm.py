"""Does `verify.py` go red when the behaviour it checks is put back?

    python3 docs/evidence/2026-11-28-derivation-edge/redarm.py [worktree]

Each arm restores earlier behaviour in a copy of the tree and runs the real `verify.py`
there -- the same entry a reader re-runs. An arm counts only when the *named* check fails.

Two lessons this file carries, both learned by watching an arm stay green:

* **An arm is a list of edits.** `link` is refused twice -- by the CLI's choice list and by
  `Store.link` -- and restoring only the first left the library refusing, so the arm proved
  nothing. Both are undone below.
* **An anchor has to be unique, including its indentation.** A 12-space prefix occurs
  inside a 20-space line, so a replace written for `_draft_conclusion` landed on
  `_save_conclusion` instead. Every anchor below carries the line above it, and the runner
  refuses an anchor that is not found exactly once.

Two arms restore defects the supervisor measured on this slice's own first version, not on
an older release: the per-row table scan (601 reads for one search) and the screen
announcing a discussion behind a hand-typed relation.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1
            else Path(__file__).resolve().parents[3]).resolve()
VERIFY = "docs/evidence/2026-11-28-derivation-edge/verify.py"

EDGE = "新卡记着它是在带着原来那条的讨论里写下的"
ARMS = [
    # Twenty spaces of indent is `_save_conclusion` (the accepted path); twelve is
    # `_draft_conclusion`. Worth stating because the labels were the other way round in the
    # first draft of this file, and a mislabelled arm still runs and still goes red -- on
    # the other scene's check.
    (
        "an-accepted-conclusion-leaves-no-edge",
        [("dojo/discuss.py",
          "                    unknowns=candidate[\"unknowns\"], session=session,\n"
          "                    sources=[source], derived_from=derived_from,\n",
          "                    unknowns=candidate[\"unknowns\"], session=session,\n"
          "                    sources=[source],\n")],
          "当场认可的那一版，也记着它是从哪条来的",
    ),
    (
        "a-draft-written-in-a-discussion-leaves-no-edge",
        [("dojo/discuss.py",
          "            unknowns=candidate[\"unknowns\"], session=session,\n"
          "            sources=[source], derived_from=derived_from,\n",
          "            unknowns=candidate[\"unknowns\"], session=session,\n"
          "            sources=[source],\n")],
        EDGE,
    ),
    (
        "the-draft-path-stops-handing-the-card-over",  # the twelve-space call site
        [("dojo/discuss.py",
          "                    derived_from=(handed[\"id\"] if handed is not None\n"
          "                                  and saved_candidate_id is None else None),\n",
          "                    derived_from=None,\n")],
        EDGE,
    ),
    (
        "the-screen-does-not-say-where-the-newer-version-came-from",
        [("dojo/finding.py",
          "    relation = relation_lines(row, derivation=row.get(\"derivation\"), database=database)\n"
          "    if relation:\n"
          "        lines.extend(relation)\n",
          "")],
        "新卡那边写着它从哪条来的",
    ),
    (
        "the-old-card-does-not-say-there-is-a-later-version",
        [("dojo/finding.py",
          "    later = _later_lines(row, database)\n    if later:\n        lines.extend(later)\n",
          "")],
        "旧卡那边写着后来有一版是从它来的",
    ),
    (
        # The supervisor's provenance reproducer, restored: the type name decides.
        "a-hand-typed-edge-is-called-a-discussion",
        [("dojo/storage.py",
          "                    \"basis\": (\"discussion\" if self.derivation(state[\"id\"]) == target\n"
          "                              else \"recorded_relation\"),\n",
          "                    \"basis\": \"discussion\",\n")],
        "库里原本就有的手打边，屏幕不再说这是一场讨论",
    ),
    (
        # Both gates, because either one alone still refuses.
        "a-person-can-manufacture-a-discussion",
        [("dojo/storage.py",
          "        if relation not in RELATIONS:\n",
          "        if relation in PROGRAM_RELATIONS:\n"
          "            RELATIONS.add(relation)\n"
          "        if relation not in RELATIONS:\n"),
         ("dojo/cli.py",
          "choices=[\"supports\", \"challenges\", \"narrows\", \"generalizes\", \"conflicts\", "
          "\"instantiates\", \"duplicates\"])\n    link.add_argument(\"--target\"",
          "choices=[\"supports\", \"challenges\", \"narrows\", \"generalizes\", \"conflicts\", "
          "\"instantiates\", \"duplicates\", \"derived_from\"])\n    link.add_argument(\"--target\"")],
        "命令行不再能手动造出一条「讨论留下的」边",
    ),
    (
        # The supervisor's scale reproducer, restored: the reverse lookup asks the table.
        "the-reverse-lookup-reads-the-whole-table-per-row",
        [("dojo/storage.py",
          "        everything = getattr(self, \"last_scan\", []) if for_reading else []\n",
          "        everything = None if for_reading else []\n")],
        "300 张和 600 张的库上，候选表都只读一次",
    ),
    (
        "the-reading-keys-leak-into-the-model-payload",
        [("dojo/cli.py",
          "                 if key not in READING_ROW_KEYS}\n",
          "                 if key not in (\"matched_on\", \"matched_wording\")}\n")],
        "屏幕上的键没有漏进 stdout",
    ),
    (
        "the-later-version-is-called-a-replacement",
        [("dojo/finding.py",
          "        lines.append(\"  后来有一场带着这条继续谈，写下了另一版（不是替换，也不说明变窄还是变宽；\"\n"
          "                     \"两版都在库里）：\")\n",
          "        lines.append(\"  后来有一场带着这条继续谈，写下了另一版，它替换了上面这一条：\")\n")],
        "旧卡那边说了这不是替换",
    ),
]


def main() -> int:
    baseline = subprocess.run([sys.executable, "-B", str(ROOT / VERIFY), str(ROOT)],
                              cwd=str(ROOT), text=True, capture_output=True, timeout=3600)
    if baseline.returncode != 0:
        print("baseline verify.py is not green; arms would prove nothing")
        print(baseline.stdout[-3000:])
        return 1
    print("baseline: verify.py green (" + str(len(ARMS)) + " arms)")
    broken = 0
    for name, edits, expected in ARMS:
        work = Path(tempfile.mkdtemp(prefix="derivation-arm-"))
        try:
            for entry in ("dojo", "tests", "docs"):
                shutil.copytree(ROOT / entry, work / entry)
            missing = None
            for target, old, new in edits:
                path = work / target
                source = path.read_text(encoding="utf-8")
                if source.count(old) != 1:
                    # Not "found at least once": an ambiguous anchor replaces the wrong
                    # occurrence and the arm then measures nothing.
                    missing = "%s (%d matches)" % (target, source.count(old))
                    break
                path.write_text(source.replace(old, new, 1), encoding="utf-8")
            if missing:
                print("  %-46s ARM BROKEN: anchor %s" % (name, missing))
                broken += 1
                continue
            done = subprocess.run([sys.executable, "-B", str(work / VERIFY), str(work)],
                                  cwd=str(work), text=True, capture_output=True, timeout=3600)
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
