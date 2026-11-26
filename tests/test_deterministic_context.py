import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from dojo.inquiry import Inquiry
from dojo.deterministic import revalidate_context
from tests.test_knowledge import proposal


class DeterministicContextTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'db'
  self.host=SimpleNamespace(config=SimpleNamespace(model='deepseek-flash',api_key=None))
  self.q=Inquiry(self.path,self.host,synthetic=True)
  self.user=self.q.record('user',{'text':'Check a fixed calculation under assumptions','synthetic':True})
  self.old=self.q.knowledge.accept(self.q.run,proposal('A hypothesis to test',self.user,'fixed calculation'),{self.user},synthetic=True)
  self.action={'kind':'calculate','expression':'0.3/2','basis':'Model explanation, not observed proof','prediction':'Expect 0.15'}
 def tearDown(self):self.q.close();self.tmp.cleanup()
 def receipt(self,*,legacy=False,value=0.15):
  plan=self.q.record('reflection',{'reflection':{'answer':'Plan a test','action':self.action}});self.q.dependencies.link(plan,[self.old])
  if legacy:
   event=self.q.record('tool_result',{'action':self.action,'status':'executed','result':{'value':value,'basis':self.action['basis'],'scope':'仅给定假设下算术，非现实验证'}})
   self.q.dependencies.link(event,[plan])
  else:event,_,_=self.q.execute_action(self.action,plan)
  return event,plan
 def revise_old(self):
  return self.q.knowledge.accept(self.q.run,proposal('Revised hypothesis',self.user,'fixed calculation',revises=self.old),{self.user,self.old},synthetic=True)
 def test_new_numeric_observation_keeps_provenance_without_narrative_invalidation(self):
  event,plan=self.receipt();new=self.revise_old();self.q.dependencies.drain(100)
  self.assertTrue(self.q.dependencies.depends_on(event,self.old))
  self.assertFalse(self.q.dependencies.depends_on(event,self.old,include_execution_context=False))
  self.assertEqual('current_interpretation',self.q.dependencies.status(event)['state'])
  self.assertEqual('execution_context',self.q.db.execute('SELECT relation FROM inquiry_dependencies WHERE conclusion=? AND premise=?',(event,plan)).fetchone()[0])
  derived=self.q.knowledge.accept(self.q.run,proposal('Only this number was calculated',event,'"value": 0.15'),{event},synthetic=True)
  replacement=self.q.record('tool_result',{'status':'executed','result':{'value':0.2}})
  self.q.dependencies.revise(event,replacement,'Actual observation corrected')
  self.assertEqual('needs_review',self.q.dependencies.status(derived)['state'])
 def test_independent_computation_can_test_and_revise_a_hypothesis_but_text_cannot(self):
  event,plan=self.receipt()
  p=proposal('Conditional result differs',event,'"value": 0.15',revises=self.old)
  new=self.q.knowledge.accept(self.q.run,p,{event,self.old},synthetic=True)
  self.assertEqual('current_interpretation',self.q.dependencies.status(new)['state'])
  self.assertTrue(self.q.dependencies.depends_on(new,self.old))
  # Historical provenance survives; it is not a logical echo across the CPU run.
  raw=self.q.record('reflection',{'reflection':{'answer':'Repetition of current claim'}});self.q.dependencies.link(raw,[new])
  bad=proposal('Text rewrite alone',raw,'Repetition',revises=new);bad['premises'][0]['role']='assumption'
  with self.assertRaisesRegex(ValueError,'depends on old'):self.q.knowledge.accept(self.q.run,bad,{raw,new},synthetic=True)
 def test_old_queue_is_ignored_only_after_budgeted_exact_replay(self):
  event,plan=self.receipt(legacy=True);raw=self.q.db.execute('SELECT payload FROM inquiry_events WHERE seq=?',(event,)).fetchone()[0]
  derived=self.q.knowledge.accept(self.q.run,proposal('A downstream numeric claim',event,'"value": 0.15'),{event},synthetic=True)
  self.revise_old();self.q.dependencies.drain(100)
  self.assertEqual('needs_review',self.q.dependencies.status(derived)['state'])
  before_tools=self.q.tools;before_requests=self.q.requests
  result=revalidate_context(self.q)
  self.assertEqual('revalidated',result['outcomes'][0]['status'])
  self.assertEqual(before_tools-1,self.q.tools);self.assertEqual(before_requests,self.q.requests)
  self.assertEqual('current_interpretation',self.q.dependencies.status(derived)['state'])
  self.assertEqual(raw,self.q.db.execute('SELECT payload FROM inquiry_events WHERE seq=?',(event,)).fetchone()[0])
  self.assertGreater(self.q.db.execute('SELECT count(*) FROM inquiry_review_queue WHERE event=?',(derived,)).fetchone()[0],0)
  self.assertEqual(0,revalidate_context(self.q)['tool_attempts_used'])
 def test_real_premise_path_remains_stale_even_when_another_path_is_computational(self):
  event,_=self.receipt()
  derived=self.q.knowledge.accept(self.q.run,proposal('Depends on two sources',event,'"value": 0.15'),{event},synthetic=True)
  self.q.dependencies.link(derived,[self.old]);self.revise_old()
  self.assertEqual('current_interpretation',self.q.dependencies.status(event)['state'])
  self.assertEqual('needs_review',self.q.dependencies.status(derived)['state'])
 def test_mismatch_is_not_reclassified_or_retried_and_zero_tool_budget_does_nothing(self):
  event,plan=self.receipt(legacy=True,value=999);self.revise_old();self.q.tools=0
  self.assertEqual(0,revalidate_context(self.q)['tool_attempts_used'])
  self.q.tools=2
  result=revalidate_context(self.q);self.assertEqual('failed',result['outcomes'][0]['status'])
  self.assertEqual('context',self.q.db.execute('SELECT relation FROM inquiry_dependencies WHERE conclusion=? AND premise=?',(event,plan)).fetchone()[0])
  self.assertEqual('needs_review',self.q.dependencies.status(event)['state'])
  self.assertEqual(0,revalidate_context(self.q)['tool_attempts_used']);self.assertEqual(1,self.q.tools)
 def test_boundary_cannot_be_attached_to_model_text_search_or_failed_calculation(self):
  plan=self.q.record('reflection',{'reflection':{'answer':'Plan'}})
  for kind,status in [('search','executed'),('calculate','failed')]:
   event=self.q.record('tool_result',{'action':{'kind':kind},'status':status,'result':{'value':1}})
   with self.assertRaises(ValueError):self.q.dependencies.link(event,[plan],relation='execution_context')
  text=self.q.record('reflection',{'reflection':{'answer':'Only text'}})
  with self.assertRaises(ValueError):self.q.dependencies.link(text,[plan],relation='execution_context')
 def test_audit_root_is_visible_past_undrained_queue_frontier(self):
  previous=self.old
  for _ in range(15):
   event=self.q.record('reflection',{'reflection':{'answer':'Dependent context'}});self.q.dependencies.link(event,[previous]);previous=event
  self.q.db.execute('INSERT INTO inquiry_review_queue(event,cause) VALUES(?,?)',(self.old,self.user));self.q.db.commit()
  self.assertEqual('needs_review',self.q.dependencies.status(previous)['state'])
 def test_computed_counterexample_can_link_to_tested_candidate_but_not_text_echo(self):
  event,plan=self.receipt()
  for source in [self.user,self.old,event]:self.q.visible_source_text[source]=self.q.knowledge.source(source)['text']
  self.q.user_sources[self.user]=self.q.knowledge.source(self.user)['text']
  action={'kind':'map_inquiry','questions':[{'key':'root','text':'Does the hypothesis survive this model?','parents':[],'origin_event':self.user,'origin_quote':'fixed calculation','revises':None}],'links':[{'question':'root','proposition':self.old,'source_event':event,'quote':'0.15','relation':'challenges','explanation':'Computed result tests the proposed numerical model, not real-world truth'}],'prediction':'Keep the tested candidate and limited result connected'}
  graph=self.q.questions.apply(self.q,action)['graph']
  self.assertEqual('challenges',graph['nodes'][0]['annotations'][0]['relation'])
  self.assertEqual([plan],self.q.knowledge.source(event)['execution_context_events'])
  echo=self.q.record('reflection',{'reflection':{'answer':'The hypothesis is false'}});self.q.dependencies.link(echo,[self.old])
  self.q.visible_source_text[echo]=self.q.knowledge.source(echo)['text']
  action['links'][0].update(source_event=echo,quote='hypothesis')
  with self.assertRaisesRegex(ValueError,'only provides context'):self.q.questions.apply(self.q,action)

if __name__=='__main__':unittest.main()
