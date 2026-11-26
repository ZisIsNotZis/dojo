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


def action():
    return dict(kind='check_entailment',variables={'A':'INPUT_MEANING_SENTINEL','B':'A different latent property'},
                premises=['A'],conclusion='A and B',assumptions=['These are hypothetical Boolean propositions.'],
                prediction='A alone does not decide B; expect two premise models with different conclusions.')


class EntailmentRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.q=Inquiry(Path(self.tmp.name)/'db',SimpleNamespace(config=SimpleNamespace(model='deepseek-flash',api_key=None)),synthetic=True)
        self.plan=self.q.record('reflection',{'synthetic':True,'reflection':{'answer':'Check a supplied formalization','action':None}})

    def tearDown(self):self.q.close();self.tmp.cleanup()

    def test_native_function_roundtrip_shares_budget_and_returns_computed_witness(self):
        host=client();opener=Mock()
        args={k:v for k,v in action().items() if k!='kind'}
        opener.open.side_effect=[reply(calls=[tool('check_entailment',json.dumps(args))],finish='tool_calls'),
                                 reply('给定公式有反模型；这是假设赋值，不是实际人物。')]
        q=Inquiry(Path(self.tmp.name)/'native-db',host,synthetic=True,request_budget=2,tool_budget=1)
        try:
            with patch('dojo.live.urllib.request.build_opener',return_value=opener):answer=q.turn('检查这个逻辑关系')
            self.assertIn('假设赋值',answer)
            self.assertEqual((0,0),(q.requests,q.tools))
            payload=json.loads(q.db.execute("SELECT payload FROM inquiry_events WHERE kind='tool_result'").fetchone()[0])
            self.assertEqual('executed',payload['status'])
            self.assertEqual('underdetermined',payload['result']['status'])
            self.assertEqual([{'A':1,'B':0}],payload['result']['countermodels'])
            self.assertIn('countermodels',json.dumps(opener.open.call_args.args[0].data.decode()))
        finally:q.close()

    def test_no_tool_budget_never_runs_the_checker(self):
        self.q.tools=0
        with patch('dojo.entailment.check',side_effect=AssertionError('must not execute')):
            _,result,_=self.q.execute_action(action(),self.plan)
        self.assertEqual('not_executed',result['status'])

    def test_invalid_full_formula_is_rejected_before_native_execution(self):
        value=action();value['conclusion']='0 and hidden()'
        with self.assertRaises(LiveError):validate_host(json.dumps({'answer':'Check','action':value}))
        self.assertEqual(0,self.q.db.execute("SELECT count(*) FROM inquiry_events WHERE kind='tool_started'").fetchone()[0])

    def test_input_meanings_cannot_be_laundered_as_observation_evidence(self):
        event,result,_=self.q.execute_action(action(),self.plan)
        self.assertNotIn('INPUT_MEANING_SENTINEL',self.q.knowledge.observed_tool_text(event))
        proposal=dict(statement='The supplied formulas leave B undetermined.',kind='decision',method='deduction',
                      premises=[{'event':event,'quote':'"countermodel_count": 1','role':'evidence'}],
                      assumptions=['Only these formulas are checked.'],conditions=['Boolean meanings remain assumptions.'],
                      alternatives=['Add a justified bridge premise.'],falsifier='A changed formalization removes the countermodel.',revises=None)
        accepted=self.q.knowledge.accept(self.q.run,proposal,{event},synthetic=True)
        self.assertIsInstance(accepted,int)
        invalid=copy.deepcopy(proposal);invalid['premises'][0]['quote']='INPUT_MEANING_SENTINEL'
        with self.assertRaisesRegex(ValueError,'not an observation'):self.q.knowledge.check(invalid,{event},synthetic=True)

    def test_changed_planning_narrative_does_not_invalidate_fixed_formula_result(self):
        event,_,_=self.q.execute_action(action(),self.plan)
        later=self.q.record('reflection',{'synthetic':True,'reflection':{'answer':'New planning interpretation','action':None}})
        self.q.dependencies.revise(self.plan,later,'Changed interpretation, not the fixed formulas')
        self.assertEqual('current_interpretation',self.q.dependencies.status(event)['state'])

    def test_executed_inconsistent_check_does_not_mean_a_claim_is_proved(self):
        value=action();value['premises']=['A','not A']
        _,result,_=self.q.execute_action(value,self.plan)
        self.assertEqual('executed',result['status'])
        self.assertEqual('inconsistent_premises',result['result']['status'])
        self.assertIsNone(result['result']['entails_conclusion'])
        self.assertEqual(1,ledger(self.q)['story_counts']['check_entailment']['executed'])


if __name__=='__main__':unittest.main()
