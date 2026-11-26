import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from dojo.context_window import pack
from dojo.inquiry import Inquiry,validate_host


class ContextWindowTests(unittest.TestCase):
 def test_catalog_omission_preserves_current_user_receipt_and_original_messages(self):
  value={'user_event':20,'user':'CURRENT USER','user_source':{'event':20,'text':'CURRENT USER'},'source_catalog':[
   {'event':2,'kind':'user','text':'ORIGINAL GOAL'}, {'event':3,'kind':'reflection','text':'OLD MODEL '*400},
   {'event':5,'kind':'tool_result','text':'OLD TOOL '*400}],
   'citation_anchors':[{'anchor':11,'source_event':3},{'anchor':25,'source_event':99}]}
  messages=[{'role':'system','content':'SYSTEM'},{'role':'user','content':json.dumps(value)},
   {'role':'user','content':'系统实际工具回执\nLATEST RECEIPT'}]
  original=copy.deepcopy(messages);shown,result=pack(messages,limit=2000,target=1500)
  self.assertEqual('packed',result['status']);self.assertLessEqual(result['characters_after'],2000)
  self.assertEqual(original,messages);self.assertEqual(original[-1],shown[-1]);self.assertEqual(original[0],shown[0])
  view=json.loads(shown[1]['content']);self.assertEqual('CURRENT USER',view['user_source']['text'])
  self.assertEqual('ORIGINAL GOAL',view['source_catalog'][0]['text'])
  self.assertTrue(view['source_catalog'][1]['body_omitted_for_context_limit'])
  self.assertEqual([{'anchor':25,'source_event':99}],view['citation_anchors'])
  self.assertEqual(1,result['citation_anchors_suppressed'])
 def test_explicit_restore_catalog_is_supported_and_plain_user_json_is_not_pruned(self):
  restore={'previous_run':'old','sources':[{'event':2,'kind':'reflection','text':'HISTORY'*500}],
   'latest_intent_snapshot':{'goal':'KEEP GOAL'}}
  message={'role':'user','content':'系统恢复\n'+json.dumps(restore)}
  plain={'role':'user','content':json.dumps({'text':'USER '*500})}
  shown,result=pack([message,plain],limit=3500,target=3000)
  self.assertEqual(plain,shown[1]);self.assertEqual('packed',result['status'])
  self.assertIn('KEEP GOAL',shown[0]['content']);self.assertIn('body_omitted',shown[0]['content'])
 def test_unmodified_small_context_and_uncompressible_big_input_are_explicit(self):
  messages=[{'role':'user','content':'x'*100}]
  shown,result=pack(messages,limit=200,target=150);self.assertIs(shown,messages);self.assertEqual('unchanged',result['status'])
  shown,result=pack(messages,limit=50,target=40)
  self.assertEqual('insufficient_space',result['status']);self.assertEqual(messages,shown)
 def test_real_turn_packs_history_and_still_delivers_after_tool_receipt(self):
  packets=[];config=SimpleNamespace(model='deepseek-flash',api_key=None)
  class Host:
   def __init__(self):self.config=config
   def complete(self,messages):
    packets.append(copy.deepcopy(messages))
    self_test.assertLessEqual(sum(len(m['content']) for m in messages),120000)
    if len(packets)==1:return validate_host(json.dumps({'answer':'验证一个算式','action':{'kind':'calculate','expression':'2+2','basis':'Arithmetic only','prediction':'4'}}))
    return validate_host(json.dumps({'answer':'实际计算为4；原问题仍保留。','action':None}))
  self_test=self
  with tempfile.TemporaryDirectory() as tmp:
   q=Inquiry(Path(tmp)/'db',Host(),synthetic=True,request_budget=3)
   try:
    q.messages.append({'role':'user','content':json.dumps({'previous_run':'fixture','sources':[{'event':0,'kind':'reflection','text':'X'*130000}],'latest_intent_snapshot':None})})
    original=copy.deepcopy(q.messages)
    self.assertIn('实际计算为4',q.turn('继续原问题'))
    self.assertEqual(original[1],q.messages[1]);self.assertEqual(1,q.requests)
    self.assertEqual(1,q.db.execute("SELECT count(*) FROM inquiry_events WHERE kind='delivered'").fetchone()[0])
    self.assertGreater(q.db.execute("SELECT count(*) FROM inquiry_events WHERE kind='context_projection'").fetchone()[0],0)
   finally:q.close()

if __name__=='__main__':unittest.main()
