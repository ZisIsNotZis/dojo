import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from dojo.inquiry import Inquiry,validate_host
from dojo.associations import apply,packet,perform
from tests.test_knowledge import proposal


class Host:
 config=SimpleNamespace(model='deepseek-flash',api_key=None)
 def complete(self,messages):return validate_host('{"answer":"Continue under the saved model conditions.","action":null}')


class AssociationTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'db';self.q=Inquiry(self.path,Host(),synthetic=True)
  self.user=self.q.record('user',{'text':'Understand when caching reduces mean time','synthetic':True})
  self.q.user_sources[self.user]='Understand when caching reduces mean time'
  plan=self.q.record('reflection',{'synthetic':True,'reflection':{'answer':'Plan a finite calculation'}})
  self.source,_,_=self.q.execute_action({'kind':'calculate','expression':'0.3/2','basis':'MODEL_ONLY_BASIS','prediction':'Expect 0.15'},plan)
  self.p=proposal('Under fixed overhead, the numerical threshold example is 0.15',self.source,'"value": 0.15')
  self.claim=self.q.knowledge.accept(self.q.run,self.p,{self.source},synthetic=True)
  for event in [self.user,self.source,self.claim]:self.q.visible_source_text[event]=self.q.knowledge.source(event)['text']
  result=self.q.questions.apply(self.q,{'kind':'map_inquiry','questions':[{'key':'root','text':'When is caching beneficial in the toy model?','parents':[],'origin_event':self.user,'origin_quote':'caching reduces mean time','revises':None}],'links':[],'prediction':'Keep the question open'})
  self.node=result['question_keys']['root']
 def tearDown(self):self.q.close();self.tmp.cleanup()
 def response(self,**changes):
  anchor=next(a['anchor'] for a in packet(self.q)['anchors'] if a['source_event']==self.source and a['quote']=='"value": 0.15')
  return {'questions':[],'links':[{'question':self.node,'proposition':self.claim,'anchor':anchor,'relation':'supports','explanation':'Only the actual numeric example, not empirical latency',**changes}],'reason':'Connect the existing conditional proposal to its model question'}
 def annotations(self):return [a for n in self.q.questions.view(story=self.q.story,synthetic=True)['nodes'] for a in n['annotations']]
 def test_budgeted_backfill_has_real_provenance_no_new_knowledge_and_no_self_trigger(self):
  calls=[]
  def complete(messages):calls.append(messages);return self.response()
  before=packet(self.q)['sha256'];budget=self.q.requests
  result=perform(self.q,SimpleNamespace(complete=complete))
  self.assertEqual('associated',result['status']);self.assertEqual(1,len(result['new_annotation_events']))
  self.assertEqual(budget-1,self.q.requests);self.assertEqual(before,packet(self.q)['sha256'])
  self.assertEqual(1,len(self.q.knowledge.proposals(synthetic=True)))
  self.assertEqual('unchanged',perform(self.q,SimpleNamespace(complete=complete))['status']);self.assertEqual(1,len(calls))
  self.assertEqual(self.source,self.annotations()[0]['source_event'])
  self.assertEqual('agent_organization_not_truth_verdict',self.annotations()[0]['epistemic_status'])
 def test_invalid_second_link_rejects_all_and_failure_packet_does_not_retry(self):
  response=self.response();response['links'].append({**response['links'][0],'anchor':999999})
  client=SimpleNamespace(complete=lambda m:response)
  self.assertEqual('failed',perform(self.q,client)['status']);self.assertEqual([],self.annotations())
  self.assertEqual('unchanged',perform(self.q,client)['status'])
 def test_source_revision_during_model_request_discards_old_response(self):
  response=self.response()
  def complete(messages):
   new=self.q.record('tool_result',{'status':'executed','result':{'value':0.2}})
   self.q.dependencies.revise(self.source,new,'Correct actual observation')
   return response
  self.assertEqual('discarded',perform(self.q,SimpleNamespace(complete=complete))['status']);self.assertEqual([],self.annotations())
 def test_model_basis_is_context_only_not_observation(self):
  client=SimpleNamespace(complete=lambda m:self.response(anchor=999999))
  self.assertEqual('failed',perform(self.q,client)['status']);self.assertEqual([],self.annotations())
  material=next(s for s in packet(self.q)['sources'] if s['event']==self.source)
  self.assertNotIn('MODEL_ONLY_BASIS',material['text']);self.assertNotIn('basis',material['input_context'])
  self.assertFalse(any('MODEL_ONLY_BASIS' in a['quote'] for a in packet(self.q)['anchors']))
  result=apply(self.q,packet(self.q),self.response(relation='context'))
  self.assertEqual('associated',result['status'])
 def test_explanation_rephrasing_does_not_create_duplicate(self):
  original=packet(self.q);apply(self.q,original,self.response())
  self.assertEqual('no_changes',apply(self.q,original,self.response(explanation='A different phrasing of the same numeric relation'))['status'])
  self.assertEqual(1,len(self.annotations()))
 def test_no_data_or_zero_allowance_buys_no_request_and_cross_story_candidate_is_unseen(self):
  def forbidden(messages):raise AssertionError('No budget or candidate must not buy request')
  before=self.q.requests
  self.assertEqual('budget',perform(self.q,SimpleNamespace(complete=forbidden),max_requests=0)['status']);self.assertEqual(before,self.q.requests)
  other=Inquiry(self.path,Host(),synthetic=True)
  try:
   foreign=other.record('knowledge_proposal',{'proposal':self.p,'synthetic':True})
   self.assertNotIn(foreign,packet(self.q)['candidate_events'])
   with self.assertRaisesRegex(ValueError,'outside packet'):apply(self.q,packet(self.q),self.response(proposition=foreign))
   self.assertEqual('no_candidates_or_questions',perform(other,SimpleNamespace(complete=forbidden))['status'])
  finally:other.close()
 def test_eof_style_maintenance_distills_then_associates_with_same_budget(self):
  scribe=SimpleNamespace(complete=lambda m:{'intent':{'goals':[],'motivations':[],'inferred_needs':[],'unresolved':[]},'knowledge':[self.p]})
  association=SimpleNamespace(complete=lambda m:self.response())
  before=self.q.requests
  result=self.q.maintain(None,scribe_client=scribe,association_client=association,max_requests=2,reserve_chat=False)
  self.assertEqual(2,result['requests_used']);self.assertEqual(before-2,self.q.requests)
  self.assertEqual('distilled',result['distillation']['status']);self.assertEqual('associated',result['associations']['status'])
 def test_saved_link_is_provided_to_resumed_host_and_used_as_context(self):
  result=apply(self.q,packet(self.q),self.response());annotation=result['new_annotation_events'][0]
  story=self.q.story;self.q.close();self.q=Inquiry(self.path,Host(),synthetic=True,story=story)
  self.q.turn('Continue caching model')
  shown=[json.loads(m['content']) for m in self.q.messages if m['role']=='user' and m['content'].startswith('{')]
  self.assertIn(annotation,[a['event'] for p in shown if 'question_map' in p for n in p['question_map']['nodes'] for a in n['annotations']])
  self.assertTrue(self.q.dependencies.depends_on(self.q.last_reflection,annotation))
 def test_backend_can_create_initial_questions_and_links_without_frontend_map(self):
  other=Inquiry(self.path,Host(),synthetic=True)
  try:
   user=other.record('user',{'text':'Find the caching threshold','synthetic':True});other.user_sources[user]='Find the caching threshold'
   claim=other.knowledge.accept(other.run,proposal('A conditional threshold hypothesis',user,'caching threshold'),{user},synthetic=True)
   data=packet(other);user_anchor=next(a['anchor'] for a in data['anchors'] if a['source_event']==user)
   hypothesis_anchor=next(a['anchor'] for a in data['anchors'] if a['source_event']==claim)
   response={'questions':[{'key':'root','text':'Which caching threshold applies?','parents':[],'origin_anchor':user_anchor}],'links':[{'question':'root','proposition':claim,'anchor':hypothesis_anchor,'relation':'context','explanation':'Existing proposal only, not verified'}],'reason':'No front-end graph existed'}
   client=SimpleNamespace(complete=lambda m:response)
   before=len(other.knowledge.proposals(synthetic=True))
   result=perform(other,client);self.assertEqual(1,len(result['new_question_events']));self.assertEqual(1,len(result['new_annotation_events']))
   self.assertEqual('unchanged',perform(other,client)['status'])
   self.assertEqual(before,len(other.knowledge.proposals(synthetic=True)))
  finally:other.close()
 def test_anchor_catalog_never_offers_noncontiguous_fields_or_candidate_alternatives(self):
  data=packet(self.q)
  for anchor in data['anchors']:
   source=next(s for s in data['sources'] if s['event']==anchor['source_event'])
   self.assertIn(anchor['quote'],source['text']);self.assertIn(anchor['quote'],self.q.knowledge.source(anchor['source_event'])['text'])
  self.assertLessEqual(len(data['anchors']),64)
 def test_review_of_another_story_does_not_become_new_story_intent_or_question(self):
  other=Inquiry(self.path,Host(),synthetic=True)
  try:
   user=other.record('user',{'text':'Continue something else','synthetic':True});other.user_sources[user]='Continue something else'
   replacement=other.knowledge.accept(other.run,proposal('Old story corrected elsewhere',self.source,'"value": 0.15',revises=self.claim),{self.source,self.claim},synthetic=True)
   other.record('knowledge_review',{'target':self.claim,'replacement_event':replacement,'packet_sha256':'fixture','disposition':'replace','reason':'Global maintenance of the old story'})
   self.assertIsNone(packet(other))
   self.assertIn(replacement,packet(self.q)['candidate_events'])
  finally:other.close()
 def test_bad_new_root_anchor_rejects_question_and_good_link_together(self):
  data=packet(self.q);response=self.response()
  response['questions']=[{'key':'bad','text':'A new question?','parents':[],'origin_anchor':response['links'][0]['anchor']}]
  before=self.q.db.execute('SELECT count(*) FROM inquiry_events').fetchone()[0]
  with self.assertRaisesRegex(ValueError,'root needs'):apply(self.q,data,response)
  self.assertEqual(before,self.q.db.execute('SELECT count(*) FROM inquiry_events').fetchone()[0])
 def test_metadata_marks_self_echo_without_weakening_atomic_rejection(self):
  data=packet(self.q);own=next(a for a in data['anchors'] if a['source_event']==self.claim)
  self.assertIn(self.claim,own['context_only_for']);self.assertEqual('knowledge_proposal',own['source_kind'])
  independent=next(a for a in data['anchors'] if a['source_event']==self.source)
  self.assertNotIn(self.claim,independent['context_only_for'])
  response=self.response();response['links'].append({**response['links'][0],'anchor':own['anchor']})
  before=self.q.db.execute('SELECT count(*) FROM inquiry_events').fetchone()[0]
  with self.assertRaisesRegex(ValueError,'echo'):apply(self.q,data,response)
  self.assertEqual(before,self.q.db.execute('SELECT count(*) FROM inquiry_events').fetchone()[0]);self.assertEqual([],self.annotations())
 def test_descendant_text_is_context_only_for_its_ancestor_candidate(self):
  derived=self.q.knowledge.accept(self.q.run,proposal('A derived description of the threshold',self.claim,self.p['statement']),{self.claim},synthetic=True)
  data=packet(self.q);anchor=next(a for a in data['anchors'] if a['source_event']==derived)
  self.assertIn(self.claim,anchor['context_only_for']);self.assertIn(derived,anchor['context_only_for'])
 def test_fixed_input_computation_is_not_mislabeled_as_a_planning_echo(self):
  plan=self.q.record('reflection',{'synthetic':True,'reflection':{'answer':'Independently calculate a number'}})
  self.q.dependencies.link(plan,[self.claim])
  event,_,_=self.q.execute_action({'kind':'calculate','expression':'1+1','basis':'fixed inputs','prediction':'Expect 2'},plan)
  self.assertTrue(self.q.dependencies.depends_on(event,self.claim))
  self.assertFalse(self.q.dependencies.depends_on(event,self.claim,include_execution_context=False))
  data=packet(self.q);anchor=next(a for a in data['anchors'] if a['source_event']==event)
  self.assertNotIn(self.claim,anchor['context_only_for']);self.assertEqual('tool_result',anchor['source_kind'])

if __name__=='__main__':unittest.main()
