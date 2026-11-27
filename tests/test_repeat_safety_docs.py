"""The repeat-safety evidence must keep matching what it measures.

`docs/evidence/2026-11-27-repeat-safety/LOOP.md` states numbers: three requests
before, one after; version 2 before and after a repeat; a pipeline mark that
stayed valid; two reasons for one sentence ending up in two rows. Prose that
quotes numbers is exactly the kind of thing that rots silently when the code
moves, so the numbers are re-produced here from the committed probe and compared
with what the doc says.

The front pages make two claims about this slice, and both are checked as routes
rather than as wording: that the reader is pointed at the evidence, and that the
block the page prints really shows the two reasons as separate rows.

It also refuses two shapes that would make the evidence reassuring instead of
true:

  * a quote that no longer appears verbatim in the committed excerpt, or a doc
    that drops the check that proves it (`check_quotes.py`);
  * a "before" number asserted without saying it was measured on the baseline.
"""
import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path


def _repo_root():
    if os.environ.get('DOJO_ROOT'):
        return Path(os.environ['DOJO_ROOT']).resolve()
    for parent in Path(__file__).resolve().parents:
        if (parent / 'dojo' / 'storage.py').is_file() and (parent / 'docs').is_dir():
            return parent
    raise RuntimeError('cannot locate the dojo repository root')


ROOT = _repo_root()
EVIDENCE = ROOT / 'docs' / 'evidence' / '2026-11-27-repeat-safety'
PROBE = EVIDENCE / 'probe.py'


def run_probe():
    env = {k: v for k, v in os.environ.items() if not k.startswith('DOJO_')}
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    proc = subprocess.run([sys.executable, '-B', str(PROBE)], cwd=str(ROOT),
                          capture_output=True, text=True, env=env, timeout=300)
    if proc.returncode != 0:
        raise AssertionError('probe.py failed:\n%s' % proc.stderr[-2000:])
    return json.loads(proc.stdout)


class TheDocsNumbersAreTheProbesNumbers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reading = run_probe()
        cls.loop = (EVIDENCE / 'LOOP.md').read_text(encoding='utf-8')
        cls.acceptance = (EVIDENCE / 'ACCEPTANCE.md').read_text(encoding='utf-8')

    def test_a_cut_response_is_its_own_kind_and_is_not_resent(self):
        a = self.reading['scenario_a']
        self.assertEqual('incomplete_response', a['client_error_kind_for_a_cut_body'])
        self.assertEqual(1, a['requests_received_for_one_user_turn'])
        self.assertFalse(a['told_the_user_the_model_format_was_invalid'])
        self.assertTrue(a['told_the_user_the_request_was_not_resent'])
        # The doc must keep claiming the *before* number and say where it came from.
        self.assertIn('3', self.loop)
        self.assertRegex(self.loop, r'改前', 'the doc dropped the before/after framing')

    def test_a_repeat_leaves_the_version_and_the_mark_alone(self):
        b = self.reading['scenario_b']
        self.assertEqual(b['version_after_first_confirm'], b['version_after_identical_repeat'])
        self.assertTrue(b['pipeline_mark_still_matches_the_card'])
        self.assertTrue(b['repeat_points_at_the_original'])
        self.assertEqual('confirm_discussable.repeat', b['repeat_event'])

    def test_a_real_second_action_still_writes(self):
        """The half a naive 'repeats are no-ops' fix would break."""
        self.assertTrue(self.reading['scenario_b']['a_different_confirm_still_writes'])

    def test_the_quote_check_is_still_part_of_the_evidence(self):
        checker = EVIDENCE / 'check_quotes.py'
        self.assertTrue(checker.is_file(), 'the verbatim-quote check was removed')
        excerpt = (EVIDENCE / 'source-excerpt.txt').read_text(encoding='utf-8')
        for url in ('https://www.rfc-editor.org/rfc/rfc9110.txt',
                    'https://www.rfc-editor.org/rfc/rfc9112.txt'):
            self.assertIn(url, excerpt, 'the excerpt no longer names where it came from')
        # The script must fail when a block is absent, not print a warning and pass.
        self.assertIn('return 1', checker.read_text(encoding='utf-8'))
        self.assertIn('check_quotes.py', self.loop,
                      'LOOP.md no longer tells the reader the quotes are checked')

    def test_the_doc_says_which_published_assertion_it_changed(self):
        """Changing a published assertion silently is the thing to refuse."""
        self.assertIn('tests/test_http_interruption.py', self.loop)
        self.assertRegex(self.loop, 'connect|已发布的断言',
                         'the doc does not say which published assertion moved')

    def test_the_doc_keeps_the_uncertainty_section(self):
        """A slice that reads as settled invites the next reader to stop checking."""
        self.assertIn('不确定', self.loop)

    def test_a_second_reason_is_not_a_replay(self):
        """Decision C, measured rather than asserted."""
        c = self.reading['scenario_c']
        self.assertEqual(2, c['version_after_first_reason'])
        self.assertEqual(2, c['version_after_a_new_reason'])
        self.assertEqual(['revise', 'revise'], c['rows_for_the_two_reasons'])
        self.assertTrue(c['the_new_reason_is_not_a_repeat'])
        self.assertEqual('revise.repeat', c['the_actual_replay_is_marked'])
        self.assertEqual(2, c['version_after_the_replay'])


class TheFrontPagesPointAtTheEvidence(unittest.TestCase):
    """A reader who starts at the front page must be able to find this slice.

    Two things are refused: a page that never mentions the evidence directory,
    and a page that describes the plugin's behaviour without showing a command
    that produces it. Naming a path in prose is not registration -- the same rule
    the knowledge-chain gate applies to the `stories` views.
    """

    PAGES = ('README.md', 'README.zh-CN.md')
    EVIDENCE_LINK = 'docs/evidence/2026-11-27-repeat-safety/'

    def page(self, name):
        return (ROOT / name).read_text(encoding='utf-8')

    def test_each_page_links_the_evidence(self):
        for page in self.PAGES:
            with self.subTest(page=page):
                self.assertIn(self.EVIDENCE_LINK, self.page(page),
                              '%s never points at this slice\'s evidence' % page)

    def test_each_page_names_both_decisions(self):
        """The page claims two decisions changed; both must be on it by name."""
        for page in self.PAGES:
            text = self.page(page)
            with self.subTest(page=page):
                self.assertIn('incomplete_response', text,
                              '%s does not name the cut-response decision' % page)
                self.assertIn('revise.repeat', text,
                              '%s does not name the replay decision' % page)

    def test_each_page_shows_a_command_for_the_replay_claim(self):
        for page in self.PAGES:
            text = self.page(page)
            with self.subTest(page=page):
                self.assertTrue(
                    any('same-words' in line and 'dojo events' in line
                        for line in text.splitlines()),
                    '%s says how a repeat is recorded but shows no command to see it' % page)

    def test_the_printed_block_really_shows_two_rows_and_one_repeat(self):
        """Run the page's own block and read the ledger it produces."""
        import subprocess
        import sys
        for page in self.PAGES:
            with self.subTest(page=page):
                script = self._block(page)
                work = Path(__import__('tempfile').mkdtemp(prefix='repeat-doc-'))
                home = work / 'home'
                home.mkdir()
                env = {k: v for k, v in os.environ.items()
                       if k in ('PATH', 'LANG', 'LC_ALL', 'TZ')}
                env.update({'HOME': str(home), 'TMPDIR': str(work),
                            'PYTHONPATH': str(ROOT), 'PYTHONDONTWRITEBYTECODE': '1'})
                proc = subprocess.run(['sh', '-eu', '-c', script], cwd=str(ROOT),
                                      capture_output=True, text=True, env=env,
                                      stdin=subprocess.DEVNULL, timeout=120)
                self.assertEqual(0, proc.returncode, proc.stderr[-1200:])
                events = json.loads(proc.stdout[proc.stdout.rindex('[\n'):])
                self.assertEqual(['add', 'revise', 'revise', 'revise.repeat'],
                                 [e['event'] for e in events])
                reasons = [e['details'].get('reason') for e in events[1:]]
                self.assertEqual(['\u79fb\u52a8\u7aef\u540c\u4f34\u770b\u4e0d\u89c1\u6d3b\u52a8\u706f',
                                  '\u89e6\u5c4f\u8bfb\u5c4f\u9700\u8981\u4e00\u4e2a\u53ef\u8bfb\u72b6\u6001',
                                  '\u89e6\u5c4f\u8bfb\u5c4f\u9700\u8981\u4e00\u4e2a\u53ef\u8bfb\u72b6\u6001'],
                                 reasons)
                self.assertNotIn('repeat_of', events[2]['details'],
                                 'the new reason was filed as a replay')
                self.assertIn('repeat_of', events[3]['details'])

    def _block(self, page):
        blocks, current = [], None
        for line in self.page(page).splitlines():
            stripped = line.strip()
            if current is None:
                if stripped == '```sh':
                    current = []
                continue
            if stripped == '```':
                blocks.append('\n'.join(current) + '\n')
                current = None
                continue
            current.append(line)
        found = [b for b in blocks if 'same-words' in b]
        self.assertEqual(1, len(found), '%s must print exactly one block for this claim' % page)
        return found[0]


if __name__ == '__main__':
    unittest.main()
