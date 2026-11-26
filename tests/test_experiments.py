import unittest
from dojo.experiments import parameter_sweep,expression,repair_hint

class ExperimentTests(unittest.TestCase):
 def test_binary_totals_are_separate_from_impossible_point_count_assertions(self):
  r=parameter_sweep({'mode':[0,1,2],'bf':[0,1]},
   {'one':'mode==1','two':'mode==2'},'one==2 and two==2')
  self.assertEqual(0,r['passed'])
  self.assertEqual({'one':{'zero':4,'one':2},'two':{'zero':4,'one':2}},r['binary_derived_counts'])
  self.assertIn('separately at each parameter point',r['assertion_scope'])
  self.assertIn('not expression variables',r['assertion_scope'])
 def test_binary_totals_cover_unsampled_points_and_do_not_publish_partial_nonbinary_counts(self):
  r=parameter_sweep({'x':list(range(20))},
   {'late':'x>=10','constant':'0','not_binary':'x/19*2'},'late==1')
  self.assertEqual(10,len(r['sample_points']))
  self.assertTrue(all(p['derived']['late']==0 for p in r['sample_points']))
  self.assertEqual({'zero':10,'one':10},r['binary_derived_counts']['late'])
  self.assertEqual({'zero':20,'one':0},r['binary_derived_counts']['constant'])
  self.assertNotIn('not_binary',r['binary_derived_counts'])
  self.assertEqual({},parameter_sweep({'x':[0,1,2]},{'mixed':'x'},'x>=0')['binary_derived_counts'])
 def test_finite_sweep_finds_actual_counterexamples(self):
  r=parameter_sweep({'n':[1,6,13],'setup':[0,100]},{'net':'n*8-setup'},'net>0')
  self.assertEqual((6,4,2),(r['evaluated'],r['passed'],r['counterexample_count']))
  self.assertEqual([-92,104],r['derived_ranges']['net'])
  self.assertEqual({'n':6,'setup':100},r['counterexamples'][1]['parameters'])
  self.assertIn('参数域',r['scope'])
 def test_boundary_is_not_positive_and_scoped_success_is_not_universal(self):
  self.assertEqual(1,parameter_sweep({'setup':[48]},{'net':'6*8-setup'},'net>0')['counterexample_count'])
  r=parameter_sweep({'n':[13,20]},{'net':'n*8-100'},'net>0')
  self.assertEqual(0,r['counterexample_count']);self.assertEqual({'n':[13,20]},r['domain'])
 def test_model_cannot_execute_code_or_unbounded_grid(self):
  for text in ('__import__("os")','x.__class__','[1]*5','2**10000000'):
   with self.assertRaises((ValueError,SyntaxError)):expression(text,{'x':1})
  for p in ({'x':[1]*20},{'x':[True]},{'x':[float('nan')]},{'x':[1e16]},{'x':list(range(20)),'y':list(range(20)),'z':list(range(20)),'w':list(range(20))}):
   with self.assertRaises(ValueError):parameter_sweep(p,{},'x>0')
 def test_unknown_inputs_and_invalid_assertions_do_not_turn_into_results(self):
  with self.assertRaises(ValueError):parameter_sweep({'x':[1]},{'y':'missing+1'},'y>0')
  with self.assertRaises(ZeroDivisionError):parameter_sweep({'x':[0]},{'y':'1/x'},'y>0')
  with self.assertRaises(ValueError):parameter_sweep({'x':[1]},{},'x+1')
 def test_binomial_tail_has_actual_parameter_values_not_just_a_range(self):
  r=parameter_sweep({'p':[0.1,0.2,0.3,0.4,0.5]},{'tail':'1-((1-p)**10+10*(1-p)**9*p+45*(1-p)**8*p*p)'},'tail>=0 and tail<=1')
  self.assertEqual(5,len(r['sample_points']));self.assertFalse(r['sample_points_truncated'])
  for sample,expected in zip(r['sample_points'],(0.0701908264,0.3222004736,0.6172172136,0.8327102464,0.9453125)):
   self.assertAlmostEqual(expected,sample['derived']['tail'],places=10)
   self.assertTrue(sample['assertion_holds'])
 def test_sample_cap_is_explicit_and_failed_forms_get_safe_repair_help(self):
  r=parameter_sweep({'x':list(range(20))},{'y':'x*2'},'y<10')
  self.assertEqual(10,len(r['sample_points']));self.assertTrue(r['sample_points_truncated'])
  self.assertEqual(15,r['counterexample_count'])
  for error in (SyntaxError('PRIVATE_EXCEPTION_SENTINEL'),ValueError('PRIVATE_EXCEPTION_SENTINEL')):
   hint=repair_hint(error);self.assertIn('**',hint);self.assertNotIn('PRIVATE_EXCEPTION_SENTINEL',hint)
  with self.assertRaises(ValueError):expression('2^3')
if __name__=='__main__':unittest.main()
