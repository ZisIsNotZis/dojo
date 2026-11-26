"""DAO time precision and basis must survive both render paths."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


life = load_module('dao_life', 'scripts/dao_life.py')
seed = load_module('seed_dao', 'fixtures/seed_dao.py')
DAO_ID = 'ring-d-1'
TIMED = '2187-03-07T13:11:00Z'
DATE_ONLY = '2187-03-07'
BASIS = '按两张虚构交接签的日期与序号排序，不凭回忆。'


class TimeBasisOnScreenTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / 'authored-fixtures'
        seed.build(self.root)
        self.library = self.root / seed.A
        self.vocabulary = json.loads((self.root / 'vocabulary.json').read_text(encoding='utf-8'))

    def add_observation(self, at, kind='later_session'):
        path = self.library / 'observations.json'
        data = json.loads(path.read_text(encoding='utf-8'))
        data['observations'].append({
            'id': 'fictional-follow-up',
            'dao': DAO_ID,
            'kind': kind,
            'at': at,
            'at_basis': BASIS,
            'matched': True,
            'prediction': '合成交接时来人先看到外侧紫签。',
            'applied_in': '虚构展台第二轮交接',
            'result': '来人先看到了外侧紫签',
            'could_have_gone_otherwise': '若封贴盖住挂位则不会挂签',
        })
        seed.put(path, data)

    def render(self):
        data = life.load_library(self.library)
        receipts = life.run_bench(data, seed.AT, self.vocabulary)
        return life.render(data, receipts, seed.AT, {}, self.vocabulary), receipts[DAO_ID]['field']

    def check_output(self):
        proc = subprocess.run(
            [sys.executable, '-B', '-X', 'utf8', str(ROOT / 'scripts' / 'dao_life.py'),
             str(self.library), '--check', '--at', seed.AT],
            cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=20)
        self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
        return proc.stdout

    def test_timed_observation_names_the_coarse_case_and_preserves_its_basis(self):
        self.add_observation(TIMED)
        page, field = self.render()
        self.assertEqual('date_convention', field['time_basis'])
        lines = [line for line in page.splitlines() if line.startswith('时间依据')]
        line, = lines
        self.assertIn(BASIS, line)
        self.assertIn('弱在案例那一侧', line)
        self.assertIn(f'观察 {TIMED} 带时区', line)
        self.assertNotIn('日期不含案例或观察的精确时刻', page)
        out = self.check_output()
        self.assertIn('落地依据（date_convention）', out)
        self.assertIn(BASIS, out)
        self.assertIn('弱在案例那一侧', out)

    def test_timed_self_check_names_its_moment(self):
        self.add_observation(TIMED, 'agent_self')
        page, field = self.render()
        self.assertEqual(TIMED, field['observation']['at'])
        self.assertIn(TIMED, page)

    def test_date_only_observation_names_both_coarse_sides(self):
        self.add_observation(DATE_ONLY)
        page, field = self.render()
        self.assertEqual(DATE_ONLY, field['observation']['at'])
        for rendered in (page, self.check_output()):
            self.assertIn('两侧都粗', rendered)
            self.assertIn(f'观察 {DATE_ONLY} 也只到日', rendered)
            self.assertNotIn('弱在案例那一侧', rendered)

    def test_no_landing_has_no_time_basis_and_preserves_the_row_format(self):
        page, field = self.render()
        self.assertIsNone(field['time_basis'])
        self.assertNotIn('时间依据（', page)
        out = self.check_output()
        self.assertNotIn('落地依据（', out)
        row, = [line for line in out.splitlines() if line.startswith(f'  {DAO_ID}')]
        self.assertTrue(row.startswith(f'  {DAO_ID}  v2  模拟 · 未检（'), row)

    def test_render_and_check_do_not_write_the_fixture(self):
        self.add_observation(TIMED)
        before = {p.name: p.read_bytes() for p in self.library.iterdir()}
        self.render()
        self.check_output()
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.library.iterdir()})


if __name__ == '__main__':
    unittest.main()
