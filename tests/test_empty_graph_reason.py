"""r100: an empty `dojo questions` graph must say which of four things it is.

Measured before this: `python -m dojo --db X questions` printed the identical
171-byte JSON for a path that does not exist, for a healthy sqlite file that is
not a dojo library, for a dojo library with no question rows, and for a view
that filtered all of them. r99 recorded three `docs/evidence` files as
`unreadable_db` on that basis; all three open fine and pass
`PRAGMA integrity_check`, they simply carry the candidate-pipeline schema.

Pinned here:
  * each of the four situations prints its own reason line on stderr;
  * stdout is byte-identical across all four (the JSON is the contract);
  * a library with visible questions prints no reason line;
  * the reason text never claims the library is broken.
"""
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from dojo.inquiry import Inquiry

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'dojo' / 'cli.py').is_file())
ENV = {**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1'}
def seed_questions(target):
    class OfflineHost:
        config = SimpleNamespace(model='offline-questions-fixture', api_key=None)

        def complete(self, *args, **kwargs):
            raise AssertionError('the fixture does not call a model')

    text = '两张合成标签里，蓝签是否需要保留？'
    q = Inquiry(target, OfflineHost(), synthetic=True, request_budget=0, tool_budget=0)
    try:
        event = q.record('user', {'text': text, 'synthetic': True})
        q.user_sources[event] = text
        q.visible_source_text[event] = text
        q.questions.apply(q, {'kind': 'map_inquiry', 'questions': [{
            'key': 'blue', 'text': text, 'parents': [], 'origin_event': event,
            'origin_quote': '蓝签是否需要保留', 'revises': None,
        }], 'links': [], 'prediction': '确认蓝签是否属于这组合成样例'})
    finally:
        q.close()


def questions(db, *extra):
    proc = subprocess.run(
        [sys.executable, '-X', 'utf8', '-m', 'dojo', '--db', str(db), 'questions', *extra],
        cwd=str(ROOT), capture_output=True, env=ENV)
    return (proc.returncode, proc.stdout, proc.stderr.decode('utf-8', 'replace'))


class EmptyGraphReasonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.source = self.dir / 'seed.sqlite3'
        seed_questions(self.source)

    def copy_source(self, name):
        target = self.dir / name
        shutil.copyfile(self.source, target)
        return target

    def test_a_missing_path_says_it_could_not_see_the_library(self):
        code, out, err = questions(self.dir / 'not-there.sqlite3', '--synthetic')
        self.assertEqual(0, code)
        self.assertEqual([], json.loads(out)['nodes'])
        self.assertIn('空图原因（absent）', err)
        self.assertIn('这个路径上没有文件', err)

    def test_a_pipeline_store_is_not_called_broken(self):
        """The three docs/evidence files: healthy sqlite, other schema."""
        target = self.dir / 'store.sqlite3'
        db = sqlite3.connect(target)
        db.execute('CREATE TABLE candidates (id TEXT, version INTEGER, state_json TEXT)')
        db.execute('CREATE TABLE events (seq INTEGER, candidate_id TEXT)')
        db.commit()
        db.close()
        code, out, err = questions(target, '--synthetic')
        self.assertEqual(0, code)
        self.assertEqual([], json.loads(out)['nodes'])
        self.assertIn('空图原因（not_dojo）', err)
        # names what it does hold, so the reader can recognise the file
        self.assertIn('candidates', err)
        self.assertIn('没有 inquiry_events', err)
        # and never calls a readable file unreadable or corrupt
        for word in ('坏', '损坏', '打不开', 'malformed', 'not a database'):
            self.assertNotIn(word, err)

    def test_a_library_without_questions_says_so(self):
        target = self.copy_source('no-questions.sqlite3')
        db = sqlite3.connect(target)
        for kind in ('inquiry_question', 'question_parent', 'question_evidence'):
            db.execute('DELETE FROM inquiry_events WHERE kind=?', (kind,))
        db.commit()
        remaining = db.execute('SELECT count(*) FROM inquiry_events').fetchone()[0]
        db.close()
        self.assertGreater(remaining, 0, 'fixture must still be a dojo library')
        code, out, err = questions(target, '--synthetic')
        self.assertEqual(0, code)
        self.assertEqual([], json.loads(out)['nodes'])
        self.assertIn('空图原因（no_questions）', err)
        self.assertIn(str(remaining), err)

    def test_a_filtered_view_says_it_filtered_rather_than_that_nothing_exists(self):
        target = self.copy_source('all-synthetic.sqlite3')
        db = sqlite3.connect(target)
        rows = db.execute(
            "SELECT seq,payload FROM inquiry_events WHERE kind IN "
            "('inquiry_question','question_parent','question_evidence')").fetchall()
        self.assertTrue(rows)
        for seq, payload in rows:
            data = json.loads(payload)
            data['synthetic'] = True
            db.execute('UPDATE inquiry_events SET payload=? WHERE seq=?',
                       (json.dumps(data, ensure_ascii=False), seq))
        db.commit()
        db.close()
        # no --synthetic: every question row is synthetic, so this view hides them all
        code, out, err = questions(target)
        self.assertEqual(0, code)
        self.assertEqual([], json.loads(out)['nodes'])
        self.assertIn('空图原因（filtered）', err)
        self.assertIn(str(len(rows)), err)

    def test_stdout_is_identical_across_all_four_and_a_populated_library_is_quiet(self):
        other = self.dir / 'store.sqlite3'
        db = sqlite3.connect(other)
        db.execute('CREATE TABLE candidates (id TEXT)')
        db.commit()
        db.close()
        no_questions = self.copy_source('no-questions.sqlite3')
        with sqlite3.connect(no_questions) as db:
            db.execute("DELETE FROM inquiry_events WHERE kind='inquiry_question'")
        empty = [
            questions(self.dir / 'not-there.sqlite3', '--synthetic'),
            questions(other, '--synthetic'),
            questions(no_questions, '--synthetic'),
            questions(self.source),
        ]
        self.assertTrue(all(code == 0 for code, _, _ in empty))
        digests = {hashlib.sha256(out).hexdigest()[:16] for _, out, _ in empty}
        self.assertEqual(1, len(digests), 'the JSON contract must not vary with the reason')
        # a library that does hold questions gets no reason line
        code, out, err = questions(self.source, '--synthetic')
        self.assertEqual(0, code)
        self.assertTrue(json.loads(out)['nodes'])
        self.assertNotIn('空图原因', err)


if __name__ == '__main__':
    unittest.main()
