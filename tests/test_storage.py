import json
import tempfile
import unittest
from pathlib import Path

from dojo.storage import DojoError, Store, load_simulated_seeds


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "dojo.sqlite3")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def add(self, candidate_id="d-one", statement="交接约定值得讨论", sources=None, **kwargs):
        return self.store.add(
            statement, "abstract_idea", candidate_id=candidate_id,
            sources=sources or [], **kwargs,
        )

    def test_seed_load_is_four_simulated_and_idempotent(self):
        first = load_simulated_seeds(self.store)
        events_before = self.store.connection.execute("SELECT count(*) FROM events").fetchone()[0]
        second = load_simulated_seeds(self.store)
        self.assertTrue(first["loaded"])
        self.assertFalse(second["loaded"])
        self.assertEqual(4, len(self.store.list_candidates()))
        self.assertEqual(events_before, self.store.connection.execute("SELECT count(*) FROM events").fetchone()[0])
        s04 = self.store.show("seed-m04")["candidate"]["sources"][0]
        self.assertEqual("unverified", s04["verification"])
        self.assertEqual("unknown", s04["independence_group"])

    def test_confirm_revoke_is_discussability_only_and_versions_are_immutable(self):
        self.add()
        confirmed = self.store.confirm("d-one", "clear enough to inspect", "s-a")
        self.assertEqual("discussable", confirmed["status"])
        self.assertTrue(confirmed["confirmation"]["not_truth_claim"])
        self.assertEqual(2, confirmed["version"])
        self.store.revoke("d-one", "scope still unclear")
        revoked = self.store.show("d-one")["candidate"]
        self.assertEqual("draft", revoked["status"])
        self.assertFalse(revoked["confirmation"]["active"])
        history = self.store.history("d-one")["versions"]
        self.assertEqual([1, 2, 3], [item["version"] for item in history])
        self.assertEqual("draft", history[0]["state"]["status"])
        self.assertEqual("discussable", history[1]["state"]["status"])
        self.assertEqual([], self.store.retrieve("交接")["results"])

    def test_challenge_revision_and_alias_link_versions_preserve_sources(self):
        source = {"id": "src-a", "type": "abstract_reasoning", "claim": "抽象推理", "verification": "not_evidence"}
        self.add(sources=[source])
        self.store.confirm("d-one", "worth discussion")
        self.store.challenge("d-one", "旧插件是否仍受支持未知")
        challenged = self.store.show("d-one")["candidate"]
        self.assertEqual("challenged", challenged["status"])
        self.assertEqual(["旧插件是否仍受支持未知"], challenged["contradictions"])
        self.store.revise("d-one", "仅在支持版本范围明确时检查交接", "加入边界")
        self.store.alias("d-one", "支持版本范围明确时检查组件交接", "等价表述")
        self.add("d-two", "另一条候选")
        self.store.link("d-one", "challenges", "d-two", "条件不同")
        final = self.store.show("d-one")["candidate"]
        self.assertEqual(6, final["version"])
        self.assertEqual(source["id"], final["sources"][0]["id"])
        self.assertIn("支持版本范围明确时检查组件交接", final["aliases"])
        self.assertEqual("challenges", final["relations"][0]["type"])
        self.assertEqual([1, 2, 3, 4, 5, 6], [item["version"] for item in self.store.history("d-one")["versions"]])

    def test_invalid_link_and_malformed_split_are_atomic(self):
        self.add()
        self.add("d-two", "另一个候选")
        before = self.store.show("d-one")["candidate"]
        event_count = self.store.connection.execute("SELECT count(*) FROM events").fetchone()[0]
        for call in (
            lambda: self.store.link("d-one", "supports", "d-one", "self"),
            lambda: self.store.link("d-one", "supports", "missing", "missing target"),
            lambda: self.store.link("d-one", "not-a-relation", "d-two", "invalid type"),
        ):
            with self.assertRaises(DojoError):
                call()
        with self.assertRaises(DojoError):
            self.store.split("d-one", [{"statement": "one"}, {"statement": ""}], "bad split")
        after = self.store.show("d-one")["candidate"]
        self.assertEqual(before, after)
        self.assertEqual(event_count, self.store.connection.execute("SELECT count(*) FROM events").fetchone()[0])
        self.assertEqual(2, len(self.store.list_candidates()))

    def test_split_preserves_source_ids_and_parent_history(self):
        source = {"id": "src-split", "type": "claimed_firsthand", "claim": "未核验报告", "verification": "unverified"}
        self.add(sources=[source])
        children = self.store.split(
            "d-one",
            [{"id": "d-left", "statement": "情况甲", "source_ids": ["src-split"]},
             {"id": "d-right", "statement": "情况乙", "source_ids": ["src-split"]}],
            "条件分开",
        )
        self.assertEqual({"d-left", "d-right"}, {child["id"] for child in children})
        parent = self.store.show("d-one")["candidate"]
        self.assertEqual("superseded", parent["status"])
        self.assertEqual(2, parent["version"])
        for child_id in ("d-left", "d-right"):
            child = self.store.show(child_id)["candidate"]
            self.assertEqual("src-split", child["sources"][0]["id"])
            self.assertEqual("unverified", child["sources"][0]["verification"])
        self.assertEqual([1, 2], [v["version"] for v in self.store.history("d-one")["versions"]])

    def test_merge_requires_explicit_confirmation_and_unmerge_restores_sources(self):
        left_source = {"id": "src-left", "type": "abstract_reasoning", "claim": "源左", "verification": "not_evidence"}
        right_source = {"id": "src-right", "type": "claimed_firsthand", "claim": "源右", "verification": "unverified"}
        self.add("d-left", "同一主张措辞甲", sources=[left_source])
        self.add("d-right", "同一主张措辞乙", sources=[right_source])
        self.store.confirm("d-left", "当前措辞可讨论")
        with self.assertRaises(DojoError):
            self.store.merge("d-right", "d-left", confirmed=False, reason="equivalent")
        self.assertEqual(2, self.store.show("d-left")["candidate"]["version"])
        merged = self.store.merge("d-right", "d-left", confirmed=True, reason="人工确认范围等价")
        self.assertEqual({"src-left", "src-right"}, {item["id"] for item in merged["sources"]})
        self.assertIn("同一主张措辞乙", merged["aliases"])
        self.assertEqual("d-left", self.store.show("d-right")["resolved_id"])
        self.assertEqual("d-left", self.store.retrieve("主张")["results"][0]["id"])
        restored = self.store.unmerge("d-right", "复核后撤销")
        self.assertEqual("draft", restored["source"]["status"])
        self.assertEqual("d-right", restored["source"]["id"])
        self.assertEqual(["src-left"], [item["id"] for item in restored["target"]["sources"]])
        self.assertEqual(["src-right"], [item["id"] for item in restored["source"]["sources"]])
        self.assertNotIn("redirect_to", restored["source"])
        self.assertEqual([1, 2, 3], [v["version"] for v in self.store.history("d-right")["versions"]])
        self.assertEqual([1, 2, 3, 4], [v["version"] for v in self.store.history("d-left")["versions"]])

    def test_unmerge_rejects_intervening_change_without_partial_restore(self):
        self.add("d-left", "等价甲")
        self.add("d-right", "等价乙")
        self.store.merge("d-right", "d-left", confirmed=True, reason="manual")
        self.store.alias("d-left", "人工添加别名", "later change")
        source_before = self.store.show("d-right")["candidate"]
        target_before = self.store.show("d-left")["candidate"]
        with self.assertRaises(DojoError):
            self.store.unmerge("d-right", "attempt")
        self.assertEqual(source_before, self.store.show("d-right")["candidate"])
        self.assertEqual(target_before, self.store.show("d-left")["candidate"])

    def test_redirect_cycle_detection_and_canonical_self_link_guard(self):
        self.add("d-a", "A")
        self.add("d-b", "B")
        self.add("d-observer", "observes B")
        self.store.link("d-observer", "supports", "d-b", "pre-merge relation")
        self.store.merge("d-b", "d-a", confirmed=True, reason="manual")
        with self.assertRaises(DojoError):
            self.store.link("d-a", "supports", "d-b", "redirect resolves to self")
        displayed_relation = self.store.show("d-observer")["candidate"]["relations"][0]
        self.assertEqual("d-a", displayed_relation["target"])
        self.assertEqual("d-b", displayed_relation["redirected_from"])
        with self.store.transaction():
            current = self.store._get("d-b")
            current["redirect_to"] = "d-b"
            self.store.connection.execute("UPDATE candidates SET state_json=? WHERE id=?", (json.dumps(current), "d-b"))
        with self.assertRaises(DojoError):
            self.store.show("d-b")

    def test_retrieval_is_empty_transparent_chinese_lexical_and_status_filtered(self):
        self.add("d-draft", "中文摩擦持续条件")
        self.add(
            "d-ready", "中文摩擦持续条件", scope=["日常整理"],
            unknowns=["旧插件支持范围未知"], contradictions=["支持范围确认前不可推广"],
            sources=[{"id": "src-ready", "type": "unknown", "claim": "未核实来源摘要", "verification": "unknown"}],
        )
        self.store.confirm("d-ready", "值得检索")
        self.add("d-other", "天气很好")
        self.store.confirm("d-other", "可讨论")
        self.assertEqual([], self.store.retrieve("")["results"])
        self.assertEqual([], self.store.retrieve("不存在的词")["results"])
        result = self.store.retrieve("摩擦持续")
        self.assertEqual("transparent lexical overlap (distinct query terms only); not semantic search or truth ranking", result["method"])
        self.assertEqual("d-ready", result["results"][0]["id"])
        self.assertEqual("discussable", result["results"][0]["status"])
        self.assertIn("摩擦", result["results"][0]["matched_terms"])
        self.assertEqual(["旧插件支持范围未知"], result["results"][0]["unknowns"])
        self.assertEqual(["支持范围确认前不可推广"], result["results"][0]["contradictions"])
        self.assertEqual("src-ready", result["results"][0]["sources"][0]["id"])
        self.assertEqual(["日常整理"], result["results"][0]["scope"])
        self.assertNotIn("d-draft", [row["id"] for row in result["results"]])
        self.store.withdraw("d-ready", "不再检索")
        self.assertEqual([], self.store.retrieve("摩擦")["results"])

    def test_export_b_c_budget_ids_unverified_state_and_no_silent_overwrite(self):
        load_simulated_seeds(self.store)
        outdir = self.root / "separate-exports"
        b = self.store.export_prompt("b", [], 4000, outdir)
        c = self.store.export_prompt("c", ["seed-m04"], 6000, outdir)
        b_text = Path(b["path"]).read_text(encoding="utf-8")
        c_text = Path(c["path"]).read_text(encoding="utf-8")
        self.assertNotIn("seed-m04", b_text)
        self.assertIn("Target case:", b_text)
        self.assertIn("seed-m04", c_text)
        b_target = b_text.split("Target case:\n", 1)[1].split("\n\nRespond", 1)[0]
        c_target = c_text.split("Target case:\n", 1)[1].split("\n\nExplicitly selected dojo excerpts", 1)[0]
        self.assertEqual(b_target, c_target)
        self.assertIn("src-m04", c_text)
        self.assertIn("verification=unverified", c_text)
        self.assertNotIn("Actor-only", c_text)
        self.assertNotIn("facilitator notes", c_text.lower())
        self.assertLessEqual(b["characters"], b["budget_chars"])
        self.assertLessEqual(c["characters"], c["budget_chars"])
        before = list(outdir.iterdir())
        with self.assertRaises(DojoError):
            self.store.export_prompt("c", ["seed-m04"], 100, outdir)
        self.assertEqual(before, list(outdir.iterdir()))
        with self.assertRaises(DojoError):
            self.store.export_prompt("c", ["seed-m01", "seed-m01"], 6000, outdir)
        self.assertEqual(len({b["path"], c["path"]}), 2)

    def test_abstain_is_event_only_and_does_not_increment_version(self):
        self.add()
        before = self.store.show("d-one")["candidate"]
        abstention = self.store.abstain("不知道是否等价", "d-one", "查来源")
        after = self.store.show("d-one")["candidate"]
        self.assertEqual(before, after)
        self.assertEqual("abstain", self.store.history("d-one")["events"][-1]["event"])
        self.assertEqual("d-one", abstention["candidate_id"])


if __name__ == "__main__":
    unittest.main()
