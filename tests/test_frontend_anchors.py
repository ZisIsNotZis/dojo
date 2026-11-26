import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from dojo.inquiry import Inquiry,validate_host
from dojo.live import LiveError
from dojo.questions import resolve_native_action
from tests.test_knowledge import proposal

class FrontendAnchorTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'db';self.host=SimpleNamespace(config=SimpleNamespace(model='deepseek-flash',api_key=None));self.q=Inquiry(self.path,self.host,synthetic=True)
  self.user=self.q.record('user',{'text':'Check this numeric condition','synthetic':True});self.q.user_sources[self.user]='Check this numeric condition';self.q.visible_source_text[self.user]='Check this numeric condition'
  self.target=self.q.knowledge.accept(self.q.run,proposal('A conditional hypothesis',self.user,'numeric condition'),{self.user},synthetic=True);self.q.visible_source_text[self.target]=self.q.knowledge.source(self.target)['text']
  self.source=self.q.record('tool_result',{'action':{'kind':'calculate','basis':'INPUT_SENTINEL','prediction':'INPUT_SENTINEL'},'status':'executed','result':{'value':0.15,'scope':'Given inputs only'}});self.q.visible_source_text[self.source]=self.q.knowledge.source(self.source)['text']
  offered=self.q.offer_front_anchors([self.q.knowledge.source(self.user),self.q.knowledge.source(self.source)])
  self.anchor=next(a['anchor'] for a in offered if a['source_event']==self.source and a.get('observation_path')==['value'])
 def tearDown(self):self.q.close();self.tmp.cleanup()
 def action(self,**overrides):
  value={'kind':'map_inquiry','anchor_run':self.q.run,'questions':[{'key':'root','text':'Which condition applies?','parents':[],'origin_event':self.user,'origin_quote':'numeric condition','revises':None}],
   'links':[{'question':'root','proposition':self.target,'anchor':self.anchor,'relation':'supports','explanation':'A finite value under given inputs'}],'prediction':'Connect a source, not certify truth'}
  value.update(overrides);return value
 def plan(self):return self.q.record('reflection',{'synthetic':True,'reflection':{'answer':'An organizing plan'}})
 def test_native_shape_resolves_to_canonical_storage_and_input_is_not_offered(self):
  action=self.action();validate_host(json.dumps({'answer':'Organize','action':action}))
  event,receipt,_=self.q.execute_action(action,self.plan());self.assertEqual('executed',receipt['status'])
  self.assertEqual(action,receipt['action']);canonical=receipt['resolved_action'];self.assertNotIn('anchor_run',canonical);self.assertEqual(self.source,canonical['links'][0]['source_event'])
  nodes=self.q.questions.view(story=self.q.story,synthetic=True)['nodes'];link=nodes[0]['annotations'][0]
  self.assertEqual(self.source,link['source_event']);self.assertIn('0.15',link['quote']);self.assertNotIn('anchor',link)
  self.assertFalse(any('INPUT_SENTINEL' in a['quote'] for a in self.q.front_anchors.entries.values()))
 def test_unknown_changed_and_cross_run_handles_reject_whole_action(self):
  for changed in [self.action(anchor_run='0'*32),self.action(links=[{**self.action()['links'][0],'anchor':99999}])]:
   _,receipt,_=self.q.execute_action(changed,self.plan());self.assertEqual('failed',receipt['status']);self.assertEqual([],self.q.questions.view(story=self.q.story,synthetic=True)['nodes'])
  newer=self.q.record('tool_result',{'status':'executed','result':{'value':0.2}});self.q.dependencies.revise(self.source,newer,'A corrected source')
  _,receipt,_=self.q.execute_action(self.action(),self.plan());self.assertEqual('failed',receipt['status']);self.assertEqual([],self.q.questions.view(story=self.q.story,synthetic=True)['nodes'])
 def test_same_numeric_handle_in_another_run_cannot_alias_old_run(self):
  other=Inquiry(self.path,self.host,synthetic=True)
  try:
   other.visible_source_text.update(self.q.visible_source_text);other.user_sources.update(self.q.user_sources)
   other.offer_front_anchors([other.knowledge.source(self.user),other.knowledge.source(self.source)])
   with self.assertRaisesRegex(ValueError,'another run'):resolve_native_action(other,self.action())
  finally:other.close()
 def test_model_anchor_only_context_and_invalid_mixed_shape_is_rejected(self):
  model=self.q.record('reflection',{'synthetic':True,'reflection':{'answer':'An unverified suggestion'}});self.q.visible_source_text[model]=self.q.knowledge.source(model)['text']
  entries=self.q.offer_front_anchors([self.q.knowledge.source(model)]);handle=entries[0]['anchor']
  bad=self.action(links=[{**self.action()['links'][0],'anchor':handle}])
  with self.assertRaisesRegex(ValueError,'only provides context'):resolve_native_action(self.q,bad)
  good=copy.deepcopy(bad);good['links'][0]['relation']='context';self.assertEqual(model,resolve_native_action(self.q,good)['links'][0]['source_event'])
  mixed=copy.deepcopy(good);mixed['links'][0]['source_event']=model
  with self.assertRaises(LiveError):validate_host(json.dumps({'answer':'No mixed citations','action':mixed}))
 def test_offers_are_delta_only_and_source_changes_never_reuse_id(self):
  source=self.q.knowledge.source(self.source);self.assertEqual([],self.q.offer_front_anchors([source]))
  # Source payload corrections use a new event; no old id silently denotes it.
  new=self.q.record('tool_result',{'status':'executed','result':{'value':0.2}});self.q.visible_source_text[new]=self.q.knowledge.source(new)['text']
  self.q.dependencies.revise(self.source,new,'Corrected receipt')
  offered=self.q.offer_front_anchors([self.q.knowledge.source(new)]);self.assertTrue(all(a['anchor']>self.anchor for a in offered));self.assertEqual(self.source,self.q.front_anchors.entries[self.anchor]['source_event'])
 def test_current_run_backend_tool_is_included_in_next_prompt_and_links_can_use_it(self):
  plan=self.plan();event,_,_=self.q.execute_action({'kind':'calculate','expression':'2+3','basis':'A conditional calculation','prediction':'5'},plan)
  prompt=self.q.prompt_context('Continue',self.user,[],[],{'nodes':[]})
  self.assertIn(event,prompt['source_references']);self.assertIn(event,[s['event'] for s in prompt['source_catalog']]);self.assertTrue(any(a['source_event']==event for a in prompt['citation_anchors']))
  again=self.q.prompt_context('Continue',self.user,[],[],{'nodes':[]});self.assertEqual([],again['citation_anchors']);self.assertEqual([],again['source_catalog'])

if __name__=='__main__':unittest.main()
