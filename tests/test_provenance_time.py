import json
import tempfile
import unittest
from pathlib import Path

from dojo.experiments import parameter_sweep
from dojo.falsifier import compile_check, receipt_hits
from dojo.inquiry import Inquiry

PROSE = '若在同一模型下找不到 badfmt=1 且 P1=1 的样例，则本条被反驳。'
PARAMS = {'q': [0, 1], 'badfmt': [0, 1], 'stub': [0, 1]}
DERIVED = {'P1': 'stub*(1-q)*(badfmt>0)'}
# stub=0 makes P1=0, so P1==1 is false there: a real failure point.
CHECK = {'parameters': PARAMS, 'derived': DERIVED, 'predicate': 'P1==1',
         'predicate_fails_at': {'q': 1, 'badfmt': 0, 'stub': 0}}


class Client:
    class config:
        model = 'offline'
        api_key = None

    def complete(self, messages):
        raise AssertionError('no model call expected')


class ProvenanceTimeTests(unittest.TestCase):
    """A downgrade whose grounds cannot be dated or located is not reviewable.

    These came out of a real chain over docs/evidence/2026-11-13-knowledge-
    transfer/maintenance/inquiry.sqlite3, where both gaps were invisible until
    an actual receipt and an actual proposal were wired together.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.q = Inquiry(Path(self.tmp.name) / 'db', Client(), synthetic=True)
        self.u = self.q.record('user', {'text': '没人再问我了', 'synthetic': True})

    def tearDown(self):
        self.q.close()
        self.tmp.cleanup()

    def accept(self, check):
        import hashlib
        proof = dict(check)
        proof['falsifier_sha256'] = hashlib.sha256(PROSE.encode('utf-8')).hexdigest()
        p = {'statement': '缺 badfmt 时换桩成功不足以排除格式故障。', 'kind': 'decision', 'method': 'deduction',
             'premises': [{'event': self.u, 'quote': '没人再问我了', 'role': 'assumption'}],
             'assumptions': ['布尔取 0/1'], 'conditions': ['仅此参数网格'], 'alternatives': ['直接采真实响应'],
             'falsifier': PROSE, 'revises': None, 'falsifier_check': proof}
        return self.q.knowledge.accept(self.q.run, p, {self.u}, synthetic=True)

    # The receipt must assert something the candidate's predicate can contradict.
    # Asserting exactly `P1==1` would mean every point where the predicate holds
    # is a point where the receipt's assertion held too -- the r48 DISJOINT shape,
    # which is not a hit. These tests are about dating the hit, not about hit
    # semantics, so the receipt asserts the opposite and really does fail where
    # the candidate predicate holds (2 of 8 points).
    RECEIPT_ASSERTION = 'P1==0'

    def receipt(self):
        return self.q.record('tool_result', {'action': {'kind': 'experiment', 'derived': DERIVED,
                                                       'assertion': self.RECEIPT_ASSERTION, 'prediction': 'p'},
                                            'status': 'executed',
                                            'result': parameter_sweep(PARAMS, DERIVED, self.RECEIPT_ASSERTION)})

    def test_receipt_time_reaches_the_hit_and_the_reviewer(self):
        claim = self.accept(CHECK)
        event = self.receipt()
        receipt_at = self.q.db.execute('SELECT at FROM inquiry_events WHERE seq=?', (event,)).fetchone()[0]
        outcome = receipt_hits(self.q.knowledge, self.q.run, event, synthetic=True)
        self.assertEqual(receipt_at, outcome['receipt_at'])
        hit = [o for o in outcome['outcomes'] if o['proposal'] == claim][0]
        self.assertEqual('needs_review', hit['status'])
        self.assertEqual(receipt_at, hit['receipt_at'])
        stored = json.loads(self.q.db.execute(
            'SELECT payload FROM inquiry_events WHERE seq=?', (hit['hit_event'],)).fetchone()[0])
        self.assertEqual(receipt_at, stored['receipt_at'])
        # The reviewer's own view, not just the storage column.
        self.assertEqual(receipt_at, self.q.knowledge.source(event)['at'])
        # The cause a reviewer is shown is the hit event; it now carries both its
        # own write time and the time of the receipt it rests on.
        causes = self.q.knowledge.source(claim)['review_context']['causes']
        cause = next(c for c in causes if c['event'] == hit['hit_event'])
        self.assertTrue(cause['at'])
        self.assertIn(receipt_at, cause['excerpt'])

    def test_review_packet_sources_carry_time(self):
        claim = self.accept(CHECK)
        event = self.receipt()
        receipt_hits(self.q.knowledge, self.q.run, event, synthetic=True)
        packet = self.q.knowledge.review_packet(claim)
        self.assertTrue(packet['sources'])
        for source in packet['sources']:
            stored = self.q.db.execute('SELECT at FROM inquiry_events WHERE seq=?', (source['event'],)).fetchone()[0]
            self.assertEqual(stored, source['at'])

    def test_scan_scope_is_reported_so_an_empty_result_is_not_misread(self):
        """Real evidence DBs put the citing proposal in a different run than the
        receipt. The scan then sees nothing, and that must be distinguishable
        from 'no proposal was hit'."""
        self.accept(CHECK)
        other = Inquiry(Path(self.tmp.name) / 'db', Client(), synthetic=True)
        try:
            receipt = other.record('tool_result', {
                'action': {'kind': 'experiment', 'derived': DERIVED,
                           'assertion': self.RECEIPT_ASSERTION, 'prediction': 'p'},
                'status': 'executed',
                'result': parameter_sweep(PARAMS, DERIVED, self.RECEIPT_ASSERTION)})
            outcome = receipt_hits(self.q.knowledge, other.run, receipt, synthetic=True)
            self.assertEqual('checked', outcome['status'])
            self.assertEqual([], outcome['outcomes'])
            self.assertEqual(0, outcome['proposals_scanned'])
            self.assertEqual(1, self.q.db.execute(
                "SELECT count(*) FROM inquiry_events WHERE kind='knowledge_proposal'").fetchone()[0])
        finally:
            other.close()

    def test_packet_digest_ignores_timestamps_so_old_attempts_stay_suppressed(self):
        """The digest must identify reviewed content, not write time.

        It used to hash the whole packet, so adding `at` to sources changed every
        digest and silently un-suppressed proposals a reviewer had already
        examined. Measured on disk: of 151 stored attempts, matches went 3 -> 0.
        """
        claim = self.accept(CHECK)
        event = self.receipt()
        receipt_hits(self.q.knowledge, self.q.run, event, synthetic=True)
        packet = self.q.knowledge.review_packet(claim)
        self.assertTrue(packet['sources'])
        self.assertTrue(all('at' in s for s in packet['sources']))
        import hashlib
        from dojo.anchors import strip_times, packet_hash
        # The digest is taken before the `sha256` key is added, so recompute over
        # the packet minus that key. A pre-change packet is the same packet with
        # no timestamps anywhere: both must give today's digest, or every stored
        # attempt goes stale and already-reviewed proposals return to the queue.
        body = {k: v for k, v in strip_times(packet).items() if k != 'sha256'}
        recomputed = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True)
                                    .encode('utf-8')).hexdigest()
        self.assertEqual(recomputed, packet['sha256'])
        self.assertEqual(packet_hash(packet), packet['sha256'])
        self.assertNotIn('"at"', json.dumps(body))

    def test_bridge_reads_formulas_from_action_not_result(self):
        """Real receipts store derived in action.derived; the result never has it.
        If the bridge ever read result, every real receipt would be refused."""
        claim = self.accept(CHECK)
        event = self.receipt()
        payload = json.loads(self.q.db.execute(
            'SELECT payload FROM inquiry_events WHERE seq=?', (event,)).fetchone()[0])
        self.assertNotIn('derived', payload['result'])
        self.assertEqual(DERIVED, payload['action']['derived'])
        outcome = receipt_hits(self.q.knowledge, self.q.run, event, synthetic=True)
        hit = [o for o in outcome['outcomes'] if o['proposal'] == claim][0]
        self.assertEqual('needs_review', hit['status'])


if __name__ == '__main__':
    unittest.main()
