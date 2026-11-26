import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from dojo.experiments import diagnose,parameter_sweep,validate_diagnosis
from dojo.inquiry import Inquiry,validate_host
from tests.test_experiment_components import PARAMETERS,DERIVED,SECOND,THIRD

class DiagnosisTests(unittest.TestCase):
 def setUp(self):
  self.directory=tempfile.TemporaryDirectory()
  self.q=Inquiry(Path(self.directory.name)/'db',SimpleNamespace(config=SimpleNamespace(model='deepseek-flash',api_key=None)),synthetic=True)
  self.original={'kind':'experiment','parameters':PARAMETERS,'derived':DERIVED,'assertion':'gain_us == 2000*h-c_us and '+SECOND+' and '+THIRD,'assumptions':['Toy model'],'prediction':'Find numerical failures'}
  self.plan=self.q.record('reflection',{'reflection':{'answer':'Check','action':self.original}})
  self.source,self.receipt,_=self.q.execute_action(self.original,self.plan)
  self.action={'kind':'diagnose_experiment','source_event':self.source,'equality_indices':[0],'absolute_tolerance':1e-12,'prediction':'A 1e-12 microsecond tolerance should remove roundoff, preserving the economic condition.'}
 def tearDown(self):
  self.q.close();self.directory.cleanup()
 def test_frozen_conditions_and_immutable_original(self):
  before=self.q.db.execute('SELECT payload FROM inquiry_events WHERE seq=?',(self.source,)).fetchone()[0]
  validate_host(json.dumps({'answer':'Check','action':self.action}))
  event,result,_=self.q.execute_action(self.action,self.plan)
  self.assertEqual('executed',result['status'])
  data=result['result'];self.assertEqual(2,data['original']['counterexample_count']);self.assertEqual(0,data['tolerant']['counterexample_count'])
  self.assertEqual([1,2],data['unchanged_component_indices'])
  self.assertTrue(data['unselected_conditions_preserved'])
  self.assertNotIn('assertion',data['tolerant']);self.assertNotIn('domain',data['original'])
  self.assertEqual(before,self.q.db.execute('SELECT payload FROM inquiry_events WHERE seq=?',(self.source,)).fetchone()[0])
  self.assertTrue(self.q.dependencies.depends_on(event,self.source,include_execution_context=False))
  self.assertFalse(self.q.dependencies.depends_on(event,self.plan,include_execution_context=False))
 def test_cannot_select_or_inequality_chained_or_unknown_clause(self):
  for assertion,index in [('x>0',0),('x==1 or x==2',0),('0==x==1',0),('x==1',1)]:
   action={**self.original,'parameters':{'x':[1,2]},'derived':{},'assertion':assertion}
   source,_,_=self.q.execute_action(action,self.plan);self.q.tools+=1
   with self.subTest(assertion=assertion),self.assertRaises(ValueError):diagnose(self.q,{**self.action,'source_event':source,'equality_indices':[index]})
 def test_tolerance_does_not_mask_wrong_formula_or_failing_economic_condition(self):
  for changes in [{'derived':{**DERIVED,'gain_us':'200*d*T_s-c_us+1'}},{'assertion':'gain_us == 2000*h-c_us and h<0'}]:
   action={**self.original,**changes};source,_,_=self.q.execute_action(action,self.plan);self.q.tools+=1
   result=diagnose(self.q,{**self.action,'source_event':source})
   self.assertGreater(result['tolerant']['counterexample_count'],0)
 def test_invalid_tolerance_and_unseen_source(self):
  for tolerance in [True,0,-1,float('nan'),float('inf')]:
   with self.subTest(tolerance=tolerance),self.assertRaises(ValueError):validate_diagnosis({**self.action,'absolute_tolerance':tolerance})
  self.q.visible_source_text.pop(self.source)
  with self.assertRaises(ValueError):diagnose(self.q,self.action)

if __name__=='__main__':unittest.main()
