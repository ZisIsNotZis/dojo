import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from dojo.inquiry import Inquiry
from dojo.research import packet,perform,validate
from dojo.live import LiveError
from tests.test_knowledge import proposal


class ResearchTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'db'
  self.host=SimpleNamespace(config=SimpleNamespace(model='deepseek-flash',api_key=None))
  self.q=Inquiry(self.path,self.host,synthetic=True)
  self.user=self.q.record('user',{'text':'Check a fixed numeric condition','synthetic':True});self.q.user_sources[self.user]='Check a fixed numeric condition'
  self.target=self.q.knowledge.accept(self.q.run,proposal('Condition remains unknown',self.user,'condition'),{self.user},synthetic=True)
  self.q.visible_source_text[self.user]=self.q.knowledge.source(self.user)['text']
  action={'kind':'map_inquiry','questions':[{'key':'root','text':'Which numeric condition holds?','parents':[],'origin_event':self.user,'origin_quote':'condition','revises':None}],'links':[],'prediction':'Keep an open question'}
  self.question=self.q.questions.apply(self.q,action)['question_keys']['root']
 def tearDown(self):self.q.close();self.tmp.cleanup()
 def plan(self,**changes):
  return {'question':self.question,'target':self.target,'reason':'A fixed numeric check can distinguish the old hypothesis','action':{'kind':'calculate','expression':'0.3/2','basis':'Toy arithmetic only, not a user fact','prediction':'Expect 0.15; a different value changes the example'},**changes}
 def user_count(self):return self.q.db.execute("SELECT count(*) FROM inquiry_events WHERE kind='user'").fetchone()[0]
 def test_completed_tool_remains_in_agenda_even_when_no_knowledge_candidate_cites_it(self):
  plan=self.q.record('reflection',{'synthetic':True,'reflection':{'answer':'A fresh verification plan'}})
  event,_,_=self.q.execute_action({'kind':'calculate','expression':'0.3/2','basis':'INPUT_SENTINEL','prediction':'INPUT_SENTINEL'},plan)
  data=packet(self.q);self.assertIn(event,data['recent_tool_events'])
  source=next(s for s in data['sources'] if s['event']==event)
  self.assertIn('0.15',source['text']);self.assertNotIn('INPUT_SENTINEL',json.dumps(source))
  self.assertTrue(any(a['source_event']==event and a.get('observation_path')==['value'] for a in data['anchors']))
  _,receipt,_=self.q.execute_action({'kind':'calculate','expression':'1/0','basis':'An intentionally undefined fixture','prediction':'Failure is not evidence of success'},plan)
  self.assertEqual('failed',receipt['status']);latest=packet(self.q);failure=next(s for s in latest['sources'] if s['event']==self.q.tool_sources[-1]);self.assertIn('failed',failure['text'])
 def test_uncited_observation_survives_resume_and_still_filters_a_superseded_receipt(self):
  plan=self.q.record('reflection',{'synthetic':True,'reflection':{'answer':'A check not cited by the existing candidate'}})
  event,_,_=self.q.execute_action({'kind':'calculate','expression':'0.3/2','basis':'INPUT_SENTINEL','prediction':'INPUT_SENTINEL'},plan)
  old=self.q.db.execute('SELECT seq,payload FROM inquiry_events ORDER BY seq').fetchall()
  story=self.q.story;self.q.close();self.q=Inquiry(self.path,self.host,synthetic=True,story=story)
  self.assertIn(event,self.q.tool_sources)
  data=packet(self.q);self.assertIn(event,data['recent_tool_events'])
  source=next(s for s in data['sources'] if s['event']==event)
  self.assertIn('0.15',source['text']);self.assertNotIn('INPUT_SENTINEL',json.dumps(source))
  self.assertTrue(any(a['source_event']==event and a.get('observation_path')==['value'] for a in data['anchors']))
  self.assertEqual(old,self.q.db.execute('SELECT seq,payload FROM inquiry_events WHERE seq<=? ORDER BY seq',(old[-1][0],)).fetchall())
  newplan=self.q.record('reflection',{'synthetic':True,'reflection':{'answer':'Correct the numeric fixture'}})
  replacement,_,_=self.q.execute_action({'kind':'calculate','expression':'0.4/2','basis':'New fixed input','prediction':'0.2'},newplan)
  self.q.dependencies.revise(event,replacement,'Corrected fixture input')
  after=packet(self.q);self.assertNotIn(event,after['recent_tool_events']);self.assertIn(replacement,after['recent_tool_events'])
 def test_recent_observations_remain_bounded_and_do_not_import_foreign_or_map_receipts(self):
  self.q.tools=8;plan=self.q.record('reflection',{'synthetic':True,'reflection':{'answer':'Six small fixture checks'}})
  receipts=[]
  for n in range(6):
   event,_,_=self.q.execute_action({'kind':'calculate','expression':str(n)+'+1','basis':'Fixture only','prediction':'A finite integer'},plan)
   receipts.append(event)
  foreign=Inquiry(self.path,self.host,synthetic=True)
  try:
   fp=foreign.record('reflection',{'synthetic':True,'reflection':{'answer':'Different story'}})
   external,_,_=foreign.execute_action({'kind':'calculate','expression':'99','basis':'Foreign fixture','prediction':'99'},fp)
  finally:foreign.close()
  self.q.tool_sources.append(external)
  action={'kind':'map_inquiry','questions':[{'key':'extra','text':'Another framing?', 'parents':[],'origin_event':self.user,'origin_quote':'condition','revises':None}],'links':[],'prediction':'Organization is not an observation'}
  mapped,receipt,_=self.q.execute_action(action,plan);self.assertEqual('executed',receipt['status'])
  data=packet(self.q)
  self.assertEqual(list(reversed(receipts[-4:])),data['recent_tool_events'])
  self.assertNotIn(external,[s['event'] for s in data['sources']]);self.assertNotIn(mapped,[s['event'] for s in data['sources']])
 def test_multiple_uncited_receipts_keep_task_identity_across_resume_and_do_not_buy_another_deferral(self):
  plan=self.q.record('reflection',{'synthetic':True,'reflection':{'answer':'Two completed checks, not knowledge premises'}})
  receipts=[]
  for expression in ('1+1','2+2'):
   event,_,_=self.q.execute_action({'kind':'calculate','expression':expression,'basis':'Fixture','prediction':'Finite sum'},plan)
   receipts.append(event)
  before=packet(self.q);self.assertEqual(list(reversed(receipts)),before['recent_tool_events'])
  self.assertEqual('deferred',perform(self.q,SimpleNamespace(complete=lambda m:self.plan(action=None,reason='No further discriminating step in the fixture')),max_requests=3)['status'])
  postponed=packet(self.q)
  story=self.q.story;self.q.close();self.q=Inquiry(self.path,self.host,synthetic=True,story=story,request_budget=9)
  after=packet(self.q)
  self.assertEqual(postponed['sha256'],after['sha256']);self.assertEqual(before['recent_tool_events'],after['recent_tool_events'])
  def forbidden(messages):raise AssertionError('Restoration order is not new evidence')
  self.assertEqual('unchanged',perform(self.q,SimpleNamespace(complete=forbidden),max_requests=9)['status'])
  self.assertEqual(9,self.q.requests)
 def add_sibling(self):
  result=self.q.questions.apply(self.q,{'kind':'map_inquiry','questions':[{'key':'other','text':'Can another conditional check distinguish explanations?',
   'parents':[],'origin_event':self.user,'origin_quote':'condition','revises':None}],'links':[],'prediction':'Independent open topic'})
  return result['question_keys']['other']
 def resume(self):
  story=self.q.story;self.q.close();self.q=Inquiry(self.path,self.host,synthetic=True,story=story,request_budget=3,tool_budget=2)
 def test_one_postponed_question_does_not_block_other_question_or_change_user_records(self):
  sibling=self.add_sibling();users=self.user_count()
  self.assertEqual('deferred',perform(self.q,SimpleNamespace(complete=lambda m:self.plan(action=None,reason='This topic needs physical observation')),max_requests=3)['status'])
  self.resume();shown=packet(self.q)
  self.assertNotIn(self.question,[n['event'] for n in shown['questions']]);self.assertIn(sibling,[n['event'] for n in shown['questions']])
  self.assertEqual(self.question,shown['deferred_questions'][0]['question'])
  result=perform(self.q,SimpleNamespace(complete=lambda m:self.plan(question=sibling,target=None)),max_requests=3)
  self.assertEqual('executed',result['status']);self.assertEqual(sibling,result['question']);self.assertEqual(users,self.user_count())
  self.assertEqual(2,self.q.requests)
 def test_all_postponed_makes_no_call_and_new_observation_reopens_topics(self):
  sibling=self.add_sibling()
  perform(self.q,SimpleNamespace(complete=lambda m:self.plan(action=None)),max_requests=3)
  self.resume();perform(self.q,SimpleNamespace(complete=lambda m:self.plan(question=sibling,action=None)),max_requests=3)
  self.resume()
  def forbidden(messages):raise AssertionError('All current topics already postponed')
  result=perform(self.q,SimpleNamespace(complete=forbidden),max_requests=3)
  self.assertEqual('all_questions_deferred_for_current_material',result['reason']);self.assertEqual(3,self.q.requests)
  plan=self.q.record('reflection',{'synthetic':True,'reflection':{'answer':'New observed fixture result'}})
  self.q.execute_action({'kind':'calculate','expression':'2+3','basis':'New fixture input','prediction':'5'},plan)
  self.assertEqual({self.question,sibling},{n['event'] for n in packet(self.q)['questions']})
 def test_legacy_defer_is_scoped_by_exact_packet_and_deferred_target_cannot_execute(self):
  sibling=self.add_sibling();old=packet(self.q)
  foreign=Inquiry(self.path,self.host,synthetic=True)
  try:foreign.record('research_step',{'packet_sha256':old['sha256'],'status':'deferred','question':self.question,'target':None,'reason':'Copied from another story'})
  finally:foreign.close()
  self.assertEqual(old['sha256'],packet(self.q)['sha256'])
  self.q.record('research_step',{'packet_sha256':old['sha256'],'status':'deferred','question':self.question,'target':None,'reason':'Legacy fixture record'})
  data=packet(self.q)
  self.assertEqual([sibling],[n['event'] for n in data['questions']])
  tools=self.q.tools
  result=perform(self.q,SimpleNamespace(complete=lambda m:self.plan()),max_requests=3)
  self.assertEqual('failed',result['status']);self.assertEqual(tools,self.q.tools)
 def test_step_executes_without_fabricating_user_and_opens_review_with_actual_result(self):
  users=self.user_count();before=self.q.requests;tools=self.q.tools
  result=perform(self.q,SimpleNamespace(complete=lambda m:self.plan()),max_requests=3)
  self.assertEqual('executed',result['status']);self.assertEqual(before-1,self.q.requests);self.assertEqual(tools-1,self.q.tools)
  self.assertEqual(users,self.user_count());self.assertEqual('requested',result['notice']['status'])
  self.assertEqual('needs_review',self.q.dependencies.status(self.target)['state'])
  receipt=json.loads(self.q.db.execute('SELECT payload FROM inquiry_events WHERE seq=?',(result['tool_event'],)).fetchone()[0])
  self.assertEqual(0.15,receipt['result']['value'])
  plan=json.loads(self.q.db.execute("SELECT payload FROM inquiry_events WHERE kind='reflection' ORDER BY seq DESC LIMIT 1").fetchone()[0])
  self.assertEqual(self.target,plan['research_target'])
  self.assertFalse(self.q.dependencies.depends_on(result['tool_event'],self.target))
  self.assertEqual('run_limit',perform(self.q,SimpleNamespace(complete=lambda m: (_ for _ in ()).throw(AssertionError())),max_requests=3)['status'])
 def test_deferral_is_bounded_and_budget_change_does_not_retry_same_packet(self):
  client=SimpleNamespace(complete=lambda m:self.plan(action=None,reason='A physical observation is missing; no executable discriminating step'))
  self.assertEqual('deferred',perform(self.q,client,max_requests=3)['status'])
  story=self.q.story;self.q.close();self.q=Inquiry(self.path,self.host,synthetic=True,story=story,request_budget=9)
  def forbidden(messages):raise AssertionError('Same input must not buy another request')
  self.assertEqual('unchanged',perform(self.q,SimpleNamespace(complete=forbidden),max_requests=9)['status']);self.assertEqual(9,self.q.requests)
 def test_invalid_targets_or_organization_action_execute_nothing(self):
  for index,update in enumerate([{'question':99999},{'target':99999},{'action':{'kind':'map_inquiry','questions':[],'links':[],'prediction':'Not verification'}}]):
   with self.subTest(update=update):
    # Separate runs AND explicit new fixture input make a genuinely new packet.
    story=self.q.story;self.q.close();self.q=Inquiry(self.path,self.host,synthetic=True,story=story)
    event=self.q.record('user',{'text':'Additional fixture condition '+str(index),'synthetic':True});self.q.user_sources[event]='Additional fixture condition '+str(index)
    result=perform(self.q,SimpleNamespace(complete=lambda m:self.plan(**update)),max_requests=3)
    self.assertEqual('failed',result['status'])
  self.assertEqual(0,self.q.db.execute("SELECT count(*) FROM inquiry_events WHERE kind='tool_started'").fetchone()[0])
 def test_source_change_while_planning_discards_step_before_tool_execution(self):
  value=self.plan()
  def complete(messages):
   new=self.q.record('user',{'text':'Changed condition','synthetic':True})
   self.q.dependencies.revise(self.user,new,'Input changed during planning')
   return value
  self.assertEqual('discarded',perform(self.q,SimpleNamespace(complete=complete),max_requests=3)['status'])
  self.assertEqual(0,self.q.db.execute("SELECT count(*) FROM inquiry_events WHERE kind='tool_started'").fetchone()[0])
 def test_text_internal_requests_cannot_borrow_outside_step_integration_reserve(self):
  action={'kind':'text_experiment','source_events':[self.user],'probes':[{'question':'What is being checked?','event':self.user,'quote':'numeric condition'}],'prediction':'Only literal retention, not semantic correctness'}
  tools=self.q.tools;requests=self.q.requests
  packets=[]
  result=perform(self.q,SimpleNamespace(complete=lambda m:(packets.append(json.loads(m[-1]['content'])) or self.plan(action=action))),max_requests=3)
  self.assertNotIn('text_experiment',[t['name'] for t in packets[0]['verification_tools']])
  self.assertEqual(0,packets[0]['budget']['tool_internal_requests_available'])
  self.assertEqual('failed',result['status']);self.assertEqual(tools,self.q.tools);self.assertEqual(requests-1,self.q.requests)
  self.assertEqual(0,self.q.db.execute("SELECT count(*) FROM inquiry_events WHERE kind='tool_started'").fetchone()[0])
 def test_text_experiment_is_available_when_planning_tool_and_integration_fit(self):
  packets=[]
  result=perform(self.q,SimpleNamespace(complete=lambda m:(packets.append(json.loads(m[-1]['content'])) or self.plan(action=None))),max_requests=7)
  self.assertEqual('deferred',result['status']);self.assertIn('text_experiment',[t['name'] for t in packets[0]['verification_tools']]);self.assertEqual(4,packets[0]['budget']['tool_internal_requests_available'])
 def test_hidden_urls_and_insufficient_budget_never_invoke_tools(self):
  def forbidden(messages):raise AssertionError('Insufficient integration allowance')
  self.assertEqual('budget',perform(self.q,SimpleNamespace(complete=forbidden),max_requests=2)['status'])
  action={'kind':'read_source','url':'https://not-shown.example/paper','prediction':'Cannot treat an unprovided URL as read'}
  result=perform(self.q,SimpleNamespace(complete=lambda m:self.plan(action=action)),max_requests=3)
  self.assertEqual('failed',result['status']);self.assertEqual(0,self.q.db.execute("SELECT count(*) FROM inquiry_events WHERE kind='tool_started'").fetchone()[0])
 def test_normal_maintenance_integrates_follow_up_with_same_budget_and_no_user_record(self):
  calls=[]
  researcher=SimpleNamespace(complete=lambda m:(calls.append(m) or self.plan()))
  def review(messages):
   data=json.loads(messages[-1]['content']);source=next(s for s in data['sources'] if s['kind']=='tool_result')
   return {'disposition':'replace','reason':'Only this conditional arithmetic instance was checked','replacement':proposal('The checked number is 0.15',source['event'],'"value": 0.15',revises=data['target'])}
  reviewer=SimpleNamespace(complete=review);users=self.user_count();requests=self.q.requests
  chat=self.q.maintain(reviewer,research_client=researcher,max_requests=4,reserve_chat=True)
  self.assertNotIn('research',chat);self.assertEqual([],calls)
  result=self.q.maintain(reviewer,research_client=researcher,max_requests=3,reserve_chat=False)
  self.assertEqual(2,result['requests_used']);self.assertEqual(requests-2,self.q.requests)
  self.assertEqual('executed',result['research']['status']);self.assertEqual('superseded',self.q.dependencies.status(self.target)['state'])
  self.assertEqual(users,self.user_count());self.assertEqual(1,len(calls))
 def test_existing_question_without_candidate_can_still_receive_a_plan(self):
  other=Inquiry(self.path,self.host,synthetic=True)
  try:
   user=other.record('user',{'text':'Check a ratio','synthetic':True});other.user_sources[user]='Check a ratio';other.visible_source_text[user]='Check a ratio'
   action={'kind':'map_inquiry','questions':[{'key':'root','text':'What is the fixed ratio?','parents':[],'origin_event':user,'origin_quote':'ratio','revises':None}],'links':[],'prediction':'An existing problem without a candidate'}
   question=other.questions.apply(other,action)['question_keys']['root']
   data=packet(other);self.assertEqual([],data['candidate_events'])
   client=SimpleNamespace(complete=lambda m:{**self.plan(question=question,target=None)})
   self.assertEqual('executed',perform(other,client,max_requests=3)['status'])
  finally:other.close()
 def test_cli_eof_runs_the_hook_without_an_extra_user_message(self):
  import io
  from unittest.mock import patch
  from dojo.inquiry import run_inquiry,validate_host
  real=Inquiry(self.path,self.host,synthetic=False)
  user=real.record('user',{'text':'Fixture goal: check this numeric condition','synthetic':False});real.user_sources[user]='Fixture goal: check this numeric condition';real.visible_source_text[user]=real.knowledge.source(user)['text']
  target=real.knowledge.accept(real.run,proposal('Fixture unresolved numeric condition',user,'numeric condition'),{user},synthetic=False)
  action={'kind':'map_inquiry','questions':[{'key':'root','text':'Which numeric condition holds?','parents':[],'origin_event':user,'origin_quote':'numeric condition','revises':None}],'links':[],'prediction':'Fixture organization, not a human research observation'}
  question=real.questions.apply(real,action)['question_keys']['root'];story=real.story;real.close()
  host=SimpleNamespace(config=self.host.config,complete=lambda m:validate_host('{"answer":"Continue the saved goal.","action":null}'))
  def review(messages):
   data=json.loads(messages[-1]['content']);source=next(s for s in data['sources'] if s['kind']=='tool_result')
   return {'disposition':'replace','reason':'Fixture check now has a numeric receipt','replacement':proposal('Fixture result is 0.15',source['event'],'0.15',revises=data['target'])}
  reviewer=SimpleNamespace(config=self.host.config,complete=review)
  scribe=SimpleNamespace(config=self.host.config,complete=lambda m:{'intent':{'goals':[],'motivations':[],'inferred_needs':[],'unresolved':[]},'knowledge':[]})
  critic=SimpleNamespace(config=self.host.config,complete=lambda m:{'issues':[]})
  associations=SimpleNamespace(config=self.host.config,complete=lambda m:{'questions':[],'links':[],'reason':'Fixture has enough organization'})
  researcher=SimpleNamespace(config=self.host.config,complete=lambda m:self.plan(question=question,target=target))
  values=iter(['Continue the fixture goal'])
  def read(prompt):
   try:return next(values)
   except StopIteration:raise EOFError()
  with patch('dojo.inquiry.config_from_pi',return_value=self.host.config),patch('dojo.inquiry.make_client',side_effect=[host,reviewer,scribe,critic,reviewer,associations,researcher]):
   self.assertEqual(0,run_inquiry(self.path,story=story,read_line=read,output=io.StringIO()))
  run=self.q.db.execute("SELECT run FROM inquiry_events WHERE kind='research_request_started' ORDER BY seq DESC LIMIT 1").fetchone()[0]
  self.assertEqual(1,self.q.db.execute("SELECT count(*) FROM inquiry_events WHERE run=? AND kind='user'",(run,)).fetchone()[0])
  self.assertEqual(1,self.q.db.execute("SELECT count(*) FROM inquiry_events WHERE run=? AND kind='research_step'",(run,)).fetchone()[0])
 def test_new_research_observation_is_the_focus_of_distillation_and_coverage_is_explicit(self):
  packets=[];empty={'goals':[],'motivations':[],'inferred_needs':[],'unresolved':[]}
  def scribe(messages):
   data=json.loads(messages[-1]['content']);packets.append(data)
   if not data.get('focus_events'):return {'intent':empty,'knowledge':[]}
   event=data['focus_events'][0]
   self.assertEqual(event,data['sources'][0]['event']);self.assertEqual('tool_result',data['sources'][0]['kind'])
   return {'intent':empty,'knowledge':[proposal('A conditional ratio is 0.15',event,'"value": 0.15')]}
  researcher=SimpleNamespace(complete=lambda m:self.plan(target=None))
  before=self.q.requests;users=self.user_count()
  result=self.q.maintain(self.host,scribe_client=SimpleNamespace(complete=scribe),research_client=researcher,max_requests=5,reserve_chat=False)
  research=result['research'];distilled=research['integration']['distillation'];coverage=distilled['focus_coverage'][0]
  self.assertEqual(research['tool_event'],coverage['event']);self.assertEqual('represented',coverage['status']);self.assertEqual(distilled['proposal_events'],coverage['evidence_proposal_events'])
  self.assertEqual(3,result['requests_used']);self.assertEqual(before-3,self.q.requests);self.assertEqual(users,self.user_count());self.assertEqual(2,len(packets))
 def test_empty_focused_distillation_does_not_claim_the_new_observation_was_saved_as_knowledge(self):
  step=perform(self.q,SimpleNamespace(complete=lambda m:self.plan(target=None)),max_requests=3)
  client=SimpleNamespace(complete=lambda m:{'intent':{'goals':[],'motivations':[],'inferred_needs':[],'unresolved':[]},'knowledge':[]})
  result=self.q.distill(client,focus_events=[step['tool_event']])
  self.assertEqual('unrepresented',result['focus_coverage'][0]['status']);self.assertEqual([],result['proposal_events'])
  self.assertEqual('unchanged',self.q.distill(client,focus_events=[step['tool_event']])['status'])
  before=self.q.requests
  with self.assertRaises(ValueError):self.q.distill(client,focus_events=[999999])
  self.assertEqual(before,self.q.requests)
 def test_single_argument_wrapper_is_lossless_but_missing_or_extra_fields_still_fail(self):
  flat=self.plan();nested={**flat,'action':{'kind':'calculate','parameters':{k:v for k,v in flat['action'].items() if k!='kind'}}}
  self.assertEqual(flat,validate(json.dumps(nested)))
  result=perform(self.q,SimpleNamespace(complete=lambda m:nested),max_requests=3)
  receipt=json.loads(self.q.db.execute('SELECT payload FROM inquiry_events WHERE seq=?',(result['tool_event'],)).fetchone()[0])
  self.assertEqual(flat['action'],receipt['action']);self.assertEqual(0.15,receipt['result']['value'])
  for arguments in [{'expression':'1+1'},{'expression':'1+1','basis':'assumed','prediction':'2','shell':'forbidden'}]:
   with self.assertRaises(LiveError):validate(json.dumps({**flat,'action':{'kind':'calculate','parameters':arguments}}))
  malformed={**flat,'action':{'kind':'experiment','parameters':{'x':[1]}}}
  with self.assertRaises(LiveError) as caught:validate(json.dumps(malformed))
  self.assertEqual('tool_fields',caught.exception.validation_code)

if __name__=='__main__':unittest.main()
