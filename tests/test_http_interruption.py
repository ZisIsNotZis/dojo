import http.client
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
import urllib.error
from dojo.inquiry import Inquiry,make_client
from dojo.live import LiveConfig,LiveError

PARTIAL=b'PRIVATE_PARTIAL_RESPONSE_SENTINEL'
class BrokenBody(io.BytesIO):
 def read(self,*args):raise http.client.IncompleteRead(PARTIAL,4096)

class HTTPInterruptionTests(unittest.TestCase):
 def client(self):return make_client(LiveConfig('http://127.0.0.1:1/v1/chat/completions','deepseek-flash','KEY_SENTINEL'))
 def test_partial_success_body_is_normalized_and_never_retried_or_captured(self):
  c=self.client();opener=Mock();opener.open.return_value=BrokenBody()
  with patch('dojo.live.urllib.request.build_opener',return_value=opener),self.assertRaises(LiveError) as caught:c.complete([{'role':'user','content':'继续'}])
  # Was 'connect'. A cut body is not a failed connection: the request was answered
  # and may have been applied, so `discuss` must not retry it as a transient
  # network error. The kind is separate now, and this test names the new fact.
  self.assertEqual('incomplete_response',caught.exception.kind);self.assertEqual(1,opener.open.call_count)
  self.assertEqual('',caught.exception.raw_response);self.assertIsNone(c.last_response_shape)
  self.assertNotIn(PARTIAL.decode(),str(caught.exception))
 def test_partial_http_error_body_preserves_status_without_partial_content(self):
  c=self.client();opener=Mock();opener.open.side_effect=urllib.error.HTTPError(c.config.endpoint,503,'Unavailable',None,BrokenBody())
  with patch('dojo.live.urllib.request.build_opener',return_value=opener),self.assertRaises(LiveError) as caught:c.complete([{'role':'user','content':'继续'}])
  self.assertEqual('http_error',caught.exception.kind);self.assertEqual(503,caught.exception.http_status)
  self.assertNotIn(PARTIAL.decode(),caught.exception.raw_response or '')
  self.assertEqual(1,opener.open.call_count)
 def test_inquiry_keeps_user_and_budget_but_delivers_no_partial_reply(self):
  c=self.client();opener=Mock();opener.open.return_value=BrokenBody()
  with tempfile.TemporaryDirectory() as tmp:
   q=Inquiry(Path(tmp)/'db',c,synthetic=True,request_budget=3)
   try:
    with patch('dojo.live.urllib.request.build_opener',return_value=opener),self.assertRaises(LiveError):q.turn('继续推进判断')
    self.assertEqual(2,q.requests);self.assertEqual(1,opener.open.call_count)
    rows=q.db.execute('SELECT kind,payload FROM inquiry_events').fetchall()
    self.assertEqual(1,sum(k=='user' for k,p in rows));self.assertEqual(0,sum(k=='delivered' for k,p in rows))
    self.assertEqual('incomplete_response',next(json.loads(p)['kind'] for k,p in rows if k=='failure'))
    self.assertNotIn(PARTIAL.decode(),json.dumps(rows));self.assertNotIn('KEY_SENTINEL',json.dumps(rows))
   finally:q.close()

if __name__=='__main__':unittest.main()
