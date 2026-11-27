#!/usr/bin/env python3
"""你这份检出里，每条道引的凭据核过了没有。

    python3 docs/evidence/2026-11-27-citation-slice-archive/verify.py

只读、离线、不联网、不写盘。它替一个读者回答一个问题，不问别的：

    这一行说「检」的时候，它自己引的那几条，真的在它写的那个修订上读到了吗？

三种结果：

  OK      每条说「检」的道，出处都核过。
  FAIL    有条道说「检」，而它自己的出处没核上——这是本片要修的那件事。
  读数    你这份检出里能核到几条。**浅克隆与完整克隆本来就不一样**：
          记录的修订不在本地，就核不到。这不是缺陷，是每一行必须如实说明的情形。

所以这个脚本不判断「这个仓库对你好不好」，只把每一行的说法和它自己的证据并排给你看。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
GATE = ROOT / 'scripts' / 'dao_life.py'
LIBRARIES = ('repeat-safety', 'person-dojo', 'demo-strangers')

SOURCE_WORD = {'过': '过', '不过': '不过', '未核': '未核'}


def read(library: str) -> dict:
    done = subprocess.run([sys.executable, '-B', str(GATE),
                           str(ROOT / 'docs' / 'dao' / library), '--check'],
                          cwd=str(ROOT), capture_output=True, text=True)
    lines = (done.stdout + done.stderr).splitlines()
    return {
        'library': library,
        'exit': done.returncode,
        'dao_line': next((line.strip() for line in lines if '·' in line and '条道' not in line), ''),
        'sources_line': next((line.strip() for line in lines if '出处核对' in line), ''),
    }


def claims_checked(dao_line: str) -> bool:
    """Does this dao's own line say the check was run?"""
    if '·' not in dao_line:
        return False
    head = dao_line.split('·')[1].strip()
    return head.startswith('检')


def source_verdict(dao_line: str) -> str:
    for word in ('出处 过', '出处 不', '出处 未核'):
        if word in dao_line:
            return word.replace('出处 ', '')
    return 'unknown'


def main() -> int:
    out = {
        'checkout': str(ROOT),
        'head': subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=str(ROOT),
                               capture_output=True, text=True).stdout.strip(),
        'shallow': subprocess.run(['git', 'rev-parse', '--is-shallow-repository'],
                                  cwd=str(ROOT), capture_output=True, text=True).stdout.strip(),
        'libraries': [],
    }
    broken = []
    for name in LIBRARIES:
        item = read(name)
        checked = claims_checked(item['dao_line'])
        verdict = source_verdict(item['dao_line'])
        item['claims_checked'] = checked
        item['source_cell'] = verdict
        # 这一行说「检」而出处不是「过」，就是本片要修的那件事。
        item['holds'] = (not checked) or verdict == '过'
        if not item['holds']:
            broken.append(name)
        out['libraries'].append(item)

    print(json.dumps(out, ensure_ascii=False, indent=1))

    for item in out['libraries']:
        cell = SOURCE_WORD.get(item['source_cell'], '—')
        mark = '说检过' if item['claims_checked'] else '没说检过'
        print('%-14s %s；出处 %s' % (item['library'], mark, cell or '（这一行不带这格）'),
              file=sys.stderr)

    if broken:
        print('\nFAIL  这些行说「检」，而它们自己的出处没核上：%s' % '、'.join(broken),
              file=sys.stderr)
        return 1
    print('\nOK    没有一行夸大：凡是说「检」的，出处都核过了。', file=sys.stderr)
    print('      你这份检出 shallow=%s。修订不在本地时，出处会印「未核」而不是「过」——'
          '那就是它该说的话。' % out['shallow'], file=sys.stderr)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
