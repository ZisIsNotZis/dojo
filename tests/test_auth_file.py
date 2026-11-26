"""Credential channel: one explicit local file, read once, failures name the file.

The value must never reach a message, a report, an argv or the environment.
`test_*` names say which leak each case would catch; probe_red_control.py in
.scratch/dojo-grid/r97/ shows each of them does go red on a leaking reader.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dojo.inquiry import config_from_auth_file
from dojo.live import LiveError

SENTINEL = 'sk-should-never-appear-in-any-message'


class AuthFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def message(self, path):
        with self.assertRaises(LiveError) as caught:
            config_from_auth_file(path)
        self.assertEqual('config', caught.exception.kind)
        return str(caught.exception)

    def test_well_formed_file_yields_a_config_without_reading_the_environment(self):
        p = self.dir / 'auth.json'
        p.write_text(json.dumps({'deepseek': {'type': 'api', 'key': SENTINEL}}), encoding='utf-8')
        with patch.dict('os.environ', {}, clear=True):
            config = config_from_auth_file(p)
        self.assertEqual('deepseek-flash', config.model)
        self.assertEqual('https://api.deepseek.com/v1/chat/completions', config.endpoint)
        self.assertEqual(SENTINEL, config.api_key)

    def test_missing_file_names_the_file_and_leaks_nothing(self):
        path = self.dir / 'absent' / 'auth.json'
        msg = self.message(path)
        self.assertIn(str(path), msg)
        self.assertIn('不存在', msg)
        self.assertNotIn(SENTINEL, msg)

    def test_missing_key_names_the_key_and_leaks_the_neighbouring_value(self):
        p = self.dir / 'auth.json'
        p.write_text(json.dumps({'deepseek': {'type': 'api', 'token': SENTINEL}}), encoding='utf-8')
        msg = self.message(p)
        self.assertIn('deepseek.key', msg)
        self.assertNotIn(SENTINEL, msg)

    def test_key_of_wrong_type_is_refused_without_echoing_the_value(self):
        p = self.dir / 'auth.json'
        p.write_text(json.dumps({'deepseek': {'key': 12345, 'note': SENTINEL}}), encoding='utf-8')
        msg = self.message(p)
        self.assertIn('非空字符串', msg)
        self.assertNotIn('12345', msg)
        self.assertNotIn(SENTINEL, msg)

    def test_unreadable_path_reports_the_os_error_class_only(self):
        d = self.dir / 'auth.json.d'
        d.mkdir()
        msg = self.message(d)
        self.assertIn('不可读', msg)
        self.assertNotIn(SENTINEL, msg)

    def test_malformed_json_does_not_echo_file_content(self):
        p = self.dir / 'auth.json'
        p.write_text('{"deepseek": {"key": ' + SENTINEL, encoding='utf-8')
        msg = self.message(p)
        self.assertIn('不是合法 JSON', msg)
        self.assertNotIn(SENTINEL, msg)

    def test_sibling_models_json_can_move_the_endpoint(self):
        p = self.dir / 'auth.json'
        p.write_text(json.dumps({'deepseek': {'key': SENTINEL}}), encoding='utf-8')
        (self.dir / 'models.json').write_text(
            json.dumps({'providers': {'deepseek': {'baseUrl': 'https://example.invalid'}}}), encoding='utf-8')
        self.assertEqual('https://example.invalid/v1/chat/completions', config_from_auth_file(p).endpoint)

    def test_recheck_reads_the_file_before_building_any_client(self):
        from dojo import reviews
        calls = []
        with patch.object(reviews, 'make_client', side_effect=lambda config, **kw: calls.append(config)):
            with self.assertRaises(LiveError) as caught:
                reviews.run_rechecks(self.dir / 'db', auth_file=self.dir / 'absent.json')
        self.assertEqual([], calls, 'no client may be built before the credential file reads cleanly')
        self.assertIn('absent.json', str(caught.exception))
        self.assertNotIn(SENTINEL, str(caught.exception))


if __name__ == '__main__':
    unittest.main()
