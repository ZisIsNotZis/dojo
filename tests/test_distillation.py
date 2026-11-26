import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from dojo.inquiry import Inquiry,validate_host,validate_distillation,run_inquiry,make_client
from dojo.live import LiveError

class Host:
 config=SimpleNamespace(model='deepseek-flash',api_key=None)
 def complete(self,messages):return validate_host('{"answer":"先讲一件具体的事，我们一起理解它。","action":null}')

class Scribe(Host):
 def __init__(self,bad=False):self.bad=bad;self.calls=0
 def complete(self,messages):
  self.calls+=1;packet=json.loads(messages[-1]['content'])
  source=next(s for s in packet['sources'] if s['kind']=='user')
  return {'intent':{'goals':[{'text':'公共经验分享','source_event':source['event'],'quote':'不存在的原话' if self.bad else '公共经验平台'}],
    'motivations':[],'inferred_needs':[],'unresolved':['迁移适用性待检验']},
   'knowledge':[{'statement':'公共目标尚未被用户撤回','kind':'descriptive','method':'hypothesis',
    'premises':[{'event':source['event'],'quote':'公共经验平台','role':'evidence'}],
    'assumptions':[],'conditions':['仅当前公开对话'],'alternatives':[],'falsifier':'用户明确改变目标','revises':None}]}

class DistillationTests(unittest.TestCase):
 def test_host_contract_does_not_require_private_notes_and_rejects_hybrid_format(self):
  v=validate_host('{"answer":"一起想想","action":null}')
  self.assertEqual('一起想想',v['answer']);self.assertNotIn('knowledge',v)
  with self.assertRaises(LiveError):validate_host('{"answer":"一起想想","action":null,"intent":{}}')
  with self.assertRaises(LiveError):validate_distillation('{"answer":"不得混入用户回答","knowledge":[]}')
 def test_scribe_captures_grounded_knowledge_after_answer_and_caches_same_packet(self):
  with tempfile.TemporaryDirectory() as d:
   q=Inquiry(Path(d)/'db',Host(),synthetic=True)
   try:
    answer=q.turn('我想做公共经验平台')
    self.assertIn('具体的事',answer)
    self.assertEqual([],q.knowledge.proposals(synthetic=True))
    scribe=Scribe();before=q.requests;result=q.distill(scribe)
    self.assertEqual('distilled',result['status']);self.assertEqual(before-1,q.requests)
    self.assertEqual(1,len(q.knowledge.proposals(synthetic=True)))
    self.assertEqual('unchanged',q.distill(scribe)['status']);self.assertEqual(1,scribe.calls)
   finally:q.close()
 def test_invalid_intent_is_rejected_without_erasing_independent_knowledge_or_answer(self):
  with tempfile.TemporaryDirectory() as d:
   q=Inquiry(Path(d)/'db',Host(),synthetic=True)
   try:
    q.turn('我想做公共经验平台');result=q.distill(Scribe(bad=True))
    self.assertEqual('partially_distilled',result['status']);self.assertEqual('intent_source_mismatch',result['kind'])
    self.assertEqual(1,len(q.knowledge.proposals(synthetic=True)))
    saved=json.loads(q.db.execute("SELECT payload FROM inquiry_events WHERE kind='distillation'").fetchone()[0])
    self.assertIsNone(saved['intent']);self.assertEqual('rejected',saved['intent_status'])
    self.assertEqual(1,q.db.execute("SELECT count(*) FROM inquiry_events WHERE kind='delivered'").fetchone()[0])
   finally:q.close()
 def test_current_intent_pool_is_explicit_even_when_historical_user_sources_are_present(self):
  with tempfile.TemporaryDirectory() as d:
   class HistoricalHost(Host):
    def complete(self,messages):return validate_host('{"answer":"公共经验平台尚待研究。","action":null}')
   path=Path(d)/'db';old=Inquiry(path,HistoricalHost(),synthetic=True)
   old.turn('公共经验平台是旧故事');old_user=next(iter(old.user_sources));old.close()
   q=Inquiry(path,Host(),synthetic=True)
   try:
    q.turn('公共经验平台这次想诊断检索');current=next(iter(q.user_sources))
    self.assertIn(old_user,q.visible_source_text)
    class Scoped(Scribe):
     def complete(inner,messages):
      packet=json.loads(messages[-1]['content'])
      self.assertEqual([current],packet['current_user_events'])
      self.assertEqual([current],[s['event'] for s in packet['intent_sources']])
      self.assertIn(old_user,[s['event'] for s in packet['sources']])
      source=packet['intent_sources'][0]
      return {'intent':{'goals':[{'text':'诊断检索','source_event':source['event'],'quote':'这次想诊断检索'}],'motivations':[],'inferred_needs':[],'unresolved':[]},'knowledge':[]}
    self.assertEqual('distilled',q.distill(Scoped())['status'])
   finally:q.close()
 def test_maintenance_budget_includes_distillation_and_does_not_double_spend(self):
  with tempfile.TemporaryDirectory() as d:
   q=Inquiry(Path(d)/'db',Host(),synthetic=True)
   try:
    q.turn('我想做公共经验平台');q.turn('普通人的经验能帮到别人')
    before=q.requests;result=q.maintain(Host(),scribe_client=Scribe(),max_requests=1)
    self.assertEqual(1,result['requests_used']);self.assertEqual(before-1,q.requests)
    self.assertEqual('distilled',result['distillation']['status'])
   finally:q.close()
 def test_client_setup_failure_never_opens_database(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'db'
   with patch('dojo.inquiry.config_from_pi',return_value=Host.config),patch('dojo.inquiry.make_client',side_effect=[Host(),LiveError('配置无效',kind='config')]):
    with self.assertRaises(LiveError):run_inquiry(p,output=io.StringIO())
   self.assertFalse(p.exists())
if __name__=='__main__':unittest.main()
