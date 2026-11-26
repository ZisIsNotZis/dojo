"""Two predeclared DeepSeek requests, no retries; run only after offline review.

Synthetic input, not user research. No raw response values or request payloads logged.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dojo.discuss import SYSTEM_PROMPT, validate_conclusion
from dojo import live

SEED_TRACE = Path(__file__).resolve().parents[1] / 'docs/evidence/2026-11-12-deepseek-synthetic/discuss-6fa582563d4b4e7cada290edc4d00545.jsonl'
MINIMAL_PROMPT = '''请用中文回应用户的想法，区分假设与事实。只返回JSON对象，不要代码围栏。四个键必须且只能为answer、candidate、user_stance、person_updates。answer为非空字符串，candidate为null，user_stance为neutral，person_updates为空数组。'''


def make_messages(prompt: str):
    """Reconstruct the first failing round's synthetic six-message context."""
    rows = [json.loads(line) for line in SEED_TRACE.read_text(encoding='utf-8').splitlines()]
    rounds = {row['seq']: row for row in rows if 'seq' in row}
    history = []
    for seq in (1, 2):
        row = rounds[seq]
        history += [{'role':'user','content':'用户本轮自然语言输入：\n' + row['user'] + '\n\n请按系统约定返回 json。'},
                    {'role':'assistant','content':row['answer']}]
    context = '用户本轮自然语言输入：\n' + rounds[3]['user']
    context += '\n\n上一轮已经呈现给用户的当前结论：\n' + json.dumps(rounds[2]['candidate'], ensure_ascii=False, separators=(',', ':'))
    context += '\n\n只有用户明确认可这条结论的实质内容时才报告 user_stance=accept，并原样返回完全相同的 candidate。若用户只是说没有更多、不确定或类似收束语，报告 neutral，直接贡献判断，不再追问同类问题。纠正或反对时按新信息修订或撤回候选。'
    context += '\n\n请按系统约定返回 json。'
    return [{'role':'system','content':prompt}, *history, {'role':'user','content':context}]


def make_client(config):
    return live.OpenAICompatibleClient(
        config, allowed_extra_keys=frozenset({'user_stance', 'person_updates'}),
        allow_search=True, max_answer_chars=live.MAX_DISCUSS_ANSWER_CHARS,
        max_completion_chars=live.MAX_DISCUSS_COMPLETION_CHARS,
        max_response_bytes=live.MAX_DISCUSS_RESPONSE_BYTES,
        max_tokens=live.MAX_TOKENS,
        max_raw_response_chars=live.MAX_DISCUSS_RAW_RESPONSE_CHARS,
        max_statement_chars=live.MAX_DISCUSS_STATEMENT_CHARS,
        max_field_chars=live.MAX_DISCUSS_FIELD_CHARS,
        max_fields_per_list=live.MAX_DISCUSS_FIELDS_PER_LIST,
        reasoning_effort='medium', max_request_chars=live.MAX_DISCUSS_REQUEST_CHARS,
    )


def main() -> int:
    target = Path(sys.argv[1])
    target.mkdir(parents=True, exist_ok=False)
    key = json.loads((Path.home() / '.agents/auth.json').read_text(encoding='utf-8'))['deepseek']['key']
    config = live.LiveConfig('https://api.deepseek.com/chat/completions', 'deepseek-flash', key, timeout=120)
    recipe = {'synthetic': True,
              'context_source':'reconstructed first failing round (seq=3), original synthetic trace; same six-message context in both arms',
              'seed_trace_sha256':hashlib.sha256(SEED_TRACE.read_bytes()).hexdigest(),
              'endpoint':config.endpoint, 'model':config.model,
              'reasoning_effort':'medium', 'max_tokens':live.MAX_TOKENS, 'timeout_seconds':120,
              'planned_requests':2, 'authorized_max_requests':3, 'automatic_retries':0,
              'purpose':'Compare minimal JSON contract with full host prompt. No stability or user-value claim.'}
    (target / 'recipe.json').write_text(json.dumps(recipe, ensure_ascii=False, indent=2), encoding='utf-8')
    for seq, (arm, prompt) in enumerate([('minimal', MINIMAL_PROMPT), ('full', SYSTEM_PROMPT)], 1):
        client = make_client(config)
        messages = make_messages(prompt)
        started = time.monotonic()
        record = {'request':seq, 'arm':arm,
                  'prompt_sha256':hashlib.sha256(prompt.encode('utf-8')).hexdigest(),
                  'context_sha256':hashlib.sha256(json.dumps(messages[1:], ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()}
        # Persist a conservative attempt count before sending; never infer zero cost after interruption.
        with (target / 'request-ledger.jsonl').open('a', encoding='utf-8') as ledger:
            ledger.write(json.dumps({'request':seq, 'arm':arm, 'event':'started'}) + chr(10))
        try:
            value = client.complete(messages)
            model_value = {key: item for key, item in value.items() if key not in {'finish_reason', 'raw_response'}}
            if 'search' in model_value:
                if model_value.get('user_stance') not in {'accept', 'reject', 'neutral'}:
                    raise live.LiveError('invalid stance', kind='schema_violation')
                classification = 'valid_search_request_not_executed'
            else:
                validate_conclusion(model_value)
                classification = 'valid_schema'
            record.update(classification=classification, completion_sha256=hashlib.sha256(json.dumps(model_value, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest())
        except live.LiveError as exc:
            record.update(classification=exc.kind, http_status=exc.http_status)
        record['elapsed_seconds'] = round(time.monotonic() - started, 3)
        record['response_shape'] = getattr(client, 'last_response_shape', None)
        with (target / 'attempts.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + '\n')
        print(json.dumps(record, ensure_ascii=False), flush=True)
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
