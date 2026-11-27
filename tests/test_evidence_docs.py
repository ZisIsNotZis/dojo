"""The evidence docs' red-arm recipes must be executable, and must not lie.

Two defects were found in these recipes by a reviewer, both already fixed once:

  1. `git show 6aac311:docs/cli-guide.md > docs/cli-guide.md` then `git checkout --`.
     That overwrites whatever guide the reader is editing, and two readers running
     it at once destroy each other's work.
  2. `git archive 6aac311 | tar -x -C "$RED"` then `unittest tests.test_doc_cli_flags`.
     That runs the *old gate* against the *old text* -- which was green on 6aac311,
     so it proves nothing about whether the new gate would catch the old text.

This test refuses to accept either shape again, and executes the corrected recipe:

  shape     no doc under docs/evidence may redirect into a tracked file
            (`> docs/...`) or restore one with `git checkout --`.
  runs      the corrected red arm, run for real: old text + new gate must fail the
            four arms the doc names; old text + old gate must be green, which is the
            gap the doc is describing.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


def _repo_root():
    if os.environ.get('DOJO_ROOT'):
        return Path(os.environ['DOJO_ROOT']).resolve()
    for parent in Path(__file__).resolve().parents:
        if (parent / 'dojo' / 'cli.py').is_file() and (parent / 'docs' / 'cli-guide.md').is_file():
            return parent
    raise RuntimeError('cannot locate the dojo repository root')


ROOT = _repo_root()
EVIDENCE = ROOT / 'docs' / 'evidence' / '2026-11-27-guide-standalone-loop'
BASELINE = '6aac311'

# Exactly the four arms the doc says fail. Named, not counted, so a doc that says
# "4 failures" while the failures moved is caught.
# A line that forbids the command may quote it. Recognised so the gate can
# tell a warning apart from a recipe -- otherwise the doc cannot warn at all.
PROHIBITION = re.compile(r'不要|别去|切勿|don\'t|do not|never')

EXPECTED_FAILURES = {
    'test_no_ledger_block_names_a_fixed_library_path',
    'test_every_documented_command_actually_runs',
    'test_every_ledger_block_runs_alone_and_on_a_second_sitting',
    'test_the_guide_states_the_numbers_its_own_commands_produce',
}


def is_git_checkout(path: Path) -> bool:
    return subprocess.run(['git', '-C', str(path), 'rev-parse', '--git-dir'],
                          capture_output=True).returncode == 0


class DocsDoNotOverwriteTheReadersTree(unittest.TestCase):
    def test_no_doc_redirects_into_a_tracked_path(self):
        """A recipe must not write into the checkout it is documenting."""
        offenders = []
        for page in sorted(EVIDENCE.glob('*.md')):
            for number, line in enumerate(page.read_text(encoding='utf-8').splitlines(), 1):
                if line.lstrip().startswith('#'):
                    continue
                # A doc that *warns against* the command has to be able to quote it.
                # A warning says 不要 / 别 / don't before the command; a recipe does not.
                if PROHIBITION.search(line):
                    continue
                # `> docs/cli-guide.md` or `> tests/...`: writing over a tracked file.
                if re.search(r'>\s*(docs|tests|dojo|fixtures|scripts)/', line):
                    offenders.append('%s:%d %s' % (page.name, number, line.strip()))
                # `git checkout -- docs/...`: restoring someone else's edit.
                if re.search(r'git\s+checkout\s+(--\s+)?(docs|tests|dojo|fixtures|scripts)/',
                             line):
                    offenders.append('%s:%d %s' % (page.name, number, line.strip()))
        self.assertEqual([], offenders,
                         'a recipe writes into or restores a tracked file, so following it '
                         'destroys what the reader is editing: %s' % (offenders,))

    def test_the_red_arm_puts_the_new_gate_against_the_old_text(self):
        """The naive 'extract 6aac311 and run unittest' recipe proves nothing.

        It runs the old gate, which was green on the old text. The doc has to copy
        the new gate in; this asserts the sentence is there, because that sentence is
        the whole difference between a real red arm and a reassuring one.
        """
        for page in ('LOOP.md', 'RERUN.md'):
            text = (EVIDENCE / page).read_text(encoding='utf-8')
            self.assertIn('tests/test_doc_cli_flags.py', text,
                          '%s no longer copies the new gate into the throwaway extract'
                          % page)
            self.assertRegex(text, r'新门[^\n]*旧正文|new gate[^\n]*old text',
                             '%s does not say which gate meets which text, so a reader '
                             'cannot tell a real red arm from a reassuring one' % page)


class TheCorrectedRedArmActuallyBites(unittest.TestCase):
    """Execute the recipe instead of trusting it."""

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix='dojo-docs-gate.'))
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)

    def extract(self) -> Path:
        toplevel = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--show-toplevel"],
                                  capture_output=True, text=True).stdout.strip()
        if not toplevel or Path(toplevel).resolve() != ROOT:
            # ROOT is not itself the repository root -- e.g. an extract unpacked inside
            # another checkout. `git archive` there archives the wrong tree, so this is
            # a skip, not a failure of the code being tested.
            self.skipTest("ROOT is not a git checkout (toplevel=%r)" % toplevel)
            self.skipTest('not a git checkout, so git archive cannot extract the baseline')
        target = self.work / 'baseline'
        target.mkdir()
        archive = subprocess.run(['git', '-C', str(ROOT), 'archive', BASELINE],
                                 capture_output=True)
        if archive.returncode != 0:
            self.skipTest('baseline commit %s is not available here' % BASELINE)
        subprocess.run(['tar', '-x', '-C', str(target)], input=archive.stdout, check=True)
        # Guard the silent-failure mode met while writing this: an empty extract makes
        # every later assertion vacuous.
        self.assertTrue((target / 'tests' / 'test_doc_cli_flags.py').is_file(),
                        'the extract has no tests/, so the recipe would pass on nothing')
        return target

    def run_gate(self, checkout: Path) -> tuple[int, str]:
        env = {k: os.environ[k] for k in ('PATH', 'LANG', 'TZ', 'TMPDIR') if k in os.environ}
        env['PYTHONPATH'] = str(checkout)
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        env.pop('DOJO_ROOT', None)
        proc = subprocess.run([sys.executable, '-m', 'unittest', 'tests.test_doc_cli_flags'],
                              cwd=str(checkout), capture_output=True, text=True,
                              env=env, timeout=600)
        return proc.returncode, proc.stderr

    def test_new_gate_with_old_text_fails_exactly_the_named_arms(self):
        checkout = self.extract()
        shutil.copyfile(ROOT / 'tests' / 'test_doc_cli_flags.py',
                        checkout / 'tests' / 'test_doc_cli_flags.py')
        code, err = self.run_gate(checkout)
        self.assertNotEqual(0, code, 'the new gate passed on the old guide, so it does '
                                     'not catch the defect it was written for')
        failed = set(re.findall(r'^FAIL: (\w+)', err, re.M))
        self.assertEqual(EXPECTED_FAILURES, failed,
                         'the doc names four failing arms; this run failed %s' % (sorted(failed),))

    def test_old_gate_with_old_text_is_green_which_is_the_gap(self):
        checkout = self.extract()
        code, err = self.run_gate(checkout)
        self.assertEqual(0, code,
                         'the baseline gate is no longer green on the baseline text; the '
                         'doc\'s account of why the gap was invisible needs re-checking\n%s'
                         % err[-1200:])


if __name__ == '__main__':
    unittest.main()
