import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from dojo.inquiry import Inquiry,run_inquiry,validate_host
from dojo.stories import listing,prepare_resume

class Host:
 config=SimpleNamespace(model='deepseek-flash',api_key=None)
 def __init__(self):self.seen=[]
 def complete(self,messages):
  self.seen.append(json.loads(json.dumps(messages)))
  return validate_host('{"answer":"公共经验平台需要继续核实条件，原目标不变。","action":null}')

class StoryTests(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'db'
 def tearDown(self):self.tmp.cleanup()
 def create(self,synthetic=True):
  q=Inquiry(self.path,Host(),synthetic=synthetic);q.turn('我想做公共经验平台，帮助陌生人接续判断。')
  return q
 def test_resume_restores_original_goal_without_keyword_match_and_has_bounded_new_budget(self):
  old=self.create();story=old.story;origin=next(iter(old.user_sources));oldrun=old.run;old.close()
  host=Host();q=Inquiry(self.path,host,synthetic=True,story=story)
  try:
   self.assertEqual((12,4),(q.requests,q.tools));self.assertNotEqual(oldrun,q.run)
   self.assertIn(origin,q.user_sources);q.turn('继续。')
   self.assertIn('帮助陌生人',json.dumps(host.seen[0],ensure_ascii=False))
   self.assertTrue(q.dependencies.depends_on(q.last_reflection,origin))
   packet=json.loads(q.db.execute("SELECT payload FROM inquiry_events WHERE run=? AND kind='story_context'",(q.run,)).fetchone()[0])
   self.assertIn(origin,[s['event'] for s in packet['sources']]);self.assertEqual(oldrun,packet['previous_run'])
   q.check_intent({'goals':[{'text':'帮助陌生人','source_event':origin,'quote':'帮助陌生人'}],'motivations':[]})
   self.assertEqual(2,listing(self.path,synthetic=True)[0]['run_count'])
  finally:q.close()
 def test_cross_story_borrowing_does_not_restore_intent_ownership(self):
  old=self.create();origin=next(iter(old.user_sources));old.close()
  q=Inquiry(self.path,Host(),synthetic=True)
  try:
   q.turn('公共经验平台这次只看检索')
   self.assertIn(origin,q.visible_source_text);self.assertNotIn(origin,q.user_sources)
   from dojo.live import LiveError
   with self.assertRaises(LiveError):q.check_intent({'goals':[{'source_event':origin,'quote':'帮助陌生人'}],'motivations':[]})
  finally:q.close()
 def test_invalid_resume_or_synthetic_mismatch_never_mutates_database(self):
  with patch('dojo.inquiry.config_from_pi') as config:
   with self.assertRaises(ValueError):run_inquiry(self.path,story='absent')
   config.assert_not_called()
  self.assertFalse(self.path.exists())
  q=self.create();story=q.story;q.close();before=self.path.read_bytes()
  for sid,syn in (('unknown',True),(story,False)):
   with self.assertRaises(ValueError):Inquiry(self.path,Host(),story=sid,synthetic=syn)
   self.assertEqual(before,self.path.read_bytes())
 def test_legacy_start_events_resolve_without_rewriting_them(self):
  q=self.create();run=q.run
  row=q.db.execute("SELECT seq,payload FROM inquiry_events WHERE kind='start'").fetchone()
  value=json.loads(row[1]);value.pop('story');value.pop('continued_from')
  q.db.execute('UPDATE inquiry_events SET payload=? WHERE seq=?',(json.dumps(value),row[0]));q.db.commit();q.close()
  before=self.path.read_bytes();plan=prepare_resume(self.path,run,synthetic=True)
  self.assertEqual(run,plan['story']);self.assertEqual(before,self.path.read_bytes())
 def test_resumed_search_whitelist_comes_only_from_actual_successful_receipts(self):
  q=self.create();story=q.story
  for status,url in (('executed','https://example.org/real'),('failed','https://example.org/fake')):
   q.record('tool_result',{'action':{'kind':'search'},'status':status,'result':{'sources':[{'url':url,'title':'材料'}]}})
  q.close();resumed=Inquiry(self.path,Host(),synthetic=True,story=story)
  try:self.assertEqual({'https://example.org/real'},resumed.known_source_urls)
  finally:resumed.close()
 def test_pending_model_critique_is_restored_as_opinion_and_cannot_become_evidence(self):
  q=self.create();story=q.story
  class Critic(Host):
   def complete(self,messages):return {'issues':[{'quote':'原目标不变','kind':'unsupported_fact','reason':'需要按后续原话确认','counterexample':'假设用户改变目标','rewrite':'按当前已见原话保留目标，仍可改变'}]}
  checked=q.inspect_reply(Critic());opinion=checked['event'];q.close()
  q=Inquiry(self.path,Host(),synthetic=True,story=story)
  try:
   self.assertIn(opinion,q.history_context_events)
   self.assertEqual('model_critique_not_truth_verdict',q.knowledge.source(opinion)['epistemic_status'])
   proposal={'statement':'不应把意见当事实','kind':'question','method':'hypothesis','premises':[{'event':opinion,'quote':'原目标不变','role':'evidence'}],'assumptions':[],'conditions':[],'alternatives':[],'falsifier':'来源变化','revises':None}
   with self.assertRaisesRegex(ValueError,'invalid source kind'):q.knowledge.accept(q.run,proposal,q.visible_source_text,synthetic=True)
   q.turn('继续');self.assertTrue(q.dependencies.depends_on(q.last_reflection,opinion))
  finally:q.close()
 def test_large_history_reports_omissions_and_preserves_root_source(self):
  q=self.create();story=q.story;origin=next(iter(q.user_sources))
  for i in range(20):q.record('user',{'text':str(i)+'后续材料'*2000,'synthetic':True})
  q.close();q=Inquiry(self.path,Host(),synthetic=True,story=story)
  try:
   packet=json.loads(q.db.execute("SELECT payload FROM inquiry_events WHERE run=? AND kind='story_context'",(q.run,)).fetchone()[0])
   self.assertGreater(packet['source_events_omitted'],0);self.assertIn(origin,q.user_sources)
   self.assertLess(len(q.messages[-1]['content']),62000)
  finally:q.close()
 def test_listing_is_read_only_and_synthetic_is_not_visible_by_default(self):
  self.assertEqual([],listing(self.path));self.assertFalse(self.path.exists())
  q=self.create();story=q.story;q.close();before=hashlib.sha256(self.path.read_bytes()).hexdigest()
  self.assertEqual([],listing(self.path));self.assertEqual(story,listing(self.path,synthetic=True)[0]['story'])
  for args in (('stories',),('stories','--synthetic'),('stories',story,'--synthetic')):
   r=subprocess.run([sys.executable,'-X','utf8','-m','dojo','--db',str(self.path),*args],capture_output=True,text=True,encoding='utf-8',timeout=20)
   self.assertEqual(0,r.returncode,r.stderr);json.loads(r.stdout)
  self.assertEqual(before,hashlib.sha256(self.path.read_bytes()).hexdigest())
 def test_listing_orders_by_latest_continuation_and_eof_without_input_costs_no_request(self):
  a=self.create(synthetic=False);story=a.story;a.close()
  b=self.create(synthetic=False);b.close()
  class NoRequest(Host):
   def complete(self,messages):raise AssertionError('no new input must not buy maintenance')
  def eof(prompt):raise EOFError()
  with patch('dojo.inquiry.config_from_pi',return_value=Host.config),patch('dojo.inquiry.make_client',side_effect=[NoRequest() for _ in range(7)]):
   run_inquiry(self.path,story=story,read_line=eof,output=io.StringIO())
  self.assertEqual(story,listing(self.path)[0]['story'])
 def test_resume_catalog_does_not_repeat_full_original_source_in_retrieval(self):
  original='UNIQUE_ORIGINAL_SENTINEL '+('经验材料'*1500)
  q=Inquiry(self.path,Host(),synthetic=True);q.turn(original);story=q.story;q.close()
  host=Host();q=Inquiry(self.path,host,synthetic=True,story=story)
  try:
   q.turn('公共经验平台继续')
   joined=json.dumps(host.seen[0],ensure_ascii=False)
   self.assertEqual(1,joined.count('UNIQUE_ORIGINAL_SENTINEL'))
   packet=json.loads(host.seen[0][-1]['content'])
   self.assertTrue(packet['prior_unverified_inquiries']);self.assertEqual([],packet['source_catalog'])
  finally:q.close()
 def test_late_user_correction_is_explicitly_not_covered_by_old_intent(self):
  q=self.create();story=q.story
  snapshot=q.record('distillation',{'intent':{'goals':[],'motivations':[],'inferred_needs':['An early guess'],'unresolved':[]},'intent_status':'accepted'})
  correction=q.record('user',{'text':'我不是要纪要，是希望普通人的经验自然帮到陌生人。','synthetic':True});q.close()
  plan=prepare_resume(self.path,story,synthetic=True);self.assertEqual(snapshot,plan['intent_snapshot_event']);self.assertEqual('new_user_input_pending',plan['intent_snapshot_state']);self.assertEqual([correction],plan['user_events_after_intent'])
  self.assertEqual([correction],listing(self.path,synthetic=True,story=story)[0]['user_events_after_intent'])
  q=Inquiry(self.path,Host(),synthetic=True,story=story)
  try:
   context=json.loads(q.db.execute("SELECT payload FROM inquiry_events WHERE run=? AND kind='story_context'",(q.run,)).fetchone()[0]);self.assertEqual([correction],context['user_events_after_intent']);self.assertIn(correction,q.user_sources)
   from dojo.research import packet
   # A current question makes the bounded research packet available.
   q.questions.apply(q,{'kind':'map_inquiry','questions':[{'key':'root','text':'How does this corrected goal change the design?','parents':[],'origin_event':correction,'origin_quote':'普通人的经验','revises':None}],'links':[],'prediction':'Keep the correction visible'})
   research=packet(q);self.assertEqual('new_user_input_pending',research['intent_snapshot_state']);self.assertEqual([correction],research['user_events_after_intent'])
   q.record('distillation',{'intent':{'goals':[],'motivations':[],'inferred_needs':[],'unresolved':[]},'intent_status':'accepted'})
   refreshed=prepare_resume(self.path,story,synthetic=True);self.assertEqual('no_later_user_input',refreshed['intent_snapshot_state']);self.assertEqual([],refreshed['user_events_after_intent'])
  finally:q.close()
if __name__=='__main__':unittest.main()
