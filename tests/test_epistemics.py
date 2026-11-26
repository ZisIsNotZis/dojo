import unittest
from dojo.epistemics import validate,grounded
from dojo.live import LiveError

class EpistemicChecks(unittest.TestCase):
 def test_empty_issues_are_valid_without_claiming_truth(self):
  r=grounded({'draft':'有条件的解释'},validate('{"issues":[]}'))
  self.assertEqual([],r['issues']);self.assertEqual('model_critique_not_truth_verdict',r['epistemic_status'])
 def test_invented_quote_is_not_accepted(self):
  issue=dict(quote='从没说过的断言',kind='unsupported_fact',reason='缺依据',counterexample='假设反例',rewrite='保留未知')
  with self.assertRaises(LiveError):grounded({'draft':'实际答复'},{'issues':[issue]})
 def test_score_or_silent_schema_extension_is_rejected(self):
  for s in ('{"issues":[],"truth":true}','{"issues":{},"score":1}','{}'):
   with self.assertRaises(LiveError):validate(s)
if __name__=='__main__':unittest.main()
