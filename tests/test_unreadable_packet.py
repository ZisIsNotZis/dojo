"""r98: a review whose basis event is gone must still be readable, and say so.

r97 printed the basis of every review row, but one case stayed unreachable:
`basis_source_state` has a sentence for 'this cited event is not in this library'
and the CLI could never print it, because `proposals()` -> `review_packet()`
raised `unknown knowledge source` first and took the whole run down with exit 2
and empty stdout. Measured on a copy of the r97 run db with one cited event
deleted: `error: unknown knowledge source`, and the guard returned the right
sentence when called directly.

Pinned here:
  * the listing survives a proposal whose premise event is absent, and names it;
  * the row's reviews are still listed, and the absent basis event gets the
    'cannot be read' sentence rather than 'still standing' or nothing;
  * the attempt's digest is a third state, not 'same_as_today' and not
    'written_under_another_rule' -- no comparison happened;
  * `review_packet` still refuses, so a reviewer cannot act on a packet it
    cannot read;
  * a library with nothing missing is unchanged (no `packet_unreadable` key).
"""
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'dojo' / 'cli.py').is_file())
from dojo.inquiry import Inquiry  # noqa: E402
from dojo.knowledge import Knowledge  # noqa: E402
from dojo.reviews import apply_review  # noqa: E402

UNRESOLVED = {'disposition': 'unresolved', 'reason': 'r98 fixture verdict', 'replacement': None}


def proposal(statement, source, quote):
    return {'statement': statement, 'kind': 'causal', 'method': 'hypothesis',
            'premises': [{'event': source, 'quote': quote, 'role': 'evidence'}],
            'assumptions': ['a'], 'conditions': ['c'], 'alternatives': ['b'],
            'falsifier': 'f', 'revises': None}


class UnreadablePacketTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'db'
        self.q = Inquiry(self.path,
                         SimpleNamespace(config=SimpleNamespace(model='deepseek-flash', api_key=None)),
                         synthetic=True)
        self.addCleanup(self.q.close)
        self.live = self.q.record('user', {'text': '我只看时间成本，每次省8分钟', 'synthetic': True})
        self.spare = self.q.record('user', {'text': '另外那批报告不算时间成本', 'synthetic': True})
        claim = proposal('模型内 6 次报告净省 48 分钟', self.live, '每次省8分钟')
        # A premise quote needs a 6-character run (MIN_QUOTE_RUN); a shorter one
        # is refused by the gate, which is why the first fixture never got as
        # far as building a packet.
        claim['premises'].append({'event': self.spare, 'quote': '另外那批报告', 'role': 'value'})
        self.target = self.q.knowledge.accept(self.q.run, claim, {self.live, self.spare}, synthetic=True)
        apply_review(self.q, self.q.knowledge.review_packet(self.target), dict(UNRESOLVED))

    def cli(self):
        proc = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'dojo', '--db', str(self.path),
                               'knowledge', '--synthetic'],
                              cwd=str(ROOT), capture_output=True)
        return (proc.returncode, proc.stdout.decode('utf-8', 'replace'),
                proc.stderr.decode('utf-8', 'replace'))

    def delete_cited_event(self):
        # No product path deletes events; this is the damaged-library case.
        con = sqlite3.connect(self.path)
        con.execute('DELETE FROM inquiry_events WHERE seq=?', (self.spare,))
        con.commit()
        con.close()

    def test_the_listing_survives_and_names_the_absent_event(self):
        self.delete_cited_event()
        code, out, err = self.cli()
        self.assertEqual(0, code, err)
        self.assertIn('重建不出来', err)
        self.assertIn('事件 %d' % self.spare, err)
        # Not a verdict on the proposition, and not a claim that reviews never ran.
        self.assertIn('这不是在说这个说法错了', err)
        self.assertIn('也不是在说这些复核没做过', err)
        rows = json.loads(out)
        row = next(r for r in rows if r['event'] == self.target)
        self.assertIn('packet_unreadable', row)
        self.assertTrue(row.get('review_attempts'))

    def test_the_absent_basis_event_says_it_cannot_be_read(self):
        self.delete_cited_event()
        code, out, err = self.cli()
        self.assertEqual(0, code, err)
        unreadable = [l for l in err.splitlines() if '在本库里找不到' in l and '依据' in l]
        self.assertTrue(unreadable, err)
        self.assertIn('（%d）' % self.spare, ''.join(unreadable))
        # and it must not also be described as still standing
        self.assertNotIn('（事件 %d）至今没被换掉' % self.spare, err)

    def test_the_attempt_digest_is_a_third_state(self):
        self.delete_cited_event()
        code, out, _ = self.cli()
        self.assertEqual(0, code)
        rows = json.loads(out)
        item = next(r for r in rows if r['event'] == self.target)['review_attempts'][0]
        self.assertEqual('packet_unreadable_today', item['digest'])
        self.assertIn('没跟今天比过', item['reading'])
        # must not read as 'the material differs'
        self.assertNotIn('不同的内容摘要下', item['reading'])

    def test_review_packet_still_refuses_an_unreadable_basis(self):
        """The listing degrades; the reviewer's gate must not."""
        self.delete_cited_event()
        con = sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True)
        self.addCleanup(con.close)
        k = Knowledge(con, initialize=False)
        with self.assertRaises(ValueError):
            k.review_packet(self.target)

    def test_an_intact_library_gains_no_new_key(self):
        code, out, err = self.cli()
        self.assertEqual(0, code, err)
        rows = json.loads(out)
        for row in rows:
            self.assertNotIn('packet_unreadable', row)
        self.assertNotIn('重建不出来', err)


if __name__ == '__main__':
    unittest.main()
