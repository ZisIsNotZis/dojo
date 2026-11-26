"""Offline recipe checks: no credentials, outputs or retries escape the probe."""
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout

SPEC = importlib.util.spec_from_file_location('shape_probe', Path(__file__).resolve().parents[1] / 'scripts/probe_response_shape.py')
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


class ShapeProbeRecipeTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        trace = Path(directory.name) / 'synthetic-shape-seed.jsonl'
        rounds = [
            {'seq': 1, 'user': '合成样例：入口有红蓝两个标签。', 'answer': '先核对标签含义。'},
            {'seq': 2, 'user': '蓝签只供本次排练。', 'answer': '把使用条件写在结论里。',
             'candidate': {'statement': '蓝签仅用于本次排练。'}},
            {'seq': 3, 'user': '没有补充，请按现有条件回应。'},
        ]
        trace.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rounds),
                         encoding='utf-8')
        seed_override = patch.object(probe, 'SEED_TRACE', trace)
        seed_override.start()
        self.addCleanup(seed_override.stop)

    def test_only_the_system_prompt_varies_between_the_two_arms(self):
        a = probe.make_messages(probe.MINIMAL_PROMPT)
        b = probe.make_messages(probe.SYSTEM_PROMPT)
        self.assertEqual(['system', 'user', 'assistant', 'user', 'assistant', 'user'],
                         [message['role'] for message in a])
        self.assertIn('蓝签仅用于本次排练。', a[-1]['content'])
        self.assertEqual(a[1:], b[1:])
        self.assertNotEqual(a[0], b[0])

    def run_recipe(self, failure=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.agents').mkdir()
            (root / '.agents/auth.json').write_text(json.dumps({'deepseek': {'key':'CREDENTIAL_SENTINEL'}}), encoding='utf-8')
            target = root / 'output'
            sent = []
            class FakeClient:
                last_response_shape = {'top_type':'object'}
                def complete(self, messages):
                    sent.append(messages)
                    if failure and len(sent) == 1:
                        self.last_response_shape = None
                        raise probe.live.LiveError('ERROR_SENTINEL', kind='empty_content', raw_response='RAW_SENTINEL', detail='CREDENTIAL_SENTINEL')
                    return {'answer':'ANSWER_SENTINEL', 'candidate':None, 'user_stance':'neutral', 'person_updates':[],
                            'finish_reason':'stop', 'raw_response':'RAW_SENTINEL'}
            output = io.StringIO()
            with patch.object(probe.Path, 'home', return_value=root), patch.object(probe, 'make_client', side_effect=lambda config: FakeClient()), patch.object(probe.sys, 'argv', ['probe', str(target)]), redirect_stdout(output):
                self.assertEqual(0, probe.main())
            records = [json.loads(line) for line in (target / 'attempts.jsonl').read_text(encoding='utf-8').splitlines()]
            logged = output.getvalue() + ''.join(path.read_text(encoding='utf-8') for path in target.iterdir())
            for forbidden in ('CREDENTIAL_SENTINEL', 'ANSWER_SENTINEL', 'RAW_SENTINEL', 'ERROR_SENTINEL'):
                self.assertNotIn(forbidden, logged)
            self.assertEqual(2, len(sent))
            self.assertEqual(sent[0][1:], sent[1][1:])
            return records

    def test_transport_metadata_is_not_misclassified_as_model_schema(self):
        records = self.run_recipe()
        self.assertEqual(['valid_schema', 'valid_schema'], [row['classification'] for row in records])

    def test_failed_first_request_counts_and_does_not_trigger_a_retry(self):
        records = self.run_recipe(failure=True)
        self.assertEqual(['empty_content', 'valid_schema'], [row['classification'] for row in records])
        self.assertEqual(['minimal', 'full'], [row['arm'] for row in records])
        self.assertIsNone(records[0]['response_shape'])


if __name__ == '__main__':
    unittest.main()
