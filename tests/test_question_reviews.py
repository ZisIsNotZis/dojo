import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from dojo.inquiry import Inquiry
from dojo.question_reviews import apply_review,candidates,perform_rechecks,review_packet


class QuestionReviewTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory()
  self.q=Inquiry(Path(self.tmp.name)/'db',SimpleNamespace(config=SimpleNamespace(model='deepseek-flash',api_key=None)),synthetic=True)
  self.user=self.q.record('user',{'text':'Reuse decisions with stated conditions','synthetic':True})
  self.q.user_sources[self.user]='Reuse decisions with stated conditions'
  self.show(self.user)
  proposal={'statement':'Raw sentences may suffice','kind':'causal','method':'hypothesis','premises':[{'event':self.user,'quote':'Reuse decisions','role':'evidence'}],'assumptions':['reader has context'],'conditions':['handoff'],'alternatives':['preserve conditions'],'falsifier':'reader misses conditions','revises':None}
  self.claim=self.q.knowledge.accept(self.q.run,proposal,{self.user},synthetic=True);self.show(self.claim)
  self.source=self.q.record('tool_result',{'status':'executed','result':{'accuracy':'not_measured','matches':1}});self.show(self.source)
  result=self.q.questions.apply(self.q,{'kind':'map_inquiry','questions':[{'key':'root','text':'What must a handoff retain?','parents':[],'origin_event':self.user,'origin_quote':'Reuse decisions','revises':None}],'links':[{'question':'root','proposition':self.claim,'source_event':self.source,'quote':'not_measured','relation':'challenges','explanation':'Literal matches do not measure accuracy'}],'prediction':'Organize uncertainties'})
  self.node=result['question_keys']['root'];self.show(self.node)
  self.target=result['graph']['nodes'][0]['annotations'][0]['event']
  self.new=self.q.record('tool_result',{'status':'executed','result':{'accuracy':'still_not_measured','matches':0}})
  self.q.dependencies.revise(self.source,self.new,'Corrected observation')
 def tearDown(self):self.q.close();self.tmp.cleanup()
 def show(self,event):self.q.visible_source_text[event]=self.q.knowledge.source(event)['text']
 def review(self,kind='retain',**changes):
  link={'question':self.node,'proposition':self.claim,'source_event':self.new,'quote':'still_not_measured','relation':'challenges','explanation':'New observation still does not test semantic accuracy',**changes}
  return {'disposition':kind,'reason':'Only literal counts changed; semantic accuracy remains unknown','replacement':link if kind in {'retain','replace'} else None}
 def view(self):return self.q.questions.view(story=self.q.story,synthetic=True)['nodes'][0]
 def test_retain_rebuilds_current_relation_preserves_history_and_clears_review(self):
  self.assertTrue(self.view()['review_needed_in_visible_subgraph'])
  result=apply_review(self.q,review_packet(self.q,self.target),self.review())
  node=self.view();self.assertFalse(node['review_needed_in_visible_subgraph'])
  self.assertEqual([self.target],[a['event'] for a in node['annotation_history']])
  self.assertEqual(self.new,node['annotations'][0]['source_event'])
  self.assertFalse(self.q.dependencies.depends_on(result['replacement_event'],self.target))
  self.assertEqual([],list(candidates(self.q)))
 def test_withdraw_does_not_withdraw_question_or_claim(self):
  apply_review(self.q,review_packet(self.q,self.target),self.review('withdraw'))
  node=self.view();self.assertEqual([],node['annotations']);self.assertFalse(node['review_needed_in_visible_subgraph'])
  self.assertEqual('current_interpretation',self.q.dependencies.status(self.claim)['state'])
  self.assertEqual('current_interpretation',self.q.dependencies.status(self.node)['state'])
 def test_unresolved_is_not_retried_until_packet_changes(self):
  client=SimpleNamespace(complete=lambda messages:self.review('unresolved'))
  self.assertEqual(1,perform_rechecks(self.q,client,max_requests=3)['requests_used'])
  self.assertEqual(0,perform_rechecks(self.q,client,max_requests=3)['requests_used'])
  self.assertTrue(self.view()['review_needed_in_visible_subgraph'])
  later=self.q.record('tool_result',{'status':'executed','result':{'accuracy':'not_measured','matches':2}})
  self.q.dependencies.revise(self.new,later,'Another corrected observation')
  self.assertEqual(1,len(list(candidates(self.q))))
 def test_changed_packet_discards_model_response(self):
  packet=review_packet(self.q,self.target)
  later=self.q.record('tool_result',{'status':'executed','result':{'matches':3}})
  self.q.dependencies.revise(self.new,later,'Changed while reviewing')
  self.assertEqual('discarded',apply_review(self.q,packet,self.review())['status'])
  self.assertEqual('needs_review',self.q.dependencies.status(self.target)['state'])
 def test_retain_cannot_change_candidate_or_relation_and_stale_source_rejected_atomically(self):
  for review in (self.review(relation='supports'),self.review(source_event=self.source,quote='not_measured'),self.review('replace',source_event=self.claim,quote='Raw sentences')):
   before=self.q.db.execute('SELECT count(*) FROM inquiry_events').fetchone()[0]
   with self.assertRaises(ValueError):apply_review(self.q,review_packet(self.q,self.target),review)
   self.assertEqual(before,self.q.db.execute('SELECT count(*) FROM inquiry_events').fetchone()[0])
 def test_zero_budget_and_failure_do_not_buy_retries(self):
  calls=[]
  def bad(messages):calls.append(messages);return {'bad':'schema'}
  client=SimpleNamespace(complete=bad)
  self.assertEqual(0,perform_rechecks(self.q,client,max_requests=0)['requests_used'])
  before=self.q.requests
  self.assertEqual('failed',perform_rechecks(self.q,client,max_requests=3)['outcomes'][0]['status'])
  self.assertEqual(before-1,self.q.requests)
  self.assertEqual(0,perform_rechecks(self.q,client,max_requests=3)['requests_used']);self.assertEqual(1,len(calls))
 def test_replacement_cannot_move_to_new_frame(self):
  other=self.q.record('user',{'text':'New goal','synthetic':True});self.show(other);self.q.user_sources[other]='New goal'
  self.q.questions.apply(self.q,{'kind':'map_inquiry','questions':[{'key':'new','text':'A different goal?','parents':[],'origin_event':other,'origin_quote':'New goal','revises':self.node}],'links':[],'prediction':'Explicit reframe'})
  with self.assertRaises(ValueError):apply_review(self.q,review_packet(self.q,self.target),self.review())
  self.assertEqual('needs_review',self.q.dependencies.status(self.target)['state'])
 def test_maintenance_uses_shared_budget_and_excludes_history_from_chat(self):
  client=SimpleNamespace(complete=lambda messages:self.review())
  before=self.q.requests
  result=self.q.maintain(None,question_review_client=client,max_requests=1)
  self.assertEqual(1,result['requests_used']);self.assertEqual(before-1,self.q.requests)
  context=self.q.question_context();self.assertNotIn('annotation_history',context['nodes'][0])
  self.assertEqual(self.new,context['nodes'][0]['annotations'][0]['source_event'])

if __name__=='__main__':unittest.main()
