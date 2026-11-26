import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from dojo.inquiry import Inquiry
from dojo.live import LiveError
from tests.test_predelivery import Host,answer

class LocalDeliveryTests(unittest.TestCase):
 def fixture(self,editor,*,budget=3,critic=None):
  tmp=tempfile.TemporaryDirectory();host=Host([answer('保留事实。错误片段。')]);calls=[]
  def check(messages):
   shown=json.loads(messages[-1]['content']);calls.append(shown);span=next(s for s in shown['draft_spans'] if '错误' in s['quote'])
   return {'issues':[{'span':span['span'],'kind':'scope_leap','reason':'The scope is unsupported','counterexample':'A narrower reading remains possible','rewrite':'保留未知。'}]}
  q=Inquiry(Path(tmp.name)/'db',host,synthetic=True,request_budget=budget,critic_client=critic or SimpleNamespace(complete=check),editor_client=SimpleNamespace(complete=editor))
  self.addCleanup(tmp.cleanup);self.addCleanup(q.close);return q,host,calls
 def edit(self,messages):
  request=json.loads(messages[-1]['content']);shown=request['editing']
  self.assertEqual({'executed':0,'failed':0,'not_executed':0},request['execution_ledger']['current_run_counts']['map_inquiry'])
  return {'decisions':[{'span':s['span'],'disposition':'replace','reason':'Only a bounded claim is supported','replacement':'保留未知。'} for s in shown['edit_spans']]}
 def test_last_budget_request_edits_and_delivers_once_without_another_host_call(self):
  q,host,calls=self.fixture(self.edit);result=q.turn('明确输入')
  self.assertEqual('保留事实。保留未知。',result);self.assertEqual(0,q.requests);self.assertEqual(1,len(host.calls));self.assertEqual(1,len(calls))
  self.assertEqual(1,q.db.execute("SELECT count(*) FROM inquiry_events WHERE kind='delivered'").fetchone()[0])
  request=json.loads(q.db.execute("SELECT payload FROM inquiry_events WHERE kind='delivery_edit_request_started'").fetchone()[0]);self.assertTrue(q.dependencies.depends_on(q.last_reflection,request['inspection']))
  self.assertFalse(q.dependencies.depends_on(q.last_reflection,request['target']))
 def test_failed_or_out_of_scope_edit_is_not_retried_or_delivered(self):
  def invalid(messages):return {'decisions':[{'span':999,'disposition':'replace','reason':'Invalid reference','replacement':'No'}]}
  def failed(messages):raise LiveError('Unavailable',kind='transport')
  for editor in (invalid,failed):
   q,host,_=self.fixture(editor)
   with self.assertRaises(LiveError):q.turn('输入')
   self.assertEqual(0,q.requests);self.assertEqual(1,len(host.calls));self.assertEqual(0,q.db.execute("SELECT count(*) FROM inquiry_events WHERE kind='delivered'").fetchone()[0])
 def test_source_change_during_edit_discards_complete_patch(self):
  q=None
  def changing(messages):
   value=self.edit(messages);old=next(iter(q.user_sources));new=q.record('user',{'text':'Corrected input','synthetic':True});q.dependencies.revise(old,new,'Concurrent correction');return value
  q,_,_=self.fixture(changing)
  with self.assertRaises(LiveError) as caught:q.turn('原始输入')
  self.assertEqual('sources_changed',caught.exception.kind);self.assertEqual(0,q.db.execute("SELECT count(*) FROM inquiry_events WHERE kind='delivered'").fetchone()[0])
 def test_insufficient_budget_never_starts_review_or_editor(self):
  def forbidden(messages):raise AssertionError('No editor allowance')
  q,_,calls=self.fixture(forbidden,budget=2);q.turn('输入');self.assertEqual([],calls);self.assertEqual(1,q.requests)
 def test_communication_history_excludes_unpublished_drafts_and_other_stories_on_resume(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'db';q=Inquiry(path,Host([answer('此前确实问过的问题。')]),synthetic=True)
   q.turn('先前的输入');story=q.story;private=q.record('reflection',{'synthetic':True,'reflection':answer('从未交付的草稿。')})
   opinion=q.record('epistemic_check',{'target':private,'phase':'before_delivery','issues':[{'quote':'从未交付的草稿。','reason':'A private check'}]});q.close()
   other=Inquiry(path,Host([answer('另一个故事。')]),synthetic=True);other.turn('另一件事');other.close()
   q=Inquiry(path,Host([]),synthetic=True,story=story)
   try:
    history=q.communication_history();self.assertEqual(['此前确实问过的问题。'],[i['answer'] for i in history['delivered']]);self.assertIn('not user facts',history['scope'])
    self.assertNotIn(private,q.history_context_events);self.assertNotIn(private,[m['event_seq'] for m in q.retrieve('从未交付的草稿')])
    self.assertNotIn(opinion,q.history_context_events)
    context=json.loads(q.db.execute("SELECT payload FROM inquiry_events WHERE run=? AND kind='story_context'",(q.run,)).fetchone()[0]);self.assertEqual(1,context['internal_replies_not_restored']);self.assertEqual(1,context['internal_critiques_not_restored'])
   finally:q.close()

if __name__=='__main__':unittest.main()
