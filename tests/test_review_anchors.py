import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from dojo.inquiry import Inquiry,validate_distillation
from dojo.live import LiveError
from dojo.anchors import anchor_catalog,packet_hash
from dojo.reviews import apply_review,validate_review
from dojo.question_reviews import apply_review as apply_relation,review_packet
from tests.test_knowledge import proposal

class ReviewAnchorTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.q=Inquiry(Path(self.tmp.name)/'db',SimpleNamespace(config=SimpleNamespace(model='deepseek-flash',api_key=None)),synthetic=True)
  self.user=self.q.record('user',{'text':'Protect files, verify configuration','synthetic':True});self.q.user_sources[self.user]=self.q.knowledge.source(self.user)['text']
  self.target=self.q.knowledge.accept(self.q.run,proposal('A conditional risk remains unknown',self.user,'configuration'),{self.user},synthetic=True)
  self.source=self.q.record('tool_result',{'action':{'kind':'search','query':'INPUT_SENTINEL','prediction':'INPUT_SENTINEL'},'status':'executed','result':{'sources':[{'title':'A source','url':'https://example.test/a','excerpt':'Changes overwrite the target, even if\nthey are newer. '+('context '*160)}],'scope':'External claim, not verified','basis':'INPUT_SENTINEL'}})
  self.q.knowledge.request_review(self.q.run,self.target,[self.source],'New external material',{self.target,self.source},synthetic=True)
 def tearDown(self):self.q.close();self.tmp.cleanup()
 def packet(self):return self.q.knowledge.review_packet(self.target)
 def review(self,packet):
  anchor=next(a for a in packet['anchors'] if a['source_event']==self.source and 'excerpt' in a['quote'])
  replacement=proposal('A conditional interpretation, not actual configuration verification',self.source,'placeholder',revises=self.target)
  replacement['premises']=[{'anchor':anchor['anchor'],'role':'evidence'}]
  return {'disposition':'replace','reason':'The exact external excerpt supplies conditional material only','replacement':replacement}
 def test_newline_escaping_is_recovered_from_verified_anchor_without_normalizing_legacy_quotes(self):
  packet=self.packet();response=self.review(packet)
  validate_review(json.dumps(response))
  bad=copy.deepcopy(response);bad['replacement']['premises']=[{'event':self.source,'quote':'Changes overwrite the target, even if they are newer.','role':'evidence'}]
  with self.assertRaisesRegex(ValueError,'quote not displayed'):apply_review(self.q,packet,bad)
  accepted=apply_review(self.q,packet,response)
  saved=self.q.knowledge.source(accepted['replacement_event'])['proposal']['premises'][0]
  self.assertIn('\\n',saved['quote']);self.assertEqual(self.source,saved['event']);self.assertNotIn('anchor',saved)
  self.assertIn(saved['quote'],self.q.knowledge.observed_tool_text(self.source));self.assertIn(saved['quote'],self.q.knowledge.source(self.source)['text'])
 def test_hidden_or_mixed_or_boolean_anchors_never_create_proposal(self):
  packet=self.packet();response=self.review(packet);before=len(self.q.knowledge.proposals(synthetic=True))
  hidden=copy.deepcopy(response);hidden['replacement']['premises'][0]['anchor']=999999
  with self.assertRaisesRegex(ValueError,'unseen review anchor'):apply_review(self.q,packet,hidden)
  for premise in [{'anchor':True,'role':'evidence'},{'anchor':1,'event':self.user,'quote':'configuration','role':'evidence'},{'anchor':1,'role':'evidence','extra':'guess'}]:
   invalid=copy.deepcopy(response);invalid['replacement']['premises']=[premise]
   with self.assertRaises(LiveError):validate_review(json.dumps(invalid))
  self.assertEqual(before,len(self.q.knowledge.proposals(synthetic=True)))
 def test_anchor_catalog_omits_inputs_and_stale_sources_and_keeps_bounds(self):
  packet=self.packet();anchors=packet['anchors']
  self.assertFalse(any('INPUT_SENTINEL' in a['quote'] for a in anchors));self.assertLessEqual(len(anchors),64);self.assertLessEqual(sum(len(a['quote']) for a in anchors),24000)
  newer=self.q.record('tool_result',{'status':'executed','result':{'value':1}});self.q.dependencies.revise(self.source,newer,'A revised receipt')
  self.assertFalse(any(a['source_event']==self.source for a in self.packet()['anchors']))
  self.assertEqual('discarded',apply_review(self.q,packet,self.review(packet))['status'])
 def test_forged_packet_anchor_is_discarded_with_either_old_or_recomputed_hash(self):
  packet=self.packet();response=self.review(packet)
  for rehash in (False,True):
   forged=copy.deepcopy(packet);forged['anchors'][0]['quote']='Invented material'
   if rehash:forged['sha256']=packet_hash(forged)
   self.assertEqual('discarded',apply_review(self.q,forged,response)['status'])
  self.assertEqual('needs_review',self.q.dependencies.status(self.target)['state'])
 def test_anchor_does_not_upgrade_model_text_from_assumption_to_evidence(self):
  reflection=self.q.record('reflection',{'synthetic':True,'reflection':{'answer':'An unverified model thought'}})
  target=self.q.knowledge.accept(self.q.run,{**proposal('A tentative interpretation',reflection,'unverified'), 'premises':[{'event':reflection,'quote':'unverified','role':'assumption'}]},{reflection},synthetic=True)
  packet=self.q.knowledge.review_packet(target);a=next(a for a in packet['anchors'] if a['source_event']==reflection)
  response=self.review(self.packet());response['replacement']['revises']=target;response['replacement']['premises']=[{'anchor':a['anchor'],'role':'evidence'}]
  with self.assertRaisesRegex(ValueError,'assumption role'):apply_review(self.q,packet,response)
 def test_nested_diagnosis_offers_both_stages_with_context_paths(self):
  event=self.q.record('tool_result',{'action':{'kind':'diagnose_experiment'},'status':'executed','result':{'original':{'evaluated':30,'passed':28,'counterexample_count':2},'tolerant':{'evaluated':30,'passed':30,'counterexample_count':0}}})
  anchors=anchor_catalog(self.q.knowledge,[self.q.knowledge.source(event)])
  self.assertIn(['original','counterexample_count'],[a.get('observation_path') for a in anchors]);self.assertIn(['tolerant','counterexample_count'],[a.get('observation_path') for a in anchors])
 def test_numeric_fields_never_join_different_json_parents_and_late_failure_is_offered(self):
  from dojo.experiments import parameter_sweep
  result=parameter_sweep({'x':[0,1]},{},'x>=0 and x<=1 and x<2 and x>-1 and x==1')
  event=self.q.record('tool_result',{'action':{'kind':'experiment'},'status':'executed','result':result})
  anchors=anchor_catalog(self.q.knowledge,[self.q.knowledge.source(event)])
  self.assertEqual('"passed": 1',next(a['quote'] for a in anchors if a.get('observation_path')==['passed']))
  self.assertIn(['component_checks',4],[a.get('observation_path') for a in anchors])
  observed=json.loads(self.q.knowledge.observed_tool_text(event))
  for a in anchors:
   path=a['observation_path'];value=observed
   for part in path:value=value[part]
   expected=json.dumps(path[-1],ensure_ascii=False)+': '+json.dumps(value,ensure_ascii=False,sort_keys=True) if isinstance(path[-1],str) else json.dumps(value,ensure_ascii=False,sort_keys=True)
   self.assertEqual(expected,a['quote'])
 def relation_fixture(self):
  action={'kind':'map_inquiry','questions':[{'key':'root','text':'How can data be protected?','parents':[],'origin_event':self.user,'origin_quote':'Protect files','revises':None}],'links':[],'prediction':'Organize the fixture'}
  self.q.visible_source_text[self.user]=self.q.knowledge.source(self.user)['text'];question=self.q.questions.apply(self.q,action)['question_keys']['root']
  self.q.visible_source_text[question]=self.q.knowledge.source(question)['text']
  self.q.visible_source_text[self.target]=self.q.knowledge.source(self.target)['text']
  action={**action,'questions':[],'links':[{'question':question,'proposition':self.target,'source_event':self.user,'quote':'Protect files','relation':'context','explanation':'Original user report only'}]}
  self.q.questions.apply(self.q,action);relation=self.q.questions.view(story=self.q.story,synthetic=True)['nodes'][0]['annotations'][0]['event']
  return question,relation
 def test_relation_uses_same_verified_excerpt_and_cannot_retain_pending_candidate(self):
  question,relation=self.relation_fixture()
  packet=review_packet(self.q,relation);anchor=next(a for a in packet['anchors'] if a['source_event']==self.user)
  response={'disposition':'retain','reason':'Still pending','replacement':{'question':question,'proposition':self.target,'anchor':anchor['anchor'],'relation':'context','explanation':'A user report'}}
  with self.assertRaisesRegex(ValueError,'current packet sources'):apply_relation(self.q,packet,response)
  replacement=apply_review(self.q,self.packet(),self.review(self.packet()))['replacement_event']
  packet=review_packet(self.q,relation);anchor=next(a for a in packet['anchors'] if a['source_event']==self.source and 'excerpt' in a['quote'])
  response['disposition']='replace';response['replacement'].update(proposition=replacement,anchor=anchor['anchor'])
  result=apply_relation(self.q,packet,response)
  self.assertEqual('reviewed',result['status']);self.assertEqual('superseded',self.q.dependencies.status(relation)['state'])
 def test_normal_maintenance_rechecks_knowledge_before_its_relation_with_shared_budget(self):
  question,relation=self.relation_fixture();calls=[]
  def knowledge(messages):
   calls.append('knowledge');return self.review(json.loads(messages[-1]['content']))
  def relations(messages):
   calls.append('relations');packet=json.loads(messages[-1]['content']);replacement=self.q.dependencies.status(self.target)['replacement']
   self.assertEqual('current_interpretation',self.q.dependencies.status(replacement)['state'])
   anchor=next(a for a in packet['anchors'] if a['source_event']==self.source and 'excerpt' in a['quote'])
   return {'disposition':'replace','reason':'Current conditional proposition now has exact citations','replacement':{'question':question,'proposition':replacement,'anchor':anchor['anchor'],'relation':'context','explanation':'External claim, not an actual configuration check'}}
  before=self.q.requests
  result=self.q.maintain(SimpleNamespace(complete=knowledge),question_review_client=SimpleNamespace(complete=relations),max_requests=2,reserve_chat=False)
  self.assertEqual(['knowledge','relations'],calls);self.assertEqual(2,result['requests_used']);self.assertEqual(before-2,self.q.requests)
  self.assertEqual('superseded',self.q.dependencies.status(relation)['state'])
 def test_distillation_uses_observation_anchors_and_saves_canonical_event_quotes(self):
  self.q.visible_source_text[self.source]=self.q.knowledge.source(self.source)['text']
  def scribe(messages):
   packet=json.loads(messages[-1]['content']);anchored=self.review(packet)['replacement'];anchored['revises']=None
   return validate_distillation(json.dumps({'intent':{'goals':[],'motivations':[],'inferred_needs':[],'unresolved':[]},'knowledge':[anchored]}))
  result=self.q.distill(SimpleNamespace(complete=scribe),focus_events=[self.source])
  self.assertEqual('represented',result['focus_coverage'][0]['status'])
  saved=self.q.knowledge.source(result['proposal_events'][0])['proposal']['premises'][0]
  self.assertEqual(self.source,saved['event']);self.assertNotIn('anchor',saved);self.assertNotIn('INPUT_SENTINEL',saved['quote'])
 def test_distillation_rejects_unseen_anchor_and_keeps_explicit_unrepresented_status(self):
  self.q.visible_source_text[self.source]=self.q.knowledge.source(self.source)['text'];calls=[]
  def scribe(messages):
   calls.append(messages);anchored=proposal('Not accepted',self.source,'placeholder');anchored['premises']=[{'anchor':999999,'role':'evidence'}]
   return {'intent':{'goals':[],'motivations':[],'inferred_needs':[],'unresolved':[]},'knowledge':[anchored]}
  result=self.q.distill(SimpleNamespace(complete=scribe),focus_events=[self.source])
  self.assertEqual([],result['proposal_events']);self.assertEqual('unrepresented',result['focus_coverage'][0]['status'])
  self.assertEqual('unchanged',self.q.distill(SimpleNamespace(complete=scribe),focus_events=[self.source])['status']);self.assertEqual(1,len(calls))
 def test_distillation_discards_a_changed_source_snapshot_before_writing(self):
  self.q.visible_source_text[self.source]=self.q.knowledge.source(self.source)['text']
  def scribe(messages):
   packet=json.loads(messages[-1]['content']);anchored=self.review(packet)['replacement'];anchored['revises']=None
   new=self.q.record('tool_result',{'status':'executed','result':{'value':1}});self.q.dependencies.revise(self.source,new,'Concurrent correction')
   return {'intent':{'goals':[],'motivations':[],'inferred_needs':[],'unresolved':[]},'knowledge':[anchored]}
  before=len(self.q.knowledge.proposals(synthetic=True));result=self.q.distill(SimpleNamespace(complete=scribe),focus_events=[self.source])
  self.assertEqual('discarded',result['status']);self.assertEqual(before,len(self.q.knowledge.proposals(synthetic=True)))

if __name__=='__main__':unittest.main()
