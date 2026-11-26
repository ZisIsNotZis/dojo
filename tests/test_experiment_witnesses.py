import itertools
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from dojo.experiments import parameter_sweep,expression,repair_hint
from dojo.inquiry import Inquiry


def schedule_action():
 return {'kind':'experiment','parameters':{k:[1,2,3,4] for k in ('a','b','c','d')},'derived':{},
  'assertion':'a != 2 and b != 1 and c != 1 and d != 2 and a != b and a != c and a != d and b != c and b != d and c != d',
  'assumptions':['Four explicit slots; people1/2 alternate availability and people3/4 are always available. All four must participate once.'],
  'prediction':'Expect eight schedules; the initial ten grid points are invalid, so they cannot supply a feasible plan.'}


class ExperimentWitnessTests(unittest.TestCase):
 def test_indicator_counts_encode_the_actual_failed_schedule_model_without_coercing_inputs(self):
  action=schedule_action();derived={f'n{i}':'+'.join(f'({key}=={i})' for key in ('a','b','c','d')) for i in range(1,5)}
  result=parameter_sweep(action['parameters'],derived,'a != 2 and b != 1 and c != 1 and d != 2 and n1 == 1 and n2 == 1 and n3 == 1 and n4 == 1')
  direct=parameter_sweep(action['parameters'],{},action['assertion'])
  self.assertEqual(8,result['passed']);self.assertEqual({tuple(p['parameters'].values()) for p in direct['passing_examples']},{tuple(p['parameters'].values()) for p in result['passing_examples']})
  self.assertTrue(all(p['derived']=={'n1':1,'n2':1,'n3':1,'n4':1} for p in result['passing_examples']))
  for params in ({'x':[True]},{'x':[False]}):
   with self.assertRaises(ValueError):parameter_sweep(params,{'gate':'x>0'},'gate>=0')
 def test_indicators_keep_arithmetic_bounds_and_boolean_assertion_types(self):
  self.assertEqual(2,expression('2*(3>=2)',indicators=True));self.assertEqual(0,expression('3<2',indicators=True))
  self.assertEqual(1,expression('(2>1 and 4>3)',indicators=True))
  for formula in ('True+1','__import__("os")','x[0]','2**(20+(x>0))'):
   with self.assertRaises((ValueError,SyntaxError)):expression(formula,{'x':1},indicators=True)
  with self.assertRaises(ValueError):expression('(x>0)+1',{'x':1},assertion=True,indicators=True)
  with self.assertRaises(ValueError):expression('x>0',{'x':1})
 def test_failed_comparison_receipts_show_evaluated_indicator_counts(self):
  result=parameter_sweep({'a':[1,2],'b':[1,2]},{},'(a==1)+(b==1) == 1')
  self.assertEqual((4,2,2),(result['evaluated'],result['passed'],result['counterexample_count']))
  values=result['component_checks'][0]['failed_numeric_comparisons']
  self.assertEqual([2,0],[p['left_value'] for p in values]);self.assertEqual([1,-1],[p['difference'] for p in values])
 def test_four_person_participation_count_fits_but_larger_expression_is_bounded(self):
  formula='+'.join('('+'+'.join(f'({key}=={i})' for key in ('a','b','c','d'))+'>0)' for i in range(1,5))
  self.assertEqual(3,expression(formula,{'a':3,'b':4,'c':2,'d':4},indicators=True))
  with self.assertRaisesRegex(ValueError,'复杂'):expression('+'.join(['1']*80),indicators=True)
 def test_numeric_indicator_flags_remain_usable_as_logical_conditions(self):
  result=parameter_sweep({'x':[0,1,2]},{'available':'x>1'},'available and x>=2')
  self.assertEqual(1,result['passed']);self.assertEqual({'x':2},result['passing_examples'][0]['parameters'])
  with self.assertRaises(ValueError):parameter_sweep({'x':[2]},{},'x and x>0')
  self.assertIn('8',repair_hint(ValueError('派生量过多')));self.assertIn('160',repair_hint(ValueError('表达式过复杂')))
 def test_feasible_schedules_are_reported_even_when_initial_samples_all_fail(self):
  action=schedule_action();result=parameter_sweep(action['parameters'],action['derived'],action['assertion'])
  # Independent permutation/availability oracle, not the AST interpreter.
  expected={p for p in itertools.permutations((1,2,3,4)) if p[0] in {1,3,4} and p[1] in {2,3,4} and p[2] in {2,3,4} and p[3] in {1,3,4}}
  actual={tuple(p['parameters'][key] for key in ('a','b','c','d')) for p in result['passing_examples']}
  self.assertEqual(8,len(expected));self.assertEqual(expected,actual);self.assertEqual(8,result['passed']);self.assertFalse(result['passing_examples_truncated'])
  self.assertTrue(all(not p['assertion_holds'] for p in result['sample_points']))
  self.assertFalse(any(tuple(p['parameters'][key] for key in ('a','b','c','d')) in expected for p in result['counterexamples']))
 def test_bounded_witnesses_do_not_turn_a_count_into_an_exhaustive_list(self):
  result=parameter_sweep({'x':list(range(20))},{'square':'x*x'},'x>=0')
  self.assertEqual(20,result['passed']);self.assertEqual(10,len(result['passing_examples']));self.assertTrue(result['passing_examples_truncated'])
  self.assertEqual([i*i for i in range(10)],[p['derived']['square'] for p in result['passing_examples']])
  failed=parameter_sweep({'x':[0,1]},{},'x>2');self.assertEqual([],failed['passing_examples']);self.assertFalse(failed['passing_examples_truncated'])
 def test_feasible_witness_can_be_cited_and_saved_as_a_scoped_observation(self):
  with tempfile.TemporaryDirectory() as tmp:
   q=Inquiry(Path(tmp)/'db',SimpleNamespace(config=SimpleNamespace(model='deepseek-flash',api_key=None)),synthetic=True)
   try:
    plan=q.record('reflection',{'synthetic':True,'reflection':{'answer':'Check explicit toy schedule constraints'}})
    event,receipt,_=q.execute_action(schedule_action(),plan);self.assertEqual('executed',receipt['status'])
    q.offer_front_anchors([q.knowledge.source(event)])
    entries=[a for a in q.front_anchors.entries.values() if a.get('observation_path',[None])[0]=='passing_examples']
    self.assertTrue(entries)
    anchor=entries[0];self.assertIn(anchor['quote'],q.knowledge.observed_tool_text(event))
    witness=json.loads(anchor['quote']);self.assertEqual(4,len(set(witness['parameters'].values())))
    proposal={'statement':'A feasible assignment exists in this finite toy schedule model.','kind':'descriptive','method':'deduction','premises':[{'event':event,'quote':anchor['quote'],'role':'evidence'}],'assumptions':['Only the explicitly enumerated availability and one-participation constraints.'],'conditions':['Four slots in the two-week toy model.'],'alternatives':[],'falsifier':'A listed assignment violates one of those explicit constraints.','revises':None}
    saved=q.knowledge.accept(q.run,proposal,q.visible_source_text,synthetic=True);self.assertEqual('current_interpretation',q.dependencies.status(saved)['state'])
   finally:q.close()

if __name__=='__main__':unittest.main()
