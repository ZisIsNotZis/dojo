import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from dojo.inquiry import Inquiry,validate_host
from dojo.execution import ledger
from dojo.live import LiveError
from tests.test_native_host import client,reply,tool
from tests.test_progress_checks import model


def action():
    value=model(['wait','advance'],[('wait','wait'),('wait','advance')])
    value['states']['wait']='INPUT_STATE_MEANING_SENTINEL'
    return value


class ProgressRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.q=Inquiry(Path(self.tmp.name)/'db',SimpleNamespace(config=SimpleNamespace(model='deepseek-flash',api_key=None)),synthetic=True)
        self.plan=self.q.record('reflection',{'synthetic':True,'reflection':{'answer':'Test a supplied workflow model','action':None}})

    def tearDown(self):self.q.close();self.tmp.cleanup()

    def test_native_cycle_check_roundtrip_counts_one_cpu_tool_and_no_internal_model_calls(self):
        host=client();opener=Mock();args={k:v for k,v in action().items() if k!='kind'}
        opener.open.side_effect=[reply(calls=[tool('check_progress',json.dumps(args))],finish='tool_calls'),
                                 reply('图中有可重复等待环；这不是实测人会卡住。')]
        q=Inquiry(Path(self.tmp.name)/'native',host,synthetic=True,request_budget=2,tool_budget=1)
        try:
            with patch('dojo.live.urllib.request.build_opener',return_value=opener):answer=q.turn('检查这个流程')
            self.assertIn('等待环',answer);self.assertEqual((0,0),(q.requests,q.tools))
            payload=json.loads(q.db.execute("SELECT payload FROM inquiry_events WHERE kind='tool_result'").fetchone()[0])
            self.assertEqual('executed',payload['status']);self.assertFalse(payload['result']['all_paths_reach_goal'])
            self.assertTrue(payload['result']['goal_reachable'])
            self.assertEqual(1,ledger(q)['story_counts']['check_progress']['executed'])
        finally:q.close()

    def test_budget_denial_does_not_run_graph_analysis(self):
        self.q.tools=0
        with patch('dojo.progress_checks.check',side_effect=AssertionError('must not execute')):
            _,result,_=self.q.execute_action(action(),self.plan)
        self.assertEqual('not_executed',result['status'])

    def test_unknown_transition_state_fails_before_native_execution(self):
        invalid=action();invalid['transitions'][0]['target']='missing'
        with self.assertRaises(LiveError):validate_host(json.dumps({'answer':'Check','action':invalid}))
        self.assertEqual(0,self.q.db.execute("SELECT count(*) FROM inquiry_events WHERE kind='tool_started'").fetchone()[0])

    def test_declared_state_meaning_is_not_computed_observation_evidence(self):
        event,_,_=self.q.execute_action(action(),self.plan)
        self.assertNotIn('INPUT_STATE_MEANING_SENTINEL',self.q.knowledge.observed_tool_text(event))
        proposal=dict(statement='The supplied graph permits an infinite non-goal path.',kind='decision',method='deduction',
                      premises=[{'event':event,'quote':'"all_paths_reach_goal": false','role':'evidence'}],
                      assumptions=['Only the supplied transitions are checked.'],conditions=['Not a human timing result.'],
                      alternatives=['Replace the loop with a bounded countdown.'],falsifier='Changed transitions remove the loop.',revises=None)
        self.assertIsInstance(self.q.knowledge.accept(self.q.run,proposal,{event},synthetic=True),int)
        invalid=copy.deepcopy(proposal);invalid['premises'][0]['quote']='INPUT_STATE_MEANING_SENTINEL'
        with self.assertRaisesRegex(ValueError,'not an observation'):self.q.knowledge.check(invalid,{event},synthetic=True)

    def test_plan_revision_leaves_fixed_graph_computation_current(self):
        event,_,_=self.q.execute_action(action(),self.plan)
        later=self.q.record('reflection',{'synthetic':True,'reflection':{'answer':'New narrative','action':None}})
        self.q.dependencies.revise(self.plan,later,'Narrative changed, fixed graph did not')
        self.assertEqual('current_interpretation',self.q.dependencies.status(event)['state'])

    def test_success_exposes_step_rank_without_asserting_wall_time(self):
        value=model(['wait','advance'],[('wait','advance')])
        _,result,_=self.q.execute_action(value,self.plan)
        self.assertEqual(1,result['result']['max_transitions_to_goal'])
        self.assertEqual({'advance':0,'wait':1},result['result']['rank'])
        self.assertIn('wall-time',result['result']['scope'])


if __name__=='__main__':unittest.main()
