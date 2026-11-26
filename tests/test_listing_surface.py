"""r65: the CLI listing must show what the review packet already holds.

Until r65 the packet carried `bridge`, `bridge_checked_without_hit`,
`bridge_refused` and `review_attempts`, and `Knowledge.proposals()` -- the row
set behind `python -m dojo knowledge` -- showed none of them. A proposal that had
been scored and survived, one the bridge refused, and one parked after a failed
review attempt therefore read exactly like one nothing had happened to.
"""
import unittest

import dojo.knowledge as knowledge_module
from dojo.falsifier import receipt_hits
from tests.test_knowledge import Client
from tests.test_review_attempts import CHECK, PARAMS, Fixture


class ListingSurfaceTests(Fixture):
    def row(self, event):
        return next(r for r in self.q.knowledge.proposals(synthetic=True) if r['event'] == event)

    def failing_attempt(self, claim, kind='review_schema'):
        return self.q.record('review_failure', {
            'target': claim,
            'packet_sha256': self.q.knowledge.review_packet(claim)['sha256'],
            'kind': kind})

    def test_a_parked_attempt_reaches_the_listing(self):
        claim = self.accept(CHECK)
        self.assertNotIn('review_attempts', self.row(claim))
        self.failing_attempt(claim)
        row = self.row(claim)
        self.assertIn('review_attempts', row)
        self.assertEqual('review_schema', row['review_attempts'][0]['failure'])
        # The listing shows the packet's own object, not a re-rendering of it.
        self.assertEqual(self.q.knowledge.review_packet(claim)['review_attempts'],
                         row['review_attempts'])

    def test_a_bridged_proposal_shows_the_bridge_in_the_listing(self):
        claim = self.accept(CHECK)
        event = self.receipt(PARAMS, 'to_second<=C')
        receipt_hits(self.q.knowledge, self.q.run, event, synthetic=True)
        row = self.row(claim)
        self.assertIn('bridge', row)
        packet = self.q.knowledge.review_packet(claim)
        self.assertEqual(packet['bridge'], row['bridge'])
        self.assertEqual('finite_computation_under_stated_model_not_truth_verdict',
                         row['bridge']['epistemic_status'])

    def test_a_proposal_nothing_happened_to_keeps_its_old_shape(self):
        """The surface adds no key that the packet does not already carry: an
        empty `bridge` or a default `review_attempts: []` would make 'never
        scored' indistinguishable from a reading. 977 of 980 real rows are this
        case, so their listing bytes must not move (verified byte for byte in
        .scratch/dojo-grid/r65_diff.py)."""
        claim = self.accept(CHECK)
        self.assertEqual(
            {'event', 'run', 'proposal', 'synthetic', 'epistemic_status', 'dependency_status'},
            set(self.row(claim)))

    def test_the_surface_is_the_packet_key_list_not_a_copy(self):
        """Teeth: emptying the shared name must empty the listing too. A test
        that still passes with the list emptied is pinning nothing."""
        original = knowledge_module.PACKET_SURFACE_KEYS
        claim = self.accept(CHECK)
        self.failing_attempt(claim)
        try:
            knowledge_module.PACKET_SURFACE_KEYS = ()
            self.assertNotIn('review_attempts', self.row(claim))
        finally:
            knowledge_module.PACKET_SURFACE_KEYS = original
        self.assertIn('review_attempts', self.row(claim))

    def test_the_surface_adds_no_verdict_boolean(self):
        claim = self.accept(CHECK)
        self.failing_attempt(claim)
        event = self.receipt(PARAMS, 'to_second<=C')
        receipt_hits(self.q.knowledge, self.q.run, event, synthetic=True)
        row = self.row(claim)
        # r87: `review_attempts` is a list, and until r87 this branch never saw it --
        # the attempt was silently dropped because its digest had moved, so the only
        # key present was the `bridge` dict. The test passed for the wrong reason.
        # It now inspects dicts and dicts inside lists alike.
        def booleans(value):
            if isinstance(value, dict):
                return [k for k, v in value.items() if isinstance(v, bool)] + [
                    k for v in value.values() for k in booleans(v)]
            if isinstance(value, list):
                return [k for v in value for k in booleans(v)]
            return []
        for key in knowledge_module.PACKET_SURFACE_KEYS:
            if key in row:
                self.assertEqual([], booleans(row[key]))
        self.assertFalse([k for k in row if k in {
            'passed', 'verified', 'holds', 'satisfied', 'ok', 'survived', 'confirmed',
            'rejected', 'failed'}])

    def test_listing_does_not_move_a_packet_digest_or_a_candidate(self):
        claim = self.accept(CHECK)
        self.failing_attempt(claim)
        before = self.q.knowledge.review_packet(claim)['sha256']
        candidates_before = [p['target'] for p in
                             self.q.knowledge.review_candidates(synthetic=True, limit=50)]
        self.q.knowledge.proposals(synthetic=True)
        self.assertEqual(before, self.q.knowledge.review_packet(claim)['sha256'])
        self.assertEqual(candidates_before, [p['target'] for p in
                         self.q.knowledge.review_candidates(synthetic=True, limit=50)])

    def test_listing_writes_nothing(self):
        claim = self.accept(CHECK)
        self.failing_attempt(claim)
        snapshot = self.q.db.execute('SELECT seq,kind,payload,at FROM inquiry_events').fetchall()
        self.q.knowledge.proposals(synthetic=True)
        self.assertEqual(snapshot,
                         self.q.db.execute('SELECT seq,kind,payload,at FROM inquiry_events').fetchall())

    def test_an_inherited_bridge_reaches_the_listing(self):
        """The pre-scan must find ids named only by `inquiry_revisions`: a review
        that replaces a scored proposal mints an id that no hit names."""
        claim = self.accept(CHECK)
        event = self.receipt(PARAMS, 'to_second<=C')
        receipt_hits(self.q.knowledge, self.q.run, event, synthetic=True)
        revised = self.revise(claim, event)
        row = self.row(revised)
        self.assertIn('bridge', row)
        self.assertEqual(claim, row['bridge']['inherited_from'])

    def test_a_refused_candidate_reaches_the_listing(self):
        """The pre-scan must find ids named inside a bridge check's outcomes: a
        refusal writes no hit row, only an outcome entry in
        `falsifier_bridge_checked` -- and `execute_action` is the only production
        writer of that event, so the test drives it rather than receipt_hits.

        The receipt must also have found counterexamples, or the bridge skips it
        before comparing grids. C=[2,4] fails at N=50,u=60, so the refusal below
        is the grid mismatch and nothing else.
        """
        claim = self.accept(CHECK)
        action = {'kind': 'experiment',
                  'parameters': {'N': [20, 50], 'u': [5, 60], 'C': [2, 4]},
                  'derived': {'to_second': 'N*u/100'}, 'assertion': 'to_second<=C',
                  'assumptions': ['容量固定'], 'prediction': 'p'}
        reflection = self.q.record('reflection', {'synthetic': True,
                                                  'reflection': {'answer': '测一下', 'action': action}})
        self.q.execute_action(action, reflection)
        row = self.row(claim)
        self.assertIn('bridge_refused', row)
        self.assertEqual('parameter_values_do_not_match_receipt_domain',
                         row['bridge_refused']['reason'])

    def test_every_listed_row_matches_its_packet(self):
        """Equivalence between the pre-scan and the packet, on every construction
        this fixture can make: no row gains a key the packet lacks or misses one
        it has. On 980 real rows this was measured at 0 mismatches
        (.scratch/dojo-grid/r65_equiv.py)."""
        a = self.accept(CHECK)
        b = self.accept(CHECK)
        event = self.receipt(PARAMS, 'to_second<=C')
        receipt_hits(self.q.knowledge, self.q.run, event, synthetic=True)
        self.failing_attempt(b)
        for row in self.q.knowledge.proposals(synthetic=True):
            packet = self.q.knowledge.review_packet(row['event'])
            want = {k: packet[k] for k in knowledge_module.PACKET_SURFACE_KEYS if k in packet}
            got = {k: row[k] for k in knowledge_module.PACKET_SURFACE_KEYS if k in row}
            self.assertEqual(want, got, row['event'])
        self.assertIn('bridge', self.row(a))
        self.assertIn('review_attempts', self.row(b))

if __name__ == '__main__':
    unittest.main()
