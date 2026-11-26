import json
from types import SimpleNamespace
import unittest

from dojo.associations import validate,perform
from dojo.live import LiveError
from tests import test_associations as fixtures


class AssociationDiagnosticTests(unittest.TestCase):
 def test_structural_errors_have_safe_phases_without_raw_values(self):
  secret='PRIVATE_VALUE_SHOULD_NOT_ENTER_DIAGNOSTICS'
  base=dict(questions=[],links=[],reason='Organize only')
  cases=[('```json\n'+json.dumps(base)+'\n```','json'),
    (json.dumps({**base,secret:secret}),'envelope'),
    (json.dumps({**base,'questions':[dict(key='q',text=secret,parents=[],origin_anchor=True)]}),'question_fields'),
    (json.dumps({**base,'questions':[dict(key='q',text=secret,parents=secret,origin_anchor=1)]}),'question_structure'),
    (json.dumps({**base,'links':[dict(question=1,proposition=2,anchor=3,relation=secret,explanation=secret)]}),'link_relation_or_explanation')]
  for content,stage in cases:
   with self.subTest(stage=stage),self.assertRaises(LiveError) as result:validate(content)
   error=result.exception
   self.assertEqual('association_schema',error.kind);self.assertEqual(stage,error.validation_code)
   self.assertNotIn(secret,json.dumps(error.validation_details));self.assertFalse(error.raw_response)
  self.assertEqual(base,validate(json.dumps(base)))
 def test_failed_worker_records_only_structure_and_does_not_retry_or_write_graph(self):
  fixture=fixtures.AssociationTests();fixture.setUp()
  try:
   q=fixture.q;before=q.questions.view(story=q.story,synthetic=True);calls=[]
   def complete(messages):
    calls.append(messages)
    return validate(json.dumps(dict(questions=[],links=[],reason='OK',PRIVATE_VALUE_SHOULD_NOT_ENTER_DIAGNOSTICS='private')))
   client=SimpleNamespace(complete=complete)
   result=perform(q,client)
   self.assertEqual('failed',result['status'])
   failure=json.loads(q.db.execute("SELECT payload FROM inquiry_events WHERE kind='association_failure' ORDER BY seq DESC LIMIT 1").fetchone()[0])
   self.assertEqual('envelope',failure['validation_code'])
   self.assertEqual(1,failure['validation_details']['envelope']['unknown_field_count'])
   self.assertNotIn('PRIVATE_VALUE_SHOULD_NOT_ENTER_DIAGNOSTICS',json.dumps(failure))
   self.assertEqual(before,q.questions.view(story=q.story,synthetic=True))
   self.assertEqual('unchanged',perform(q,client)['status']);self.assertEqual(1,len(calls))
  finally:fixture.tearDown()
 def test_explicit_recovery_only_retries_failed_packet_once_and_never_repeats_success(self):
  fixture=fixtures.AssociationTests();fixture.setUp()
  try:
   q=fixture.q;budget=q.requests;calls=[]
   def complete(messages):
    calls.append(messages)
    if len(calls)==1:return validate('{"questions":[],"links":[],"reason":"test","extra":true}')
    return fixture.response()
   client=SimpleNamespace(complete=complete)
   self.assertEqual('failed',perform(q,client)['status'])
   self.assertEqual('unchanged',perform(q,client)['status'])
   self.assertEqual('associated',perform(q,client,retry_failed=True)['status'])
   self.assertEqual(budget-2,q.requests);self.assertEqual(2,len(calls))
   self.assertEqual('unchanged',perform(q,client,retry_failed=True)['status'])
   self.assertEqual(2,len(calls));self.assertEqual(1,len(fixture.annotations()))
   requests=[json.loads(p) for (p,) in q.db.execute("SELECT payload FROM inquiry_events WHERE kind='association_request_started' ORDER BY seq")]
   self.assertNotIn('retry_failed',requests[0]);self.assertTrue(requests[1]['retry_failed'])
   with self.assertRaises(ValueError):perform(q,client,retry_failed=1)
  finally:fixture.tearDown()


if __name__=='__main__':unittest.main()
