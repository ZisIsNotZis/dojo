import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from dojo.inquiry import Inquiry,validate_host
from dojo.live import LiveError

class Host:
 config=SimpleNamespace(model='deepseek-flash',api_key=None)
 native_tools=[]
 def __init__(self,values):self.values=iter(values);self.calls=[]
 def complete(self,messages,*,allow_tools=True):
  self.calls.append({'allow_tools':allow_tools,'messages':list(messages)})
  value=next(self.values)
  if isinstance(value,Exception):raise value
  return value

def answer(text):return validate_host(json.dumps({'answer':text,'action':None}))

class PredeliveryTests(unittest.TestCase):
 def run_fixture(self,values,critic,*,budget=5):
  tmp=tempfile.TemporaryDirectory();host=Host(values);q=Inquiry(Path(tmp.name)/'db',host,synthetic=True,request_budget=budget,critic_client=critic)
  self.addCleanup(tmp.cleanup);self.addCleanup(q.close);return q,host
 def critic(self,issues=True):
  calls=[]
  def complete(messages):
   data=json.loads(messages[-1]['content']);calls.append(data)
   return {'issues':[{'span':data['draft_spans'][0]['span'],'kind':'scope_leap','reason':'The later task has not been observed','counterexample':'The second task may fail','rewrite':'Require post-intervention completion evidence'}] if issues else []}
  return SimpleNamespace(complete=complete,calls=calls)
 def test_only_revised_answer_is_delivered_with_same_budget_and_provenance(self):
  critic=self.critic();q,host=self.run_fixture([answer('等待就能证明任务完成。'),answer('等待不能证明完成，需事后运行证据。')],critic)
  result=q.turn('确认测试是否有区分力')
  self.assertIn('需事后',result);self.assertEqual(2,q.requests);self.assertEqual([True,False],[c['allow_tools'] for c in host.calls]);self.assertEqual(1,len(critic.calls))
  delivered=[json.loads(p) for (p,) in q.db.execute("SELECT payload FROM inquiry_events WHERE kind='delivered'")]
  self.assertEqual(1,len(delivered));self.assertNotIn('等待就能',delivered[0]['answer'])
  draft=json.loads(q.db.execute("SELECT payload FROM inquiry_events WHERE kind='delivery_review'").fetchone()[0])
  inspection=draft['inspection']['event'];self.assertTrue(q.dependencies.depends_on(q.last_reflection,inspection));self.assertFalse(q.dependencies.depends_on(inspection,draft['draft_event']))
  before=q.requests;q.maintain(None,critic_client=critic,max_requests=1);self.assertEqual(before,q.requests);self.assertEqual(1,len(critic.calls))
  self.assertEqual(1,q.db.execute("SELECT count(*) FROM inquiry_events WHERE kind='user'").fetchone()[0])
  synthesis=host.calls[1]['messages']
  self.assertFalse(any(m['role']=='assistant' and '等待就能' in m['content'] for m in synthesis))
  self.assertTrue(any(m['role']=='user' and 'unpublished_draft' in m['content'] and '等待就能' in m['content'] for m in synthesis))
 def test_no_issue_pass_checks_each_turn_without_rewrite_within_shared_budget(self):
  critic=self.critic(False);q,host=self.run_fixture([answer('有条件结论。')]*3,critic,budget=10)
  for _ in range(3):q.turn('继续')
  self.assertEqual(3,len(critic.calls));self.assertEqual(3,len(host.calls));self.assertEqual(4,q.requests)
 def test_insufficient_budget_does_not_buy_unfinishable_review(self):
  critic=self.critic();q,host=self.run_fixture([answer('保留未知。')],critic,budget=2)
  q.turn('当前未知');self.assertEqual([],critic.calls);self.assertEqual(1,q.requests)
 def test_failed_check_is_not_retried_or_recorded_as_approval(self):
  calls=[]
  def fail(messages):calls.append(messages);raise LiveError('Unavailable',kind='transport')
  critic=SimpleNamespace(complete=fail);q,host=self.run_fixture([answer('一个未核验的解释。')],critic)
  q.turn('当前问题');q.maintain(None,critic_client=critic,max_requests=1)
  self.assertEqual(1,len(calls));self.assertEqual(1,len(host.calls))
  review=json.loads(q.db.execute("SELECT payload FROM inquiry_events WHERE kind='delivery_review'").fetchone()[0]);self.assertEqual('failed',review['inspection']['status']);self.assertFalse(review['rewrite_requested'])
 def test_rewrite_tool_call_or_failure_cannot_execute_or_loop(self):
  for last in [validate_host('{"answer":"再算","action":{"kind":"calculate","expression":"1+1","basis":"toy","prediction":"2"}}'),LiveError('Unavailable',kind='transport')]:
   with self.subTest(last=type(last).__name__):
    q,host=self.run_fixture([answer('等待就能证明完成。'),last],self.critic(),budget=5)
    with self.assertRaises(LiveError):q.turn('检查')
    self.assertEqual(2,len(host.calls));self.assertEqual(2,q.requests);self.assertEqual(0,q.db.execute("SELECT count(*) FROM inquiry_events WHERE kind IN ('tool_started','delivered')").fetchone()[0])
 def test_source_change_during_review_discards_draft_instead_of_delivering_stale_claim(self):
  q=None
  def changing(messages):
   old=next(iter(q.user_sources));new=q.record('user',{'text':'A source correction','synthetic':True});q.dependencies.revise(old,new,'Concurrent source correction');return {'issues':[]}
  q,host=self.run_fixture([answer('一个草稿。')],SimpleNamespace(complete=changing))
  with self.assertRaises(LiveError) as caught:q.turn('原话')
  self.assertEqual('sources_changed',caught.exception.kind);self.assertEqual(0,q.db.execute("SELECT count(*) FROM inquiry_events WHERE kind='delivered'").fetchone()[0])

if __name__=='__main__':unittest.main()
