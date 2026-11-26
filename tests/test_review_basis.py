"""r86: a review row must say what it stood on, without a later join.

Until r86 the time and the citation form lived only in the packet handed to the
reviewer: `knowledge_review`, `review_request_started` and the origin sidecar
carried 0 rows with `at` across 169 recorded databases. Recovering them meant
joining immutable event tables afterwards -- recoverable, not recorded.

The row now carries `premise_events` (each with its own `at`) and
`basis_readings` (one readable line per citation). `citation_kind()` existed
since r84 with no consumer; these are its consumers.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from dojo.anchors import packet_hash
from dojo.inquiry import Inquiry
from dojo.knowledge import citation_kind
from dojo.reviews import apply_review, perform_rechecks, review_basis
from tests.test_knowledge import Client, proposal

UNRESOLVED = {'disposition': 'unresolved', 'reason': 'fixture: inputs unchanged', 'replacement': None}


class Fixture(unittest.TestCase):
    def setUp(self):
        self._env = os.environ.pop('DOJO_REVIEW_RECORD', None)
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.path = Path(self.tmp.name) / 'db'
        q = Inquiry(self.path, Client(), synthetic=True)
        self.q = q
        self.user = q.record('user', {'text': '我只看时间成本，报告只做6次', 'synthetic': True})
        self.tool = q.record('tool_result', {'status': 'executed', 'result': {'net': 48}})
        p = proposal('模型内6次报告净省48分钟', self.tool, '"net": 48')
        p['premises'].append({'event': self.user, 'quote': '我只看时间成本', 'role': 'value'})
        self.target = q.knowledge.accept(q.run, p, {self.tool, self.user}, synthetic=True)
        self.report = q.record('user', {'text': '设置成本其实是100分钟', 'synthetic': True})
        self.fresh = q.record('tool_result', {'status': 'executed', 'result': {'net': -52}})
        q.knowledge.request_review(q.run, self.target, [self.report, self.fresh],
                                   'A changed setup cost', {self.target, self.report, self.fresh},
                                   synthetic=True)

    def tearDown(self):
        self.q.close()
        self.tmp.cleanup()
        os.environ.pop('DOJO_REVIEW_RECORD', None)
        if self._env is not None:
            os.environ['DOJO_REVIEW_RECORD'] = self._env

    def review(self, review=None):
        return apply_review(self.q, self.q.knowledge.review_packet(self.target), review or dict(UNRESOLVED))

    def last_row(self):
        return json.loads(self.q.db.execute(
            "SELECT payload FROM inquiry_events WHERE kind='knowledge_review' ORDER BY seq DESC").fetchone()[0])

    def listing(self):
        """The bytes a reader actually gets from `python -m dojo knowledge`."""
        return json.dumps(self.q.knowledge.proposals(synthetic=True), ensure_ascii=False, indent=2)


class BasisIsRecordedTests(Fixture):
    def test_the_row_carries_each_premise_with_its_own_time(self):
        self.review()
        row = self.last_row()
        self.assertEqual(2, len(row['premise_events']))
        by_event = {item['event']: item for item in row['premise_events']}
        for item in row['premise_events']:
            stored = self.q.db.execute('SELECT at FROM inquiry_events WHERE seq=?', (item['event'],)).fetchone()[0]
            self.assertEqual(stored, item['at'])
        self.assertEqual('"net": 48', by_event[self.tool]['quote'])
        self.assertEqual('我只看时间成本', by_event[self.user]['quote'])
        self.assertEqual(['field', 'prose'], [by_event[self.tool]['citation_kind'],
                                              by_event[self.user]['citation_kind']])

    def test_every_reading_is_a_sentence_and_names_the_time(self):
        self.review()
        row = self.last_row()
        self.assertEqual([x['reading'] for x in row['premise_events']], row['basis_readings'])
        for item in row['premise_events']:
            self.assertIn('「', item['reading'])
            self.assertIn(item['at'], item['reading'])
            # A machine word is not a sentence: the stored kind must not leak in.
            self.assertNotIn('prose', item['reading'])
            self.assertNotIn('field', item['reading'])

    def test_a_replacement_basis_is_recorded_too(self):
        """The review's own new citations are part of what it stood on."""
        self.q.visible_source_text = {}
        replacement = proposal('按纯时间标准，6次自动化不值得做', self.fresh, '"net": -52',
                               revises=self.target)
        replacement['premises'][0]['role'] = 'evidence'
        self.review({'disposition': 'replace', 'reason': 'New cost changes the net',
                     'replacement': replacement})
        row = self.last_row()
        fresh = next(x for x in row['premise_events'] if x['event'] == self.fresh)
        self.assertEqual('replacement', fresh['cited_by'])
        self.assertEqual('field', fresh['citation_kind'])


class ReaderSeesItTests(Fixture):
    def test_the_listing_shows_the_recorded_basis(self):
        self.review()
        attempt = self.q.knowledge.review_packet(self.target)['review_attempts'][0]
        self.assertEqual(self.last_row()['premise_events'], attempt['premise_events'])
        self.assertEqual(self.last_row()['basis_readings'], attempt['basis_readings'])
        self.assertIn('引用了人写的那句原话「我只看时间成本」', self.listing())

    def test_a_row_without_a_basis_says_so_instead_of_staying_silent(self):
        """r89: the `if` had no `else`, so a row without a basis looked exactly
        like a row whose basis was never worth recording -- while still carrying
        `at`, the time the *review* happened, which reads like an answer to
        'when was this based on'. Silence is the failure here, not absence.

        The sentence must state what is in the record and must not imply the
        review was wrong: an older review may have needed no basis at all.
        """
        self.q.record('knowledge_review', {
            'target': self.target,
            'packet_sha256': self.q.knowledge.review_packet(self.target)['sha256'],
            'disposition': 'unresolved', 'reason': 'r85-shaped row', 'replacement_event': None})
        item = self.q.knowledge.review_packet(self.target)['review_attempts'][-1]
        self.assertIn('basis_missing', item)
        self.assertIsInstance(item['basis_missing'], str)
        self.assertIn('没有依据条目', item['basis_missing'])
        # No verdict words, and no boolean: `basis_missing: False` would read as
        # 'the basis is fine' rather than 'this row did not record one'.
        for word in ('无依据', '依据缺失', '未经验证', '错误', '应当'):
            self.assertNotIn(word, item['basis_missing'])
        self.assertEqual([], [k for k, v in item.items() if isinstance(v, bool)])
        self.assertIn('没有依据条目', self.listing())

    def test_a_basis_that_is_present_is_never_reported_as_missing(self):
        """Teeth the other way: the new sentence must not leak onto real bases,
        and an empty list must not pass itself off as a recorded one."""
        self.review()
        item = self.q.knowledge.review_packet(self.target)['review_attempts'][-1]
        self.assertTrue(item['premise_events'])
        self.assertNotIn('basis_missing', item)
        # A row that names a basis list but lists nothing has not recorded a
        # basis, and must not read as though it had (two empty arrays do).
        self.q.record('knowledge_review', {
            'target': self.target,
            'packet_sha256': self.q.knowledge.review_packet(self.target)['sha256'],
            'disposition': 'unresolved', 'reason': 'r89 empty-basis control',
            'replacement_event': None, 'premise_events': [], 'basis_readings': []})
        control = self.q.knowledge.review_packet(self.target)['review_attempts'][-1]
        self.assertIn('basis_missing', control)
        self.assertNotIn('premise_events', control)
        self.assertNotIn('basis_readings', control)

    def test_prose_and_field_are_told_apart_in_the_visible_sentence(self):
        """The distinction has to survive to a reader who does not know our keys."""
        self.review()
        listing = self.listing()
        # The sentence a reader gets, not the raw quote echoed in the proposal:
        # the proposal block has no `reading` word in it.
        sentence = next(x for x in listing.splitlines()
                        if '我只看时间成本' in x and '记录于' in x)
        field_sentence = next(x for x in listing.splitlines()
                              if 'net' in x and '记录于' in x)
        self.assertIn('原话', sentence)
        self.assertIn('存在的字段', field_sentence)
        self.assertNotEqual(citation_kind('我只看时间成本'), citation_kind('"net": 48'))


class NegativeControls(Fixture):
    def test_erasing_the_new_fields_changes_what_a_reader_sees(self):
        """Teeth: flipping the recorder to legacy must move the visible bytes.

        A control that only deletes a constant would pass on any build. This one
        runs the same review twice through the real consumer and compares the
        listing a user reads.
        """
        self.review()
        full = self.listing()
        self.assertIn('basis_readings', full)
        self.q.close()
        legacy_path = Path(self.tmp.name) / 'legacy'
        os.environ['DOJO_REVIEW_RECORD'] = 'legacy'
        try:
            q = Inquiry(legacy_path, Client(), synthetic=True)
            user = q.record('user', {'text': '我只看时间成本，报告只做6次', 'synthetic': True})
            tool = q.record('tool_result', {'status': 'executed', 'result': {'net': 48}})
            p = proposal('模型内6次报告净省48分钟', tool, '"net": 48')
            p['premises'].append({'event': user, 'quote': '我只看时间成本', 'role': 'value'})
            target = q.knowledge.accept(q.run, p, {tool, user}, synthetic=True)
            report = q.record('user', {'text': '设置成本其实是100分钟', 'synthetic': True})
            fresh = q.record('tool_result', {'status': 'executed', 'result': {'net': -52}})
            q.knowledge.request_review(q.run, target, [report, fresh], 'A changed setup cost',
                                       {target, report, fresh}, synthetic=True)
            apply_review(q, q.knowledge.review_packet(target), dict(UNRESOLVED))
            legacy = json.dumps(q.knowledge.proposals(synthetic=True), ensure_ascii=False, indent=2)
            row = json.loads(q.db.execute(
                "SELECT payload FROM inquiry_events WHERE kind='knowledge_review'").fetchone()[0])
            self.assertEqual({'target', 'packet_sha256', 'disposition', 'reason', 'replacement_event'},
                             set(row))
        finally:
            q.close()
            os.environ.pop('DOJO_REVIEW_RECORD', None)
        self.assertNotIn('basis_readings', legacy)
        self.assertNotIn('我只看时间成本」，记录于', legacy)
        self.assertNotEqual(full, legacy)

    def test_a_model_proposal_is_never_labelled_as_a_person_s_words(self):
        """The label must follow the source kind.

        First version said 'quoted the words they wrote' for every prose quote,
        so a review whose basis was a model's own proposal read back as if a
        person had said it. Caught on a real row, not in review.
        """
        inner = self.q.knowledge.accept(
            self.q.run, proposal('模型内6次报告净省48分钟', self.tool, '"net": 48'),
            {self.tool}, synthetic=True)
        later = self.q.record('user', {'text': '后来说成本是100分钟', 'synthetic': True})
        self.q.knowledge.request_review(self.q.run, inner, [later], 'newer report',
                                        {inner, later}, synthetic=True)
        outer = self.q.knowledge.accept(
            self.q.run, proposal('按纯时间标准，6次值得做', inner, '模型内6次报告净省48分钟'),
            {inner}, synthetic=True)
        item = next(x for x in review_basis(self.q, self.q.knowledge.review_packet(outer))
                    if x['event'] == inner)
        self.assertEqual('knowledge_proposal', item['kind'])
        self.assertNotIn('人写的', item['reading'])
        self.assertIn('模型提议', item['reading'])

    def test_a_pending_source_is_named_pending_and_gets_nothing_invented(self):
        """Negative control in the opposite direction: no anchor, no made-up time."""
        self.review()
        reopened = self.q.knowledge.accept(
            self.q.run, proposal('旧解释仍待复核', self.user, '我只看时间成本'),
            {self.user}, synthetic=True)
        later = self.q.record('user', {'text': '后来又说成本是120分钟', 'synthetic': True})
        self.q.knowledge.request_review(self.q.run, reopened, [later], 'newer report',
                                        {reopened, later}, synthetic=True)
        outer = self.q.knowledge.accept(
            self.q.run, proposal('外层结论引用一个待复核解释', reopened, '旧解释仍待复核'),
            {reopened}, synthetic=True)
        packet = self.q.knowledge.review_packet(outer)
        basis = review_basis(self.q, packet)
        item = next(x for x in basis if x['event'] == reopened)
        self.assertEqual('needs_review', item['dependency_state'])
        self.assertIn('这条依据本身仍未复核', item['reading'])
        self.assertNotIn('anchor', item)
        stored = self.q.db.execute('SELECT at FROM inquiry_events WHERE seq=?', (reopened,)).fetchone()[0]
        self.assertEqual(stored, item['at'])


class ShapeStaysTests(Fixture):
    def test_the_new_keys_do_not_move_the_packet_digest(self):
        """146 recorded reviews must stay recorded: the digest is content, not history."""
        before = self.q.knowledge.review_packet(self.target)
        self.review()
        after = self.q.knowledge.review_packet(self.target)
        self.assertEqual(before['sha256'], after['sha256'])
        self.assertEqual(packet_hash(after), after['sha256'])
        stripped = {k: v for k, v in after.items() if k not in {'sha256', 'review_attempts'}}
        self.assertEqual(packet_hash(stripped), after['sha256'])

    def test_a_legacy_row_is_still_read_by_the_new_reader(self):
        self.q.record('knowledge_review', {
            'target': self.target,
            'packet_sha256': self.q.knowledge.review_packet(self.target)['sha256'],
            'disposition': 'unresolved', 'reason': 'r85-shaped row', 'replacement_event': None})
        attempt = self.q.knowledge.review_packet(self.target)['review_attempts'][-1]
        self.assertEqual('unresolved', attempt['disposition'])
        self.assertNotIn('premise_events', attempt)
        self.assertNotIn('basis_readings', attempt)
        # An r85 row has no reason copy on the attempt item, and still lists.
        self.assertIn('review_attempts', self.listing())
        self.assertNotIn('basis_readings', self.listing())


class DigestDriftTests(unittest.TestCase):
    """A stored digest that no longer matches must not mean 'never reviewed'.

    r86 measured the consequence on real data: `review_attempts` showed 0 of the
    146 recorded reviews, because every stored digest was computed under an older
    rule. Rebuilding the packet as of each review proved the *material* had not
    changed -- the rule had -- so the packet was offered again with no trace of
    the review. These tests pin the reader that replaces that silence.
    """

    def setUp(self):
        self._env = os.environ.pop('DOJO_REVIEW_RECORD', None)
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.q = Inquiry(Path(self.tmp.name) / 'db', Client(), synthetic=True)
        self.user = self.q.record('user', {'text': '我只看时间成本，报告只做6次', 'synthetic': True})
        self.tool = self.q.record('tool_result', {'status': 'executed', 'result': {'net': 48}})
        p = proposal('模型内6次报告净省48分钟', self.tool, '"net": 48')
        p['premises'].append({'event': self.user, 'quote': '我只看时间成本', 'role': 'value'})
        self.target = self.q.knowledge.accept(self.q.run, p, {self.tool, self.user}, synthetic=True)
        self.report = self.q.record('user', {'text': '设置成本其实是100分钟', 'synthetic': True})
        self.q.knowledge.request_review(self.q.run, self.target, [self.report], 'changed cost',
                                        {self.target, self.report}, synthetic=True)

    def tearDown(self):
        self.q.close()
        self.tmp.cleanup()
        os.environ.pop('DOJO_REVIEW_RECORD', None)

    def attempt(self, digest):
        self.q.record('knowledge_review', {'target': self.target, 'packet_sha256': digest,
                                           'disposition': 'unresolved', 'reason': 'fixture',
                                           'replacement_event': None})

    def offered(self):
        return [p['target'] for p in self.q.knowledge.review_candidates(synthetic=True, limit=10)]

    def test_a_drifted_digest_still_suppresses_the_packet_and_says_why(self):
        """The defect: offered again, with no attempt shown."""
        self.attempt('d' * 64)
        self.assertEqual([], self.offered())
        items = self.q.knowledge.review_packet(self.target)['review_attempts']
        self.assertEqual(1, len(items))
        self.assertEqual('written_under_another_rule', items[0]['digest'])
        self.assertEqual('no', items[0]['reopened_since'])
        # A reader must be able to tell this apart from 'never reviewed'.
        self.assertIn('摘要不同不等于没复核过', items[0]['reading'])
        self.assertIn('不会再提出来', items[0]['reading'])

    def test_a_matching_digest_reads_unchanged(self):
        exact = self.q.knowledge.review_packet(self.target)['sha256']
        self.attempt(exact)
        self.assertEqual([], self.offered())
        item = self.q.knowledge.review_packet(self.target)['review_attempts'][0]
        self.assertEqual('same_as_today', item['digest'])
        self.assertNotIn('reading', item)

    def test_newer_review_work_after_a_drifted_attempt_is_offered_with_the_attempt_shown(self):
        """The other direction: real new work must not be suppressed by a stale row."""
        self.attempt('d' * 64)
        newer = self.q.record('user', {'text': '净省其实只有12分钟', 'synthetic': True})
        self.q.knowledge.request_review(self.q.run, self.target, [newer], 'newer measurement',
                                        {self.target, newer}, synthetic=True)
        self.assertEqual([self.target], self.offered())
        item = self.q.knowledge.review_packet(self.target)['review_attempts'][0]
        self.assertEqual('yes', item['reopened_since'])
        self.assertIn('会被再提出来一次', item['reading'])

    def test_the_attempt_item_does_not_claim_the_material_changed(self):
        """Two broader signals fired on 109/115 real rows where a rebuild showed the
        packet was byte-identical. The shipped reading must therefore say only what
        is known: that newer work exists, never that the content moved."""
        self.attempt('d' * 64)
        newer = self.q.record('user', {'text': '净省其实只有12分钟', 'synthetic': True})
        self.q.knowledge.request_review(self.q.run, self.target, [newer], 'newer measurement',
                                        {self.target, newer}, synthetic=True)
        reading = self.q.knowledge.review_packet(self.target)['review_attempts'][0]['reading']
        # No sentence may assert a change. The negation is the only place the word
        # may appear, so the clause itself is the assertion.
        for claim in ('内容已经变了', '材料已经变了', '内容变了，', '所以它的内容'):
            self.assertNotIn(claim, reading)
        self.assertIn('也不说明材料变了', reading)
        self.assertIn('又有了新的复核工作', reading)

    def test_the_old_reader_shape_is_what_a_caller_compared(self):
        """`packet_sha256` on the item still means 'the digest stored on that row'."""
        self.attempt('d' * 64)
        item = self.q.knowledge.review_packet(self.target)['review_attempts'][0]
        self.assertEqual('d' * 64, item['packet_sha256'])


class RequestRowTimeTests(unittest.TestCase):
    """153 `review_request_started` rows carried no `at`; the column was the only copy."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.q = Inquiry(Path(self.tmp.name) / 'db', Client(), synthetic=True)

    def tearDown(self):
        self.q.close()
        self.tmp.cleanup()

    def test_the_request_row_carries_the_same_time_in_payload_and_column(self):
        q = self.q
        user = q.record('user', {'text': '我只看时间成本', 'synthetic': True})
        tool = q.record('tool_result', {'status': 'executed', 'result': {'net': 48}})
        target = q.knowledge.accept(q.run, proposal('模型内6次报告净省48分钟', tool, '"net": 48'),
                                    {tool}, synthetic=True)
        report = q.record('user', {'text': '成本其实是100分钟', 'synthetic': True})
        q.knowledge.request_review(q.run, target, [report], 'changed', {target, report}, synthetic=True)
        perform_rechecks(q, SimpleNamespace(complete=lambda messages: UNRESOLVED), max_requests=1)
        payload, column = q.db.execute(
            "SELECT payload,at FROM inquiry_events WHERE kind='review_request_started' ORDER BY seq DESC").fetchone()
        data = json.loads(payload)
        self.assertIn('at', data)
        self.assertEqual(column, data['at'])
        self.assertGreater(len(data['at']), 10)

    def test_a_row_written_before_the_change_is_still_readable(self):
        q = self.q
        q.record('review_request_started', {'target': 1, 'packet_sha256': 'x', 'remaining': 1})
        payload = q.db.execute(
            "SELECT payload FROM inquiry_events WHERE kind='review_request_started'").fetchone()[0]
        self.assertNotIn('at', json.loads(payload))


if __name__ == '__main__':
    unittest.main()
