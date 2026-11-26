"""Gate between the two README front pages and the `stories` read-only views.

#3247 closed the guide↔CLI gap; the front page was still silent. A reader who
starts at README never learns the knowledge-chain entries exist, and a reader
who starts at README.zh-CN.md must not get a different set of claims than the
English page. Three things this gate refuses to accept:

  block absent   a README that never shows a command for one of the four
                 read-only views. Naming a flag in prose is not registration.
  block broken   the README's own `sh` block failing when executed. It is run
                 here from the text, in its own temp dir -- not from a copy
                 written into the test, so a regress in the README is caught.
  prose drifting the numbers the prose quotes (`checked` with `[3, 4]`,
                 `[5, 15, 16, 17]`, the `--revision` refusal naming #27) read
                 off the executed output, in *both* languages.

Why a temp dir per page: both pages name the same library
(`/tmp/dojo-ledger-front.sqlite3`) and the builder refuses to clobber. Running
both blocks into one directory would fail on the second page for a reason the
reader's machine would not have -- the #3247 harness bug, caught before it
could produce a verdict. The two-language parity check is separate from that:
it compares registered flags and quoted numbers, not file bytes.
"""
import io
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
        if (parent / 'dojo' / 'cli.py').is_file() and (parent / 'README.md').is_file():
            return parent
    raise RuntimeError('cannot locate the dojo repository root')


ROOT = _repo_root()
sys.path.insert(0, str(ROOT))
from dojo.cli import _parser  # noqa: E402
from fixtures import build_comparison_ledger as ledger_fixture  # noqa: E402

PAGES = ('README.md', 'README.zh-CN.md')
VIEWS = ('--context', '--report', '--proposal', '--comparison')
# The block is identified by what it does, not by a fixed path: a reader-facing
# example must mint its own directory each run, so the page owns no shared name
# for this gate to key on (#3286: a second run must not clear the first).
BUILDER = 'fixtures/build_comparison_ledger.py'
STORY = '0f272e5f34244b328df1c80edfdde3df'


def page_text(name):
    return (ROOT / name).read_text(encoding='utf-8')


def shell_blocks(text):
    blocks, current = [], None
    for line in text.splitlines():
        stripped = line.strip()
        if current is None:
            if stripped == '```sh':
                current = []
            continue
        if stripped == '```':
            blocks.append(current)
            current = None
            continue
        current.append(line)
    if current is not None:
        raise AssertionError('unbalanced ```sh fence in a README')
    return blocks


def view_blocks(name):
    """The README block that builds and reads the knowledge chain."""
    return [block for block in shell_blocks(page_text(name))
            if any(BUILDER in line for line in block)
            and any('stories' in line for line in block)]


def example_commands(text):
    return [line for line in text.splitlines()
            if 'dojo' in line and re.search(r'\bstories\b', line)
            and not line.lstrip().startswith('#')]


def dojo_commands(text):
    """Any copyable `python3 -m dojo ...` line, not only the `stories` views."""
    return [line for line in text.splitlines()
            if re.search(r'python3? -m dojo', line) and not line.lstrip().startswith('#')]


def flags_in(line):
    return set(re.findall(r'(?<![\w-])--[a-z][a-z0-9-]*', line))


def stories_option_strings():
    parser = _parser()
    action = next(a for a in parser._actions if a.dest == 'command')
    stories = next(p for p in action.choices.values() if p.prog.endswith('stories'))
    return {option for a in stories._actions for option in a.option_strings}


def json_documents(text):
    decoder, index, found = json.JSONDecoder(), 0, []
    while True:
        match = re.search(r'[{[]', text[index:])
        if match is None:
            return found
        start = index + match.start()
        try:
            value, end = decoder.raw_decode(text, start)
        except ValueError:
            index = start + 1
            continue
        found.append(value)
        index = end


def by_key(text, outer, inner):
    """Rows of the form {outer: {inner: ...}} keyed by `inner`."""
    rows = {}
    for document in json_documents(text):
        if isinstance(document, dict) and isinstance(document.get(outer), dict):
            rows[document[outer].get(inner)] = document[outer]
    return rows


class FrontPageRegistersTheViews(unittest.TestCase):
    def test_each_page_shows_a_command_for_all_four_views(self):
        for page in PAGES:
            blocks = view_blocks(page)
            self.assertTrue(blocks, '%s never builds the knowledge-chain library' % page)
            examples = example_commands(page_text(page))
            for view in VIEWS:
                self.assertTrue(any(view in flags_in(line) for line in examples),
                                '%s does not register %s' % (page, view))

    def test_no_page_teaches_a_flag_the_parser_rejects(self):
        accepted = stories_option_strings()
        for page in PAGES:
            stray = sorted({flag for line in example_commands(page_text(page))
                            for flag in flags_in(line)
                            if flag != '--db' and flag not in accepted})
            self.assertEqual([], stray, '%s shows stories flags the parser rejects: %s'
                             % (page, stray))

    def test_the_two_pages_register_the_same_views(self):
        """A Chinese page that drifts is a reader-facing gap, not a translation choice."""
        registered = {}
        for page in PAGES:
            examples = example_commands(page_text(page))
            registered[page] = {view for view in VIEWS
                                if any(view in flags_in(line) for line in examples)}
        self.assertEqual(set(VIEWS), registered[PAGES[0]])
        self.assertEqual(registered[PAGES[0]], registered[PAGES[1]],
                         'the two front pages register different views: %s' % (registered,))


class FrontPageRouteRuns(unittest.TestCase):
    """Each page's own block, executed in its own temp dir, then read for its claims."""

    def setUp(self):
        self.env = {k: os.environ[k] for k in ('PATH', 'LANG', 'TZ') if k in os.environ}
        self.env['PYTHONPATH'] = str(ROOT)
        self.env['PYTHONDONTWRITEBYTECODE'] = '1'
        self.work = Path(tempfile.mkdtemp(prefix='dojo-readme-gate.'))
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)

    def page_env(self, page):
        """Own TMPDIR per page, so the block's `mktemp -d` stays inside this test."""
        tmp = self.work / ('tmp-%s' % page.replace('.', '-'))
        tmp.mkdir(exist_ok=True)
        env = dict(self.env)
        env['TMPDIR'] = str(tmp)
        return env

    def run_block(self, page, env):
        """Run the page's block exactly as printed. No rewriting: a page that only
        works after the gate substitutes its own paths is not a page a reader can run."""
        script = '\n'.join(view_blocks(page)[0])
        return subprocess.run(['sh', '-eu', '-c', script], cwd=str(ROOT), capture_output=True,
                              text=True, env=env, timeout=300)

    def run_page(self, page):
        proc = self.run_block(page, self.page_env(page))
        script = '\n'.join(view_blocks(page)[0])
        self.assertEqual(0, proc.returncode,
                         '%s prints a block that fails:\n%s\n--- stderr ---\n%s'
                         % (page, script, proc.stderr[-1500:]))
        return proc.stdout

    def test_both_front_pages_run(self):
        for page in PAGES:
            with self.subTest(page=page):
                self.run_page(page)

    def test_the_numbers_the_prose_quotes_come_off_the_run(self):
        for page in PAGES:
            with self.subTest(page=page):
                text = self.run_page(page)
                comparisons = by_key(text, 'comparison', 'conclusion_event')
                self.assertIn(5, comparisons, '%s: no command reads proposal #5' % page)
                self.assertEqual('checked', comparisons[5]['comparison_status'])
                self.assertEqual([[3, 4]], [record['source_events']
                                            for record in comparisons[5]['comparisons']],
                                 '%s: the base library no longer reports [3, 4]' % page)

                contexts = [document['story_coverage']['missing_independence']
                            for document in json_documents(text)
                            if isinstance(document, dict)
                            and isinstance(document.get('story_coverage'), dict)]
                self.assertTrue(contexts, '%s: no command reads the context view' % page)
                self.assertEqual([5, 15, 16, 17], contexts[-1]['omitted_events'],
                                 '%s: the omitted numbers moved' % page)
                # Both pages say each omitted number "is readable as-is by --comparison".
                # A claim about a route is checked by taking it; the guide's gate does
                # this for the guide, and the front page needs the same evidence.
                db = self.work / ('omitted-%s.sqlite3' % page.replace('.', '-'))
                ledger_fixture.build(db)
                for event in contexts[-1]['omitted_events']:
                    code, out, err = self.cli(db, 'stories', STORY, '--comparison',
                                              str(event), '--synthetic')
                    self.assertEqual(0, code, '%s says #%d is readable by --comparison; '
                                     'it refused: %s' % (page, event, err))
                    self.assertEqual('checked',
                                     json.loads(out)['comparison']['comparison_status'])

                documents = [document for document in json_documents(text)
                             if isinstance(document, dict)]
                report = next((d for d in documents if d.get('epistemic_status')), None)
                self.assertIsNotNone(report, '%s: no command reads a user report' % page)
                self.assertEqual('user_report_not_independently_verified',
                                 report['epistemic_status'])
                proposal = next((d for d in documents if 'report_review' in d), None)
                self.assertIsNotNone(proposal, '%s: no command reads a proposal' % page)
                self.assertEqual([], proposal['report_review'])
                self.assertEqual('current_interpretation', proposal['state'])

                prose = page_text(page)
                # Arm M (#3248) survived: the route was taken, but nothing asserted the
                # sentence promising it. Replacing "each is readable as-is by
                # `--comparison`" with "the four are read alike" kept the gate green,
                # because a route with no sentence still passes. Claim and route are
                # two facts; the page needs both, each in its own language.
                promise = {'README.md': 'each is readable as-is by',
                           'README.zh-CN.md': '每个都能直接拿去'}[page]
                self.assertIn(promise, prose,
                              '%s no longer promises the omitted numbers are readable' % page)
                for needle in ('[5, 15, 16, 17]', '[3, 4]',
                               'user_report_not_independently_verified'):
                    self.assertIn(needle, prose, '%s no longer prints %s verbatim'
                                  % (page, needle))
                # Both pages must refuse the reading "empty means verified", each in its
                # own language. My first version asserted the English sentence against
                # both pages and the control run went red (#3248) -- a gate that fails
                # on unchanged text has no verdict to give, so the pairs are per page.
                refusal = {'README.md': ('not a clean bill', 'is a clean bill'),
                           'README.zh-CN.md': ('不是「核过没问题」', '核过没问题」')}[page]
                self.assertIn(refusal[0], prose,
                              '%s no longer refuses to read an empty report_review '
                              'as a clean bill' % page)
                self.assertNotIn(refusal[1], prose.replace(refusal[0], ''),
                                 '%s now reads an empty report_review as a clean bill' % page)

    def test_the_prose_revision_claim_is_a_route_that_runs(self):
        """The prose says `--revision` shows a refusal naming #27. Take that route."""
        for page in PAGES:
            with self.subTest(page=page):
                prose = page_text(page)
                self.assertIn('--revision', prose, '%s no longer mentions --revision' % page)
                self.assertIn('#27', prose, '%s no longer names the current version' % page)
                db = self.work / ('revision-%s.sqlite3' % page.replace('.', '-'))
                ledger_fixture.build(db, successor=True)
                proc = subprocess.run(
                    [sys.executable, '-B', '-m', 'dojo', '--db', str(db), 'stories', STORY,
                     '--comparison', '5', '--synthetic'],
                    cwd=str(ROOT), capture_output=True, text=True, env=self.env, timeout=180)
                self.assertEqual(2, proc.returncode,
                                 '%s says the replaced state refuses; it returned %d'
                                 % (page, proc.returncode))
                self.assertIn('27', proc.stderr,
                              '%s says the refusal names #27; it said: %r'
                              % (page, proc.stderr[-800:]))

    def test_the_exclusivity_claim_is_written_and_enforced(self):
        """Both pages say "one flag per call". Arm J (#3248) survived that sentence.

        The mutant replaced 四个视图互斥 with 四个视图各读各的 on the Chinese page and
        the gate stayed green: the English paragraph was checked only by being
        present, and the Chinese one not at all. A claim about how the parser
        behaves is checked by handing it two views, not by finding a phrase.
        """
        claims = {'README.md': 'mutually exclusive', 'README.zh-CN.md': '四个视图互斥'}
        db = self.work / 'exclusive.sqlite3'
        ledger_fixture.build(db)
        for page, claim in claims.items():
            with self.subTest(page=page):
                self.assertIn(claim, page_text(page),
                              '%s no longer says the four views exclude each other' % page)
                for pair in (('--report', '2', '--proposal', '5'),
                             ('--comparison', '5', '--context')):
                    code, _, err = self.cli(db, 'stories', STORY, *pair, '--synthetic')
                    self.assertEqual(2, code, '%s: %r was not refused' % (page, pair))
                    self.assertNotIn('没有可见', err,
                                     '%s says the refusal is an argument-usage error, '
                                     'but %r was refused by the data layer' % (page, pair))

    def test_the_unaccepted_draft_contract_matches_the_prose(self):
        """Both pages now say an unaccepted version is *kept*, not discarded.

        #3248: the pages said "writes only on agreement", which a reader takes as
        "nothing is left behind before agreement". The code has kept an
        `unaccepted_draft` since r110 (`tests/test_discuss.py`:
        `assert_only_unconfirmed_draft`), so the sentence was the defect, not the
        behaviour. This takes the route the prose now describes: run a discussion
        that ends on a stance nobody accepted, then read the library with `list`.
        """
        statements = {'README.md': ('kept as an `unaccepted_draft`', 'dojo list'),
                      'README.zh-CN.md': ('保留为 `unaccepted_draft` 草稿', 'dojo list')}
        for page, (claim, readback) in statements.items():
            with self.subTest(page=page):
                text = page_text(page)
                self.assertIn(claim, text,
                              '%s no longer says an unaccepted version is kept' % page)
                # Arm P (#3248) survived: the gate proved `list` shows the draft by
                # calling it itself, while the page could stop showing that command
                # entirely. The reader needs the command, not only the fact.
                self.assertTrue(any(readback in line for line in dojo_commands(text)),
                                '%s says the draft is kept but shows no `dojo list` command'
                                % page)

        from dojo.discuss import run_discuss
        from dojo.storage import Store

        class FakeClient:
            def __init__(self, responses):
                self.responses = list(responses)
                self.messages = []

            def complete(self, messages):
                self.messages.append(messages)
                return self.responses.pop(0)

        conclusion = {'statement': '开始前把任务缩成一个可执行的第一步，可能降低启动阻力。',
                      'kind': 'application', 'scope': ['知道目标但因任务显得庞大而迟迟未开始时'],
                      'premises': ['用户知道自己要做什么'],
                      'alternatives': ['疲劳或不认同目标可能是主要原因'],
                      'contradictions': ['第一步仍不清楚时，缩小任务未必有帮助'],
                      'unknowns': ['这种做法对该用户是否有效尚未验证']}

        def read_lines(lines):
            iterator = iter(lines)

            def read_line(_prompt):
                try:
                    return next(iterator)
                except StopIteration:
                    raise EOFError
            return read_line

        db = self.work / 'draft.sqlite3'
        store = Store(str(db))
        try:
            code = run_discuss(
                store, client=FakeClient([
                    {'answer': '先把这件事说清楚。', 'candidate': conclusion, 'user_stance': 'neutral'},
                    {'answer': '关键判断是，启动困难不一定来自任务规模。',
                     'candidate': conclusion, 'user_stance': 'neutral'},
                ]), read_line=read_lines(['我有个想法', '不确定，我没有更多了']),
                output=io.StringIO())
        finally:
            store.close()
        self.assertEqual(0, code)

        code, out, err = self.cli(db, 'list')
        self.assertEqual(0, code, err)
        rows = json.loads(out)
        self.assertEqual(1, len(rows), 'expected exactly one kept draft, got %r' % (rows,))
        self.assertIs(True, rows[0].get('unaccepted_draft'),
                      'the prose says the kept version is flagged; list shows %r' % (rows[0],))
        # `list` rows do not carry sources; the source type is on the record.
        code, out, err = self.cli(db, 'show', rows[0]['id'])
        self.assertEqual(0, code, err)
        sources = json.loads(out)['candidate']['sources']
        self.assertEqual(['model_generated'], [source['type'] for source in sources])
        self.assertEqual(['unverified'], [source['verification'] for source in sources])

    def cli(self, db, *args):
        proc = subprocess.run([sys.executable, '-B', '-m', 'dojo', '--db', str(db), *args],
                              cwd=str(ROOT), capture_output=True, text=True,
                              env=self.env, timeout=180)
        return proc.returncode, proc.stdout, proc.stderr


if __name__ == '__main__':
    unittest.main()
