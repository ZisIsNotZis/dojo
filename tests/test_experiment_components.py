from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from dojo.experiments import parameter_sweep
from dojo.inquiry import Inquiry
from dojo.deterministic import revalidate_context
from tests.test_knowledge import proposal

PARAMETERS={'d':[0.2,1.0],'c_us':[100,300,600],'T_s':[0.5,1,2,3,4]}
DERIVED={'r':'T_s/10','h':'d*T_s/10','gain_us':'200*d*T_s-c_us'}
SECOND='gain_us == 200*d*T_s-c_us'
THIRD='(gain_us > 0 or h <= c_us/2000)'


class ComponentTests(unittest.TestCase):
 def test_actual_compound_failure_does_not_become_failure_of_each_component(self):
  result=parameter_sweep(PARAMETERS,DERIVED,'gain_us == 2000*h-c_us and '+SECOND+' and '+THIRD)
  self.assertEqual(2,result['counterexample_count'])
  self.assertEqual([2,0,0],[p['counterexample_count'] for p in result['component_checks']])
  first=result['component_checks'][0]
  self.assertEqual([{'d':0.2,'c_us':100,'T_s':3},{'d':0.2,'c_us':300,'T_s':3}],first['counterexample_parameters'])
  self.assertFalse(first['counterexample_parameters_truncated'])
  self.assertTrue(all(set(c)=={'index','evaluated','passed','counterexample_count','counterexample_parameters','counterexample_parameters_truncated','failed_numeric_comparisons'} for c in result['component_checks']))
 def test_failed_points_report_actual_values_even_when_two_residuals_coincide(self):
  result=parameter_sweep(PARAMETERS,DERIVED,'gain_us == 2000*h-c_us')
  rows=result['component_checks'][0]['failed_numeric_comparisons']
  self.assertEqual([100,300],[r['parameters']['c_us'] for r in rows])
  self.assertEqual([20.0,-180.0],[r['left_value'] for r in rows])
  self.assertEqual([20.00000000000003,-179.99999999999997],[r['right_value'] for r in rows])
  self.assertEqual([-2.842170943040401e-14,-2.842170943040401e-14],[r['difference'] for r in rows])
 def test_tolerance_only_on_numeric_identity_does_not_mask_an_actual_wrong_model(self):
  assertion='(gain_us-(2000*h-c_us))**2 <= 1e-24 and '+SECOND+' and '+THIRD
  result=parameter_sweep(PARAMETERS,DERIVED,assertion)
  self.assertEqual(0,result['counterexample_count'])
  wrong={**DERIVED,'gain_us':'200*d*T_s-c_us+1'}
  bad=parameter_sweep(PARAMETERS,wrong,assertion)
  self.assertEqual(30,bad['counterexample_count']);self.assertEqual(30,bad['component_checks'][0]['counterexample_count'])
 def test_or_remains_a_whole_property_and_component_witnesses_are_bounded(self):
  result=parameter_sweep({'x':[0,1]},{},'x>0 or x<=0')
  self.assertEqual(1,len(result['component_checks']));self.assertEqual(0,result['component_checks'][0]['counterexample_count'])
  result=parameter_sweep({'x':[-4,-3,-2,-1,1]},{},'x>0 and (x<10 or x==20)')
  first=result['component_checks'][0]
  self.assertEqual(4,first['counterexample_count']);self.assertEqual(2,len(first['counterexample_parameters']));self.assertTrue(first['counterexample_parameters_truncated'])
  self.assertEqual(0,result['component_checks'][1]['counterexample_count'])
 def test_component_diagnostics_preserve_valid_multiline_parenthesized_formulas(self):
  result=parameter_sweep({'x':[1,3]},{},'x > 0 and (\n x < 2\n or x == 3\n)')
  self.assertEqual(0,result['counterexample_count']);self.assertEqual([0,0],[c['counterexample_count'] for c in result['component_checks']])
 def test_legacy_replay_checks_every_old_field_without_requiring_new_diagnostics(self):
  with tempfile.TemporaryDirectory() as directory:
   q=Inquiry(Path(directory)/'db',SimpleNamespace(config=SimpleNamespace(model='deepseek-flash',api_key=None)),synthetic=True)
   try:
    user=q.record('user',{'text':'A fixed toy model of the number','synthetic':True})
    old=q.knowledge.accept(q.run,proposal('A hypothesis',user,'the number'),{user},synthetic=True)
    action={'kind':'experiment','parameters':PARAMETERS,'derived':DERIVED,'assertion':'gain_us == 2000*h-c_us','assumptions':['Fixed decimal inputs, not physical measurements'],'prediction':'Check identity'}
    result=parameter_sweep(PARAMETERS,DERIVED,action['assertion'])
    for key in ('component_checks','binary_derived_counts','assertion_scope'):result.pop(key)
    plan=q.record('reflection',{'reflection':{'answer':'Plan a check','action':action}});q.dependencies.link(plan,[old])
    event=q.record('tool_result',{'action':action,'status':'executed','result':result});q.dependencies.link(event,[plan])
    new=q.knowledge.accept(q.run,proposal('Updated hypothesis',user,'the number',revises=old),{old,user},synthetic=True)
    self.assertEqual('needs_review',q.dependencies.status(event)['state'])
    replay=revalidate_context(q)
    self.assertEqual('revalidated',replay['outcomes'][0]['status']);self.assertEqual('current_interpretation',q.dependencies.status(event)['state'])
   finally:q.close()

if __name__=='__main__':unittest.main()
