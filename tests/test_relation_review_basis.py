"""r92: `question_review` must record the same basis `knowledge_review` does.

Until r92 the relation review row carried five keys and nothing else, while
`knowledge_review` had recorded `premise_events`/`basis_readings` since r86.
Two review rows in one product disagreeing about whether 'what did this stand
on, and when was that recorded' is a question worth answering is the defect --
not a missing field.

These tests pin the shape, the named difference from the knowledge row, and
that the read side exists at all: a basis nobody can print is still unobserved.
The real-identity comparison lives in `.scratch/dojo-grid/r92/probe.py`, because
it needs the same corpus order in both rows to avoid reporting a time
difference as a code difference.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from dojo.inquiry import Inquiry
from dojo.question_reviews import apply_review, relation_basis, review_basis_view, review_packet


class Host:
    config = SimpleNamespace(model='deepseek-flash', api_key=None)


class RelationBasisTests(unittest.TestCase):
    def setUp(self):
        self._env = os.environ.pop('DOJO_REVIEW_RECORD', None)
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.q = Inquiry(Path(self.tmp.name) / 'db', Host(), synthetic=True)
        q = self.q
        self.user = q.record('user', {'text': '我只看时间成本', 'synthetic': True})
        q.user_sources[self.user] = '我只看时间成本'
        q.visible_source_text[self.user] = '我只看时间成本'
        self.tool = q.record('tool_result', {'status': 'executed', 'result': {'net': 48}})
        q.visible_source_text[self.tool] = q.knowledge.source(self.tool)['text']
        proposal = {'statement': '6次报告净省48分钟', 'kind': 'decision', 'method': 'deduction',
                    'premises': [{'event': self.tool, 'quote': '"net": 48', 'role': 'evidence'}],
                    'assumptions': ['每次净省8分钟'], 'conditions': ['只做6次'],
                    'alternatives': ['保留手工'], 'falsifier': '设置成本超过48分钟', 'revises': None}
        self.claim = q.knowledge.accept(q.run, proposal, {self.tool}, synthetic=True)
        q.visible_source_text[self.claim] = q.knowledge.source(self.claim)['text']
        created = q.questions.apply(q, {'kind': 'map_inquiry',
            'questions': [{'key': 'root', 'text': '交接必须保留什么？', 'parents': [],
                           'origin_event': self.user, 'origin_quote': '我只看时间成本', 'revises': None}],
            'links': [{'question': 'root', 'proposition': self.claim, 'source_event': self.tool,
                       'quote': '"net": 48', 'relation': 'challenges',
                       'explanation': '净收益不等于判据成立'}],
            'prediction': '组织待核实条件'})
        self.node = created['question_keys']['root']
        q.visible_source_text[self.node] = q.knowledge.source(self.node)['text']
        self.target = q.questions.view(story=q.story, synthetic=True)['nodes'][0]['annotations'][0]['event']
        self.fresh = q.record('tool_result', {'status': 'executed', 'result': {'net': -52}})
        q.dependencies.revise(self.tool, self.fresh, '修正后的观察')

    def tearDown(self):
        self.q.close()
        self.tmp.cleanup()
        os.environ.pop('DOJO_REVIEW_RECORD', None)
        if self._env is not None:
            os.environ['DOJO_REVIEW_RECORD'] = self._env

    def review(self, review=None):
        return apply_review(self.q, review_packet(self.q, self.target),
                            review or {'disposition': 'unresolved', 'reason': '材料不足', 'replacement': None})

    def last_row(self):
        return json.loads(self.q.db.execute(
            "SELECT payload FROM inquiry_events WHERE kind='question_review' ORDER BY seq DESC").fetchone()[0])

    def test_the_row_carries_the_quotation_with_its_own_recorded_time(self):
        self.review()
        row = self.last_row()
        self.assertEqual(1, len(row['premise_events']))
        item = row['premise_events'][0]
        stored = self.q.db.execute('SELECT at FROM inquiry_events WHERE seq=?', (self.tool,)).fetchone()[0]
        self.assertEqual(stored, item['at'])
        self.assertEqual('"net": 48', item['quote'])
        self.assertEqual('field', item['citation_kind'])
        self.assertEqual([item['reading']], row['basis_readings'])
        self.assertIn(item['at'], item['reading'])

    def test_the_relation_label_does_not_borrow_the_premise_role_key(self):
        """Same position, different vocabulary -- and said out loud, not merged.

        `knowledge_review` stores evidence/assumption/value under `role`. A
        relation's label is supports/challenges/context. Putting both under
        `role` would give one key two meanings, which is exactly what a reader
        comparing the two rows would then not be told.
        """
        self.review()
        item = self.last_row()['premise_events'][0]
        self.assertNotIn('role', item)
        self.assertEqual('challenges', item['relation'])

    def test_a_replaced_citation_is_named_replaced_in_the_reading(self):
        """The quote below was revised before the review was written.

        Only `needs_review` used to be spoken. A superseded citation read
        exactly like a live one -- found by diffing a question row against a
        knowledge row on the same quotation.
        """
        self.review()
        item = self.last_row()['premise_events'][0]
        self.assertEqual('superseded', item['dependency_state'])
        self.assertIn('这条依据后来已被替换', item['reading'])

    def test_the_legacy_switch_removes_the_basis_and_the_reader_says_so(self):
        """Control arm: same code path, basis off. Proves it is computed.

        A basis field that survived the switch would be a template, not a
        reading of what the review used.
        """
        os.environ['DOJO_REVIEW_RECORD'] = 'legacy'
        try:
            self.review()
        finally:
            os.environ.pop('DOJO_REVIEW_RECORD', None)
        row = self.last_row()
        self.assertEqual(['disposition', 'packet_sha256', 'reason', 'replacement_event', 'target'],
                         sorted(row))
        attempts = review_basis_view(self.q, self.target)
        self.assertTrue(attempts)
        self.assertIn('basis_missing', attempts[-1])
        self.assertNotIn('premise_events', attempts[-1])

    def test_the_cli_shows_the_basis_only_when_asked(self):
        """Opt-in, because the default view is fed verbatim to the model."""
        self.review()
        quiet = self.q.questions.view(story=self.q.story, synthetic=True)
        self.assertNotIn('review_attempts', json.dumps(quiet, ensure_ascii=False))
        loud = self.q.questions.view(story=self.q.story, synthetic=True, with_review_basis=True)
        annotation = loud['nodes'][0]['annotations'][0]
        self.assertIn('review_attempts', annotation)
        self.assertEqual(self.last_row()['premise_events'],
                         annotation['review_attempts'][0]['premise_events'])

    def test_the_relation_row_says_what_happened_to_the_version_it_produced(self):
        """r95: 15 of 104 stored relation rows name an outcome that was replaced.

        `disposition` is what the review decided; it is not a statement about
        whether the version it produced is still current.
        """
        self.review()
        attempt = review_basis_view(self.q, self.target)[-1]
        self.assertIn('replacement_event', attempt)
        # This fixture's review is `unresolved`: no version was produced, and
        # that must not read as 'the produced version is still standing'.
        self.assertIsNone(attempt['replacement_event'])
        self.assertIn('没有产出新版本', attempt['outcome_state_now'])
        self.assertNotIn('至今没被换掉', attempt['outcome_state_now'])

    def test_the_basis_is_computed_from_the_packet_not_from_what_the_model_said(self):
        """The review response has no basis field; it cannot be echoed back."""
        response = {'disposition': 'unresolved', 'reason': '材料不足', 'replacement': None}
        self.review(dict(response))
        basis = relation_basis(self.q, review_packet(self.q, self.target))
        self.assertEqual([self.tool], [item['event'] for item in basis])
        self.assertEqual(['target'], [item['cited_by'] for item in basis])


if __name__ == '__main__':
    unittest.main()
