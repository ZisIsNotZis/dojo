import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from dojo.inquiry import Inquiry
from dojo.execution import ledger


class ExecutionLedgerTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'db'
  self.host=SimpleNamespace(config=SimpleNamespace(model='deepseek-flash',api_key=None))
  self.q=Inquiry(self.path,self.host,synthetic=True)
 def tearDown(self):self.q.close();self.tmp.cleanup()
 def receipt(self,q,tool,status,**extra):
  return q.record('tool_result',{'action':{'kind':tool},'status':status,**extra})
 def test_complete_counts_survive_bounded_receipts_and_exclude_plans(self):
  self.q.record('reflection',{'reflection':{'answer':'已运行map_inquiry','action':{'kind':'map_inquiry'}}})
  self.q.record('tool_started',{'kind':'map_inquiry'})
  self.q.record('question_associations',{'reason':'后台保存了问题图'})
  for i in range(9):self.receipt(self.q,'search','executed',result={'sources':[]})
  self.receipt(self.q,'map_inquiry','failed',error_kind='schema')
  self.receipt(self.q,'map_inquiry','not_executed',error_kind='budget')
  result=ledger(self.q)
  self.assertEqual(9,result['story_counts']['search']['executed'])
  self.assertEqual({'executed':0,'failed':1,'not_executed':1},result['story_counts']['map_inquiry'])
  self.assertEqual(4,len(result['recent_receipts_per_tool_status']))
 def test_other_story_identity_and_future_receipts_cannot_certify_claim(self):
  cutoff=self.receipt(self.q,'calculate','failed',error_kind='ValueError')
  self.receipt(self.q,'calculate','executed',result={'value':1})
  story=self.q.story
  other=Inquiry(self.path,self.host,synthetic=True)
  try:self.receipt(other,'map_inquiry','executed',result={})
  finally:other.close()
  state=ledger(self.q,through_event=cutoff)
  self.assertEqual(0,state['story_counts']['calculate']['executed'])
  self.assertEqual(0,state['story_counts']['map_inquiry']['executed'])
  continued=Inquiry(self.path,self.host,synthetic=True,story=story)
  try:
   state=ledger(continued)
   self.assertEqual(1,state['story_counts']['calculate']['executed'])
   self.assertEqual(0,state['current_run_counts']['calculate']['executed'])
   self.assertEqual(0,state['story_counts']['map_inquiry']['executed'])
  finally:continued.close()
  real=Inquiry(self.path,self.host,synthetic=False)
  try:
   # Deliberately mixed fixture identity must still not enter the ledger.
   raw=json.loads(real.db.execute("SELECT payload FROM inquiry_events WHERE run=? AND kind='start'",(real.run,)).fetchone()[0])
   raw['story']=story
   with real.db:real.db.execute("UPDATE inquiry_events SET payload=? WHERE run=? AND kind='start'",(json.dumps(raw),real.run))
   self.receipt(real,'map_inquiry','executed',result={})
   self.assertEqual(0,ledger(self.q)['story_counts']['map_inquiry']['executed'])
  finally:real.close()
 def test_partial_result_is_not_reported_as_complete_experiment(self):
  self.receipt(self.q,'text_experiment','executed',result={'status':'incomplete'})
  state=ledger(self.q)
  self.assertEqual('incomplete',state['recent_receipts_per_tool_status'][0]['result_status'])
 def test_critic_gets_closed_scope_even_when_visible_sources_omit_receipt(self):
  self.receipt(self.q,'search','executed',result={'sources':[]})
  target=self.q.record('reflection',{'reflection':{'answer':'已执行map_inquiry。','action':None}})
  self.receipt(self.q,'map_inquiry','executed',result={})
  captured=[]
  def complete(messages):captured.append(json.loads(messages[-1]['content']));return {'issues':[]}
  result=self.q.inspect_reply(SimpleNamespace(complete=complete),target=target,phase='before_delivery')
  self.assertEqual('checked',result['status']);self.assertEqual([],captured[0]['sources'])
  self.assertEqual(1,captured[0]['execution_ledger']['story_counts']['search']['executed'])
  self.assertEqual(0,captured[0]['execution_ledger']['story_counts']['map_inquiry']['executed'])
 def test_changed_ledger_discards_critique_even_if_receipt_not_visible(self):
  receipt=self.receipt(self.q,'search','executed',result={'sources':[]})
  target=self.q.record('reflection',{'reflection':{'answer':'执行状态待核对。','action':None}})
  def complete(messages):
   with self.q.db:self.q.db.execute('DELETE FROM inquiry_events WHERE seq=?',(receipt,))
   return {'issues':[]}
  result=self.q.inspect_reply(SimpleNamespace(complete=complete),target=target,phase='before_delivery')
  self.assertEqual('discarded',result['status'])

if __name__=='__main__':unittest.main()
