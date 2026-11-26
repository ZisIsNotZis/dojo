from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from dojo.inquiry import Inquiry
from dojo.reviews import apply_review,perform_rechecks
from tests.test_knowledge import proposal


class ReviewEvidenceTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'db'
  self.host=SimpleNamespace(config=SimpleNamespace(model='deepseek-flash',api_key=None))
  self.q=Inquiry(self.path,self.host,synthetic=True)
  self.user=self.q.record('user',{'text':'Check the condition','synthetic':True})
  self.target=self.q.knowledge.accept(self.q.run,proposal('Condition not yet checked',self.user,'condition'),{self.user},synthetic=True)
  self.evidence=self.q.record('tool_result',{'status':'executed','result':{'value':0.15}})
 def tearDown(self):self.q.close();self.tmp.cleanup()
 def request(self,evidence=None,allowed=None):
  return self.q.knowledge.request_review(self.q.run,self.target,[self.evidence if evidence is None else evidence],'Actual new observation, not a truth verdict',{self.target,self.evidence} if allowed is None else allowed,synthetic=True)
 def test_new_evidence_enters_target_packet_and_downstream_status_without_rewriting_data(self):
  child=self.q.knowledge.accept(self.q.run,proposal('Dependent application',self.target,'Condition'),{self.target},synthetic=True)
  old=self.q.db.execute('SELECT payload FROM inquiry_events WHERE seq=?',(self.target,)).fetchone()[0]
  before=self.q.requests;result=self.request()
  self.assertEqual('requested',result['status']);self.assertEqual(before,self.q.requests)
  self.assertIn(self.evidence,{s['event'] for s in self.q.knowledge.review_packet(self.target)['sources']})
  self.assertEqual('needs_review',self.q.dependencies.status(child)['state'])
  self.assertEqual(old,self.q.db.execute('SELECT payload FROM inquiry_events WHERE seq=?',(self.target,)).fetchone()[0])
  count=self.q.db.execute('SELECT count(*) FROM inquiry_events').fetchone()[0]
  self.assertEqual('unchanged',self.request()['status']);self.assertEqual(count,self.q.db.execute('SELECT count(*) FROM inquiry_events').fetchone()[0])
 def test_unseen_old_stale_and_model_echo_sources_do_not_create_notice(self):
  raw=self.q.record('reflection',{'reflection':{'answer':'Condition is true'},'synthetic':True})
  echo=self.q.knowledge.accept(self.q.run,proposal('Condition restated',self.target,'Condition'),{self.target},synthetic=True)
  for event,allowed in [(self.evidence,{self.target}),(self.user,{self.target,self.user}),(raw,{self.target,raw}),(echo,{self.target,echo})]:
   before=self.q.db.execute('SELECT count(*) FROM inquiry_events').fetchone()[0]
   with self.assertRaises(ValueError):self.request(event,allowed)
   self.assertEqual(before,self.q.db.execute('SELECT count(*) FROM inquiry_events').fetchone()[0])
  newer=self.q.record('tool_result',{'status':'executed','result':{'value':0.2}})
  self.q.dependencies.revise(self.evidence,newer,'Correct source')
  with self.assertRaises(ValueError):self.request()
 def test_recheck_can_revise_interpretation_while_old_tool_result_stays_current(self):
  self.request();packet=self.q.knowledge.review_packet(self.target)
  replacement=proposal('A finite numeric observation is now available',self.evidence,'"value": 0.15',revises=self.target)
  result=apply_review(self.q,packet,{'disposition':'replace','reason':'New actual evidence narrows the prior unknown','replacement':replacement})
  self.assertEqual('superseded',self.q.dependencies.status(self.target)['state'])
  self.assertEqual('current_interpretation',self.q.dependencies.status(result['replacement_event'])['state'])
  self.assertEqual('current_interpretation',self.q.dependencies.status(self.evidence)['state'])
 def test_unresolved_does_not_retry_until_genuinely_new_source_is_noticed(self):
  self.request();calls=[]
  def complete(messages):calls.append(messages);return {'disposition':'unresolved','reason':'Insufficient semantic evidence','replacement':None}
  client=SimpleNamespace(complete=complete)
  self.assertEqual(1,perform_rechecks(self.q,client,max_requests=3)['requests_used'])
  self.request();self.assertEqual(0,perform_rechecks(self.q,client,max_requests=3)['requests_used'])
  new=self.q.record('tool_result',{'status':'executed','result':{'value':0.2}})
  self.request(new,{self.target,new})
  self.assertEqual(1,perform_rechecks(self.q,client,max_requests=1)['requests_used']);self.assertEqual(2,len(calls))
 def test_synthetic_source_cannot_reopen_real_target(self):
  real=Inquiry(self.path,self.host,synthetic=False)
  try:
   user=real.record('user',{'text':'Fixture real-side condition','synthetic':False})
   target=real.knowledge.accept(real.run,proposal('Unverified fixture',user,'condition'),{user},synthetic=False)
   fake=self.q.record('tool_result',{'status':'executed','result':{'value':99}})
   with self.assertRaisesRegex(ValueError,'synthetic review evidence'):real.knowledge.request_review(real.run,target,[fake],'Must not contaminate',{target,fake},synthetic=False)
  finally:real.close()
 def test_current_run_notice_precedes_newer_historical_pending_target(self):
  other=self.q.knowledge.accept(self.q.run,proposal('Another condition',self.user,'condition'),{self.user},synthetic=True)
  evidence=self.q.record('tool_result',{'status':'executed','result':{'value':0.2}})
  self.q.knowledge.request_review(self.q.run,other,[evidence],'Historical pending check',{other,evidence},synthetic=True)
  later=Inquiry(self.path,self.host,synthetic=True)
  try:
   later.knowledge.request_review(later.run,self.target,[self.evidence],'Current follow-up',{self.target,self.evidence},synthetic=True)
   self.assertEqual(other,later.knowledge.review_candidates(synthetic=True,limit=1)[0]['target'])
   calls=[]
   def complete(messages):
    import json
    calls.append(json.loads(messages[-1]['content'])['target'])
    return {'disposition':'unresolved','reason':'Preferences still unknown','replacement':None}
   self.assertEqual(1,perform_rechecks(later,SimpleNamespace(complete=complete),max_requests=1)['requests_used'])
   self.assertEqual([self.target],calls)
   perform_rechecks(later,SimpleNamespace(complete=complete),max_requests=1)
   self.assertEqual([self.target,other],calls)
  finally:later.close()

if __name__=='__main__':unittest.main()
