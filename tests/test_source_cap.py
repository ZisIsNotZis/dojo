"""一条道的等级必须被它自己的出处核对封顶。

实测的缺陷：在一个浅克隆里 `--check` 的库里印着 `按所指版本核对 0 条`，
而同一份输出的第 2 行仍写 `检（3/3）`，退出码还是 0。计数是诚实的，
但它没有碰到读者真正读的那一行。

这里不测"计数对不对"（那有别的测试），只测那个连线：
能够核的引文一条也没核上时，这一行不许说"检"。
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('dao_life', ROOT / 'scripts' / 'dao_life.py')
live = importlib.util.module_from_spec(spec)
spec.loader.exec_module(live)


DAO = {'id': 'd-1', 'version': 1,
       'situation': {'covers': ['ep-1']},
       'provenance': [{'person': 'p', 'episode': 'ep-1'}]}


def receipts(rows):
    return {'structure': {'verdict': 'pass'},
            'falsifiable': {'verdict': 'pass'},
            'field': {'verdict': 'pass', 'observation': {'kind': 'agent_self'}},
            'sources': {'rows': rows}}


def row(quote='found', commit_state='resolved', checked_at='commit', ident='ep-1'):
    return {'id': ident, 'quote': quote, 'commit_state': commit_state,
            'checked_at': checked_at}


class TheLevelIsCappedByItsOwnCitations(unittest.TestCase):
    def status(self, rows, dao=None):
        return live.status_of(dao or DAO, receipts(rows), {})

    def test_a_quote_read_at_its_revision_does_not_cap(self):
        state = self.status([row()])
        self.assertEqual('pass', state['sources']['verdict'])
        self.assertEqual('检', state['mark'])
        self.assertIn('出处 过（1/1', state['line'])

    def test_a_revision_that_could_not_be_read_caps_the_level(self):
        """The shallow-clone shape: nothing failed, but nothing was read either."""
        state = self.status([row(quote='unchecked-at-revision',
                                 commit_state='unresolved', checked_at='no-revision')])
        self.assertEqual('uncertain', state['sources']['verdict'])
        self.assertEqual('未检', state['mark'])
        self.assertIn('出处 未核（0/1', state['line'])

    def test_a_quote_that_is_not_where_it_says_caps_the_level(self):
        state = self.status([row(quote='absent')])
        self.assertEqual('fail', state['sources']['verdict'])
        self.assertEqual('未检', state['mark'])
        self.assertIn('出处 不过', state['line'])

    def test_a_moving_name_caps_the_level(self):
        state = self.status([row(commit_state='moving-name', checked_at='no-revision')])
        self.assertEqual('fail', state['sources']['verdict'])
        self.assertEqual('未检', state['mark'])

    def test_an_authored_corpus_is_not_capped(self):
        """No revision is owed, so there is nothing to check and nothing to cap."""
        state = self.status([row(quote='found', commit_state='not-required',
                                 checked_at='working-tree')])
        self.assertEqual('not_run', state['sources']['verdict'])
        self.assertEqual('检', state['mark'])
        self.assertNotIn('出处', state['line'])  # nothing to say is said by saying nothing

    def test_another_daos_unreadable_quote_does_not_cap_this_one(self):
        """Only the episodes this dao covers count: a neighbour's gap is not a cap."""
        rows = [row(),
                row(quote='absent', commit_state='resolved', checked_at='commit',
                    ident='ep-other')]
        state = self.status(rows)
        self.assertEqual('pass', state['sources']['verdict'])
        self.assertEqual('检', state['mark'])

    def test_the_cap_does_not_drop_the_count_it_still_reports(self):
        """3/3 was true about those three cells; the cap adds a word, not a lie."""
        state = self.status([row(checked_at='no-revision', quote='unchecked-at-revision',
                                 commit_state='unresolved')])
        self.assertEqual(3, state['count'])
        self.assertIn('3/3', state['line'])


if __name__ == '__main__':
    unittest.main()
