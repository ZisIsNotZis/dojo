"""Two-way gate between docs/cli-guide.md and the `stories` parser.

There was no doc<->CLI consistency gate before #3246, which is why `--comparison`
could land in the parser (and in `--help`) and never appear in the guide.

Four things this gate refuses to accept:

  direction A  a read-only `stories` view the guide never shows in a runnable example.
               Naming a flag inside a prose sentence ("these four are mutually
               exclusive") is not registration: the reader still has no command to
               copy, and the next step they try still fails. The known gaps are
               declared in UNDOCUMENTED_VIEWS with a reason, so the hole is printed
               rather than silently passing; the gate fails if that list and the
               guide disagree either way -- a stale excuse, or a hidden hole.
  direction B  a `stories` example in the guide that names a flag the parser does
               not accept: a guide that teaches a command which cannot run.
  direction C  a fenced command in the guide that fails when executed. #3261: the
               supervisor could only walk the route because a gitignored
               `*.sqlite3` happened to sit on one machine. Grepping for a flag does
               not notice that, so this gate runs the guide's own `sh` blocks in a
               temp directory -- not a copy of them written here. A test that
               hardcodes the commands it expects keeps passing after the guide
               regresses (measured: three of six arms stayed green), so the text
               under test is the source of truth for what runs.
  direction D  the semantic claims the prose attaches to those lines: #5 `checked`
               with `[3, 4]`, #23 `open`, and the `--revision` library refusing #5
               with a pointer to a readable current version.

Cheap by design: argparse introspection, one text read, two offline builds and a
handful of CLI calls. No model, no network.
"""
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
sys.path.insert(0, str(ROOT))
from dojo.cli import _parser  # noqa: E402
from fixtures import build_comparison_ledger as ledger_fixture  # noqa: E402

GUIDE = Path(os.environ['DOJO_GUIDE']) if os.environ.get('DOJO_GUIDE') else ROOT / 'docs' / 'cli-guide.md'

STORIES_VIEWS = ('--context', '--report', '--proposal', '--comparison')

UNDOCUMENTED_VIEWS = {
    # #3247 registered the last two views, so the excuse list is empty. Keep the
    # shape: a future gap must be declared here, with a reason, not silently pass.
}

STORY = '0f272e5f34244b328df1c80edfdde3df'


import json
import re


def json_documents(text):
    """Every top-level JSON document in `text`, skipping the builder's human lines."""
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


def comparisons(text):
    """`--comparison` rows, keyed by the event the output is about."""
    rows = {}
    for document in json_documents(text):
        if isinstance(document, dict) and isinstance(document.get('comparison'), dict):
            rows[document['comparison']['conclusion_event']] = document['comparison']
    return rows


def contexts(text):
    """`story_coverage.missing_independence` blocks from `--context` runs."""
    return [document['story_coverage']['missing_independence']
            for document in json_documents(text)
            if isinstance(document, dict)
            and isinstance(document.get('story_coverage'), dict)
            and isinstance(document['story_coverage'].get('missing_independence'), dict)]


def listings(text):
    return [document for document in json_documents(text) if isinstance(document, list)]

# A block belongs to this gate only if it points at the ledger the gate builds.
LEDGER_MARKER = 'dojo-ledger'

# The guide writes its sample libraries under this prefix. The gate redirects the
# *prefix*, not a fixed list of names, into a temp dir: #3246 shipped a third path
# (`-walk.sqlite3`) that a two-name table did not cover, so a second run of the guide
# failed on a stale file left by the first one -- a route that only works on a clean
# host is not a route. Any `.sqlite3` the ledger blocks print must live under here;
# test_every_printed_library_path_is_redirectable enforces that.
LEDGER_ROOT = '/tmp/dojo-ledger'


def stories_option_strings():
    parser = _parser()
    action = next(a for a in parser._actions if a.dest == 'command')
    stories = next(p for p in action.choices.values() if p.prog.endswith('stories'))
    return {option for a in stories._actions for option in a.option_strings}


def guide_text():
    return GUIDE.read_text(encoding='utf-8')


def example_commands(text):
    return [line for line in text.splitlines()
            if 'dojo' in line and re.search(r'\bstories\b', line) and not line.lstrip().startswith('#')]


def flags_in(line):
    return set(re.findall(r'(?<![\w-])--[a-z][a-z0-9-]*', line))


def shell_blocks(text):
    """Every ```sh block, line by line -- the guide's actual copyable commands."""
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
        raise AssertionError('unbalanced ```sh fence in the guide')
    return blocks


def guide_scripts(text):
    """The blocks that build and read the ledger this gate can isolate.

    Other `sh` blocks in the guide write to the repository's default library
    (`dojo add --id life-01` and friends), so running them from a test would
    mutate state the test does not own and fail on the second run. They are
    excluded by evidence -- the marker is "this block names the builder or the
    ledger path" -- and EXECUTED_ELSEWHERE records the exclusion rather than
    hiding it.
    """
    return [block for block in shell_blocks(text) if any('python3' in line for line in block)
            and any(LEDGER_MARKER in line for line in block)]


class GuideMatchesParser(unittest.TestCase):
    def test_views_without_a_runnable_example_are_declared(self):
        accepted = stories_option_strings()
        examples = example_commands(guide_text())
        missing = {flag for flag in STORIES_VIEWS
                   if flag in accepted and not any(flag in flags_in(line) for line in examples)}
        self.assertEqual(set(UNDOCUMENTED_VIEWS), missing,
                         'undeclared gap in the guide: %s; stale excuse: %s'
                         % (sorted(missing - set(UNDOCUMENTED_VIEWS)),
                            sorted(set(UNDOCUMENTED_VIEWS) - missing)))

    def test_every_printed_library_path_is_redirectable(self):
        """A route that only runs on a clean host is not a route.

        The gate runs the guide's blocks in a temp dir by rewriting LEDGER_ROOT. A
        block that prints a library somewhere else keeps whatever a previous run
        left behind -- #3246 shipped `/tmp/dojo-ledger-walk.sqlite3` and failed on
        its second run for exactly that reason. So: any `.sqlite3` a ledger block
        names must sit under LEDGER_ROOT, and LEDGER_ROOT must be a prefix of the
        paths actually used. Nothing is executed here; it is a text invariant.
        """
        stray = []
        for block in guide_scripts(guide_text()):
            for line in block:
                for path in re.findall(r'/[^\s"\']*\.sqlite3', line):
                    if not path.startswith(LEDGER_ROOT):
                        stray.append('%s (block names %s)' % (path, line.strip()))
        self.assertEqual([], stray,
                         'the guide prints a library path the gate cannot redirect, '
                         'so the example fails on its second run: %s' % (stray,))

    def test_the_view_this_slice_adopted_keeps_its_example(self):
        self.assertNotIn('--comparison', UNDOCUMENTED_VIEWS)
        examples = example_commands(guide_text())
        self.assertTrue(any('--comparison' in flags_in(line) for line in examples),
                        'guide lost the `--comparison` example')

    def test_every_read_only_view_keeps_a_runnable_example(self):
        """#3247: the last two views were declared gaps, so nothing enforced them.

        A declared gap is honest only while it is true. Once the guide ships an
        example, the excuse must go -- otherwise a later rewrite of the guide could
        silently drop the example and the gate would still call it documented.
        """
        self.assertEqual(set(), set(UNDOCUMENTED_VIEWS),
                         'a view is still declared undocumented: %s' % (sorted(UNDOCUMENTED_VIEWS),))
        examples = example_commands(guide_text())
        for view in STORIES_VIEWS:
            self.assertTrue(any(view in flags_in(line) for line in examples),
                            'guide no longer shows a command for %s' % (view,))

    def test_no_stories_example_teaches_an_unaccepted_flag(self):
        accepted = stories_option_strings()
        stray = sorted({flag for line in example_commands(guide_text()) for flag in flags_in(line)
                        if flag != '--db' and flag not in accepted})
        self.assertEqual([], stray, 'guide shows stories flags the parser rejects: %s' % (stray,))


class GuideRouteRuns(unittest.TestCase):
    """Directions C/D: execute the guide's own blocks, then check what they claim."""

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix='dojo-guide-gate.'))
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        self.env = {k: os.environ[k] for k in ('PATH', 'LANG', 'TZ') if k in os.environ}
        self.env['PYTHONPATH'] = str(ROOT)
        self.env['PYTHONDONTWRITEBYTECODE'] = '1'

    def tidy(self, block):
        """Point the guide's sample paths at this test's temp directory."""
        return '\n'.join(block).replace(LEDGER_ROOT, str(self.work / 'dojo-ledger'))

    def run_block(self, block, label):
        script = self.tidy(block)
        proc = subprocess.run(['sh', '-eu', '-c', script], cwd=str(ROOT), capture_output=True,
                              text=True, env=self.env, timeout=300)
        self.assertEqual(0, proc.returncode,
                         'the guide prints a command that fails (%s):\n%s\n--- stderr ---\n%s'
                         % (label, script, proc.stderr[-1500:]))
        return proc.stdout

    def test_every_documented_command_actually_runs(self):
        """A block that cannot run is a route the reader cannot follow."""
        scripts = guide_scripts(guide_text())
        self.assertTrue(scripts, 'guide has no runnable `sh` block')
        for index, block in enumerate(scripts):
            self.run_block(block, 'sh block %d' % index)

    def test_the_guide_states_the_numbers_its_own_commands_produce(self):
        """Direction D: read the prose claims off the executed output, not off a copy."""
        rows, coverage_blocks = {}, []
        for block in guide_scripts(guide_text()):
            proc = subprocess.run(['sh', '-eu', '-c', self.tidy(block)], cwd=str(ROOT),
                                  capture_output=True, text=True, env=self.env, timeout=300)
            self.assertEqual(0, proc.returncode, proc.stderr[-1200:])
            rows.update(comparisons(proc.stdout))
            coverage_blocks.extend(contexts(proc.stdout))

        self.assertIn(5, rows, 'no documented command reads the checked proposal')
        self.assertEqual('checked', rows[5]['comparison_status'])
        self.assertEqual([[3, 4]], [record['source_events'] for record in rows[5]['comparisons']],
                         'the base library no longer reports the two source receipts')
        self.assertIn(23, rows, 'no documented command reads the open proposal')
        self.assertEqual('open', rows[23]['comparison_status'])
        self.assertTrue(rows[23]['next_check'], '`open` no longer names what to check')

        self.assertTrue(coverage_blocks, 'no documented command reads the context view')
        omitted = coverage_blocks[-1]['omitted_events']
        self.assertEqual([5, 15, 16, 17], omitted, 'the omitted numbers the guide prints moved')
        # The guide claims these numbers are readable by `--comparison`, but shows no
        # command that reads them -- so the gate reads them. A claim about a route is
        # checked by taking the route, not by finding the number in some other output.
        db = self.work / 'dojo-ledger.sqlite3'
        for event in omitted:
            code, out, err = self.cli(db, 'stories', STORY, '--comparison', str(event), '--synthetic')
            self.assertEqual(0, code, 'the guide claims omitted #%d is readable; it refused: %s'
                             % (event, err))
            self.assertEqual('checked', json.loads(out)['comparison']['comparison_status'])

        # "显示的那几条全是 open，省略的四个号全是 checked" is a sentence about this
        # output, so read it off the output. The loop above already took each omitted
        # number through `--comparison` and got `checked`; this covers the shown rows.
        self.assertEqual({'open'}, {item['comparison_status'] for item in coverage_blocks[-1]['items']},
                         'the guide says the shown items are all open')

        # A right output and a stale sentence is still a guide that misleads: a reader
        # compares their own output against the prose, so the numbers must be there.
        prose = guide_text()
        self.assertIn('[5, 15, 16, 17]', prose, 'the guide no longer prints omitted_events verbatim')
        self.assertIn('[3, 4]', prose, 'the guide no longer prints the two source receipts')

    def test_report_and_proposal_state_the_claims_the_prose_makes(self):
        """#3247: the prose around `--report`/`--proposal` has to be read off output.

        Four claims, each observable: the report keeps its epistemic label, the
        quoted premise of #5 (read off `knowledge`) appears verbatim in the report's text,
        `report_review` is empty in this library (and the prose says so rather
        than implying a clean bill), and a replaced proposal still lists as
        `superseded` instead of vanishing.
        """
        db = self.work / 'read.sqlite3'
        ledger_fixture.build(db)
        code, out, err = self.cli(db, 'stories', STORY, '--report', '2', '--synthetic')
        self.assertEqual(0, code, 'the guide shows `--report 2`; it refused: %s' % err)
        report = json.loads(out)
        self.assertEqual('user', report['kind'])
        self.assertEqual('user_report_not_independently_verified', report['epistemic_status'])
        self.assertEqual('same_story', report['story_scope'])

        code, out, err = self.cli(db, 'stories', STORY, '--proposal', '5', '--synthetic')
        self.assertEqual(0, code, 'the guide shows `--proposal 5`; it refused: %s' % err)
        proposal = json.loads(out)
        self.assertEqual('current_interpretation', proposal['state'])
        self.assertEqual([], proposal['report_review'],
                         'the guide says this library shows no review signals; it now shows %r'
                         % (proposal['report_review'],))

        # The guide's load-bearing sentence: proposal #5's premise quote is the same
        # text `--report 2` prints. If a fixture edit broke that, the pointer would
        # send the reader to a report that does not contain the quoted words.
        # The supervisor's objection on #3247: `--proposal` carries no `premises` field,
        # so a guide pointing there for the quote sent the reader to a dead end. The
        # route is `knowledge` -> `--report`, and the gate takes that route.
        self.assertNotIn('premises', proposal,
                         '--proposal now exposes premises; the guide instruction is stale')
        self.assertIn('knowledge', guide_text(),
                      'the guide must name the view that actually carries premises')

        code, out, err = self.cli(db, 'knowledge', '--synthetic')
        self.assertEqual(0, code, err)
        listing = json.loads(out)
        entry = next(row for row in listing if row['event'] == 5)
        quote = '希望后来者能看见原始报告'
        self.assertEqual({'event': 2, 'quote': quote, 'role': 'assumption'},
                         entry['proposal']['premises'][0],
                         'the guide quotes the first premise of #5; it changed')
        self.assertIn(quote, report['text'],
                      'the quoted premise is not verbatim in the report the guide points at')
        spec = json.loads((ROOT / 'fixtures' / 'comparison-ledger.json').read_text(encoding='utf-8'))
        premises = next(event['payload']['proposal']['premises']
                        for event in spec['events']
                        if event['kind'] == 'knowledge_proposal' and event['seq'] == 5)
        self.assertIn({'event': 2, 'quote': quote, 'role': 'assumption'}, premises,
                      'proposal #5 no longer quotes report #2 with that text')
        self.assertIn(quote, guide_text(), 'the guide no longer prints the quote it points at')

        # A replaced proposal is listed, not hidden: the prose promises `superseded`.
        revised = self.work / 'revised-state.sqlite3'
        ledger_fixture.build(revised, successor=True)
        code, out, err = self.cli(revised, 'stories', STORY, '--proposal', '5', '--synthetic')
        self.assertEqual(0, code, err)
        self.assertEqual('superseded', json.loads(out)['state'],
                         'the guide says a replaced proposal still lists as superseded')
        self.assertIn('superseded', guide_text())

        # The prose says the empty block is NOT a clean bill. Measured blind on arms
        # F and G (#3247): flipping that sentence, or dropping the exclusivity claim,
        # kept the gate green because neither phrase was asserted -- the word
        # '互斥' also occurs in the older `--comparison` paragraph, so a loose
        # `assertIn` checked a different sentence.
        prose = guide_text()
        self.assertIn('不是「核过没问题」', prose,
                      'the guide no longer says an empty report_review is not a clean bill')
        self.assertNotIn('就是「核过没问题」', prose,
                         'the guide now reads an empty report_review as a clean bill')
        self.assertIn('四个视图互斥', prose,
                      'the guide no longer states the four read-only views are exclusive')

    def test_the_four_read_only_views_are_mutually_exclusive(self):
        """The prose says a second view is refused by argument parsing, not by data."""
        db = self.work / 'exclusive.sqlite3'
        ledger_fixture.build(db)
        for flags in (('--report', '2', '--proposal', '5'),
                      ('--proposal', '5', '--context')):
            code, _, err = self.cli(db, 'stories', STORY, *flags, '--synthetic')
            self.assertEqual(2, code, '%r was not refused' % (flags,))
            self.assertNotIn('没有可见', err,
                             'the refusal for %r came from the data layer, but the guide '
                             'tells the reader it is an argument-usage error' % (flags,))
        self.assertIn('互斥', guide_text())

    def test_a_replaced_version_points_at_the_current_one(self):
        """The `--revision` recipe must produce a refusal that names a readable version."""
        revised = [block for block in guide_scripts(guide_text())
                   if any('--revision' in line for line in block)
                   and any('--comparison 5' in line for line in block)]
        self.assertTrue(revised, 'guide no longer shows how to reach the replaced state')
        block = revised[0]
        script = self.tidy(block)
        proc = subprocess.run(['sh', '-c', script], cwd=str(ROOT), capture_output=True,
                              text=True, env=self.env, timeout=300)
        # The block is expected to *end* in a refusal; that refusal is the lesson.
        pointer = re.search(r'--comparison (\d+)', proc.stderr + proc.stdout)
        self.assertIsNotNone(pointer,
                             'the replaced-version recipe no longer names a current version: %r'
                             % (proc.stderr[-800:] + proc.stdout[-800:]))
        code, out, err = self.cli(self.work / 'dojo-ledger-revised.sqlite3', 'stories', STORY,
                                  '--comparison', pointer.group(1), '--synthetic')
        self.assertEqual(0, code, 'the named current version is not readable: %s' % err)
        document = json.loads(out)['comparison']
        self.assertEqual(int(pointer.group(1)), document['conclusion_event'])
        self.assertEqual('open', document['comparison_status'],
                         'the guide says the pointed-at version is open (no comparison yet)')

        # Measured blind on arm I: the block also prints a *follow-up* command telling
        # the reader which version to open next. Reading only the refusal left that
        # command unchecked, so a guide that says "open #27" in one line and "open #15"
        # in the next still passed. The two numbers must be the same number.
        followups = [int(number) for line in block
                     for number in re.findall(r'--comparison (\d+)', line)]
        self.assertTrue(followups, 'the recipe names no version to open next')
        self.assertEqual([int(pointer.group(1))], followups[-1:],
                         'the guide tells the reader to open #%d but the refusal names #%s'
                         % (followups[-1], pointer.group(1)))

    def test_omitted_events_are_readable_by_the_entry_the_guide_points_at(self):
        db = self.work / 'omitted.sqlite3'
        ledger_fixture.build(db)
        code, out, err = self.cli(db, 'stories', STORY, '--context', '--synthetic')
        self.assertEqual(0, code, err)
        missing = json.loads(out)['story_coverage']['missing_independence']
        self.assertEqual([5, 15, 16, 17], missing['omitted_events'])
        for event in missing['omitted_events']:
            code, out, err = self.cli(db, 'stories', STORY, '--comparison', str(event), '--synthetic')
            self.assertEqual(0, code, 'omitted event #%d refused: %s' % (event, err))

    def test_the_build_refuses_to_overwrite(self):
        db = self.work / 'once.sqlite3'
        argv = [sys.executable, '-B', str(ROOT / 'fixtures' / 'build_comparison_ledger.py'), str(db)]
        self.assertEqual(0, subprocess.run(argv, cwd=str(ROOT), env=self.env, timeout=180).returncode)
        again = subprocess.run(argv, cwd=str(ROOT), capture_output=True, text=True, env=self.env, timeout=180)
        self.assertNotEqual(0, again.returncode, 'builder silently overwrote an existing library')

    def test_the_documented_reads_do_not_write_the_library(self):
        db = self.work / 'readonly.sqlite3'
        ledger_fixture.build(db, successor=True)
        before = db.read_bytes()
        self.cli(db, 'stories', STORY, '--context', '--synthetic')
        self.cli(db, 'stories', STORY, '--comparison', '5', '--synthetic')
        self.cli(db, 'stories', '--synthetic')
        self.assertEqual(before, db.read_bytes())

    def cli(self, db, *args):
        proc = subprocess.run([sys.executable, '-B', '-m', 'dojo', '--db', str(db), *args],
                              cwd=str(ROOT), capture_output=True, text=True,
                              env=self.env, timeout=180)
        return proc.returncode, proc.stdout, proc.stderr


class GuideNumbersMatchTheBuild(unittest.TestCase):
    """The `.sqlite3` is gitignored: a guide that points at one is unwalkable."""

    def test_the_guide_ships_a_command_instead_of_a_fixture_file(self):
        text = guide_text()
        self.assertIn('fixtures/build_comparison_ledger.py', text)
        self.assertNotIn('fixtures/comparison-ledger.sqlite3', text,
                         'guide points at a file the ignore rule keeps out of the checkout')


if __name__ == '__main__':
    unittest.main()
