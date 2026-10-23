"""一条道的一生的验收：三道检查各自能判、能判不过，未检印得出来，重跑不改字。

负控制是这份文件的重点：一个只会说「是的」的对抗台证明不了任何东西，
所以这里有一条套话道（结构该判不过）和一条装饰性失效条件（模拟该判不过）。
"""

import copy
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("dao_life", ROOT / "scripts" / "dao_life.py")
dao_life = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dao_life)

DATA_FILES = ("episodes.json", "daos.json", "observations.json", "exposures.json", "map.json")
REPO_DATA = ROOT / "docs" / "dao" / "person-dojo"
AT = "2026-10-23T22:00:00Z"


class DaoLifeTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="dojo-dao-"))
        for name in DATA_FILES:
            shutil.copy(REPO_DATA / name, self.dir / name)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    # --- helpers ---------------------------------------------------------
    def read(self, name):
        return json.loads((self.dir / name).read_text(encoding="utf-8"))

    def write(self, name, value):
        (self.dir / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def dossiers(self):
        return {
            "episodes": self.read("episodes.json"),
            "daos": self.read("daos.json"),
            "observations": self.read("observations.json"),
            "exposures": self.read("exposures.json"),
            "map": self.read("map.json"),
        }

    def bench(self, data=None):
        return dao_life.run_bench(data or self.dossiers(), AT)

    def run_command(self):
        return dao_life.main(["dao_life", str(self.dir), "--at", AT])

    # --- the real library ------------------------------------------------
    def test_person_library_passes_both_network_checks_and_keeps_its_unrun_cell(self):
        receipts = self.bench()
        self.assertEqual(len(receipts), 3)
        for dao_id, receipt in receipts.items():
            self.assertEqual(receipt["structure"]["verdict"], "pass", (dao_id, receipt["structure"]["failures"]))
            self.assertEqual(receipt["falsifiable"]["verdict"], "pass", (dao_id, receipt["falsifiable"]["notes"]))
            self.assertEqual(receipt["field"]["verdict"] in {"pass", "fail", "not_run"}, True)
        self.assertEqual(receipts["dojo-d-001"]["field"]["verdict"], "not_run")
        self.assertIsNone(receipts["dojo-d-001"]["field"]["observation"])
        self.assertIsNone(receipts["dojo-d-001"]["field"]["ran"])
        self.assertEqual(receipts["dojo-d-002"]["field"]["verdict"], "pass")
        self.assertEqual(receipts["dojo-d-002"]["field"]["observation"]["kind"], "later_session")
        self.assertIn("弱", receipts["dojo-d-002"]["field"]["strength"])

    def test_each_falsifiable_receipt_carries_two_situations_two_actions_and_a_conclusion(self):
        data = self.dossiers()
        receipts = self.bench()
        for dao in data["daos"]["daos"]:
            cases = receipts[dao["id"]]["falsifiable"]["cases"]
            self.assertGreaterEqual(len(cases), 2, dao["id"])
            actions = {case["action"] for case in cases}
            self.assertGreaterEqual(len(actions), 2, f"{dao['id']}：两个处境给出了同一个动作")
            self.assertTrue(all(case["situation"] for case in cases), dao["id"])
            self.assertTrue(receipts[dao["id"]]["falsifiable"]["notes"] == [])

    def test_status_line_prints_the_missing_cell_instead_of_calling_it_verified(self):
        data = self.dossiers()
        receipts = self.bench()
        for dao in data["daos"]["daos"]:
            line = dao_life.status_of(dao, receipts[dao["id"]])["line"]
            self.assertIn("/3", line)
            if receipts[dao["id"]]["field"]["verdict"] == "not_run":
                self.assertIn("未检", line)
                self.assertNotIn("已验证", line)

    def test_rerun_with_the_same_stamp_writes_the_same_bytes(self):
        self.assertEqual(self.run_command(), 0)
        first = (self.dir / "receipts.json").read_bytes(), (self.dir / "道图.md").read_bytes()
        self.assertEqual(self.run_command(), 0)
        second = (self.dir / "receipts.json").read_bytes(), (self.dir / "道图.md").read_bytes()
        self.assertEqual(first, second)
        self.assertIn("未检", second[1].decode("utf-8"))
        self.assertNotIn("已验证", second[1].decode("utf-8"))

    # --- negative controls ----------------------------------------------
    def test_a_dao_of_commonplaces_fails_structure(self):
        data = self.dossiers()
        dao = copy.deepcopy(data["daos"]["daos"][0])
        dao["off"][0]["then"] = "因人而异，注意平衡"
        dao["price"][0]["unit"] = "心情"
        data["daos"]["daos"] = [dao]
        receipt = self.bench(data)["dojo-d-001"]["structure"]
        self.assertEqual(receipt["verdict"], "fail")
        failed = " ".join(receipt["failures"])
        self.assertIn("套话", failed)
        self.assertIn("真正花掉的资源", failed)

    def test_a_decorative_failure_condition_fails_the_simulation(self):
        data = self.dossiers()
        dao = copy.deepcopy(data["daos"]["daos"][0])
        dao["off"] = [item for item in dao["off"] if item["axis"] == "judge"]
        dao["off"].append(
            {
                "when": "检查由系统自己记着（看起来像换了一个人，其实动作不变）",
                "axis": "check_keeper",
                "value": "系统",
                "then_kind": "reverse",
                "then": "换一个独立的一方来跑",
            }
        )
        data["daos"]["daos"] = [dao]
        receipt = self.bench(data)["dojo-d-001"]["falsifiable"]
        self.assertEqual(receipt["verdict"], "fail")
        self.assertTrue(any("装饰" in note for note in receipt["notes"]), receipt["notes"])

    def test_a_dao_whose_case_is_not_in_the_event_layer_is_refused(self):
        data = self.dossiers()
        dao = copy.deepcopy(data["daos"]["daos"][1])
        dao["provenance"][0]["episode"] = "ep-never-recorded"
        data["daos"]["daos"] = [dao]
        receipt = self.bench(data)["dojo-d-002"]["structure"]
        self.assertEqual(receipt["verdict"], "fail")
        self.assertTrue(any("归属边" in name for name in receipt["failures"]), receipt["failures"])

    def test_a_second_session_is_refused_rather_than_folded_in(self):
        data = self.dossiers()
        episode = copy.deepcopy(data["episodes"]["episodes"][1])
        episode["id"] = "ep-2026-10-25-later"
        episode["at"] = "2026-10-25"
        data["episodes"]["episodes"].append(episode)
        data["daos"]["daos"][1]["provenance"][0]["episode"] = "ep-2026-10-25-later"
        data["daos"]["daos"] = [data["daos"]["daos"][1]]
        receipt = self.bench(data)["dojo-d-002"]["structure"]
        self.assertEqual(receipt["verdict"], "fail")
        self.assertTrue(any("之后的 person 输入" in name for name in receipt["failures"]), receipt["failures"])


if __name__ == "__main__":
    unittest.main()
