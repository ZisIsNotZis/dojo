import tempfile
import unittest
from pathlib import Path

from dojo.inquiry import Inquiry
from tests.test_knowledge import Client, proposal


U1 = '交接这件事值不值得自动化'
# ASCII markers so the byte-level assertions cannot be satisfied by an
# unrelated Chinese token happening to appear in a rendered packet.
P_ASSUMPTION = 'ASSMVP-MARKER 维护成本计'
P_FALSIFIER = 'P_FALSIFIER-MARKER'
R_ASSUMPTION = 'RSMVP-MARKER 一次性设置成本计入本期'
R_FALSIFIER = 'R_FALSIFIER-MARKER'


class CounterexampleReuseTests(unittest.TestCase):
    """A withdrawn proposition stays reviewable without entering the next prompt.

    Each reasoning state gets its own Inquiry so that prompt_context runs on a
    first, unsent catalog (inquiry.py:299-303 dedupes already-sent source
    hashes, which made an earlier probe read zeroes).
    """

    def setUp(self):
        # sqlite files stay open until GC on Windows; let the OS reap them.
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)

    def tearDown(self):
        self.tmp.cleanup()

    def inquiry(self, name):
        q = Inquiry(Path(self.tmp.name) / (name + '.sqlite3'), Client(), synthetic=True)
        self.addCleanup(q.close)
        return q

    def build(self, name, state):
        q = self.inquiry(name)
        u1 = q.record('user', {'text': U1, 'synthetic': True})
        p = proposal('交接可以自动完成', u1, '值不值得自动化')
        p['assumptions'] = [P_ASSUMPTION]
        p['falsifier'] = P_FALSIFIER
        p_event = q.knowledge.accept(q.run, p, {u1}, synthetic=True)
        r_event = None
        if state in ('S2', 'S3'):
            revises = p_event if state == 'S2' else None
            allowed = {u1, p_event} if revises is not None else {u1}
            r = proposal('交接不能自动完成', u1, '值不值得自动化', revises=revises)
            r['assumptions'] = [R_ASSUMPTION]
            r['falsifier'] = R_FALSIFIER
            r_event = q.knowledge.accept(q.run, r, allowed, synthetic=True)
        return q, u1, p_event, r_event

    def prompt(self, q, text):
        prior = q.retrieve(text)
        prior_knowledge = q.retrieve_knowledge(text)
        user_event = q.record('user', {'text': text, 'synthetic': True})
        return q.prompt_context(text, user_event, prior, prior_knowledge, q.question_context())

    def test_superseded_target_is_not_retrieved_but_its_revision_is(self):
        q, u1, p_event, r_event = self.build('s2', 'S2')
        self.assertEqual('superseded', q.knowledge.dependencies.status(p_event)['state'])
        events = [m['event'] for m in q.retrieve_knowledge(U1)]
        self.assertEqual([r_event], events)

    def test_both_current_puts_revision_first(self):
        q, u1, p_event, r_event = self.build('s3', 'S3')
        matches = q.retrieve_knowledge(U1)
        self.assertEqual([r_event, p_event], [m['event'] for m in matches])
        # Equal core hits, so only the newest-first order separates the two:
        # this is a tie-break, not evidence that R is a stronger match.
        self.assertEqual(matches[0]['core_hit_terms'], matches[1]['core_hit_terms'])

    def test_withdrawn_proposition_bytes_never_reach_the_prompt(self):
        q, u1, p_event, r_event = self.build('s2_prompt', 'S2')
        spec = self.prompt(q, U1)
        whole = str(spec)
        for marker in (P_ASSUMPTION, P_FALSIFIER):
            self.assertNotIn(marker, whole)
            self.assertNotIn(marker, str(spec['knowledge_proposals']))
        # The revision's own assumptions, by contrast, are visible:
        self.assertIn(R_ASSUMPTION, str(spec['source_catalog']))

    def test_proposals_channel_never_carries_assumptions(self):
        q, u1, p_event, r_event = self.build('s3_prompt', 'S3')
        spec = self.prompt(q, U1)
        rendered = str(spec['knowledge_proposals'])
        for marker in (P_ASSUMPTION, R_ASSUMPTION, P_FALSIFIER, R_FALSIFIER):
            self.assertNotIn(marker, rendered)

    def test_review_packet_of_withdrawn_proposition_keeps_only_its_own_source(self):
        q, u1, p_event, r_event = self.build('s2_packet', 'S2')
        packet = q.knowledge.review_packet(p_event)
        self.assertEqual([u1], [s['event'] for s in packet['sources']])
        self.assertNotIn(R_ASSUMPTION, str(packet))

    def test_assumption_only_query_recalls_without_claiming_the_claim(self):
        q, u1, p_event, r_event = self.build('s1_query', 'S1')
        matches = q.retrieve_knowledge('维护')
        self.assertEqual([p_event], [m['event'] for m in matches])
        self.assertEqual(['维护'], matches[0]['hit_terms'])
        self.assertEqual([], matches[0]['core_hit_terms'])
        self.assertNotIn('维护', matches[0]['proposal']['statement'])


if __name__ == '__main__':
    unittest.main()
