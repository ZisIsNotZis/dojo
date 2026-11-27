#!/usr/bin/env python3
"""复验这份迁移记录：before/after 的逐字文本，和那条经验的失效条件。

    python3 docs/evidence/2026-11-27-citation-slice-archive/transfer/verify.py

只读、离线、不写盘。它检查的是这份记录自己声称过的东西：

  1. BEFORE/AFTER/DIFF 的字节没有被改过（对声明的摘要）。
  2. BEFORE 里没有出现 AFTER 才有的判词——顺序不能反。
  3. 那条经验的适用条件在发布库里仍然成立：`dojo-d-001` 的两条失效条件
     仍然写在那里，且 `judge` 那条仍然要求「另一个独立方」。
  4. 决定本身可以复算：一条道引的凭据核不到时，它的等级封不封顶。

第 4 项是本轮改的那处代码。第 1–3 项不依赖那次运行的现场，只依赖这份树。

这个脚本最初的一版读的是作者本机的 `.scratch/3314/clean`，陌生人跑起来只得到
「引语找不到」。那一版没有价值，已删；现在它只读自己所在的这棵树。
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
GATE = ROOT / 'scripts' / 'dao_life.py'
LIBRARY = ROOT / 'docs' / 'dao' / 'repeat-safety'

DECLARED = {
    'BRIEF.md': 'f03597492575fbeb838d75ed27b864875e227fb147381365394b234b9dc6b19d',
    'BEFORE.md': 'a5427c2222e44bab34bf8a14f345495da2d8229a7c04c1582d62ee4bd27d940e',
    'AFTER.md': '5c4b1d9ecd60e5ce62da37d8dff66af480ead60bda36389a36d35eca2697ab66',
    'DIFF.md': '57cf757e9378cf9e132192a5e6406bf6baefbb541af2c85a987cfd061349e7d4',
}


def load_gate():
    spec = importlib.util.spec_from_file_location('dao_life', GATE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def text(name: str) -> str:
    return (HERE / name).read_text(encoding='utf-8')


def body(name: str) -> str:
    """Drop the leading note block: the part below the second `---`.

    The three files carry a provenance header that was written later than the words
    it describes. Comparing bodies keeps the check on the content and off the header,
    and says so rather than silently comparing everything.
    """
    parts = text(name).split('---')
    return parts[-1] if len(parts) > 2 else text(name)


def decisions():
    dao = json.loads((LIBRARY / 'daos.json').read_text(encoding='utf-8'))['daos'][0]
    situation = dao['situation']
    return {
        'id': dao['id'],
        'version': dao['version'],
        'off': situation.get('off') or dao.get('off') or [],
        'covers': situation.get('covers') or [],
        'one_line': dao.get('one_line', ''),
    }


def main() -> int:
    out = {'checkout': str(ROOT), 'files': {}}
    failures = []

    for name, want in DECLARED.items():
        path = HERE / name
        got = hashlib.sha256(path.read_bytes()).hexdigest()
        out['files'][name] = {'sha256': got, 'matches_declared': got == want}
        if got != want:
            failures.append('%s 的字节与声明的摘要不同' % name)

    before, after, diff = body('BEFORE.md'), body('AFTER.md'), body('DIFF.md')
    # BEFORE 是盲答：它不可能逐字含有 AFTER 才有的判词。`判定与证据脱钩` 是
    # 那次读数之后才出现的一句（我实测它在 AFTER 与 DIFF 里、不在 BEFORE 里），
    # 所以它能把"先留 before 再给 brief"这个顺序钉住。
    after_only = '判定与证据脱钩'
    out['order'] = {
        'witness': after_only,
        'before_mentions_it': after_only in before,
        'after_mentions_it': after_only in after,
        'diff_names_it': after_only in diff,
    }
    if out['order']['before_mentions_it']:
        failures.append('BEFORE 里出现了只该在 AFTER 里的判词：顺序反了')
    if not (out['order']['after_mentions_it'] or out['order']['diff_names_it']):
        failures.append('AFTER 与 DIFF 都没有那句话：用来钉顺序的见证词已经不在，'
                        '这条检查需要另选一个')

    info = decisions()
    out['judgement'] = info
    off_by_axis = {item.get('axis'): item for item in info['off']}
    if 'judge' not in off_by_axis:
        failures.append('这条经验缺 judge 失效条件')
    elif '独立' not in json.dumps(off_by_axis['judge'], ensure_ascii=False):
        failures.append('judge 失效条件不再要求独立的一方')

    # 第 4 项：决定有没有落到代码上。
    gate = load_gate()
    out['cap_exists'] = hasattr(gate, 'sources_cell')
    if not out['cap_exists']:
        failures.append('scripts/dao_life.py 没有 sources_cell：本片的决定不在这棵树上')
        out['main'] = None
        print(json.dumps(out, ensure_ascii=False, indent=1))
        print('\nFAIL', file=sys.stderr)
        for item in failures:
            print('  ' + item, file=sys.stderr)
        return 1

    # 用真实库读一次：这条道引的凭据，在这份检出里核到了几条。
    done = subprocess.run([sys.executable, '-B', str(GATE), str(LIBRARY), '--check'],
                          cwd=str(ROOT), capture_output=True, text=True)
    lines = (done.stdout + done.stderr).splitlines()
    out['main'] = {
        'exit': done.returncode,
        'line': next((line.strip() for line in lines if '·' in line), ''),
        'sources': next((line.strip() for line in lines if '出处核对' in line), ''),
        'shallow': subprocess.run(['git', 'rev-parse', '--is-shallow-repository'],
                                  cwd=str(ROOT), capture_output=True, text=True).stdout.strip(),
    }
    # 不变式：这一行说「检」的时候，出处必须是核过的。
    if '· 检' in out['main']['line'] and '出处 过' not in out['main']['line']:
        failures.append('这一行说检过，但出处不是「过」：%s' % out['main']['line'])

    print(json.dumps(out, ensure_ascii=False, indent=1))
    if failures:
        print('\nFAIL', file=sys.stderr)
        for item in failures:
            print('  ' + item, file=sys.stderr)
        return 1
    print('\nOK  %d 个文件字节相符；顺序未被反写；失效条件仍在；决定落在代码上。' % len(DECLARED),
          file=sys.stderr)
    print('    你这份检出：shallow=%s；%s' % (out['main']['shallow'], out['main']['line']),
          file=sys.stderr)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
