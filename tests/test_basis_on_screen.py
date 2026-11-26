"""r97: the basis a row recorded must reach the screen, and its absence must too.

Before this, `basis_missing` was computed into the JSON (156 occurrences across
real libraries) and never printed: 0 lines on screen. So a row with no recorded
basis looked on screen exactly like a row nobody had reviewed.

Pinned here:
  * a complete basis prints its citations and neither the missing nor the gap line;
  * a row with no basis prints the "no basis entry" sentence, and no citation
    sentence of its own (the row must not borrow a neighbour's basis);
  * a row whose basis holds an unlocatable quote prints a gap line naming the
    entry, and is NOT reported as having no basis at all;
  * `basis_gaps` returns [] for a complete list (so the key stays absent).
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Locate the tree that holds the package, not a fixed depth: this file runs from
# tests/ in the repo and from .scratch/dojo-grid/r97/ under a red-control copy.
ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'dojo' / 'cli.py').is_file())
from dojo.inquiry import Inquiry  # noqa: E402
from dojo.knowledge import basis_gaps  # noqa: E402
from dojo.reviews import apply_review  # noqa: E402

from types import SimpleNamespace  # noqa: E402

UNRESOLVED = {'disposition': 'unresolved', 'reason': 'r97 fixture verdict', 'replacement': None}


def proposal(statement, source, quote):
    return {'statement': statement, 'kind': 'causal', 'method': 'hypothesis',
            'premises': [{'event': source, 'quote': quote, 'role': 'evidence'}],
            'assumptions': ['a'], 'conditions': ['c'], 'alternatives': ['b'],
            'falsifier': 'f', 'revises': None}


class ScreenTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'db'
        self.q = Inquiry(self.path,
                         SimpleNamespace(config=SimpleNamespace(model='deepseek-flash', api_key=None)),
                         synthetic=True)
        self.addCleanup(self.q.close)
        self.live = self.q.record('user', {'text': '我只看时间成本，每次省8分钟', 'synthetic': True})
        claim = proposal('模型内 6 次报告净省 48 分钟', self.live, '每次省8分钟')
        self.target = self.q.knowledge.accept(self.q.run, claim, {self.live}, synthetic=True)
        apply_review(self.q, self.q.knowledge.review_packet(self.target), dict(UNRESOLVED))

    def cli(self):
        proc = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'dojo', '--db', str(self.path),
                               'knowledge', '--synthetic'],
                              cwd=str(ROOT), capture_output=True)
        self.assertEqual(0, proc.returncode, proc.stderr.decode('utf-8', 'replace'))
        return (proc.stdout.decode('utf-8', 'replace'), proc.stderr.decode('utf-8', 'replace'))

    def add_row(self, **fields):
        payload = {'target': self.target,
                   'packet_sha256': self.q.knowledge.review_packet(self.target)['sha256'],
                   'disposition': 'unresolved', 'reason': 'r97 control', 'replacement_event': None}
        payload.update(fields)
        self.q.record('knowledge_review', payload)

    def test_a_complete_basis_prints_citations_and_no_gap_line(self):
        out, err = self.cli()
        self.assertIn('复核记录所依据的那句', err)
        self.assertNotIn('没有依据条目', err)
        self.assertNotIn('的引文定位不到任何内容', err)
        item = self.q.knowledge.review_packet(self.target)['review_attempts'][-1]
        self.assertTrue(item['premise_events'])
        self.assertNotIn('basis_incomplete', item)

    def test_a_row_with_no_basis_says_so_and_borrows_nothing(self):
        self.add_row(premise_events=[], basis_readings=[])
        out, err = self.cli()
        missing = [l for l in err.splitlines() if '没有依据条目' in l]
        self.assertTrue(missing, err)
        # The control row is the newest, so its line is the last missing one.
        # Its own line must not carry any citation text.
        self.assertNotIn('每次省8分钟', ''.join(missing))
        self.assertNotIn('据了哪几句，也没有', ''.join(
            l for l in err.splitlines() if '依据的那句' in l and '48' in l))

    def test_a_basis_with_an_unlocatable_quote_is_a_gap_not_an_absence(self):
        self.q.record('knowledge_review', {
            'target': self.target,
            'packet_sha256': self.q.knowledge.review_packet(self.target)['sha256'],
            'disposition': 'unresolved', 'reason': 'r97 unlocatable', 'replacement_event': None,
            'premise_events': [{'event': self.live, 'at': '2026-01-01T00:00:00+00:00',
                                'reading': 'x', 'citation_kind': 'none', 'role': 'evidence',
                                'quote': '48'}],
            'basis_readings': ['x']})
        out, err = self.cli()
        self.assertIn('的引文定位不到任何内容', err)
        self.assertIn('「48」', err)
        # and the row is not called basis-less
        item = self.q.knowledge.review_packet(self.target)['review_attempts'][-1]
        self.assertNotIn('basis_missing', item)
        self.assertTrue(item['basis_incomplete'])

    def test_gaps_is_empty_for_a_complete_list(self):
        stored = [{'event': 1, 'at': 't', 'reading': 'r', 'citation_kind': 'prose',
                   'role': 'evidence', 'quote': '我只看时间成本'}]
        self.assertEqual([], basis_gaps(stored, ['r']))
        self.assertTrue(basis_gaps(stored, []))
        self.assertTrue(basis_gaps([{'event': 1, 'quote': '我只看时间成本'}], ['r']))
        self.assertTrue(basis_gaps([dict(stored[0], quote='48')], ['r']))


if __name__ == '__main__':
    unittest.main()
