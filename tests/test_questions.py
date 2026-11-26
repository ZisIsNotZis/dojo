import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from dojo.inquiry import Inquiry,validate_host
from dojo.questions import read_graph

class Host:
 config=SimpleNamespace(model='deepseek-flash',api_key=None)
 def complete(self,messages):return validate_host('{"answer":"继续核实经验的适用条件。","action":null}')

class QuestionTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'db';self.q=Inquiry(self.path,Host(),synthetic=True)
  self.user=self.q.record('user',{'text':'经验要能帮助陌生人，但不想额外填卡。','synthetic':True})
  self.q.user_sources[self.user]='经验要能帮助陌生人，但不想额外填卡。';self.show(self.user)
 def tearDown(self):self.q.close();self.tmp.cleanup()
 def show(self,event):self.q.visible_source_text[event]=self.q.knowledge.source(event)['text']
 def node(self,key,text,parents=()):return {'key':key,'text':text,'parents':list(parents),'origin_event':self.user,'origin_quote':'经验要能帮助陌生人','revises':None}
 def map(self,questions,links=()):return self.q.questions.apply(self.q,{'kind':'map_inquiry','questions':questions,'links':list(links),'prediction':'组织后明确下一步需核实的条件'})
 def proposal(self,source=None,quote=None):
  source=source or self.user;quote=quote or '经验要能帮助陌生人'
  p={'statement':'只保存原句或许足以帮助后来者','kind':'causal','method':'hypothesis','premises':[{'event':source,'quote':quote,'role':'assumption' if self.q.knowledge.source(source)['kind']=='reflection' else 'evidence'}],'assumptions':['保存与理解之间可能有缺口'],'conditions':['当前合成故事'],'alternatives':['保留适用条件'],'falsifier':'只看原句仍无法理解适用条件','revises':None}
  event=self.q.knowledge.accept(self.q.run,p,{source},synthetic=True);self.show(event);return event
 def link(self,question,claim,source,quote,relation='challenges'):
  return {'question':question,'proposition':claim,'source_event':source,'quote':quote,'relation':relation,'explanation':'该材料不足以证明只保留原句就能复用'}
 def test_multi_parent_organization_is_dag_and_exact_replay_does_not_duplicate(self):
  questions=[self.node('a','怎样帮助陌生人？'),self.node('b','怎样减少额外工作？'),self.node('c','怎样保留判断条件？',['a','b'])]
  first=self.map(questions);before=self.q.db.execute('SELECT count(*) FROM inquiry_events').fetchone()[0]
  second=self.map(questions)
  self.assertEqual(first['question_keys'],second['question_keys']);self.assertEqual(2,len(first['graph']['parents']))
  self.assertEqual(before,self.q.db.execute('SELECT count(*) FROM inquiry_events').fetchone()[0])
 def test_bad_second_link_or_cycle_rejects_entire_map_before_writing(self):
  claim=self.proposal();good=self.link('a',claim,self.user,'不想额外填卡','supports');bad={**good,'quote':'从未说过'}
  before=self.q.db.execute('SELECT count(*) FROM inquiry_events').fetchone()[0]
  with self.assertRaises(ValueError):self.map([self.node('a','需要检验什么？')],[good,bad])
  with self.assertRaisesRegex(ValueError,'cycle'):self.map([self.node('a','甲？',['b']),self.node('b','乙？',['a'])])
  self.assertEqual(before,self.q.db.execute('SELECT count(*) FROM inquiry_events').fetchone()[0])
  made=self.map([self.node('a','甲？'),self.node('b','乙？',['a'])]);self.q.question_context()
  with self.assertRaisesRegex(ValueError,'cycle'):self.map([self.node('a','甲？',[made['question_keys']['b']])])
 def test_support_needs_candidate_and_cannot_launder_candidate_or_model_opinion(self):
  claim=self.proposal()
  for link in (self.link('a',None,self.user,'经验要能帮助陌生人','supports'),self.link('a',claim,claim,self.q.knowledge.source(claim)['text'],'supports')):
   with self.assertRaises(ValueError):self.map([self.node('a','判断依据是什么？')],[link])
  reflection=self.q.record('reflection',{'reflection':{'answer':'只要保住原句就足够'},'synthetic':True});self.show(reflection)
  with self.assertRaisesRegex(ValueError,'only provides context'):self.map([self.node('a','判断依据是什么？')],[self.link('a',claim,reflection,'保住原句','supports')])
 def test_tool_prediction_is_context_not_supporting_observation(self):
  claim=self.proposal();event=self.q.record('tool_result',{'action':{'kind':'calculate','prediction':'PREDICTED_TRUE'},'status':'failed','error_kind':'SyntaxError'});self.show(event)
  with self.assertRaisesRegex(ValueError,'not an observation'):self.map([self.node('a','应如何验证？')],[self.link('a',claim,event,'PREDICTED_TRUE','supports')])
  graph=self.map([self.node('a','应如何验证？')],[self.link('a',claim,event,'SyntaxError','challenges')])['graph']
  self.assertEqual('tool_failure_not_positive_evidence',graph['nodes'][0]['annotations'][0]['source_epistemic_status'])
 def test_changed_source_marks_child_and_visible_ancestor_without_read_writes(self):
  claim=self.proposal();source=self.q.record('tool_result',{'status':'executed','result':{'literal_matches':1,'semantic_accuracy':'not_measured'}});self.show(source)
  result=self.map([self.node('a','怎样复用判断？'),self.node('b','原句保留足够吗？',['a'])],[self.link('b',claim,source,'not_measured')])
  new=self.q.record('tool_result',{'status':'executed','result':{'literal_matches':0}})
  self.q.dependencies.revise(source,new,'新观察改变旧材料')
  before=self.q.db.execute('SELECT count(*) FROM inquiry_events').fetchone()[0]
  graph=self.q.questions.view(story=self.q.story,synthetic=True)
  self.assertTrue(all(n['review_needed_in_visible_subgraph'] for n in graph['nodes']))
  child=next(n for n in graph['nodes'] if n['event']==result['question_keys']['b'])
  self.assertEqual('challenges',child['annotations'][0]['relation'])
  self.assertEqual('needs_review',child['annotations'][0]['dependency_status']['state'])
  self.assertEqual(before,self.q.db.execute('SELECT count(*) FROM inquiry_events').fetchone()[0])
 def test_questions_return_on_resume_even_when_new_input_has_no_lexical_match(self):
  result=self.map([self.node('a','适用条件如何判断？')]);story=self.q.story;self.q.close()
  self.q=Inquiry(self.path,Host(),synthetic=True,story=story);self.q.turn('继续')
  event=result['question_keys']['a']
  self.assertIn(event,self.q.visible_source_text);self.assertTrue(self.q.dependencies.depends_on(self.q.last_reflection,event))
 def test_cross_story_parent_and_root_origin_are_rejected(self):
  old=self.map([self.node('a','旧故事问题？')])['question_keys']['a']
  q=Inquiry(self.path,Host(),synthetic=True)
  try:
   q.visible_source_text[old]=self.q.knowledge.source(old)['text']
   q.visible_source_text[self.user]=self.q.knowledge.source(self.user)['text']
   action={'kind':'map_inquiry','questions':[self.node('new','新问题？',[old])],'links':[],'prediction':'不能跨故事改组织'}
   with self.assertRaises(ValueError):q.questions.apply(q,action)
   action['questions'][0]['parents']=[]
   with self.assertRaisesRegex(ValueError,'current-story'):q.questions.apply(q,action)
  finally:q.close()
 def test_reframing_preserves_history_and_marks_descendant_without_automatic_rewrite(self):
  made=self.map([self.node('a','怎样帮陌生人？'),self.node('b','如何判断适用条件？',['a'])]);self.q.question_context()
  replacement=self.node('new','怎样帮两人交接？');replacement['revises']=made['question_keys']['a']
  updated=self.map([replacement]);new=updated['question_keys']['new']
  self.assertEqual('superseded',self.q.dependencies.status(made['question_keys']['a'])['state'])
  graph=self.q.questions.view(story=self.q.story,synthetic=True)
  child=next(n for n in graph['nodes'] if n['event']==made['question_keys']['b'])
  self.assertTrue(child['ancestor_framing_review_needed']);self.assertEqual('如何判断适用条件？',child['text'])
  self.assertEqual(new,self.map([replacement])['question_keys']['new'])
  self.q.question_context()
  reissued=self.node('child','如何判断适用条件？',[new]);reissued['revises']=made['question_keys']['b']
  current=self.map([reissued]);current_child=current['question_keys']['child']
  self.assertNotEqual(made['question_keys']['b'],current_child)
  entry=next(n for n in current['graph']['nodes'] if n['event']==current_child)
  self.assertFalse(entry['ancestor_framing_review_needed']);self.assertEqual([],entry['annotations'])
 def test_context_suppresses_a_relation_that_would_return_current_interpretation_as_evidence(self):
  self.q.turn('经验需要核实');previous=self.q.last_reflection;self.show(previous)
  claim=self.proposal(previous,self.q.knowledge.source(previous)['text'])
  self.map([self.node('a','哪些条件待核实？')],[self.link('a',claim,self.user,'不想额外填卡','context')])
  context=self.q.question_context();self.assertEqual([],context['nodes'][0]['annotations'])
  self.q.turn('继续核实')
  self.assertEqual('superseded',self.q.dependencies.status(previous)['state'])
 def test_cli_is_read_only_and_synthetic_isolation_and_empty_path_hold(self):
  missing=Path(self.tmp.name)/'missing';self.assertEqual([],read_graph(missing)['nodes']);self.assertFalse(missing.exists())
  with self.assertRaises(ValueError):read_graph(missing,limit=0)
  self.map([self.node('a','还有哪些未知？')]);before=hashlib.sha256(self.path.read_bytes()).hexdigest()
  for flag,count in (([],0),(['--synthetic'],1)):
   run=subprocess.run([sys.executable,'-X','utf8','-m','dojo','--db',str(self.path),'questions',*flag],capture_output=True,text=True,encoding='utf-8',timeout=20)
   self.assertEqual(0,run.returncode,run.stderr);self.assertEqual(count,len(json.loads(run.stdout)['nodes']))
  self.assertEqual(before,hashlib.sha256(self.path.read_bytes()).hexdigest())
 def test_source_catalog_sends_shared_material_once_and_resends_changed_state(self):
  claim=self.proposal();source=self.q.record('tool_result',{'status':'executed','result':{'semantic_accuracy':'not_measured'}});self.show(source)
  self.map([self.node('a','怎样核查？')],[self.link('a',claim,source,'not_measured')])
  user=self.q.record('user',{'text':'继续','synthetic':True})
  first=self.q.prompt_context('继续',user,[],[],self.q.question_context())
  second=self.q.prompt_context('继续',user,[],[],self.q.question_context())
  self.assertIn(source,[s['event'] for s in first['source_catalog']]);self.assertEqual([],second['source_catalog'])
  replacement=self.q.record('tool_result',{'status':'executed','result':{'semantic_accuracy':'still_not_measured'}})
  self.q.dependencies.revise(source,replacement,'来源更新')
  changed=self.q.prompt_context('继续',user,[],[],self.q.question_context())
  s=next(s for s in changed['source_catalog'] if s['event']==source)
  self.assertEqual('superseded',s['dependency_status']['state'])
if __name__=='__main__':unittest.main()
