import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from dojo.inquiry import Inquiry
from dojo.stories import source_view
from tests.test_stories import Host


class StoryProvenanceTests(unittest.TestCase):
 def test_embedded_quote_has_its_own_origin_not_the_proposal_creation_story(self):
  source={'event':3,'kind':'knowledge_proposal','run':'new','text':'A candidate',
   'proposal':{'premises':[{'event':1,'quote':'Old experience','role':'evidence'},
                           {'event':2,'quote':'Unknown origin','role':'assumption'}]}}
  before=copy.deepcopy(source)
  view=source_view(source,'current',{'new':{'story':'current'},'old':{'story':'previous'}},
   premise_sources={1:{'run':'old','kind':'user'}})
  self.assertEqual('same_story',view['story_scope'])
  old,unknown=view['proposal']['premises']
  self.assertEqual('other_story',old['source_origin']['story_scope'])
  self.assertEqual('historical_report_not_current_user_testimony',old['source_origin']['attribution'])
  self.assertEqual('unknown',unknown['source_origin']['story_scope'])
  self.assertEqual(before,source)
  view['proposal']['premises'][0]['quote']='View edit'
  self.assertEqual(before,source)

 def test_inquiry_scopes_embedded_sources_without_changing_proposal_contract(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'db';old=Inquiry(path,Host(),synthetic=True);old.turn('公共经验平台是旧故事。')
   origin=next(iter(old.user_sources));old.close()
   q=Inquiry(path,Host(),synthetic=True)
   try:
    proposal={'statement':'历史报告可供类比，不是当前用户经历。','kind':'descriptive','method':'hypothesis',
     'premises':[{'event':origin,'quote':'公共经验平台是旧故事。','role':'evidence'}],
     'assumptions':[],'conditions':[],'alternatives':[],'falsifier':'出现不同材料','revises':None}
    event=q.knowledge.accept(q.run,proposal,{origin:q.knowledge.source(origin)['text']},synthetic=True)
    canonical=q.knowledge.source(event)
    view=q.scoped_sources([canonical])[0]
    self.assertEqual('same_story',view['story_scope'])
    self.assertEqual('other_story',view['proposal']['premises'][0]['source_origin']['story_scope'])
    self.assertEqual(canonical,q.knowledge.source(event))
    self.assertEqual(proposal,q.knowledge.source(event)['proposal'])
   finally:q.close()

 def test_embedded_origin_is_recomputed_even_if_parent_canonical_source_is_unchanged(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'db';old=Inquiry(path,Host(),synthetic=True);old.turn('其他故事的原话。')
   origin=next(iter(old.user_sources));old_run=old.run;old.close()
   q=Inquiry(path,Host(),synthetic=True)
   try:
    proposal={'statement':'条件解释','kind':'descriptive','method':'hypothesis',
     'premises':[{'event':origin,'quote':'其他故事的原话。','role':'evidence'}],
     'assumptions':[],'conditions':[],'alternatives':[],'falsifier':'新材料','revises':None}
    event=q.knowledge.accept(q.run,proposal,{origin:q.knowledge.source(origin)['text']},synthetic=True)
    canonical=q.knowledge.source(event);source=q.scoped_sources([canonical])[0]
    self.assertEqual('same_story',source['story_scope'])
    self.assertEqual('other_story',source['proposal']['premises'][0]['source_origin']['story_scope'])
    row=json.loads(q.db.execute("SELECT payload FROM inquiry_events WHERE run=? AND kind='start'",(old_run,)).fetchone()[0]);row['story']=q.story
    with q.db:q.db.execute("UPDATE inquiry_events SET payload=? WHERE run=? AND kind='start'",(json.dumps(row),old_run))
    updated=q.scoped_sources([canonical])[0]
    self.assertEqual('same_story',updated['proposal']['premises'][0]['source_origin']['story_scope'])
    self.assertEqual(canonical,q.knowledge.source(event))
   finally:q.close()

 def test_view_does_not_rewrite_source_or_invent_identity_for_unknown_run(self):
  source={'event':1,'kind':'user','run':'old','text':'Historical report'};before=copy.deepcopy(source)
  view=source_view(source,'new',{'old':{'story':'older'}})
  self.assertEqual('other_story',view['story_scope']);self.assertEqual(before,source)
  self.assertEqual('historical_report_not_current_user_testimony',view['attribution'])
  self.assertEqual('unknown',source_view(source,'new',{})['story_scope'])
 def test_new_story_labels_retrieved_user_without_changing_canonical_source_hash(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'db';old=Inquiry(path,Host(),synthetic=True)
   old.turn('我和同事讨论产品，功能清单忘记判断。');origin=next(iter(old.user_sources));story=old.story
   raw=old.knowledge.source(origin);old.close()
   q=Inquiry(path,Host(),synthetic=True)
   try:
    current=q.record('user',{'text':'同事开会没问题，产物却不一样。','synthetic':True});q.user_sources[current]='同事开会没问题，产物却不一样。'
    prior=q.retrieve('公共经验平台');self.assertTrue(prior)
    packet=q.prompt_context(q.user_sources[current],current,prior,[],{'nodes':[]})
    historical=next(s for s in packet['source_catalog'] if s['event']==origin)
    self.assertEqual('other_story',historical['story_scope']);self.assertEqual(story,historical['origin_story'])
    self.assertEqual('same_story',packet['user_source']['story_scope'])
    self.assertEqual(raw,q.knowledge.source(origin));self.assertNotIn(origin,q.user_sources)
    self.assertEqual([],q.prompt_context(q.user_sources[current],current,prior,[],{'nodes':[]})['source_catalog'])
   finally:q.close()
 def test_explicit_resume_and_critic_have_consistent_origin_labels(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'db';old=Inquiry(path,Host(),synthetic=True);old.turn('公共经验平台。');story=old.story;origin=next(iter(old.user_sources));old.close()
   host=Host();q=Inquiry(path,host,synthetic=True,story=story)
   try:
    restored=json.loads(q.db.execute("SELECT payload FROM inquiry_events WHERE run=? AND kind='story_context'",(q.run,)).fetchone()[0])
    self.assertEqual('same_story',next(s for s in restored['sources'] if s['event']==origin)['story_scope'])
    q.turn('继续。');packets=[]
    def complete(messages):packets.append(json.loads(messages[-1]['content']));return {'issues':[]}
    self.assertEqual('checked',q.inspect_reply(SimpleNamespace(complete=complete))['status'])
    self.assertTrue(all(s['story_scope']=='same_story' for s in packets[0]['sources']))
   finally:q.close()
 def test_changed_story_mapping_discards_opinion_without_rewriting_source(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'db';old=Inquiry(path,Host(),synthetic=True);old.turn('历史用户的报告。');origin=next(iter(old.user_sources));run=old.run;old.close()
   q=Inquiry(path,Host(),synthetic=True)
   try:
    q.visible_source_text[origin]=q.knowledge.source(origin)['text'];before=q.knowledge.source(origin)
    target=q.record('reflection',{'reflection':{'answer':'历史可借鉴，不自动属于这次用户。','action':None}})
    def complete(messages):
     packet=json.loads(messages[-1]['content']);self.assertEqual('other_story',packet['sources'][0]['story_scope'])
     row=json.loads(q.db.execute("SELECT payload FROM inquiry_events WHERE run=? AND kind='start'",(run,)).fetchone()[0]);row['story']=q.story
     with q.db:q.db.execute("UPDATE inquiry_events SET payload=? WHERE run=? AND kind='start'",(json.dumps(row),run))
     return {'issues':[]}
    self.assertEqual('discarded',q.inspect_reply(SimpleNamespace(complete=complete),target=target)['status'])
    self.assertEqual(before,q.knowledge.source(origin))
   finally:q.close()

if __name__=='__main__':unittest.main()
