"""Dependency revisions preserve evidence and immediately disclose downstream staleness."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from dojo.dependencies import DependencyIndex
from dojo.inquiry import Inquiry


class DependencyTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        self.db.execute('CREATE TABLE inquiry_events(seq INTEGER PRIMARY KEY,run TEXT,kind TEXT,payload TEXT)')
        self.g=DependencyIndex(self.db)
        self.db.execute('INSERT INTO inquiry_events VALUES(1,?,?,?)',('r','start',json.dumps({'synthetic':False})))
        for n in range(2,15):self.db.execute('INSERT INTO inquiry_events VALUES(?,?,?,?)',(n,'r','reflection',json.dumps({'text':str(n)})))
        self.db.commit()
    def tearDown(self):self.db.close()

    def test_diamond_revision_marks_all_descendants_before_queue_drains(self):
        self.g.link(3,[2]);self.g.link(4,[2]);self.g.link(5,[3,4]);self.g.link(6,[5])
        before=list(self.db.execute('SELECT * FROM inquiry_events'))
        self.g.revise(2,7,'新证据改变解释')
        self.assertEqual('needs_review',self.g.status(6)['state'])
        self.assertEqual(1,len(self.g.drain(1)))
        self.assertEqual('needs_review',self.g.status(6)['state'])
        remaining=self.g.drain(100)
        self.assertEqual(3,len(remaining))
        self.assertEqual(4,self.db.execute('SELECT count(*) FROM inquiry_review_queue').fetchone()[0])
        self.assertEqual([],self.g.drain(100))
        self.assertEqual(before,list(self.db.execute('SELECT * FROM inquiry_events')))
        self.assertEqual('current_interpretation',self.g.status(7)['state'])
        self.g.revise(2,7,'新证据改变解释')
        with self.assertRaises(ValueError):self.g.revise(2,8,'重写历史')

    def test_multi_premise_and_late_context_are_not_silently_certified(self):
        self.g.link(5,[2,3])
        self.g.revise(3,6,'前提已更新')
        self.g.link(7,[5])
        self.assertEqual('needs_review',self.g.status(7)['state'])
        self.assertTrue(self.g.depends_on(7,3))
        self.assertEqual('not_certified',self.g.status(2)['truth'])

    def test_invalid_edges_and_replacement_cycles_leave_no_partial_mutation(self):
        with self.assertRaises(ValueError):self.g.link(5,[2,9])
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM inquiry_dependencies').fetchone()[0])
        self.g.link(3,[2]);self.g.link(4,[3])
        with self.assertRaises(ValueError):self.g.revise(2,4,'把回声当新认识')
        with self.assertRaises(ValueError):self.g.link(2,[4])
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM inquiry_revisions').fetchone()[0])

    def test_synthetic_context_cannot_change_or_support_real_inquiry(self):
        self.db.execute('INSERT INTO inquiry_events VALUES(15,?,?,?)',('sim','start',json.dumps({'synthetic':True})))
        self.db.execute('INSERT INTO inquiry_events VALUES(16,?,?,?)',('sim','reflection','{}'))
        self.db.execute('INSERT INTO inquiry_events VALUES(17,?,?,?)',('r','reflection','{}'))
        self.db.commit()
        with self.assertRaises(ValueError):self.g.link(17,[16])
        with self.assertRaises(ValueError):self.g.revise(2,16,'模拟盖过真人')


class Client:
    config=SimpleNamespace(model='deepseek-flash',api_key=None)
    def complete(self,messages):
        return dict(answer='自动化值得继续核实',understanding='自动化取决于条件',hypotheses=[],unknowns=[],revision='更新自动化判断',action=None)


class InquiryDependencyIntegrationTests(unittest.TestCase):
    def test_knowledge_interpretation_cannot_return_as_its_own_independent_context(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'db';a=Inquiry(path,Client(),synthetic=True);b=None
            try:
                a.turn('自动化值得吗');old=a.last_reflection
                b=Inquiry(path,Client(),synthetic=True)
                p={'statement':'自动化值得重新思考','kind':'decision','method':'hypothesis',
                  'premises':[{'event':old,'quote':'自动化值得继续核实','role':'assumption'}],
                  'assumptions':[],'conditions':[],'alternatives':[],'falsifier':'原解释不成立时撤回','revises':None}
                b.knowledge.accept(b.run,p,{old},synthetic=True)
                self.assertEqual([],a.retrieve_knowledge('自动化'))
            finally:
                a.close()
                if b:b.close()

    def test_revision_propagates_across_runs_and_blocks_returning_echo(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'db'
            a=Inquiry(path,Client(),synthetic=True)
            b=None
            try:
                a.turn('自动化值得吗')
                old=a.last_reflection
                b=Inquiry(path,Client(),synthetic=True)
                b.turn('自动化有什么条件')
                derived=b.last_reflection
                self.assertTrue(b.dependencies.depends_on(derived,old))
                self.assertEqual([],a.retrieve('自动化'))
                a.turn('自动化现在增加维护费用')
                self.assertEqual('superseded',a.dependencies.status(old)['state'])
                self.assertEqual('needs_review',a.dependencies.status(derived)['state'])
                hits=b.retrieve('自动化')
                self.assertNotIn(old,[h['event_seq'] for h in hits])
                self.assertIn(a.last_reflection,[h['event_seq'] for h in hits])
            finally:
                a.close()
                if b:b.close()

if __name__=='__main__':unittest.main()
