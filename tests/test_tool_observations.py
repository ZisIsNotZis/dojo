import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from dojo.inquiry import Inquiry
from dojo.grounding import audit_observation_anchors
from dojo.reviews import apply_review
from tests.test_knowledge import proposal


class ToolObservationTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'db'
  self.client=SimpleNamespace(config=SimpleNamespace(model='deepseek-flash',api_key=None))
  self.q=Inquiry(self.path,self.client,synthetic=True)
 def tearDown(self):self.q.close();self.tmp.cleanup()
 def source(self,kind,result):return self.q.record('tool_result',{'action':{'kind':kind},'status':'executed','result':result})
 def reject(self,event,quote):
  with self.assertRaisesRegex(ValueError,'not an observation'):self.q.knowledge.accept(self.q.run,proposal('Claim remains unverified',event,quote),{event},synthetic=True)
 def test_old_copied_basis_remains_context_but_cannot_be_evidence_or_duplicate_bypass(self):
  event=self.source('calculate',{'value':0.15,'basis':'UNVERIFIED_ALGEBRA'})
  self.reject(event,'UNVERIFIED_ALGEBRA')
  p=proposal('Claim remains unverified',event,'UNVERIFIED_ALGEBRA')
  self.q.record('knowledge_proposal',{'proposal':p,'synthetic':True})
  self.reject(event,'UNVERIFIED_ALGEBRA')
  p['premises'][0]['role']='assumption'
  self.assertIsInstance(self.q.knowledge.accept(self.q.run,p,{event},synthetic=True),int)
  self.assertIsInstance(self.q.knowledge.accept(self.q.run,proposal('Computed threshold under assumptions',event,'"value": 0.15'),{event},synthetic=True),int)
 def test_experiment_inputs_are_not_computed_findings(self):
  event=self.source('experiment',{'evaluated':4,'passed':4,'assumptions':['ASSUMED_REALITY'],'assertion':'UNTESTED_EXPRESSION','domain':{'INPUT_NAME':[1]},'sample_points':[{'parameters':{'h':0.2},'derived':{'gain':0.1},'assertion_holds':True}]})
  for quote in ['ASSUMED_REALITY','UNTESTED_EXPRESSION','INPUT_NAME']:self.reject(event,quote)
  self.assertIsInstance(self.q.knowledge.accept(self.q.run,proposal('Finite points passed',event,'"passed": 4'),{event},synthetic=True),int)
 def test_text_generated_answers_and_map_organization_are_not_tool_evidence(self):
  event=self.source('text_experiment',{'status':'observed','semantic_accuracy':'not_measured','probes':[{'quote':'REFERENCE_INPUT'}],'sources':[{'text':'SOURCE_INPUT'}],'arms':[{'arm':'summary','status':'observed','representation':'MODEL_REPRESENTATION','observations':[{'unverified_reader_answer':'MODEL_ANSWER'}],'literal_counts':{'probe_count':2}}]})
  for quote in ['REFERENCE_INPUT','SOURCE_INPUT','MODEL_REPRESENTATION','MODEL_ANSWER']:self.reject(event,quote)
  self.assertIsInstance(self.q.knowledge.accept(self.q.run,proposal('Literal probe count only',event,'"probe_count": 2'),{event},synthetic=True),int)
  graph=self.source('map_inquiry',{'graph':{'text':'MODEL_SAVED_ANSWER'}});self.reject(graph,'MODEL_SAVED_ANSWER')
 def test_question_links_share_the_same_observation_boundary(self):
  user=self.q.record('user',{'text':'Understand the threshold','synthetic':True});self.q.user_sources[user]='Understand the threshold'
  claim=self.q.knowledge.accept(self.q.run,proposal('Threshold might be sufficient',user,'threshold'),{user},synthetic=True)
  source=self.source('calculate',{'value':0.15,'basis':'UNVERIFIED_ALGEBRA'})
  for event in [user,claim,source]:self.q.visible_source_text[event]=self.q.knowledge.source(event)['text']
  action={'kind':'map_inquiry','questions':[{'key':'root','text':'Which threshold?','parents':[],'origin_event':user,'origin_quote':'threshold','revises':None}],'links':[{'question':'root','proposition':claim,'source_event':source,'quote':'UNVERIFIED_ALGEBRA','relation':'supports','explanation':'Not independently computed'}],'prediction':'Organize'}
  with self.assertRaisesRegex(ValueError,'not an observation'):self.q.questions.apply(self.q,action)
 def test_audit_marks_legacy_anchors_bounded_idempotent_and_recheck_can_rebuild(self):
  source=self.source('calculate',{'value':0.15,'basis':'UNVERIFIED_ALGEBRA'})
  targets=[]
  for i in range(2):targets.append(self.q.record('knowledge_proposal',{'proposal':proposal('Old claim '+str(i),source,'UNVERIFIED_ALGEBRA'),'synthetic':True}))
  first=audit_observation_anchors(self.q,limit=1);self.assertEqual([targets[0]],[x['target'] for x in first['marked']])
  self.assertEqual('needs_review',self.q.dependencies.status(targets[0])['state'])
  self.assertEqual([targets[1]],[x['target'] for x in audit_observation_anchors(self.q,limit=1)['marked']])
  self.assertEqual([],audit_observation_anchors(self.q)['marked'])
  p=proposal('Only 0.15 was computed',source,'"value": 0.15',revises=targets[0])
  result=apply_review(self.q,self.q.knowledge.review_packet(targets[0]),{'disposition':'replace','reason':'Rebuild from actual value and preserve model assumptions','replacement':p})
  self.assertEqual('current_interpretation',self.q.dependencies.status(result['replacement_event'])['state'])
  self.assertIn('UNVERIFIED_ALGEBRA',self.q.knowledge.source(targets[0])['proposal']['premises'][0]['quote'])
 def test_audit_does_not_touch_another_story_or_assumption(self):
  source=self.source('calculate',{'value':1,'basis':'ASSUMED_ONLY'})
  p=proposal('Assumed',source,'ASSUMED_ONLY');p['premises'][0]['role']='assumption'
  self.q.knowledge.accept(self.q.run,p,{source},synthetic=True)
  other=Inquiry(self.path,self.client,synthetic=True)
  try:
   target=other.record('knowledge_proposal',{'proposal':proposal('Other story',source,'ASSUMED_ONLY'),'synthetic':True})
   self.assertEqual([],audit_observation_anchors(self.q)['marked'])
   self.assertEqual('current_interpretation',self.q.dependencies.status(target)['state'])
  finally:other.close()
 def test_audit_marks_legacy_support_and_relation_can_be_reclassified_as_context(self):
  from dojo.question_reviews import apply_review as review_relation,review_packet
  user=self.q.record('user',{'text':'Understand conditions','synthetic':True})
  node=self.q.record('inquiry_question',{'story':self.q.story,'synthetic':True,'text':'Which conditions?','origin_event':user,'origin_quote':'conditions'})
  claim=self.q.knowledge.accept(self.q.run,proposal('Conditions matter',user,'conditions'),{user},synthetic=True)
  source=self.source('calculate',{'value':0.15,'basis':'UNVERIFIED_ALGEBRA'})
  target=self.q.record('question_evidence',{'story':self.q.story,'synthetic':True,'question':node,'proposition':claim,'source_event':source,'quote':'UNVERIFIED_ALGEBRA','relation':'supports','explanation':'Old unverified input'})
  self.assertEqual([target],[x['target'] for x in audit_observation_anchors(self.q)['marked']])
  self.assertEqual('needs_review',self.q.dependencies.status(target)['state'])
  result=review_relation(self.q,review_packet(self.q,target),{'disposition':'replace','reason':'The derivation was input only, preserve as context','replacement':{'question':node,'proposition':claim,'source_event':source,'quote':'UNVERIFIED_ALGEBRA','relation':'context','explanation':'Unverified derivation only'}})
  self.assertEqual('current_interpretation',self.q.dependencies.status(result['replacement_event'])['state'])
  graph=self.q.questions.view(story=self.q.story,synthetic=True)
  self.assertEqual('context',graph['nodes'][0]['annotations'][0]['relation'])
  self.assertEqual(1,len(graph['nodes'][0]['annotation_history']))
 def test_new_receipts_keep_model_inputs_only_in_action(self):
  plan=self.q.record('reflection',{'reflection':{'answer':'Plan arithmetic'}})
  _,receipt,_=self.q.execute_action({'kind':'calculate','expression':'0.3/2','basis':'UNVERIFIED_ALGEBRA','prediction':'Expect 0.15'},plan)
  self.assertEqual(0.15,receipt['result']['value']);self.assertNotIn('basis',receipt['result'])
  self.assertEqual('UNVERIFIED_ALGEBRA',receipt['action']['basis'])
  _,receipt,_=self.q.execute_action({'kind':'experiment','parameters':{'x':[1,2]},'derived':{'y':'x+1'},'assertion':'y>x','assumptions':['ASSUMED_ONLY'],'prediction':'Two finite points pass'},plan)
  self.assertEqual(2,receipt['result']['passed']);self.assertNotIn('assumptions',receipt['result'])
  self.assertEqual(['ASSUMED_ONLY'],receipt['action']['assumptions'])
 def test_resume_audits_before_first_model_request_or_retrieval(self):
  source=self.source('calculate',{'value':1,'basis':'LEGACY_DERIVATION'})
  target=self.q.record('knowledge_proposal',{'proposal':proposal('Legacy cache threshold',source,'LEGACY_DERIVATION'),'synthetic':True})
  story=self.q.story;self.q.close()
  self.q=Inquiry(self.path,self.client,synthetic=True,story=story,request_budget=2)
  self.assertEqual(2,self.q.requests)
  self.assertEqual('needs_review',self.q.dependencies.status(target)['state'])
  matches=self.q.retrieve_knowledge('cache threshold')
  self.assertEqual('needs_review',matches[0]['dependency_status']['state'])

if __name__=='__main__':unittest.main()
