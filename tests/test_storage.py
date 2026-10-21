import json
import tempfile
import unittest
from pathlib import Path

from dojo.storage import DojoError, DuplicateContent, Store, independence, load_simulated_seeds


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

    def _single_session_card(self, session="sess-a", candidate_id="d-session"):
        return self.store.add(
            "交接前先把当前版本的范围写下来，能减少返工。", "application", candidate_id=candidate_id,
            scope=["交接"], session=session,
            sources=[{
                "type": "unknown", "claim": "本次讨论会话形成的结论；内容未经独立核验。",
                "independence_group": session, "verification": "unknown",
                "scope_note": "单一会话来源；不构成独立佐证。",
            }],
        )

    def test_single_session_card_is_visible_to_search_but_not_to_broadcast(self):
        self._single_session_card()
        self.store.confirm("d-session", "worth discussing")
        searched = [item["id"] for item in self.store.retrieve("交接 版本 范围")["results"]]
        self.assertEqual(["d-session"], searched)
        broadcast = self.store.broadcast("交接 版本 范围")
        self.assertEqual([], broadcast["results"])
        self.assertEqual(["d-session"], [item["id"] for item in broadcast["suppressed"]])
        self.assertIn("single-session provenance", broadcast["suppressed"][0]["reason"])

    def test_a_second_independence_group_makes_a_card_broadcastable(self):
        self.store.add(
            "交接前先把当前版本的范围写下来，能减少返工。", "application", candidate_id="d-two-groups",
            scope=["交接"], session="sess-a",
            sources=[
                {"type": "unknown", "claim": "本次会话形成的结论", "independence_group": "sess-a", "verification": "unknown"},
                {"type": "claimed_firsthand", "claim": "另一位互不相关的会话也独立得出相容主张", "independence_group": "sess-b", "verification": "unverified"},
            ],
        )
        self.store.confirm("d-two-groups", "worth discussing")
        broadcast = self.store.broadcast("交接 版本 范围")
        self.assertEqual(["d-two-groups"], [item["id"] for item in broadcast["results"]])
        self.assertEqual(["sess-a", "sess-b"], broadcast["results"][0]["independence"]["independence_groups"])
        self.assertTrue(broadcast["results"][0]["independence"]["independent"])
        self.assertEqual([], broadcast["suppressed"])

    def test_broadcast_excludes_the_asking_session_even_with_two_groups(self):
        self.store.add(
            "交接前先把当前版本的范围写下来，能减少返工。", "application", candidate_id="d-own",
            scope=["交接"], session="sess-a",
            sources=[
                {"type": "unknown", "claim": "本次会话形成的结论", "independence_group": "sess-a", "verification": "unknown"},
                {"type": "claimed_firsthand", "claim": "另一独立会话得出相容主张", "independence_group": "sess-b", "verification": "unverified"},
            ],
        )
        self.store.confirm("d-own", "worth discussing")
        self.assertEqual(1, len(self.store.broadcast("交接 版本 范围")["results"]))
        own = self.store.broadcast("交接 版本 范围", exclude_session="sess-a")
        self.assertEqual([], own["results"])
        self.assertIn("its own word back", own["suppressed"][0]["reason"])

    def test_export_c_refuses_single_session_provenance_and_names_independence(self):
        self._single_session_card()
        self.store.confirm("d-session", "worth discussing")
        outdir = self.root / "exports"
        with self.assertRaises(DojoError):
            self.store.export_prompt("c", ["d-session"], 6000, outdir)
        self.assertFalse(outdir.exists() and any(outdir.iterdir()))
        self.store.add(
            "交接时把未验证的假设单独列出来，能减少返工。", "application", candidate_id="d-two-groups",
            scope=["交接"], session="sess-a",
            sources=[
                {"type": "unknown", "claim": "本次会话形成的结论", "independence_group": "sess-a", "verification": "unknown"},
                {"type": "claimed_firsthand", "claim": "另一独立会话得出相容主张", "independence_group": "sess-b", "verification": "unverified"},
            ],
        )
        self.store.confirm("d-two-groups", "worth discussing")
        exported = self.store.export_prompt("c", ["d-two-groups"], 6000, outdir)
        text = Path(exported["path"]).read_text(encoding="utf-8")
        self.assertIn("independence_groups=2", text)
        self.assertIn("independent=true", text)

    def test_independence_counts_no_group_when_sources_say_unknown(self):
        self.add(candidate_id="d-unknown", sources=[{"type": "unknown", "claim": "来源未知", "verification": "unknown"}])
        shown = self.store.show("d-unknown")["candidate"]
        info = independence(shown)
        self.assertEqual([], info["independence_groups"])
        self.assertFalse(info["independent"])
        self.assertFalse(info["single_session"])

    def test_duplicate_content_creates_no_second_card_and_no_version(self):
        first = self.add("d-first", "交接前先写下当前版本的范围，能减少返工。", scope=["交接"])
        before = len(self.store.list_candidates()), self.store.history("d-first")["versions"][-1]["version"]
        with self.assertRaises(DuplicateContent) as caught:
            self.add("d-second", "交接前先写下当前版本的范围，能减少返工。", scope=["交接"])
        self.assertEqual("d-first", caught.exception.candidate_id)
        self.assertIn("no new version was created", str(caught.exception))
        self.assertEqual(before, (len(self.store.list_candidates()), self.store.history("d-first")["versions"][-1]["version"]))
        self.assertEqual(1, first["version"])

    def test_duplicate_is_content_not_spacing_or_list_order(self):
        self.add("d-first", "交接前先写下当前版本的范围，能减少返工。", scope=["交接", "上线前"])
        with self.assertRaises(DuplicateContent):
            self.store.add(
                "  交接前先写下当前版本的范围，能减少返工。 ", "abstract_idea",
                candidate_id="d-second", scope=["上线前", "交接"],
            )

    def test_a_different_scope_or_wording_is_not_a_duplicate(self):
        self.add("d-first", "交接前先写下当前版本的范围，能减少返工。", scope=["交接"])
        other_scope = self.add("d-second", "交接前先写下当前版本的范围，能减少返工。", scope=["多人协作交接"])
        other_wording = self.add("d-third", "交接前先写下这次要交接的范围。", scope=["交接"])
        self.assertEqual(3, len(self.store.list_candidates()))
        self.assertEqual("d-second", other_scope["id"])
        self.assertEqual("d-third", other_wording["id"])

    def test_attach_source_turns_a_duplicate_into_a_second_independence_group(self):
        source = {"id": "src-a", "type": "unknown", "claim": "第一次会话的结论", "independence_group": "sess-a", "verification": "unknown"}
        self.store.add(
            "交接前先写下当前版本的范围，能减少返工。", "application", candidate_id="d-one",
            scope=["交接"], session="sess-a", sources=[source],
        )
        self.store.confirm("d-one", "worth discussing")
        self.assertFalse(independence(self.store.show("d-one")["candidate"])["independent"])
        with self.assertRaises(DuplicateContent):
            self.store.add(
                "交接前先写下当前版本的范围，能减少返工。", "application", candidate_id="d-two",
                scope=["交接"], session="sess-b",
                sources=[{"id": "src-b", "type": "unknown", "claim": "第二次会话独立得出同一结论", "independence_group": "sess-b", "verification": "unknown"}],
            )
        attached = self.store.attach_source(
            "d-one",
            {"id": "src-b", "type": "unknown", "claim": "第二次会话独立得出同一结论", "independence_group": "sess-b", "verification": "unknown"},
            "sess-b",
        )
        info = independence(attached)
        self.assertEqual(["sess-a", "sess-b"], info["independence_groups"])
        self.assertTrue(info["independent"])
        self.assertEqual("attach_source", self.store.history("d-one")["events"][-1]["event"])
        self.assertEqual(["d-one"], [item["id"] for item in self.store.broadcast("交接 范围 返工")["results"]])

    def test_attaching_the_same_session_twice_is_a_no_op(self):
        self.store.add(
            "交接前先写下当前版本的范围，能减少返工。", "application", candidate_id="d-one",
            scope=["交接"], session="sess-a",
            sources=[{"id": "src-a", "type": "unknown", "claim": "会话结论", "independence_group": "sess-a", "verification": "unknown"}],
        )
        before = self.store.show("d-one")["candidate"]
        events_before = len(self.store.history("d-one")["events"])
        again = self.store.attach_source(
            "d-one",
            {"id": "src-b", "type": "unknown", "claim": "同一会话再次跑到同一结论", "independence_group": "sess-a", "verification": "unknown"},
            "sess-a",
        )
        self.assertEqual(before, again)
        self.assertEqual(before, self.store.show("d-one")["candidate"])
        self.assertEqual(events_before, len(self.store.history("d-one")["events"]))

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
