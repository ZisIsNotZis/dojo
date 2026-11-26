import json
import hashlib
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from dojo.cli import main
from dojo.inquiry import Inquiry,validate_distillation
from dojo.live import LiveError
from dojo.maintenance import run_maintenance
from tests.test_stories import Host


def proposal(statement,event,quote,revises=None):
 return {'statement':statement,'kind':'decision','method':'hypothesis',
  'premises':[{'event':event,'quote':quote,'role':'assumption'}],
  'assumptions':[],'conditions':[],'alternatives':[],'falsifier':'New observations','revises':revises}


class MaintenanceTests(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'db'
 def tearDown(self):self.tmp.cleanup()
 def story(self,synthetic=True):
  q=Inquiry(self.path,Host(),synthetic=synthetic);q.turn('公共经验平台的目标与条件需要澄清。')
  story=q.story;q.close();return story
 def rows(self):
  db=sqlite3.connect(self.path)
  try:return db.execute('SELECT seq,run,kind,payload FROM inquiry_events ORDER BY seq').fetchall()
  finally:db.close()
 def factory(self,calls,fail_scribe=False):
  def make(config,*,content_validator=None):
   class Client:
    json_output=False
    def complete(inner,messages):
     calls.append(content_validator)
     if content_validator is validate_distillation and not fail_scribe:
      return {'intent':{'goals':[],'motivations':[],'inferred_needs':[],'unresolved':['Still a hypothesis']},'knowledge':[]}
     raise LiveError('Controlled failure',kind='connect')
   client=Client();client.config=config;return client
  return make
 def test_invalid_options_and_stories_do_not_read_credentials_or_modify_database(self):
  with patch('dojo.maintenance.config_from_pi') as config:
   with self.assertRaises(ValueError):run_maintenance(self.path,'missing')
   self.assertFalse(self.path.exists());config.assert_not_called()
  sid=self.story();before=self.path.read_bytes()
  for options in ({'max_requests':True},{'max_requests':13},{'max_tools':5},{'max_tools':-1},{'synthetic':False},{'retry_associations':1}):
   with patch('dojo.maintenance.config_from_pi') as config:
    with self.assertRaises(ValueError):run_maintenance(self.path,sid,**options)
    config.assert_not_called();self.assertEqual(before,self.path.read_bytes())
 def test_cpu_only_continuation_has_no_new_user_or_credentials(self):
  sid=self.story();before=self.rows()
  with patch('dojo.maintenance.config_from_pi') as config,patch('dojo.maintenance.make_client') as factory:
   result=run_maintenance(self.path,sid,synthetic=True,max_requests=0,max_tools=0)
   config.assert_not_called();factory.assert_not_called()
  self.assertEqual((0,0),(result['requests_used'],result['tools_used']))
  self.assertFalse(result['initial_distillation']['scheduled'])
  self.assertEqual(before,self.rows()[:len(before)])
  fresh=self.rows()[len(before):];self.assertNotIn('user',[row[2] for row in fresh])
  self.assertEqual('maintenance_pass',json.loads(fresh[-1][3])['reason'])
  self.assertEqual(sid,json.loads(next(row[3] for row in fresh if row[2]=='start'))['story'])
 def test_client_setup_failure_does_not_open_a_writable_run(self):
  sid=self.story();before=hashlib.sha256(self.path.read_bytes()).hexdigest()
  with patch('dojo.maintenance.config_from_pi',return_value=Host.config),patch('dojo.maintenance.make_client',side_effect=LiveError('setup failed',kind='config')):
   with self.assertRaises(LiveError):run_maintenance(self.path,sid,synthetic=True)
  self.assertEqual(before,hashlib.sha256(self.path.read_bytes()).hexdigest())
 def test_shared_model_budget_failure_suppression_and_explicit_retry(self):
  sid=self.story();calls=[]
  with patch('dojo.maintenance.config_from_pi',return_value=Host.config),patch('dojo.maintenance.make_client',side_effect=self.factory(calls,fail_scribe=True)):
   first=run_maintenance(self.path,sid,synthetic=True,max_requests=1,max_tools=0)
   self.assertEqual(1,first['requests_used']);self.assertEqual('failed',first['result']['distillation']['status'])
   self.assertEqual(1,calls.count(validate_distillation))
   second=run_maintenance(self.path,sid,synthetic=True,max_requests=1,max_tools=0)
   self.assertFalse(second['initial_distillation']['scheduled']);self.assertEqual(1,calls.count(validate_distillation))
   third=run_maintenance(self.path,sid,synthetic=True,max_requests=1,max_tools=0,retry_distillation=True)
   self.assertTrue(third['initial_distillation']['forced']);self.assertEqual(2,calls.count(validate_distillation))
   self.assertEqual(1,third['requests_used'])
 def test_new_material_reenables_initial_distillation_without_new_testimony_from_maintenance(self):
  sid=self.story();calls=[]
  with patch('dojo.maintenance.config_from_pi',return_value=Host.config),patch('dojo.maintenance.make_client',side_effect=self.factory(calls)):
   run_maintenance(self.path,sid,synthetic=True,max_requests=1,max_tools=0)
   q=Inquiry(self.path,Host(),story=sid,synthetic=True)
   try:q.turn('我补充一个新的取舍：低负担也很重要。')
   finally:q.close()
   before=sum(row[2]=='user' for row in self.rows())
   result=run_maintenance(self.path,sid,synthetic=True,max_requests=1,max_tools=0)
  self.assertTrue(result['initial_distillation']['needed']);self.assertEqual(2,calls.count(validate_distillation))
  self.assertEqual(before,sum(row[2]=='user' for row in self.rows()))
 def test_skipping_initial_distillation_does_not_skip_new_research_result_integration(self):
  sid=self.story();q=Inquiry(self.path,Host(),story=sid,synthetic=True,request_budget=2,tool_budget=1)
  calls=[];scribe=self.factory(calls)(Host.config,content_validator=validate_distillation)
  def research(q,client,**kwargs):
   q.requests-=1
   action={'kind':'calculate','expression':'2+3','basis':'A declared model','prediction':'5'}
   plan=q.record('reflection',{'synthetic':True,'reflection':{'answer':'Check a model','action':action}})
   event,receipt,_=q.execute_action(action,plan)
   self.assertEqual('executed',receipt['status'])
   return {'status':'executed','tool_event':event,'notice':None}
  try:
   with patch('dojo.research.perform',side_effect=research):
    result=q.maintain(Host(),scribe_client=scribe,research_client=Host(),max_requests=2,reserve_chat=False,distill_initial=False)
   self.assertEqual(2,result['requests_used']);self.assertEqual(1,calls.count(validate_distillation))
   self.assertEqual('distilled',result['research']['integration']['distillation']['status'])
  finally:q.close()
 def test_review_scope_excludes_unrelated_targets_but_carries_explicit_upstream_across_passes(self):
  old=Inquiry(self.path,Host(),synthetic=True)
  raw=old.record('user',{'text':'Old report','synthetic':True})
  first=old.knowledge.accept(old.run,proposal('First',raw,'Old report'),{raw},synthetic=True)
  other=old.knowledge.accept(old.run,proposal('Other',raw,'Old report'),{raw},synthetic=True)
  later=old.record('user',{'text':'Correction','synthetic':True});old.dependencies.revise(raw,later,'New report');old.close()
  q=Inquiry(self.path,Host(),synthetic=True);q.turn('公共经验平台的新问题。');sid=q.story
  try:
   self.assertEqual([],q.knowledge.review_candidates(synthetic=True,story=sid))
   self.assertEqual({first,other},{p['target'] for p in q.knowledge.review_candidates(synthetic=True)})
   action={'kind':'calculate','expression':'1+1','basis':'Declared example','prediction':'2'}
   plan=q.record('reflection',{'synthetic':True,'reflection':{'answer':'Check','action':action}})
   event,_,_=q.execute_action(action,plan)
   q.knowledge.request_review(q.run,first,[event],'Explicit upstream check',{first,event},synthetic=True)
   self.assertEqual([first],[p['target'] for p in q.knowledge.review_candidates(synthetic=True,story=sid)])
  finally:q.close()
  q=Inquiry(self.path,Host(),story=sid,synthetic=True)
  try:self.assertEqual([first],[p['target'] for p in q.knowledge.review_candidates(synthetic=True,story=sid)])
  finally:q.close()
 def test_scoped_review_finds_an_older_story_beyond_the_global_recent_pool(self):
  old=Inquiry(self.path,Host(),synthetic=True)
  raw=old.record('user',{'text':'Older report','synthetic':True})
  target=old.knowledge.accept(old.run,proposal('Older pending',raw,'Older report'),{raw},synthetic=True)
  newer=old.record('user',{'text':'Correction','synthetic':True});old.dependencies.revise(raw,newer,'Changed')
  sid=old.story;old_run=old.run;old.close()
  q=Inquiry(self.path,Host(),synthetic=True)
  try:
   raw=q.record('user',{'text':'Unrelated report','synthetic':True})
   # These unrelated rows only fill the retrieval pool; their statements are
   # distinct and all belong to another valid synthetic run.
   with q.db:
    q.db.executemany('INSERT INTO inquiry_events(run,kind,payload,at) VALUES(?,?,?,?)',[
     (q.run,'knowledge_proposal',json.dumps({'proposal':proposal('Unrelated '+str(i),raw,'Unrelated report'),
      'synthetic':True,'epistemic_status':'model_proposal_not_certified'}),'fixture') for i in range(501)])
   self.assertEqual([target],[p['target'] for p in q.knowledge.review_candidates(synthetic=True,story=sid)])
   # Current, non-pending rows in the selected story cannot hide its older
   # pending target either. These are temporary fixture rows, not live data.
   with q.db:
    q.db.executemany('INSERT INTO inquiry_events(run,kind,payload,at) VALUES(?,?,?,?)',[
     (old_run,'knowledge_proposal',json.dumps({'proposal':proposal('Current '+str(i),raw,'Unrelated report'),
      'synthetic':True,'epistemic_status':'model_proposal_not_certified'}),'fixture') for i in range(501)])
   self.assertEqual([target],[p['target'] for p in q.knowledge.review_candidates(synthetic=True,story=sid)])
  finally:q.close()
 def test_synthetic_maintenance_cannot_reopen_or_replace_ordinary_knowledge(self):
  real=Inquiry(self.path,Host(),synthetic=False)
  source=real.record('user',{'text':'Ordinary report','synthetic':False})
  target=real.knowledge.accept(real.run,proposal('Ordinary hypothesis',source,'Ordinary report'),{source},synthetic=False)
  newer=real.record('user',{'text':'New report','synthetic':False});real.dependencies.revise(source,newer,'Correction');real.close()
  q=Inquiry(self.path,Host(),synthetic=True)
  try:
   with self.subTest('candidate selection'):self.assertEqual([],q.knowledge.review_candidates(synthetic=True))
   raw=q.record('user',{'text':'Synthetic report','synthetic':True})
   action={'kind':'calculate','expression':'1+1','basis':'Synthetic model','prediction':'2'}
   plan=q.record('reflection',{'synthetic':True,'reflection':{'answer':'Check','action':action}});event,_,_=q.execute_action(action,plan)
   with self.subTest('review notice'):
    with self.assertRaises(ValueError):q.knowledge.request_review(q.run,target,[event],'Synthetic check',{target,event},synthetic=True)
   with self.subTest('replacement'):
    with self.assertRaises(ValueError):q.knowledge.accept(q.run,proposal('Synthetic replacement',raw,'Synthetic report',target),{raw,target},synthetic=True)
  finally:q.close()
 def test_direct_cross_identity_review_cannot_withdraw_or_record_unresolved(self):
  from dojo.reviews import apply_review
  real=Inquiry(self.path,Host(),synthetic=False)
  raw=real.record('user',{'text':'Ordinary report','synthetic':False})
  target=real.knowledge.accept(real.run,proposal('Ordinary hypothesis',raw,'Ordinary report'),{raw},synthetic=False)
  packet=real.knowledge.review_packet(target);real.close()
  q=Inquiry(self.path,Host(),synthetic=True)
  try:
   count=q.db.execute('SELECT count(*) FROM inquiry_events').fetchone()[0]
   for disposition in ('withdraw','unresolved'):
    with self.assertRaises(ValueError):apply_review(q,packet,{'disposition':disposition,'reason':'Must not cross identities','replacement':None})
   self.assertEqual(count,q.db.execute('SELECT count(*) FROM inquiry_events').fetchone()[0])
   self.assertEqual('current_interpretation',q.dependencies.status(target)['state'])
  finally:q.close()
 def test_question_and_relation_revision_boundaries_reject_cross_identity_proxy(self):
  from dojo.question_reviews import review_packet,apply_review
  real=Inquiry(self.path,Host(),synthetic=False)
  raw=real.record('user',{'text':'Ordinary question','synthetic':False})
  real.user_sources[raw]='Ordinary question';real.visible_source_text[raw]='Ordinary question'
  real.questions.apply(real,{'kind':'map_inquiry','questions':[{'key':'a','text':'What does this mean?',
   'parents':[],'origin_event':raw,'origin_quote':'Ordinary question','revises':None}],
   'links':[],'prediction':'Organize'})
  node=real.db.execute("SELECT seq FROM inquiry_events WHERE kind='inquiry_question'").fetchone()[0]
  real.visible_source_text[node]=real.knowledge.source(node)['text']
  link={'question':node,'proposition':None,'source_event':raw,'quote':'Ordinary question','relation':'context','explanation':'Reported context'}
  real.questions.apply(real,{'kind':'map_inquiry','questions':[],'links':[link],'prediction':'Connect'})
  annotation=real.db.execute("SELECT seq FROM inquiry_events WHERE kind='question_evidence'").fetchone()[0]
  packet=review_packet(real,annotation);sid=real.story;real.close()
  q=Inquiry(self.path,Host(),synthetic=True)
  try:
   count=q.db.execute('SELECT count(*) FROM inquiry_events').fetchone()[0]
   proxy=SimpleNamespace(story=sid,run=q.run,synthetic=True,dependencies=q.dependencies,
    user_sources={raw:'Ordinary question'},visible_source_text={raw:'Ordinary question',node:q.knowledge.source(node)['text']})
   with self.assertRaises(ValueError):q.questions.apply(proxy,{'kind':'map_inquiry','questions':[{
    'key':'new','text':'A new mixed-identity question','parents':[],'origin_event':raw,'origin_quote':'Ordinary question','revises':None}],
    'links':[],'prediction':'Must reject'})
   with self.assertRaises(ValueError):q.questions.apply(proxy,{'kind':'map_inquiry','questions':[{
    'key':'b','text':'Revised question','parents':[],'origin_event':raw,'origin_quote':'Ordinary question','revises':node}],
    'links':[],'prediction':'Must reject'})
   with self.assertRaises(ValueError):q.questions.apply(proxy,{'kind':'map_inquiry','questions':[],
    'links':[link],'prediction':'Must reject'},revises_link=annotation,revision_reason='Identity mismatch')
   with self.assertRaises(ValueError):apply_review(proxy,packet,{'disposition':'withdraw','reason':'Must reject','replacement':None})
   self.assertEqual(count,q.db.execute('SELECT count(*) FROM inquiry_events').fetchone()[0])
  finally:q.close()
 def test_cli_routes_a_zero_model_pass_without_prompting(self):
  import io
  sid=self.story();out=io.StringIO()
  with patch('sys.stdout',out),patch('builtins.input',side_effect=AssertionError('No input allowed')):
   code=main(['--db',str(self.path),'maintain','--story',sid,'--synthetic','--max-requests','0','--max-tools','0'])
  self.assertEqual(0,code);self.assertEqual(0,json.loads(out.getvalue())['requests_used'])
 def test_cli_explicit_association_retry_has_no_budget_bypass_or_implicit_distillation_retry(self):
  import io
  sid=self.story();out=io.StringIO();old=self.rows()
  with patch('sys.stdout',out),patch('dojo.maintenance.config_from_pi') as config:
   code=main(['--db',str(self.path),'maintain','--story',sid,'--synthetic','--max-requests','0','--max-tools','0','--retry-associations'])
   config.assert_not_called()
  summary=json.loads(out.getvalue())
  self.assertEqual(0,code);self.assertEqual(0,summary['requests_used'])
  self.assertTrue(summary['retry_associations']);self.assertFalse(summary['initial_distillation']['forced'])
  self.assertEqual(old,self.rows()[:len(old)])
  self.assertFalse(any(row[2]=='user' for row in self.rows()[len(old):]))

if __name__=='__main__':unittest.main()
