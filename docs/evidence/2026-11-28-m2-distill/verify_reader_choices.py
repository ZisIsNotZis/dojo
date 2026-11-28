#!/usr/bin/env python3
"""Replay two synthetic reader exercises plus one archived old card, offline.

Usage: python3 -B verify_reader_choices.py [--require-reader-paths] WORKTREE NEW_OUTPUT_DIR
The resulting DB and real CLI traces remain in NEW_OUTPUT_DIR for manual reads.
With --require-reader-paths, follow per-version quote and link-help commands from
screen, then separately write one explicit link on a disposable database copy.
No model is called for readback; no merge, promotion, or classification is performed.
"""
from __future__ import annotations

from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import queue
import re
import shlex
from shutil import copyfile
import subprocess
import sys
import threading


def card(statement, scope, *, kind='application', unknowns=(), contradictions=()):
    return dict(statement=statement, kind=kind, scope=[scope], premises=[], alternatives=[],
                contradictions=list(contradictions), unknowns=list(unknowns))


SHELF = '在图书交换架上留一张“下一位放哪里”的指引卡。'
OLD = [('交换架交班时，我想在架上留一张“下一位放哪里”的指引卡。旧主张就按每次交班都可以写，两个投放口同时开也包括在内。说清楚：双口交班我其实没试过。',
        card(SHELF, '图书交换架的每次交班，包括两个投放口同时开放', unknowns=['没试过双口交班']), True)]
A = [('雨天社区修伞站如果临时借不到登记册，我想只在今晚用一张纸签记下伞号，纸签交给还在场的值班员。这个办法没实际用过，也不替代平时登记。',
      card('临时用一张纸签记下借伞编号，交给在场值班员。', '仅今晚雨天，登记册临时借不到且值班员还在场',
           unknowns=['未实际用过，不替代平时登记']), True),
     ('再留一个没有答案的问题：如果值班员离开前没拿到纸签，谁来核对晚归的伞？不是说已经有人弄丢了伞。',
      card('值班员没拿到纸签时，谁核对晚归的伞？', '雨天修伞站、值班员离开前未收到纸签', kind='question',
           unknowns=['没有答案；未报告丢伞']), True),
     ('把纸签拍照发到群里也只是另一个念头。我还没问借伞人同不同意，先别认可。',
      card('把纸签拍照发到群里。', '与借伞人确认同意之后才考虑', unknowns=['还未问借伞人']), False)]
B = [('我不同意旧说法把两个投放口同时开也算进去。我的建议是：只有一个投放口开、前一班还在并当面确认投放位置时，才在图书交换架上留一张“下一位放哪里”的指引卡。双口各收不同类的书，同一张指引未必指得清，但我没实测出错率。',
      card(SHELF, '图书交换架交班时仅一个投放口开放，前一班在场并当面确认投放位置',
           contradictions=['两个口同时开放、各收不同类的书，不照搬该指引'],
           unknowns=['双口的出错率未实测']), True)]


def check(cond, desc):
    if not cond:
        raise AssertionError(desc)


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


class Replay:
    def __init__(self, repo, out, require_reader_paths):
        self.repo, self.out = repo, out
        self.require_reader_paths = require_reader_paths
        out.mkdir(parents=True, mode=0o700)
        self.home = out / 'isolated home'
        self.home.mkdir()
        self.db = self.home / 'library.sqlite3'
        self.cmd = [sys.executable, '-B', '-u', '-m', 'dojo', '--db', str(self.db)]
        self.env = {'PATH': os.environ['PATH'], 'HOME': str(self.home), 'LANG': 'C.UTF-8',
                    'NO_PROXY': '127.0.0.1', 'DOJO_SESSIONS': str(self.home / 'sessions'),
                    'PYTHONPATH': str(repo), 'PYTHONUTF8': '1', 'PYTHONDONTWRITEBYTECODE': '1'}
        self.calls, self.errors, self.turns = [], [], []
        self.traces, self.sessions, self.ends = {}, {}, {}

    def invoke(self, argv, **env):
        result = subprocess.run(argv, cwd=self.out, env=self.env | env, text=True, encoding='utf-8',
                                capture_output=True, timeout=25)
        check(result.returncode == 0, f'{argv!r}: {result.stderr}\n{result.stdout}')
        return result.stdout

    def cli(self, *args, **env):
        return json.loads(self.invoke([*self.cmd, *args], **env))

    def discuss(self, name, turns, model_env):
        self.turns = turns
        self.calls.clear()
        screen, lines = [], queue.Queue()
        with (self.out / f'{name}.discuss.stderr.txt').open('w', encoding='utf-8') as err:
            proc = subprocess.Popen([*self.cmd, 'discuss', '--no-profile'], cwd=self.repo, env=self.env | model_env,
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err, text=True, encoding='utf-8')

            def read():
                for line in proc.stdout:
                    screen.append(line)
                    lines.put(line)
                lines.put(None)

            def send(text):
                proc.stdin.write(text + '\n')
                proc.stdin.flush()

            def expect(needle):
                chunk = []
                while True:
                    line = lines.get(timeout=15)
                    check(line is not None, f'{name}: EOF before {needle!r}')
                    chunk.append(line)
                    if needle in line:
                        return ''.join(chunk)

            reader = threading.Thread(target=read, daemon=True)
            reader.start()
            try:
                for i, (text, snapshot, approve) in enumerate(turns):
                    send(text)
                    expect('【写入前核对 · 尚未认可】')
                    review = expect('认可上面这一版，单独输入「/认可」。')
                    for word in [text, snapshot['statement'], snapshot['kind'],
                                 *snapshot['scope'], *snapshot['unknowns'], *snapshot['contradictions']]:
                        check(word in review, f'{name}: pending wording missing: {word}')
                    if approve:
                        send('/认可')
                        expect('已记下对屏上这一版的认可')
                        if i == 0:
                            for _ in range(4):
                                send('跳过')
                proc.stdin.close()
                check(proc.wait(timeout=15) == 0, f'{name}: nonzero EOF')
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=5)
                proc.stdin.close()
                reader.join(timeout=5)
                proc.stdout.close()
                (self.out / f'{name}.discuss.txt').write_text(''.join(screen), encoding='utf-8')
        check(not self.errors and len(self.calls) == len(turns), (self.errors, len(self.calls)))
        endings = ''.join(screen).split('讨论已结束。')
        check(len(endings) == 2, f'{name}: not a normal close')
        self.ends[name] = endings[-1]
        command = self.footer(self.ends[name], '回看这一场说了什么')
        trace, = [Path(arg) for arg in command if arg.endswith('.jsonl')]
        check(trace.is_relative_to(self.home) and trace.is_file(), trace)
        rows = [json.loads(line) for line in trace.read_text(encoding='utf-8').splitlines()]
        check(rows[-1]['event'] == 'session_end' and rows[-1]['reason'] == 'eof', rows[-1])
        check(all(any(row.get('user') == text for row in rows) for text, _, _ in turns), 'original words missing')
        self.traces[name] = trace
        self.sessions[name] = trace.stem

    @staticmethod
    def footer(text, label):
        command, = [line.split('：', 1)[1] for line in text.splitlines() if line.startswith(label)]
        argv = shlex.split(command)
        check('--db' in argv, f'not addressed to original library: {command}')
        return argv

    def readback(self, model_env):
        def signatures():
            return {str(p): sha256(p.read_bytes()).hexdigest() for p in sorted(self.home.rglob('*')) if p.is_file()}

        before = signatures()
        self.calls.clear()
        self.turns = []  # every unexpected request fails locally
        reports, commands, listings = {}, {}, {}
        for name, turns in [('archive', OLD), ('A', A), ('B', B)]:
            transcript_cmd = self.footer(self.ends[name], '回看这一场说了什么')
            transcript = self.invoke(transcript_cmd, **model_env)
            (self.out / f'{name}.transcript.txt').write_text(transcript, encoding='utf-8')
            check(all(text in transcript for text, _, _ in turns), (name, 'original words in transcript'))
            list_cmd = self.footer(transcript, '看本场留下的版本和草稿')
            check(list_cmd == self.footer(self.ends[name], '稍后看本场留下的版本和草稿'), name)
            listing = self.invoke(list_cmd, **model_env)
            listings[name] = listing
            (self.out / f'{name}.distill.txt').write_text(listing, encoding='utf-8')
            report = self.cli('distill', '--session', self.sessions[name], **model_env)
            write_json(self.out / f'{name}.distill.json', report)
            check(report['session'] == self.sessions[name], name)
            approved = [r for r in report['cards'] if r['approval_status'] == 'approved']
            expected = [snapshot for _, snapshot, accept in turns if accept]
            check([r['version'] for r in approved] == list(range(1, 1 + len(expected))), (name, approved))
            check([{k: r[k] for k in s} for r, s in zip(approved, expected)] == expected, (name, approved))
            drafts = [r for r in report['cards'] if r['approval_status'] == 'unaccepted_draft']
            check([r['statement'] for r in drafts] == [s['statement'] for _, s, accept in turns if not accept], (name, drafts))
            check(all(r['classification'] is None for r in report['cards']), (name, 'must not classify'))
            check(len(approved) + len(drafts) == len(report['cards']), (name, 'entries from another session'))
            commands[name] = {'transcript': shlex.join(transcript_cmd), 'distill': shlex.join(list_cmd)}
            reports[name] = report
        ids = {name: {c['id'] for c in r['cards']} for name, r in reports.items()}
        check(all(ids[a].isdisjoint(ids[b]) for a, b in (('archive', 'A'), ('A', 'B'), ('B', 'archive'))), ids)
        old, = reports['archive']['cards']
        new, = reports['B']['cards']
        check(new['of'] == old['id'] or any(p['of'] == old['id'] for p in new['challenges']),
              ('old card should be a visible comparison', new, old))
        for name in ('A', 'B'):
            for item in reports[name]['cards']:
                broadcast = self.cli('broadcast', item['statement'], **model_env)
                check(not any(c['id'] in ids[name] for c in broadcast['results']), (name, broadcast))
                if item['approval_status'] == 'approved':
                    check(any(c['id'] == item['id'] and 'single-session' in c['reason']
                              for c in broadcast['suppressed']),
                          (name, 'fixture did not actually exercise suppression', broadcast))
                write_json(self.out / f'{name}.v{item["version"]}.{item["id"]}.broadcast.json', broadcast)
        if self.require_reader_paths:
            quote_cmds, help_cmd = self.reader_paths(listings, reports, model_env)
            for name, scene_cmds in quote_cmds.items():
                commands[name].update(scene_cmds)
            commands['B']['link_help'] = shlex.join(help_cmd)
            check(signatures() == before, 'following original words or help changed the original DB or traces')
            check(not self.calls and not self.errors, ('unexpected reader request', self.calls, self.errors))
            self.verify_binding(commands, model_env)
            self.explicit_link(help_cmd, new, old, model_env)
        write_json(self.out / 'commands.json', commands)
        check(not self.calls and not self.errors, ('unexpected readback request', self.calls, self.errors))
        check(signatures() == before, 'readback mutated original DB or traces')
        write_json(self.out / 'sha256-readback.json', before)

    def reader_paths(self, listings, reports, model_env):
        def entry(name, item):
            # Select what a reader sees, not the current card of the same ID.
            listing = listings[name]
            headings = list(re.finditer(r'^\[[^\n]+?\] (d-\S+) v(\d+) ', listing, re.M))
            i, = [i for i, match in enumerate(headings)
                  if match.groups() == (item['id'], str(item['version']))]
            end = headings[i + 1].start() if i + 1 < len(headings) else len(listing)
            return listing[headings[i].start():end]

        def read_words(name, evidence, target, text, tag):
            cmd = shlex.split(evidence)
            check(self.db == Path(cmd[cmd.index('--db') + 1]), ('not original DB', cmd))
            check('transcript' in cmd and '--turn' in cmd, ('not a focused transcript', cmd))
            raw = self.invoke(cmd, **model_env)
            (self.out / f'{name}.{tag}.txt').write_text(raw, encoding='utf-8')
            check(self.sessions[target] in raw, (target, 'wrong session', raw))
            spoken = re.findall(r'^\s+\[\d+\] 你说：(.*)$', raw, re.M)
            check(spoken == [text, '/认可'], (tag, 'not just the chosen version and its approval', spoken))
            check('主持人：' not in raw, (tag, 'focused display should contain user words only'))
            for foreign in set(self.sessions) - {target}:
                check(self.sessions[foreign] not in raw, ('foreign session inside quote', tag, foreign))
            return shlex.join(cmd)

        def one_line(block, prefix):
            line, = [line for line in block.splitlines() if line.strip().startswith(prefix)]
            return line.split('：', 1)[1]

        commands = {'A': {}, 'B': {}}
        old, = reports['archive']['cards']
        for name, turns in [('A', A), ('B', B)]:
            item, = [r for r in reports[name]['cards'] if r['version'] == 1 and r['approval_status'] == 'approved']
            block = entry(name, item)
            check(item['statement'] in block and all(scope in block for scope in item['scope']), (name, block))
            evidence = one_line(block, '回看本场原话')
            commands[name]['chosen_v1_original'] = read_words(name, evidence, name, turns[0][0], 'chosen-v1-original')
            check(OLD[0][0] not in listings[name], (name, 'old raw text in current listing'))
            check('按原边界留用' in listings[name] and '暂不采用' in listings[name], (name, 'take/decline not visible'))
            if name == 'A':
                check('回看对照卡' not in listings[name] and 'link --help' not in listings[name],
                      'A has no archive comparison; do not imply it needs a link')
            else:
                label = f'回看对照卡 {old["id"]} v{old["version"]} 的原话'
                evidence = one_line(block, label)
                local_scope, = item['scope']
                archive_scope, = old['scope']
                check(archive_scope in block and block.index(local_scope) < block.index(archive_scope) < block.index('回看本场原话'),
                      ('read both scopes before the long commands', block))
                commands[name]['old_v1_original'] = read_words(name, evidence, 'archive', OLD[0][0], 'old-v1-original')

        line, = [s for s in listings['B'].splitlines() if s.startswith('要关联而不合并')]
        check('核对双方原话' in line and '另行写入' in line, ('link is not an implicit write', line))
        help_cmd = shlex.split(line.split('用法：', 1)[1])
        check(help_cmd[-2:] == ['link', '--help'] and '--db' not in help_cmd, ('not just a help command', help_cmd))
        help_text = self.invoke(help_cmd, **model_env)
        (self.out / 'B.link-help.txt').write_text(help_text, encoding='utf-8')
        check(all(arg in help_text for arg in ('narrows', '--target', '--relation', '--reason')), help_text)
        return commands, help_cmd

    def verify_binding(self, commands, model_env):
        # Exercise both ends of the pasted command without editing the real replay artifacts.
        isolated = self.out / 'binding-fixtures'
        isolated.mkdir()
        local = self.traces['B']
        scratch = isolated / local.name
        local_rows = [json.loads(line) for line in local.read_text(encoding='utf-8').splitlines()]
        local_cmd = shlex.split(commands['B']['chosen_v1_original'])
        old_cmd = shlex.split(commands['B']['old_v1_original'])
        list_cmd = shlex.split(commands['B']['distill'])
        results = {}

        def write_rows(rows):
            scratch.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows), encoding='utf-8')

        def replace_trace(argv, path):
            argv = list(argv)
            i = argv.index('--trace' if '--trace' in argv else 'transcript') + 1
            argv[i] = str(path)
            return argv

        def rejects(argv, name):
            rejected = subprocess.run(replace_trace(argv, scratch), cwd=self.out, env=self.env | model_env,
                                      text=True, encoding='utf-8', capture_output=True, timeout=25)
            check(rejected.returncode == 2 and not rejected.stdout and '轨迹与清单定位时不同' in rejected.stderr,
                  (name, rejected.returncode, rejected.stdout, rejected.stderr))
            results[name] = rejected.stderr.strip()

        scratch.write_bytes(self.traces['archive'].read_bytes())
        rejects(local_cmd, 'local_replaced_with_archive')
        scratch.write_bytes(local.read_bytes())
        rejects(old_cmd, 'archive_replaced_with_local')
        # Same UID, approval and shape, but different words after copying the command.
        write_rows([{**local_rows[0], 'user': '替换过的用户原话'}, *local_rows[1:]])
        rejects(local_cmd, 'same_session_words_replaced')

        for name, rows in {
            'wrong_session': [*local_rows[:-1], {**local_rows[-1], 'session': self.sessions['archive']}],
            'wrong_version': [local_rows[0], {**local_rows[1], 'approval': {**local_rows[1]['approval'], 'version': 2}}, *local_rows[2:]],
            'wrong_card': [local_rows[0], {**local_rows[1], 'approval': {**local_rows[1]['approval'], 'id': 'another-card'}}, *local_rows[2:]],
            'duplicate_turn': [local_rows[0], *local_rows],
        }.items():
            write_rows(rows)
            text = self.invoke(replace_trace(list_cmd, scratch), **model_env)
            check('无法在给定轨迹定位这一版的认可轮' in text and '回看本场原话' not in text, (name, text))
            check(B[0][1]['statement'] in text, (name, 'approved snapshot was lost'))
            results[name] = 'listing kept approved snapshot but refused the original-words anchor'
        write_json(self.out / 'version-binding.json', results)

    def explicit_link(self, help_cmd, new, old, model_env):
        # Help explains the syntax; the reader still decides relation, direction and reason.
        copy = self.out / 'link-copy.sqlite3'
        copyfile(self.db, copy)
        prefix = [*help_cmd[:-2], '--db', str(copy)]
        reason = '本场只在单口且当面确认时考虑；旧卡包括未试过的双口，不采纳该外推。'
        old_before = json.loads(self.invoke([*prefix, 'show', old['id']], **model_env))
        current = json.loads(self.invoke([*prefix, 'show', new['id']], **model_env))['candidate']
        check(current['version'] == new['version'] == 1 and not current['relations'], current)
        cmd = [*prefix, 'link', new['id'], '--relation', 'narrows', '--target', old['id'], '--reason', reason]
        related = json.loads(self.invoke(cmd, **model_env))
        check(related == {**current, 'version': 2, 'relations': [{'type': 'narrows', 'target': old['id'], 'note': reason}]},
              ('link changed more than relation/version', current, related))
        check(related['status'] == 'draft' and related['sessions'] == [self.sessions['B']], related)
        check(json.loads(self.invoke([*prefix, 'show', old['id']], **model_env)) == old_before, 'old card modified')
        after = json.loads(self.invoke([*prefix, 'distill', '--session', self.sessions['B']], **model_env))
        approved, = after['cards']
        snapshot_keys = ['id', 'version', 'approval_status', *B[0][1].keys()]
        check(all(approved[key] == new[key] for key in snapshot_keys), ('approval snapshot changed', approved))
        write_json(self.out / 'B.link-copy.json', {'command': shlex.join(cmd), 'current': related, 'approved': approved})

    def main(self):
        replay = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                try:
                    check(self.path == '/v1/chat/completions', self.path)
                    request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                    i = len(replay.calls)
                    replay.calls.append(i)
                    text, snapshot, _ = replay.turns[i]
                    check(any(text in m['content'] for m in request['messages'] if m['role'] == 'user'),
                          'fixture turn mismatch')
                    reply = dict(answer='先按你刚说的范围拟这版，请核对。', candidate=snapshot,
                                 user_stance='neutral', person_updates=[])
                    body = json.dumps({'choices': [{'message': {'role': 'assistant', 'content':
                                      json.dumps(reply, ensure_ascii=False)}, 'finish_reason': 'stop'}]}).encode()
                except Exception as exc:
                    replay.errors.append(repr(exc))
                    self.send_error(400, 'Synthetic fixture disagreement')
                    return
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_):
                pass

        with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                model_env = dict(DOJO_LLM_BASE_URL=f'http://127.0.0.1:{server.server_port}/v1',
                                 DOJO_LLM_API_KEY='synthetic-fixture-only', DOJO_LLM_MODEL='synthetic-loopback')
                for name, turns in [('archive', OLD), ('A', A), ('B', B)]:
                    self.discuss(name, turns, model_env)
                self.readback(model_env)
            finally:
                server.shutdown()
                worker.join(timeout=5)
        reader_checks = ', copied originals/help, version and trace replacement controls, one explicit link on disposable copy' if self.require_reader_paths else ''
        print(f'PASS EOF → transcript → distill for A and B, archive comparison, read-only hashes, '
              f'zero readback requests, independent sessions{reader_checks}: {self.out}')


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('worktree', type=lambda s: Path(s).resolve())
    p.add_argument('output', type=lambda s: Path(s).resolve())
    p.add_argument('--require-reader-paths', action='store_true', help='also verify copied quote commands, link help, and explicit link on a separate DB')
    args = p.parse_args()
    Replay(args.worktree, args.output, args.require_reader_paths).main()
