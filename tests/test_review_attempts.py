"""A reviewer gets a packet, not the event log.

Two gaps are pinned here, both of the same shape: work was recorded and the
reader could not see it.

1. `review_failure` / `knowledge_review` rows suppress a packet from ever being
   offered again (`knowledge.py`, retry exclusion). Without a key on the packet,
   a parked proposal reads exactly like one that was never examined (r61).
2. A `falsifier_hit` names the proposal id that was scored. A review that
   replaces it creates a new id that is never scored in that run, so the new
   packet showed no bridge at all (r58 A).
"""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from dojo.falsifier import receipt_hits
from dojo.inquiry import Inquiry
from tests.test_knowledge import Client

PROSE = '若第二人每天要复核的件数超过其容量，则流量并未真正转移。'
PARAMS = {'N': [20, 50], 'u': [5, 60], 'C': [2, 40]}
DERIVED = {'to_second': 'N*u/100'}
CHECK = {'falsifier_sha256': hashlib.sha256(PROSE.encode('utf-8')).hexdigest(),
         'parameters': PARAMS, 'derived': DERIVED, 'predicate': 'to_second>C',
         'predicate_fails_at': {'N': 20, 'u': 5, 'C': 40}}
LEGACY = {'target', 'proposal', 'dependency_status', 'sources', 'source_expansion_truncated',
          'truth', 'citation_contract', 'anchors', 'sha256'}


def proposal(prose, check):
    p = {'statement': '未归类比例把第二个人变成瓶颈时，流量没有真正转移。', 'kind': 'causal',
         'method': 'hypothesis', 'premises': [], 'assumptions': ['容量固定'],
         'conditions': ['仅此参数网格'], 'alternatives': ['保留兵底'], 'falsifier': prose,
         'revises': None}
    if check is not None:
        p['falsifier_check'] = check
    return p


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.q = Inquiry(Path(self.tmp.name) / 'db', Client(), synthetic=True)
        self.u = self.q.record('user', {'text': '没人再问我了', 'synthetic': True})

    def tearDown(self):
        self.q.close()
        self.tmp.cleanup()

    def accept(self, check, prose=PROSE):
        p = proposal(prose, check)
        p['premises'] = [{'event': self.u, 'quote': '没人再问我了', 'role': 'assumption'}]
        return self.q.knowledge.accept(self.q.run, p, {self.u}, synthetic=True)

    def receipt(self, parameters, assertion, derived=DERIVED):
        return self.q.record('tool_result', {
            'action': {'kind': 'experiment', 'derived': derived, 'prediction': 'p'},
            'status': 'executed',
            'result': __import__('dojo.experiments', fromlist=['x']).parameter_sweep(
                parameters, derived, assertion)})

    def revision_terms(self, statement, premises, falsifier, revises):
        return {'statement': statement, 'kind': 'causal', 'method': 'hypothesis',
                'premises': premises, 'assumptions': ['容量固定'], 'conditions': ['仅此参数网格'],
                'alternatives': ['保留兵底'], 'falsifier': falsifier, 'revises': revises}

    def revise(self, claim, receipt_event):
        self.q.visible_source_text[claim] = self.q.knowledge.source(claim)['text']
        self.q.visible_source_text[receipt_event] = self.q.knowledge.source(receipt_event)['text']
        return self.q.knowledge.accept(self.q.run, self.revision_terms(
            '流量转移只在人手不足时受阻；容量充足时仍可转移。',
            [{'event': receipt_event, 'quote': 'counterexample_count', 'role': 'evidence'}],
            '若容量充足时也无法转移，则本条不成立。', claim), self.q.visible_source_text,
            synthetic=True)


class AttemptVisibilityTests(Fixture):
    def failing_attempt(self, claim, kind='review_schema', sha=None):
        sha = sha or self.q.knowledge.review_packet(claim)['sha256']
        return self.q.record('review_failure',
                             {'target': claim, 'packet_sha256': sha, 'kind': kind})

    def test_a_failed_attempt_is_visible_on_the_packet(self):
        claim = self.accept(CHECK)
        self.assertNotIn('review_attempts', self.q.knowledge.review_packet(claim))
        self.failing_attempt(claim)
        packet = self.q.knowledge.review_packet(claim)
        self.assertIn('review_attempts', packet)
        self.assertEqual(1, len(packet['review_attempts']))
        item = packet['review_attempts'][0]
        self.assertEqual('review_failure', item['kind'])
        self.assertEqual('review_schema', item['failure'])
        self.assertEqual(packet['sha256'], item['packet_sha256'])
        self.assertIsInstance(item['at'], str)
        self.assertTrue(item['at'])

    def test_a_review_disposition_is_visible_too(self):
        claim = self.accept(CHECK)
        self.q.record('knowledge_review', {
            'target': claim,
            'packet_sha256': self.q.knowledge.review_packet(claim)['sha256'],
            'disposition': 'unresolved', 'reason': 'r63 fixture', 'replacement_event': None})
        item = self.q.knowledge.review_packet(claim)['review_attempts'][0]
        self.assertEqual('knowledge_review', item['kind'])
        self.assertEqual('unresolved', item['disposition'])
        self.assertNotIn('failure', item)

    def test_the_attempt_record_carries_no_verdict_boolean(self):
        claim = self.accept(CHECK)
        self.failing_attempt(claim)
        item = self.q.knowledge.review_packet(claim)['review_attempts'][0]
        self.assertEqual([], [k for k, v in item.items() if isinstance(v, bool)])
        self.assertFalse([k for k in item if k in {
            'passed', 'verified', 'holds', 'satisfied', 'ok', 'survived', 'confirmed',
            'rejected', 'failed'}])

    def test_the_attempt_record_does_not_move_state(self):
        claim = self.accept(CHECK)
        self.failing_attempt(claim)
        self.assertEqual('current_interpretation', self.q.dependencies.status(claim)['state'])

    def test_the_attempt_record_is_digest_neutral(self):
        """Including it in the digest would change the very sha the retry
        exclusion compares against, so a parked proposal would be offered again
        on every scan (measured on a real db: 9b7761bf14efe6f0 -> f5596684479399bb)."""
        from dojo.anchors import packet_hash
        claim = self.accept(CHECK)
        bare = self.q.knowledge.review_packet(claim)['sha256']
        self.failing_attempt(claim)
        packet = self.q.knowledge.review_packet(claim)
        self.assertIn('review_attempts', packet)
        self.assertEqual(bare, packet['sha256'])
        self.assertEqual(packet_hash(packet), packet['sha256'])
        stripped = {k: v for k, v in packet.items() if k not in {'sha256', 'review_attempts'}}
        self.assertEqual(packet_hash(stripped), packet['sha256'])

    def test_an_attempt_does_not_reopen_its_own_packet(self):
        """Digest neutrality has a consequence that must hold: the packet being
        compared is the one already attempted, so it stays parked."""
        claim = self.accept(CHECK)
        event = self.receipt(PARAMS, 'to_second<=C')
        receipt_hits(self.q.knowledge, self.q.run, event, synthetic=True)
        packet = self.q.knowledge.review_packet(claim)
        self.failing_attempt(claim, sha=packet['sha256'])
        offered = self.q.knowledge.review_candidates(synthetic=True, limit=50)
        self.assertNotIn(claim, [p['target'] for p in offered])

    def test_an_attempt_under_another_digest_is_shown_and_says_which(self):
        """r87 reversed this on purpose; the old reason is kept here because it is
        the part that was wrong.

        This test used to assert the attempt was *hidden*, on the reasoning that an
        attempt with another digest is an attempt on other content. Real data says
        otherwise: all 146 recorded reviews store a digest that no longer matches,
        and rebuilding each packet as of its review shows the material had not
        changed -- the digest rule had. Hiding those rows made 'reviewed under an
        older rule' read as 'never reviewed'. So the row is shown, and the item says
        which digest it was written under instead of silently dropping it.
        """
        claim = self.accept(CHECK)
        self.failing_attempt(claim, sha='0' * 64)
        item = self.q.knowledge.review_packet(claim)['review_attempts'][0]
        self.assertEqual('written_under_another_rule', item['digest'])
        self.assertEqual('0' * 64, item['packet_sha256'])
        # It still explains the exclusion, because nothing was written since.
        self.assertNotIn(claim, [p['target'] for p in
                                 self.q.knowledge.review_candidates(synthetic=True, limit=50)])

    def test_a_proposal_without_attempts_keeps_the_legacy_shape(self):
        claim = self.accept(CHECK)
        self.assertEqual(LEGACY, set(self.q.knowledge.review_packet(claim)))


class InheritedBridgeTests(Fixture):
    def test_a_revision_shows_where_the_readings_came_from(self):
        claim = self.accept(CHECK)
        event = self.receipt(PARAMS, 'to_second<=C')
        receipt_hits(self.q.knowledge, self.q.run, event, synthetic=True)
        revised = self.revise(claim, event)
        packet = self.q.knowledge.review_packet(revised)
        self.assertIn('bridge', packet)
        self.assertEqual(claim, packet['bridge']['inherited_from'])
        self.assertEqual(event, packet['bridge']['receipt'])

    def test_the_inherited_view_does_not_move_state_or_manufacture_a_hit(self):
        claim = self.accept(CHECK)
        event = self.receipt(PARAMS, 'to_second<=C')
        receipt_hits(self.q.knowledge, self.q.run, event, synthetic=True)
        revised = self.revise(claim, event)
        self.assertEqual('current_interpretation', self.q.dependencies.status(revised)['state'])
        hits = [json.loads(r[0]) for r in self.q.db.execute(
            "SELECT payload FROM inquiry_events WHERE kind='falsifier_hit'")]
        self.assertEqual(1, len(hits))
        self.assertEqual(claim, hits[0]['proposal'])

    def test_the_inherited_view_carries_no_verdict_boolean(self):
        claim = self.accept(CHECK)
        event = self.receipt(PARAMS, 'to_second<=C')
        receipt_hits(self.q.knowledge, self.q.run, event, synthetic=True)
        bridge = self.q.knowledge.review_packet(self.revise(claim, event))['bridge']
        self.assertEqual([], [k for k, v in bridge.items() if isinstance(v, bool)])
        self.assertEqual('finite_computation_under_stated_model_not_truth_verdict',
                         bridge['epistemic_status'])

    def test_a_revision_of_an_unscored_proposal_keeps_the_legacy_packet(self):
        claim = self.accept(None)
        self.q.visible_source_text[claim] = self.q.knowledge.source(claim)['text']
        self.q.visible_source_text[self.u] = self.q.knowledge.source(self.u)['text']
        revised = self.q.knowledge.accept(self.q.run, self.revision_terms(
            '没人再问我了，所以流程可以保留。',
            [{'event': self.u, 'quote': '没人再问我了', 'role': 'assumption'}],
            '若有人重新来问，本条不成立。', claim), self.q.visible_source_text, synthetic=True)
        self.assertNotIn('bridge', self.q.knowledge.review_packet(revised))


if __name__ == '__main__':
    unittest.main()
