import copy
import json
import unittest
from dojo.epistemics import packet,grounded,validate
from dojo.live import LiveError

class CritiqueSpanTests(unittest.TestCase):
 def issue(self,**kwargs):return {'span':1,'kind':'scope_leap','reason':'Check the condition','counterexample':'A hypothetical later task fails','rewrite':'Require evidence after the intervention',**kwargs}
 def test_exact_markdown_is_restored_and_legacy_quote_remains_strict(self):
  data=packet('这只说明**截至查看时**仍然在。\n尚未证明任务执行。',[])
  result=grounded(data,{'issues':[self.issue()]})
  self.assertEqual('这只说明**截至查看时**仍然在。',result['issues'][0]['quote']);self.assertNotIn('span',result['issues'][0]);self.assertEqual(1,result['span_resolutions'][0]['span'])
  raw={k:v for k,v in self.issue().items() if k!='span'}|{'quote':'这只说明截至查看时仍然在。'}
  with self.assertRaises(LiveError):grounded(data,{'issues':[raw]})
 def test_unknown_boolean_mixed_and_forged_spans_are_not_grounded(self):
  data=packet('第一句。第二句。',[])
  with self.assertRaises(LiveError):grounded(data,{'issues':[self.issue(span=999)]})
  for issue in [self.issue(span=True),self.issue(span=0),self.issue(quote='第一句。')]:
   with self.assertRaises(LiveError):validate(json.dumps({'issues':[issue]}))
  forged=copy.deepcopy(data);forged['draft_spans'][0]['quote']='编造'
  with self.assertRaises(LiveError):grounded(forged,{'issues':[self.issue()]})
 def test_catalog_is_bounded_and_offsets_are_exact_including_long_sentences(self):
  data=packet('长'*1500+'。\n'+('另一个句子。'*100),[])
  self.assertLessEqual(len(data['draft_spans']),64);self.assertTrue(data['draft_spans_truncated'])
  for span in data['draft_spans']:
   self.assertLessEqual(len(span['quote']),600);self.assertEqual(span['quote'],data['draft'][span['start']:span['end']])
  self.assertEqual([],grounded(packet('有条件的有效结论。',[]),{'issues':[]})['issues'])

if __name__=='__main__':unittest.main()
