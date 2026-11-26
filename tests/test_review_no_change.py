import copy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from dojo.inquiry import Inquiry
from dojo.reviews import apply_review, perform_rechecks
from tests.test_knowledge import proposal


class NoChangeReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.q=Inquiry(Path(self.tmp.name)/'db',SimpleNamespace(config=SimpleNamespace(model='deepseek-flash',api_key=None)),synthetic=True)
        self.user=self.q.record('user',{'text':'alpha condition beta','synthetic':True})
        original=proposal('Unchanged conditional conclusion',self.user,'alpha condition')
        original['premises'].append({'event':self.user,'quote':'condition beta','role':'assumption'})
        self.target=self.q.knowledge.accept(self.q.run,original,{self.user},synthetic=True)
        self.child=self.q.knowledge.accept(self.q.run,proposal('Dependent conclusion',self.target,'conditional'),{self.target},synthetic=True)
        self.evidence=self.q.record('tool_result',{'status':'executed','result':{'value':1}})
        self.notice(self.evidence)
        self.q.dependencies.drain(100)

    def tearDown(self):
        self.q.close();self.tmp.cleanup()

    def notice(self,event):
        self.q.knowledge.request_review(self.q.run,self.target,[event],'New material to assess, not automatic refutation',{self.target,event},synthetic=True)

    def review(self,disposition='replace'):
        value=copy.deepcopy(self.q.knowledge.source(self.target)['proposal'])
        value['revises']=self.target
        value['premises'].reverse()
        return {'disposition':disposition,'reason':'The new observation does not change this conditional conclusion.','replacement':value}

    def graph_state(self):
        return {name:self.q.db.execute('SELECT count(*) FROM '+name).fetchone()[0] for name in ('inquiry_revisions','inquiry_dependencies','inquiry_review_queue')}

    def test_pointer_and_citation_order_do_not_create_a_version_or_new_propagation(self):
        before=self.graph_state()
        raw=self.q.knowledge.source(self.target)['text']
        count=self.q.db.execute("SELECT count(*) FROM inquiry_events WHERE kind='knowledge_proposal'").fetchone()[0]
        result=apply_review(self.q,self.q.knowledge.review_packet(self.target),self.review())
        self.assertEqual('unresolved',result['disposition'])
        self.assertTrue(result['unchanged_content'])
        self.assertEqual('replace',result['requested_disposition'])
        self.assertIsNone(result['replacement_event'])
        self.assertEqual(before,self.graph_state())
        self.assertEqual(count,self.q.db.execute("SELECT count(*) FROM inquiry_events WHERE kind='knowledge_proposal'").fetchone()[0])
        self.assertEqual(raw,self.q.knowledge.source(self.target)['text'])
        self.assertEqual('needs_review',self.q.dependencies.status(self.target)['state'])
        self.assertEqual('needs_review',self.q.dependencies.status(self.child)['state'])

    def test_repeated_citation_is_not_new_evidence_and_same_packet_is_not_retried(self):
        response=self.review('retain')
        response['replacement']['premises'].append(copy.deepcopy(response['replacement']['premises'][0]))
        calls=[]
        def complete(messages):
            calls.append(messages)
            return response
        first=perform_rechecks(self.q,SimpleNamespace(complete=complete),max_requests=1)
        self.assertTrue(first['outcomes'][0]['unchanged_content'])
        self.assertEqual('retain',first['outcomes'][0]['requested_disposition'])
        self.assertNotIn(self.target,[p['target'] for p in self.q.knowledge.review_candidates(synthetic=True,limit=10)])
        self.assertEqual(1,len(calls))
        fresh=self.q.record('tool_result',{'status':'executed','result':{'value':2}})
        self.notice(fresh)
        self.assertIn(self.target,[p['target'] for p in self.q.knowledge.review_candidates(synthetic=True,limit=10)])

    def assert_real_change(self,response):
        result=apply_review(self.q,self.q.knowledge.review_packet(self.target),response)
        self.assertIsNotNone(result['replacement_event'])
        self.assertNotIn('unchanged_content',result)
        self.assertEqual('superseded',self.q.dependencies.status(self.target)['state'])

    def test_new_evidence_still_creates_a_real_revision(self):
        response=self.review('retain')
        response['replacement']['premises'].append({'event':self.evidence,'quote':'"value": 1','role':'evidence'})
        self.assert_real_change(response)

    def test_new_conditions_still_create_a_real_revision(self):
        response=self.review('retain')
        response['replacement']['conditions'].append('Only in the supplied domain')
        self.assert_real_change(response)

    def test_changed_premise_role_still_creates_a_real_revision(self):
        response=self.review('retain')
        response['replacement']['premises'][0]['role']='value'
        self.assert_real_change(response)

    def test_no_change_comparison_does_not_bypass_source_validation(self):
        response=self.review()
        response['replacement']['premises'][0]['quote']='unseen source fragment'
        before=self.graph_state()
        with self.assertRaises(ValueError):apply_review(self.q,self.q.knowledge.review_packet(self.target),response)
        self.assertEqual(before,self.graph_state())


if __name__=='__main__':unittest.main()
