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
QUOTE = "只有两张虚构蓝签都固定后，才把记录交给下一班。"
EPISODE = "synthetic-blue-labels"
PART_KEYS = {"情境": "situation", "张力": "tension", "代价": "price", "失效": "off"}


def seed_library(root, replay):
    root.mkdir()
    daos = []
    lines = []
    for i in range(1, 5):
        entry = f"synthetic-rule-{i}"
        sources = dict.fromkeys(PART_KEYS.values(), "系统补")
        if i >= 3:
            sources["off"] = "他的原话"
        daos.append({"id": entry, "part_sources": sources})
        lines.append(f"entry: {entry}")
        for part, key in PART_KEYS.items():
            if sources[key] != "系统补":
                continue
            lines.append(f"  ask {part}")
            if part == "情境":
                lines.append(f"  answer his {EPISODE} | {QUOTE}")
            else:
                lines.extend(["  answer none", "  answer none"])
    for name, payload in (
        ("daos", {"daos": daos}),
        ("episodes", {"episodes": [{"id": EPISODE, "quote": QUOTE}]}),
    ):
        (root / f"{name}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    replay.write_text("\n".join(lines) + "\n", encoding="utf-8")


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
        self.library = self.dir / "synthetic-library"
        self.replay = self.dir / "replay.txt"
        seed_library(self.library, self.replay)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def run_script(self, text):
        self.script.write_text(text, encoding="utf-8")
        return dao_elicit.run(self.library, self.script, AT)

    def test_the_replay_measures_what_asking_costs(self):
        report = dao_elicit.run(self.library, self.replay, AT)
        self.assertEqual(report["totals"]["entries"], 4)
        self.assertEqual(report["totals"]["parts"], 14)
        self.assertEqual(report["totals"]["filled"], 4)
        self.assertEqual(report["totals"]["unfilled"], 10)
        self.assertEqual(report["totals"]["turns"], 24)
        self.assertEqual(report["totals"]["turns_per_rule"], 6.0)

    def test_every_answer_claimed_as_his_is_verbatim_in_the_event_layer(self):
        text = (
            "entry: synthetic-rule-1\n"
            "  ask 情境\n"
            "  answer his synthetic-blue-labels | 我从来没说过这句话\n"
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
            "entry: synthetic-rule-1\n"
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
            "entry: synthetic-rule-3\n"
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
            "entry: synthetic-rule-3\n"
            "  ask 情境\n  answer none\n  answer none\n"
            "  ask 张力\n  answer none\n  answer none\n"
        )
        with self.assertRaises(dao_elicit.ElicitError) as caught:
            self.run_script(text)
        self.assertIn("要问满", str(caught.exception))

    def test_a_third_turn_is_refused(self):
        text = (
            "entry: synthetic-rule-1\n"
            "  ask 情境\n  answer none\n  answer none\n  answer none\n"
        )
        with self.assertRaises(dao_elicit.ElicitError) as caught:
            self.run_script(text)
        self.assertIn("第三遍", str(caught.exception))

    def test_when_the_answer_never_comes_the_part_and_the_entry_stay_supplied(self):
        report = dao_elicit.run(self.library, self.replay, AT)
        daos = {dao["id"]: dao for dao in json.loads((self.library / "daos.json").read_text(encoding="utf-8"))["daos"]}
        for entry in report["entries"]:
            if not entry["supplied_after"]:
                continue
            projected = dict(daos[entry["id"]])
            projected["part_sources"] = entry["after"]
            self.assertEqual(dao_life.authorship(projected["part_sources"]), "合写", entry["id"])
        # 一场问完，四条道没有一条变成「他的」：每一场都还有问不出来的件
        self.assertTrue(all(entry["supplied_after"] for entry in report["entries"]))

    def test_verbatim_fixture_quotes_can_complete_a_rule(self):
        quote = QUOTE
        text = (
            "entry: synthetic-rule-3\n"
            f"  ask 情境\n  answer his synthetic-blue-labels | {quote}\n"
            f"  ask 张力\n  answer his synthetic-blue-labels | {quote}\n"
            f"  ask 代价\n  answer relayed synthetic-blue-labels | {quote}\n"
        )
        report = self.run_script(text)
        after = report["entries"][0]["after"]
        self.assertEqual([after["situation"], after["tension"], after["price"]], ["他的原话", "他的原话", "转述"])
        self.assertEqual(after["off"], "他的原话")
        daos = {dao["id"]: dao for dao in json.loads((self.library / "daos.json").read_text(encoding="utf-8"))["daos"]}
        projected = dict(daos["synthetic-rule-3"])
        projected["part_sources"] = after
        self.assertEqual(dao_life.authorship(projected["part_sources"]), "他的")

    def test_the_run_touches_no_library_file(self):
        before = {p.name: p.read_bytes() for p in self.library.iterdir()}
        dao_elicit.run(self.library, self.replay, AT)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.library.iterdir()})

    def test_the_report_says_what_a_live_session_would_have_to_hear(self):
        report = dao_elicit.run(self.library, self.replay, AT)
        page = dao_elicit.render(report, self.replay, {"parts": [{"part": name, **value} for name, value in QUESTIONS.items()]})
        self.assertIn("要变成他的，还得听他说出这样一句", page)
        self.assertIn("一句说出「另一件好事」的话", page)
        self.assertIn("停「系统补」", page)
        self.assertIn("平均每条道 6.0 轮", page)


if __name__ == "__main__":
    unittest.main()
