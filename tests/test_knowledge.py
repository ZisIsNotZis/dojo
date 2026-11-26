import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from dojo.inquiry import Inquiry
from dojo.experiments import parameter_sweep
from dojo.knowledge import validate_proposal
from dojo.reviews import apply_review,run_rechecks

class Client:
 config=SimpleNamespace(model='deepseek-flash',api_key=None)
 def complete(self,messages):raise AssertionError('unexpected model request')


def proposal(text,event,quote,*,revises=None):
 return {'statement':text,'kind':'decision','method':'deduction','premises':[{'event':event,'quote':quote,'role':'evidence'}],
   'assumptions':['每次净省8分钟，忽略维护和非时间收益'],'conditions':['只做6次'],'alternatives':['保留手工'],
   'falsifier':'若设置成本超过48分钟则纯时间收益反转','revises':revises}


def stage(q):
 user=q.record('user',{'text':'我只看时间成本，报告只做6次','synthetic':q.synthetic})
 a=q.record('tool_result',{'status':'executed','result':parameter_sweep({'setup':[0]},{'net':'6*8-setup'},'net>0')})
 pa=proposal('模型内6次报告净省48分钟',a,'"net": 48')
 original=q.knowledge.accept(q.run,pa,{a},synthetic=q.synthetic)
 pb=proposal('按纯时间标准，6次自动化值得做',original,pa['statement'])
 pb['premises'].append({'event':user,'quote':'我只看时间成本','role':'value'})
 derived=q.knowledge.accept(q.run,pb,{original,user},synthetic=q.synthetic)
 b=q.record('tool_result',{'status':'executed','result':parameter_sweep({'setup':[100]},{'net':'6*8-setup'},'net>0')})
 revised=proposal('模型内6次报告净亏52分钟',b,'"net": -52',revises=original)
 replacement=q.knowledge.accept(q.run,revised,{b,original},synthetic=q.synthetic)
 return original,derived,replacement,user


class KnowledgeTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.q=Inquiry(Path(self.tmp.name)/'db',Client(),synthetic=True)
 def tearDown(self):self.q.close();self.tmp.cleanup()
 def test_false_or_unseen_anchor_writes_no_proposal(self):
  event=self.q.record('user',{'text':'我愿意付时间成本','synthetic':True})
  before=self.q.db.execute('SELECT count(*) FROM inquiry_events').fetchone()[0]
  with self.assertRaises(ValueError):self.q.knowledge.accept(self.q.run,proposal('结论',event,'没说过'),{event},synthetic=True)
  with self.assertRaises(ValueError):self.q.knowledge.accept(self.q.run,proposal('结论',event,'时间成本'),set(),synthetic=True)
  self.assertEqual(before,self.q.db.execute('SELECT count(*) FROM inquiry_events').fetchone()[0])
 def test_executed_tool_prediction_cannot_be_cited_as_observation(self):
  event=self.q.record('tool_result',{'action':{'kind':'calculate','prediction':'PREDICTED_TRUE'},'status':'executed','result':{'value':False}})
  p=proposal('模型结果是正向',event,'PREDICTED_TRUE')
  with self.assertRaisesRegex(ValueError,'not an observation'):self.q.knowledge.accept(self.q.run,p,{event},synthetic=True)
  p['premises'][0]['role']='assumption'
  self.assertIsInstance(self.q.knowledge.accept(self.q.run,p,{event},synthetic=True),int)
 def test_quote_floor_rejects_token_level_citations(self):
  event=self.q.record('user',{'text':'我只看时间成本，报告只做6次；样例 48 -52 [] true 1 ,','synthetic':True})
  for quote in (',','1','48','-52','[]','true'):
   with self.assertRaisesRegex(ValueError,'content run'):self.q.knowledge.accept(self.q.run,proposal('Filler conclusion',event,quote),{event},synthetic=True)
  self.assertIsInstance(self.q.knowledge.accept(self.q.run,proposal('Real phrase',event,'我只看时间成本'),{event},synthetic=True),int)
 def test_quote_floor_has_teeth_only_mid_string(self):
  event=self.q.record('user',{'text':'我只看时间成本，报告只做6次','synthetic':True})
  good=proposal('Baseline',event,'我只看时间成本')
  self.assertIsInstance(self.q.knowledge.accept(self.q.run,good,{event},synthetic=True),int)
  middle=proposal('Middle changed',event,'我只看Z间成本')
  with self.assertRaises(ValueError):self.q.knowledge.accept(self.q.run,middle,{event},synthetic=True)
  # Known boundary, not a footnote: deleting the tail of a substring stays a
  # substring, so this floor cannot catch truncation. Recorded as accepted.
  self.assertIsInstance(self.q.knowledge.accept(self.q.run,proposal('Tail cut',event,'我只看时间成'),{event},synthetic=True),int)
 def test_quote_floor_can_be_switched_back_to_legacy(self):
  import os
  event=self.q.record('user',{'text':'我只看时间成本，报告只做6次；样例 ,','synthetic':True})
  os.environ['DOJO_QUOTE_FLOOR']='legacy'
  try:self.assertIsInstance(self.q.knowledge.accept(self.q.run,proposal('Legacy floor',event,','),{event},synthetic=True),int)
  finally:os.environ.pop('DOJO_QUOTE_FLOOR',None)
  with self.assertRaisesRegex(ValueError,'content run'):self.q.knowledge.accept(self.q.run,proposal('Default floor',event,','),{event},synthetic=True)
 def test_exact_restatement_is_idempotent_and_not_truth_certification(self):
  event=self.q.record('user',{'text':'只算时间成本这一项','synthetic':True})
  p=proposal('待检验结论',event,'时间成本这一项')
  a=self.q.knowledge.accept(self.q.run,p,{event},synthetic=True)
  self.assertEqual(a,self.q.knowledge.accept(self.q.run,p,{event},synthetic=True))
  self.assertEqual('model_proposal_not_certified',self.q.knowledge.source(a)['epistemic_status'])
 def test_model_story_cannot_be_promoted_to_evidence_but_can_be_an_assumption(self):
  event=self.q.record('reflection',{'reflection':{'answer':'奶奶调小了火'},'synthetic':True})
  p=proposal('气泡变化触发了调火',event,'奶奶调小了火')
  before=self.q.db.execute('SELECT count(*) FROM inquiry_events').fetchone()[0]
  with self.assertRaisesRegex(ValueError,'assumption role'):self.q.knowledge.accept(self.q.run,p,{event},synthetic=True)
  self.assertEqual(before,self.q.db.execute('SELECT count(*) FROM inquiry_events').fetchone()[0])
  p['premises'][0]['role']='assumption';p['method']='hypothesis'
  saved=self.q.knowledge.accept(self.q.run,p,{event},synthetic=True)
  self.assertEqual('assumption',self.q.knowledge.source(saved)['proposal']['premises'][0]['role'])
  self.assertEqual('model_proposal_not_certified',self.q.knowledge.source(saved)['epistemic_status'])
 def test_changed_premise_creates_targeted_review_with_latest_evidence(self):
  old,derived,new,user=stage(self.q)
  self.assertEqual('needs_review',self.q.dependencies.status(derived)['state'])
  packets=self.q.knowledge.review_candidates(synthetic=True,limit=2)
  self.assertEqual([derived],[p['target'] for p in packets])
  self.assertIn(new,[s['event'] for s in packets[0]['sources']])
  newp=proposal('按当前模型纯时间净亏52分钟，6次不划算',new,'净亏52分钟',revises=derived)
  result=apply_review(self.q,packets[0],{'disposition':'replace','reason':'新设置成本改变净收益','replacement':newp})
  self.assertEqual('superseded',self.q.dependencies.status(derived)['state'])
  self.assertEqual('current_interpretation',self.q.dependencies.status(result['replacement_event'])['state'])
  self.assertEqual([],self.q.knowledge.review_candidates(synthetic=True))
 def test_unresolved_review_does_not_promote_or_repeatedly_spend(self):
  _,derived,_,_=stage(self.q);packet=self.q.knowledge.review_packet(derived)
  apply_review(self.q,packet,{'disposition':'unresolved','reason':'需要新的现实观察','replacement':None})
  self.assertEqual('needs_review',self.q.dependencies.status(derived)['state'])
  self.assertEqual([],self.q.knowledge.review_candidates(synthetic=True))
 def test_stale_review_packet_cannot_apply_after_another_revision(self):
  _,derived,new,_=stage(self.q);packet=self.q.knowledge.review_packet(derived)
  e=self.q.record('user',{'text':'新的限制条件','synthetic':True})
  newer=proposal('模型条件进一步改变',e,'新的限制条件',revises=new)
  self.q.knowledge.accept(self.q.run,newer,{e,new},synthetic=True)
  result=apply_review(self.q,packet,{'disposition':'withdraw','reason':'旧packet已过期','replacement':None})
  self.assertEqual('discarded',result['status'])
  self.assertNotEqual('superseded',self.q.dependencies.status(derived)['state'])
 def test_review_worker_has_budget_and_does_not_retry_failure(self):
  stage(self.q)
  class Fail(Client):
   def complete(self,messages):
    from dojo.live import LiveError
    raise LiveError('failure',kind='timeout')
  result=run_rechecks(Path(self.tmp.name)/'db',client=Fail(),synthetic=True,max_requests=2)
  self.assertEqual(1,result['requests_used']);self.assertEqual('failed',result['outcomes'][0]['status'])
  repeated=run_rechecks(Path(self.tmp.name)/'db',client=Fail(),synthetic=True,max_requests=2)
  self.assertEqual(0,repeated['requests_used'])
  explicit=run_rechecks(Path(self.tmp.name)/'db',client=Fail(),synthetic=True,max_requests=2,retry_failures=True)
  self.assertEqual(1,explicit['requests_used'])
 def test_interactive_maintenance_shares_chat_budget_and_reserves_one_turn(self):
  _,derived,new,_=stage(self.q)
  class Reviewer(Client):
   def complete(inner,messages):
    packet=json.loads(messages[-1]['content'])
    return {'disposition':'replace','reason':'固定成本改为100，净收益反转',
      'replacement':proposal('当前模型的6次自动化不划算',new,'净亏52分钟',revises=packet['target'])}
  self.q.requests=2
  outcome=self.q.maintain(Reviewer(),max_requests=2)
  self.assertEqual(1,outcome['requests_used']);self.assertEqual(1,self.q.requests)
  self.assertEqual('superseded',self.q.dependencies.status(derived)['state'])
  self.assertEqual(0,self.q.maintain(Reviewer(),max_requests=2)['requests_used'])
 def test_user_can_detach_and_remaining_budget_finishes_bounded_review(self):
  stage(self.q)
  class Reviewer(Client):
   def complete(inner,messages):
    return {'disposition':'unresolved','reason':'模型外现实收益尚未知','replacement':None}
  self.q.requests=1
  self.assertEqual(0,self.q.maintain(Reviewer())['requests_used'])
  result=self.q.maintain(Reviewer(),max_requests=1,reserve_chat=False)
  self.assertEqual(1,result['requests_used']);self.assertEqual(0,self.q.requests)
 def test_cli_conversation_runs_maintenance_without_user_command(self):
  import io
  from unittest.mock import patch
  from dojo.inquiry import run_inquiry
  self.q.close()
  path=Path(self.tmp.name)/'ordinary-input-branch'
  self.q=Inquiry(path,Client(),synthetic=False)
  _,derived,new,_=stage(self.q)
  class Chat(Client):
   def complete(inner,messages):
    return dict(answer='先继续讨论当前问题',understanding='未改变用户目标',hypotheses=[],unknowns=[],revision='',action=None)
  class Reviewer(Client):
   def complete(inner,messages):
    packet=json.loads(messages[-1]['content'])
    return {'disposition':'replace','reason':'按新成本更新下游应用',
     'replacement':proposal('新模型下净时间不划算',new,'净亏52分钟',revises=packet['target'])}
  class Scribe(Client):
   def complete(inner,messages):
    return {'intent':{'goals':[],'motivations':[],'inferred_needs':[],'unresolved':[]},'knowledge':[]}
  class Critic(Client):
   def complete(inner,messages):return {'issues':[]}
  turns=iter(['继续'])
  def read(prompt):
   try:return next(turns)
   except StopIteration:raise EOFError()
  # Exercise the ordinary-input branch using unit fixtures and fake transports;
  # these unit records are not observations about real people.
  output=io.StringIO()
  with patch('dojo.inquiry.config_from_pi',return_value=Client.config),patch('dojo.inquiry.make_client',side_effect=[Chat(),Reviewer(),Scribe(),Critic(),Client(),Client(),Client()]):
   self.assertEqual(0,run_inquiry(path,read_line=read,output=output))
  self.assertIn('先继续讨论',output.getvalue())
  self.assertEqual('superseded',self.q.dependencies.status(derived)['state'])
  self.assertEqual(1,self.q.db.execute("SELECT count(*) FROM inquiry_events WHERE kind='review_request_started'").fetchone()[0])
if __name__=='__main__':unittest.main()
