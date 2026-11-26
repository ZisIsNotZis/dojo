import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from dojo.inquiry import Inquiry

ROOT=Path(__file__).resolve().parents[1]
class Client:
 config=SimpleNamespace(model='deepseek-flash',api_key=None)

class KnowledgeCliTests(unittest.TestCase):
 def run_cli(self,path,*args):
  return subprocess.run([sys.executable,'-X','utf8','-m','dojo','--db',str(path),*args],cwd=ROOT,text=True,encoding='utf-8',capture_output=True,timeout=20)
 def test_listing_absent_database_does_not_create_it(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'absent.sqlite3';result=self.run_cli(p,'knowledge')
   self.assertEqual(0,result.returncode,result.stderr);self.assertEqual([],json.loads(result.stdout));self.assertFalse(p.exists())
 def test_existing_knowledge_listing_is_read_only_and_labels_synthetic(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'db';q=Inquiry(p,Client(),synthetic=True)
   source=q.record('user',{'text':'设置成本100分钟','synthetic':True})
   proposal={'statement':'固定成本需要在使用次数中摊销','kind':'decision','method':'hypothesis',
    'premises':[{'event':source,'quote':'设置成本100分钟','role':'assumption'}],
    'assumptions':[],'conditions':[],'alternatives':[],'falsifier':'没有固定成本时需要重新判断','revises':None}
   q.knowledge.accept(q.run,proposal,{source},synthetic=True);q.close()
   before=hashlib.sha256(p.read_bytes()).hexdigest()
   regular=self.run_cli(p,'knowledge');synthetic=self.run_cli(p,'knowledge','--synthetic')
   self.assertEqual(0,regular.returncode,regular.stderr);self.assertEqual([],json.loads(regular.stdout))
   self.assertEqual(0,synthetic.returncode,synthetic.stderr);self.assertTrue(json.loads(synthetic.stdout)[0]['synthetic'])
   self.assertEqual(before,hashlib.sha256(p.read_bytes()).hexdigest())

class EmptyIsNotSilentTests(unittest.TestCase):
 """An empty default listing must say which kind of empty it is.

 `[]` alone cannot separate 'no proposal records exist here' from 'they exist
 and the default scope filtered every one'. Both sentences go to stderr so the
 stdout value every caller parses stays exactly what it was.
 """
 def run_cli(self,path,*args):
  return subprocess.run([sys.executable,'-X','utf8','-m','dojo','--db',str(path),*args],cwd=ROOT,text=True,encoding='utf-8',capture_output=True,timeout=20)
 def make(self,path,synthetic,count):
  q=Inquiry(path,Client(),synthetic=synthetic)
  source=q.record('user',{'text':'设置成本100分钟','synthetic':synthetic})
  for i in range(count):
   proposal={'statement':'固定成本需要在使用次数中摊销 %d'%i,'kind':'decision','method':'hypothesis',
    'premises':[{'event':source,'quote':'设置成本100分钟','role':'assumption'}],
    'assumptions':[],'conditions':[],'alternatives':[],'falsifier':'没有固定成本时需要重新判断','revises':None}
   q.knowledge.accept(q.run,proposal,{source},synthetic=synthetic)
  q.close()
 def test_a_synthetic_only_ledger_states_how_many_rows_it_hid(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'db';self.make(p,True,3)
   before=hashlib.sha256(p.read_bytes()).hexdigest()
   result=self.run_cli(p,'knowledge')
   self.assertEqual(0,result.returncode,result.stderr)
   self.assertEqual([],json.loads(result.stdout))
   self.assertIn('3 条知识提议记录',result.stderr)
   self.assertIn('--synthetic',result.stderr)
   for word in ('依据','来源','时刻'):self.assertNotIn(word,result.stderr)
   self.assertEqual(before,hashlib.sha256(p.read_bytes()).hexdigest())
 def test_a_ledger_without_any_proposal_counts_nothing_and_says_zero_not_filtered(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'db';q=Inquiry(p,Client(),synthetic=True);q.record('user',{'text':'只有一句话','synthetic':True});q.close()
   result=self.run_cli(p,'knowledge')
   self.assertEqual(0,result.returncode,result.stderr)
   self.assertEqual([],json.loads(result.stdout))
   self.assertIn('没有知识提议记录',result.stderr)
   self.assertNotIn('--synthetic',result.stderr)
   self.assertFalse(any(ch.isdigit() for ch in result.stderr),result.stderr)
 def test_a_ledger_with_a_plain_record_is_listed_and_never_called_filtered(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'db';self.make(p,False,1)
   result=self.run_cli(p,'knowledge')
   self.assertEqual(0,result.returncode,result.stderr)
   self.assertEqual(1,len(json.loads(result.stdout)))
   self.assertNotIn('默认视图不列出',result.stderr)
   self.assertNotIn('--synthetic',result.stderr)
 def test_a_mixed_ledger_reports_the_split_it_actually_applies(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'db';self.make(p,True,2)
   q=Inquiry(p,Client(),synthetic=False)
   source=q.record('user',{'text':'普通的一句话','synthetic':False})
   proposal={'statement':'普通身份下的一条提议','kind':'decision','method':'hypothesis',
    'premises':[{'event':source,'quote':'普通的一句话','role':'assumption'}],
    'assumptions':[],'conditions':[],'alternatives':[],'falsifier':'没有的情况下需要重新判断','revises':None}
   q.knowledge.accept(q.run,proposal,{source},synthetic=False);q.close()
   result=self.run_cli(p,'knowledge')
   self.assertEqual(0,result.returncode,result.stderr)
   self.assertEqual(1,len(json.loads(result.stdout)))
   self.assertIn('3 条知识提议记录',result.stderr)
   self.assertIn('2 条标注为合成',result.stderr)
   self.assertIn('另有 1 条未标注为合成',result.stderr)
 def test_a_ledger_bigger_than_the_read_window_still_counts_the_whole_ledger(self):
  # `proposals()` reads the newest 100 rows and only then drops synthetic ones,
  # so an older plain record can be outside the window and never printed. The
  # note may therefore state the ledger's composition but must not promise
  # that the default view lists a particular number of rows.
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'db';self.make(p,False,1)
   self.make(p,True,120)
   result=self.run_cli(p,'knowledge')
   self.assertEqual(0,result.returncode,result.stderr)
   self.assertEqual([],json.loads(result.stdout))
   self.assertIn('121 条知识提议记录',result.stderr)
   self.assertIn('120 条标注为合成',result.stderr)
   for promise in ('只列出','已一并列出','全部列出'):
    self.assertNotIn(promise,result.stderr)
if __name__=='__main__':unittest.main()
