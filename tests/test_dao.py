"""一条道的一生的验收：三道检查各自能判、能判不过，未检印得出来，重跑不改字。

负控制是这份文件的重点：一个只会说「是的」的对抗台证明不了任何东西，
所以这里有套话道（结构该判不过）、装饰性失效条件（模拟该判不过），
以及一条没有写清「用在哪件真实活里」的自验（落地该判未跑）。
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
LIBRARY_FILES = ("episodes.json", "daos.json", "observations.json", "exposures.json", "map.json", "refusals.json", "record_checks.json", "promotions.json")


class DaoLifeTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="dojo-dao-"))
        shutil.copy(DAO / "vocabulary.json", self.dir / "vocabulary.json")
        (self.dir / "person-dojo").mkdir()
        for file_name in LIBRARY_FILES:
            shutil.copy(DAO / "person-dojo" / file_name, self.dir / "person-dojo" / file_name)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    # --- helpers ---------------------------------------------------------
    def read(self, name, library="person-dojo"):
        return json.loads((self.dir / library / name).read_text(encoding="utf-8"))

    def write(self, name, value, library="person-dojo"):
        (self.dir / library / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def vocabulary(self):
        return json.loads((self.dir / "vocabulary.json").read_text(encoding="utf-8"))

    def dossiers(self, library="person-dojo"):
        data = {
            "episodes": self.read("episodes.json", library),
            "daos": self.read("daos.json", library),
            "observations": self.read("observations.json", library),
            "exposures": self.read("exposures.json", library),
            "map": self.read("map.json", library),
            "refusals": self.read("refusals.json", library),
            "record_checks": self.read("record_checks.json", library),
            "promotions": self.read("promotions.json", library),
            "root": str(self.dir / library),
        }
        return data

    def bench(self, data=None, library="person-dojo"):
        return dao_life.run_bench(data or self.dossiers(library), AT, self.vocabulary())

    def run_command(self, *extra):
        argv = ["dao_life", str(self.dir / "person-dojo"), "--at", AT, *extra]
        return dao_life.main(argv)

    # --- the real library ------------------------------------------------
    def test_person_library_passes_both_network_checks_on_every_entry(self):
        receipts = self.bench()
        self.assertEqual(len(receipts), 13)
        for dao_id, receipt in receipts.items():
            self.assertEqual(receipt["structure"]["verdict"], "pass", (dao_id, receipt["structure"]["failures"]))
            self.assertEqual(receipt["falsifiable"]["verdict"], "pass", (dao_id, receipt["falsifiable"]["notes"]))
        for dao_id in ("dojo-d-001", "dojo-d-002", "dojo-d-003"):
            self.assertEqual(receipts[dao_id]["field"]["verdict"], "pass", dao_id)
            self.assertIn("弱", receipts[dao_id]["field"]["strength"], dao_id)
        unrun = [dao_id for dao_id, receipt in receipts.items() if receipt["field"]["verdict"] == "not_run"]
        self.assertEqual(len(unrun), 10)

    def test_every_unrun_entry_states_what_would_ground_it(self):
        data = self.dossiers()
        needed = {item["dao"] for item in data["observations"]["needed"]}
        receipts = self.bench()
        for dao in data["daos"]["daos"]:
            if receipts[dao["id"]]["field"]["verdict"] == "not_run":
                self.assertIn(dao["id"], needed)

    def test_the_library_shows_what_it_refused_and_by_which_part(self):
        data = self.dossiers()
        failures, summary = dao_life.check_library(data)
        self.assertEqual(failures, [])
        self.assertEqual(summary["entered"], 13)
        self.assertEqual(summary["refused"], 9)
        self.assertEqual(summary["refusal_counts"]["张力"], 4)
        self.assertEqual(summary["refusal_counts"]["重复"], 1)
        parts = {"情境", "张力", "动作", "代价", "失效", "归属", "重复"}
        for item in data["refusals"]["items"]:
            self.assertTrue(set(item["missing"]) <= parts, item["id"])
            self.assertTrue(item["why"])
            self.assertTrue(item["source"]["path"])
        page = dao_life.render(data, self.bench(), AT, {}, self.vocabulary())
        self.assertIn("没进库的东西：写不成道的材料", page)
        self.assertIn("按缺的那一件数", page)
        self.assertIn("六件按来源合计", page)
        self.assertIn("情境 系统补 13", page)

    def test_a_refusal_without_its_missing_part_is_refused(self):
        data = self.read("refusals.json")
        del data["items"][0]["missing"]
        self.write("refusals.json", data)
        self.assertEqual(self.run_command(), 1)

    def test_a_duplicate_pair_inside_one_library_is_refused(self):
        data = self.dossiers()
        dao = copy.deepcopy(data["daos"]["daos"][0])
        dao["id"] = "dojo-d-999"
        dao["version"] = 1
        data["daos"]["daos"] = data["daos"]["daos"] + [dao]
        failures, summary = dao_life.check_library(data)
        self.assertTrue(summary["relations"])
        self.assertTrue(any("同一条" in line for line in failures), failures)

    def test_two_entries_that_contradict_must_be_registered(self):
        data = self.dossiers()
        failures, summary = dao_life.check_library(data)
        self.assertEqual([r["kind"] for r in summary["relations"]], ["相反"])
        self.assertEqual(failures, [])
        data["map"]["contradictions"] = []
        failures, _ = dao_life.check_library(data)
        self.assertTrue(any("contradictions" in line for line in failures), failures)

    def test_a_dao_without_declared_part_sources_is_refused(self):
        data = self.dossiers()
        del data["daos"]["daos"][4]["part_sources"]
        receipt = self.bench(data)[data["daos"]["daos"][4]["id"]]["structure"]
        self.assertEqual(receipt["verdict"], "fail")
        self.assertTrue(any("part_sources" in item or "六件各自写明" in item for item in receipt["failures"]), receipt["failures"])

    def test_each_falsifiable_receipt_carries_two_situations_two_actions_and_a_conclusion(self):
        data = self.dossiers()
        receipts = self.bench()
        for dao in data["daos"]["daos"]:
            cases = receipts[dao["id"]]["falsifiable"]["cases"]
            self.assertGreaterEqual(len(cases), 2, dao["id"])
            actions = {case["action"] for case in cases}
            self.assertGreaterEqual(len(actions), 2, f"{dao['id']}：两个处境给出了同一个动作")
            self.assertEqual(receipts[dao["id"]]["falsifiable"]["notes"], [])

    def test_self_verification_grounds_a_cell_only_with_the_three_fields(self):
        data = self.dossiers()
        observation = copy.deepcopy(data["observations"]["observations"][1])
        self.assertEqual(observation["kind"], "agent_self")
        del observation["applied_in"]
        data["observations"]["observations"] = [observation]
        receipt = self.bench(data)["dojo-d-001"]["field"]
        self.assertEqual(receipt["verdict"], "not_run")
        self.assertTrue(any("自验" in item["reason"] for item in receipt["rejected"]), receipt["rejected"])

    def test_status_line_prints_the_missing_cell_instead_of_calling_it_verified(self):
        data = self.dossiers()
        receipts = self.bench()
        episodes = {episode["id"]: episode for episode in data["episodes"]["episodes"]}
        for dao in data["daos"]["daos"]:
            line = dao_life.status_of(dao, receipts[dao["id"]], episodes)["line"]
            self.assertIn("/3", line)
            if receipts[dao["id"]]["field"]["verdict"] == "not_run":
                self.assertIn("未检", line)
                self.assertNotIn("已验证", line)

    def test_rerun_with_the_same_stamp_writes_the_same_bytes(self):
        self.assertEqual(self.run_command(), 0)
        first = (self.dir / "person-dojo" / "receipts.json").read_bytes(), (self.dir / "person-dojo" / "道图.md").read_bytes()
        self.assertEqual(self.run_command(), 0)
        second = (self.dir / "person-dojo" / "receipts.json").read_bytes(), (self.dir / "person-dojo" / "道图.md").read_bytes()
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
        self.assertTrue(any("窗口" in name for name in receipt["failures"]), receipt["failures"])

    def test_a_tension_word_outside_the_vocabulary_fails_structure(self):
        data = self.dossiers()
        data["daos"]["daos"][0]["tension_key"] = "我自己编的一个词"
        receipt = self.bench(data)["dojo-d-001"]["structure"]
        self.assertEqual(receipt["verdict"], "fail")
        self.assertTrue(any("受控词表" in name for name in receipt["failures"]), receipt["failures"])

    # --- the claim is narrowed where it is made -------------------------
    def test_the_limit_sentence_stands_beside_the_ambition_in_four_places(self):
        proposal = (ROOT / "docs" / "proposal-knowledge-network.md").read_text(encoding="utf-8")
        product = (ROOT / "docs" / "product.md").read_text(encoding="utf-8")
        need = (ROOT / "docs" / "need.md").read_text(encoding="utf-8")
        self.assertIn("一个真人", proposal)
        self.assertIn("人类的道", proposal)
        self.assertIn("一个人的思想整理器", product)
        self.assertIn("仍然是**目标**", product)
        self.assertIn("没有任何跨人证据", need)
        data = self.dossiers()
        page = dao_life.render(data, self.bench(), AT, {}, self.vocabulary())
        self.assertIn("这张图是一个人的", page)
        self.assertIn("人类的道", page)
        self.assertNotIn("已经是人类的道", page)

    # --- depth on the first person ---------------------------------------
    def test_every_entry_that_was_unchecked_has_an_answer_now(self):
        receipts = self.bench()
        for dao_id in ("dojo-d-001", "dojo-d-002", "dojo-d-003"):
            self.assertEqual(receipts[dao_id]["field"]["verdict"], "pass", dao_id)
            self.assertIn("弱", receipts[dao_id]["field"]["strength"], dao_id)
        data = self.dossiers()
        episodes = {episode["id"]: episode for episode in data["episodes"]["episodes"]}
        for dao in data["daos"]["daos"]:
            line = dao_life.status_of(dao, receipts[dao["id"]], episodes)["line"]
            self.assertTrue(line.startswith("合写·") or line.startswith("合写 "), line)
            if dao["id"] in {"dojo-d-001", "dojo-d-002", "dojo-d-003"}:
                self.assertIn("检（3/3", line, line)
            else:
                self.assertIn("未检（2/3", line, line)

    def test_the_dao_the_three_suggest_is_named_but_not_counted(self):
        data = self.dossiers()
        dao_ids = {dao["id"] for dao in data["daos"]["daos"]}
        candidates = data["map"]["candidates"]
        self.assertTrue(candidates)
        for candidate in candidates:
            self.assertNotIn(candidate["id"], dao_ids)
            for source in candidate["suggested_by"]:
                self.assertIn(source, dao_ids)
            self.assertTrue(candidate["why_not_entered"])
            self.assertTrue(candidate["what_would_support_it"])
        page = dao_life.render(data, self.bench(), AT, {}, self.vocabulary())
        self.assertIn("候选（还不成立，所以没进库）", page)
        self.assertIn(candidates[0]["id"], page)
        self.assertIn("3 条道", page)

    def test_a_candidate_without_its_missing_part_is_refused(self):
        data = self.read("map.json")
        del data["candidates"][0]["why_not_entered"]
        self.write("map.json", data)
        self.assertEqual(self.run_command(), 1)
        self.assertEqual(sorted(path.name for path in (self.dir / "person-dojo").iterdir() if path.name not in set(LIBRARY_FILES)), [])

    # --- who wrote it, and what may be concluded -------------------------
    def test_a_co_written_entry_never_renders_as_his_words(self):
        data = self.dossiers()
        receipts = self.bench()
        episodes = {episode["id"]: episode for episode in data["episodes"]["episodes"]}
        page = dao_life.render(data, receipts, AT, {}, self.vocabulary())
        self.assertIn("按作者分：他的 0 条、合写 13 条、系统的 0 条。", page)
        for dao in data["daos"]["daos"]:
            line = dao_life.status_of(dao, receipts[dao["id"]], episodes)["line"]
            self.assertTrue(line.startswith("合写"), line)
            for word in ("自述", "验过", "量过"):
                self.assertNotIn(word, line, line)
        self.assertIn("**六件是谁写的：**", page)
        self.assertIn("**读这条能得出什么：**", page)
        self.assertIn("系统补", page)
        self.assertIn("不能被读成「他的看法」", page)

    def test_every_supplied_tension_and_price_has_a_record_check(self):
        data = self.dossiers()
        covered = {(item["dao"], item["part"]) for item in data["record_checks"]["checks"]}
        for dao in data["daos"]["daos"]:
            if dao["part_sources"]["tension"] == "系统补":
                self.assertIn((dao["id"], "tension"), covered, dao["id"])
            if dao["part_sources"]["price"] == "系统补":
                self.assertIn((dao["id"], "price"), covered, dao["id"])
        failures, summary = dao_life.check_library(data)
        self.assertEqual(failures, [])
        self.assertEqual(summary["record_status"]["收窄"], 2)
        self.assertEqual(summary["promotions"], 0)

    def test_a_record_check_that_narrows_without_a_version_is_refused(self):
        data = self.dossiers()
        for dao in data["daos"]["daos"]:
            if dao["id"] == "dojo-d-013":
                dao["version"] = 1
                dao["revisions"] = []
        failures, _ = dao_life.check_library(data)
        self.assertTrue(any("没有升版" in line for line in failures), failures)

    def test_a_record_check_that_says_nothing_is_refused(self):
        data = self.dossiers()
        data["record_checks"]["checks"][0]["against"]["quote"] = ""
        failures, _ = dao_life.check_library(data)
        self.assertTrue(any("没写引文" in line for line in failures), failures)

    def test_a_missing_record_check_is_refused(self):
        data = self.dossiers()
        data["record_checks"]["checks"] = [
            item for item in data["record_checks"]["checks"]
            if not (item["dao"] == "dojo-d-005" and item["part"] == "tension")
        ]
        failures, _ = dao_life.check_library(data)
        self.assertTrue(any("记录检查" in line for line in failures), failures)

    # --- promotion: the one way an inference becomes his ------------------
    def _promotion(self, **overrides):
        promotion = {
            "id": "pm-001",
            "dao": "dojo-d-013",
            "part": "tension",
            "kind": "确认",
            "episode": "ep-2026-10-23-ux",
            "quote": "way better than last time",
            "as": "他的原话",
            "ran": {"by": "scripts/dao_life.py promotion-v1", "at": AT, "on_version": 2},
        }
        promotion.update(overrides)
        return promotion

    def test_a_promotion_needs_a_quote_that_is_really_in_the_episode(self):
        data = self.dossiers()
        data["promotions"]["promotions"] = [self._promotion(quote="这句他没有说过")]
        failures, _ = dao_life.check_library(data)
        self.assertTrue(any("引文不在事件" in line for line in failures), failures)

    def test_a_promotion_that_confirms_must_change_the_part(self):
        data = self.dossiers()
        data["promotions"]["promotions"] = [self._promotion()]
        failures, _ = dao_life.check_library(data)
        self.assertTrue(any("还标着「系统补」" in line for line in failures), failures)

    def test_a_valid_promotion_moves_the_part_to_his_words(self):
        data = self.dossiers()
        data["promotions"]["promotions"] = [self._promotion()]
        for dao in data["daos"]["daos"]:
            if dao["id"] == "dojo-d-013":
                dao["part_sources"]["tension"] = "他的原话"
        failures, summary = dao_life.check_library(data)
        self.assertEqual(failures, [])
        self.assertEqual(summary["promotions"], 1)

    def test_a_promotion_that_overturns_must_be_handled(self):
        data = self.dossiers()
        data["promotions"]["promotions"] = [self._promotion(kind="推翻")]
        failures, _ = dao_life.check_library(data)
        self.assertTrue(any("没写处理" in line for line in failures), failures)

    def test_the_narrowed_entry_is_at_version_two_and_names_its_check(self):
        data = self.dossiers()
        dao = [item for item in data["daos"]["daos"] if item["id"] == "dojo-d-013"][0]
        self.assertEqual(dao["version"], 2)
        self.assertTrue(any("rc-013" in (rev.get("because") or "") for rev in dao["revisions"]))
        receipts = self.bench()
        self.assertEqual(receipts["dojo-d-013"]["structure"]["ran"]["on_version"], 2)

    # --- the pending line stays pending ---------------------------------
    def test_the_pending_boundary_is_not_written_into_the_product_documents(self):
        boundaries = json.loads((DAO / "person-dojo" / "map.json").read_text(encoding="utf-8"))["boundaries"]
        boundary = boundaries[0]
        self.assertEqual(boundary["status"], "待确认")
        product = (ROOT / "docs" / "product.md").read_text(encoding="utf-8")
        need = (ROOT / "docs" / "need.md").read_text(encoding="utf-8")
        for document in (product, need):
            self.assertNotIn("入口显式", document)
            self.assertNotIn(boundary["test_line"], document)


if __name__ == "__main__":
    unittest.main()
