"""Comparison uses controlled keys, preserves synthetic status and leaves rules intact."""
import importlib.util
import json
from pathlib import Path
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


class DaoCompareTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / 'libraries'
        seed.build(self.root)
        self.vocabulary_path = self.root / 'vocabulary.json'
        self.vocabulary = json.loads(self.vocabulary_path.read_text(encoding='utf-8'))

    def comparison(self):
        a = life.load_library(self.root / seed.A)
        b = life.load_library(self.root / seed.B)
        return life.compare_libraries(
            a, life.run_bench(a, seed.AT, self.vocabulary),
            b, life.run_bench(b, seed.AT, self.vocabulary), self.vocabulary,
        )

    def test_second_library_is_explicitly_synthetic(self):
        data = life.load_library(self.root / seed.B)
        receipts = life.run_bench(data, seed.AT, self.vocabulary)
        dao, = data['daos']['daos']
        episodes = {episode['id']: episode for episode in data['episodes']['episodes']}
        line = life.status_of(dao, receipts[dao['id']], episodes)['line']
        self.assertTrue(line.startswith('模拟'), line)
        page = life.render(data, receipts, seed.AT, {}, self.vocabulary)
        for witness in ('模拟来源', '不是一个人的道图', '不是一个人的道理'):
            self.assertIn(witness, page)

    def test_shared_tension_distinguishes_variant_and_contradiction(self):
        variant, = self.comparison()['pairs']
        self.assertTrue(variant['relation'].startswith('变体'), variant)
        changed = '过道内侧先标'
        self.vocabulary['moves'].append({
            'key': changed, 'gloss': '虚构反向动作', 'introduced_by': ['screen-d-1'],
            'reason': '比较另一种方向',
        })
        path = self.root / seed.B / 'daos.json'
        data = json.loads(path.read_text(encoding='utf-8'))
        data['daos'][0]['move_key'] = changed
        seed.put(path, data)
        contradiction, = self.comparison()['pairs']
        self.assertTrue(contradiction['relation'].startswith('相反'), contradiction)

    def test_unrelated_libraries_compare_without_changing_rules(self):
        changed = '另一处交接难题'
        self.vocabulary['tensions'].append({
            'key': changed, 'gloss': '虚构的另一处张力', 'introduced_by': ['screen-d-1'],
            'reason': '验证不同张力',
        })
        seed.put(self.vocabulary_path, self.vocabulary)
        path = self.root / seed.B / 'daos.json'
        data = json.loads(path.read_text(encoding='utf-8'))
        data['daos'][0]['tension_key'] = changed
        seed.put(path, data)
        paths = [self.root / name / 'daos.json' for name in (seed.A, seed.B)]
        before = [p.read_bytes() for p in paths]
        self.assertEqual(0, life.main([
            'dao_life', str(self.root / seed.A), '--compare', str(self.root / seed.B),
            '--at', seed.AT,
        ]))
        self.assertEqual(before, [p.read_bytes() for p in paths])
        page = (self.root / seed.A / '对比.md').read_text(encoding='utf-8')
        limit = json.loads((self.root / 'comparison.json').read_text(encoding='utf-8'))['limit']
        for witness in ('0 对落在同一个张力上', '没有改动任何一条道', '不能证明什么', limit):
            self.assertIn(witness, page)


if __name__ == '__main__':
    unittest.main()
