from fractions import Fraction
import itertools
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from dojo.design_checks import check,validate_action
from dojo.inquiry import Inquiry,validate_host
from dojo.knowledge import tool_observation_text
from dojo.research import validate as validate_research


def action(rows,contrast,terms=None):
 return {'kind':'check_design','terms':terms or ['x'+str(i) for i in range(len(contrast))],
  'rows':rows,'contrast':contrast,'assumptions':['Specified exact linear model only; no observed human outcomes.'],
  'prediction':'Check whether distinct coefficients can predict the same observations.'}


class DesignChecksTests(unittest.TestCase):
 def certificate(self,a,r):
  x=[[Fraction(str(v)) for v in row] for row in a['rows']];c=[Fraction(str(v)) for v in a['contrast']]
  if not r['identifiable']:
   shift=list(map(Fraction,r['coefficient_shift']))
   self.assertEqual([0]*len(x),[sum(v*b for v,b in zip(row,shift)) for row in x])
   self.assertEqual(1,sum(v*b for v,b in zip(c,shift)))
  else:
   weights=list(map(Fraction,r['observation_weights']))
   self.assertEqual(c,[sum(w*row[j] for w,row in zip(weights,x)) for j in range(len(c))])
 def test_same_pot_timing_and_second_prompt_have_exactly_same_predictions(self):
  a=action([[1,0,0],[1,1,1]],[0,1,0],['baseline','after','second_prompt'])
  result=check(a);self.assertFalse(result['identifiable']);self.assertEqual(2,result['rank'])
  self.certificate(a,result)
 def test_target_can_be_identified_without_identifying_every_nuisance(self):
  a=action([[1,0,0],[1,1,0]],[0,1,0]);r=check(a)
  self.assertTrue(r['identifiable']);self.assertLess(r['rank'],3);self.certificate(a,r)
  a['contrast']=[0,0,1];r=check(a);self.assertFalse(r['identifiable']);self.certificate(a,r)
 def test_independent_units_are_a_model_assumption_not_an_automatic_fix(self):
  # With a distinct uncontrolled intercept per episode, a timing effect can
  # still be traded for episode differences. Independence was not measured.
  a=action([[1,0,0],[0,1,1]],[0,0,1],['episode_a','episode_b','after'])
  r=check(a);self.assertFalse(r['identifiable']);self.certificate(a,r)
 def test_decimal_entries_use_exact_rationals(self):
  a=action([[1,0],[1,0.1]],[0,1]);r=check(a)
  self.assertEqual(['-10','10'],r['observation_weights']);self.certificate(a,r)
 def test_all_binary_two_by_two_designs_against_independent_determinant_oracle(self):
  for values in itertools.product((0,1),repeat=4):
   x=[list(values[:2]),list(values[2:])];a,b,c,d=values
   for contrast in ([1,0],[0,1],[1,1]):
    # In two dimensions full rank uses a nonzero determinant. Rank one
    # identifies exactly the multiples of any nonzero design row.
    row=next((r for r in x if any(r)),None)
    expected=bool(a*d-b*c) or bool(row and row[0]*contrast[1]==row[1]*contrast[0])
    model=action(x,list(contrast));r=check(model)
    self.assertEqual(expected,r['identifiable'],(x,contrast));self.certificate(model,r)
 def test_malformed_or_unbounded_input_is_rejected_before_arithmetic(self):
  for patch in ({'rows':[[1]]},{'rows':[]},{'contrast':[0,0]},{'contrast':[1,True]},
    {'contrast':[1,float('nan')]},{'contrast':[1,10**1000]}, {'rows':[[1,True]]},
    {'rows':[[1,float('nan')]]},{'rows':[[1,float('inf')]]},{'rows':[[1,10**1000]]},
    {'rows':[[1,0.0000001]]},{'terms':['x','x']},{'terms':['x']*9},{'rows':[[1,0]]*33}):
   with self.subTest(patch=patch),self.assertRaises(ValueError):validate_action({**action([[1,0]],[0,1]),**patch})
 def test_runtime_research_and_observation_contract_keep_input_out_of_evidence(self):
  a=action([[1,0,0],[1,1,1]],[0,1,0]);a['assumptions']=['INPUT_ONLY_SECRET_ASSUMPTION']
  validated=validate_host(json.dumps({'answer':'Plan','action':a}))
  self.assertEqual(a,validated['action'])
  self.assertEqual(a,validate_research(json.dumps({'question':1,'target':None,'reason':'Compare models','action':a}))['action'])
  with tempfile.TemporaryDirectory() as tmp:
   host=SimpleNamespace(config=SimpleNamespace(model='deepseek-flash',api_key=None))
   q=Inquiry(Path(tmp)/'db',host,synthetic=True,request_budget=1,tool_budget=1)
   try:
    plan=q.record('reflection',{'reflection':{'answer':'Controller plan','action':a}})
    event,receipt,_=q.execute_action(a,plan)
    self.assertEqual('executed',receipt['status']);self.assertEqual(0,q.tools);self.assertEqual(1,q.requests)
    self.assertNotIn('INPUT_ONLY',tool_observation_text(receipt))
    from dojo.anchors import anchor_catalog
    anchors=anchor_catalog(q.knowledge,[q.knowledge.source(event)])
    self.assertEqual([],anchors[0]['observation_path'])
    self.assertIn('"identifiable": false',anchors[0]['quote'])
    self.assertIn('coefficient_shift',anchors[0]['quote'])
    self.assertNotIn('INPUT_ONLY',anchors[0]['quote'])
    self.assertEqual('execution_context',q.db.execute('SELECT relation FROM inquiry_dependencies WHERE conclusion=? AND premise=?',(event,plan)).fetchone()[0])
    self.certificate(a,receipt['result'])
   finally:q.close()

if __name__=='__main__':unittest.main()
