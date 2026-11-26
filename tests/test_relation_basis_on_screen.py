"""r99: a relation review's basis must reach the screen in three states.

Measured before this: `question_review` rows carried `premise_events` since r92
and `review_basis_view` computed `basis_missing` for the rest, while
`dojo questions` printed neither -- 104 of 104 stored relation reviews showed no
basis line at all. Same defect as r97 on the knowledge side, one table over.

Pinned here:
  * a complete basis prints its recorded citation and says what it is now;
  * a row with no basis prints the missing sentence and borrows no quotation --
    the assertion is against every quote in the database, not just the
    neighbour's;
  * a row whose quote locates nothing prints the gap sentence and is not
    reported as having no basis;
  * the JSON contract on stdout is unchanged: `review_attempts` still needs
    `--review-basis`, because that document is fed to the model verbatim.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'dojo' / 'cli.py').is_file())
from dojo.inquiry import Inquiry  # noqa: E402
from dojo.question_reviews import apply_review, review_packet  # noqa: E402

UNRESOLVED = {'disposition': 'unresolved', 'reason': 'r99 fixture verdict', 'replacement': None}


class Host:
    config = SimpleNamespace(model='deepseek-flash', api_key=None)


class RelationScreenTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'db'
        self.q = Inquiry(self.path, Host(), synthetic=True)
        self.addCleanup(self.q.close)

    def build(self, quote, value=48):
        q = self.q
        self.user = q.record('user', {'text': '我只看时间成本，每次省8分钟', 'synthetic': True})
        q.user_sources[self.user] = '我只看时间成本，每次省8分钟'
        q.visible_source_text[self.user] = '我只看时间成本，每次省8分钟'
        self.tool = q.record('tool_result', {'status': 'executed', 'result': {'value': value}})
        q.visible_source_text[self.tool] = q.knowledge.source(self.tool)['text']
        proposal = {'statement': '6次报告净省48分钟', 'kind': 'decision', 'method': 'deduction',
                    'premises': [{'event': self.tool, 'quote': '"value": %d' % value, 'role': 'evidence'}],
                    'assumptions': ['每次净省8分钟'], 'conditions': ['只做6次'],
                    'alternatives': ['保留手工'], 'falsifier': '设置成本超过48分钟', 'revises': None}
        self.claim = q.knowledge.accept(q.run, proposal, {self.tool}, synthetic=True)
        q.visible_source_text[self.claim] = q.knowledge.source(self.claim)['text']
        created = q.questions.apply(q, {'kind': 'map_inquiry',
            'questions': [{'key': 'root', 'text': '交接必须保留什么？', 'parents': [],
                           'origin_event': self.user, 'origin_quote': '我只看时间成本', 'revises': None}],
            'links': [{'question': 'root', 'proposition': self.claim, 'source_event': self.tool,
                       'quote': quote, 'relation': 'context',
                       'explanation': '该材料与问题相关，但不构成支持或反驳'}],
            'prediction': '组织待核实条件'})
        self.node = created['question_keys']['root']
        q.visible_source_text[self.node] = q.knowledge.source(self.node)['text']
        self.target = q.questions.view(story=q.story, synthetic=True)['nodes'][0]['annotations'][0]['event']

    def review(self):
        return apply_review(self.q, review_packet(self.q, self.target), dict(UNRESOLVED))

    def cli(self, *extra):
        proc = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'dojo', '--db', str(self.path),
                               'questions', '--synthetic', *extra],
                              cwd=str(ROOT), capture_output=True)
        self.assertEqual(0, proc.returncode, proc.stderr.decode('utf-8', 'replace'))
        return (proc.stdout.decode('utf-8', 'replace'), proc.stderr.decode('utf-8', 'replace'))

    def basis_lines(self, err):
        return [line for line in err.splitlines() if '复核' in line and '（关系' in line]

    def test_a_complete_basis_prints_its_citation_and_its_state_now(self):
        self.build('"value": 48')
        self.review()
        out, err = self.cli()
        lines = self.basis_lines(err)
        self.assertTrue(lines, err)
        self.assertIn('这条关系复核记下的是', '\n'.join(lines))
        self.assertIn('所依据的那句（事件 %d）' % self.tool, '\n'.join(lines))
        self.assertNotIn('没有依据条目', err)
        self.assertNotIn('定位不到任何内容', err)

    def test_a_row_with_no_basis_borrows_no_quotation_at_all(self):
        """The control this order exists for: absence must not be filled in."""
        self.build('"value": 48')
        os.environ['DOJO_REVIEW_RECORD'] = 'legacy'
        try:
            self.review()
        finally:
            os.environ.pop('DOJO_REVIEW_RECORD', None)
        out, err = self.cli()
        missing = [line for line in self.basis_lines(err) if '没有依据条目' in line]
        self.assertTrue(missing, err)
        # Every quotation the database holds, checked against the missing line.
        quotes = []
        for (payload,) in self.q.db.execute("SELECT payload FROM inquiry_events"):
            data = json.loads(payload)
            for item in data.get('premise_events') or []:
                if isinstance(item, dict) and isinstance(item.get('quote'), str):
                    quotes.append(item['quote'])
            if isinstance(data.get('quote'), str):
                quotes.append(data['quote'])
        self.assertTrue(quotes, 'fixture must hold at least one quotation to test against')
        for quote in quotes:
            self.assertNotIn(quote, ''.join(missing))
        self.assertNotIn('记下的是', ''.join(missing))
        self.assertNotIn('定位不到任何内容', ''.join(missing))

    def test_a_quote_that_locates_nothing_is_a_gap_not_an_absent_basis(self):
        self.build('-52', value=-52)
        self.review()
        out, err = self.cli()
        text = '\n'.join(self.basis_lines(err))
        self.assertIn('定位不到任何内容', text)
        self.assertIn('记下的是「-52」', text)
        self.assertNotIn('没有依据条目', err)

    def test_the_json_contract_does_not_grow_these_keys(self):
        self.build('"value": 48')
        self.review()
        quiet, _ = self.cli()
        loud, _ = self.cli('--review-basis')
        self.assertNotIn('review_attempts', quiet)
        self.assertNotIn('basis_state_now', quiet)
        self.assertIn('review_attempts', loud)
        # `--review-basis` is opt-in for the JSON only; everything else is
        # identical, so the flag cannot be smuggling a different graph.
        def without_basis(nodes):
            return [{k: v for k, v in node.items()} for node in nodes]
        quiet_nodes = json.loads(quiet)['nodes']
        loud_nodes = json.loads(loud)['nodes']
        for node in loud_nodes:
            for item in (node.get('annotation_history') or []) + (node.get('annotations') or []):
                item.pop('review_attempts', None)
        self.assertEqual(quiet_nodes, without_basis(loud_nodes))


if __name__ == '__main__':
    unittest.main()
