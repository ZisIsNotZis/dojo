"""四句问法的演练：引文必须真、问不出来就停、轮数要量出来、库一个字节不动。

这一支测的是「问」而不是「道」：它证明一场会话能把哪几件变成他的，以及不能的时候它不会替人填。
"""

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "docs" / "dao" / "person-dojo"
ELICIT = ROOT / "docs" / "dao" / "elicitation"
SCRIPT = ELICIT / "session-1.txt"


def _module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dao_life = _module("dao_life", ROOT / "scripts" / "dao_life.py")
dao_elicit = _module("dao_elicit", ROOT / "scripts" / "dao_elicit.py")
sys.path.insert(0, str(ROOT))
from dojo.elicit import QUESTIONS  # noqa: E402

AT = "2026-10-23T22:00:00Z"


class ElicitTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="dojo-elicit-"))
        self.script = self.dir / "session.txt"

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def run_script(self, text):
        self.script.write_text(text, encoding="utf-8")
        return dao_elicit.run(LIB, self.script, AT)

    def test_the_replay_measures_what_asking_costs(self):
        report = dao_elicit.run(LIB, SCRIPT, AT)
        self.assertEqual(report["totals"]["entries"], 4)
        self.assertEqual(report["totals"]["parts"], 14)
        self.assertEqual(report["totals"]["filled"], 4)
        self.assertEqual(report["totals"]["unfilled"], 10)
        self.assertEqual(report["totals"]["turns"], 24)
        self.assertEqual(report["totals"]["turns_per_rule"], 6.0)

    def test_every_answer_claimed_as_his_is_verbatim_in_the_event_layer(self):
        text = (
            "entry: dojo-d-001\n"
            "  ask 情境\n"
            "  answer his ep-2026-10-23-detach | 我从来没说过这句话\n"
            "  answer none\n"
            "  ask 张力\n  answer none\n  answer none\n"
            "  ask 代价\n  answer none\n  answer none\n"
            "  ask 失效\n  answer none\n  answer none\n"
        )
        with self.assertRaises(dao_elicit.ElicitError) as caught:
            self.run_script(text)
        self.assertIn("引文不在", str(caught.exception))

    def test_an_answer_from_an_unknown_episode_is_refused(self):
        text = (
            "entry: dojo-d-001\n"
            "  ask 情境\n"
            "  answer his ep-never-recorded | 任何话\n"
            "  answer none\n"
            "  ask 张力\n  answer none\n  answer none\n"
            "  ask 代价\n  answer none\n  answer none\n"
            "  ask 失效\n  answer none\n  answer none\n"
        )
        with self.assertRaises(dao_elicit.ElicitError) as caught:
            self.run_script(text)
        self.assertIn("不在事件层", str(caught.exception))

    def test_asking_a_part_that_is_already_his_is_refused(self):
        text = (
            "entry: dojo-d-005\n"
            "  ask 情境\n  answer none\n  answer none\n"
            "  ask 张力\n  answer none\n  answer none\n"
            "  ask 代价\n  answer none\n  answer none\n"
            "  ask 失效\n  answer none\n  answer none\n"
        )
        with self.assertRaises(dao_elicit.ElicitError) as caught:
            self.run_script(text)
        self.assertIn("不该再问", str(caught.exception))

    def test_skipping_a_part_that_is_still_supplied_is_refused(self):
        text = (
            "entry: dojo-d-005\n"
            "  ask 情境\n  answer none\n  answer none\n"
            "  ask 张力\n  answer none\n  answer none\n"
        )
        with self.assertRaises(dao_elicit.ElicitError) as caught:
            self.run_script(text)
        self.assertIn("要问满", str(caught.exception))

    def test_a_third_turn_is_refused(self):
        text = (
            "entry: dojo-d-001\n"
            "  ask 情境\n  answer none\n  answer none\n  answer none\n"
        )
        with self.assertRaises(dao_elicit.ElicitError) as caught:
            self.run_script(text)
        self.assertIn("第三遍", str(caught.exception))

    def test_when_the_answer_never_comes_the_part_and_the_entry_stay_supplied(self):
        report = dao_elicit.run(LIB, SCRIPT, AT)
        daos = {dao["id"]: dao for dao in json.loads((LIB / "daos.json").read_text(encoding="utf-8"))["daos"]}
        for entry in report["entries"]:
            if not entry["supplied_after"]:
                continue
            projected = dict(daos[entry["id"]])
            projected["part_sources"] = entry["after"]
            self.assertEqual(dao_life.authorship(projected["part_sources"]), "合写", entry["id"])
        # 一场问完，四条道没有一条变成「他的」：每一场都还有问不出来的件
        self.assertTrue(all(entry["supplied_after"] for entry in report["entries"]))

    def test_four_real_quotes_can_make_every_part_his(self):
        quote = "任何道，只要逻辑自洽、说得通、不重复，都可以存在。"
        text = (
            "entry: dojo-d-005\n"
            f"  ask 情境\n  answer his ep-idea-2-2 | {quote}\n"
            f"  ask 张力\n  answer his ep-idea-2-2 | {quote}\n"
            f"  ask 代价\n  answer relayed ep-idea-2-2 | {quote}\n"
        )
        report = self.run_script(text)
        after = report["entries"][0]["after"]
        self.assertEqual([after["situation"], after["tension"], after["price"]], ["他的原话", "他的原话", "转述"])
        self.assertEqual(after["off"], "他的原话")
        daos = {dao["id"]: dao for dao in json.loads((LIB / "daos.json").read_text(encoding="utf-8"))["daos"]}
        projected = dict(daos["dojo-d-005"])
        projected["part_sources"] = after
        self.assertEqual(dao_life.authorship(projected["part_sources"]), "他的")

    def test_the_run_touches_no_library_file(self):
        before = (LIB / "daos.json").read_bytes()
        dao_elicit.run(LIB, SCRIPT, AT)
        self.assertEqual(before, (LIB / "daos.json").read_bytes())

    def test_the_report_says_what_a_live_session_would_have_to_hear(self):
        report = dao_elicit.run(LIB, SCRIPT, AT)
        page = dao_elicit.render(report, SCRIPT, {"parts": [{"part": name, **value} for name, value in QUESTIONS.items()]})
        self.assertIn("要变成他的，还得听他说出这样一句", page)
        self.assertIn("一句说出「另一件好事」的话", page)
        self.assertIn("停「系统补」", page)
        self.assertIn("平均每条道 6.0 轮", page)


if __name__ == "__main__":
    unittest.main()
