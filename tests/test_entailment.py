import unittest

from dojo.entailment import check


class EntailmentTests(unittest.TestCase):
    def test_report_and_indecision_do_not_determine_unstated_mental_process(self):
        result=check({'sent':'A counterexample was sent','undecided':'Indecision was reported',
                      'independent':'Independent thinking occurred','knows':'Knows exactly where stuck'},
                     ['sent','undecided'],'independent and knows')
        self.assertEqual('underdetermined',result['status'])
        self.assertEqual((16,4,1,3),(result['total_assignments'],result['premise_model_count'],result['supporting_model_count'],result['countermodel_count']))
        self.assertTrue(all(a['sent']==a['undecided']==1 for a in result['countermodels']))
        self.assertTrue(any(a['independent']==0 for a in result['countermodels']))

    def test_explicit_bridge_changes_the_formal_result_not_its_empirical_truth(self):
        variables={'sent':'Report','independent':'Independent reasoning'}
        self.assertFalse(check(variables,['sent'],'independent')['entails_conclusion'])
        result=check(variables,['sent','not sent or independent'],'independent')
        self.assertTrue(result['entails_conclusion'])
        self.assertEqual([{'independent':1,'sent':1}],result['supporting_examples'])
        self.assertIn('premise truth',result['scope'])

    def test_multiple_premises_support_a_chain_without_claiming_reality(self):
        result=check({'A':'First condition','B':'Second condition','C':'Third condition'},
                     ['A','not A or B','not B or C'],'C')
        self.assertEqual('entailed',result['status'])
        self.assertEqual((1,0),(result['supporting_model_count'],result['countermodel_count']))

    def test_inconsistent_premises_are_not_presented_as_usable_proof(self):
        result=check({'A':'A','B':'B'},['A','not A'],'B')
        self.assertEqual('inconsistent_premises',result['status'])
        self.assertEqual(0,result['premise_model_count'])
        self.assertIsNone(result['entails_conclusion'])
        self.assertIsNone(result['entails_negation'])

    def test_refuted_is_distinct_from_underdetermined(self):
        result=check({'A':'A'},['not A'],'A')
        self.assertEqual('refuted',result['status'])
        self.assertTrue(result['entails_negation'])
        self.assertEqual([{'A':0}],result['countermodels'])

    def test_constants_and_nested_negation_use_complete_boolean_semantics(self):
        self.assertEqual('entailed',check({},['True'],'not False')['status'])
        self.assertEqual('entailed',check({'A':'A'},[],'A or not A')['status'])
        self.assertEqual('entailed',check({'A':'A'},['not not A'],'A == True')['status'])
        self.assertEqual('refuted',check({'A':'A'},[],'A != A')['status'])

    def test_counts_cover_full_domain_while_witness_display_is_bounded(self):
        result=check({chr(65+i):'A hypothetical bit' for i in range(8)},[],'A')
        self.assertEqual((256,128,128),(result['total_assignments'],result['supporting_model_count'],result['countermodel_count']))
        self.assertEqual((3,3),(len(result['supporting_examples']),len(result['countermodels'])))
        self.assertTrue(result['countermodels_truncated'])
        self.assertTrue(result['supporting_examples_truncated'])

    def test_unused_or_repeated_premises_do_not_add_logical_evidence(self):
        first=check({'A':'A','B':'B'},['A'],'B')
        self.assertEqual(first,check({'B':'B','A':'A'},['A','A'],'B'))
        extended=check({'A':'A','B':'B','C':'Unused'},['A'],'B')
        self.assertEqual(first['premise_model_count']*2,extended['premise_model_count'])
        self.assertEqual(first['status'],extended['status'])

    def test_unsafe_and_undeclared_hidden_branches_are_rejected_before_enumeration(self):
        for bad in ('0 and dangerous()','0 == 1 == missing','A.__class__','A[0]','A+A == 1',"0 and 'text'",'2','A < 1'):
            with self.subTest(formula=bad),self.assertRaises(ValueError):check({'A':'A'},[],bad)

    def test_resource_and_input_bounds_fail_explicitly(self):
        for variables,premises,conclusion in [({str(i):'meaning' for i in range(9)},[],'1'),
                                             ({'True':'Reserved'},[],'True'),
                                             ({'A':False},[],'A'),
                                             ({'A':'A'},['A']*13,'A'),
                                             ({'A':'A'},[],'A'*161),
                                             ({'A':'A'},[],''),
                                             ({'A':'A'},[],None)]:
            with self.subTest(variables=variables,conclusion=conclusion),self.assertRaises(ValueError):check(variables,premises,conclusion)


if __name__=='__main__':unittest.main()
