"""一条道的一生的验收：三道检查各自能判、能判不过，未检印得出来，重跑不改字。

负控制是这份文件的重点：一个只会说「是的」的对抗台证明不了任何东西，
所以这里有套话道（结构该判不过）、装饰性失效条件（模拟该判不过），
以及一条没有写清「用在哪件真实活里」的自验（落地该判未跑）。
"""

import copy
from contextlib import redirect_stdout
import io
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("dao_life", ROOT / "scripts" / "dao_life.py")
dao_life = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dao_life)

AT = "2026-10-23T22:00:00Z"


class SyntheticDaoLifeTests(unittest.TestCase):
    def setUp(self):
        fixture_spec = importlib.util.spec_from_file_location("seed_dao", ROOT / "fixtures/seed_dao.py")
        seed = importlib.util.module_from_spec(fixture_spec)
        fixture_spec.loader.exec_module(seed)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name) / "authored-libraries"
        seed.build(root)
        self.library = root / seed.A
        self.at = seed.AT
        self.vocabulary = dao_life.load(root / "vocabulary.json")

    def dossiers(self):
        return dao_life.load_library(self.library)

    def bench(self, data=None):
        return dao_life.run_bench(data if data is not None else self.dossiers(), self.at, self.vocabulary)

    def run_command(self):
        return dao_life.main(["dao_life", str(self.library), "--at", self.at])


    def test_a_duplicate_pair_inside_one_library_is_refused(self):
        data = self.dossiers()
        dao = copy.deepcopy(data["daos"]["daos"][0])
        dao["id"] = "dojo-d-999"
        dao["version"] = 1
        data["daos"]["daos"] = data["daos"]["daos"] + [dao]
        failures, summary = dao_life.check_library(data)
        self.assertTrue(summary["relations"])
        self.assertTrue(any("同一条" in line for line in failures), failures)


    def test_a_dao_without_declared_part_sources_is_refused(self):
        data = self.dossiers()
        del data["daos"]["daos"][0]["part_sources"]
        receipt = self.bench(data)[data["daos"]["daos"][0]["id"]]["structure"]
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
        first = (self.library / "receipts.json").read_bytes(), (self.library / "道图.md").read_bytes()
        self.assertEqual(self.run_command(), 0)
        second = (self.library / "receipts.json").read_bytes(), (self.library / "道图.md").read_bytes()
        self.assertEqual(first, second)
        self.assertIn("未检", second[1].decode("utf-8"))
        self.assertNotIn("已验证", second[1].decode("utf-8"))


    def test_a_dao_of_commonplaces_fails_structure(self):
        data = self.dossiers()
        dao = copy.deepcopy(data["daos"]["daos"][0])
        dao["off"][0]["then"] = "因人而异，注意平衡"
        dao["price"][0]["unit"] = "心情"
        data["daos"]["daos"] = [dao]
        receipt = self.bench(data)["ring-d-1"]["structure"]
        self.assertEqual(receipt["verdict"], "fail")
        failed = " ".join(receipt["failures"])
        self.assertIn("套话", failed)
        self.assertIn("真正花掉的资源", failed)


    def test_a_dao_whose_case_is_not_in_the_event_layer_is_refused(self):
        data = self.dossiers()
        dao = copy.deepcopy(data["daos"]["daos"][0])
        dao["provenance"][0]["episode"] = "ep-never-recorded"
        data["daos"]["daos"] = [dao]
        receipt = self.bench(data)["ring-d-1"]["structure"]
        self.assertEqual(receipt["verdict"], "fail")
        self.assertTrue(any("归属边" in name for name in receipt["failures"]), receipt["failures"])


    def test_a_second_session_is_refused_rather_than_folded_in(self):
        data = self.dossiers()
        episode = copy.deepcopy(data["episodes"]["episodes"][0])
        episode["id"] = "ep-2187-03-05-later"
        episode["at"] = "2187-03-05"
        data["episodes"]["episodes"].append(episode)
        data["daos"]["daos"][0]["provenance"][0]["episode"] = "ep-2187-03-05-later"
        data["daos"]["daos"] = [data["daos"]["daos"][0]]
        receipt = self.bench(data)["ring-d-1"]["structure"]
        self.assertEqual(receipt["verdict"], "fail")
        self.assertTrue(any("窗口" in name for name in receipt["failures"]), receipt["failures"])


    def test_a_tension_word_outside_the_vocabulary_fails_structure(self):
        data = self.dossiers()
        data["daos"]["daos"][0]["tension_key"] = "我自己编的一个词"
        receipt = self.bench(data)["ring-d-1"]["structure"]
        self.assertEqual(receipt["verdict"], "fail")
        self.assertTrue(any("受控词表" in name for name in receipt["failures"]), receipt["failures"])


    @staticmethod
    def promotion(data, **overrides):
        return {**data["promotions"]["promotions"][0], **overrides}

    def test_self_verification_grounds_a_cell_only_with_the_three_fields(self):
        data = self.dossiers()
        observation = {"id": "synthetic-self-check", "dao": "ring-d-1",
                       "kind": "agent_self", "at": "2187-03-07", "matched": True,
                       "result": "虚构紫签可见", "could_have_gone_otherwise": "封贴可能遮住挂位"}
        data["observations"]["observations"] = [observation]
        receipt = self.bench(data)["ring-d-1"]["field"]
        self.assertEqual(receipt["verdict"], "not_run")
        self.assertTrue(any("自验" in item["reason"] for item in receipt["rejected"]), receipt["rejected"])


    def test_a_provenance_row_without_person_is_judged_and_refused(self):
        """#1831: the same row must fail `check_structure` and stop `render` with a name.

        Before this, `check_structure` passed the entry while `render` died inside
        `sorted(people)` on a `None`. A check that passes the shape the renderer
        crashes on is not judging the same object, so both sides read one list.
        """
        data = self.dossiers()
        episodes = {episode["id"]: episode for episode in data["episodes"]["episodes"]}
        dao = data["daos"]["daos"][0]
        dao["provenance"][0].pop("person")
        structure = dao_life.check_structure(
            dao, episodes, data["episodes"]["window"], self.vocabulary, self.at)
        self.assertEqual(structure["verdict"], "fail")
        self.assertTrue(any("四键" in check["name"] for check in structure["checks"] if not check["ok"]))

        with self.assertRaises(dao_life.NoteError) as caught:
            dao_life.render(data, self.bench(data), self.at, {}, self.vocabulary)
        self.assertIn("person", str(caught.exception))
        self.assertIn(dao["id"], str(caught.exception))


    def test_the_same_row_with_its_person_key_still_passes(self):
        """The control: the arm above moves because of the missing key, not the fixture."""
        data = self.dossiers()
        episodes = {episode["id"]: episode for episode in data["episodes"]["episodes"]}
        dao = data["daos"]["daos"][0]
        structure = dao_life.check_structure(
            dao, episodes, data["episodes"]["window"], self.vocabulary, self.at)
        self.assertEqual(structure["verdict"], "pass")
        dao_life.render(data, self.bench(data), self.at, {}, self.vocabulary)


    def test_a_promotion_needs_a_quote_that_is_really_in_the_episode(self):
        data = self.dossiers()
        data["promotions"]["promotions"] = [self.promotion(data, quote="这句他没有说过")]
        failures, _ = dao_life.check_library(data)
        self.assertTrue(any("引文不在事件" in line for line in failures), failures)


    def test_a_promotion_that_confirms_must_change_the_part(self):
        data = self.dossiers()
        data["promotions"]["promotions"] = [self.promotion(data)]
        data["daos"]["daos"][0]["part_sources"]["move"] = "系统补"
        failures, _ = dao_life.check_library(data)
        self.assertTrue(any("还标着「系统补」" in line for line in failures), failures)


    def test_a_valid_promotion_moves_the_part_to_his_words(self):
        data = self.dossiers()
        data["promotions"]["promotions"] = [self.promotion(data)]
        for dao in data["daos"]["daos"]:
            if dao["id"] == "ring-d-1":
                dao["part_sources"]["move"] = "他的原话"
        failures, summary = dao_life.check_library(data)
        self.assertEqual(failures, [])
        self.assertEqual(summary["promotions"], 1)


    def test_a_promotion_that_overturns_must_be_handled(self):
        data = self.dossiers()
        data["promotions"]["promotions"] = [self.promotion(data, kind="推翻")]
        failures, _ = dao_life.check_library(data)
        self.assertTrue(any("没写处理" in line for line in failures), failures)


    def test_a_refusal_without_its_missing_part_is_refused(self):
        path = self.library / "refusals.json"
        path.write_text(json.dumps({"items": [{
            "id": "fictional-refusal", "why": "没有说出何时撤下标记",
            "source": {"path": "fictional-hand-off.md"},
        }]}), encoding="utf-8")
        before = {p.name: p.read_bytes() for p in self.library.iterdir()}
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(1, self.run_command())
        self.assertIn('缺哪一件', out.getvalue())
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.library.iterdir()})

    def test_two_entries_that_contradict_must_be_registered(self):
        data = self.dossiers()
        other = copy.deepcopy(data["daos"]["daos"][0])
        other["id"] = "fictional-opposite"
        other["move_key"] = "内侧先标"
        data["daos"]["daos"].append(other)
        data["map"]["contradictions"] = [{
            "id": "fictional-conflict", "between": ["ring-d-1", "fictional-opposite"],
            "on": other["tension_key"], "state": "待核",
            "what_would_settle_it": "观察从两侧到达的交接条件",
        }]
        failures, summary = dao_life.check_library(data)
        self.assertEqual(["相反"], [r["kind"] for r in summary["relations"]])
        self.assertEqual([], failures)
        data["map"]["contradictions"].clear()
        failures, _ = dao_life.check_library(data)
        self.assertTrue(any("contradictions" in line for line in failures), failures)

    def test_a_decorative_failure_condition_fails_the_simulation(self):
        data = self.dossiers()
        dao = data["daos"]["daos"][0]
        dao["rule"][1]["action"] = dao["rule"][0]["action"]
        result = self.bench(data)[dao["id"]]["falsifiable"]
        self.assertEqual("fail", result["verdict"])
        self.assertTrue(any("装饰" in note for note in result["notes"]), result["notes"])

    def test_a_candidate_without_its_missing_part_is_refused(self):
        path = self.library / "map.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["candidates"] = [{
            "id": "fictional-candidate", "one_line": "改用一张更亮的签",
            "what_would_support_it": "在暗处重排一次", "suggested_by": ["ring-d-1"],
        }]
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        before = {p.name: p.read_bytes() for p in self.library.iterdir()}
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(1, self.run_command())
        self.assertIn('why_not_entered', out.getvalue())
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.library.iterdir()})


    def authored_person_category(self):
        data = self.dossiers()
        data["episodes"]["episodes"][0]["attribution"] = "person"
        return data

    def with_second_source(self, data, *, observed_action):
        dao = data["daos"]["daos"][0]
        case = dict(data["episodes"]["episodes"][0], id="fictional-second-case")
        case["observed_action"] = observed_action
        data["episodes"]["episodes"].append(case)
        dao["provenance"].append({
            "person": "fictional-second-id", "episode": case["id"],
            "status": "自述", "learned_from": "测试构造",
        })
        return data

    def test_a_second_written_id_still_moves_the_count_and_still_is_not_a_person(self):
        data = self.authored_person_category()
        one = dao_life.independent_groups(data)
        two = dao_life.independent_groups(self.with_second_source(data, observed_action="重挂蓝签"))
        self.assertEqual((1, 2), (one["groups"], two["groups"]))
        self.assertIn("来源 id 1 个", one["line"])
        self.assertIn("来源 id 2 个", two["line"])
        self.assertIn("这不是人数", two["line"])
        self.assertNotRegex(two["line"], r"不同的人 \d+ 个")

    def test_a_library_without_relayed_rows_does_not_claim_any(self):
        data = self.authored_person_category()
        line = dao_life.independent_groups(data)["line"]
        self.assertIn("这不是人数", line)
        self.assertNotIn("relayed", line)
        data["episodes"]["episodes"][0]["attribution"] = "relayed"
        self.assertIn("relayed", dao_life.independent_groups(data)["line"])

    def test_a_synthetic_library_keeps_the_sentence_that_was_written_for_it(self):
        line = dao_life.independent_groups(self.dossiers())["line"]
        self.assertIn("来源是模拟材料", line)
        self.assertNotIn("这不是人数", line)

    def test_a_second_source_with_only_a_quote_is_not_a_second_group(self):
        data = self.with_second_source(self.authored_person_category(), observed_action=None)
        rejected = dao_life.independent_groups(data)
        self.assertEqual(1, rejected["groups"])
        self.assertNotIn("fictional-second-id", rejected["people"])
        data["episodes"]["episodes"][-1]["observed_action"] = "重挂蓝签"
        counted = dao_life.independent_groups(data)
        self.assertEqual(2, counted["groups"])
        self.assertIn("fictional-second-id", counted["people"])

    def record_check_fixture(self):
        data = self.authored_person_category()
        data["refusals"]["items"] = [{
            "id": "fictional-refusal", "why": "缺少撤下标记的条件",
            "source": {"path": "fictional-record"}, "missing": ["失效"],
        }]
        dao = data["daos"]["daos"][0]
        dao["revisions"] = [{"because": "fictional-tension-check"}]
        data["record_checks"]["checks"] = [
            {"id": "fictional-tension-check", "dao": dao["id"], "part": "tension",
             "status": "收窄", "against": {"quote": "虚构蓝签条件"},
             "says": "只限于这次合成交接", "handling": "收窄到这次交接"},
            {"id": "fictional-price-check", "dao": dao["id"], "part": "price",
             "status": "确认", "against": {"quote": "虚构准备耗时"},
             "says": "合成场景确有准备成本"},
        ]
        self.assertEqual([], dao_life.check_library(data)[0])
        return data

    def test_a_record_check_that_narrows_without_a_version_is_refused(self):
        data = self.record_check_fixture()
        data["daos"]["daos"][0]["version"] = 1
        failures, _ = dao_life.check_library(data)
        self.assertTrue(any("没有升版" in line for line in failures), failures)

    def test_a_record_check_that_says_nothing_is_refused(self):
        data = self.record_check_fixture()
        data["record_checks"]["checks"][0]["against"]["quote"] = ""
        failures, _ = dao_life.check_library(data)
        self.assertTrue(any("没写引文" in line for line in failures), failures)

    def test_a_missing_record_check_is_refused(self):
        data = self.record_check_fixture()
        del data["record_checks"]["checks"][0]
        failures, _ = dao_life.check_library(data)
        self.assertTrue(any("张力" in line and "记录检查" in line for line in failures), failures)


class ObservationTimeTests(unittest.TestCase):
    def test_precise_times_are_compared_as_instants(self):
        cases = [
            ("2026-10-23T11:00:00Z", "2026-10-23T10:00:00Z", True),
            ("2026-10-23T10:00:00Z", "2026-10-23T10:00:00Z", False),
            ("2026-10-24T00:30:00+08:00", "2026-10-23T23:00:00Z", False),
            ("2026-10-23T23:30:00Z", "2026-10-24T00:00:00+08:00", True),
            ("2026-10-23T11:00", "2026-10-23T10:00", True),
        ]
        for observation, episode, expected in cases:
            with self.subTest(observation=observation, episode=episode):
                self.assertEqual(dao_life.later(observation, episode), expected)

    def test_missing_invalid_or_incomparable_times_do_not_earn_evidence(self):
        for observation, episode in [
            ("2026-10-24garbage", "2026-10-23"),
            ("2026-10-24", "2026-02-30"),
            ("2026-02-30", "2026-01-01"),
            ("", "2026-10-23"),
            ("2026-10-24", ""),
            ("2026-10-23T12", "2026-10-23"),
            ("2026-10-24T11:00", "2026-10-23T10:00:00Z"),
            ("2026-10-24T11:00:00Z", "2026-10-23T10:00"),
        ]:
            with self.subTest(observation=observation, episode=episode):
                self.assertFalse(dao_life.later(observation, episode))

    def test_day_granularity_keeps_the_existing_same_day_convention(self):
        self.assertTrue(dao_life.later("2026-10-23T10:00:00Z", "2026-10-23"))
        self.assertFalse(dao_life.later("2026-10-23", "2026-10-23"))
        self.assertTrue(dao_life.later("2026-10-24", "2026-10-23"))
        self.assertFalse(dao_life.later("2026-10-23", "2026-10-23T10:00:00Z"))
        self.assertTrue(dao_life.later("2026-10-24", "2026-10-23T10:00:00Z"))

    def test_field_must_be_later_than_every_case_not_the_lexical_max(self):
        dao = {"id": "d-time", "version": 1, "provenance": [{"episode": "a"}, {"episode": "b"}]}
        episodes = {
            "a": {"at": "2026-10-23T23:00:00Z"},
            "b": {"at": "2026-10-24T01:00:00+08:00"},
        }
        observation = {"id": "o-time", "dao": "d-time", "kind": "later_session",
                       "at": "2026-10-24T02:00:00+08:00", "matched": True}
        receipt = dao_life.check_field(dao, episodes, [observation], AT)
        self.assertEqual(receipt["verdict"], "not_run")
        observation["at"] = "2026-10-24T08:00:00+08:00"
        self.assertEqual(dao_life.check_field(dao, episodes, [observation], AT)["verdict"], "pass")

    def test_receipt_basis_uses_the_weakest_source_precision(self):
        dao = {"id": "d-time", "version": 1,
               "provenance": [{"episode": "a"}, {"episode": "b"}]}
        observation = {"dao": "d-time", "kind": "later_session",
                       "at": "2026-10-24T12:00:00Z", "matched": True}
        episodes = {"a": {"at": "2026-10-23T23:00:00Z"},
                    "b": {"at": "2026-10-24T00:00:00+08:00"}}
        receipt = dao_life.check_field(dao, episodes, [observation], AT)
        self.assertEqual(receipt["time_basis"], "exact_instants")
        self.assertIn("观察晚于全部来源案例", receipt["note"])
        # One date-only source weakens the whole temporal claim, even across days/zones.
        episodes["b"]["at"] = "2026-10-24"
        receipt = dao_life.check_field(dao, episodes, [observation], AT)
        self.assertEqual(receipt["time_basis"], "date_convention")
        self.assertIn("实际先后未证实", receipt["note"])
        self.assertEqual(receipt["verdict"], "pass")
        episodes = {"a": {"at": "2026-10-23T23:00"}, "b": {"at": "2026-10-24T00:00"}}
        observation["at"] = "2026-10-24T12:00"
        receipt = dao_life.check_field(dao, episodes, [observation], AT)
        self.assertEqual(receipt["time_basis"], "local_times")
        self.assertIn("同一时区", receipt["note"])
        self.assertIn("实际先后未证实", receipt["note"])
        observation["at"] = "2026-10-24T12:00Z"
        receipt = dao_life.check_field(dao, episodes, [observation], AT)
        self.assertEqual(receipt["verdict"], "not_run")
        self.assertIsNone(receipt["time_basis"])

    def test_missing_source_case_time_cannot_be_hidden_by_a_known_one(self):
        dao = {"id": "d-time", "version": 1, "provenance": [{"episode": "a"}, {"episode": "missing"}]}
        observation = {"dao": "d-time", "kind": "later_session", "at": "2026-10-24", "matched": True}
        receipt = dao_life.check_field(dao, {"a": {"at": "2026-10-23"}}, [observation], AT)
        self.assertEqual(receipt["verdict"], "not_run")


if __name__ == "__main__":
    unittest.main()
