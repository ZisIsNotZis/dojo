"""The falsifier bridge only downgrades; it never judges a proposal false.

Prose is not understood: a predicate must be bound to the exact falsifier text.
"""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from dojo.experiments import parameter_sweep
from dojo.falsifier import CRITERIA_VERSION, compile_check, evaluate, evaluate_point, receipt_hits
from dojo.inquiry import Inquiry
from tests.test_knowledge import Client

PROSE = '若第二人每天要复核的件数超过其容量，则流量并未真正转移。'
# The receipt assertion an experiment actually ran. A hit needs it: a predicate
# that only holds where the receipt's own assertion held has found no failure.
ASSERTION = 'to_second<=C'
PARAMS = {'N': [20, 50], 'u': [5, 60], 'C': [2, 40]}
DERIVED = {'to_second': 'N*u/100'}
FAILING_POINT = {'N': 20, 'u': 5, 'C': 40}
CHECK = {'falsifier_sha256': hashlib.sha256(PROSE.encode('utf-8')).hexdigest(),
         'parameters': PARAMS, 'derived': DERIVED, 'predicate': 'to_second>C',
         'predicate_fails_at': FAILING_POINT}
# A predicate no point on PARAMS satisfies: the bridge walks the grid and misses.
# to_second = N*u/100 never exceeds 1000 on PARAMS, so no grid point falsifies it.
# It still gets in: `predicate_fails_at` is checked against the predicate only,
# so a predicate that misses everywhere is falsifiable-but-unrefuted, which is
# exactly the not_hit case these tests are about.
PASSES_EVERYWHERE = {**CHECK, 'predicate': 'to_second>1000'}
# Same keys, different values: the bridge refuses instead of scoring.
NEVER_ENUMERATED_GRID = {'N': [50], 'u': [60], 'C': [2]}


def proposal(prose, check):
    p = {'statement': '未归类比例把第二个人变成瓶颈时，流量没有真正转移。','kind': 'causal','method': 'hypothesis',
         'premises': [],'assumptions': ['容量固定'],'conditions': ['仅此参数网格'],'alternatives': ['保留兵底'],
         'falsifier': prose,'revises': None}
    if check is not None:
        p['falsifier_check'] = check
    return p


class CompileTests(unittest.TestCase):
    def test_predicate_bound_to_other_prose_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'bound to different falsifier text'):
            compile_check(CHECK, PROSE + '（改了一个字）')

    def test_unparsable_predicate_is_refused_with_reason(self):
        bad = {**CHECK, 'predicate': 'import os'}
        with self.assertRaisesRegex(ValueError, 'does not compile'):
            compile_check(bad, PROSE)

    def test_unknown_field_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'falsifier_check needs exactly'):
            compile_check({**CHECK, 'selector': 'x'}, PROSE)

    def test_omitted_digest_is_computed_from_the_prose_it_binds(self):
        """A model cannot hash the prose: no tool returns sha256. Requiring the
        digest made the predicate unreachable, so the server computes it. The
        stored form is unchanged, so the read-back validation still applies."""
        check = compile_check({'parameters': PARAMS, 'derived': DERIVED, 'predicate': 'to_second>C',
                               'predicate_fails_at': FAILING_POINT}, PROSE)
        self.assertEqual(hashlib.sha256(PROSE.encode('utf-8')).hexdigest(), check['falsifier_sha256'])
        self.assertEqual({'falsifier_sha256', 'parameters', 'derived', 'predicate',
                          'predicate_fails_at'}, set(check))
        verdict = evaluate(check, PARAMS, DERIVED, ASSERTION)
        self.assertEqual('evaluated', verdict['status'])
        # knowledge.py:31 writes this dict back, so re-compiling it must not raise.
        self.assertEqual(check, compile_check(check, PROSE))

    def test_filled_digest_still_rejects_prose_edited_afterwards(self):
        """Filling the digest must not weaken the only guard against inheriting
        a predicate written for different prose. An explicit wrong digest is
        also refused rather than silently overwritten."""
        stored = compile_check({'parameters': PARAMS, 'derived': DERIVED, 'predicate': 'to_second>C',
                                'predicate_fails_at': FAILING_POINT}, PROSE)
        with self.assertRaisesRegex(ValueError, 'bound to different falsifier text'):
            compile_check(stored, PROSE + '（改了一个字）')
        with self.assertRaisesRegex(ValueError, 'bound to different falsifier text'):
            compile_check({**stored, 'falsifier_sha256': '0' * 64}, PROSE)

    def test_domain_mismatch_is_refused_not_reinterpreted(self):
        check = compile_check(CHECK, PROSE)
        verdict = evaluate(check, {'N': [20], 'u': [60], 'C': [2], 'p': [10]}, DERIVED, ASSERTION)
        self.assertEqual('refused', verdict['status'])
        self.assertEqual('parameter_names_do_not_match_receipt_domain', verdict['reason'])

    def test_same_names_but_other_declared_values_are_refused(self):
        """Declaring the right parameter *names* is not enough: the receipt
        searched a different grid, so the predicate would be scored on points
        the experiment never computed. That is neither a hit nor a miss."""
        check = compile_check(CHECK, PROSE)
        verdict = evaluate(check, {'N': [20, 50], 'u': [5, 60], 'C': [2, 41]}, DERIVED, ASSERTION)
        self.assertEqual('refused', verdict['status'])
        self.assertEqual('parameter_values_do_not_match_receipt_domain', verdict['reason'])
        self.assertNotIn('hits', verdict)

    def test_declared_grid_missing_a_point_is_refused(self):
        """A declared grid smaller than the searched one is still a different grid."""
        check = compile_check(CHECK, PROSE)
        verdict = evaluate(check, {'N': [20], 'u': [5, 60], 'C': [2, 40]}, DERIVED, ASSERTION)
        self.assertEqual('refused', verdict['status'])
        self.assertEqual('parameter_values_do_not_match_receipt_domain', verdict['reason'])

    def test_same_names_but_other_derived_model_is_refused(self):
        """Identical parameter names are not enough: the receipt computed a
        different quantity, so neither a hit nor a miss may be reported."""
        check = compile_check(CHECK, PROSE)
        verdict = evaluate(check, {'N': [20, 50], 'u': [5, 60], 'C': [2, 40]}, {'to_second': 'N*u'}, ASSERTION)
        self.assertEqual('refused', verdict['status'])
        self.assertEqual('derived_formula_does_not_match_receipt_model', verdict['reason'])
        self.assertEqual({'to_second': {'declared': 'N*u/100', 'receipt': 'N*u'}}, verdict['differing'])

    def test_evaluated_result_reports_which_derived_formulas_were_compared(self):
        """残口(a)：候选少声明 derived 也能 evaluated。判定不改，但读者必须能
        看见这次到底比了几个公式——否则「derived 已逐字比对」会被读成全覆盖。"""
        check = compile_check(CHECK, PROSE)
        verdict = evaluate(check, {'N': [20, 50], 'u': [5, 60], 'C': [2, 40]}, DERIVED, ASSERTION)
        self.assertEqual('evaluated', verdict['status'])
        self.assertEqual(['to_second'], verdict['derived_compared'])

    def test_empty_declaration_is_still_evaluated_but_reports_zero_coverage(self):
        """不补键集门禁（根已拍 B）：口径是让覆盖面可见，不是拒掉单量候选。"""
        small = {**CHECK, 'derived': {}, 'predicate': 'C>=40',
                 'predicate_fails_at': {'N': 20, 'u': 5, 'C': 2}}
        check = compile_check(small, PROSE)
        verdict = evaluate(check, {'N': [20, 50], 'u': [5, 60], 'C': [2, 40]}, DERIVED, ASSERTION)
        self.assertEqual('evaluated', verdict['status'])
        self.assertEqual([], verdict['derived_compared'])

    def test_refused_verdict_carries_no_coverage_field(self):
        check = compile_check(CHECK, PROSE)
        verdict = evaluate(check, {'N': [20], 'u': [5, 60], 'C': [2, 40]}, DERIVED, ASSERTION)
        self.assertEqual('refused', verdict['status'])
        self.assertNotIn('derived_compared', verdict)

    def test_receipt_without_derived_definitions_is_refused(self):
        check = compile_check(CHECK, PROSE)
        # The grid matches on purpose: this case isolates "no derived on the
        # receipt", so it must not also trip the grid check.
        verdict = evaluate(check, PARAMS, None, ASSERTION)
        self.assertEqual('refused', verdict['status'])
        self.assertEqual('receipt_does_not_record_derived_definitions', verdict['reason'])

    def test_hit_is_the_point_where_the_falsifier_holds(self):
        check = compile_check(CHECK, PROSE)
        verdict = evaluate(check, {'N': [20, 50], 'u': [5, 60], 'C': [2, 40]}, DERIVED, ASSERTION)
        self.assertEqual('evaluated', verdict['status'])
        # 3 of 8 grid points put to_second above capacity:
        # 20/60 -> 12 > 2, 50/5 -> 2.5 > 2, 50/60 -> 30 > 2 (none exceed 40).
        self.assertEqual(3, verdict['hits'])
        self.assertTrue(evaluate_point(check, {'N': 50, 'u': 60, 'C': 2})['holds'])
        self.assertFalse(evaluate_point(check, {'N': 20, 'u': 5, 'C': 40})['holds'])


class StrictHitDefinitionTests(unittest.TestCase):
    """r48: a hit is a point where the predicate holds AND the receipt's own
    assertion failed. r46 found a predicate (P1==1 and badfmt==1) whose hits all
    fell on points where the receipt's assertion held, so the bridge downgraded a
    proposal while reporting something the experiment never contradicted.

    These tests pin both directions: the disjoint case must stop counting, and
    the coincident case must keep counting.
    """

    # 8 points; to_second = N*u/100 in {1, 2.5, 12, 30}.
    STRICT_PARAMS = {'N': [20, 50], 'u': [5, 60], 'C': [2, 40]}

    def check(self, predicate, fails_at):
        return compile_check({'parameters': self.STRICT_PARAMS, 'derived': DERIVED,
                              'predicate': predicate, 'predicate_fails_at': fails_at}, PROSE)

    def test_coincident_predicate_keeps_its_hits(self):
        """The honest case must not be collateral damage."""
        stored = self.check('to_second>C', {'N': 20, 'u': 5, 'C': 40})
        verdict = evaluate(stored, self.STRICT_PARAMS, DERIVED, 'to_second<=C')
        self.assertEqual('evaluated', verdict['status'])
        self.assertEqual(3, verdict['hits'])
        self.assertEqual(3, verdict['predicate_only_hits'])

    def test_predicate_holding_where_the_assertion_held_is_not_a_hit(self):
        """The DISJOINT shape found on disk: every point where the predicate
        holds is a point where the receipt's assertion held too, so the
        experiment found no counterexample there. hits must be zero."""
        # 'to_second>C and N>=20' holds at 3 points, all of which satisfy
        # 'to_second<=C' -- fabricated by asserting the negation of the predicate.
        stored = self.check('to_second>C', {'N': 20, 'u': 5, 'C': 40})
        verdict = evaluate(stored, self.STRICT_PARAMS, DERIVED, 'to_second>C or C>=40')
        self.assertEqual('evaluated', verdict['status'])
        self.assertEqual(0, verdict['hits'])
        # The count the old definition reported stays visible, but under a name
        # that cannot be read as a hit.
        self.assertEqual(3, verdict['predicate_only_hits'])

    def test_receipt_without_an_assertion_is_refused_not_scored(self):
        """No assertion means the failure side cannot be computed. Falling back
        to 'predicate holds' would silently restore the old definition."""
        stored = self.check('to_second>C', {'N': 20, 'u': 5, 'C': 40})
        verdict = evaluate(stored, self.STRICT_PARAMS, DERIVED, None)
        self.assertEqual('refused', verdict['status'])
        self.assertEqual('receipt_does_not_record_the_assertion_that_failed', verdict['reason'])
        self.assertNotIn('hits', verdict)

    def test_unparsable_receipt_assertion_is_refused_not_scored(self):
        stored = self.check('to_second>C', {'N': 20, 'u': 5, 'C': 40})
        verdict = evaluate(stored, self.STRICT_PARAMS, DERIVED, 'import os')
        self.assertEqual('refused', verdict['status'])
        # The reason name is fixed and the parser detail is appended after it.
        self.assertTrue(verdict['reason'].startswith('receipt_assertion_does_not_compile'),
                        verdict['reason'])

    def test_evaluated_verdict_declares_which_definition_produced_it(self):
        """Old rows are not rewritten, so a reading without a version cannot be
        compared to a new one."""
        stored = self.check('to_second>C', {'N': 20, 'u': 5, 'C': 40})
        verdict = evaluate(stored, self.STRICT_PARAMS, DERIVED, 'to_second<=C')
        self.assertEqual('predicate_holds_and_receipt_assertion_fails', verdict['hit_definition'])
        self.assertEqual(CRITERIA_VERSION, verdict['criteria_version'])

    def test_a_disjoint_hit_no_longer_downgrades_the_proposal(self):
        """End-to-end: the on-disk DISJOINT shape must leave the state alone.

        Before r48 this exact input produced hits=3 and needs_review.
        """
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            q = Inquiry(Path(tmp) / 'db', Client(), synthetic=True)
            try:
                u = q.record('user', {'text': '没人再问我了', 'synthetic': True})
                p = proposal(PROSE, self.check('to_second>C', {'N': 20, 'u': 5, 'C': 40}))
                p['premises'] = [{'event': u, 'quote': '没人再问我了', 'role': 'assumption'}]
                claim = q.knowledge.accept(q.run, p, {u}, synthetic=True)
                receipt = q.record('tool_result', {
                    'action': {'kind': 'experiment', 'parameters': self.STRICT_PARAMS,
                               'derived': DERIVED, 'assertion': 'to_second>C or C>=40',
                               'prediction': 'p'},
                    'status': 'executed',
                    'result': parameter_sweep(self.STRICT_PARAMS, DERIVED, 'to_second>C or C>=40')})
                outcome = receipt_hits(q.knowledge, q.run, receipt, synthetic=True)
                hit = [o for o in outcome['outcomes'] if o['proposal'] == claim][0]
                self.assertEqual('not_hit', hit['status'])
                self.assertEqual('current_interpretation', q.dependencies.status(claim)['state'])
            finally:
                q.close()


class BridgeTests(unittest.TestCase):
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
        # The real experiment action always carries `derived`; without it the
        # receipt cannot confirm which model produced the counterexamples.
        return self.q.record('tool_result', {'action': {'kind': 'experiment', 'derived': derived, 'prediction': 'p'},
                                            'status': 'executed',
                                            'result': parameter_sweep(parameters, derived, assertion)})

    def test_hit_downgrades_but_does_not_rewrite_the_claim(self):
        claim = self.accept(CHECK)
        self.assertEqual('current_interpretation', self.q.dependencies.status(claim)['state'])
        event = self.receipt(PARAMS, 'to_second<=C')
        outcome = receipt_hits(self.q.knowledge, self.q.run, event, synthetic=True)
        self.assertEqual('needs_review', self.q.dependencies.status(claim)['state'])
        hit = [o for o in outcome['outcomes'] if o['proposal'] == claim][0]
        self.assertEqual('needs_review', hit['status'])
        self.assertGreater(hit['hits'], 0)
        self.assertEqual('model_proposal_not_certified', self.q.knowledge.source(claim)['epistemic_status'])
        self.assertNotIn('false', str(hit).lower())

    def test_other_derived_model_never_downgrades(self):
        claim = self.accept(CHECK)
        event = self.receipt(PARAMS, 'to_second<=C', derived={'to_second': 'N*u'})
        outcome = receipt_hits(self.q.knowledge, self.q.run, event, synthetic=True)
        self.assertEqual('checked', outcome['status'])
        hit = [o for o in outcome['outcomes'] if o['proposal'] == claim][0]
        self.assertEqual('refused', hit['status'])
        self.assertEqual('derived_formula_does_not_match_receipt_model', hit['reason'])
        self.assertEqual('current_interpretation', self.q.dependencies.status(claim)['state'])

    def test_passing_receipt_never_downgrades(self):
        claim = self.accept(CHECK)
        event = self.receipt({'N': [1], 'u': [1], 'C': [40]}, 'to_second<=C')
        outcome = receipt_hits(self.q.knowledge, self.q.run, event, synthetic=True)
        self.assertEqual('skipped', outcome['status'])
        self.assertEqual('current_interpretation', self.q.dependencies.status(claim)['state'])

    def test_prose_alone_never_downgrades(self):
        claim = self.accept(None)
        event = self.receipt(PARAMS, 'to_second<=C')
        outcome = receipt_hits(self.q.knowledge, self.q.run, event, synthetic=True)
        self.assertEqual('checked', outcome['status'])
        self.assertEqual([], outcome['outcomes'])
        self.assertEqual('current_interpretation', self.q.dependencies.status(claim)['state'])

    def revision_terms(self, statement, premises, falsifier, revises):
        return {'statement': statement, 'kind': 'causal', 'method': 'hypothesis', 'premises': premises,
                'assumptions': ['容量固定'], 'conditions': ['仅此参数网格'], 'alternatives': ['保留兵底'],
                'falsifier': falsifier, 'revises': revises}

    def test_hit_then_revise_completes_without_apply_review(self):
        """A hit makes the proposal reviewable; the revision itself is an
        ordinary proposal pointing at it, not something apply_review alone can do."""
        claim = self.accept(CHECK)
        event = self.receipt(PARAMS, 'to_second<=C')
        receipt_hits(self.q.knowledge, self.q.run, event, synthetic=True)
        self.assertEqual('needs_review', self.q.dependencies.status(claim)['state'])
        self.q.visible_source_text[claim] = self.q.knowledge.source(claim)['text']
        self.q.visible_source_text[event] = self.q.knowledge.source(event)['text']
        prose = '若容量充足时也无法转移，则本条不成立。'
        revised = self.q.knowledge.accept(self.q.run, self.revision_terms(
            '流量转移只在人手不足时受阻；容量充足时仍可转移。',
            [{'event': event, 'quote': 'counterexample_count', 'role': 'evidence'}], prose, claim),
            self.q.visible_source_text, synthetic=True)
        state = self.q.dependencies.status(claim)
        self.assertEqual('superseded', state['state'])
        self.assertEqual(revised, state['replacement'])
        # The replacement cites the very receipt that was the hit cause; it must
        # not inherit needs_review from it, or the fix would poison its own cure.
        self.assertEqual('current_interpretation', self.q.dependencies.status(revised)['state'])

    def test_replacement_that_depends_on_the_hit_claim_is_refused(self):
        claim = self.accept(CHECK)
        event = self.receipt(PARAMS, 'to_second<=C')
        receipt_hits(self.q.knowledge, self.q.run, event, synthetic=True)
        claim_text = self.q.knowledge.source(claim)['text']
        self.q.visible_source_text[claim] = claim_text
        with self.assertRaisesRegex(ValueError, 'replacement depends on old proposition'):
            self.q.knowledge.accept(self.q.run, self.revision_terms(
                '把容量提高到3就能转移。', [{'event': claim, 'quote': claim_text, 'role': 'evidence'}],
                '若容量3仍不足则不成立。', claim), self.q.visible_source_text, synthetic=True)

    def test_hit_event_is_not_a_citable_source(self):
        """The hit is bookkeeping, not evidence; citing it would let the bridge
        launder its own verdict into a premise."""
        claim = self.accept(CHECK)
        event = self.receipt(PARAMS, 'to_second<=C')
        outcome = receipt_hits(self.q.knowledge, self.q.run, event, synthetic=True)
        hit_event = [o for o in outcome['outcomes'] if o['proposal'] == claim][0]['hit_event']
        self.q.visible_source_text[hit_event] = self.q.knowledge.source(hit_event)['text']
        with self.assertRaisesRegex(ValueError, 'invalid source kind'):
            self.q.knowledge.accept(self.q.run, self.revision_terms(
                '容量条件过强。', [{'event': hit_event, 'quote': 'needs_review', 'role': 'evidence'}],
                '若容量条件不过强则不成立。', claim), self.q.visible_source_text, synthetic=True)

    def test_hit_proposal_is_offered_to_the_review_worker(self):
        claim = self.accept(CHECK)
        event = self.receipt(PARAMS, 'to_second<=C')
        outcome = receipt_hits(self.q.knowledge, self.q.run, event, synthetic=True)
        hit_event = [o for o in outcome['outcomes'] if o['proposal'] == claim][0]['hit_event']
        candidates = self.q.knowledge.review_candidates(synthetic=True, limit=3)
        packet = [c for c in candidates if c['target'] == claim][0]
        self.assertIn(hit_event, [s['event'] for s in packet['sources']])
        self.assertEqual('needs_review', packet['dependency_status']['state'])

    def test_hit_payload_keeps_the_coverage_the_reviewer_reads(self):
        """The reviewer reads the stored hit payload, not the evaluate() return.
        If coverage stops at evaluate(), a hit on a single-formula check reads
        exactly like a hit on the whole receipt model."""
        claim = self.accept(CHECK)
        event = self.receipt(PARAMS, 'to_second<=C')
        outcome = receipt_hits(self.q.knowledge, self.q.run, event, synthetic=True)
        hit = [o for o in outcome['outcomes'] if o['proposal'] == claim][0]
        self.assertEqual(['to_second'], hit['derived_compared'])
        stored = self.q.db.execute(
            "SELECT payload FROM inquiry_events WHERE kind='falsifier_hit' AND seq=?",
            (hit['hit_event'],)).fetchone()[0]
        self.assertIn('derived_compared', stored)
        self.assertIn('to_second', stored)

    def test_hit_payload_carries_the_grid_it_was_scored_on(self):
        """The hit tells the reviewer '1 of 2 points held' without saying which
        grid those points came from. #555's gate compares the declared grid to
        the receipt's grid, but the receipt's grid never reaches the reviewer,
        so that gate can only be believed, not checked. Carry it with the hit."""
        claim = self.accept(CHECK)
        event = self.receipt(PARAMS, 'to_second<=C')
        outcome = receipt_hits(self.q.knowledge, self.q.run, event, synthetic=True)
        hit = [o for o in outcome['outcomes'] if o['proposal'] == claim][0]
        self.assertEqual(PARAMS, hit['domain'])
        stored = json.loads(self.q.db.execute(
            "SELECT payload FROM inquiry_events WHERE kind='falsifier_hit' AND seq=?",
            (hit['hit_event'],)).fetchone()[0])
        self.assertEqual(PARAMS, stored['domain'])
        # What the reviewer actually reads, not just the storage column.
        self.q.visible_source_text[hit['hit_event']] = self.q.knowledge.source(hit['hit_event'])['text']
        cause = self.q.knowledge.review_context(claim, self.q.dependencies.status(claim))['causes'][0]
        self.assertFalse(cause['excerpt_truncated'])
        self.assertEqual(PARAMS, json.loads(cause['excerpt'])['domain'])

    def test_packet_carries_the_bridge_so_the_reviewer_need_not_hunt_for_it(self):
        """The reviewer is handed a packet, not the event log. A hit is only
        reachable from that packet through `dependency_status.causes`, one event
        per cause, four causes max. If the bridge readings are not in the packet
        itself the reviewer must trust the downgrade without its numbers."""
        claim = self.accept(CHECK)
        self.assertNotIn('bridge', self.q.knowledge.review_packet(claim))
        event = self.receipt(PARAMS, 'to_second<=C')
        outcome = receipt_hits(self.q.knowledge, self.q.run, event, synthetic=True)
        hit = [o for o in outcome['outcomes'] if o['proposal'] == claim][0]
        packet = self.q.knowledge.review_packet(claim)
        self.assertIn('bridge', packet)
        bridge = packet['bridge']
        self.assertEqual(hit['hit_event'], bridge['hit_event'])
        self.assertEqual(event, bridge['receipt'])
        self.assertEqual(PARAMS, bridge['domain'])
        # The bridge records the *candidate's* predicate, not the receipt's
        # assertion; the reviewer recovers the asserted claim from the receipt
        # source itself. Pinned here so the difference is not mistaken for a bug.
        self.assertEqual('to_second>C', bridge['predicate'])
        self.assertEqual(hit['evaluated'], bridge['evaluated'])
        self.assertEqual(hit['hits'], bridge['hits'])
        self.assertEqual(['to_second'], bridge['derived_compared'])
        # The coverage limit must travel with the readings, not only with evaluate().
        self.assertEqual('finite_computation_under_stated_model_not_truth_verdict',
                         bridge['epistemic_status'])

    def test_packet_digest_covers_the_bridge_readings(self):
        """apply_review trusts packet['sha256'] to decide whether the packet was
        substituted (reviews.py). A bridge outside the digest could be rewritten
        between offering and applying the review without that check noticing."""
        from dojo.anchors import packet_hash
        claim = self.accept(CHECK)
        event = self.receipt(PARAMS, 'to_second<=C')
        receipt_hits(self.q.knowledge, self.q.run, event, synthetic=True)
        packet = self.q.knowledge.review_packet(claim)
        self.assertIn('bridge', packet)
        self.assertEqual(packet_hash(packet), packet['sha256'])
        without_bridge = {k: v for k, v in packet.items() if k not in {'sha256', 'bridge'}}
        self.assertNotEqual(packet_hash(without_bridge), packet['sha256'])

    def test_a_pre_r48_hit_row_keeps_the_legacy_packet_digest(self):
        """Rows written before r48 keep the old `hits` meaning, and their packets
        must not gain keys: a new key would change the digest and silently
        un-suppress recorded review attempts. The 15 bridged rows on disk are
        exactly this shape (no criteria_version), so this is a live invariant.
        """
        from dojo.anchors import packet_hash
        claim = self.accept(CHECK)
        event = self.receipt(PARAMS, 'to_second<=C')
        receipt_hits(self.q.knowledge, self.q.run, event, synthetic=True)
        # Rewrite the stored hit payload to the pre-r48 shape.
        row = self.q.db.execute(
            "SELECT seq,payload FROM inquiry_events WHERE kind='falsifier_hit' ORDER BY seq DESC LIMIT 1").fetchone()
        data = json.loads(row[1])
        # receipt_passed is newer still (r62): a pre-r48 row cannot carry it, and
        # leaving it in would test a shape no stored row ever had.
        for key in ('criteria_version', 'hit_definition', 'receipt_passed'):
            data.pop(key, None)
        self.q.db.execute('UPDATE inquiry_events SET payload=? WHERE seq=?',
                          (json.dumps(data, ensure_ascii=False), row[0]))
        self.q.db.commit()
        packet = self.q.knowledge.review_packet(claim)
        self.assertIn('bridge', packet)
        self.assertNotIn('criteria_version', packet['bridge'])
        self.assertNotIn('hit_definition', packet['bridge'])
        self.assertEqual(
            {'hit_event', 'receipt', 'receipt_at', 'predicate', 'evaluated', 'hits',
             'derived_compared', 'domain', 'epistemic_status'}, set(packet['bridge']))
        self.assertEqual(packet_hash(packet), packet['sha256'])

    def test_a_r48_hit_row_carries_the_definition_the_reviewer_reads(self):
        """A new reading must say which definition produced it; otherwise two
        incomparable counts look the same in the packet."""
        claim = self.accept(CHECK)
        event = self.receipt(PARAMS, 'to_second<=C')
        outcome = receipt_hits(self.q.knowledge, self.q.run, event, synthetic=True)
        hit = [o for o in outcome['outcomes'] if o['proposal'] == claim][0]
        self.assertEqual('r48', hit['criteria_version'])
        bridge = self.q.knowledge.review_packet(claim)['bridge']
        self.assertEqual('r48', bridge['criteria_version'])
        self.assertEqual('predicate_holds_and_receipt_assertion_fails', bridge['hit_definition'])

    def test_unbridged_packet_keeps_exactly_the_old_shape(self):
        """Every proposal that never crossed the bridge must keep the legacy
        packet: same key set, same digest definition. The 151 recorded review
        attempts exist to catch a coverage change that silently re-opens work."""
        from dojo.anchors import packet_hash
        claim = self.accept(CHECK)
        packet = self.q.knowledge.review_packet(claim)
        self.assertEqual({'target', 'proposal', 'dependency_status', 'sources',
                          'source_expansion_truncated', 'truth', 'citation_contract',
                          'anchors', 'sha256'}, set(packet))
        self.assertEqual(packet_hash(packet), packet['sha256'])

    def experiment(self, parameters):
        """Drive the real entry: only execute_action writes bridge_checked."""
        action = {'kind': 'experiment', 'parameters': parameters, 'derived': DERIVED,
                  'assertion': 'to_second<=C', 'assumptions': ['容量固定'], 'prediction': 'p'}
        reflection = self.q.record('reflection', {'synthetic': True,
                                                  'reflection': {'answer': '测一下', 'action': action}})
        return self.q.execute_action(action, reflection)[0]

    def test_enumerated_without_a_hit_keeps_a_visible_record(self):
        """'Enumerated and survived' and 'never enumerated' must not read alike.

        A `not_hit` outcome lives inside `falsifier_bridge_checked.outcomes`,
        which no reader in dojo/ touches, so the packet used to be byte-identical
        whether the candidate's grid had been walked or never scored at all.
        """
        claim = self.accept(PASSES_EVERYWHERE)
        self.assertNotIn('bridge_checked_without_hit', self.q.knowledge.review_packet(claim))
        receipt = self.experiment(PARAMS)
        checked = json.loads(self.q.db.execute(
            "SELECT payload FROM inquiry_events WHERE kind='falsifier_bridge_checked' ORDER BY seq DESC LIMIT 1").fetchone()[0])
        # A not_hit under r48 is a different claim than a not_hit before it: no
        # point exists where the predicate holds *and* the receipt's assertion
        # failed. The stamp is stored with the outcome because old rows keep the
        # old meaning and the two are not comparable.
        self.assertEqual([{'proposal': claim, 'status': 'not_hit', 'evaluated': 8,
                           'predicate_only_hits': 0, 'criteria_version': 'r48'}], checked['outcomes'])
        reading = self.q.knowledge.review_packet(claim)['bridge_checked_without_hit']
        self.assertEqual(receipt, reading['receipt'])
        self.assertEqual(8, reading['evaluated'])
        self.assertEqual('finite_computation_under_stated_model_not_truth_verdict',
                         reading['epistemic_status'])
        # A visible record only: the downgrade decision must not move.
        self.assertEqual('current_interpretation', self.q.dependencies.status(claim)['state'])

    def test_the_enumerated_without_hit_record_cannot_be_read_as_a_pass(self):
        """The key must not smuggle a pass/fail boolean.

        `evaluated=8` says how many grid points were computed, nothing more.
        Any boolean named passed/verified/holds would let the next reader turn a
        survival into an endorsement the bridge is not entitled to give.
        """
        claim = self.accept(PASSES_EVERYWHERE)
        self.experiment(PARAMS)
        reading = self.q.knowledge.review_packet(claim)['bridge_checked_without_hit']
        self.assertEqual({'evaluated', 'receipt', 'receipt_at', 'epistemic_status'}, set(reading))
        self.assertEqual([], [k for k, v in reading.items() if isinstance(v, bool)])
        self.assertFalse([k for k in reading
                          if k in {'passed', 'verified', 'holds', 'satisfied', 'ok', 'survived', 'confirmed'}])

    def test_the_enumerated_without_hit_record_is_inside_the_digest(self):
        """A survival deletable between offer and apply is worse than none.

        `apply_review` trusts `packet['sha256']` alone, so the record must move it.
        """
        from dojo.anchors import packet_hash
        claim = self.accept(PASSES_EVERYWHERE)
        self.experiment(PARAMS)
        packet = self.q.knowledge.review_packet(claim)
        self.assertEqual(packet_hash(packet), packet['sha256'])
        stripped = {k: v for k, v in packet.items() if k not in {'sha256', 'bridge_checked_without_hit'}}
        self.assertNotEqual(packet_hash(stripped), packet['sha256'])

    def test_a_proposal_never_enumerated_gains_no_such_key(self):
        """A refused check is not a scored miss and must stay key-free.

        Otherwise 'the bridge could not score this' would be recorded as if the
        grid had been walked, which is the laundering this key exists to stop.
        """
        from dojo.anchors import packet_hash
        claim = self.accept(PASSES_EVERYWHERE)
        self.experiment(NEVER_ENUMERATED_GRID)
        checked = json.loads(self.q.db.execute(
            "SELECT payload FROM inquiry_events WHERE kind='falsifier_bridge_checked' ORDER BY seq DESC LIMIT 1").fetchone()[0])
        self.assertEqual('refused', checked['outcomes'][0]['status'])
        packet = self.q.knowledge.review_packet(claim)
        self.assertNotIn('bridge_checked_without_hit', packet)
        self.assertNotIn('bridge', packet)
        self.assertEqual(packet_hash(packet), packet['sha256'])

    def test_bridge_runs_through_the_real_experiment_entry(self):
        claim = self.accept(CHECK)
        action = {'kind': 'experiment', 'parameters': PARAMS, 'derived': DERIVED,
                  'assertion': 'to_second<=C', 'assumptions': ['容量固定'], 'prediction': 'p'}
        reflection = self.q.record('reflection', {'synthetic': True, 'reflection': {'answer': '测一下', 'action': action}})
        self.q.execute_action(action, reflection)
        self.assertEqual('needs_review', self.q.dependencies.status(claim)['state'])
        self.assertEqual(1, self.q.db.execute("SELECT count(*) FROM inquiry_events WHERE kind='falsifier_bridge_checked'").fetchone()[0])


    def test_superseded_receipt_can_no_longer_downgrade(self):
        """A hit is grounds for review only while its receipt still stands.

        The bridge read the receipt straight out of `inquiry_events` and never
        asked the dependency index whether that receipt had since been revised
        away, so a withdrawn observation could still downgrade a proposal.
        """
        claim = self.accept(CHECK)
        event = self.receipt(PARAMS, 'to_second<=C')
        replacement = self.q.record('reflection', {'text': '这次实验的输入被修正了。', 'synthetic': True})
        self.q.dependencies.revise(event, replacement, '输入口径修正')
        self.assertEqual('superseded', self.q.dependencies.status(event)['state'])
        outcome = receipt_hits(self.q.knowledge, self.q.run, event, synthetic=True)
        self.assertEqual('skipped', outcome['status'])
        self.assertEqual('receipt is superseded', outcome['reason'])
        self.assertEqual('current_interpretation', self.q.dependencies.status(claim)['state'])
        self.assertEqual(0, self.q.db.execute(
            "SELECT COUNT(*) FROM inquiry_events WHERE kind='falsifier_hit'").fetchone()[0])
        # Negative control in the same test: closing the whole path would also
        # pass the assertions above.
        live = self.receipt(PARAMS, 'to_second<=C')
        live_outcome = receipt_hits(self.q.knowledge, self.q.run, live, synthetic=True)
        self.assertEqual('checked', live_outcome['status'])
        self.assertEqual('needs_review', self.q.dependencies.status(claim)['state'])

    def test_packet_does_not_offer_a_hit_as_a_citable_anchor(self):
        """The packet used to publish an anchor on the hit event, but
        knowledge.py refuses `falsifier_hit` as a premise source kind, so that
        anchor could never be used: a visible promise with no way to keep it."""
        claim = self.accept(CHECK)
        event = self.receipt(PARAMS, 'to_second<=C')
        outcome = receipt_hits(self.q.knowledge, self.q.run, event, synthetic=True)
        hit_event = [o for o in outcome['outcomes'] if o['proposal'] == claim][0]['hit_event']
        packet = self.q.knowledge.review_packet(claim)
        self.assertNotIn(hit_event, [a['source_event'] for a in packet['anchors']])
        # The event must still be a source: review_context.causes reads it.
        self.assertIn(hit_event, [s['event'] for s in packet['sources']])
        self.assertTrue([c for c in self.q.knowledge.review_context(
            claim, self.q.dependencies.status(claim))['causes'] if c['event'] == hit_event])

class FalsifiabilityGateTests(unittest.TestCase):
    """A predicate that cannot fail anywhere is not a falsifier.

    r45 showed a tautology (1>0, to_second>=0) walks the whole bridge and
    produces hits == evaluated, indistinguishable from a real counterexample in
    the review packet. Nothing in the check contract asked the candidate for a
    point that would make its own predicate false, so a candidate could declare
    an unfalsifiable predicate and still be scored. The gate below makes that
    declaration required: the candidate names a grid point and the server
    evaluates it. No tautology can name one, so no tautology gets in -- not by
    pattern-matching the expression, but because the required evidence cannot
    be produced for it.
    """

    FAILING_POINT = {'N': 20, 'u': 5, 'C': 40}   # to_second = 1, so to_second>C is false
    HOLDING_POINT = {'N': 50, 'u': 60, 'C': 2}   # to_second = 30, so to_second>C is true

    def check(self, predicate, fails_at):
        base = {'parameters': PARAMS, 'derived': DERIVED, 'predicate': predicate}
        if fails_at is not None:
            base['predicate_fails_at'] = fails_at
        return base

    def test_a_tautology_can_no_longer_be_submitted(self):
        """1>0 holds at every grid point, so every declaration is refuted.

        This is the r45 finding turned into a refusal: before this gate the same
        input compiled and scored evaluated=8 hits=8.
        """
        with self.assertRaisesRegex(ValueError, 'declared_failure_point_does_not_falsify_predicate'):
            compile_check(self.check('1>0', self.FAILING_POINT), PROSE)
        with self.assertRaisesRegex(ValueError, 'declared_failure_point_does_not_falsify_predicate'):
            compile_check(self.check('to_second>=0', self.HOLDING_POINT), PROSE)

    def test_a_tautology_cannot_dodge_the_gate_by_omitting_the_point(self):
        """Including the key must not become optional with a default."""
        with self.assertRaisesRegex(ValueError, 'falsifier_check needs exactly'):
            compile_check(self.check('to_second>C', None), PROSE)

    def test_a_declared_point_where_the_predicate_holds_is_refused(self):
        """Claiming a failure point that does not fail is a false declaration."""
        with self.assertRaisesRegex(ValueError, 'declared_failure_point_does_not_falsify_predicate'):
            compile_check(self.check('to_second>C', self.HOLDING_POINT), PROSE)

    def test_a_failure_point_valued_outside_the_declared_grid_is_refused(self):
        """The witness must be a point the grid contains, else it is evidence
        about an experiment nobody declared."""
        with self.assertRaisesRegex(ValueError, 'failure_point_is_not_in_declared_grid'):
            compile_check(self.check('to_second>C', {'N': 21, 'u': 5, 'C': 40}), PROSE)

    def test_a_failure_point_with_other_parameter_names_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'failure_point_parameters_do_not_match_grid'):
            compile_check(self.check('to_second>C', {'N': 20, 'u': 5}), PROSE)
        with self.assertRaisesRegex(ValueError, 'failure_point_parameters_do_not_match_grid'):
            compile_check(self.check('to_second>C', {'N': 20, 'u': 5, 'C': 40, 'x': 1}), PROSE)

    def test_a_genuine_falsifier_still_passes_and_is_scored(self):
        """The gate must not cost a real candidate anything."""
        stored = compile_check(self.check('to_second>C', self.FAILING_POINT), PROSE)
        self.assertEqual({'falsifier_sha256', 'parameters', 'derived', 'predicate',
                          'predicate_fails_at'}, set(stored))
        self.assertEqual(self.FAILING_POINT, stored['predicate_fails_at'])
        # knowledge.py:31 writes this dict back, so re-compiling it must not raise.
        self.assertEqual(stored, compile_check(stored, PROSE))
        verdict = evaluate(stored, PARAMS, DERIVED, ASSERTION)
        self.assertEqual('evaluated', verdict['status'])
        self.assertEqual(3, verdict['hits'])

    def test_a_refused_tautology_never_becomes_a_hit(self):
        """Same input as r45's end-to-end case: it must now fail at submission,
        before any receipt can be scored against it."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            q = Inquiry(Path(tmp) / 'db', Client(), synthetic=True)
            try:
                u = q.record('user', {'text': '没人再问我了', 'synthetic': True})
                with self.assertRaisesRegex(ValueError,
                                            'declared_failure_point_does_not_falsify_predicate'):
                    q.knowledge.accept(q.run, proposal(PROSE, self.check('1>0', self.FAILING_POINT)), {u},
                                       synthetic=True)
            finally:
                q.close()


class DiscriminationGateTests(unittest.TestCase):
    """r62: an experiment that failed at every point it searched cannot refute.

    A receipt whose own assertion never held anywhere is not evidence against a
    candidate, because every grid point where the candidate's predicate holds is
    also a point where the receipt's claim already failed. Before r62 such a
    receipt produced `needs_review` with hits > 0: the candidate was downgraded by
    an experiment that discriminated nothing. The narrow gate refuses exactly
    that shape and leaves the `not_hit` record (candidate never holds) alone.

    Every case here drives `execute_action`, which is the only production entry
    that writes `falsifier_bridge_checked`, and then reads the stored outcome.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.q = Inquiry(Path(self.tmp.name) / 'db', Client(), synthetic=True)
        self.u = self.q.record('user', {'text': '没人再问我了', 'synthetic': True})

    def tearDown(self):
        self.q.close()
        self.tmp.cleanup()

    def accept(self, check):
        p = proposal(PROSE, check)
        p['premises'] = [{'event': self.u, 'quote': '没人再问我了', 'role': 'assumption'}]
        return self.q.knowledge.accept(self.q.run, p, {self.u}, synthetic=True)

    def experiment(self, parameters, assertion='to_second<=C'):
        action = {'kind': 'experiment', 'parameters': parameters, 'derived': DERIVED,
                  'assertion': assertion, 'assumptions': ['容量固定'], 'prediction': 'p'}
        reflection = self.q.record('reflection', {'synthetic': True,
                                                  'reflection': {'answer': '测一下', 'action': action}})
        return self.q.execute_action(action, reflection)[0]

    def outcome_for(self, claim):
        checked = json.loads(self.q.db.execute(
            "SELECT payload FROM inquiry_events WHERE kind='falsifier_bridge_checked' "
            "ORDER BY seq DESC LIMIT 1").fetchone()[0])
        return [o for o in checked['outcomes'] if o['proposal'] == claim][0]

    def test_a_receipt_that_failed_everywhere_cannot_downgrade(self):
        claim = self.accept(CHECK)
        # to_second>1000 never holds on PARAMS: 0 passed points out of 8. The
        # candidate predicate to_second>C holds at 3 of them, so every one of its
        # 'hits' is a point the receipt already called false.
        self.experiment(PARAMS, 'to_second>1000')
        reading = self.outcome_for(claim)
        self.assertEqual('refused', reading['status'])
        self.assertEqual('receipt_assertion_never_held_on_its_own_grid', reading['reason'])
        self.assertEqual(0, reading['receipt_passed'])
        # A refusal is not a downgrade: the proposal is exactly where it was.
        self.assertEqual('current_interpretation', self.q.dependencies.status(claim)['state'])
        self.assertEqual(0, self.q.db.execute(
            "SELECT COUNT(*) FROM inquiry_events WHERE kind='falsifier_hit'").fetchone()[0])

    def test_a_discriminating_receipt_still_downgrades(self):
        """Negative control: closing the whole hit path would also pass the test
        above. This receipt passes 5 of 8 points, so its 3 failures mean something."""
        claim = self.accept(CHECK)
        self.experiment(PARAMS, 'to_second<=C')
        reading = self.outcome_for(claim)
        self.assertEqual('needs_review', reading['status'])
        self.assertEqual(3, reading['hits'])
        self.assertEqual(5, reading['receipt_passed'])
        self.assertEqual('needs_review', self.q.dependencies.status(claim)['state'])

    def test_a_candidate_that_never_holds_keeps_its_not_hit_record(self):
        """The r37 record must survive r62: a candidate that misses everywhere was
        still enumerated, and 'enumerated and missed' is not 'refused'."""
        claim = self.accept(PASSES_EVERYWHERE)
        self.experiment(PARAMS, 'to_second>1000')
        self.assertEqual('not_hit', self.outcome_for(claim)['status'])
        packet = self.q.knowledge.review_packet(claim)
        self.assertIn('bridge_checked_without_hit', packet)
        self.assertNotIn('bridge_refused', packet)
        self.assertEqual('current_interpretation', self.q.dependencies.status(claim)['state'])

    def test_the_hit_record_reports_how_discriminating_its_experiment_was(self):
        """r62 R3: `hits` alone cannot distinguish a refutation from a coincidence."""
        claim = self.accept(CHECK)
        self.experiment(PARAMS, 'to_second<=C')
        bridge = self.q.knowledge.review_packet(claim)['bridge']
        self.assertEqual(5, bridge['receipt_passed'])
        self.assertEqual(3, bridge['hits'])
        # And it must not be readable as a verdict on the claim.
        self.assertFalse([k for k in bridge if k in {'passed', 'verified', 'holds', 'confirmed'}])

    def test_a_row_stored_before_r62_keeps_the_old_packet_shape(self):
        """R3 adds a key only when the stored reading carries it. Otherwise every
        already-bridged packet would change digest and re-open old reviews."""
        from dojo.anchors import packet_hash
        claim = self.accept(CHECK)
        self.experiment(PARAMS, 'to_second<=C')
        self.assertIn('receipt_passed', self.q.knowledge.review_packet(claim)['bridge'])
        row = self.q.db.execute(
            "SELECT seq,payload FROM inquiry_events WHERE kind='falsifier_hit' "
            "ORDER BY seq DESC LIMIT 1").fetchone()
        data = json.loads(row[1])
        data.pop('receipt_passed', None)
        with self.q.db:
            self.q.db.execute('UPDATE inquiry_events SET payload=? WHERE seq=?',
                              (json.dumps(data, ensure_ascii=False), row[0]))
        packet = self.q.knowledge.review_packet(claim)
        self.assertNotIn('receipt_passed', packet['bridge'])
        self.assertEqual(packet_hash(packet), packet['sha256'])


class RefusedVisibilityTests(unittest.TestCase):
    """r62 R1: 'the bridge computed this and refused it' must be visible.

    r60 measured that a refused candidate and a candidate that never crossed the
    bridge produced packets with the same key set, and that deleting the very
    event which refused a candidate left its packet byte-identical. The reviewer
    asked to judge the target could not tell the two apart.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.q = Inquiry(Path(self.tmp.name) / 'db', Client(), synthetic=True)
        self.u = self.q.record('user', {'text': '没人再问我了', 'synthetic': True})

    def tearDown(self):
        self.q.close()
        self.tmp.cleanup()

    def accept(self, check):
        p = proposal(PROSE, check)
        p['premises'] = [{'event': self.u, 'quote': '没人再问我了', 'role': 'assumption'}]
        return self.q.knowledge.accept(self.q.run, p, {self.u}, synthetic=True)

    def experiment(self, parameters, assertion='to_second<=C'):
        action = {'kind': 'experiment', 'parameters': parameters, 'derived': DERIVED,
                  'assertion': assertion, 'assumptions': ['容量固定'], 'prediction': 'p'}
        reflection = self.q.record('reflection', {'synthetic': True,
                                                  'reflection': {'answer': '测一下', 'action': action}})
        return self.q.execute_action(action, reflection)[0]

    def test_a_refused_candidate_is_visible_with_a_named_reason(self):
        claim = self.accept(CHECK)
        self.assertNotIn('bridge_refused', self.q.knowledge.review_packet(claim))
        receipt = self.experiment(NEVER_ENUMERATED_GRID)
        reading = self.q.knowledge.review_packet(claim)['bridge_refused']
        self.assertEqual({'receipt', 'receipt_at', 'reason', 'detail', 'epistemic_status'}, set(reading))
        self.assertEqual(receipt, reading['receipt'])
        self.assertEqual('parameter_values_do_not_match_receipt_domain', reading['reason'])
        self.assertEqual('finite_computation_under_stated_model_not_truth_verdict',
                         reading['epistemic_status'])
        # A refusal is a record, not a decision: state must not move.
        self.assertEqual('current_interpretation', self.q.dependencies.status(claim)['state'])

    def test_a_refused_record_cannot_be_read_as_a_verdict(self):
        claim = self.accept(CHECK)
        self.experiment(NEVER_ENUMERATED_GRID)
        reading = self.q.knowledge.review_packet(claim)['bridge_refused']
        self.assertEqual([], [k for k, v in reading.items() if isinstance(v, bool)])
        self.assertFalse([k for k in reading
                          if k in {'passed', 'verified', 'holds', 'satisfied', 'ok', 'survived', 'confirmed'}])

    def test_a_proposal_never_bridged_keeps_the_legacy_packet(self):
        """The key must appear only for a candidate the bridge actually refused,
        never as an empty placeholder: that would change every stored digest."""
        from dojo.anchors import packet_hash
        claim = self.accept(CHECK)
        packet = self.q.knowledge.review_packet(claim)
        self.assertEqual({'target', 'proposal', 'dependency_status', 'sources',
                          'source_expansion_truncated', 'truth', 'citation_contract',
                          'anchors', 'sha256'}, set(packet))
        self.assertEqual(packet_hash(packet), packet['sha256'])

    def test_the_refused_record_is_inside_the_digest(self):
        """A record that can be dropped between offer and apply is worse than none."""
        from dojo.anchors import packet_hash
        claim = self.accept(CHECK)
        self.experiment(NEVER_ENUMERATED_GRID)
        packet = self.q.knowledge.review_packet(claim)
        stripped = {k: v for k, v in packet.items() if k not in {'sha256', 'bridge_refused'}}
        self.assertNotEqual(packet_hash(stripped), packet['sha256'])

    def test_the_discrimination_refusal_is_also_visible(self):
        """R2 and R1 must agree: the new refusal reason reaches the reader too."""
        claim = self.accept(CHECK)
        self.experiment(PARAMS, 'to_second>1000')
        reading = self.q.knowledge.review_packet(claim)['bridge_refused']
        self.assertEqual('receipt_assertion_never_held_on_its_own_grid', reading['reason'])
        self.assertEqual('current_interpretation', self.q.dependencies.status(claim)['state'])


if __name__ == '__main__':
    unittest.main()
