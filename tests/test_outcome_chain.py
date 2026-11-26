"""r96: the sentence about a review's produced version must follow the chain.

r95 made the reader say 'the version this review produced was itself replaced,
by event X'. Measured on the stored corpus (172 dbs, read-only): the chain after
X can continue. Exactly one row does -- `2026-11-13-intent-focus/live/baseline`,
review 171 -> 170 -> 294 -> 523 -- so the r95 sentence named 294 as if that were
the end while 294 had already been replaced by 523.

What is pinned here:
  * a chain of length 1 keeps the r95 sentence, word for word (no regression);
  * a longer chain names the tail and how many further hops happened;
  * a chain whose middle cannot be read says so, and never says the chain ended;
  * a library whose revisions loop says so, and never names a tail;
  * the stored row keeps its bytes and the sentence stays out of model input.

Identity note: fixtures are `synthetic=True`. They pin the reader. The real-file
evidence is `.scratch/dojo-grid/r96/probe_beforeafter.py` (real CLI arms + two
negative controls on declared copies).
"""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from dojo.inquiry import Inquiry
from dojo.knowledge import outcome_chain_tail
from dojo.reviews import apply_review


def proposal(statement, source, quote, revises=None):
    return {'statement': statement, 'kind': 'causal', 'method': 'hypothesis',
            'premises': [{'event': source, 'quote': quote, 'role': 'evidence'}],
            'assumptions': ['a'], 'conditions': ['c'], 'alternatives': ['b'],
            'falsifier': 'f', 'revises': revises}


class ChainTailTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.q = Inquiry(Path(self.tmp.name) / 'db',
                         SimpleNamespace(config=SimpleNamespace(model='deepseek-flash', api_key=None)),
                         synthetic=True)
        self.live = self.q.record('user', {'text': '我只看时间成本', 'synthetic': True})
        self.target = self.q.knowledge.accept(
            self.q.run, proposal('模型内 6 次报告净省 48 分钟', self.live, '我只看时间成本'),
            {self.live}, synthetic=True)
        result = apply_review(self.q, self.q.knowledge.review_packet(self.target), {
            'disposition': 'replace', 'reason': 'r96 fixture',
            'replacement': proposal('模型内 6 次报告净省 41 分钟', self.live, '我只看时间成本',
                                    revises=self.target)})
        self.assertEqual('reviewed', result['status'])
        self.outcome = result['replacement_event']

    def tearDown(self):
        self.q.close()
        self.tmp.cleanup()

    def sentence(self):
        return self.q.knowledge.review_packet(self.target)['review_attempts'][-1]['outcome_state_now']

    def chain(self, n):
        """Append `n` further replacements on top of the review's own outcome."""
        events = [self.outcome]
        for i in range(n):
            newer = self.q.record('user', {'text': '再改口 %d' % i, 'synthetic': True})
            self.q.dependencies.revise(events[-1], newer, 'r96 fixture hop %d' % i)
            events.append(newer)
        return events

    def follow(self, event):
        """(tail, hops) read straight from the ledger, independent of the helper."""
        hops, tail = 0, event
        while True:
            row = self.q.db.execute(
                'SELECT new_event FROM inquiry_revisions WHERE old_event=?', (tail,)).fetchone()
            if row is None:
                return tail, hops
            tail, hops = row[0], hops + 1

    def test_one_hop_keeps_the_r95_sentence_unchanged(self):
        events = self.chain(1)
        sentence = self.sentence()
        self.assertEqual(
            '这次复核产出的那个版本（事件 %d）后来也被换掉了，换成了事件 %d：'
            '这次复核的结论已不是当前版本，行里留着的仍是它当时说的。'
            % (self.outcome, events[1]), sentence)
        self.assertNotIn('链尾', sentence)

    def test_a_longer_chain_names_the_tail_and_the_hops(self):
        self.chain(2)
        successor = self.q.db.execute(
            'SELECT new_event FROM inquiry_revisions WHERE old_event=?', (self.outcome,)
        ).fetchone()[0]
        tail, hops = self.follow(successor)
        self.assertGreaterEqual(hops, 1, 'fixture must leave the successor itself replaced')
        sentence = self.sentence()
        self.assertIn('换成了事件 %d' % successor, sentence)
        self.assertIn('此后又被换掉 %d 次' % hops, sentence)
        self.assertIn('现在的链尾是事件 %d' % tail, sentence)
        # the intermediate is not presented as the current version
        self.assertNotIn('换成了事件 %d：' % successor, sentence)

    def test_the_tail_helper_reports_how_the_walk_ended(self):
        events = self.chain(2)
        for event in events:
            self.assertEqual(self.follow(event) + ('live',),
                             outcome_chain_tail(self.q.knowledge, event))
        self.assertEqual((None, None, 'unreadable'),
                         outcome_chain_tail(self.q.knowledge, 999999))

    def test_a_mid_chain_event_that_cannot_be_read_is_not_called_the_end(self):
        events = self.chain(2)
        successor = self.q.db.execute(
            'SELECT new_event FROM inquiry_revisions WHERE old_event=?', (self.outcome,)
        ).fetchone()[0]
        with self.q.db:
            self.q.db.execute('DELETE FROM inquiry_events WHERE seq=?', (successor,))
        sentence = self.sentence()
        self.assertIn('而事件 %d 在本库里读不出来' % successor, sentence)
        self.assertNotIn('链尾', sentence)
        self.assertNotIn('至今没被换掉', sentence)

    def test_a_revision_loop_is_named_as_a_loop_not_as_a_tail(self):
        events = self.chain(2)
        with self.q.db:
            self.q.db.execute('INSERT INTO inquiry_revisions VALUES(?,?,?)',
                              (events[-1], self.outcome, 'r96 fixture loop'))
        sentence = self.sentence()
        self.assertIn('成了环', sentence)
        self.assertIn('说不出哪个是现在的版本', sentence)
        self.assertNotIn('链尾', sentence)

    def test_the_stored_row_is_unchanged_by_the_new_branch(self):
        self.chain(2)
        stored = json.loads(self.q.db.execute(
            "SELECT payload FROM inquiry_events WHERE kind='knowledge_review' ORDER BY seq DESC"
        ).fetchone()[0])
        self.assertEqual(self.outcome, stored['replacement_event'])
        self.assertNotIn('outcome_state_now', stored)

    def test_the_sentence_stays_out_of_model_input(self):
        self.chain(2)
        context = json.dumps(self.q.question_context(), ensure_ascii=False)
        self.assertNotIn('链尾', context)
        self.assertNotIn('成了环', context)


if __name__ == '__main__':
    unittest.main()
