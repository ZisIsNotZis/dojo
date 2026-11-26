import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from dojo.inquiry import Inquiry,validate_host
from dojo.live import LiveError
from dojo.text_experiments import run,observe,validate_reading

class Host:
 config=SimpleNamespace(model='deepseek-flash',api_key=None)
 def complete(self,messages):raise AssertionError('unexpected host request')

def action(event):
 return {'kind':'text_experiment','source_events':[event],'probes':[{'question':'为什么不迁移？','event':event,'quote':'规模还没到迁移的触发条件'}],'prediction':'普通摘要可能漏掉被否方案的复活条件'}

class TextExperimentTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.q=Inquiry(Path(self.tmp.name)/'db',Host(),synthetic=True)
  self.source=self.q.record('user',{'text':'我们保留当前库，规模还没到迁移的触发条件。增长后再评估迁移。','synthetic':True})
  self.q.visible_source_text[self.source]=self.q.knowledge.source(self.source)['text']
 def tearDown(self):self.q.close();self.tmp.cleanup()
 def factory(self,seen,fail=False,change=False):
  q=self.q;source=self.source
  def create(q,validator):
   class Backend:
    def complete(inner,messages):
     seen.append(messages)
     if fail and len(seen)==1:raise LiveError('fixture',kind='timeout')
     if 'representation' not in json.loads(messages[-1]['content']):
      text='保留当前库。' if len(seen)==1 else '规模还没到迁移的触发条件'
      return validator(text)
     if change:
      new=q.record('user',{'text':'更正：已经达到阈值','synthetic':True})
      q.dependencies.revise(source,new,'更正')
     representation=json.loads(messages[-1]['content'])['representation']
     return validator(json.dumps({'answers':[{'index':0,'answer':'按给定记录回答','quotes':[representation],'unknown':False}]},ensure_ascii=False))
   return Backend()
  return create
 def test_actual_pipeline_blinds_questions_and_references_and_counts_all_calls(self):
  seen=[]
  with patch('dojo.text_experiments.backend',side_effect=self.factory(seen)):result=run(self.q,action(self.source))
  self.assertEqual('observed',result['status']);self.assertEqual(4,result['requests_used']);self.assertEqual(8,self.q.requests)
  self.assertEqual([False,True],[a['observations'][0]['reference_verbatim_in_representation'] for a in result['arms']])
  self.assertEqual([False,True],[a['observations'][0]['reference_verbatim_in_valid_reader_citations'] for a in result['arms']])
  self.assertEqual('not_measured',result['semantic_accuracy']);self.assertTrue(result['original_source_event_links_retained'])
  for index in (0,2):
   self.assertEqual({'sources'},set(json.loads(seen[index][-1]['content'])))
  for index in (1,3):
   packet=json.loads(seen[index][-1]['content'])
   self.assertEqual({'representation','questions'},set(packet))
   self.assertNotIn('quote',packet['questions'][0]);self.assertNotIn('sources',packet)
   self.assertNotIn('decision_trace',json.dumps(seen[index]))
 def test_unanchored_quotes_are_visible_but_not_counted_as_reference_recovery(self):
  probe=action(self.source)['probes']
  r=observe('保留当前库',{'answers':[{'index':0,'answer':'模型补全','quotes':[probe[0]['quote']],'unknown':False}]},probe)[0]
  self.assertFalse(r['reference_verbatim_in_valid_reader_citations']);self.assertEqual([],r['reader_citations_in_representation']);self.assertEqual([probe[0]['quote']],r['reader_citations_absent_from_representation'])
 def test_paraphrased_record_citation_is_not_original_quote_or_semantic_failure(self):
  probe=action(self.source)['probes'];paraphrase='当前规模尚不需要迁移'
  r=observe(paraphrase,{'answers':[{'index':0,'answer':'暂缓迁移','quotes':[paraphrase],'unknown':False}]},probe,[{'event':self.source,'text':self.q.visible_source_text[self.source]}])[0]
  self.assertFalse(r['reference_verbatim_in_representation'])
  self.assertEqual([paraphrase],r['reader_citations_in_representation'])
  self.assertEqual([],r['reader_citation_original_locations'][0]['source_events'])
  self.assertEqual('not_evaluated',r['semantic_correctness'])
 def test_invalid_unseen_model_or_reference_source_never_calls_model(self):
  invalid=[action(self.source)]
  invalid[0]['probes'][0]['quote']='从未说过'
  unseen=action(self.source+100);invalid.append(unseen)
  model=self.q.record('reflection',{'reflection':{'answer':'模型假想'},'synthetic':True})
  self.q.visible_source_text[model]='模型假想';m=action(model);m['probes'][0]['quote']='模型假想';invalid.append(m)
  with patch('dojo.text_experiments.backend') as backend:
   for a in invalid:
    with self.assertRaises(ValueError):run(self.q,a)
   backend.assert_not_called()
  self.assertEqual(12,self.q.requests)
 def test_insufficient_budget_is_not_an_executed_experiment(self):
  self.q.requests=4;plan=self.q.record('reflection',{'reflection':{'answer':'计划验证'},'synthetic':True})
  with patch('dojo.text_experiments.backend') as backend:event,result,_=self.q.execute_action(action(self.source),plan)
  self.assertEqual('not_executed',result['status']);self.assertEqual(4,self.q.requests);backend.assert_not_called()
  self.assertEqual('tool_failure_not_positive_evidence',self.q.knowledge.source(event)['epistemic_status'])
 def test_failed_arm_is_preserved_without_retry_and_other_arm_still_runs(self):
  seen=[]
  with patch('dojo.text_experiments.backend',side_effect=self.factory(seen,fail=True)):r=run(self.q,action(self.source))
  self.assertEqual('incomplete',r['status']);self.assertEqual(3,r['requests_used'])
  self.assertEqual('timeout',r['arms'][0]['error_kind']);self.assertEqual('observed',r['arms'][1]['status'])
 def test_source_revision_during_execution_discards_comparison(self):
  seen=[]
  # Change once; later calls must not attempt to overwrite the immutable revision.
  create=self.factory(seen,change=True)
  def factory(q,v):
   if len(seen)>=2:return self.factory(seen)(q,v)
   return create(q,v)
  with patch('dojo.text_experiments.backend',side_effect=factory):r=run(self.q,action(self.source))
  self.assertEqual('discarded_sources_changed',r['status'])
 def test_contract_rejects_reference_leak_and_duplicate_reader_keys(self):
  a=action(self.source);a['probes'][0]['question']=a['probes'][0]['quote']
  with self.assertRaises(LiveError):validate_host(json.dumps({'answer':'计划','action':a}))
  with self.assertRaises(LiveError):validate_reading('{"answers":[],"answers":[]}')
  with self.assertRaises(LiveError):validate_reading('{"answers":[{"index":true,"answer":"x","quotes":[],"unknown":false}]}')
 def test_tool_plan_is_not_experimental_source_material(self):
  event=self.q.record('tool_result',{'action':{'kind':'search','prediction':'PLAN_SENTINEL'},'status':'executed','result':{'sources':[{'excerpt':'实际检索摘录'}]}})
  self.q.visible_source_text[event]=self.q.knowledge.source(event)['text']
  a=action(event);a['probes'][0]['quote']='PLAN_SENTINEL'
  with patch('dojo.text_experiments.backend') as factory:
   with self.assertRaises(ValueError):run(self.q,a)
   factory.assert_not_called()
  a['probes'][0]['quote']='实际检索摘录';seen=[]
  with patch('dojo.text_experiments.backend',side_effect=self.factory(seen)):run(self.q,a)
  for i in (0,2):self.assertNotIn('PLAN_SENTINEL',json.dumps(seen[i]))
if __name__=='__main__':unittest.main()
