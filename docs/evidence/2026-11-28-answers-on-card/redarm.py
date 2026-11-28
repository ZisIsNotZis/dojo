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
        # The supervisor's finding, put back: `--no-trace` turns off only the session
        # record, so his words are written onto the card while the screen says nothing
        # was kept. An arm of its own because the flag was a promise about one filename,
        # not about privacy, and the reading is what makes that visible.
        "no-trace-keeps-his-words-on-the-card-anyway",
        "dojo/discuss.py",
        "                promote_answers_onto_card() if trace is not None else\n",
        "                promote_answers_onto_card() if True else\n",
        "show 读不到任何一条他的原话",
    ),
    (
        # The write is withheld but the receipt says nothing, which reads as success.
        "the-quiet-session-says-nothing-about-the-card",
        "dojo/discuss.py",
        '    elif withheld == "no_trace" and said:\n',
        '    elif False and said:\n',
        "回执说原话没有附到卡片上",
    ),
    (
        # Review: the upgrade decision sat outside the write lock, so two sessions
        # upgrading one old library both ran the ALTER and the second lost its answer to
        # `duplicate column name`. This reverses exactly that lock and nothing else; the
        # window is widened by the test seam (`_widen_pause`), and `duplicate column` is
        # NOT tolerated here -- tolerating it is what made the first version of this arm
        # green on broken code.
        "the-upgrade-decides-outside-the-write-lock",
        # Two reversals, because the fix has two halves and each one masks the other:
        # (a) the decision moves back outside `BEGIN IMMEDIATE`; (b) the tolerance for
        # `duplicate column` goes away. With only (a) the second writer quietly accepts
        # the column it finds and the arm is green on broken code -- which is exactly what
        # the first two versions of this arm did. The reading is what review described:
        # two writers, one old library, both answers must survive.
        [
            ("dojo/storage.py",
             '        with self.transaction():\n'
             '            if self.connection.execute(\n'
             '                "SELECT 1 FROM sqlite_master WHERE type=\'table\' AND name=\'answers\'"\n'
             '            ).fetchone() is None:\n'
             '                # `executescript` would commit the open transaction; the table is small\n'
             '                # and fixed, so the statements are run one by one instead.\n'
             '                for statement in self.ANSWERS_SCHEMA.split(";"):\n'
             '                    if statement.strip():\n'
             '                        self.connection.execute(statement)\n'
             '            self._widen_answers_table()\n',
             '        if self.connection.execute(\n'
             '            "SELECT 1 FROM sqlite_master WHERE type=\'table\' AND name=\'answers\'"\n'
             '        ).fetchone() is not None:\n'
             '            self._widen_pause = 0.4  # widen the window the lock used to close\n'
             '            self._widen_answers_table()\n'
             '            return\n'
             '        with self.transaction():\n'
             '            if self.connection.execute(\n'
             '                "SELECT 1 FROM sqlite_master WHERE type=\'table\' AND name=\'answers\'"\n'
             '            ).fetchone() is None:\n'
             '                for statement in self.ANSWERS_SCHEMA.split(";"):\n'
             '                    if statement.strip():\n'
             '                        self.connection.execute(statement)\n'
             '            self._widen_answers_table()\n'),
            ("dojo/storage.py",
             '            except sqlite3.OperationalError as exc:\n'
             '                if "duplicate column name" not in str(exc):\n'
             '                    raise\n'
             '                # Another writer added it between our read and our write. The state we\n'
             '                # wanted is the state we have.\n'
             '                continue\n',
             '            except sqlite3.OperationalError:\n'
             '                raise\n'),
        ],
        "两个写入同时给旧库补列，都没有报错",
    ),
    (
        # Review: every line offered the way back even when the record died before that
        # answer, so the command opened a file that did not contain the sentence.
        "a-way-back-is-offered-for-a-sentence-not-in-the-record",
        "dojo/discuss.py",
        "                    entry[\"recorded\"] = _answer_reached_the_file(trace_path, part, answer)\n",
        "                    entry[\"recorded\"] = True\n",
        "每条回看命令打开的记录都真的有那句原话",
    ),
    (
        # Review: a session number typed into `promote` made a hand-kept sentence look
        # like a `--no-trace` discussion.
        "a-hand-kept-answer-borrows-a-session-number",
        "dojo/cli.py",
        '"session": args.session, "provenance": "manual"})',
        '"session": args.session, "provenance": "discussion"})',
        "手工 promote 顺手给了会话号，也没有被说成一场 --no-trace 讨论",
    ),
    (
        # Review's finding on fdd55ff, put back: the record column holds the time the
        # answer was promoted instead of the path of the session that said it, so `show`
        # offers a field a reader cannot open and the screen prints no way back.
        "the-record-of-a-session-is-a-timestamp-not-a-place",
        "dojo/discuss.py",
        '                entry["trace"] = str(commands.absolute(trace_path))\n',
        '                entry["trace"] = str(datetime.now(timezone.utc).isoformat())\n',
        "每条回答的 trace 是一个真存在、能打开的记录文件",
    ),
    (
        # A hand-kept sentence borrows a session and a moment it never had.
        "a-hand-kept-answer-claims-a-conversation",
        "dojo/answers.py",
        '        from_discussion = item.get("provenance") == "discussion"\n',
        '        from_discussion = True\n',
        "手工 promote 顺手给了会话号，也没有被说成一场 --no-trace 讨论",
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
    for name, target, old, new, expected in ((arm[0], arm[1],
                                              arm[2] if not isinstance(arm[1], list) else None,
                                              arm[3] if not isinstance(arm[1], list) else None,
                                              arm[-1]) for arm in ARMS):
        work = Path(tempfile.mkdtemp(prefix="answers-arm-"))
        try:
            for entry in ("dojo", "tests", "docs"):
                shutil.copytree(ROOT / entry, work / entry)
            # An arm may need more than one reversal, either because the fix has more
            # than one part or because one part *masks* another: the upgrade race is
            # invisible while `duplicate column` is tolerated, so an arm that restores
            # only the unlocked decision stays green on broken code. `target` may be a
            # single path with one (old, new) pair, or a list of such triples. Requiring
            # every anchor keeps an arm from silently testing only half its change.
            plan = target if isinstance(target, list) else [(target, old, new)]
            if isinstance(target, list):
                if not all(isinstance(step, tuple) and len(step) == 3 for step in plan):
                    print("  %-46s ARM BROKEN: malformed multi-step arm" % name)
                    broken += 1
                    continue
                edits = plan
            else:
                edits = [(target, old, new)]
            missing = [path for path, old_text, _new in edits
                       if old_text not in (work / path).read_text(encoding="utf-8")]
            if missing:
                print("  %-46s ARM BROKEN: anchor not found in %s"
                      % (name, ", ".join(missing)))
                broken += 1
                continue
            for path_name, old_text, new_text in edits:
                path = work / path_name
                source = path.read_text(encoding="utf-8")
                path.write_text(source.replace(old_text, new_text, 1), encoding="utf-8")
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
