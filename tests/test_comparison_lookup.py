
"""Regressions for the read-only `stories STORY --comparison EVENT` entry.

The point of these assertions is that exit status alone cannot hold this entry:
`comparison=None` still exits 0 for a correct story while dropping the object.
"""
import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dojo.cli import main  # noqa: E402
from dojo.inquiry import Inquiry

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
# `*.sqlite3` is gitignored, so a checkout has no ledger file to copy: build it from
# the committed scenario text instead. Same content, and the suite runs anywhere.
from fixtures import build_comparison_ledger as ledger_fixture  # noqa: E402
STORY = '0f272e5f34244b328df1c80edfdde3df'


class ComparisonLookupTests(unittest.TestCase):
    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix='dojo-lookup-guard.'))
        self.db = self.work / 'story.sqlite3'
        # Base shape only: test_replaced_conclusion... writes its own `5 -> 23`
        # revision row, and the successor spec already occupies `old_event = 5`.
        ledger_fixture.build(self.db)
        self.before = self.db.read_bytes()

    def tearDown(self):
        shutil.rmtree(self.work, ignore_errors=True)

    def ask(self, story, event):
        import contextlib
        import io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(['--db', str(self.db), 'stories', story,
                         '--comparison', str(event), '--synthetic'])
        return code, out.getvalue()

    def test_checked_and_open_are_named_not_merely_returned(self):
        code, text = self.ask(STORY, 5)
        self.assertEqual(0, code)
        row = json.loads(text)['comparison']
        self.assertEqual(5, row['conclusion_event'])
        self.assertEqual('checked', row['comparison_status'])
        self.assertEqual([3, 4], row['comparisons'][0]['source_events'])

        code, text = self.ask(STORY, 23)
        self.assertEqual(0, code)
        row = json.loads(text)['comparison']
        self.assertEqual(23, row['conclusion_event'])
        self.assertEqual('open', row['comparison_status'])
        self.assertTrue(row['next_check'])
        self.assertEqual(self.before, self.db.read_bytes())

    def test_existing_other_story_cannot_retrieve_comparison(self):
        client = SimpleNamespace(config=SimpleNamespace(model='offline-guard', api_key=None))
        writer = Inquiry(self.db, client, synthetic=True, request_budget=0, tool_budget=0)
        try:
            other = writer.story
            writer.record('user', {'text': '这个独立合成故事没有正文比较。', 'synthetic': True})
        finally:
            writer.close()
        self.assertNotEqual(STORY, other)
        import contextlib
        import io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            status = main(['--db', str(self.db), 'stories', '--synthetic'])
        self.assertEqual(0, status)
        self.assertIn(other, {story['story'] for story in json.loads(out.getvalue())})
        before_lookup = self.db.read_bytes()
        self.assertEqual((2, ''), self.ask(other, 5))
        self.assertEqual(before_lookup, self.db.read_bytes())

    def test_absent_event_is_refused(self):
        self.assertEqual((2, ''), self.ask(STORY, 999))

    def test_replaced_conclusion_and_absent_number_are_two_refusals(self):
        # A replaced conclusion has a successor to read; an absent number has none.
        # One sentence for both sends the reader to the wrong next step.
        # The revision row is written straight into this copy's ledger; the product
        # write path that produces the same row is proven in comparison-refusal.json.
        with closing(sqlite3.connect(self.db)) as db:
            db.execute('INSERT INTO inquiry_revisions VALUES(?,?,?)',
                       (5, 23, 'guard: 标记旧版已被替代，不改任何提议内容'))
            db.commit()
        before = self.db.read_bytes()
        replaced = self.refusal(5)
        absent = self.refusal(999)
        self.assertEqual(2, replaced[0])
        self.assertEqual(2, absent[0])
        self.assertIn('#23', replaced[1])
        self.assertNotEqual(replaced[1], absent[1])
        self.assertEqual(before, self.db.read_bytes())
        # Adjacent story: the same number under another story is not 'absent'.
        self.assertEqual(2, self.refusal(999)[0])
        self.assertIn('不存在', absent[1])

    def refusal(self, event):
        import contextlib
        import io
        err = io.StringIO()
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(['--db', str(self.db), 'stories', STORY,
                         '--comparison', str(event), '--synthetic'])
        return code, err.getvalue().strip()


if __name__ == '__main__':
    unittest.main()
