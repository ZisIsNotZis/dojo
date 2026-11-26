"""Structured comparison closure is version-scoped, not a review/text heuristic."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest

from dojo.inquiry import Inquiry
from dojo.knowledge import _reopened_since, record_source_comparison
from dojo.stories import reading_context, resume_comparison_view


class SourceComparisonTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'ledger.sqlite'
        self.host = SimpleNamespace(config=SimpleNamespace(model='offline'))
        self.q = Inquiry(self.path, self.host, request_budget=0)
        self.addCleanup(self.q.close)

    def read(self, slug, text='现场逐项原始记录', *, q=None):
        q = q or self.q
        url = 'https://test.invalid/' + slug
        return q.record('tool_result', {'status': 'executed', 'action': {'kind': 'read_source', 'url': url},
                                        'result': {'url': url, 'text': text}})

    def proposal(self, *events, statement='同一批次有 7 项。', old=None):
        premises = [{'event': e, 'role': 'evidence', 'quote': '现场逐项原始记录'} for e in events]
        return self.q.knowledge.accept(self.q.run, {
            'statement': statement, 'kind': 'descriptive', 'method': 'induction', 'premises': premises,
            'assumptions': [], 'conditions': [], 'alternatives': [], 'falsifier': '不同读数', 'revises': old,
        }, {*events, old})

    def snapshot(self):
        return self.path.read_bytes(), sorted(p.name for p in self.path.parent.iterdir())

    def row(self, target):
        before = self.snapshot()
        data = reading_context(self.path, self.q.story)
        self.assertEqual(before, self.snapshot())
        return next(x for x in data['story_coverage']['missing_independence']['items']
                    if x['conclusion_event'] == target)

    def compare(self, target, first, second, relation='supports_independently'):
        return record_source_comparison(self.path, self.q.story, target, [first, second], relation,
                                        '人工核对记录；不解析此文本。')

    def test_both_caps_count_omitted_pending_comparisons(self):
        first, second = self.read('original'), self.read('second')
        checked = self.proposal(first, second)
        self.compare(checked, first, second)
        pending = [self.proposal(first, second, statement=f'待核结论 {i}') for i in range(6)]

        report = reading_context(self.path, self.q.story)['story_coverage']['missing_independence']
        self.assertEqual(pending[:5], [row['conclusion_event'] for row in report['items']])
        self.assertEqual((2, 1), (report['omitted'], report['omitted_pending']))
        # #3192 guard: the dropped set is named, and its unchecked members are counted.
        # Without this, `omitted` is a directionless integer and no test holds it.
        self.assertEqual([pending[5], checked], report['omitted_events'])
        wide = resume_comparison_view(report, {first, second})
        self.assertEqual(report['omitted_events'], wide['omitted_events'])
        self.assertEqual(0, wide['omitted_events_hidden'])
        self.assertEqual(1, report['omitted_unchecked'])
        self.assertEqual(report['omitted'], len(report['omitted_events']) + report['omitted_events_hidden'])
        # Ordering guard, stated as intent rather than read off one event numbering:
        # within a rank class an unchecked conclusion may never follow a checked one.

        preview = resume_comparison_view(report, {first, second}, max_characters=1100)
        count = len(preview['items'])
        self.assertGreater(count, 0)
        self.assertLess(count, len(report['items']))
        self.assertEqual(pending[:count], [row['conclusion_event'] for row in preview['items']])
        self.assertEqual((7 - count, 6 - count), (preview['omitted'], preview['omitted_pending']))
        # The second layer must not lose the unchecked count either; every previewed
        # row here is open, so the two pending counts must fall together.
        self.assertEqual(6 - count, preview['omitted_unchecked'])
        self.assertEqual((pending[count:] + [checked])[:4], preview['omitted_events'])
        self.assertEqual(preview['omitted'],
                         len(preview['omitted_events']) + preview['omitted_events_hidden'])

    def test_pending_leads_checked_within_a_rank_class(self):
        # The guard has to be able to fail on its own. The compared conclusion is
        # created FIRST, so its event number is the smallest: without the ordering
        # key, plain (rank, event) puts the checked row at the top and this goes red.
        first, second = self.read('original'), self.read('second')
        checked = self.proposal(first, second, statement='已核结论')
        self.compare(checked, first, second)
        pending = [self.proposal(first, second, statement=f'待核结论 {i}') for i in range(4)]

        report = reading_context(self.path, self.q.story)['story_coverage']['missing_independence']
        statuses = [row['comparison_status'] for row in report['items']]
        # Stated as intent: a checked conclusion may never precede an unchecked one.
        self.assertEqual([], [i for i, s in enumerate(statuses)
                              if s == 'checked' and any(later != 'checked' for later in statuses[i + 1:])])
        self.assertEqual([row['conclusion_event'] for row in report['items'][:4]], pending)
        self.assertEqual(checked, report['items'][4]['conclusion_event'])

    def test_affirmative_comparison_records_without_reopening_or_inheriting(self):
        first, second = self.read('original'), self.read('second')
        target = self.proposal(first, second)
        self.q.record('knowledge_review', {'target': target, 'reason': '两份独立支持', 'replacement_event': target})
        open_row = self.row(target)
        self.assertIn('已引用', open_row['gap'])
        self.assertNotIn('正文支撑', open_row['gap'])
        self.assertIn('是否各自支持', open_row['next_check'])
        self.assertEqual('open', open_row['comparison_status'])
        result = self.compare(target, first, second)
        self.assertEqual('recorded', result['status'])
        self.assertEqual('current_interpretation', self.q.dependencies.status(target)['state'])
        self.assertFalse(_reopened_since(self.q.db, target, target))
        before = self.snapshot()
        self.assertEqual(result['notice_event'], self.compare(target, first, second)['notice_event'])
        self.assertEqual(before, self.snapshot())
        self.assertIsNone(self.row(target)['next_check'])
        successor = self.proposal(first, second, old=target)
        self.assertEqual('open', self.row(successor)['comparison_status'])
        with self.assertRaisesRegex(ValueError, 'current proposal'):
            self.compare(target, first, second)

    def test_conflict_is_explicit_and_wins_over_affirmative_comparison(self):
        first = self.read('ledger')
        target = self.proposal(first)
        second = self.read('counter', '现场逐项原始记录：总共 6 项')
        legacy = self.q.knowledge.request_review(self.q.run, target, [second], '明确冲突', {target, second})
        self.assertEqual('requested', legacy['status'])
        self.assertEqual('open', self.row(target)['comparison_status'])
        requested = self.compare(target, first, second, 'conflicts')
        self.assertEqual('requested', requested['status'])
        self.assertNotEqual(requested['notice_event'], legacy['notice_event'])
        self.assertIn(second, self.q.dependencies.status(target)['causes'])
        self.assertIn(f'#{second}', self.row(target)['next_check'])
        successor = self.proposal(first, second, old=target)
        self.compare(successor, first, second)
        contested = self.row(successor)
        self.assertEqual('contested', contested['comparison_status'])
        self.assertEqual(requested['notice_event'], contested['comparisons'][0]['notice_event'])
        self.assertEqual(['https://test.invalid/ledger'], contested['distinct_material_sources'])
        self.assertEqual('counter_evidence', contested['have'][1]['state'])
        changed = self.proposal(first, second, old=successor, statement='两份原文给出的计数不同。')
        self.assertEqual('open', self.row(changed)['comparison_status'])

    def test_omitted_conflicts_leave_a_count_and_an_exact_pointer(self):
        first = self.read('ledger')
        target = self.proposal(first)
        notices, others = [], []
        for i in range(6):
            others.append(self.read(f'counter-{i}', f'现场逐项原始记录：总共 {6-i} 项'))
            notices.append(self.compare(target, first, others[-1], 'conflicts')['notice_event'])
            if i < 3:
                continue
            row = self.row(target)
            omitted = i - 3
            self.assertEqual('contested', row['comparison_status'])
            self.assertEqual(omitted, row['comparisons_omitted'])
            self.assertEqual(notices[-4:][::-1], [x['notice_event'] for x in row['comparisons']])
            self.assertIn(f'判清事件 #{first} 与 #{others[i]} 的冲突', row['next_check'])
            if omitted:
                self.assertIn(f'另有 {omitted} 条较早的冲突未展开', row['next_check'])
                self.assertIn(f'通知 #{notices[omitted-1]}（事件 #{first} 与 #{others[omitted-1]}）', row['next_check'])
            else:
                self.assertNotIn('未展开', row['next_check'])
            if omitted > 1:
                self.assertNotIn(f'通知 #{notices[0]}（', row['next_check'])

    def test_comparison_isolation_and_rejected_writes(self):
        first, fragment, second = self.read('p'), self.read('p#n'), self.read('q')
        frag_target = self.proposal(first, fragment)
        target = self.proposal(first, second)
        peer = self.proposal(first, second, statement='比较的是同一批次。')
        with closing(Inquiry(self.path, self.host, request_budget=0)) as another:
            foreign = self.read('r', q=another)
        snapshot = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'same source URL'):
            self.compare(frag_target, first, fragment)
        with self.assertRaisesRegex(ValueError, 'same story'):
            self.compare(target, first, foreign, 'conflicts')
        with self.assertRaisesRegex(ValueError, 'show the proposal'):
            self.q.knowledge.request_review(self.q.run, target, [first, second], '理由', {target, first},
                                           comparison='supports_independently')
        self.assertEqual(snapshot, self.snapshot())
        self.assertEqual('single_group', self.row(frag_target)['rank_class'])
        peer_before = self.row(peer)
        self.compare(target, first, second)
        self.compare(target, first, second, 'conflicts')
        self.assertEqual('contested', self.row(target)['rank_class'])
        self.assertEqual(peer_before, self.row(peer))

    def test_legacy_event_only_db_needs_no_migration_to_read_context(self):
        path = self.path.with_name('legacy.sqlite')
        with closing(sqlite3.connect(path)) as db:
            with db:
                db.execute('CREATE TABLE inquiry_events (seq INTEGER PRIMARY KEY, run, kind, payload, at)')
                rows = [
                    ('start', {'synthetic': False}),
                    ('knowledge_proposal', {'proposal': {'statement': '旧版提议', 'premises': []}}),
                    ('review_evidence_notice', {'target': 2, 'sources': [1], 'reason': '未分类旧请求'}),
                ]
                db.executemany('INSERT INTO inquiry_events(run,kind,payload) VALUES(?,?,?)',
                               [('legacy', kind, json.dumps(data)) for kind, data in rows])
        before = path.read_bytes(), self.snapshot()[1]
        context = reading_context(path, 'legacy')
        self.assertEqual('open', context['story_coverage']['missing_independence']['items'][0]['comparison_status'])
        self.assertEqual(before, (path.read_bytes(), self.snapshot()[1]))


if __name__ == '__main__':
    unittest.main()
