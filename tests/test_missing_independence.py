"""A takeover reader needs a checking order, not a truth score.

The rule pinned here: a conclusion's independent support counts distinct source
URLs with a visible body, read from its own evidence premises. User reports,
model proposals and critiques are not independent support; two reads of one URL
are one material; a premise event this library cannot read is `unknown`, never
silently zero or one. Removing a failure must change both the order and the
reason, not just a word.
"""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from dojo.inquiry import Inquiry
from dojo.stories import reading_context

PREFIX = 'https://example.org/'


class MissingIndependenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'db.sqlite'
        self.q = Inquiry(self.path, SimpleNamespace(config=SimpleNamespace(model='offline-fixture')),
                         synthetic=False)
        self.story = self.q.story

    def tearDown(self):
        self.q.close()
        self.tmp.cleanup()

    def read(self, url, text='正文：4.0 及以上'):
        return self.q.record('tool_result', {'action': {'kind': 'read_source', 'url': url},
                                             'status': 'executed', 'result': {'url': url, 'text': text}})

    def fail(self, url, error='source_type'):
        return self.q.record('tool_result', {'action': {'kind': 'read_source', 'url': url},
                                             'status': 'failed', 'error_kind': error})

    def propose(self, statement, *premises):
        return self.q.record('knowledge_proposal', {'synthetic': False, 'proposal': {
            'statement': statement, 'premises': list(premises)}})

    def block(self):
        return reading_context(self.path, self.story)['story_coverage']['missing_independence']

    def test_a_failing_declared_source_leads_a_two_material_conclusion(self):
        a1, a2 = self.read(PREFIX + 'a1'), self.read(PREFIX + 'a2#table')
        bad = self.fail(PREFIX + 'b')
        a = self.propose('规格为 4.0 及以上。', {'event': a1, 'quote': 'q', 'role': 'evidence'},
                         {'event': a2, 'quote': 'q', 'role': 'evidence'})
        b = self.propose('两日内可确认供货。', {'event': bad, 'quote': 'q', 'role': 'evidence'})
        rows = self.block()['items']
        self.assertEqual([b, a], [row['conclusion_event'] for row in rows])
        self.assertEqual(['missing_body', 'independent'], [row['rank_class'] for row in rows])
        self.assertEqual([PREFIX + 'b'], rows[0]['unread_declared_urls'])
        self.assertEqual([PREFIX + 'a1', PREFIX + 'a2'], rows[1]['distinct_material_sources'])
        self.assertNotEqual(rows[0]['gap'], rows[1]['gap'])
        self.assertNotEqual(rows[0]['next_check'], rows[1]['next_check'])
        for row in rows:
            self.assertEqual('unknown', row['freshness'])
            self.assertTrue(row['freshness_reason'])
            self.assertIn('distinct_source_url', row['independence_basis'])

    def test_removing_the_failure_demotes_and_rewrites_the_reason(self):
        before = self.fail(PREFIX + 'x')
        broken = self.propose('旧说法。', {'event': before, 'quote': 'q', 'role': 'evidence'})
        old = self.block()['items'][0]
        self.assertEqual('missing_body', old['rank_class'])
        self.assertEqual([PREFIX + 'x'], old['unread_declared_urls'])

        # A second story in the same library states the same claim, but its
        # declared source now reads successfully. The earlier story's failure
        # is untouched, so its claim must still be its own story's first row.
        other = Inquiry(self.path, SimpleNamespace(config=SimpleNamespace(model='offline-fixture')),
                        synthetic=False)
        try:
            body = other.record('tool_result', {'action': {'kind': 'read_source', 'url': PREFIX + 'y'},
                                                'status': 'executed',
                                                'result': {'url': PREFIX + 'y', 'text': '正文'}})
            fixed = other.record('knowledge_proposal', {'synthetic': False, 'proposal': {
                'statement': '旧说法。', 'premises': [{'event': body, 'quote': 'q', 'role': 'evidence'}]}})
            later = other.record('tool_result', {'action': {'kind': 'read_source',
                                                           'url': PREFIX + 'z'},
                                                'status': 'failed', 'error_kind': 'source_connect'})
            leading = other.record('knowledge_proposal', {'synthetic': False, 'proposal': {
                'statement': '另一说法。',
                'premises': [{'event': later, 'quote': 'q', 'role': 'evidence'}]}})
            demoted = reading_context(self.path, other.story)[
                'story_coverage']['missing_independence']['items']
        finally:
            other.close()
        rows = {row['conclusion_event']: row for row in demoted}
        self.assertEqual('single_material', rows[fixed]['support_status'])
        self.assertEqual('missing_body', rows[leading]['rank_class'])
        self.assertNotEqual(old['gap'], rows[fixed]['gap'])
        self.assertNotEqual(old['next_check'], rows[fixed]['next_check'])
        self.assertEqual(leading, demoted[0]['conclusion_event'])
        self.assertEqual(
            [broken, fixed], [row['conclusion_event'] for row in self.block()['items']])

    def test_same_url_failure_does_not_erase_its_cited_body_in_either_order(self):
        bad = self.fail(PREFIX + 'm#retry')
        body = self.read(PREFIX + 'm')
        for i, order in enumerate(((bad, body), (body, bad))):
            self.propose(f'提议 {i}。', *({'event': event, 'quote': 'q', 'role': 'evidence'} for event in order))
        rows = self.block()['items']
        self.assertEqual(['single_source', 'single_source'], [row['rank_class'] for row in rows])
        for row in rows:
            self.assertEqual([], row['unread_declared_urls'])
            self.assertEqual([PREFIX + 'm'], row['distinct_material_sources'])

    def test_revised_conclusion_does_not_take_the_first_check(self):
        failed = self.fail(PREFIX + 'b')
        old = self.propose('旧说法。', {'event': failed, 'quote': 'q', 'role': 'evidence'})
        body = self.read(PREFIX + 'c')
        new = self.propose('替代说法。', {'event': body, 'quote': 'q', 'role': 'evidence'})
        self.q.dependencies.revise(old, new, '修订不是判真')
        self.assertEqual([new], [row['conclusion_event'] for row in self.block()['items']])

    def test_one_url_read_twice_is_one_material(self):
        first, second = self.read(PREFIX + 'm'), self.read(PREFIX + 'm#spec')
        claim = self.propose('扭矩上限见第 3 节。', {'event': first, 'quote': 'q', 'role': 'evidence'},
                             {'event': second, 'quote': 'q', 'role': 'evidence'})
        row = self.block()['items'][0]
        self.assertEqual(claim, row['conclusion_event'])
        self.assertEqual('single_group', row['rank_class'])
        self.assertEqual([PREFIX + 'm'], row['distinct_material_sources'])
        self.assertEqual(2, row['evidence_premises'])

    def test_user_words_are_not_support_and_unknown_is_not_zero(self):
        said = self.q.record('user', {'text': '我记得保修两年。'})
        claim = self.propose('保修为两年。', {'event': said, 'quote': 'q', 'role': 'evidence'})
        broken = self.propose('周转为每月一次。', {'event': 99999, 'quote': 'q', 'role': 'evidence'})
        rows = {row['conclusion_event']: row for row in self.block()['items']}
        self.assertEqual('no_source', rows[claim]['rank_class'])
        self.assertEqual('not_independent_support', rows[claim]['have'][0]['state'])
        self.assertEqual('unknown', rows[broken]['rank_class'])
        self.assertEqual(1, rows[broken]['unresolved_premises'])
        self.assertEqual('no_source', self.block()['items'][0]['rank_class'])

    def test_a_malformed_premise_list_is_unknown_not_empty(self):
        self.q.record('knowledge_proposal', {'synthetic': False, 'proposal': {
            'statement': '格式损坏的旧提议。', 'premises': 'not-a-list'}})
        row = self.block()['items'][0]
        self.assertEqual('unknown', row['rank_class'])
        self.assertEqual(1, row['malformed_premise_list'])

    def test_absent_without_any_conclusion(self):
        coverage = reading_context(self.path, self.story)['story_coverage']
        self.assertNotIn('missing_independence', coverage)

    def test_the_view_is_read_only(self):
        self.read(PREFIX + 'r')
        self.propose('带来源的结论。', {'event': self.q.record('user', {'text': 'x'}),
                                       'quote': 'q', 'role': 'evidence'})
        before = self.path.read_bytes()
        self.block()
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual(['db.sqlite'], sorted(p.name for p in self.path.parent.iterdir()))
        with sqlite3.connect(self.path) as conn:
            self.assertGreater(conn.execute('SELECT COUNT(*) FROM inquiry_events').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
