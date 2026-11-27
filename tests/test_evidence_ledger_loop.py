"""The published loop record must be readable through dojo, not only as prose.

`docs/evidence/2026-11-27-guide-standalone-loop/` holds an inquiry about this
repository's own guide: a claim that the guide's standalone sentence did not need
checking, two readings that contradicted it, and the correction. Until this test the
evidence existed only as Markdown, which cannot answer "which version replaced which"
or "what did the comparison record". `build_ledger.py` materializes the same authored
text as an inquiry library, so the entry points a reader already knows can read it.

What this test refuses to accept:

  not visible    the story missing from `stories`, or listed only under --synthetic
                 (it is not roleplay material, and must not be presented as such)
  not versioned  `--proposal` on the original claim not reporting `superseded`, or the
                 version chain not naming the corrected proposal
  not honest     the corrected proposal reporting a status the evidence cannot carry.
                 Repo files are not https materials, so the product says `no_source`;
                 a ledger that reported `checked` here would be claiming independent
                 external support that does not exist.
  not repeatable `build_ledger.py` overwriting an existing library, or accepting a
                 premise quote that is not verbatim in the event it cites.
"""

from __future__ import annotations

import json
import os
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

EVIDENCE = ROOT / 'docs' / 'evidence' / '2026-11-27-guide-standalone-loop'
BUILDER = EVIDENCE / 'build_ledger.py'
SPEC = EVIDENCE / 'ledger.json'


class EvidenceLedger(unittest.TestCase):
    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix='dojo-evidence.'))
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        self.env = {k: os.environ[k] for k in ('PATH', 'LANG', 'TZ') if k in os.environ}
        self.env['PYTHONPATH'] = str(ROOT)
        self.env['PYTHONDONTWRITEBYTECODE'] = '1'
        self.db = self.work / 'evidence.sqlite3'
        self.build()

    def build(self, dest=None, spec=None):
        argv = [sys.executable, '-B', str(BUILDER), str(dest or self.db)]
        if spec is not None:
            argv += ['--spec', str(spec)]
        return subprocess.run(argv, cwd=str(ROOT), capture_output=True, text=True,
                              env=self.env, timeout=180)

    def dojo(self, *args):
        proc = subprocess.run([sys.executable, '-B', '-m', 'dojo', '--db', str(self.db), *args],
                              cwd=str(ROOT), capture_output=True, text=True,
                              env=self.env, timeout=180)
        return proc.returncode, proc.stdout, proc.stderr

    def story(self):
        code, out, err = self.dojo('stories')
        self.assertEqual(0, code, err)
        listed = json.loads(out)
        self.assertEqual(1, len(listed), 'the evidence ledger lists other stories too')
        return listed[0]

    def test_the_story_is_real_material_not_a_synthetic_fixture(self):
        """It is not roleplay, so it must not appear as synthetic."""
        story = self.story()
        self.assertFalse(story['synthetic'],
                         'the evidence story is marked synthetic; --synthetic would be '
                         'the only way to read it, and that label would be a lie')
        self.assertIn('单独复制一段也能跑', story['opening'])
        self.assertEqual(2, story['run_count'], 'the two runs (claim, then correction) moved')
        self.assertEqual('historical_reports_and_model_interpretations_not_certified',
                         story['state'])

    def test_the_original_claim_is_readable_as_replaced(self):
        """The whole point: which version replaced which, read off the ledger."""
        story = self.story()['story']
        code, out, err = self.dojo('stories', story, '--proposal', '3')
        self.assertEqual(0, code, err)
        original = json.loads(out)
        self.assertEqual('superseded', original['state'],
                         'the original claim no longer reads as replaced')
        self.assertIn('只是描述', original['statement'])

    def test_reading_the_old_version_points_at_the_current_one(self):
        """A refusal that names the current version is the reader's next step."""
        story = self.story()['story']
        code, _, err = self.dojo('stories', story, '--comparison', '3')
        self.assertEqual(2, code, 'the replaced comparison was served as if current')
        self.assertIn('已被事件 #10 替代', err)
        self.assertIn('--comparison 10', err)

        code, out, err = self.dojo('stories', story, '--comparison', '10')
        self.assertEqual(0, code, err)
        current = json.loads(out)['comparison']
        self.assertEqual(10, current['conclusion_event'])
        self.assertIn('每次运行自带临时目录', current['statement'])

    def test_the_product_refuses_to_call_repo_files_independent_support(self):
        """Honest boundary, asserted so a later edit cannot quietly upgrade it.

        `_source_url_key` only counts `https://` reads. The evidence cites committed
        files and command output, so the ledger must report the gap rather than a
        confirmation. If this ever reads `checked`, someone has changed either the
        rule or the evidence -- and that change needs its own proof.
        """
        story = self.story()['story']
        code, out, err = self.dojo('stories', story, '--context')
        self.assertEqual(0, code, err)
        gap = json.loads(out)['story_coverage']['missing_independence']
        self.assertEqual('open', gap['items'][0]['comparison_status'])
        self.assertEqual('no_source', gap['items'][0]['rank_class'])
        self.assertEqual('no_independent_support', gap['items'][0]['support_status'])
        self.assertTrue(gap['items'][0]['next_check'],
                        'an open comparison must still name what to check')
        states = {item['state'] for item in gap['items'][0]['have']}
        self.assertIn('record_not_a_source_read', states,
                      'the ledger stopped saying these reads are not source material')

    def test_the_builder_refuses_to_overwrite_and_to_misquote(self):
        again = self.build()
        self.assertNotEqual(0, again.returncode, 'builder silently overwrote a library')
        self.assertIn('已存在', again.stderr)

        spec = json.loads(SPEC.read_text(encoding='utf-8'))
        for event in spec['events']:
            if event['kind'] == 'knowledge_proposal':
                for premise in event['payload']['proposal'].get('premises', []):
                    premise['quote'] = '这句话在事件里并不存在'
                break
        broken = self.work / 'broken.json'
        broken.write_text(json.dumps(spec, ensure_ascii=False), encoding='utf-8')
        result = self.build(self.work / 'broken.sqlite3', spec=broken)
        self.assertNotEqual(0, result.returncode,
                            'builder accepted a premise quote that no event holds')
        self.assertIn('找不到', result.stderr)

    def test_reading_the_evidence_does_not_write_the_library(self):
        story = self.story()['story']
        before = self.db.read_bytes()
        self.dojo('stories')
        self.dojo('stories', story, '--context')
        self.dojo('stories', story, '--comparison', '10')
        self.dojo('stories', story, '--proposal', '3')
        self.assertEqual(before, self.db.read_bytes(),
                         'a read-only evidence view wrote the library')


if __name__ == '__main__':
    unittest.main()
