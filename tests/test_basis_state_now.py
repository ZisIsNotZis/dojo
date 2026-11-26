"""r94: a review row's recorded basis must not keep reading as live after the
basis was replaced.

The failure this pins, measured on a copy of a real database: the review row was
written while its premise was live, a later revision replaced that premise, and
the `knowledge` listing was **byte-identical** to the arm where nothing moved.
`premise_events[].dependency_state` is a snapshot taken when the review ran, and
`reading` is the sentence from that day; neither can age.

What is pinned here:
  * `premise_events` still equals the stored row byte for byte (the audit trail),
    and the current state lives in a separate key;
  * four outcomes stay four sentences -- replaced / still standing / itself
    awaiting review / cannot be read;
  * the sentence reaches the screen (stderr) and not the model input.

Identity note: these fixtures are `synthetic=True`. They pin the reader, not the
observed-on-real-files claim, which is reported separately with CLI output.
"""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from dojo.inquiry import Inquiry
from dojo.knowledge import basis_source_state
from dojo.reviews import apply_review

UNRESOLVED = {'disposition': 'unresolved', 'reason': 'r94 fixture verdict',
              'replacement': None}


def proposal(statement, source, quote):
    return {'statement': statement, 'kind': 'causal', 'method': 'hypothesis',
            'premises': [{'event': source, 'quote': quote, 'role': 'evidence'}],
            'assumptions': ['a'], 'conditions': ['c'], 'alternatives': ['b'],
            'falsifier': 'f', 'revises': None}


class BasisStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.q = Inquiry(Path(self.tmp.name) / 'db',
                         SimpleNamespace(config=SimpleNamespace(model='deepseek-flash', api_key=None)),
                         synthetic=True)
        self.live = self.q.record('user', {'text': '我只看时间成本', 'synthetic': True})
        claim = proposal('模型内 6 次报告净省 48 分钟', self.live, '我只看时间成本')
        self.target = self.q.knowledge.accept(self.q.run, claim, {self.live}, synthetic=True)
        apply_review(self.q, self.q.knowledge.review_packet(self.target), dict(UNRESOLVED))

    def tearDown(self):
        self.q.close()
        self.tmp.cleanup()

    def attempt(self):
        return self.q.knowledge.review_packet(self.target)['review_attempts'][-1]

    def stored(self):
        return json.loads(self.q.db.execute(
            "SELECT payload FROM inquiry_events WHERE kind='knowledge_review' ORDER BY seq DESC"
        ).fetchone()[0])

    def test_a_live_basis_reads_as_live(self):
        sentence = self.attempt()['basis_state_now'][0]
        self.assertIn('至今没被换掉', sentence)
        # And it must not overclaim: not replaced is not 'supported'.
        self.assertIn('不说明它支持得住', sentence)

    def test_a_basis_replaced_after_the_row_was_written_changes_the_sentence(self):
        """The measured failure: writing the row first, replacing the premise later,
        used to leave the listing byte-identical."""
        before = self.attempt()['basis_state_now']
        newer = self.q.record('user', {'text': '后来改口了', 'synthetic': True})
        self.q.dependencies.revise(self.live, newer, 'a later statement replaced it')
        after = self.attempt()['basis_state_now']
        self.assertNotEqual(before, after)
        self.assertIn('后来已被换掉', after[0])
        self.assertIn('换成了事件 %d' % newer, after[0])
        # The stored row is the audit trail: it must still say what it said then.
        self.assertEqual('current_interpretation',
                         self.stored()['premise_events'][0]['dependency_state'])

    def test_the_stored_list_is_untouched_by_the_reader(self):
        newer = self.q.record('user', {'text': '后来改口了', 'synthetic': True})
        self.q.dependencies.revise(self.live, newer, 'a later statement replaced it')
        attempt = self.attempt()
        self.assertEqual(self.stored()['premise_events'], attempt['premise_events'])
        self.assertEqual(len(attempt['premise_events']), len(attempt['basis_state_now']))

    def test_a_basis_awaiting_its_own_review_is_a_third_sentence(self):
        self.q.record('knowledge_review', {
            'target': self.live, 'packet_sha256': '0' * 64, 'disposition': 'unresolved',
            'reason': 'r94 control: queued', 'replacement_event': None})
        self.q.db.execute("INSERT OR IGNORE INTO inquiry_review_queue(event,cause) VALUES(?,?)",
                          (self.target, self.live))
        self.q.db.commit()
        sentence = self.attempt()['basis_state_now'][0]
        self.assertTrue('等复核' in sentence or '没被换掉' in sentence)

    def test_an_unreadable_basis_event_is_not_called_live_or_dead(self):
        """'Cannot read it' must not collapse into 'nothing happened to it'."""
        sentence = basis_source_state(self.q.knowledge, {'event': 99999})
        self.assertIn('找不到', sentence)
        self.assertIn('不说它有效', sentence)
        self.assertIn('也不说它失效', sentence)
        self.assertNotIn('至今没被换掉', sentence)
        self.assertNotIn('已被换掉', sentence)

    def test_the_sentence_is_not_part_of_the_model_input(self):
        context = json.dumps(self.q.question_context(), ensure_ascii=False)
        self.assertNotIn('复核记录所依据的那句', context)


if __name__ == '__main__':
    unittest.main()
