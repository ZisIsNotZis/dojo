#!/usr/bin/env python3
"""Public CLI walk with scripted completions served only over loopback."""
import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
import shlex
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Thread


ROOT = Path(__file__).resolve().parents[1]
OPENING = '我们社区借用陶艺工具。上周收摊，我发现两把外形一样的刮刀放错了袋。'
SITUATION = '上周摊位撤场，我发现两把一样的刮刀混袋。'
DETAIL = '私人记号青鹿七三是我记耗时的办法，这句只留在这场记录。'
LIMIT = '有裂纹的刮刀我会先隔离，不按普通件交还。'
QUERY = '归还刮刀隔离'
PROFILE_NOTE = '只供原作者使用的合成档案：练习给釉色起名。'
PROFILE_SUGGESTION = '模型建议附记：偏爱借用表格。'
CANDIDATE = {
    'statement': '归还刮刀前先核对袋上的工具编号。', 'kind': 'experience_claim',
    'scope': ['同批外形相近、编号仍可辨的刮刀'],
    'premises': ['主持人推测编号和袋有一对一对应'],
    'alternatives': [], 'contradictions': ['编号磨掉时不能靠这个办法认领'],
    'unknowns': ['还没比较编号看不清时的替代办法'],
}


DRAFT = {**CANDIDATE, 'statement': '空台试装可先用孔雀形夹，但不接待来客。',
         'scope': ['仅限空台试装']}
DRAFT_ORIGINAL = '我空台装木背板时用了孔雀形夹，没靠承重。'
REVIEW_LIMIT = '试装期间不承重。'


def walk(root, *, selected):
    payloads = []

    class Replay(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            assert self.path == '/v1/chat/completions'
            payloads.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            proposal = {1: CANDIDATE, 4: DRAFT}.get(len(payloads))
            reply = dict(answer='先分开看核对编号和处理损坏这两件事。', candidate=proposal,
                         person_updates=[PROFILE_SUGGESTION], user_stance='neutral')
            body = json.dumps({'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(reply, ensure_ascii=False)}}]}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    with HTTPServer(('127.0.0.1', 0), Replay) as server:
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            env = dict(PATH=os.environ['PATH'], HOME=str(root), PYTHONUTF8='1',
                       NO_PROXY='127.0.0.1', DOJO_DB=str(root / 'library.sqlite3'),
                       DOJO_LLM_BASE_URL=f'http://127.0.0.1:{server.server_port}/v1',
                       DOJO_LLM_MODEL='scripted-loopback-no-model')

            def cli(name, *args, lines=(), status=0):
                result = subprocess.run([sys.executable, '-B', '-m', 'dojo', *args], cwd=ROOT,
                                        env=env, input='\n'.join(lines) + ('\n' if lines else ''),
                                        capture_output=True, encoding='utf-8', timeout=15)
                (root / f'{name}.stdout.txt').write_text(result.stdout, encoding='utf-8')
                (root / f'{name}.stderr.txt').write_text(result.stderr, encoding='utf-8')
                assert result.returncode == status, result.stdout + result.stderr
                return result.stdout

            profile = root / 'person.md'
            profile.write_text(PROFILE_NOTE + '\n', encoding='utf-8')
            profile.chmod(0o600)
            original_profile = profile.read_bytes()
            inputs = [OPENING, '/认可', SITUATION, '跳过', DETAIL, LIMIT]
            if selected:
                inputs += ['/附答 情境 失效']
            output = cli('first', 'discuss', lines=inputs)
            records = json.loads(cli('list', 'list'))
            assert len(records) == 1, records
            card = records[0]['id']
            show = json.loads(cli('show', 'show', card))
            trace, = (root / 'sessions').glob('*.jsonl')
            command, = (line.split('回看这一场说了什么：', 1)[1].strip()
                        for line in output.splitlines() if '回看这一场说了什么：' in line)
            argv = shlex.split(command)
            assert argv[:3] == ['python3', '-m', 'dojo'], argv
            transcript = cli('transcript', *argv[3:])
            assert all(text in transcript for text in (SITUATION, DETAIL, LIMIT))
            questions = [line.split('问的是：', 1)[1] for line in transcript.splitlines() if '问的是：' in line]
            assert len(questions) == 4 and all(questions), questions
            query = cli('search-private-word', 'search', '青鹿七三')
            assert [row['id'] for row in json.loads(query)['results']] == []
            cli('search', 'search', QUERY)
            screen = cli('separate-discussion', 'discuss', '--card', card,
                lines=['我管的是乐器出租，琴盒里有损坏件时该怎样点收？'])
            assert len(payloads) == 2, len(payloads)
            handoff = json.dumps(payloads[1], ensure_ascii=False)
            (root / 'reader-request.json').write_text(handoff, encoding='utf-8')
            held = show.get('answers', {})
            expected = {'situation': SITUATION, 'off': LIMIT} if selected else {}
            assert {key: item['answer'] for key, item in held.items()} == expected, held
            assert DETAIL not in handoff
            assert DETAIL not in screen
            for name in ('search.stdout', 'search.stderr', 'search-private-word.stdout',
                         'search-private-word.stderr', 'show.stdout', 'show.stderr',
                         'separate-discussion.stdout', 'separate-discussion.stderr'):
                side = (root / (name + '.txt')).read_text(encoding='utf-8')
                assert trace.name not in side, name
            assert trace.name not in handoff
            reader_trace, = [path for path in (root / 'sessions').glob('*.jsonl') if path != trace]
            reader_log = reader_trace.read_text(encoding='utf-8')
            handouts = [row for raw in reader_log.splitlines() if (row := json.loads(raw)).get('event') == 'handout']
            assert len(handouts) == 1 and set(handouts[0]['answers']) == set(expected)
            assert all('question' not in item for item in handouts[0]['answers'].values())
            public_metadata = ''.join((root / filename).read_text(encoding='utf-8') for filename in (
                'search.stdout.txt', 'search.stderr.txt', 'show.stdout.txt', 'show.stderr.txt',
            ))
            for question in questions:
                for reader_surface in (public_metadata, handoff, screen, reader_log):
                    assert question not in reader_surface
            for quote in (LIMIT, SITUATION):
                assert (quote in handoff) == selected
                assert (quote in screen) == selected
            assert CANDIDATE['contradictions'][0] in handoff
            assert CANDIDATE['premises'][0] in handoff
            assert '主持人拟写（不是你的原话，也未经独立核验）' in output
            assert '已记下对屏上这一版的认可' in output
            print(f'Attached {list(expected)}; later search and handoff are bounded; '
                  'the author can still replay the local trace')
            assert profile.read_bytes() == original_profile
            assert all(PROFILE_NOTE not in json.dumps(req, ensure_ascii=False) for req in payloads)
            assert PROFILE_SUGGESTION not in handoff
            owner = cli('own-profile', 'discuss', '--with-profile', lines=['我继续自己的釉色练习。'])
            assert len(payloads) == 3
            assert PROFILE_NOTE in json.dumps(payloads[2], ensure_ascii=False)
            assert '人物档案会作为上下文发送给模型' in owner
            assert profile.read_bytes().startswith(original_profile)
            assert PROFILE_SUGGESTION in profile.read_text(encoding='utf-8')
            if selected:
                print('读者取舍：乐器点收先隔离损坏件，不借用刮刀编号与袋子一一对应的前提。')

                pending = cli('draft-close', 'discuss', lines=[DRAFT_ORIGINAL])
                assert len(payloads) == 4
                records = json.loads(cli('author-library', 'list'))
                draft, = (row for row in records if row.get('unaccepted_draft'))
                hint, = (line.split('：python3', 1)[1] for line in pending.splitlines()
                         if line.startswith('找回本场先前的拟写（'))
                review_args = shlex.split('python3' + hint)[3:]
                before = (root / 'library.sqlite3').read_bytes()
                skipped = cli('draft-skip', *review_args, lines=['1', '/略过', '/退出'])
                assert DRAFT_ORIGINAL in skipped and DRAFT['statement'] in skipped
                assert before == (root / 'library.sqlite3').read_bytes()
                found = cli('draft-query', 'search', '背板试装')
                visible = found + (root / 'draft-query.stderr.txt').read_text(encoding='utf-8')
                assert DRAFT['statement'] not in visible and draft['id'] not in visible
                refused = cli('draft-refused', 'discuss', '--card', draft['id'],
                              lines=['有人靠着木背板，这个夹子能用吗？'], status=2)
                assert DRAFT['statement'] not in refused
                assert DRAFT['statement'] not in (root / 'draft-refused.stderr.txt').read_text(encoding='utf-8')
                assert len(payloads) == 4
                saved = cli('draft-retained', *review_args,
                            lines=['1', '/补边界 ' + REVIEW_LIMIT, '/留下'])
                assert DRAFT_ORIGINAL in saved and '已留下并认可第 1 轮的屏上版本：' in saved
                assert len(payloads) == 4
                kept = json.loads(cli('draft-now-card', 'search', '孔雀形夹'))['results']
                approved, = (row for row in kept if row['statement'] == DRAFT['statement'])
                read = cli('draft-approved-reader', 'discuss', '--card', approved['id'],
                           lines=['有人靠着木背板，这个夹子能用吗？'])
                assert len(payloads) == 5
                wire = json.dumps(payloads[4], ensure_ascii=False)
                for surface in (read, wire):
                    assert DRAFT['statement'] in surface and REVIEW_LIMIT in surface
                    assert DRAFT_ORIGINAL not in surface and PROFILE_NOTE not in surface
                print('草稿由原作者离线找回、略过再打开，明确留下含补注的版本后才可跨场借用。')
            print(f'Artifacts: {root}')
        finally:
            server.shutdown()
            worker.join()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='new directory for artifacts; defaults to a new temp directory')
    args = parser.parse_args()
    if args.output is None:
        root = Path(tempfile.mkdtemp(prefix='dojo-retention-'))
    else:
        root = args.output.resolve()
        root.mkdir(parents=True, exist_ok=False)
    for name, selected in (('default-eof', False), ('explicit-parts', True)):
        case = root / name
        case.mkdir()
        walk(case, selected=selected)


if __name__ == '__main__':
    main()
