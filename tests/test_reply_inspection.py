import json
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from dojo.inquiry import Inquiry,validate_host,run_inquiry
from dojo.live import LiveError

class Host:
 config=SimpleNamespace(model='deepseek-flash',api_key=None)
 def complete(self,messages):return validate_host('{"answer":"奶奶调小了火。","action":null}')

class Critic(Host):
 def __init__(self,bad=False):self.calls=0;self.bad=bad
 def complete(self,messages):
  self.calls+=1;self.packet=json.loads(messages[-1]['content'])
  return {'issues':[{'quote':'不存在的文字' if self.bad else '奶奶调小了火','kind':'invented_detail','reason':'用户只说看气泡，未报告一次调火','counterexample':'假设她没有调火','rewrite':'如果记录一次调火，可分析其触发条件'}]}

class ReplyInspectionTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.q=Inquiry(Path(self.tmp.name)/'db',Host(),synthetic=True)
  self.q.turn('奶奶会看气泡，具体动作不知道')
 def tearDown(self):self.q.close();self.tmp.cleanup()
 def test_inspection_keeps_sources_typed_and_advisory_out_of_evidence(self):
  c=Critic();before=self.q.requests;old=self.q.last_reflection
  result=self.q.inspect_reply(c)
  self.assertEqual('checked',result['status']);self.assertEqual(before-1,self.q.requests)
  self.assertEqual(['user'],[s['kind'] for s in c.packet['sources']])
  self.assertIn('不是用户陈述',self.q.messages[-1]['content'])
  forwarded=json.loads(self.q.messages[-1]['content'].split('\n',1)[1])['execution_ledger']
  self.assertEqual(c.packet['execution_ledger'],forwarded)
  self.assertEqual(1,self.q.db.execute("SELECT count(*) FROM inquiry_events WHERE kind='delivered'").fetchone()[0])
  self.assertNotIn(result['event'],self.q.visible_source_text)
  self.assertEqual('unchanged',self.q.inspect_reply(c)['status']);self.assertEqual(1,c.calls)
  self.q.turn('那么这个动作先不要当真')
  self.assertTrue(self.q.dependencies.depends_on(self.q.last_reflection,result['event']))
  self.assertEqual('奶奶调小了火。',self.q.knowledge.source(old)['text'])
 def test_bad_quote_is_recorded_without_erasing_reply_or_retrying(self):
  c=Critic(bad=True)
  self.assertEqual('failed',self.q.inspect_reply(c)['status'])
  self.assertEqual('unchanged',self.q.inspect_reply(c)['status']);self.assertEqual(1,c.calls)
  self.assertEqual([],self.q.advisory_events)
  self.assertEqual(1,self.q.db.execute("SELECT count(*) FROM inquiry_events WHERE kind='delivered'").fetchone()[0])
 def test_concurrent_source_revision_discards_stale_opinion(self):
  q=self.q
  class Changing(Critic):
   def complete(inner,messages):
    value=super().complete(messages)
    old=next(iter(q.user_sources))
    new=q.record('user',{'text':'更正：这次实际调了火','synthetic':True})
    q.dependencies.revise(old,new,'来源更正')
    return value
  c=Changing();r=q.inspect_reply(c)
  self.assertEqual('discarded',r['status']);self.assertEqual('sources_changed',r['reason'])
  self.assertEqual([],q.advisory_events)
  self.assertEqual('unchanged',q.inspect_reply(c)['status']);self.assertEqual(1,c.calls)
 def test_maintenance_shares_budget_and_eof_does_not_buy_unused_advice(self):
  self.q.turn('不要假装知道动作');self.q.requests=2;c=Critic()
  result=self.q.maintain(Host(),critic_client=c,max_requests=4)
  self.assertEqual(1,result['requests_used']);self.assertEqual(1,self.q.requests)
  self.q.turn('继续');self.assertEqual(0,self.q.requests)
  self.assertEqual(0,self.q.maintain(Host(),critic_client=c,max_requests=1,reserve_chat=False)['requests_used'])
  self.assertEqual(1,c.calls)
 def test_new_replies_share_the_request_budget_instead_of_a_separate_two_check_cap(self):
  c=Critic()
  for i in range(3):
   if i:self.q.turn('继续看看')
   result=self.q.inspect_reply(c)
  self.assertEqual('checked',result['status']);self.assertEqual(3,c.calls)
  self.assertEqual(6,self.q.requests)
  self.assertEqual('unchanged',self.q.inspect_reply(c)['status']);self.assertEqual(3,c.calls)
 def test_third_turn_can_be_checked_and_repaired_once_within_the_same_budget(self):
  class Replies(Host):
   def __init__(self):self.calls=0
   def complete(self,messages):
    text=['请说最近一次具体经历。','这两次报告不能确定唯一原因。',
     '下一泡会自己告诉他。','下一泡可以提供观察，仍需核对条件。'][self.calls]
    self.calls+=1;return validate_host(json.dumps({'answer':text,'action':None},ensure_ascii=False))
  class ThirdCritic(Host):
   def __init__(self):self.calls=0
   def complete(self,messages):
    self.calls+=1
    return {'issues':[] if self.calls<3 else [{'quote':'下一泡会自己告诉他','kind':'unsupported_fact',
     'reason':'没有保证下一泡提供清楚可归因的反馈','counterexample':'下一泡同时改变多个条件',
     'rewrite':'下一泡可以作为观察，不能保证自动学会'}]}
  host=Replies();critic=ThirdCritic()
  q=Inquiry(Path(self.tmp.name)/'three-turns',host,synthetic=True,critic_client=critic,request_budget=7,tool_budget=0)
  try:
   replies=[q.turn(text) for text in ('我想带新人自己判断。','我有两次口味不同的报告。','我想用一两句话引导，而不是每杯审批。')]
   self.assertEqual('下一泡可以提供观察，仍需核对条件。',replies[-1])
   self.assertEqual((4,3,0),(host.calls,critic.calls,q.requests))
   self.assertEqual(3,q.db.execute("SELECT count(*) FROM inquiry_events WHERE kind='delivered'").fetchone()[0])
   self.assertFalse(any('下一泡会自己告诉他' in json.loads(row[0])['answer'] for row in q.db.execute("SELECT payload FROM inquiry_events WHERE kind='delivered'")))
  finally:q.close()
 def test_public_cli_can_explicitly_resume_a_synthetic_story(self):
  from dojo.cli import main
  path=Path(self.tmp.name)/'db'
  with patch('dojo.cli._secure_default_paths'),patch('dojo.inquiry.run_inquiry',return_value=0) as run:
   self.assertEqual(0,main(['--db',str(path),'inquire','--resume',self.q.story,'--synthetic']))
  self.assertEqual({'story':self.q.story,'local_edits':False,'synthetic':True},run.call_args.kwargs)
 def test_cli_checks_before_delivery_and_still_distills_at_eof(self):
  class Scribe(Host):
   def complete(self,messages):return {'intent':{'goals':[],'motivations':[],'inferred_needs':[],'unresolved':[]},'knowledge':[]}
  output=io.StringIO();c=Critic();original=c.complete
  class RevisingHost(Host):
   def complete(self,messages):
    if any('尚未交付的草稿' in m['content'] for m in messages):return validate_host('{"answer":"用户只报告看气泡，调火是假设。","action":null}')
    return super().complete(messages)
  def checked(messages):
   self.assertNotIn('奶奶调小了火。',output.getvalue())
   if '奶奶调小了火' not in json.loads(messages[-1]['content'])['draft']:
    c.calls+=1;return {'issues':[]}
   return original(messages)
  c.complete=checked
  turns=iter(['奶奶会看气泡','具体动作不知道'])
  def read(prompt):
   try:return next(turns)
   except StopIteration:raise EOFError()
  path=Path(self.tmp.name)/'cli-db'
  with patch('dojo.inquiry.config_from_pi',return_value=Host.config),patch('dojo.inquiry.make_client',side_effect=[RevisingHost(),Host(),Scribe(),c,Host(),Host(),Host()]):
   self.assertEqual(0,run_inquiry(path,read_line=read,output=output))
  import sqlite3
  from contextlib import closing
  with closing(sqlite3.connect(path)) as db:
   self.assertEqual(2,db.execute("SELECT count(*) FROM inquiry_events WHERE kind='epistemic_check'").fetchone()[0])
   self.assertEqual(1,db.execute("SELECT count(*) FROM inquiry_events WHERE kind='distill_request_started'").fetchone()[0])
  self.assertEqual(2,c.calls)
if __name__=='__main__':unittest.main()
