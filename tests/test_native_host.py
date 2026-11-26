import io
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock,patch
from dojo.live import LiveConfig,LiveError
from dojo.inquiry import Inquiry,make_client

SECRET='REASONING_PRIVATE_SENTINEL'
def reply(content=None,calls=None,finish='stop'):
 message={'role':'assistant','content':content,'reasoning_content':SECRET}
 if calls is not None:message['tool_calls']=calls
 return io.BytesIO(json.dumps({'choices':[{'message':message,'finish_reason':finish}]}).encode())
def tool(name='calculate',arguments=None):
 return {'id':'call-id','type':'function','function':{'name':name,'arguments':arguments or json.dumps({'expression':'100/(10-2)','basis':'模型假设','prediction':'12.5'})}}
def client():return make_client(LiveConfig('http://127.0.0.1:1/v1/chat/completions','deepseek-flash','CONFIG_SECRET'))

class NativeHostTests(unittest.TestCase):
 def test_natural_answer_does_not_require_json_and_uses_auto_low_tools(self):
  c=client();opener=Mock();opener.open.return_value=reply('先讲一个具体经历，我们再一起判断。')
  with patch('dojo.live.urllib.request.build_opener',return_value=opener):r=c.complete([{'role':'user','content':'我说不清'}])
  self.assertIn('具体经历',r['answer']);self.assertIsNone(r['action'])
  payload=json.loads(opener.open.call_args.args[0].data)
  self.assertEqual('auto',payload['tool_choice']);self.assertEqual('low',payload['reasoning_effort'])
  self.assertEqual({'type':'text'},payload['response_format'])
  self.assertEqual({'check_progress','check_entailment','check_design','calculate','experiment','diagnose_experiment','search','read_source','text_experiment','map_inquiry'},{tool['function']['name'] for tool in payload['tools']})
  self.assertNotIn(SECRET,json.dumps(r));self.assertNotIn(SECRET,json.dumps(c.last_response_shape))
 def test_native_function_is_executed_by_runtime_and_receipt_reaches_next_request(self):
  c=client();opener=Mock();opener.open.side_effect=[reply(calls=[tool()],finish='tool_calls'),reply('实际计算得到12.5；仅限给定假设。')]
  with tempfile.TemporaryDirectory() as d:
   q=Inquiry(Path(d)/'db',c,synthetic=True)
   try:
    with patch('dojo.live.urllib.request.build_opener',return_value=opener):answer=q.turn('请验证阈值')
    self.assertIn('12.5',answer)
    event=json.loads(q.db.execute("SELECT payload FROM inquiry_events WHERE kind='tool_result'").fetchone()[0])
    self.assertEqual(12.5,event['result']['value'])
    messages=json.loads(opener.open.call_args.args[0].data)['messages']
    self.assertIn('12.5',messages[-1]['content']);self.assertIn('尚未执行',messages[-2]['content'])
    self.assertNotIn(SECRET,json.dumps(list(q.db.execute('SELECT payload FROM inquiry_events'))))
   finally:q.close()
 def test_invalid_tool_after_actual_execution_gets_one_tools_disabled_synthesis(self):
  for obeys in (True,False):
   with self.subTest(obeys=obeys),tempfile.TemporaryDirectory() as d:
    c=client();opener=Mock();opener.open.side_effect=[reply(calls=[tool()],finish='tool_calls'),reply(calls=[tool('map_inquiry','not JSON')],finish='tool_calls'),reply('已算得12.5，后续制图未执行。') if obeys else reply(calls=[tool()],finish='tool_calls')]
    q=Inquiry(Path(d)/'db',c,synthetic=True,request_budget=3)
    try:
     with patch('dojo.live.urllib.request.build_opener',return_value=opener):
      if obeys:self.assertIn('12.5',q.turn('验证阈值'))
      else:
       with self.assertRaises(LiveError) as caught:q.turn('验证阈值')
       self.assertEqual('tools_disabled',caught.exception.kind)
     self.assertEqual(3,opener.open.call_count);self.assertEqual(0,q.requests);self.assertEqual(3,q.tools)
     payload=json.loads(opener.open.call_args.args[0].data);self.assertEqual('none',payload['tool_choice']);self.assertIn('12.5',json.dumps(payload['messages'],ensure_ascii=False))
     self.assertEqual(1,q.db.execute("SELECT count(*) FROM inquiry_events WHERE kind='tool_started'").fetchone()[0])
     self.assertEqual(1,q.db.execute("SELECT count(*) FROM inquiry_events WHERE kind='delivery_repair_requested'").fetchone()[0])
     self.assertEqual(1 if obeys else 0,q.db.execute("SELECT count(*) FROM inquiry_events WHERE kind='delivered'").fetchone()[0])
     self.assertNotIn(SECRET,json.dumps(list(q.db.execute('SELECT payload FROM inquiry_events'))))
    finally:q.close()
 def test_native_text_experiment_shares_host_budget_and_returns_observations(self):
  from dojo.text_experiments import validate_representation
  arguments=json.dumps({'source_events':[2],'probes':[{'question':'为何不迁移？','event':2,'quote':'还没有达到迁移条件'}],'prediction':'摘要也可能保留条件'},ensure_ascii=False)
  c=client();opener=Mock();opener.open.side_effect=[reply(calls=[tool('text_experiment',arguments)],finish='tool_calls'),reply('两臂都保留了给定条件；不证明现实效果。')]
  def backend(q,validator):
   class Backend:
    def complete(self,messages):
     if validator is validate_representation:return validator('还没有达到迁移条件')
     return validator('{"answers":[{"index":0,"answer":"条件不足","quotes":["还没有达到迁移条件"],"unknown":false}]}')
   return Backend()
  with tempfile.TemporaryDirectory() as d:
   q=Inquiry(Path(d)/'db',c,synthetic=True)
   try:
    with patch('dojo.live.urllib.request.build_opener',return_value=opener),patch('dojo.text_experiments.backend',side_effect=backend):answer=q.turn('还没有达到迁移条件，先保留当前库。')
    self.assertIn('不证明现实效果',answer)
    self.assertEqual(6,q.requests);self.assertEqual(3,q.tools);self.assertEqual(2,opener.open.call_count)
    self.assertEqual(4,q.db.execute("SELECT count(*) FROM inquiry_events WHERE kind='text_request_started'").fetchone()[0])
    messages=json.loads(opener.open.call_args.args[0].data)['messages']
    self.assertIn('reference_verbatim_in_representation',messages[-1]['content'])
   finally:q.close()
 def test_native_question_map_is_written_and_returned_without_becoming_truth(self):
  arguments=json.dumps({'questions':[{'key':'root','text':'如何帮助陌生人？','parents':[],'origin_event':2,'origin_quote':'经验要能帮助陌生人','revises':None}],
   'links':[{'question':'root','proposition':None,'source_event':2,'quote':'经验要能帮助陌生人','relation':'context','explanation':'这是用户表达的目的，仍需检验机制'}],'prediction':'把目的和未知问题分开'},ensure_ascii=False)
  c=client();opener=Mock();opener.open.side_effect=[reply(calls=[tool('map_inquiry',arguments)],finish='tool_calls'),reply('问题已组织，仍需检验怎样帮助陌生人。')]
  with tempfile.TemporaryDirectory() as d:
   q=Inquiry(Path(d)/'db',c,synthetic=True)
   try:
    with patch('dojo.live.urllib.request.build_opener',return_value=opener):q.turn('经验要能帮助陌生人，不想填卡。')
    graph=q.questions.view(story=q.story,synthetic=True)
    self.assertEqual(1,len(graph['nodes']));self.assertEqual('context',graph['nodes'][0]['annotations'][0]['relation'])
    self.assertIn(graph['nodes'][0]['event'],q.visible_source_text)
    self.assertEqual('agent_organization_not_truth_verdict',q.knowledge.source(graph['nodes'][0]['event'])['epistemic_status'])
    self.assertEqual(10,q.requests);self.assertEqual(3,q.tools)
    messages=json.loads(opener.open.call_args.args[0].data)['messages'];self.assertIn('question_keys',messages[-1]['content'])
   finally:q.close()
 def test_known_question_shape_failure_has_one_budgeted_repair_but_no_unbounded_retry(self):
  valid={'questions':[{'key':'root','text':'如何帮助陌生人？','parents':[],'origin_event':2,'origin_quote':'经验要能帮助陌生人','revises':None}],'links':[],'prediction':'组织问题'}
  invalid=json.loads(json.dumps(valid));invalid['questions'][0].pop('revises')
  for repair_succeeds in (True,False):
   with self.subTest(repair_succeeds=repair_succeeds),tempfile.TemporaryDirectory() as d:
    c=client();opener=Mock();responses=[reply(calls=[tool('map_inquiry',json.dumps(invalid))],finish='tool_calls')]
    responses.append(reply(calls=[tool('map_inquiry',json.dumps(valid if repair_succeeds else invalid))],finish='tool_calls'))
    if repair_succeeds:responses.append(reply('问题已保存；未授予事实状态。'))
    opener.open.side_effect=responses;q=Inquiry(Path(d)/'db',c,synthetic=True)
    try:
     with patch('dojo.live.urllib.request.build_opener',return_value=opener):
      if repair_succeeds:q.turn('经验要能帮助陌生人')
      else:
       with self.assertRaises(LiveError):q.turn('经验要能帮助陌生人')
     self.assertEqual(1,q.db.execute("SELECT count(*) FROM inquiry_events WHERE kind='schema_repair_requested'").fetchone()[0])
     failures=[json.loads(r[0]) for r in q.db.execute("SELECT payload FROM inquiry_events WHERE kind='failure'")]
     self.assertEqual('invalid_question_fields',failures[0]['response_shape']['native_validation_code'])
     self.assertEqual(3 if repair_succeeds else 2,opener.open.call_count)
     self.assertEqual(9 if repair_succeeds else 10,q.requests)
    finally:q.close()
 def test_unknown_malformed_and_truncated_batches_are_not_partially_executed(self):
  cases=[([tool('shell')],'tool_calls'),([tool(),tool('shell')],'tool_calls'),([tool(arguments='not JSON')],'tool_calls'),([tool(arguments='{"kind":"shell"}')],'tool_calls'),([tool()],'length'),([tool()]*5,'tool_calls')]
  for calls,finish in cases:
   with self.subTest(finish=finish,calls=len(calls)):
    c=client();opener=Mock();opener.open.return_value=reply(calls=calls,finish=finish)
    with tempfile.TemporaryDirectory() as d:
     q=Inquiry(Path(d)/'db',c,synthetic=True)
     try:
      with patch('dojo.live.urllib.request.build_opener',return_value=opener):
       with self.assertRaises(LiveError) as caught:q.turn('验证一下')
      self.assertEqual(len(calls),c.last_response_shape['tool_calls_count'])
      if caught.exception.kind=='native_tool_schema':self.assertIn('native_validation_stage',c.last_response_shape)
      self.assertEqual(1,opener.open.call_count)
      self.assertEqual(0,q.db.execute("SELECT count(*) FROM inquiry_events WHERE kind='tool_started'").fetchone()[0])
     finally:q.close()
 def test_valid_batch_runs_each_action_and_sends_all_receipts(self):
  c=client();opener=Mock();opener.open.side_effect=[reply(calls=[tool(),tool(arguments='{"expression":"1+1","basis":"模型","prediction":"2"}')],finish='tool_calls'),reply('两次实际计算：12.5和2。')]
  with tempfile.TemporaryDirectory() as d:
   q=Inquiry(Path(d)/'db',c,synthetic=True)
   try:
    with patch('dojo.live.urllib.request.build_opener',return_value=opener):q.turn('分别核实')
    events=[json.loads(r[0]) for r in q.db.execute("SELECT payload FROM inquiry_events WHERE kind='tool_result'")]
    self.assertEqual([12.5,2],[e['result']['value'] for e in events])
    self.assertEqual(2,q.tools);self.assertEqual(10,q.requests)
    messages=json.loads(opener.open.call_args.args[0].data)['messages']
    self.assertIn('12.5',messages[-2]['content']);self.assertIn('2',messages[-1]['content'])
   finally:q.close()
 def test_budget_shortfall_has_an_explicit_not_executed_receipt(self):
  c=client();opener=Mock();opener.open.side_effect=[reply(calls=[tool(),tool()],finish='tool_calls'),reply('只完成第一项，第二项未执行。')]
  with tempfile.TemporaryDirectory() as d:
   q=Inquiry(Path(d)/'db',c,synthetic=True,tool_budget=1)
   try:
    with patch('dojo.live.urllib.request.build_opener',return_value=opener):q.turn('核实两项')
    rows=list(q.db.execute("SELECT seq,payload FROM inquiry_events WHERE kind='tool_result'"))
    self.assertEqual(['executed','not_executed'],[json.loads(r[1])['status'] for r in rows])
    self.assertEqual('tool_failure_not_positive_evidence',q.knowledge.source(rows[1][0])['epistemic_status'])
    self.assertEqual(1,q.db.execute("SELECT count(*) FROM inquiry_events WHERE kind='tool_started'").fetchone()[0])
   finally:q.close()
 def test_zero_tool_or_synthesis_budget_denies_every_item_without_executing(self):
  for tools,requests,reason in ((0,3,'budget'),(3,1,'synthesis_budget')):
   with self.subTest(tools=tools,requests=requests):
    c=client();opener=Mock();opener.open.return_value=reply(calls=[tool(),tool()],finish='tool_calls')
    with tempfile.TemporaryDirectory() as d:
     q=Inquiry(Path(d)/'db',c,synthetic=True,tool_budget=tools,request_budget=requests)
     try:
      with patch('dojo.live.urllib.request.build_opener',return_value=opener):answer=q.turn('核实两项')
      rows=[json.loads(r[0]) for r in q.db.execute("SELECT payload FROM inquiry_events WHERE kind='tool_result'")]
      self.assertEqual(['not_executed']*2,[r['status'] for r in rows])
      self.assertEqual([reason]*2,[r['error_kind'] for r in rows])
      self.assertEqual(0,q.db.execute("SELECT count(*) FROM inquiry_events WHERE kind='tool_started'").fetchone()[0])
      self.assertEqual(tools,q.tools);self.assertEqual(1,opener.open.call_count)
      self.assertIn('未执行',answer)
     finally:q.close()
 def test_internal_plan_without_native_calls_is_not_delivered_or_executed(self):
  plan='计划验证：'+json.dumps([{'kind':'calculate','expression':'1+1','basis':'assumption','prediction':'2'}],ensure_ascii=False)
  for succeeds,budget in [(True,3),(False,3),(False,1)]:
   with self.subTest(succeeds=succeeds,budget=budget),tempfile.TemporaryDirectory() as d:
    c=client();opener=Mock();opener.open.side_effect=[reply(plan),reply('已知只有先前材料；那项计划没有执行。' if succeeds else plan)]
    q=Inquiry(Path(d)/'db',c,synthetic=True,request_budget=budget)
    try:
     with patch('dojo.live.urllib.request.build_opener',return_value=opener):
      if succeeds:self.assertIn('没有执行',q.turn('继续核实'))
      else:
       with self.assertRaises(LiveError) as caught:q.turn('继续核实')
       self.assertEqual('unexecuted_plan',caught.exception.kind)
     self.assertEqual(1 if budget==1 else 2,opener.open.call_count)
     self.assertEqual(0,q.db.execute("SELECT count(*) FROM inquiry_events WHERE kind='tool_started'").fetchone()[0])
     self.assertEqual(1 if succeeds else 0,q.db.execute("SELECT count(*) FROM inquiry_events WHERE kind='delivered'").fetchone()[0])
     self.assertEqual(4,q.tools)
    finally:q.close()
 def test_native_history_does_not_teach_model_to_emit_serialized_plans(self):
  c=client();opener=Mock();opener.open.side_effect=[reply(calls=[tool()],finish='tool_calls'),reply('实际算得12.5。')]
  with tempfile.TemporaryDirectory() as d:
   q=Inquiry(Path(d)/'db',c,synthetic=True)
   try:
    with patch('dojo.live.urllib.request.build_opener',return_value=opener):q.turn('计算一下')
    messages=json.loads(opener.open.call_args.args[0].data)['messages']
    plans=[m['content'] for m in messages if m['role']=='assistant']
    self.assertTrue(plans);self.assertFalse(any(p.startswith('计划验证：') or '"expression"' in p for p in plans))
    self.assertIn('"expression"',messages[-1]['content'])
   finally:q.close()
if __name__=='__main__':unittest.main()
