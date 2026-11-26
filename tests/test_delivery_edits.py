import copy
import json
import unittest
from dojo.delivery_edits import packet,apply,validate,digest
from dojo.live import LiveError

class DeliveryEditTests(unittest.TestCase):
 def setUp(self):
  self.draft='错误一。\n错误二。\n不可动表格：甲乙丙丁。\n前缀：8种方案。\n结尾。'
  issues=[];locations=[]
  for i,text in enumerate(('错误一。','错误二。')):
   start=self.draft.index(text);issues.append({'quote':text,'kind':'scope_leap','reason':'Check scope','counterexample':'A hypothetical exception','rewrite':'A suggestion, not a command'})
   locations.append({'issue':i,'span':i+1,'start':start,'end':start+len(text)})
  self.shown=packet(self.draft,[],{'issues':issues,'span_resolutions':locations})
 def decision(self,span,disposition='replace',replacement='有限条件。'):
  return {'span':span,'disposition':disposition,'replacement':replacement,'reason':'The bounded source supports only this scope'}
 def test_two_local_edits_preserve_every_other_character_and_allow_rejecting_critique(self):
  response={'decisions':[self.decision(2,'retain',None),self.decision(1)]}
  result=apply(self.draft,self.shown,response)
  self.assertEqual(self.draft.replace('错误一。','有限条件。'),result['answer']);self.assertEqual(1,len(result['edits']))
  deleted=apply(self.draft,self.shown,{'decisions':[self.decision(1,replacement=''),self.decision(2)]})
  self.assertIn('不可动表格：甲乙丙丁。',deleted['answer']);self.assertTrue(deleted['answer'].endswith('结尾。'))
 def test_changed_draft_or_forged_locations_fail_before_any_patch(self):
  response={'decisions':[self.decision(1),self.decision(2)]}
  with self.assertRaises(ValueError):apply(self.draft+'changed',self.shown,response)
  changed=copy.deepcopy(self.shown);changed['edit_spans'][0]['start']=1;changed['sha256']=digest(changed)
  with self.assertRaises(ValueError):apply(self.draft,changed,response)
 def test_missing_extra_duplicate_or_unlocated_choices_are_rejected(self):
  for decisions in ([self.decision(1)],[self.decision(1),self.decision(3)],[self.decision(1),self.decision(1)]):
   with self.assertRaises((ValueError,LiveError)):apply(self.draft,self.shown,{'decisions':decisions})
  bad=copy.deepcopy(self.shown['review']);bad['span_resolutions']=[]
  with self.assertRaises(ValueError):packet(self.draft,[],bad)
 def test_retention_cannot_carry_a_hidden_edit_or_tool_action(self):
  for item in (self.decision(1,'retain','new'),{**self.decision(1),'action':{'kind':'calculate'}},self.decision(1,replacement='x'*2001)):
   with self.assertRaises(LiveError):validate(json.dumps({'decisions':[item]}))
 def test_independently_found_errors_can_only_use_bounded_offered_extra_spans(self):
  shown=packet(self.draft,[],self.shown['review'],additional_limit=1)
  span=next(s for s in shown['additional_spans'] if '前缀' in s['quote'])
  response={'decisions':[self.decision(1),self.decision(2),self.decision(span['span'],replacement='新前缀。')]}
  result=apply(self.draft,shown,response);self.assertIn('新前缀。',result['answer']);self.assertIn('不可动表格：甲乙丙丁。',result['answer'])
  more=next(s for s in shown['additional_spans'] if s['span']!=span['span']);response['decisions'].append(self.decision(more['span']))
  with self.assertRaises(ValueError):apply(self.draft,shown,response)

if __name__=='__main__':unittest.main()
