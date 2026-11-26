import json
from pathlib import Path
import tempfile
import unittest

from dojo.inquiry import Inquiry
from tests.test_knowledge import Client, proposal


class ReadReviewContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.q=Inquiry(Path(self.tmp.name)/'db',Client(),synthetic=True)
        self.user=self.q.record('user',{'text':'Only time matters; six reports','synthetic':True})
        self.old=self.q.record('tool_result',{'status':'executed','result':{'value':48}})
        self.base=self.q.knowledge.accept(self.q.run,proposal('Old parameters save 48 minutes',self.old,'"value": 48'),{self.old},synthetic=True)
        self.child=self.q.knowledge.accept(self.q.run,proposal('Automation is beneficial under the old parameters',self.base,'parameters save 48'),{self.base},synthetic=True)
        self.other=self.q.knowledge.accept(self.q.run,proposal('Unrelated control claim',self.old,'"value": 48'),{self.old},synthetic=True)
        self.new_user=self.q.record('user',{'text':'Setup now takes 100 minutes','synthetic':True})
        self.new=self.q.record('tool_result',{'action':{'kind':'calculate','basis':'INPUT_ONLY_SENTINEL'},'status':'executed','result':{'value':-52,'basis':'INPUT_ONLY_SENTINEL'}})
        self.q.knowledge.request_review(self.q.run,self.base,[self.new_user,self.new],'Changed setup requires applicability review',{self.base,self.new_user,self.new},synthetic=True)

    def tearDown(self):
        self.q.close();self.tmp.cleanup()

    def test_transitive_pending_claim_explains_the_new_signal_without_rewriting_text(self):
        old=self.q.db.execute('SELECT seq,payload FROM inquiry_events').fetchall()
        source=self.q.knowledge.source(self.child)
        self.assertEqual('needs_review',source['dependency_status']['state'])
        self.assertEqual('Automation is beneficial under the old parameters',source['text'])
        context=source['review_context']
        self.assertIn('-52',str(context));self.assertIn('100 minutes',str(context))
        self.assertNotIn('INPUT_ONLY_SENTINEL',str(context))
        self.assertEqual(self.base,context['requests'][0]['target'])
        self.assertEqual('agent_review_request_not_truth_verdict',context['requests'][0]['epistemic_status'])
        listed=next(p for p in self.q.knowledge.proposals(synthetic=True) if p['event']==self.child)
        self.assertEqual(context,listed['review_context'])
        self.assertEqual(old,self.q.db.execute('SELECT seq,payload FROM inquiry_events').fetchall())
        with self.assertRaisesRegex(ValueError,'premise quote mismatch'):
            self.q.knowledge.check(proposal('Do not launder the summary as claim evidence',self.child,'-52'),{self.child},synthetic=True)

    def test_other_targets_reason_does_not_leak_through_a_shared_cause(self):
        self.q.knowledge.request_review(self.q.run,self.other,[self.new],'UNRELATED_REASON',{self.other,self.new},synthetic=True)
        self.assertNotIn('UNRELATED_REASON',str(self.q.knowledge.source(self.child)['review_context']))
        self.assertIn('UNRELATED_REASON',str(self.q.knowledge.source(self.other)['review_context']))

    def test_replacement_excerpt_shows_the_change_instead_of_only_an_id(self):
        p=proposal('Updated parameters lose 52 minutes',self.new,'"value": -52',revises=self.base)
        replacement=self.q.knowledge.accept(self.q.run,p,{self.new,self.base},synthetic=True)
        context=self.q.knowledge.source(self.child)['review_context']
        changed=next(c for c in context['causes'] if c['event']==self.base)
        self.assertEqual(replacement,changed['replacement']['event'])
        self.assertEqual('Updated parameters lose 52 minutes',changed['replacement']['excerpt'])
        self.assertEqual('model_proposal_not_certified',changed['replacement']['epistemic_status'])

    def test_summary_bounds_and_unchallenged_control(self):
        for i in range(6):
            e=self.q.record('user',{'text':'New signal '+str(i),'synthetic':True})
            self.q.knowledge.request_review(self.q.run,self.base,[e],'Additional review signal',{self.base,e},synthetic=True)
        context=self.q.knowledge.source(self.child)['review_context']
        self.assertEqual(4,len(context['causes']));self.assertEqual(4,context['causes_omitted'])
        self.assertLessEqual(len(context['requests']),3)
        self.assertNotIn('review_context',self.q.knowledge.source(self.other))

    def test_nested_review_reports_keep_their_story_attribution(self):
        other=Inquiry(Path(self.tmp.name)/'db',Client(),synthetic=True)
        try:
            shown=other.scoped_sources([self.q.knowledge.source(self.child)])[0]
            cause=next(c for c in shown['review_context']['causes'] if c['event']==self.new_user)
            self.assertEqual('other_story',cause['story_scope'])
            self.assertEqual('historical_report_not_current_user_testimony',cause['attribution'])
            self.assertEqual(self.q.story,cause['origin_story'])
        finally:other.close()

    def test_failed_tool_signal_is_not_labeled_a_positive_computation(self):
        failed=self.q.record('tool_result',{'action':{'kind':'calculate','basis':'INPUT_ONLY_SENTINEL'},'status':'failed','error_kind':'timeout'})
        self.q.knowledge.request_review(self.q.run,self.base,[failed],'A failed verification is another signal',{self.base,failed},synthetic=True)
        cause=next(c for c in self.q.knowledge.source(self.child)['review_context']['causes'] if c['event']==failed)
        self.assertEqual('tool_failure_not_positive_evidence',cause['epistemic_status'])
        self.assertIn('timeout',cause['excerpt']);self.assertNotIn('INPUT_ONLY_SENTINEL',cause['excerpt'])

    def test_resume_warns_about_pending_knowledge_without_requiring_search_terms(self):
        resumed=Inquiry(Path(self.tmp.name)/'db',Client(),synthetic=True,story=self.q.story)
        try:
            payload=json.loads(resumed.messages[-1]['content'].split('\n',1)[1])
            pending=payload['pending_knowledge']
            self.assertTrue(pending['preview_only']);self.assertFalse(pending['more_pending'])
            self.assertEqual({self.base,self.child},{p['event'] for p in pending['items']})
            self.assertIn('-52',str(pending))
            self.assertNotIn(self.child,resumed.visible_source_text)
            self.assertEqual('needs_review',next(p for p in pending['items'] if p['event']==self.child)['dependency_status']['state'])
        finally:resumed.close()

    def test_pending_filter_precedes_output_limit_and_reports_more(self):
        for i in range(8):
            self.q.knowledge.accept(self.q.run,proposal('Unchallenged later result '+str(i),self.old,'"value": 48'),{self.old},synthetic=True)
        pending=self.q.knowledge.pending_for_runs([self.q.run],limit=1)
        self.assertEqual(self.child,pending['items'][0]['event']);self.assertTrue(pending['more_pending'])


if __name__=='__main__':
    unittest.main()
