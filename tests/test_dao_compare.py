"""第二个来源：它跑同一条 loop，但它的状态行必须说它是模拟材料；对比只按受控键算。

这一支测试的用处是证明对比不是空转：把张力键对上，命令必须给出「变体」或「相反」；
对不上时给出「无关」，并且不写回任何一条道。
"""

import copy
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DAO = ROOT / "docs" / "dao"
SPEC = importlib.util.spec_from_file_location("dao_life", ROOT / "scripts" / "dao_life.py")
dao_life = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dao_life)

AT = "2026-10-23T22:00:00Z"
LIBRARIES = ("person-dojo", "demo-strangers")
LIBRARY_FILES = ("episodes.json", "daos.json", "observations.json", "exposures.json", "map.json")


class DaoCompareTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="dojo-dao-cmp-"))
        shutil.copy(DAO / "vocabulary.json", self.dir / "vocabulary.json")
        shutil.copy(DAO / "comparison.json", self.dir / "comparison.json")
        for name in LIBRARIES:
            (self.dir / name).mkdir()
            for file_name in LIBRARY_FILES:
                shutil.copy(DAO / name / file_name, self.dir / name / file_name)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def read(self, name, library):
        return json.loads((self.dir / library / name).read_text(encoding="utf-8"))

    def write(self, name, value, library):
        (self.dir / library / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def vocabulary(self):
        return json.loads((self.dir / "vocabulary.json").read_text(encoding="utf-8"))

    def dossiers(self, library):
        return {
            "episodes": self.read("episodes.json", library),
            "daos": self.read("daos.json", library),
            "observations": self.read("observations.json", library),
            "exposures": self.read("exposures.json", library),
            "map": self.read("map.json", library),
            "root": str(self.dir / library),
        }

    def bench(self, library):
        return dao_life.run_bench(self.dossiers(library), AT, self.vocabulary())

    def test_a_second_library_is_statused_as_simulated_not_as_a_person(self):
        receipts = self.bench("demo-strangers")
        data = self.dossiers("demo-strangers")
        episodes = {episode["id"]: episode for episode in data["episodes"]["episodes"]}
        line = dao_life.status_of(data["daos"]["daos"][0], receipts["demo-d-101"], episodes)["line"]
        self.assertTrue(line.startswith("模拟"), line)
        rendered = dao_life.render(data, receipts, AT, {}, self.vocabulary())
        self.assertIn("模拟来源", rendered)
        self.assertIn("不是一个人的道图", rendered)
        self.assertIn("不是一个人的道理", rendered)

    def test_compare_reports_variant_and_contradiction_when_the_tension_is_shared(self):
        a_data = self.dossiers("person-dojo")
        a_receipts = self.bench("person-dojo")
        vocabulary = self.vocabulary()
        b_data = self.dossiers("demo-strangers")
        dao = copy.deepcopy(b_data["daos"]["daos"][0])
        dao["tension_key"] = "检查归属"
        dao["move_key"] = "换承担方"
        b_data["daos"]["daos"] = [dao]
        variant = dao_life.compare_libraries(a_data, a_receipts, b_data, self.bench("demo-strangers"), vocabulary)
        self.assertTrue(any(row["relation"].startswith("变体") for row in variant["pairs"]), variant["pairs"])
        dao["move_key"] = "降摩擦"
        b_data["daos"]["daos"] = [dao]
        b_receipts = dao_life.run_bench(b_data, AT, vocabulary)
        contradiction = dao_life.compare_libraries(a_data, a_receipts, b_data, b_receipts, vocabulary)
        self.assertTrue(any(row["relation"].startswith("相反") for row in contradiction["pairs"]))

    def test_compare_names_no_relation_for_the_real_pair_and_changes_no_dao(self):
        before = {name: (self.dir / name / "daos.json").read_bytes() for name in LIBRARIES}
        argv = [
            "dao_life",
            str(self.dir / "person-dojo"),
            "--compare",
            str(self.dir / "demo-strangers"),
            "--at",
            AT,
        ]
        self.assertEqual(dao_life.main(argv), 0)
        after = {name: (self.dir / name / "daos.json").read_bytes() for name in LIBRARIES}
        self.assertEqual(before, after)
        page = (self.dir / "person-dojo" / "对比.md").read_text(encoding="utf-8")
        self.assertIn("0 对落在同一个张力上", page)
        self.assertIn("没有改动任何一条道", page)
        self.assertIn("这不是收敛证据", page)


if __name__ == "__main__":
    unittest.main()
