import email.message
import io
import unittest
from dojo.sources import read_source
from dojo.search import SearchError
from unittest.mock import Mock

PUBLIC=lambda *a,**k:[(2,1,6,'',('93.184.216.34',443))]
class SourceTests(unittest.TestCase):
 def response(self,body,media='text/html'):
  value=io.BytesIO(body);value.headers=email.message.Message();value.headers['Content-Type']=media
  return value
 def test_public_html_is_actually_read_and_scripts_are_removed(self):
  opener=Mock();opener.open.return_value=self.response(b'<html><script>secret()</script><article>actual evidence</article></html>')
  result=read_source('https://example.org/paper',opener=opener,resolver=PUBLIC)
  self.assertIn('actual evidence',result['text']);self.assertNotIn('secret',result['text'])
  self.assertFalse(result['truncated'])
 def test_local_or_non_https_sources_are_rejected_before_open(self):
  opener=Mock()
  for url in ('http://example.org','https://user:pass@example.org','https://example.org:8443'):
   with self.assertRaises(SearchError):read_source(url,opener=opener,resolver=PUBLIC)
  with self.assertRaises(SearchError):read_source('https://localhost',opener=opener,resolver=lambda *a,**k:[(2,1,6,'',('127.0.0.1',443))])
  opener.open.assert_not_called()
 def test_binary_is_a_failure_and_large_text_is_explicitly_partial(self):
  for body,media,kind in ((b'%PDF','application/pdf','source_type'),):
   opener=Mock();opener.open.return_value=self.response(body,media)
   with self.assertRaises(SearchError) as error:read_source('https://example.org/p',opener=opener,resolver=PUBLIC)
   self.assertEqual(kind,error.exception.kind)
  opener=Mock();opener.open.return_value=self.response(b'x'*256001,'text/plain')
  result=read_source('https://example.org/p',opener=opener,resolver=PUBLIC)
  self.assertTrue(result['truncated']);self.assertEqual(20000,len(result['text']))
 def test_workstation_fake_dns_is_allowed_only_for_hostnames(self):
  fake=lambda *a,**k:[(2,1,6,'',('198.18.0.6',443))]
  opener=Mock();opener.open.return_value=self.response(b'actual source','text/plain')
  self.assertEqual('actual source',read_source('https://arxiv.org/p',opener=opener,resolver=fake)['text'])
  with self.assertRaises(SearchError):read_source('https://198.18.0.6/p',opener=opener,resolver=fake)
if __name__=='__main__':unittest.main()
