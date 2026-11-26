import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from dojo.live import LiveError

SPEC=importlib.util.spec_from_file_location('simulate',Path(__file__).resolve().parents[1]/'scripts/simulate_inquiry.py')
sim=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(sim)

class Host:
 config=SimpleNamespace(model='deepseek-flash',api_key=None)
 def __init__(self):self.seen=[]
 def complete(self,messages):
  self.seen.append(json.loads(json.dumps(messages)))
  return dict(answer='能讲讲最近一次具体发生的事吗？',understanding='尚未确定',hypotheses=[],unknowns=['需要具体故事'],revision='',action=None)

class Actor(Host):
 def complete(self,messages):
  self.seen.append(messages)
  return dict(utterance='上周我和同事反复解释一个决定，想保留当时的理由。')

class SimulatedUserTests(unittest.TestCase):
 def test_private_background_is_not_sent_to_host_and_budgets_are_separate(self):
  with tempfile.TemporaryDirectory() as d:
   case={'id':'test','opening':'我想做公共平台','private_facts':{'p01':'PRIVATE_SENTINEL','p02':'上周反复解释'}}
   host=Host();actor=Actor();r=sim.run_case(Path(d),case,host,actor,max_turns=2)
   self.assertEqual((2,1,3),(r['host_requests'],r['actor_requests'],r['total_requests']))
   self.assertNotIn('PRIVATE_SENTINEL',json.dumps(host.seen))
   self.assertIn('PRIVATE_SENTINEL',json.dumps(actor.seen))
   self.assertIn('上周我和同事',json.dumps(host.seen,ensure_ascii=False))
   self.assertNotIn('PRIVATE_SENTINEL',(Path(d)/'events.json').read_text(encoding='utf-8'))
 def test_actor_failure_counts_and_does_not_trigger_retry(self):
  class Fail(Actor):
   def complete(self,messages):raise LiveError('failure',kind='timeout')
  with tempfile.TemporaryDirectory() as d:
   r=sim.run_case(Path(d),sim.CASES[0],Host(),Fail(),max_turns=3)
   self.assertEqual('timeout',r['stop']);self.assertEqual(1,r['actor_requests']);self.assertEqual(2,r['total_requests'])
 def test_actor_metadata_is_rejected_before_it_reaches_host(self):
  class Wrong(Actor):
   def complete(self,messages):return dict(utterance='不存在的背景',revealed=['invented'],done=False)
  with tempfile.TemporaryDirectory() as d:
   r=sim.run_case(Path(d),sim.CASES[0],Host(),Wrong(),max_turns=3)
   self.assertEqual('actor_schema',r['stop']);self.assertEqual(1,len([x for x in r['public_dialogue'] if x['role']=='assistant']))
 def test_actor_contract_is_strict(self):
  for text in ('{}','{"utterance":"x","revealed":[],"done":1}'):
   with self.assertRaises(LiveError):sim.validate_actor(text)
 def test_observer_records_public_messages_and_latency_without_configuration_secret(self):
  with tempfile.TemporaryDirectory() as d:
   host=Host();host.config=SimpleNamespace(model='deepseek-flash',api_key='CONFIG_SECRET_SENTINEL')
   path=Path(d)/'calls.jsonl';client=sim.ObservedClient(host,path)
   client.complete([{'role':'user','content':'自然对话'}])
   log=path.read_text(encoding='utf-8')
   self.assertNotIn('CONFIG_SECRET_SENTINEL',log)
   events=[json.loads(x) for x in log.splitlines()]
   self.assertEqual(['started','completed'],[x['event'] for x in events])
   self.assertGreaterEqual(events[-1]['elapsed_seconds'],0)
if __name__=='__main__':unittest.main()
