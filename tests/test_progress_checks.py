import unittest

from dojo.progress_checks import check,validate_action


def model(states,edges,initial='wait',goals=None):
    return dict(kind='check_progress',states={s:'Hypothetical state '+s for s in states},initial=initial,
                goals=['advance'] if goals is None else goals,
                transitions=[dict(source=a,target=b,label='Declared possible transition') for a,b in edges],
                assumptions=['Finite transition graph only; no human timing certified.'],
                prediction='Check every maximal modeled path, not just one successful path.')


class ProgressCheckTests(unittest.TestCase):
    def assert_witness(self,action,result):
        edges={(e['source'],e['target']) for e in action['transitions']}
        witness=result['counterexample'];prefix=witness['prefix']
        self.assertEqual(action['initial'],prefix[0])
        self.assertTrue(all((a,b) in edges for a,b in zip(prefix,prefix[1:])))
        self.assertFalse(set(prefix)&set(action['goals']))
        if witness['kind']=='cycle':
            cycle=witness['cycle'];self.assertEqual(prefix[-1],cycle[0]);self.assertEqual(cycle[0],cycle[-1])
            self.assertTrue(all((a,b) in edges for a,b in zip(cycle,cycle[1:])))
            self.assertFalse(set(cycle)&set(action['goals']))
        else:self.assertFalse(any(a==prefix[-1] for a,b in edges))

    def test_specific_objection_without_exit_can_stall_even_if_progress_is_possible(self):
        action=model(['wait','advance'],[('wait','wait'),('wait','advance')])
        result=check(action)
        self.assertTrue(result['goal_reachable']);self.assertFalse(result['all_paths_reach_goal'])
        self.assertEqual('may_stall',result['status']);self.assert_witness(action,result)

    def test_reachable_deadlock_is_distinct_from_missing_a_success_path(self):
        action=model(['wait','stuck','advance'],[('wait','stuck'),('wait','advance')])
        result=check(action)
        self.assertEqual('deadlock',result['counterexample']['kind']);self.assert_witness(action,result)

    def test_three_state_cycle_certificate_uses_actual_edge_direction(self):
        action=model(['wait','x','y','advance'],[('wait','x'),('x','y'),('y','wait'),('wait','advance')])
        result=check(action);self.assert_witness(action,result)
        self.assertEqual(4,len(result['counterexample']['cycle']))

    def test_countdown_with_no_reset_produces_a_decreasing_rank(self):
        action=model(['wait','one','advance'],[('wait','one'),('wait','advance'),('one','advance')])
        result=check(action)
        self.assertTrue(result['all_paths_reach_goal']);self.assertEqual(2,result['max_transitions_to_goal'])
        for edge in action['transitions']:self.assertGreater(result['rank'][edge['source']],result['rank'][edge['target']])

    def test_new_message_reset_creates_a_cycle_and_defeats_countdown(self):
        action=model(['wait','one','advance'],[('wait','one'),('one','advance'),('one','wait')])
        result=check(action);self.assert_witness(action,result)
        self.assertEqual('cycle',result['counterexample']['kind'])

    def test_unreachable_stall_does_not_disprove_initial_progress(self):
        action=model(['wait','orphan','advance'],[('wait','advance'),('orphan','orphan')])
        result=check(action)
        self.assertTrue(result['all_paths_reach_goal']);self.assertNotIn('orphan',result['reachable_before_first_goal'])

    def test_property_stops_at_first_goal_and_does_not_certify_future_behavior(self):
        action=model(['wait','later','advance'],[('wait','advance'),('advance','later'),('later','later')])
        result=check(action)
        self.assertEqual(1,result['max_transitions_to_goal']);self.assertNotIn('later',result['reachable_before_first_goal'])
        self.assertIn('after the first goal',result['scope'])

    def test_initial_goal_needs_no_transition(self):
        result=check(model(['advance'],[],initial='advance'))
        self.assertTrue(result['all_paths_reach_goal']);self.assertEqual(0,result['max_transitions_to_goal'])

    def test_duplicate_transition_does_not_add_proof_weight(self):
        action=model(['wait','advance'],[('wait','advance')])
        first=check(action);action['transitions']*=3
        self.assertEqual(first,check(action))

    def test_unknown_states_invalid_types_and_resource_bounds_fail(self):
        original=model(['wait','advance'],[('wait','advance')])
        variants=[None,[],{**original,'extra':1},{**original,'goals':[]},{**original,'initial':'missing'},
                  {**original,'goals':['advance','advance']},{**original,'states':{'wait':False,'advance':'ok'}},
                  {**original,'transitions':[{'source':'wait','target':'missing','label':'bad'}]},
                  {**original,'transitions':original['transitions']*129},
                  {**original,'states':{str(i):'state' for i in range(33)}},
                  {**original,'assumptions':[]}]
        for value in variants:
            with self.subTest(value=value),self.assertRaises(ValueError):validate_action(value)


if __name__=='__main__':unittest.main()
