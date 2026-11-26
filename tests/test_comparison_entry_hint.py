"""`--context` and `--comparison` share one branch; each refusal must name its own flag.

#3245: adopting the comparison view collapsed both refusals onto the `--context`
sentence, so `stories --comparison 5` told the reader to run `--context`. Exit code
alone cannot catch that -- both paths exit 2 -- so these assertions name the words.
"""
import contextlib
import io
import unittest

from dojo.cli import main

# Deliberately absent: both refusals are raised before the ledger is opened.
ABSENT_DB = '/tmp/dojo-comparison-hint-absent.sqlite3'


def ask(*flags):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(['--db', ABSENT_DB, 'stories', *flags, '--synthetic'])
    return code, err.getvalue().strip()


class ComparisonEntryHintTests(unittest.TestCase):
    def test_comparison_without_story_names_comparison(self):
        code, err = ask('--comparison', '5')
        self.assertEqual(2, code)
        self.assertIn('--comparison', err)
        self.assertIn('STORY', err)
        self.assertNotIn('--context', err)

    def test_context_without_story_still_names_context(self):
        code, err = ask('--context')
        self.assertEqual(2, code)
        self.assertIn('--context', err)
        self.assertNotIn('--comparison', err)


if __name__ == '__main__':
    unittest.main()
