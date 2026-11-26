"""r95: a review row must not keep reading as a live verdict after the version
it produced has itself been replaced.

Measured on the stored corpus (read-only, realpath-deduped, 172 dbs):
  22 of 146 `knowledge_review` rows name a `replacement_event` that is itself in
  `inquiry_revisions.old_event`; 15 of 104 `question_review` rows do too. The
  listing printed `retain`/`replace` in the present tense and said nothing.

What is pinned here:
  * four situations, four sentences -- replaced / still standing / cannot be
    read here / no outcome was recorded at all. No boolean, and 'cannot read'
    never collapses into 'nothing happened';
  * the sentence is a sibling key beside the stored row, which keeps its bytes;
  * the key does not reach the model input.

Identity note: these fixtures are `synthetic=True`. They pin the reader. The
real-file reading is `.scratch/dojo-grid/r95/probe_beforeafter.py`.
"""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from dojo.inquiry import Inquiry
from dojo.knowledge import outcome_source_state
from dojo.reviews import apply_review

UNRESOLVED = {'disposition': 'unresolved', 'reason': 'r95 fixture verdict',
              'replacement': None}


def proposal(statement, source, quote, revises=None):
    return {'statement': statement, 'kind': 'causal', 'method': 'hypothesis',
            'premises': [{'event': source, 'quote': quote, 'role': 'evidence'}],
            'assumptions': ['a'], 'conditions': ['c'], 'alternatives': ['b'],
            'falsifier': 'f', 'revises': revises}


class OutcomeStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.q = Inquiry(Path(self.tmp.name) / 'db',
                         SimpleNamespace(config=SimpleNamespace(model='deepseek-flash', api_key=None)),
                         synthetic=True)
        self.live = self.q.record('user', {'text': '我只看时间成本', 'synthetic': True})
        self.target = self.q.knowledge.accept(
            self.q.run, proposal('模型内 6 次报告净省 48 分钟', self.live, '我只看时间成本'),
            {self.live}, synthetic=True)
        # A review that produces a version: `replace`. The writer creates the new
        # event and returns its id, so the row's `replacement_event` is that id and
        # not any event this fixture made earlier.
        result = apply_review(self.q, self.q.knowledge.review_packet(self.target), {
            'disposition': 'replace', 'reason': 'r95 fixture',
            'replacement': proposal('模型内 6 次报告净省 41 分钟', self.live, '我只看时间成本',
                                    revises=self.target)})
        self.assertEqual('reviewed', result['status'])
        self.outcome = result['replacement_event']
        self.assertIsNotNone(self.outcome)

    def tearDown(self):
        self.q.close()
        self.tmp.cleanup()

    def attempt(self):
        return self.q.knowledge.review_packet(self.target)['review_attempts'][-1]

    def test_a_standing_outcome_says_so_and_does_not_overclaim(self):
        sentence = self.attempt()['outcome_state_now']
        self.assertIn('至今没被换掉', sentence)
        self.assertIn('事件 %d' % self.outcome, sentence)
        self.assertIn('不说明它判得对', sentence)

    def test_an_outcome_replaced_afterwards_is_named_with_its_successor(self):
        newer = self.q.record('user', {'text': '改口了', 'synthetic': True})
        self.q.dependencies.revise(self.outcome, newer, 'a later statement replaced it')
        sentence = self.attempt()['outcome_state_now']
        self.assertIn('后来也被换掉了', sentence)
        self.assertIn('事件 %d' % self.outcome, sentence)
        self.assertIn('换成了事件 %d' % newer, sentence)
        # 'what the review decided then' stays readable beside it
        self.assertEqual('replace', self.attempt()['disposition'])

    def test_no_outcome_is_not_read_as_still_standing(self):
        second = self.q.knowledge.accept(
            self.q.run, proposal('模型内 6 次报告净省 30 分钟', self.live, '我只看时间成本'),
            {self.live}, synthetic=True)
        result = apply_review(self.q, self.q.knowledge.review_packet(second), dict(UNRESOLVED))
        self.assertIsNone(result['replacement_event'])
        sentence = self.q.knowledge.review_packet(second)['review_attempts'][-1]['outcome_state_now']
        self.assertIn('没有产出新版本', sentence)
        self.assertNotIn('至今没被换掉', sentence)
        self.assertNotIn('后来也被换掉', sentence)

    def test_a_failed_review_has_no_outcome_either_and_says_why(self):
        sentence = outcome_source_state(self.q.knowledge, {'replacement_event': None},
                                        'review_failure')
        self.assertIn('没有完成', sentence)
        self.assertNotIn('至今没被换掉', sentence)

    def test_an_unreadable_outcome_event_is_not_called_live_or_dead(self):
        sentence = outcome_source_state(self.q.knowledge, {'replacement_event': 999999})
        self.assertIn('读不出来', sentence)
        self.assertNotIn('至今没被换掉', sentence)
        self.assertNotIn('后来也被换掉了', sentence)

    def test_the_stored_row_keeps_its_bytes(self):
        stored = json.loads(self.q.db.execute(
            "SELECT payload FROM inquiry_events WHERE kind='knowledge_review' ORDER BY seq DESC"
        ).fetchone()[0])
        self.assertEqual({'target', 'packet_sha256', 'disposition', 'reason',
                          'replacement_event', 'premise_events', 'basis_readings'},
                         set(stored))
        self.assertEqual(stored['replacement_event'], self.outcome)

    def test_the_sentence_is_not_part_of_the_model_input(self):
        context = json.dumps(self.q.question_context(), ensure_ascii=False)
        self.assertNotIn('这次复核产出的那个版本', context)


if __name__ == '__main__':
    unittest.main()
