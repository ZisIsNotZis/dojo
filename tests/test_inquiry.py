import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from dojo.inquiry import Inquiry, calculate, validate, config_from_pi
from dojo.live import LiveError


def reflection(answer='结论',action=None):
    return dict(answer=answer,understanding='模型对用户目标的解释',hypotheses=['固定成本可能抵消节省'],unknowns=['现实输入未测量'],revision='保留未知',action=action)


class FakeClient:
    config=SimpleNamespace(model='deepseek-flash',api_key='SECRET_SENTINEL')
    def __init__(self, values): self.values=iter(values); self.seen=[]
    def complete(self,messages):
        self.seen.append(json.loads(json.dumps(messages)))
        value=next(self.values)
        if isinstance(value,Exception): raise value
        return value


class InquiryTests(unittest.TestCase):
    def test_resume_distinguishes_public_log_date_from_plan_and_receipt_time(self):
        from email.message import Message
        from io import BytesIO
        from dojo.sources import read_source

        url = 'https://example.org/east-door-log'
        plan = '值班表写 2026-11-23 周一东门 06:10 开门。'
        target = '2026-11-23'
        query = dict(kind='search', query='东门开门事件日志 2026-11-23', prediction='找实际事件日志，不找计划表')
        read = dict(kind='read_source', url=url, prediction='核对原文日期和开门事件')

        for date, expected in [(target, '记录显示当日 06:14；不再重查该日'),
                               ('2026-11-16', '目标日仍未知；查 2026-11-23 门禁日志')]:
            with self.subTest(date=date), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'story.sqlite3'
                original = Inquiry(path, FakeClient([reflection('下一步查周一东门门禁日志，不是计划表')]), synthetic=True)
                try:
                    original.turn(plan)
                    story = original.story
                finally:
                    original.close()

                observed = f'{date} 周一 东门 实际开门 06:14'
                fetched = []

                def open_fixture(request, *, timeout):
                    fetched.append(request.full_url)
                    body = BytesIO(observed.encode('utf-8'))
                    body.headers = Message()
                    body.headers['Content-Type'] = 'text/plain; charset=utf-8'
                    return body

                def public_source(source_url):
                    return read_source(source_url, opener=SimpleNamespace(open=open_fixture),
                                       resolver=lambda *a, **kw: [(None, None, None, '', ('93.184.216.34', 443))])

                external = Inquiry(path, FakeClient([reflection(action=query), reflection(action=read),
                                                      reflection('已读取来源，请核对原始日期。')]),
                                   story=story, synthetic=True, source_fn=public_source,
                                   search_fn=lambda *a, **kw: [{'url': url, 'title': '东门日志', 'snippet': '周一实际开门 06:14（日期见正文）'}])
                try:
                    external.turn('请查来源，确认是哪一个周一。')
                    self.assertEqual([url], fetched)
                finally:
                    external.close()

                import subprocess
                import sys

                result = subprocess.run([sys.executable, '-m', 'dojo', '--db', str(path),
                                         'stories', story, '--synthetic', '--context'],
                                        capture_output=True, encoding='utf-8', timeout=15, check=True)
                context = json.loads(result.stdout)
                (screen_source, screen_receipt), = [(s, json.loads(s['text'])) for s in context['sources']
                    if s['kind'] == 'tool_result' and json.loads(s['text'])['action']['kind'] == 'read_source']
                self.assertEqual(observed, screen_receipt['result']['text'])
                self.assertEqual('recorded', screen_source['recorded_at_status'])
                self.assertIn('不是原文中的外部时刻', context['reading'])

                # Decide from the real next-request payload, not prior prose, a
                # SQLite query, the writer's current clock, or the fixture branch.
                testcase = self

                class Reader(FakeClient):
                    def complete(self, messages):
                        packet, = [json.loads(m['content'].split('\n', 1)[1]) for m in messages
                                   if m['content'].startswith('系统恢复同一故事的历史')]
                        reports = [s for s in packet['sources'] if s['kind'] == 'user']
                        testcase.assertTrue(any(s['text'] == plan and s['attribution'] == 'reported_in_current_story' for s in reports))
                        reads = [(s, json.loads(s['text'])) for s in packet['sources'] if s['kind'] == 'tool_result']
                        source, receipt = [(s, r) for s, r in reads if r['action']['kind'] == 'read_source'][0]
                        testcase.assertEqual(story, source['origin_story'])
                        testcase.assertEqual('executed', receipt['status'])
                        testcase.assertEqual(url, receipt['result']['url'])
                        testcase.assertEqual(observed, receipt['result']['text'])
                        testcase.assertIn('不代表独立复现', receipt['result']['scope'])
                        testcase.assertIn('at', source)
                        answer = ('记录显示当日 06:14；不再重查该日' if receipt['result']['text'].startswith(target + ' ')
                                  else '目标日仍未知；查 2026-11-23 门禁日志')
                        return reflection(answer)

                resumed = Inquiry(path, Reader([]), story=story, synthetic=True)
                try:
                    self.assertIn(expected, resumed.turn('恢复后下一步怎么查？'))
                    self.assertEqual([url], fetched)
                finally:
                    resumed.close()

    def test_arithmetic_rejects_code_and_unbounded_work(self):
        self.assertEqual(12.5,calculate('100 / (10 - 2)'))
        self.assertEqual(0,calculate('6*(10-2)-48'))
        for bad in ('__import__("os")','(1).__class__','2**1000000','True','1/0','1e309','[1]*100'):
            with self.assertRaises((ValueError,ZeroDivisionError)): calculate(bad)

    def test_tool_result_reaches_revision_and_later_inquiry(self):
        action=dict(kind='calculate',expression='100/(10-2)',basis='合成假设：设置100分钟，每次净省8分钟',prediction='超过12次才回本')
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'db.sqlite3'
            c=FakeClient([reflection(action=action),reflection('自动化回本阈值为12.5次，不证明现实收益')])
            q=Inquiry(p,c,synthetic=True)
            try:
                self.assertIn('12.5',q.turn('自动化值得吗'))
                self.assertIn('12.5',c.seen[-1][-1]['content'])
                events=[json.loads(x[0]) for x in q.db.execute("SELECT payload FROM inquiry_events WHERE kind='tool_result'")]
                self.assertEqual('executed',events[0]['status'])
            finally:q.close()
            q=Inquiry(p,FakeClient([reflection()]),synthetic=True)
            try:
                matches=q.retrieve('自动化回本')
                self.assertEqual(1,len(matches))
                self.assertEqual(12.5,matches[0]['tool_receipts'][0]['result']['value'])
                self.assertTrue(matches[0]['user_statements'])
            finally:q.close()
            q=Inquiry(p,FakeClient([reflection()]),synthetic=False)
            try:self.assertEqual([],q.retrieve('自动化回本'))
            finally:q.close()

    def test_failure_is_not_a_pass_and_credentials_are_not_logged(self):
        with tempfile.TemporaryDirectory() as d:
            q=Inquiry(Path(d)/'db',FakeClient([LiveError('SECRET_SENTINEL',kind='connect')]))
            try:
                with self.assertRaises(LiveError):q.turn('想法')
                log=str(list(q.db.execute('SELECT payload FROM inquiry_events')))
                self.assertNotIn('SECRET_SENTINEL',log)
                self.assertNotIn('tool_result',log)
                self.assertEqual(11,q.requests)
            finally:q.close()

    def test_expression_failure_hint_reaches_repair_and_actual_sample_receipt(self):
        bad=dict(kind='calculate',expression='for p in [0.1]: print(p)',basis='合成模型',prediction='未验证')
        fixed=dict(kind='experiment',parameters={'p':[0.1,0.2,0.3]},derived={'tail':'1-((1-p)**10+10*(1-p)**9*p+45*(1-p)**8*p*p)'},assertion='tail>=0 and tail<=1',assumptions=['n=10独立同分布的模型'],prediction='预期尾概率随p上升')
        c=FakeClient([reflection(action=bad),reflection(action=fixed),reflection('实际参数点已算出，只是给定模型')])
        with tempfile.TemporaryDirectory() as d:
            q=Inquiry(Path(d)/'db',c,synthetic=True)
            try:
                q.turn('检查阈值')
                self.assertIn('repair_hint',c.seen[1][-1]['content']);self.assertIn('**',c.seen[1][-1]['content'])
                rows=[json.loads(r[0]) for r in q.db.execute("SELECT payload FROM inquiry_events WHERE kind='tool_result' ORDER BY seq")]
                self.assertEqual(['failed','executed'],[r['status'] for r in rows])
                self.assertAlmostEqual(0.3222004736,rows[1]['result']['sample_points'][1]['derived']['tail'],places=10)
                self.assertIn('sample_points',c.seen[2][-1]['content']);self.assertEqual(9,q.requests)
            finally:q.close()

    def test_no_tool_execution_without_synthesis_budget(self):
        with tempfile.TemporaryDirectory() as d:
            q=Inquiry(Path(d)/'db',FakeClient([reflection(action=dict(kind='calculate',expression='1+1',basis='假设',prediction='2'))]),request_budget=1)
            try:
                self.assertIn('未执行',q.turn('算一下'))
                self.assertEqual(0,q.db.execute("SELECT count(*) FROM inquiry_events WHERE kind='tool_started'").fetchone()[0])
            finally:q.close()

    def test_search_failure_is_fed_back_without_becoming_evidence(self):
        from dojo.search import SearchError
        def fail(*a,**k):raise SearchError('http_404','不支持')
        with tempfile.TemporaryDirectory() as d:
            c=FakeClient([reflection(action=dict(kind='search',query='理论',prediction='检查机制')),reflection('检索失败，尚不能核实')])
            q=Inquiry(Path(d)/'db',c,search_fn=fail)
            try:
                self.assertIn('失败',q.turn('搜理论'))
                self.assertIn('"status": "failed"',c.seen[-1][-1]['content'])
            finally:q.close()

    def test_pi_config_and_strict_schema(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d); (p/'auth.json').write_text(json.dumps({'deepseek':{'key':'SECRET'}}))
            c=config_from_pi(p)
            self.assertEqual('deepseek-flash',c.model)
            self.assertEqual('https://api.deepseek.com/v1/chat/completions',c.endpoint)
        validate(json.dumps(reflection()))
        for bad in ('{}','{"answer":"a","answer":"b"}',json.dumps(reflection(action={'kind':'shell','command':'dir'}))):
            with self.assertRaises(LiveError):validate(bad)

    def test_delivered_answer_carries_actual_search_sources(self):
        def found(*a,**k):
            return [{'title':'外部材料','url':'https://example.org/paper','content':'待核实摘要'}]
        with tempfile.TemporaryDirectory() as d:
            c=FakeClient([reflection(action=dict(kind='search',query='机制',prediction='查证')),reflection('仍待验证')])
            q=Inquiry(Path(d)/'db',c,search_fn=found)
            try:
                self.assertIn('https://example.org/paper',q.turn('找依据'))
                self.assertEqual(1,q.db.execute("SELECT count(*) FROM inquiry_events WHERE kind='delivered'").fetchone()[0])
            finally:q.close()

    def test_user_intent_cannot_cite_a_model_or_nonexistent_event(self):
        with tempfile.TemporaryDirectory() as d:
            value=reflection()
            value['intent']={'goals':[{'text':'目标','source_event':999,'quote':'想做公共平台'}],
                'motivations':[],'inferred_needs':[],'unresolved':[]}
            validate(json.dumps(value))
            q=Inquiry(Path(d)/'db',FakeClient([value]))
            try:
                with self.assertRaises(LiveError) as caught:q.turn('想做公共平台')
                self.assertEqual('intent_source_mismatch',caught.exception.kind)
                self.assertEqual(0,q.db.execute("SELECT count(*) FROM inquiry_events WHERE kind='reflection'").fetchone()[0])
            finally:q.close()

    def test_intent_retains_distinct_goals_and_motivations_with_real_quotes(self):
        with tempfile.TemporaryDirectory() as d:
            value=reflection()
            # start event is 1, first user's event is 2 in a fresh database.
            value['intent']={'goals':[{'text':'公共知识平台','source_event':2,'quote':'做公共平台'}],
                'motivations':[{'text':'减少重复解释','source_event':2,'quote':'重复解释很累'}],
                'inferred_needs':['可能需要跨会话上下文'],'unresolved':['还需辨别面向谁']}
            q=Inquiry(Path(d)/'db',FakeClient([value]))
            try:
                q.turn('我想做公共平台，重复解释很累')
                payload=json.loads(q.db.execute("SELECT payload FROM inquiry_events WHERE kind='reflection'").fetchone()[0])
                self.assertEqual(2,payload['reflection']['intent']['goals'][0]['source_event'])
            finally:q.close()

    def test_search_then_read_source_then_synthesis_has_real_dependency_chain(self):
        def found(*a,**k):return [{'title':'论文','url':'https://example.org/paper#section','content':'索引摘要'}]
        def fetched(url):return {'url':url,'text':'实际正文：结果只在特定任务下成立','truncated':False}
        with tempfile.TemporaryDirectory() as d:
            c=FakeClient([
                reflection(action=dict(kind='search',query='机制研究',prediction='查找原始研究')),
                reflection(action=dict(kind='read_source',url='https://example.org/paper',prediction='核查任务边界')),
                reflection('只有特定任务观察，不支持普遍保证')])
            q=Inquiry(Path(d)/'db',c,search_fn=found,source_fn=fetched)
            try:
                answer=q.turn('这个效果普遍成立吗')
                self.assertIn('https://example.org/paper',answer)
                self.assertIn('实际正文',c.seen[-1][-1]['content'])
                tools=[r[0] for r in q.db.execute("SELECT seq FROM inquiry_events WHERE kind='tool_result'")]
                for tool in tools:self.assertTrue(q.dependencies.depends_on(q.last_reflection,tool))
            finally:q.close()

    def test_source_not_returned_by_search_is_not_fetched(self):
        def forbidden(url):raise AssertionError('must not read invented sources')
        with tempfile.TemporaryDirectory() as d:
            c=FakeClient([reflection(action=dict(kind='read_source',url='https://example.org/invented',prediction='查证')),reflection('没有实际检索来源，尚未读取')])
            q=Inquiry(Path(d)/'db',c,source_fn=forbidden)
            try:
                q.turn('查一下')
                event=json.loads(q.db.execute("SELECT payload FROM inquiry_events WHERE kind='tool_result'").fetchone()[0])
                self.assertEqual('failed',event['status'])
                self.assertEqual('source_not_retrieved',event['error_kind'])
            finally:q.close()

    def test_experiment_receipt_becomes_grounded_proposal_and_is_retrievable(self):
        experiment=dict(kind='experiment',parameters={'n':[1,6,13],'setup':[0,100]},derived={'net':'n*8-setup'},assertion='net>0',assumptions=['固定净省8分钟；忽略维护'],prediction='预期存在固定成本导致的反例')
        class ExperimentClient(FakeClient):
            def complete(self,messages):
                self.seen.append(messages)
                if len(self.seen)==1:return reflection(action=experiment)
                import re
                event=int(re.search(r'"event": (\d+)',messages[-1]['content']).group(1))
                v=reflection('自动化不是每次节省就总体值得；模型找到反例')
                v['knowledge']=[{'statement':'自动化的固定成本可能超过有限次数的节省','kind':'decision','method':'deduction',
                  'premises':[{'event':event,'quote':'"counterexample_count": 2','role':'evidence'}],
                  'assumptions':['每次固定净省8分钟'],'conditions':['给定有限参数网格'],'alternatives':['保持手工'],
                  'falsifier':'设置成本为零且净省为正时，此负收益路线不适用','revises':None}]
                return v
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'db';q=Inquiry(p,ExperimentClient([]),synthetic=True)
            try:
                self.assertIn('反例',q.turn('自动化每次节省就值得吗'))
                proposals=q.knowledge.proposals(synthetic=True)
                self.assertEqual(1,len(proposals))
                premise=proposals[0]['proposal']['premises'][0]['event']
                self.assertTrue(q.dependencies.depends_on(proposals[0]['event'],premise))
            finally:q.close()
            q=Inquiry(p,FakeClient([]),synthetic=True)
            try:self.assertEqual(1,len(q.retrieve_knowledge('自动化固定成本')))
            finally:q.close()

if __name__=='__main__':unittest.main()
