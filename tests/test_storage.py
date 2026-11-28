import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from dojo import live
from dojo.storage import (
    DojoError, DuplicateContent, MergeRefused, Store, independence, is_unaccepted_draft,
    load_simulated_seeds, wording_digest,
)


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

    def test_adoption_retry_requires_the_whole_original_ask(self):
        self.add(statement="开始时的模拟表述")
        self.add("d-target", "等待采纳的原卡")
        self.store.confirm("d-target", "模拟可讨论")
        self.store.revise("d-target", "当前版模拟表述", "收窄到新版")
        self.store.link("d-one", "narrows", "d-target", "模拟改写依据")
        link, = self.store.show("d-target", include_incoming_links=True)["incoming_links"]
        seq = link["sequence"]
        ask = dict(statement="采纳后的模拟表述", reason="采纳模拟收窄", session="s-a",
                   scope=["模拟范围甲"])
        adopted = self.store.revise("d-target", adopt_link_sequence=seq, **ask)
        self.assertEqual(4, adopted["version"])
        first_revise = self.store.history("d-target")["events"][-1]
        replay = self.store.revise("d-target", adopt_link_sequence=seq, **ask)
        history = self.store.history("d-target")
        self.assertEqual(4, replay["version"])
        self.assertEqual({"link_sequence": seq, "repeat_of": first_revise["sequence"], "adopted_version": 4,
                          "current_version": 4}, replay["adoption_replay"])
        for field, value in (("statement", ask["statement"] + "x"), ("reason", "不同理由"),
                             ("session", None), ("scope", ["模拟范围乙"])):
            with self.subTest(field=field), self.assertRaises(DojoError):
                self.store.revise("d-target", adopt_link_sequence=seq, **{**ask, field: value})
        self.assertEqual(adopted, self.store.show("d-target")["candidate"])
        self.assertEqual("revise.repeat", history["events"][-1]["event"])
        self.assertEqual(history, self.store.history("d-target"))

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

    def test_export_c_carries_every_source_field_including_scope_note(self):
        """`scope_note` is the one field that bounds a source; the export dropped it.

        r113 measured the C prompt and found five of six source fields: `scope_note`
        was missing from the printed line (`storage.py:1040-1043`). Without it a
        participant receives "我在两次交接里都吃过口头改口的亏" with no way to know the
        claim covers two handovers in one team, not handovers generally.

        Checked **by value**, each source's own text, and the two sources carry
        different notes: a "six of six" satisfied by one source's note appearing twice,
        or by a key name whose value happens to appear elsewhere in the prompt, would
        pass a key-name test and say nothing about what a reader can actually see.
        """
        self.store.add(
            "交接前先把当前版本的范围写下来，能减少临场改口。", "application",
            candidate_id="d-six", scope=["交接"], session="sess-x",
            sources=[
                {"id": "src-x", "type": "claimed_firsthand", "verification": "unverified",
                 "claim": "我在两次交接里都吃过口头改口的亏", "independence_group": "person-x",
                 "scope_note": "两次都在同一团队"},
                {"id": "src-y", "type": "abstract_reasoning", "verification": "not_evidence",
                 "claim": "书面范围把隐式假设变成可检查项", "independence_group": "method-v1",
                 "scope_note": "推演，不是观察"},
            ],
        )
        self.store.confirm("d-six", "可讨论，不是真")
        state = self.store.show("d-six")["candidate"]
        exported = self.store.export_prompt("c", ["d-six"], 8000, self.root / "exports")
        text = Path(exported["path"]).read_text(encoding="utf-8")
        for source in state["sources"]:
            for field in ("id", "type", "verification", "independence_group", "claim", "scope_note"):
                self.assertIn(source[field], text,
                              f"{source['id']}.{field} did not reach the export prompt")
        lines = [line for line in text.splitlines() if line.startswith("- src-")]
        self.assertEqual(2, len(lines))
        self.assertIn("两次都在同一团队", lines[0])
        self.assertIn("推演，不是观察", lines[1])

    def test_export_omits_scope_note_stub_when_the_card_has_none(self):
        """No note must not become a `scope_note:` with nothing after it.

        The card's source JSON can omit `scope_note`; `_normalize_source` then stores
        `""`. Printing an empty stub would claim a caveat was recorded and is blank,
        which reads differently from "this source states no limit".
        """
        self.store.add(
            "交接前先把当前版本的范围写下来，能减少临场改口。", "application",
            candidate_id="d-nonote", scope=["交接"], session="sess-x",
            sources=[
                {"id": "src-n", "type": "claimed_firsthand", "verification": "unverified",
                 "claim": "没有记录范围的一次观察", "independence_group": "person-n"},
                {"id": "src-m", "type": "abstract_reasoning", "verification": "not_evidence",
                 "claim": "推演出来的检查项", "independence_group": "method-v1"},
            ],
        )
        self.store.confirm("d-nonote", "可讨论，不是真")
        exported = self.store.export_prompt("c", ["d-nonote"], 8000, self.root / "exports")
        text = Path(exported["path"]).read_text(encoding="utf-8")
        self.assertIn("src-n", text)
        self.assertNotIn("scope_note:", text)

    def _single_session_card(self, session="sess-a", candidate_id="d-session",
                             statement="交接前先把当前版本的范围写下来，能减少返工。"):
        return self.store.add(
            statement, "application", candidate_id=candidate_id,
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

    def test_a_group_less_source_attached_by_two_sessions_is_two_provenances(self):
        """#1831b: the leak. Both people really arrived; the ledger now says so.

        Two sessions each brought their own material back and neither named a group
        (`add --session a --source-json <no group>`, then `attach-source --session b`).
        The old reader could attribute only the attached one, so the card came out
        `single_session` and `broadcast` refused it -- a real second sighting thrown
        away. Red on the pre-change bytes (`.scratch/dojo-1831b/storage_before.py`:
        refused, `provenance_groups=['sess-b']`).
        """
        self.store.add(
            "两个人各自带回材料，谁都没有登记组名。", "application", candidate_id="d-two-real",
            session="sess-a",
            sources=[{"type": "unknown", "claim": "会话 A 带回的材料，未登记组名。",
                      "independence_group": "unknown", "verification": "unverified"}],
        )
        self.store.attach_source("d-two-real", {
            "type": "unknown", "claim": "会话 B 带回的材料，未登记组名。",
            "independence_group": "unknown", "verification": "unverified",
        }, session="sess-b")
        self.store.confirm("d-two-real", "worth discussing", session="sess-b")
        info = independence(self.store.show("d-two-real")["candidate"],
                            self.store._acquisition_events("d-two-real"))
        self.assertEqual(["sess-a", "sess-b"], info["provenance_groups"])
        self.assertEqual("cross_session", info["provenance_status"])
        self.assertEqual([], info["unattributed_source_ids"])
        self.assertEqual(["d-two-real"],
                         [item["id"] for item in self.store.broadcast("两个人 材料 组名")["results"]])

    def test_one_session_writing_its_own_group_less_source_is_not_admitted(self):
        """#1831b: the inflation, in the same change. Absence is not a pass.

        One session, one source, no group named. Nothing on disk says a second person
        exists, so this must not go out. The old reader attributed neither, reported
        `unidentified`, and `broadcast` let it through -- the shape `:173` forbids.
        Red on the pre-change bytes (admitted, `provenance_groups=[]`).
        """
        self.store.add(
            "一个会话自己写下的结论，来源没登记组名。", "application", candidate_id="d-own-word",
            session="sess-a",
            sources=[{"type": "unknown", "claim": "会话 A 自己的结论，未登记组名。",
                      "independence_group": "unknown", "verification": "unverified"}],
        )
        self.store.confirm("d-own-word", "worth discussing", session="sess-a")
        info = independence(self.store.show("d-own-word")["candidate"],
                            self.store._acquisition_events("d-own-word"))
        self.assertEqual(["sess-a"], info["provenance_groups"])
        self.assertEqual("single_session", info["provenance_status"])
        self.assertTrue(info["single_session"])
        self.assertEqual([], self.store.broadcast("一个会话 自己 结论 组名")["results"])

    def test_an_event_written_before_this_change_is_not_backfilled(self):
        """No guessed attribution: a card written without source ids keeps its answer.

        A library written by the old bytes has `add` events that name no sources. The
        new reader must read that as "cannot attribute", not invent the writing session
        for every group-less source -- inventing it would silently re-judge old
        libraries (and hand every seed card to whoever happened to load it).
        """
        self.store.add(
            "旧字节写下的卡：事件里没有来源 id。", "application", candidate_id="d-legacy",
            session="sess-a",
            sources=[{"type": "unknown", "claim": "旧字节写的来源。",
                      "independence_group": "unknown", "verification": "unverified"}],
        )
        self.store.connection.execute(
            "UPDATE events SET details_json=? WHERE candidate_id='d-legacy' AND event='add'",
            ('{"session": "sess-a"}',),
        )
        self.store.connection.commit()
        info = independence(self.store.show("d-legacy")["candidate"],
                            self.store._acquisition_events("d-legacy"))
        self.assertEqual([], info["provenance_groups"])
        self.assertEqual("unidentified", info["provenance_status"])
        self.assertEqual(1, len(info["unattributed_source_ids"]))

    def test_a_card_with_no_sources_but_a_writing_session_is_not_broadcast(self):
        """The empty case: no group list at all, so the old guard read it as not single-session."""
        self.store.add(
            "交接前把当前版本的范围写下来，可以减少临场改口。", "application", candidate_id="d-bare",
            scope=["交接"], session="sess-a",
        )
        self.store.confirm("d-bare", "worth discussing", session="sess-a")
        info = independence(self.store.resolve("d-bare")[0])
        self.assertEqual(["sess-a"], info["provenance_groups"])
        self.assertEqual("single_session", info["provenance_status"])
        self.assertTrue(info["single_session"])
        broadcast = self.store.broadcast("交接 版本 范围")
        self.assertEqual([], broadcast["results"])
        self.assertEqual(["d-bare"], [item["id"] for item in broadcast["suppressed"]])
        outdir = self.root / "exports"
        with self.assertRaises(DojoError):
            self.store.export_prompt("c", ["d-bare"], 6000, outdir)
        self.assertFalse(outdir.exists() and any(outdir.iterdir()))

    def test_the_asking_session_is_excluded_when_only_a_source_names_it(self):
        self.store.add(
            "交接清单的范围在开始前固定下来，可以减少返工。", "application", candidate_id="d-named-only",
            scope=["交接"],
            sources=[{
                "type": "unknown", "claim": "某会话形成的结论",
                "independence_group": "sess-a", "verification": "unknown",
            }],
        )
        self.store.confirm("d-named-only", "worth discussing")
        self.assertEqual(1, len(self.store.broadcast("交接 清单 范围")["results"]))
        own = self.store.broadcast("交接 清单 范围", exclude_session="sess-a")
        self.assertEqual([], own["results"])
        self.assertIn("its own word back", own["suppressed"][0]["reason"])

    def test_one_non_session_group_is_admitted_and_reported_unidentified(self):
        """The undecided boundary: seed / methodology material is neither one session's
        word nor two independent ones. It is admitted and its absence of provenance is
        named; whether broadcast should require two groups is the person's call."""
        self.store.add(
            "降低启动摩擦通常比反复下决心更可持续。", "abstract_idea", candidate_id="d-method",
            scope=["交接"],
            sources=[{
                "type": "abstract_reasoning", "claim": "模拟场景推演",
                "independence_group": "stranger-methodology-v1", "verification": "not_evidence",
            }],
        )
        self.store.confirm("d-method", "worth discussing")
        broadcast = self.store.broadcast("交接 摩擦 可持续")
        self.assertEqual(["d-method"], [item["id"] for item in broadcast["results"]])
        info = broadcast["results"][0]["independence"]
        self.assertEqual("unidentified", info["provenance_status"])
        self.assertFalse(info["independent"])
        self.assertFalse(info["single_session"])

    def test_confirming_with_another_session_does_not_add_provenance(self):
        """r111: confirming is not a second sighting of the claim.

        `confirm(session=…)` used to append the confirmer to `sessions`, which
        `independence()` counts as a provenance group. One facilitator marking a
        card discussable therefore raised a single-session card to
        `cross_session`, and `broadcast` handed it back as another session's
        compatible word -- the isolation guard's central claim, deleted by an
        administrative action. Paired: both arms below differ only in the argument.
        """
        for label, confirmer in (("another session", "sess-facilitator"), ("none", None)):
            with self.subTest(confirmer=label):
                candidate_id = f"d-confirm-{'other' if confirmer else 'none'}"
                # Distinct wording per arm: `add` dedupes by content key, and the two
                # arms are two separate cards, not two sightings of one sentence.
                self._single_session_card(
                    candidate_id=candidate_id,
                    statement=f"交接前先写下当前版本的范围（{candidate_id}），能减少返工。",
                )
                self.store.confirm(candidate_id, "worth discussing", session=confirmer)
                state = self.store.show(candidate_id)["candidate"]
                info = independence(state)
                self.assertEqual(["sess-a"], state["sessions"])
                self.assertEqual("single_session", info["provenance_status"])
                self.assertFalse(info["independent"])
                expected = [confirmer] if confirmer else []
                self.assertEqual(expected, state.get("confirmed_sessions", []))
                broadcast = self.store.broadcast("交接 版本 范围")
                self.assertNotIn(candidate_id, [item["id"] for item in broadcast["results"]])
                self.assertIn(candidate_id, [item["id"] for item in broadcast["suppressed"]])
        # The confirmer is still recorded -- it just is not evidence.
        self.assertEqual("sess-facilitator",
                         self.store.show("d-confirm-other")["candidate"]["confirmation"]["session"])

    def test_revoking_with_another_session_does_not_add_provenance_either(self):
        """The mirror of confirm(): taking discussability back is not evidence."""
        self._single_session_card()
        self.store.confirm("d-session", "worth discussing")
        self.store.revoke("d-session", "scope still unclear", session="sess-facilitator")
        state = self.store.show("d-session")["candidate"]
        self.assertEqual(["sess-a"], state["sessions"])
        self.assertEqual(["sess-facilitator"], state["confirmed_sessions"])
        self.assertEqual("single_session", independence(state)["provenance_status"])

    def test_a_genuine_second_source_still_flips_the_card(self):
        """Sensitivity: the fix must not be 'nothing is ever independent'.

        Without this arm an implementation that hard-coded `single_session` would
        pass every assertion above.
        """
        self._single_session_card()
        self.store.confirm("d-session", "worth discussing", session="sess-facilitator")
        self.store.attach_source("d-session", {
            "type": "claimed_firsthand", "claim": "另一位互不相关的会话也独立得出相容主张",
            "independence_group": "sess-b", "verification": "unverified",
        }, session="sess-b")
        state = self.store.show("d-session")["candidate"]
        info = independence(state, self.store._acquisition_events("d-session"))
        self.assertEqual("cross_session", info["provenance_status"])
        self.assertTrue(info["independent"])
        self.assertEqual(["sess-a", "sess-b"], info["provenance_groups"])
        self.assertEqual(["d-session"], [item["id"] for item in self.store.broadcast("交接 版本 范围")["results"]])

    def test_a_session_that_acquired_a_source_and_then_confirmed_is_still_independent(self):
        """The counterexample the rule has to survive: acquiring, then confirming.

        A rule that simply drops "whoever confirmed" would pass every r111 test and
        still be wrong here. `sess-b` really did bring a second source back; it then
        also confirmed the card. Both facts are true and the provenance must keep the
        first.

        This is a **guard, not a discriminator**: it passes on the r111 tree too, and
        for the wrong reason -- r111 counted `sess-b` because every writer sat in
        `sessions`, not because it had attached a source. Verified on the real r111
        bytes (`run_tests_on_before.py` -> ok there). It is here to stop a future fix
        from "dropping whoever confirmed" and losing a real sighting; the arm that
        actually fails on r111 is
        `test_two_sessions_citing_one_named_group_are_not_independent`.
        """
        self.store.add(
            "交接前先写下当前版本的范围，能减少返工。", "application", candidate_id="d-acq",
            scope=["交接"], session="sess-a",
            sources=[{"type": "unknown", "claim": "第一次会话的结论",
                      "independence_group": "sess-a", "verification": "unknown"}],
        )
        self.store.confirm("d-acq", "worth discussing")
        self.store.attach_source("d-acq", {
            "type": "claimed_firsthand", "claim": "另一会话独立带回的相容主张",
            "independence_group": "sess-b", "verification": "unverified",
        }, session="sess-b")
        self.store.confirm("d-acq", "second source confirmed discussable", session="sess-b")
        state = self.store.show("d-acq")["candidate"]
        self.assertEqual("sess-b", state["confirmation"]["session"])
        info = independence(state, self.store._acquisition_events("d-acq"))
        self.assertIn("sess-b", info["provenance_groups"])
        self.assertEqual("cross_session", info["provenance_status"])
        self.assertTrue(info["independent"])
        self.assertEqual(["d-acq"], [item["id"] for item in self.store.broadcast("交接 版本 范围")["results"]])

    def test_a_methodology_source_written_by_the_naming_session_is_one_group_not_two(self):
        """The shape the three legacy cards have, built on a fresh database.

        One `stranger-methodology-v1` source, written by the session that also
        confirmed the card. Before r112 that came out `independence_groups=1`
        alongside `independent=true` -- the session's act of writing was counted as a
        second sighting of a methodology pack it was the one to supply. It is one
        provenance: neither a single session's word nor two independent ones.
        """
        self.store.add(
            "固定预设陌生人提出的观点，虚构材料，不是经验依据。", "abstract_idea", candidate_id="d-method",
            scope=["设计"], session="demo-stranger-a",
            sources=[{"type": "synthetic_roleplay", "claim": "固定预设陌生人提出的观点；虚构材料，不是经验依据。",
                      "independence_group": "stranger-methodology-v1", "verification": "not_evidence"}],
        )
        self.store.confirm("d-method", "worth discussing", session="demo-stranger-a")
        info = independence(self.store.show("d-method")["candidate"],
                            self.store._acquisition_events("d-method"))
        self.assertEqual(["stranger-methodology-v1"], info["independence_groups"])
        self.assertEqual(["stranger-methodology-v1"], info["provenance_groups"])
        self.assertEqual("unidentified", info["provenance_status"])
        self.assertFalse(info["independent"],
                         "one methodology group and one session that supplied it is not independence")
        inserted = self.store.export_prompt("c", ["d-method"], 6000, self.root / "exports")
        text = Path(inserted["path"]).read_text(encoding="utf-8")
        self.assertIn("independence_groups=1 | independent=false", text)
        self.assertNotIn("independent=true", text)

    def test_the_header_cannot_print_a_count_smaller_than_the_verdict_used(self):
        """#1831d: the P shape -- one named group plus one attributed group-less source.

        Before this, the export header printed `independence_groups=1 | independent=true`:
        the count was the named groups alone (1) while the verdict was computed over two
        provenance entries (the group, and the session that brought the unnamed source).
        A reader saw a 1 sitting beside `true` and had to decide which one lied.

        Red on the pre-#1831d tree: there the header reads `independence_groups=1`.
        """
        self.store.add(
            "具名组的材料，加一个第二人真正带回来的无组名材料。", "application",
            candidate_id="d-p-shape", scope=["交接"],
            sources=[{"type": "secondhand_report", "claim": "具名组的材料。",
                      "independence_group": "team-alpha", "verification": "unverified"}],
        )
        self.store.attach_source("d-p-shape", {
            "type": "unknown", "claim": "第二人带回的材料。",
            "independence_group": "unknown", "verification": "unverified",
        }, session="sess-b")
        self.store.confirm("d-p-shape", "worth discussing")
        info = independence(self.store.show("d-p-shape")["candidate"],
                            self.store._acquisition_events("d-p-shape"))
        self.assertTrue(info["independent"])
        # The count reported is the count the verdict used, not a narrower one beside it.
        self.assertEqual(len(info["provenance_groups"]), len(info["independence_groups"]))
        # The raw named-group list is still available under its own name.
        self.assertEqual(["team-alpha"], info["named_groups"])
        exported = self.store.export_prompt("c", ["d-p-shape"], 6000, self.root / "exports")
        header = next(line for line in Path(exported["path"]).read_text(encoding="utf-8").splitlines()
                      if line.startswith("[d-p-shape"))
        self.assertIn("independence_groups=2 | independent=true", header)
        self.assertNotIn("independence_groups=1", header)

    def test_one_write_with_a_named_and_a_group_less_source_is_one_provenance(self):
        """#1876: one witness logging the same material two ways is one provenance.

        A single `add` writes a source that names `team-alpha` and a second source that
        names no group. Before this, the group-less source fell back to the writing
        session, so the card printed `['sess-b', 'team-alpha']` -- two provenance
        entries for one witness and one material, because the registration changed.

        Red on the pre-#1876 bytes `storage_before_1876.py`: there `independent` is True
        and `provenance_groups` is ['sess-b', 'team-alpha'] for this exact input.
        """
        self.store.add(
            "一次写入里，一份具名材料加一份没填组名的材料。", "application",
            candidate_id="d-one-write", scope=["交接"], session="sess-b",
            sources=[
                {"type": "secondhand_report", "claim": "具名组的材料。",
                 "independence_group": "team-alpha", "verification": "unverified"},
                {"type": "unknown", "claim": "同一次写入里没填组名的那份。",
                 "independence_group": "unknown", "verification": "unverified"},
            ],
        )
        self.store.confirm("d-one-write", "worth discussing", session="sess-b")
        info = independence(self.store.show("d-one-write")["candidate"],
                            self.store._acquisition_events("d-one-write"))
        # One witness, one material, two registration styles: one provenance entry.
        self.assertEqual(["team-alpha"], info["provenance_groups"])
        self.assertFalse(info["independent"])
        # The group name wins over the writing session; the session key is not added.
        self.assertNotIn("sess-b", info["provenance_groups"])
        # The named-group list is untouched by this rule.
        self.assertEqual(["team-alpha"], info["named_groups"])

    def test_two_sessions_declaring_two_groups_stay_two_provenances(self):
        """#1876's other direction: the contract shape must NOT be compressed.

        `sess-a` and `sess-b` each declare their own group in one write. The rule that
        fixes the one-witness-two-registrations shape must not merge these: a session
        key is never attached to a source that already names a group.

        This is the assertion the rejected union rule broke (1/false instead of 2/true).
        """
        self.store.add(
            "两份各自具名的材料，同一次写入。", "application",
            candidate_id="d-two-declared", scope=["交接"], session="sess-a",
            sources=[
                {"type": "unknown", "claim": "本次会话形成的结论",
                 "independence_group": "sess-a", "verification": "unknown"},
                {"type": "claimed_firsthand", "claim": "另一独立会话相容主张",
                 "independence_group": "sess-b", "verification": "unverified"},
            ],
        )
        self.store.confirm("d-two-declared", "worth discussing", session="sess-a")
        info = independence(self.store.show("d-two-declared")["candidate"],
                            self.store._acquisition_events("d-two-declared"))
        self.assertEqual(["sess-a", "sess-b"], info["provenance_groups"])
        self.assertTrue(info["independent"])

    def test_a_session_that_acquired_an_unnamed_source_and_then_confirmed_is_still_independent(self):
        """The same counterexample, in the shape where only the ledger can tell.

        `sess-b` attaches a source that names no group, then confirms the card. The
        source cannot be attributed except by the `attach_source` event, so this arm
        fails if the ledger is ignored -- which is exactly what happened the first time
        it was written with a *named* second group: attribution was never consulted, so
        the mutant came back green and the arm proved nothing.

        Two failures are being excluded at once. Drop the confirmation and the card is
        independent (correct). Drop the acquisition and only the confirmation is left,
        which must not make it independent (`test_confirming_with_another_session...`).
        """
        self.store.add(
            "交接前先写下当前版本的范围，能减少返工。", "application", candidate_id="d-acq-unnamed",
            scope=["交接"], session="sess-a",
            sources=[{"type": "unknown", "claim": "第一次会话的结论",
                      "independence_group": "sess-a", "verification": "unknown"}],
        )
        self.store.attach_source("d-acq-unnamed", {
            "type": "claimed_firsthand", "claim": "另一会话带回的材料，未登记组名",
            "independence_group": "unknown", "verification": "unverified",
        }, session="sess-b")
        self.store.confirm("d-acq-unnamed", "second source confirmed discussable", session="sess-b")
        state = self.store.show("d-acq-unnamed")["candidate"]
        self.assertEqual("sess-b", state["confirmation"]["session"])
        info = independence(state, self.store._acquisition_events("d-acq-unnamed"))
        self.assertEqual(["sess-a", "sess-b"], info["provenance_groups"])
        self.assertEqual("cross_session", info["provenance_status"])
        self.assertTrue(info["independent"])
        self.assertEqual([], info["unattributed_source_ids"])

    def test_two_sessions_citing_one_named_group_are_not_independent(self):
        """Two sessions, one material: still one provenance.

        Reproduces the export that still said `independent=true` with
        `independence_groups=1`: two sessions each attached a source from
        `method-pack-v1`. The old rule unioned the named groups with the sessions that
        had attached anything; a group name never equals a session ID, so the union
        could not collapse them and reported two sightings of one material. Red on the
        r111 tree (reads `cross_session`, `independent=true`) and on either export.
        """
        self.store.add(
            "同一份方法论材料被两个会话先后引用，仍是一份材料。", "abstract_idea",
            candidate_id="d-same-group", scope=["方法"], session="sess-p",
            sources=[{"type": "synthetic_roleplay", "claim": "固定的方法论预设",
                      "independence_group": "method-pack-v1", "verification": "not_evidence"}],
        )
        self.store.attach_source("d-same-group", {
            "type": "synthetic_roleplay", "claim": "同一套预设，另一个会话也引用了",
            "independence_group": "method-pack-v1", "verification": "not_evidence",
        }, session="sess-q")
        self.store.confirm("d-same-group", "worth discussing", session="sess-q")
        state = self.store.show("d-same-group")["candidate"]
        info = independence(state, self.store._acquisition_events("d-same-group"))
        self.assertEqual(["method-pack-v1"], info["independence_groups"])
        self.assertEqual(["method-pack-v1"], info["provenance_groups"])
        self.assertFalse(info["independent"],
                         "two citations of one material are one provenance, not two")
        exported = self.store.export_prompt("c", ["d-same-group"], 6000, self.root / "exports")
        header = next(line for line in Path(exported["path"]).read_text(encoding="utf-8").splitlines()
                      if line.startswith("[d-same-group"))
        self.assertIn("independence_groups=1 | independent=false", header)
        self.assertNotIn("independent=true", header)

    def test_search_excludes_a_challenged_card_and_an_untouched_draft(self):
        """What the widened gate must still keep out.

        Only `draft` + accepted is added. A challenged card is not evidence of an
        accepted conclusion however it got there, and a draft nobody accepted is still
        not a conclusion -- the fix must not turn retrieval into "show every card".
        """
        self.add(candidate_id="d-untouched", statement="没人碰过的草稿：写下来但没人认可。",
                 sources=[{"type": "model_generated", "claim": "模型写的措辞，用户没认可这版。",
                           "independence_group": "sess-n", "verification": "unverified"}], session="sess-n")
        self.add(candidate_id="d-challenged", statement="被质疑的结论：边界是否成立仍未知。",
                 sources=[{"type": "model_generated", "claim": "会话形成的结论。",
                           "independence_group": "sess-o", "verification": "unverified"}], session="sess-o")
        self.store.accept_draft("d-challenged")
        self.store.challenge("d-challenged", "这个结论的边界还没查清")
        rows = {row["id"] for row in self.store.retrieve("草稿 认可 结论 边界")["results"]}
        self.assertNotIn("d-untouched", rows)
        self.assertNotIn("d-challenged", rows)

    def test_a_group_named_source_plus_an_unnamed_one_from_another_session_is_two(self):
        """The disputed shape, ruled explicitly rather than left to the union.

        One source names its group, and a *different* session attached a second source
        that names none. Ruling: two provenances. The second source is material that
        session brought back -- it is not the named group restated -- and the ledger
        names which session attached it, so attributing it does not guess. The old code
        also said `cross_session` here, but for the wrong reason: it counted every writer
        in `sessions`, which is also why it passed cards whose only second "source" was
        the session that wrote them. This test therefore checks the reading *and* the
        reason (`provenance_groups` names both sessions, not a session and a group).
        """
        self.store.add(
            "一个具名组，加一个无组来源由另一会话附上。", "application", candidate_id="d-mixed",
            scope=["混合"], session="sess-v",
            sources=[{"type": "unknown", "claim": "会话 V 的结论",
                      "independence_group": "sess-v", "verification": "unknown"}],
        )
        self.store.attach_source("d-mixed", {
            "type": "claimed_firsthand", "claim": "会话 W 附上的另一段材料（未命名组）",
            "independence_group": "unknown", "verification": "unverified",
        }, session="sess-w")
        self.store.confirm("d-mixed", "worth discussing", session="sess-w")
        info = independence(self.store.show("d-mixed")["candidate"],
                            self.store._acquisition_events("d-mixed"))
        self.assertEqual(["sess-v", "sess-w"], info["provenance_groups"])
        self.assertEqual("cross_session", info["provenance_status"])
        self.assertTrue(info["independent"])
        self.assertEqual([], info["unattributed_source_ids"])

    def test_list_marks_an_unaccepted_draft_and_leaves_other_rows_byte_identical(self):
        """r111: `status=draft` is the same value for a conclusion nobody confirmed
        yet and for the version the user never agreed to, so `dojo list` could not
        tell them apart. The marker is added only when it is true -- judged by the
        value, not by the key's presence -- and the draft stays in the listing."""
        self.add(candidate_id="d-conclusion", statement="开始前把任务缩成第一步，可能降低启动阻力。",
                 sources=[{"type": "unknown", "claim": "本次讨论会话形成的结论",
                           "independence_group": "sess-a", "verification": "unknown"}], session="sess-a")
        self.add(candidate_id="d-draft", statement="对普通自行车，自动分配前后制动力可作为待检验的设计目标。",
                 sources=[{"type": "model_generated", "claim": "会话结束时仍是待处理草稿的候选；用户没有明确认可这版措辞。",
                           "independence_group": "sess-a", "verification": "unverified"}], session="sess-a")
        rows = {row["id"]: row for row in self.store.list_candidates()}
        self.assertEqual(2, len(rows), "the draft must not be filtered out of the listing")
        self.assertIs(True, rows["d-draft"].get("unaccepted_draft"))
        self.assertEqual(
            {"id", "version", "status", "statement", "kind"}, set(rows["d-conclusion"]),
            "a conclusion's row keeps the same five keys it had before",
        )
        self.assertEqual("draft", rows["d-conclusion"]["status"])
        # After the user accepts that exact wording, the marker goes away on the same card.
        self.store.accept_draft("d-draft")
        after = {row["id"]: row for row in self.store.list_candidates()}
        self.assertNotIn("unaccepted_draft", after["d-draft"])
        self.assertEqual({"id", "version", "status", "statement", "kind"}, set(after["d-draft"]))

    def test_the_full_listing_tells_an_unaccepted_draft_from_a_conclusion_too(self):
        """r111b: `list --history` is the same command's other path and it had the
        same blind spot. Both a draft and a conclusion the user agreed to read
        `status: draft` there, and the fuller view carried no marker at all, so the
        person who asked for more detail got less signal than the short listing."""
        self.add(candidate_id="d-conclusion", statement="开始前把任务缩成第一步，可能降低启动阻力。",
                 sources=[{"type": "unknown", "claim": "本次讨论会话形成的结论",
                           "independence_group": "sess-a", "verification": "unknown"}], session="sess-a")
        self.add(candidate_id="d-draft", statement="对普通自行车，自动分配前后制动力可作为待检验的设计目标。",
                 sources=[{"type": "model_generated", "claim": "会话结束时仍是待处理草稿的候选；用户没有明确认可这版措辞。",
                           "independence_group": "sess-a", "verification": "unverified"}], session="sess-a")
        plain = {row["id"]: row for row in self.store.list_candidates()}
        rows = {row["id"]: row for row in self.store.list_candidates(include_history=True)}
        self.assertEqual(2, len(rows), "the draft must not be filtered out of the full listing either")
        self.assertIs(True, rows["d-draft"].get("unaccepted_draft"))
        self.assertNotIn("unaccepted_draft", rows["d-conclusion"])
        # status is the ledger's value: the marker is added beside it, never instead of it.
        self.assertEqual("draft", rows["d-draft"]["status"])
        self.assertEqual("draft", rows["d-conclusion"]["status"])
        # Everything except the marker is exactly the state the plain path hides.
        self.assertEqual(
            {key: value for key, value in rows["d-draft"].items() if key != "unaccepted_draft"},
            self.store.show("d-draft")["candidate"],
            "the full row is the stored state, unedited",
        )
        self.assertEqual(plain["d-conclusion"], {key: rows["d-conclusion"][key]
                                                  for key in plain["d-conclusion"]})

    def test_a_model_draft_that_gained_a_second_source_is_no_longer_an_unaccepted_draft(self):
        """If another session adds its own source, the card is no longer only the
        model's wording, so by shape it stops being an unaccepted draft."""
        self.add(candidate_id="d-draft", statement="对普通自行车，自动分配前后制动力可作为待检验的设计目标。",
                 sources=[{"type": "model_generated", "verification": "unverified",
                           "claim": "会话结束时仍是待处理草稿的候选；用户没有明确认可这版措辞。",
                           "independence_group": "sess-a"}], session="sess-a")
        before = {row["id"]: row for row in self.store.list_candidates()}
        self.assertIs(True, before["d-draft"].get("unaccepted_draft"))
        self.store.attach_source("d-draft", {
            "type": "claimed_firsthand", "claim": "另一会话独立提出了同一个目标",
            "independence_group": "sess-b", "verification": "unverified",
        }, session="sess-b")
        after = {row["id"]: row for row in self.store.list_candidates()}
        self.assertNotIn("unaccepted_draft", after["d-draft"])
        self.assertEqual({"id", "version", "status", "statement", "kind"}, set(after["d-draft"]))

    def test_search_tells_an_unaccepted_draft_from_a_conclusion_too(self):
        """r111c: `dojo search` is the screen a person types to find what the library
        holds. A card the user accepted and a card a facilitator merely unblocked
        both come back `status: discussable`, so the screen could hand an unaccepted
        draft back as settled. The marker is added by value, only when true."""
        # Two discussable single-source cards, identical except for who wrote them:
        # the control is a card whose one source is not the model's wording.
        self.add(candidate_id="d-other-source", statement="交接前先写下当前版本的范围，能减少返工。",
                 sources=[{"type": "synthetic_roleplay", "claim": "演示材料里另一个会话的提案",
                           "independence_group": "sess-b", "verification": "not_evidence"}], session="sess-b")
        self.add(candidate_id="d-draft", statement="对普通自行车，自动分配前后制动力可作为待检验的设计目标。",
                 sources=[{"type": "model_generated", "claim": "会话结束时仍是待处理草稿的候选；用户没有明确认可这版措辞。",
                           "independence_group": "sess-a", "verification": "unverified"}], session="sess-a")
        self.store.confirm("d-other-source", "可讨论")
        # A facilitator -- not the user -- unblocks the draft. It becomes retrievable.
        self.store.confirm("d-draft", "主持人认为可以先拿出来讨论", "facilitator-2")
        rows = {row["id"]: row for row in self.store.retrieve("交接 范围 自行车 制动力")["results"]}
        self.assertEqual({"d-other-source", "d-draft"}, set(rows), "the draft must still be retrievable")
        self.assertIs(True, rows["d-draft"].get("unaccepted_draft"))
        self.assertEqual("discussable", rows["d-draft"]["status"])
        self.assertNotIn("unaccepted_draft", rows["d-other-source"],
                         "a card that is not a model-written draft keeps exactly the keys it had before")
        # Accepting that exact wording makes the card stop being an unaccepted draft.
        # `accept_draft` rewrites the source; it does not touch `status`, so this card
        # (already confirmed above) stays discussable and now reads as settled -- which
        # is correct here: the user did accept it.
        accepted = self.store.accept_draft("d-draft")
        self.assertFalse(is_unaccepted_draft(accepted))
        self.assertEqual("discussable", accepted["status"])
        settled = {row["id"]: row for row in self.store.retrieve("自行车 制动力")["results"]}
        self.assertIn("d-draft", settled)
        self.assertNotIn("unaccepted_draft", settled["d-draft"])

    def test_a_same_shape_card_nobody_accepted_is_not_searchable(self):
        """The negative control, built to be indistinguishable by shape.

        This card is byte-for-byte the shape `accept_draft` produces: one source,
        `type=unknown`, `verification=unknown`, `independence_group` equal to the
        writing session, and the exact claim and scope_note `accept_draft` writes.
        The only difference is that nobody accepted it -- there is no acceptance
        event, because `dojo add --source-json` cannot write one.

        The first version of this gate answered True here (it read the shape), which is
        why B was rejected: on that version this test is RED because the card *is*
        returned. Reverting the predicate to the shape test makes it red again.
        """
        self.store.add(
            "对普通自行车，自动分配前后制动力可作为待检验的设计目标。", "abstract_idea",
            candidate_id="d-shaped", scope=["自行车"], session="sess-a",
            sources=[{
                "type": "unknown", "verification": "unknown",
                "claim": "本次讨论会话形成的结论；完整会话原文保存在本地轨迹文件，内容未经独立核验。",
                "scope_note": "单一会话来源；不构成独立佐证。",
                "independence_group": "sess-a",
            }],
        )
        state = self.store.show("d-shaped")["candidate"]
        self.assertEqual("draft", state["status"])
        self.assertFalse(self.store.has_acceptance("d-shaped"),
                         "nothing recorded an acceptance, so there is no evidence of one")
        self.assertEqual([], [row["id"] for row in self.store.retrieve("自行车 制动力")["results"]],
                         "a card nobody accepted must not be handed back as a conclusion")
        # And the shape test this replaced would have said yes:
        self.assertEqual(1, len(state["sources"]))
        self.assertNotEqual("model_generated", state["sources"][0]["type"])
        self.assertIn(state["sources"][0]["independence_group"], state["sessions"])
        # Once something records the acceptance, the same card becomes retrievable --
        # which proves the ledger is what decides, not the fields.
        self.store.record_acceptance("d-shaped", "sess-a", path="test")
        self.assertIn("d-shaped", [row["id"] for row in self.store.retrieve("自行车 制动力")["results"]])

    def test_discuss_records_an_accepted_conclusion_so_search_finds_it(self):
        """The second positive control: the path #1486/B actually meant to rescue.

        `discuss._save_conclusion` writes a brand-new conclusion when the user accepts a
        wording in conversation. It used to leave no acceptance record at all, so the
        sentence the user agreed to was unreachable. It now records one, and this test
        goes through the real `discuss` helper and the real `search` entry point.
        """
        from dojo import discuss as discuss_module

        candidate = {
            "statement": "对普通自行车，自动分配前后制动力可作为待检验的设计目标。",
            "kind": "abstract_idea", "premises": [], "scope": ["自行车"],
            "alternatives": [], "contradictions": [], "unknowns": [],
        }
        saved_id, _version, error = discuss_module._save_conclusion(
            self.store, candidate, "sess-conv", candidate_id=None, trace_enabled=False,
        )
        self.assertIsNone(error)
        self.assertIsNotNone(saved_id)
        self.assertTrue(self.store.has_acceptance(saved_id))
        rows = {row["id"]: row for row in self.store.retrieve("自行车 制动力")["results"]}
        self.assertIn(saved_id, rows, "the conclusion written on acceptance must be findable")
        self.assertNotIn("unaccepted_draft", rows[saved_id])

    def test_a_withdrawn_card_is_not_searchable_even_though_it_was_accepted(self):
        """The status term's own arm: withdrawing does not rewrite the sentence.

        `challenge` appends a contradiction, which changes the wording's digest, so a
        challenged card is already excluded by the acceptance check. `withdraw` leaves
        the wording identical, so only the status term keeps it out -- which is why this
        is the control for dropping that term. A withdrawn card is not something to hand
        a next session as accepted.
        """
        self.add(candidate_id="d-withdrawn", statement="如果这份困难本身就是练习的一部分，去掉难度就同时去掉了练习机会。",
                 sources=[{"type": "model_generated", "claim": "会话结束时留下的草稿；用户没有明确认可。",
                           "independence_group": "sess-w", "verification": "unverified"}], session="sess-w")
        self.store.accept_draft("d-withdrawn")
        self.assertIn("d-withdrawn", [r["id"] for r in self.store.retrieve("练习 困难 难度 机会")["results"]])
        statement_before = self.store.show("d-withdrawn")["candidate"]["statement"]
        self.store.withdraw("d-withdrawn", "这个说法在别的场景下不成立")
        state = self.store.show("d-withdrawn")["candidate"]
        self.assertEqual("withdrawn", state["status"])
        self.assertEqual(statement_before, state["statement"], "the wording is untouched")
        self.assertNotIn("d-withdrawn", [r["id"] for r in self.store.retrieve("练习 困难 难度 机会")["results"]],
                         "withdrawn is not something to hand the next session as accepted")

    def test_a_later_rewrite_does_not_inherit_the_old_acceptance(self):
        """#1497 negative control: accepted, then somebody rewrote the sentence.

        A card whose user accepted one wording does not speak for a different wording.
        Before the acceptance carried the identity of what was accepted, the ledger had
        one `draft_accepted` and `is_accepted_conclusion` only asked "is there an
        acceptance event" -- so a rewrite inherited it and the new, unread sentence was
        handed back as accepted. Sequence here is exactly the reported one:
        add → draft_accepted → revise.

        The card must not be erased: it keeps its history, and it is reported in its
        truthful state (draft whose current wording nobody accepted).
        """
        self.add(candidate_id="d-rewritten", statement="对普通自行车，自动分配前后制动力可作为待检验的设计目标。",
                 sources=[{"type": "model_generated", "claim": "会话结束时留下的草稿，用户没有明确认可这版措辞。",
                           "independence_group": "sess-a", "verification": "unverified"}], session="sess-a")
        self.store.accept_draft("d-rewritten")
        self.assertIn("d-rewritten", [r["id"] for r in self.store.retrieve("自行车 制动力")["results"]],
                      "the accepted wording is retrievable (established in r112)")
        self.store.revise(
            "d-rewritten", "对电动助力车，自动分配前后制动力可作为待检验的设计目标。",
            "换了适用车型", kind="abstract_idea", scope=["自行车"], session="sess-b",
        )
        state = self.store.show("d-rewritten")["candidate"]
        self.assertEqual("draft", state["status"])
        self.assertEqual(["add", "draft_accepted", "revise"], [e["event"] for e in self.store.history("d-rewritten")["events"]])
        self.assertNotIn("d-rewritten", [r["id"] for r in self.store.retrieve("电动助力车 制动力")["results"]],
                         "a wording nobody read must not inherit the previous wording's acceptance")
        # Not erased: still in the listing, still in the library, still its own record.
        self.assertIn("d-rewritten", [r["id"] for r in self.store.list_candidates()])
        self.assertEqual(3, self.store.show("d-rewritten")["candidate"]["version"])
        # A second acceptance for the new wording brings it back -- the rule is about
        # which wording was accepted, not a life sentence for having been revised.
        self.store.record_acceptance("d-rewritten", "sess-b", path="accept_rewrite")
        self.assertIn("d-rewritten", [r["id"] for r in self.store.retrieve("电动助力车 制动力")["results"]])

    def test_an_acceptance_belongs_to_a_card_not_to_identical_wording(self):
        """#1569: two cards, one sentence, one acceptance -- only the accepted card counts.

        An acceptance is *for a card*, and the wording's digest only verifies which
        version of that card's sentence was agreed to. The two questions were collapsed
        into one: the digest decided, and a card identity was never written down. The
        real case that showed it is r1551 -- a backfill tool selecting by wording wrote
        one card's acceptance where a different card with the same sentence was meant.

        Asserted in the order the evidence supports, because the first reading of this
        test was wrong and the order is what exposed it:

        1. **already true before this change** -- an acceptance written on A is not read
           for B. The ledger is queried per `candidate_id`, so card scoping on the *read*
           path never rested on the digest. Recorded here so the claim "digest alone let
           any card claim any acceptance" cannot be repeated: that was the *write*-side
           selection in the r1551 backfill tool, not this reader.
        2. **red before this change** -- an acceptance row that sits in B's ledger and
           names card A must not count for B. The old reader looked only at the digest,
           so it counted; matching wording was enough. This is the hole the card identity
           closes.
        3. **red before this change** -- an acceptance must record the card it was given
           for at all. Without the field there is nothing for 2 to compare.

        What this does *not* claim: a hand-written event that rewrites the field to say
        B was accepted is still read as B's, because the wording matches. The binding
        makes an acceptance self-describing and refuses a moved one; it is not a
        signature, and it cannot stop a writer that lies about the card it names.
        """
        source = {"type": "model_generated", "verification": "unverified",
                  "claim": "会话结束时留下的草稿；用户没有明确认可这版措辞。",
                  "independence_group": "sess-a"}
        statement = "对普通自行车，自动分配前后制动力可作为待检验的设计目标。"
        self.add(candidate_id="d-card-a", statement=statement, sources=[source], session="sess-a")
        # B is made to carry A's exact wording the way it can really happen: `add` refuses
        # a duplicate by content, but `revise` does not check duplicates. Two sessions
        # working separately end up with one sentence on two cards, and B is the second
        # one -- a different card, the same words, hence the same digest.
        self.add(candidate_id="d-card-b", statement="另一条先写下的候选。",
                 sources=[{**source, "independence_group": "sess-b"}], session="sess-b")
        self.store.revise("d-card-b", statement, "两个会话各自收到了同一句话", session="sess-b")
        self.assertEqual(
            wording_digest(self.store.show("d-card-a")["candidate"]),
            wording_digest(self.store.show("d-card-b")["candidate"]),
            "the fixture only means something if the two cards really do share a digest",
        )
        self.store.record_acceptance("d-card-a", "sess-a", path="test")
        self.assertTrue(self.store.has_acceptance("d-card-a"))
        event = [e for e in self.store.history("d-card-a")["events"] if e["event"] == "wording_accepted"][0]

        # (2) The load-bearing arm: A's acceptance, placed in B's ledger. Wording matches
        # exactly; only the card identity in the event can tell that it is not B's.
        self.store._event("d-card-b", "wording_accepted", {
            "session": "sess-a", "path": "moved_by_hand",
            "statement_digest": event["details"]["statement_digest"],
            "candidate_id": "d-card-a",
        })
        self.assertFalse(self.store.has_acceptance("d-card-b"),
                         "an event that says it is card A's is not card B's acceptance")
        self.assertNotIn("d-card-b", [row["id"] for row in self.store.retrieve("自行车 制动力")["results"]],
                         "search must not hand back a card whose only acceptance was A's")

        # (3) The event records the card it was given for, so a move is detectable.
        self.assertEqual("d-card-a", event["details"].get("candidate_id"),
                         "an acceptance must name the card it was given for")

        # And the card that was actually accepted stays accepted: the stricter reading
        # must not cost the case it is protecting.
        self.assertIn("d-card-a", [row["id"] for row in self.store.retrieve("自行车 制动力")["results"]])
        # And the audit says why, instead of filing it as "no recoverable wording".
        unbound = {row["id"]: row for row in self.store.audit_acceptances()["unbound"]}
        self.assertEqual("acceptance was written for another card", unbound["d-card-b"]["reason"])

    def test_export_header_does_not_lend_one_card_s_acceptance_to_an_identical_wording(self):
        """The binding above is asserted on `search` and on the audit. Export is not.

        Export is the surface that actually reaches a reader: it is a frozen prompt
        with a header, and that header is where `accepted_at` is printed. So the same
        question has a second answer, and nothing was checking it -- the existing test
        stops at retrieval.

        Both cards here pass export's provenance gate (two independence groups each),
        which is the precondition for the header being written at all. Only the
        accepted one may print an acceptance; the other must carry exactly the fields
        of a card no one accepted, even though its sentence is byte-identical.

        Mutation this kills: drop the card check from `_accepted_wording_digest` and
        the second card's header starts carrying the first card's `accepted_at`,
        because the digests match.
        """
        sentence = "交接的验收判据应当在开工前由双方写定。"

        def two_groups(tag):
            return [
                {"id": f"src-{tag}-1", "type": "claimed_firsthand", "verification": "unverified",
                 "claim": f"{tag} 的用户口述", "independence_group": f"person-{tag}"},
                {"id": f"src-{tag}-2", "type": "abstract_reasoning", "verification": "not_evidence",
                 "claim": f"{tag} 的推演", "independence_group": f"method-{tag}"},
            ]

        # The digest covers `scope` as well as the sentence, so both cards have to carry
        # the same scope or the fixture fails its own precondition. That precondition is
        # asserted below rather than assumed -- my first version of this test got the
        # scope wrong and the guard under test was never reached.
        self.store.add(sentence, "abstract_idea", candidate_id="d-exp-a",
                       scope=["交接"], sources=two_groups("a"), session="sess-a")
        self.store.record_acceptance("d-exp-a", "sess-a", path="discuss_conclusion")
        self.store.confirm("d-exp-a", "可导出", "sess-a")

        self.store.add("另一条先写下的候选。", "abstract_idea", candidate_id="d-exp-b",
                       scope=["交接"], sources=two_groups("b"), session="sess-b")
        self.store.revise("d-exp-b", sentence, "两个会话各自收到了同一句话",
                          kind="abstract_idea", scope=["交接"], session="sess-b")
        self.store.confirm("d-exp-b", "可导出", "sess-b")

        self.assertEqual(
            wording_digest(self.store.show("d-exp-a")["candidate"]),
            wording_digest(self.store.show("d-exp-b")["candidate"]),
            "the fixture only means something if the two cards really do share a digest",
        )

        def header(card):
            exported = self.store.export_prompt("c", [card], 8000, self.root / ("out-" + card))
            text = Path(exported["path"]).read_text(encoding="utf-8")
            return next(line for line in text.splitlines() if line.startswith(f"[{card}"))

        accepted_header = header("d-exp-a")
        other_header = header("d-exp-b")
        self.assertIn("accepted_at=", accepted_header,
                      "the card that was accepted must print when it was accepted")
        self.assertNotIn("accepted_at=", other_header,
                         "an identical sentence on another card must not borrow its acceptance time")
        self.assertNotIn("acceptance_path=", other_header)
        self.assertEqual(
            set(self.store.time_basis("d-exp-b")), {"versioned_at"},
            "the other card's basis is its wording date and nothing else",
        )

        # The part above is necessary but not sufficient, and my first version of this
        # test stopped there -- which made it green under a mutation that deletes the
        # card guard, because `_acquisition_events` scopes the ledger by card and B never
        # sees A's row. The guard only decides anything when an acceptance *is* in this
        # card's ledger and names another card. That is the state a bad backfill leaves
        # behind, and it is what the header must refuse to print.
        event = [e for e in self.store.history("d-exp-a")["events"]
                 if e["event"] == "wording_accepted"][0]
        self.store._event("d-exp-b", "wording_accepted", {
            "session": "sess-a", "path": "backfill_from_trace",
            "statement_digest": event["details"]["statement_digest"],
            "candidate_id": "d-exp-a",
        })
        borrowed_header = header("d-exp-b")
        self.assertNotIn("accepted_at=", borrowed_header,
                         "an acceptance sitting in this card's ledger but naming card A must not "
                         "date this card's wording")
        self.assertNotIn("acceptance_path=", borrowed_header)
        self.assertEqual(set(self.store.time_basis("d-exp-b")), {"versioned_at"})

    def test_both_writers_bind_the_card_not_only_the_conversation_path(self):
        """There are two places that record an acceptance, and only one was covered.

        `record_acceptance` is the conversation path and the test above reaches it.
        `accept_draft` writes its own event under a different name, so leaving the
        card field out of it would have been invisible: every existing test asserts
        `has_acceptance`, which keeps working because the ledger row scopes the event
        to this card anyway. A missing field does not break today's reading -- it
        breaks the *next* one, which is why it needs its own assertion rather than a
        passing gate.

        Mutation this kills: delete `CARD_FIELD: candidate_id` from `accept_draft`'s
        event and this test fails while the rest stay green.
        """
        self.add(candidate_id="d-both", statement="对普通自行车，自动分配前后制动力可作为待检验的设计目标。",
                 sources=[{"type": "model_generated", "verification": "unverified",
                           "claim": "会话结束时留下的草稿；用户没有明确认可这版措辞。",
                           "independence_group": "sess-a"}], session="sess-a")
        self.store.accept_draft("d-both", session="sess-a")
        event = [e for e in self.store.history("d-both")["events"] if e["event"] == "draft_accepted"][0]
        self.assertEqual("d-both", event["details"].get("candidate_id"),
                         "accept_draft must name the card too, not just record that someone accepted")
        self.assertIn("statement_digest", event["details"],
                      "and it must still carry the wording it was accepted for")
        # Both halves together are the claim; either one alone is the defect this closes.
        self.assertTrue(self.store.has_acceptance("d-both"))

    def test_a_named_acceptance_is_not_read_for_a_state_that_names_no_card(self):
        """Unverifiable is not agreement.

        `is_accepted_conclusion` takes a state and the ledger, and a caller can hand it
        a state dict with no `id` -- the predicate is public and pure. If an acceptance
        event carries a card identity, checking it needs a card to check against; with
        none, the comparison cannot be made. Reading that as "nothing disagreed" would
        let any card's named acceptance be read for an unnamed state, which is the same
        fail-open the binding removed, moved one level up.

        Mutation this kills: `return candidate_id is None or owner != candidate_id`
        changed to `return candidate_id is not None and owner != candidate_id`.
        """
        from dojo.storage import is_accepted_conclusion

        self.add(candidate_id="d-named", statement="对普通自行车，自动分配前后制动力可作为待检验的设计目标。",
                 sources=[{"type": "model_generated", "verification": "unverified",
                           "claim": "会话结束时留下的草稿；用户没有明确认可这版措辞。",
                           "independence_group": "sess-a"}], session="sess-a")
        self.store.record_acceptance("d-named", "sess-a", path="test")
        attempts = [e for e in self.store.history("d-named")["events"]
                    if e["event"] == "wording_accepted"]
        state = self.store.show("d-named")["candidate"]
        named = dict(state, id="d-named")
        unnamed = {key: value for key, value in state.items() if key != "id"}
        snapshot = self.store._snapshot_digest("d-named")

        self.assertTrue(is_accepted_conclusion(named, attempts, snapshot),
                        "the card the acceptance was given for still reads as accepted")
        self.assertFalse(is_accepted_conclusion(unnamed, attempts, snapshot),
                         "an event naming a card cannot be confirmed against no card at all")
        # The old shape still reads, so this arm did not close the real recoveries:
        # events written before the field existed carry no card to mis-verify.
        old = [{**attempts[0], "details": {k: v for k, v in attempts[0]["details"].items()
                                           if k != "candidate_id"}}]
        self.assertTrue(is_accepted_conclusion(unnamed, old, snapshot),
                        "a pre-binding acceptance must keep working for callers with no id")

    def test_an_acceptance_survives_changes_that_do_not_touch_the_wording(self):
        """#1497 positive control A: alias / metadata must not revoke an acceptance.

        Acceptance is per wording, not per version. A card that was accepted and then
        merely aliased (or otherwise bumped without touching the sentence) keeps the
        same wording, so it must stay retrievable.

        No `confirm` here on purpose: confirming makes the card `discussable`, which
        retrieves it without any acceptance at all -- so a control that confirmed first
        would stay green even if acceptance were broken (that is how this arm first
        passed under a mutant that invalidated every acceptance on a version bump).
        """
        self.add(candidate_id="d-kept", statement="交接前先把当前版本的范围写下来，能减少临场改口。",
                 sources=[{"type": "model_generated", "claim": "会话结束时留下的草稿；用户没有明确认可。",
                           "independence_group": "sess-k", "verification": "unverified"}], session="sess-k")
        self.store.accept_draft("d-kept")
        before = self.store.show("d-kept")["candidate"]["version"]
        self.store.alias("d-kept", "交接范围", "同一个意思的另一种叫法")
        after = self.store.show("d-kept")["candidate"]
        self.assertGreater(after["version"], before, "the version did move")
        self.assertIn("d-kept", [r["id"] for r in self.store.retrieve("交接 范围 改口")["results"]],
                      "an unchanged sentence keeps its acceptance across a version bump")

    def test_a_rewritten_card_that_is_accepted_again_is_retrievable(self):
        """#1497 positive control B: the fix must not be "revised once, never again"."""
        self.add(candidate_id="d-again", statement="降低摩擦只适用于与目标无关的阻碍。",
                 sources=[{"type": "model_generated", "claim": "会话结束时留下的草稿；用户没有明确认可。",
                           "independence_group": "sess-r", "verification": "unverified"}], session="sess-r")
        self.store.accept_draft("d-again")
        self.store.revise("d-again", "降低摩擦只适用于与目标无关的阻碍；有意义的练习难度应保留。",
                          "补上边界", kind="abstract_idea", scope=["练习"], session="sess-r")
        self.assertNotIn("d-again", [r["id"] for r in self.store.retrieve("练习 摩擦 难度")["results"]])
        self.store.record_acceptance("d-again", "sess-r", path="reaccept")
        self.assertIn("d-again", [r["id"] for r in self.store.retrieve("练习 摩擦 难度")["results"]])

    def _accept_the_pre_digest_way(self, candidate_id, session=None):
        """Reproduce what an earlier version wrote: a `draft_accepted` event, no digest.

        Same source rewrite, same event name, same details `accept_draft` used before the
        acceptance carried the identity of the wording. `_write` adds the `version` that
        made the fallback possible; nothing else here is invented.
        """
        with self.store.transaction():
            state = self.store._get(candidate_id)
            source = state["sources"][0]
            state["sources"] = [{
                **source, "type": "unknown", "verification": "unknown",
                "claim": "本次讨论会话形成的结论；完整会话原文保存在本地轨迹文件，内容未经独立核验。",
                "scope_note": "单一会话来源；不构成独立佐证。",
            }]
            state["confirmation"] = self.store._confirmation_off(state, "accepted after the session resumed")
            return self.store._write(state, "draft_accepted", {"session": session, "path": "accept_draft"})

    def test_a_pre_digest_acceptance_still_speaks_for_the_wording_it_named(self):
        """#1498: an accepted card from an older library was silently discarded.

        Before this version an acceptance written without a digest matched nothing, so
        every pre-digest library lost every acceptance -- including the honest case, a
        card the user accepted and nobody then touched. The version the event names still
        has its snapshot, so the wording is recoverable by reading history rather than
        by writing anything back.

        The card is left at `draft` with no confirmation on purpose: `discussable` would
        retrieve it without consulting any acceptance, and the reading would prove nothing.
        """
        self.add(candidate_id="d-legacy", statement="对普通自行车，自动分配前后制动力可作为待检验的设计目标。",
                 sources=[{"type": "model_generated", "claim": "会话结束时留下的草稿；用户没有明确认可。",
                           "independence_group": "sess-a", "verification": "unverified"}], session="sess-a")
        self._accept_the_pre_digest_way("d-legacy", session="sess-a")
        state = self.store.show("d-legacy")["candidate"]
        self.assertEqual("draft", state["status"])
        acceptance = [e for e in self.store.history("d-legacy")["events"] if e["event"] == "draft_accepted"][0]
        self.assertNotIn("statement_digest", acceptance["details"], "the fixture must look like the old ledger")
        self.assertIn("version", acceptance["details"], "the old event does name a version")
        self.assertIn("d-legacy", [r["id"] for r in self.store.retrieve("自行车 制动力")["results"]],
                      "an accepted, never-touched card is evidence, not absence of it")
        self.assertEqual(["d-legacy"], [row["id"] for row in self.store.audit_acceptances()["bound"]])

    def test_a_pre_digest_acceptance_does_not_cover_a_later_rewrite(self):
        """The same fallback must not resurrect #1497: the snapshot is the *old* wording."""
        self.add(candidate_id="d-legacy-rewrite", statement="对普通自行车，自动分配前后制动力可作为待检验的设计目标。",
                 sources=[{"type": "model_generated", "claim": "会话结束时留下的草稿；用户没有明确认可。",
                           "independence_group": "sess-a", "verification": "unverified"}], session="sess-a")
        self._accept_the_pre_digest_way("d-legacy-rewrite", session="sess-a")
        self.store.revise("d-legacy-rewrite", "对电动助力车，自动分配前后制动力可作为待检验的设计目标。",
                          "换了适用车型", kind="abstract_idea", scope=["自行车"], session="sess-b")
        self.assertNotIn("d-legacy-rewrite", [r["id"] for r in self.store.retrieve("电动助力车 制动力")["results"]],
                         "the old acceptance named the old sentence; the new one was never read")
        audit = self.store.audit_acceptances()
        self.assertEqual(["d-legacy-rewrite"], [row["id"] for row in audit["superseded"]])

    def test_a_pre_digest_acceptance_survives_a_revision_that_restores_the_wording(self):
        """The fallback compares content, not version numbers.

        Accepted, rewritten, then restored to the accepted sentence. The version has
        moved twice and the acceptance event names neither of the new ones; it matches
        because the wording is byte-identical after normalization. This is also the
        honest cost: a rewrite that lands back on the same words cannot be told from
        never having been touched -- the acceptance is for the sentence, which is here.
        """
        original = "对普通自行车，自动分配前后制动力可作为待检验的设计目标。"
        self.add(candidate_id="d-legacy-restore", statement=original,
                 sources=[{"type": "model_generated", "claim": "草稿；用户没有明确认可。",
                           "independence_group": "sess-a", "verification": "unverified"}], session="sess-a")
        self._accept_the_pre_digest_way("d-legacy-restore", session="sess-a")
        self.store.revise("d-legacy-restore", "对电动助力车，自动分配前后制动力可作为待检验的设计目标。",
                          "换了适用车型", kind="abstract_idea", scope=["自行车"], session="sess-b")
        self.assertNotIn("d-legacy-restore", [r["id"] for r in self.store.retrieve("自行车 制动力")["results"]])
        # Restores the *content*, not just the sentence: `wording_digest` hashes
        # statement + kind + every content field, so leaving `scope` as the rewrite left
        # it would be a different wording and would (correctly) stay out. Measured the
        # hard way -- the first version of this arm kept `scope=["自行车"]` and failed,
        # which is the digest doing its job rather than a broken fallback.
        self.store.revise("d-legacy-restore", original, "改回原来的说法", kind="abstract_idea",
                          scope=[], session="sess-c")
        self.assertEqual(4, self.store.show("d-legacy-restore")["candidate"]["version"])
        self.assertIn("d-legacy-restore", [r["id"] for r in self.store.retrieve("自行车 制动力")["results"]],
                      "the accepted wording is back; the version number is not what was accepted")

    def test_an_acceptance_naming_no_wording_is_counted_not_swallowed(self):
        """Fail-closed, and visible. Two shapes, both must stay out of retrieval."""
        self.add(candidate_id="d-no-identity", statement="对普通自行车，自动分配前后制动力可作为待检验的设计目标。",
                 sources=[{"type": "model_generated", "claim": "草稿；用户没有明确认可。",
                           "independence_group": "sess-a", "verification": "unverified"}], session="sess-a")
        # A card written by hand with an acceptance-shaped event but no wording identity.
        self.store._event("d-no-identity", "wording_accepted", {"session": "sess-a", "path": "hand"})
        self.assertNotIn("d-no-identity", [r["id"] for r in self.store.retrieve("自行车 制动力")["results"]])
        self.assertEqual(["d-no-identity"], [row["id"] for row in self.store.audit_acceptances()["unbound"]])
        # And when the version the event names has no snapshot, the same answer, also counted.
        self.add(candidate_id="d-missing-snapshot", statement="交接前先把当前版本的范围写下来，能减少返工。",
                 sources=[{"type": "model_generated", "claim": "草稿；用户没有明确认可。",
                           "independence_group": "sess-b", "verification": "unverified"}], session="sess-b")
        accepted = self._accept_the_pre_digest_way("d-missing-snapshot", session="sess-b")
        self.store.connection.execute(
            "DELETE FROM snapshots WHERE candidate_id=? AND version=?", ("d-missing-snapshot", accepted["version"]),
        )
        self.assertNotIn("d-missing-snapshot", [r["id"] for r in self.store.retrieve("交接 范围 返工")["results"]])
        self.assertIn("d-missing-snapshot", [row["id"] for row in self.store.audit_acceptances()["unbound"]])

    def test_a_conclusion_accepted_without_confirmation_is_still_searchable(self):
        """r112: this used to pin a hole; the hole was the bug.

        What it pinned before: `discuss._save_conclusion` writes an accepted
        conclusion with `store.add` and never confirms it, and `_matches` returned
        only `status == "discussable"` -- so the one sentence the user agreed to
        was not retrievable, while a draft a facilitator merely unblocked was.
        r111 recorded that as a product call to be decided, not a defect. It is a
        defect: retrieval is the only screen that hands a sentence to the next
        session, and it was handing over the unaccepted one.

        What it pins now: the accepted wording is retrievable, `status` still says
        `draft` (accepting a wording is not a claim that it may be broadcast), and
        nothing about it is marked as an unaccepted draft. Reaching it does not put
        it on the broadcast path -- `independence` still reports one session.
        """
        self.add(candidate_id="d-accepted", statement="对普通自行车，自动分配前后制动力可作为待检验的设计目标。",
                 sources=[{"type": "model_generated", "claim": "会话结束时留下的草稿，用户在续谈时认可了这版措辞。",
                           "independence_group": "sess-a", "verification": "unverified"}], session="sess-a")
        self.assertEqual([], [r["id"] for r in self.store.retrieve("自行车 制动力")["results"]],
                         "an unaccepted draft reaches no retrieval screen at all")
        accepted = self.store.accept_draft("d-accepted")
        self.assertEqual("draft", accepted["status"], "accepting a wording is not a discussability claim")
        found = {r["id"]: r for r in self.store.retrieve("自行车 制动力")["results"]}
        self.assertIn("d-accepted", found, "the sentence the user agreed to is the one that must be reachable")
        self.assertNotIn("unaccepted_draft", found["d-accepted"])
        info = independence(self.store.show("d-accepted")["candidate"],
                            self.store._acquisition_events("d-accepted"))
        self.assertEqual("single_session", info["provenance_status"])
        self.assertFalse(info["independent"])
        self.assertIn("d-accepted", [r["id"] for r in self.store.list_candidates()],
                      "and it is still visible in the listing, which does not filter by status")

    # ------------------------------------------------------------------ r1537

    def test_a_read_is_a_recorded_action_with_the_acceptance_state_at_that_moment(self):
        """#1534 left this open: nothing on disk said a card had been *read*.

        `search`, `show` and `export` answered and left no trace, so the ordering
        question ("was this read before it was accepted") had no field to answer it.
        The two arms below are the same card, the same wording and the same reader,
        differing only in the order of two operations -- and they are told apart by a
        recorded fact, not by a clock, because this test never sleeps.

        The distinguishing column is `accepted_at_at_read`, not a timestamp
        comparison: `events.created_at` is second-resolution and `reads.at` is
        microsecond, so within one second "read then accepted" compares as
        `at > created_at`. That trap is asserted below rather than described.
        """
        state = self.add(candidate_id="d-read-a", session="sess-writer", sources=[{
            "type": "claimed_firsthand", "claim": "用户本人陈述",
            "independence_group": "grp-user", "verification": "unknown",
        }])
        cid = state["id"]
        self.assertIsNone(self.store.time_basis(cid).get("accepted_at"),
                          "the card starts with no acceptance, so the arm starts from nothing")
        self.store.record_read(cid, "sess-reader", surface="search")
        self.store.record_acceptance(cid, "sess-reader", path="discuss_conclusion")
        read = self.store.reads(cid)
        self.assertTrue(read["holds_table"])
        row = read["rows"][0]
        self.assertIsNone(row["accepted_at_at_read"],
                          "this read happened before any acceptance existed on the card")
        self.assertEqual("sess-reader", row["reader_session"])
        self.assertEqual("search", row["surface"])
        accepted_at = self.store.time_basis(cid)["accepted_at"]
        # The naive comparison the extra column replaces, asserted so the trap is
        # pinned by a test and not only by a comment.
        self.assertGreater(row["at"], accepted_at,
                           "clock strings alone would call this read later than the acceptance")

        second = self.add(candidate_id="d-read-b",
                        statement="交接约定值得讨论（读在之后的同形对照）",
                        session="sess-writer", sources=[{
            "type": "claimed_firsthand", "claim": "用户本人陈述",
            "independence_group": "grp-user", "verification": "unknown",
        }])["id"]
        self.store.record_acceptance(second, "sess-reader", path="discuss_conclusion")
        self.store.record_read(second, "sess-reader", surface="search")
        other = self.store.reads(second)["rows"][0]
        self.assertEqual(self.store.time_basis(second)["accepted_at"], other["accepted_at_at_read"],
                         "this read happened after the acceptance, and says so")
        self.assertNotEqual(row["accepted_at_at_read"], other["accepted_at_at_read"],
                            "same card shape, same reader, opposite order: the log tells them apart")

    def test_a_failed_read_log_leaves_the_answer_and_says_what_went_unrecorded(self):
        """The log is not worth failing a search over; silence is not acceptable either.

        An empty read history that cannot be told from "nobody read this" is exactly
        what #1534 was written to expose, so a broken log prints the answer, keeps
        exit 0, and puts one line on stderr.
        """
        self.add(candidate_id="d-log-broken", session="sess-writer",
                 sources=[{"type": "claimed_firsthand", "claim": "用户本人陈述",
                           "independence_group": "grp-user", "verification": "unknown"}])
        self.store.confirm("d-log-broken", "值得讨论", "sess-facilitator")
        # A `reads` table from some other schema: the INSERT cannot land.
        self.store.connection.execute("CREATE TABLE reads (candidate_id TEXT)")

        import contextlib
        import io
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            result = self.store.retrieve("交接", limit=5)
            from dojo.cli import _log_reads
            _log_reads(self.store, result["results"], "sess-reader", "search")
        self.assertTrue(result["results"], "the answer itself is unaffected")
        self.assertIn("未记下这次读取", stderr.getvalue())
        self.assertIn("d-log-broken", stderr.getvalue())

    def test_opening_and_reading_leave_the_library_bytes_alone(self):
        """Nothing is written unless the command layer logs a read.

        `_matches`, `retrieve`, `show` and `list_candidates` stay pure; the table is
        created by `record_read`, not by `__init__`. Otherwise merely opening a
        library would rewrite the bytes of a frozen one.
        """
        import hashlib
        self.add(candidate_id="d-pure", session="sess-writer",
                 sources=[{"type": "claimed_firsthand", "claim": "用户本人陈述",
                           "independence_group": "grp-user", "verification": "unknown"}])
        before = hashlib.sha256(Path(self.store.path).read_bytes()).hexdigest()
        self.store.list_candidates()
        self.store.retrieve("交接", limit=5)
        self.store.show("d-pure")
        after = hashlib.sha256(Path(self.store.path).read_bytes()).hexdigest()
        self.assertEqual(before, after, "a read-only path may not create the log table")
        self.assertFalse(self.store.reads()["holds_table"],
                         "and the log reports absence rather than an empty list")

    def test_a_broadcast_row_states_counts_not_people(self):
        """#1774: a two-group card must not read as two people.

        #1763 measured that an echo and a genuinely independent second arrival write
        byte-identical provenance, so `independence_groups=2 | independent=true` cannot be
        rendered as a headcount. The row states what is on disk -- how many source
        records, how many group names the sources declared for themselves -- and says in
        words that those are not people.
        """
        self.store.add(
            "交接前先把当前版本的范围写下来，能减少返工。", "application", candidate_id="d-counts",
            scope=["交接"], session="sess-a",
            sources=[
                {"type": "unknown", "claim": "本次会话形成的结论", "independence_group": "sess-a", "verification": "unknown"},
                {"type": "unknown", "claim": "第二个会话说的一模一样的话", "independence_group": "sess-b", "verification": "unknown"},
            ],
        )
        self.store.confirm("d-counts", "worth discussing")
        row = next(r for r in self.store.broadcast("交接 版本 范围")["results"] if r["id"] == "d-counts")
        reading = row["provenance_reading"]
        self.assertEqual(2, reading["source_records"])
        self.assertEqual(2, reading["self_declared_groups"])
        self.assertTrue(reading["readable"])
        self.assertIn("not people", reading["counts"])
        # The counts must not be reachable as a headcount under another name.
        for forbidden in ("people", "persons", "独立来源", "人数"):
            self.assertNotIn(forbidden, json.dumps(
                {k: v for k, v in reading.items() if k != "counts"}, ensure_ascii=False))
        # A library that never logged a handout says so; it does not report 0 rows.
        self.assertIsNone(reading["handout_rows"], "no reads table is not an empty one")
        self.assertIsNone(reading["this_session_logged"])
        # The values the rule itself reports are untouched.
        self.assertEqual(["sess-a", "sess-b"], row["independence"]["independence_groups"])
        self.assertTrue(row["independence"]["independent"])

    def test_an_echo_and_an_independent_arrival_read_the_same_here(self):
        """The exit says the same thing for both, because the ledger holds the same thing.

        This is not a defect being preserved; it is the boundary #1763 measured, pinned
        so that a future edit cannot quietly add a criterion at the exit and call the two
        cases distinguishable. A card whose second group was handed the wording and one
        whose second group never saw it produce identical readings, differing only in what
        the read log happens to hold.
        """
        def reading_for(candidate_id, handed_over, statement):
            self.store.add(
                statement, "application",
                candidate_id=candidate_id, scope=["交接"], session="sess-a",
                sources=[
                    {"type": "unknown", "claim": "本次会话形成的结论",
                     "independence_group": "sess-a", "verification": "unknown"},
                    {"type": "unknown", "claim": "第二处",
                     "independence_group": "sess-b", "verification": "unknown"},
                ],
            )
            self.store.confirm(candidate_id, "worth discussing")
            if handed_over:
                self.store.record_read(candidate_id, "sess-b", surface="search")
            row = next(r for r in self.store.broadcast("交接 版本 范围")["results"]
                       if r["id"] == candidate_id)
            return {k: v for k, v in row["provenance_reading"].items()
                    if k not in ("handout_rows", "handout_readers")}

        echo = reading_for("d-echo", True, "交接前先把当前版本的范围写下来，能减少返工。")
        independent = reading_for("d-indep", False, "交接前先写下当前范围；返工会少一些。")
        self.assertEqual(echo, independent,
                         "no exit field may separate an echo from an independent arrival")

    def test_a_single_session_card_gains_no_provenance_reading(self):
        """The control cell: one source record and one group name is not a headcount.

        `broadcast` suppresses such a card whole, so this drives the row through a card
        that is released but declares one group, and asserts the payload keeps exactly
        the keys it had.
        """
        self.store.add(
            "交接前先把当前版本的范围写下来，能减少返工。", "application", candidate_id="d-one-group",
            scope=["交接"], session="sess-a",
            sources=[{"type": "unknown", "claim": "本次会话形成的结论",
                      "independence_group": "sess-a", "verification": "unknown"}],
        )
        self.store.confirm("d-one-group", "worth discussing")
        reading = self.store.provenance_reading("d-one-group")
        self.assertEqual(1, reading["source_records"])
        self.assertEqual(1, reading["self_declared_groups"])
        self.assertFalse(reading["readable"], "one group name cannot be read as two people")
        # Suppressed whole: no row, so no key, and the suppression reason is unchanged.
        payload = self.store.broadcast("交接 版本 范围")
        self.assertEqual([], payload["results"])
        self.assertIn("single-session provenance", payload["suppressed"][0]["reason"])
        shown = self.store.show("d-one-group")
        self.assertNotIn("provenance_reading", shown)
        self.assertNotIn("provenance_reading", shown["candidate"])

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

    def _backdate(self, candidate_id, days):
        """Move one card's stored times back, so the two facts differ by days.

        Without this the whole test runs inside one second and `versioned_at ==
        accepted_at` would hold by accident -- which cannot distinguish "read from two
        different rows" from "printed the same value twice".
        """
        for table in ("snapshots", "events"):
            rows = self.store.connection.execute(
                f"SELECT rowid AS rid, created_at FROM {table} WHERE candidate_id=?", (candidate_id,),
            ).fetchall()
            for row in rows:
                moved = datetime.fromisoformat(row["created_at"]) - timedelta(days=days)
                self.store.connection.execute(
                    f"UPDATE {table} SET created_at=? WHERE rowid=?",
                    (moved.isoformat(timespec="seconds"), row["rid"]),
                )
        self.store.connection.commit()

    def test_search_shows_when_the_wording_was_written_and_when_it_was_accepted(self):
        """Two facts, two rows: a search row must not report one of them twice.

        `snapshots.created_at` holds when the sentence was written; the acceptance
        event's own `created_at` holds when that exact wording was accepted. Before
        r115 the search row carried neither, so a reader could not tell a conclusion
        from today from one from a fortnight ago.

        The card's wording is backdated 14 days and the acceptance is not, so the two
        values must differ. A reading that collapsed them -- printed the version time
        as the acceptance time, or vice versa -- would show one date here and fails.
        """
        self.add(candidate_id="d-timed", statement="对普通自行车，自动分配前后制动力可作为待检验的设计目标。",
                 scope=["自行车"], session="sess-a",
                 sources=[{"id": "src-a", "type": "claimed_firsthand", "verification": "unverified",
                           "claim": "用户在一次骑行中注意到前后制动力分配不均",
                           "independence_group": "sess-a", "scope_note": "仅此一次，未复测"}])
        self._backdate("d-timed", 14)
        accepted_at = self.store.record_acceptance("d-timed", "sess-a", path="conversation")
        row = {r["id"]: r for r in self.store.retrieve("自行车 制动力")["results"]}["d-timed"]

        snapshot_time = self.store.connection.execute(
            "SELECT created_at FROM snapshots WHERE candidate_id=? AND version=?",
            ("d-timed", row["version"]),
        ).fetchone()["created_at"]
        event_time = self.store.connection.execute(
            "SELECT created_at FROM events WHERE rowid=?", (accepted_at,)
        ).fetchone()["created_at"]

        self.assertEqual(snapshot_time, row["versioned_at"], "version time must be the snapshot's row")
        self.assertEqual(event_time, row["accepted_at"], "acceptance time must be the event's row")
        self.assertNotEqual(row["versioned_at"], row["accepted_at"],
                            "the two facts are different rows; equal values mean one was reused")

    def test_an_acceptance_for_older_wording_is_not_this_wording_s_acceptance_time(self):
        """Accepted then rewritten: the row keeps a version time and no acceptance time.

        The ledger still holds a `wording_accepted` event, but it names the sentence the
        card no longer carries. Printing its time would date an unread rewrite with the
        older acceptance -- the same falsehood r112d removed from the retrieval gate,
        reappearing on the time surface.
        """
        self.add(candidate_id="d-rewritten-time", statement="长途骑行时，坐垫高度应按髋关节角度而非腿长决定。",
                 scope=["自行车"], session="sess-b",
                 sources=[{"id": "src-r", "type": "claimed_firsthand", "verification": "unverified",
                           "claim": "两次长途骑行后膝盖不适", "independence_group": "sess-b",
                           "scope_note": "两次都超过 80 公里"}])
        self.store.record_acceptance("d-rewritten-time", "sess-b", path="conversation")
        self.store.revise("d-rewritten-time", "长途骑行时，坐垫高度与髋关节角度相关，但不宜作为唯一依据。",
                          "同一会话里的后续修正", session="sess-b")
        self.store.confirm("d-rewritten-time", "可讨论，不是真")
        row = {r["id"]: r for r in self.store.retrieve("坐垫 髋关节")["results"]}["d-rewritten-time"]

        self.assertIn("versioned_at", row)
        self.assertNotIn("accepted_at", row,
                         "an acceptance of the previous sentence must not date this one")

    def test_a_card_with_no_acceptance_reports_no_acceptance_time(self):
        """No acceptance record means no `accepted_at` -- and no empty stub either.

        Only one of the two facts can be absent: every card in this schema has a
        snapshot, so `versioned_at` is always readable *if* the reader asks the
        snapshots table. `accepted_at` is the one that depends on a ledger event naming
        this exact wording, so it is the one a reader can legitimately lack.

        This is the arm the "print unconditionally" mutant turns red: emitting
        `accepted_at=` with an empty tail would claim an acceptance exists and then
        withhold its time, which reads as "accepted, time unknown" -- the exact
        falsehood this whole line of work removes.
        """
        self.add(candidate_id="d-plain", statement="交接约定值得讨论",
                 sources=[{"id": "src-p", "type": "claimed_firsthand", "verification": "unverified",
                           "claim": "两次交接都靠口头约定", "independence_group": "person-p",
                           "scope_note": "同一团队"}])
        # Discussable so it is retrievable at all: this arm is about the missing
        # acceptance, not about passing the retrieval gate.
        self.store.confirm("d-plain", "可讨论，不是真")
        row = {r["id"]: r for r in self.store.retrieve("交接约定")["results"]}["d-plain"]
        self.assertNotIn("accepted_at", row)
        self.assertTrue(str(row.get("versioned_at", "")).strip(),
                        "versioned_at present but empty")
        for key in ("versioned_at", "accepted_at"):
            if key in row:
                self.assertTrue(str(row[key]).strip(), f"{key} present but empty")

    def test_chat_context_carries_the_same_two_time_facts_as_search(self):
        """`dojo chat` hands the model the retrieval context; it must not lose the times.

        Search and chat build their rows from the same `Store.retrieve`, but chat copies
        a fixed key list -- which is exactly how `scope_note` once survived search and
        vanished here. The values are compared to the search row's, not just their
        presence, so a chat-side fallback that prints different times fails.
        """
        self.add(candidate_id="d-chat-time", statement="夜间骑行时，尾灯的可见角度比亮度更影响被识别距离。",
                 scope=["自行车"], session="sess-c",
                 sources=[{"id": "src-c", "type": "claimed_firsthand", "verification": "unverified",
                           "claim": "夜骑时后车多次贴近", "independence_group": "sess-c",
                           "scope_note": "单次观察"}])
        self._backdate("d-chat-time", 3)
        self.store.record_acceptance("d-chat-time", "sess-c", path="conversation")
        row = {r["id"]: r for r in self.store.retrieve("尾灯")["results"]}["d-chat-time"]
        item = {i["id"]: i for i in live._retrieval_for_prompt(self.store, "尾灯")["results"]}["d-chat-time"]
        self.assertEqual(row["versioned_at"], item["versioned_at"])
        self.assertEqual(row["accepted_at"], item["accepted_at"])

    def test_export_header_carries_both_times_and_omits_them_when_absent(self):
        """The participant handed the frozen prompt gets the times, appended only.

        One card with both facts and one with no acceptance: the first's header must name
        both values, the second's must carry no `accepted_at=` stub. Compared by value
        taken from the tables, so a header printing the current clock would fail.
        """
        self.store.add(
            "交接前先把当前版本的范围写下来，能减少临场改口。", "application",
            candidate_id="d-export-time", scope=["交接"], session="sess-x",
            sources=[
                {"id": "src-x", "type": "claimed_firsthand", "verification": "unverified",
                 "claim": "我在两次交接里都吃过口头改口的亏", "independence_group": "person-x",
                 "scope_note": "两次都在同一团队"},
                {"id": "src-y", "type": "abstract_reasoning", "verification": "not_evidence",
                 "claim": "书面范围把隐式假设变成可检查项", "independence_group": "method-v1",
                 "scope_note": "推演"},
            ],
        )
        self.store.confirm("d-export-time", "可讨论，不是真")
        self._backdate("d-export-time", 7)
        self.store.record_acceptance("d-export-time", "sess-x", path="conversation")
        exported = self.store.export_prompt("c", ["d-export-time"], 8000, self.root / "exports")
        text = Path(exported["path"]).read_text(encoding="utf-8")
        header = next(line for line in text.splitlines() if line.startswith("[d-export-time"))
        basis = self.store.time_basis("d-export-time")
        self.assertIn(f"versioned_at={basis['versioned_at']}", header)
        self.assertIn(f"accepted_at={basis['accepted_at']}", header)
        # Appended inside the bracket, after everything that was already there.
        self.assertTrue(header.endswith("]"))
        self.assertIn("| independent=true | versioned_at=", header)

        # Discussable so the export gate lets it through at all: this arm is about the
        # missing *acceptance*, not about passing the status gate.
        self.add(candidate_id="d-no-accept", statement="讨论结束后把未解决的疑问单独列出。",
                 sources=[{"id": "src-n", "type": "claimed_firsthand", "verification": "unverified",
                           "claim": "两次会都有人以为疑问已经记下", "independence_group": "person-n",
                           "scope_note": "同一团队"}])
        self.store.confirm("d-no-accept", "可讨论，不是真")
        exported = self.store.export_prompt("c", ["d-no-accept"], 8000, self.root / "exports")
        header = next(line for line in Path(exported["path"]).read_text(encoding="utf-8").splitlines()
                      if line.startswith("[d-no-accept"))
        self.assertNotIn("accepted_at=", header, "no acceptance must not become an empty stub")

    def test_show_and_broadcast_carry_the_same_two_times_search_does(self):
        """r1721: `show` and `broadcast` printed provenance but not *when*.

        `search`, the chat context and `export` all answer "when was this written and
        when was it accepted"; the two exits a reader uses to look at one card or to
        cross sessions answered only "where did it come from". Before this, the two
        surfaces were inconsistent about the same reading.

        The times go *beside* `candidate`, never inside it: `candidate` is the stored
        state byte for byte, and the full-listing test above compares it to that. The
        values are compared against `time_basis`, so a surface printing its own clock
        fails.
        """
        self.store.add(
            "交接前先写下当前版本的范围，能减少返工。", "application",
            candidate_id="d-two-exits", scope=["跨会话交接时"], session="sess-a",
            sources=[{"id": "src-1", "type": "unknown", "claim": "第一个会话形成的结论",
                      "independence_group": "sess-a", "verification": "unknown"}],
        )
        self.store.attach_source("d-two-exits", {
            "id": "src-2", "type": "unknown", "claim": "第二个会话独立得出同一结论",
            "independence_group": "sess-b", "verification": "unknown",
        }, session="sess-b")
        self.store.confirm("d-two-exits", "值得在新讨论里检索", session="sess-a")
        self._backdate("d-two-exits", 5)
        self.store.record_acceptance("d-two-exits", "sess-a", path="discuss_conclusion")

        basis = self.store.time_basis("d-two-exits")
        self.assertEqual({"versioned_at", "accepted_at", "acceptance_path"}, set(basis))

        shown = self.store.show("d-two-exits")
        self.assertEqual(basis, shown["time_basis"],
                         "show must report the ledger's times, not its own")
        self.assertEqual(
            [], [k for k in ("versioned_at", "accepted_at", "acceptance_path", "agreed_at")
                 if k in shown["candidate"]],
            "candidate is the stored state; the times sit beside it, not inside it",
        )

        broadcast = self.store.broadcast("交接 版本 范围")
        row = next(r for r in broadcast["results"] if r["id"] == "d-two-exits")
        for key, value in basis.items():
            self.assertEqual(value, row[key], f"broadcast dropped {key}")
        # And the same values `search` reports, so the two exits agree.
        searched = next(r for r in self.store.retrieve("交接 版本 范围")["results"]
                        if r["id"] == "d-two-exits")
        for key in basis:
            self.assertEqual(searched[key], row[key])

    def test_a_card_with_no_acceptance_gains_no_accepted_at_on_show_or_broadcast(self):
        """The absent fact stays absent on both new surfaces (the r115 rule).

        A broadcast row has to exist for this to prove anything: a single-session card
        is suppressed whole, and an empty result would pass the assertion while testing
        nothing. So the control card gets a second independent source.
        """
        self.store.add(
            "自行车制动力分配只作待检验的设计目标。", "application",
            candidate_id="d-bare-two", scope=["普通自行车"], session="sess-c",
            sources=[{"id": "src-3", "type": "unknown", "claim": "第三个会话的提案",
                      "independence_group": "sess-c", "verification": "unknown"}],
        )
        self.store.attach_source("d-bare-two", {
            "id": "src-4", "type": "unknown", "claim": "第四个会话独立提出同一路线",
            "independence_group": "sess-d", "verification": "unknown",
        }, session="sess-d")
        self.store.confirm("d-bare-two", "可以拿来讨论", session="sess-c")

        shown = self.store.show("d-bare-two")
        self.assertIn("versioned_at", shown["time_basis"])
        self.assertNotIn("accepted_at", shown["time_basis"],
                         "no acceptance must not become an empty stub")
        self.assertNotIn("acceptance_path", shown["time_basis"])

        broadcast = self.store.broadcast("自行车 制动力")
        self.assertIn("d-bare-two", [r["id"] for r in broadcast["results"]],
                      "the row must exist, or the next two assertions prove nothing")
        row = next(r for r in broadcast["results"] if r["id"] == "d-bare-two")
        self.assertNotIn("accepted_at", row)
        self.assertNotIn("acceptance_path", row)
        self.assertTrue(str(row["versioned_at"]).strip())

    def test_a_status_change_does_not_move_the_wording_s_date(self):
        """`versioned_at` dates the sentence, not the row the card happens to hold.

        r1627: `confirm`, `revoke` and `attach_source` each write a new version with the
        same wording, and reading the current version's row printed *today* as "when this
        sentence was written". The failure was invisible in a test that ran inside one
        second, so the first version is backdated to October first -- the same reason
        `_backdate` exists above.
        """
        self.add(candidate_id="d-stable", statement="交接前先把当前版本的范围写下来。",
                 scope=["交接"], session="sess-s",
                 sources=[{"id": "src-s", "type": "claimed_firsthand", "verification": "unverified",
                           "claim": "两次交接都靠口头约定", "independence_group": "person-s",
                           "scope_note": "同一团队"}])
        self._backdate("d-stable", 35)
        written_at = self.store.time_basis("d-stable")["versioned_at"]
        digests = set()
        for step in (
            lambda: self.store.confirm("d-stable", "可讨论，不是真"),
            lambda: self.store.revoke("d-stable", "再想想"),
            lambda: self.store.attach_source("d-stable",
                                             {"id": "src-s2", "type": "abstract_reasoning",
                                              "verification": "not_evidence", "claim": "书面范围把假设变成可检查项",
                                              "independence_group": "method-v1", "scope_note": "推演"},
                                             "sess-t"),
        ):
            state = step()
            digests.add(wording_digest(state))
            self.assertEqual(written_at, self.store.time_basis("d-stable")["versioned_at"],
                             "a version bump that leaves the sentence alone must not redate it")
        self.assertEqual(1, len(digests), "the sentence never changed across these steps")
        self.assertGreater(self.store.show("d-stable")["candidate"]["version"], 1,
                           "the versions really were written, so the constant value is not a no-op")

    def test_a_rewrite_then_restore_dates_from_the_restored_wording(self):
        """After revise-then-revise-back, `versioned_at` is the restore, not the original.

        The digest is wording identity: the same sentence reached again is the same
        sentence, and the first version holding *that* wording is the one that was
        restored. Pinned so a later "use the original add row" shortcut has to argue for
        itself -- a reader asking "when was this sentence written" is looking at the text
        in front of them.
        """
        self.add(candidate_id="d-round", statement="坐垫高度应按髋关节角度决定。", session="sess-r",
                 sources=[{"id": "src-r1", "type": "claimed_firsthand", "verification": "unverified",
                           "claim": "两次长途骑行后膝盖不适", "independence_group": "person-r",
                           "scope_note": "两次都超过 80 公里"}])
        self._backdate("d-round", 20)
        self.store.revise("d-round", "坐垫高度与髋关节角度相关，但不宜作为唯一依据。", "修正",
                          session="sess-r")
        self.store.revise("d-round", "坐垫高度应按髋关节角度决定。", "改回", session="sess-r")
        current = self.store.time_basis("d-round")["versioned_at"]
        latest = self.store.connection.execute(
            "SELECT created_at FROM snapshots WHERE candidate_id=? AND version=?",
            ("d-round", self.store.show("d-round")["candidate"]["version"]),
        ).fetchone()["created_at"]
        self.assertNotEqual(latest, current, "the restore's own row is not the wording's first appearance")

    def test_export_names_the_route_that_recorded_the_acceptance(self):
        """Two acceptances, same header shape, different `acceptance_path`.

        r1627: a backfilled acceptance prints the moment of the copy, which can be weeks
        after the agreement it records. Nothing in the export said so, so the two were
        indistinguishable to the reader handed the prompt. Existing bytes are unchanged;
        the new field is appended inside the same bracket, and omitted when the ledger
        carries no path at all.
        """
        for card, path in (("d-conv", "discuss_conclusion"), ("d-backfill", "backfill_from_trace")):
            self.store.add(
                f"{card} 的交接范围需要先写下来。", "application", candidate_id=card, scope=["交接"],
                session=f"sess-{card}",
                sources=[{"id": f"src-{card}-1", "type": "claimed_firsthand", "verification": "unverified",
                          "claim": "两次交接都吃过口头的亏", "independence_group": f"person-{card}",
                          "scope_note": "两次都在同一团队"},
                         {"id": f"src-{card}-2", "type": "abstract_reasoning",
                          "verification": "not_evidence", "claim": "书面范围把隐式假设变成可检查项",
                          "independence_group": "method-v1", "scope_note": "推演"}],
            )
            self.store.confirm(card, "可讨论，不是真")
            self.store.record_acceptance(card, f"sess-{card}", path=path)
            exported = self.store.export_prompt("c", [card], 8000, self.root / "exports")
            header = next(line for line in Path(exported["path"]).read_text(encoding="utf-8").splitlines()
                          if line.startswith(f"[{card}"))
            self.assertIn(f"acceptance_path={path}", header)
            self.assertTrue(header.endswith("]"))
            self.assertIn("| independent=true | versioned_at=", header)
            self.assertIn("| accepted_at=", header)
            self.assertIn(f"| accepted_at={self.store.time_basis(card)['accepted_at']} | acceptance_path={path}]",
                          header, "the path follows the time it qualifies, nothing reordered")

    def test_chat_context_carries_the_acceptance_route_too(self):
        """`_context_item` copies a fixed key list; the route must not fall off it.

        r1627 added a third time fact, and `live.CONTEXT_TIME_FIELDS` is exactly the
        kind of place where a new field survives search and vanishes on the chat side --
        that is how `scope_note` was lost once. The absence arm is checked in the same
        test so "carries the route" cannot be satisfied by printing an empty one.
        """
        for card, path in (("d-chat-path", "discuss_conclusion"), ("d-chat-none", None)):
            self.add(candidate_id=card, statement=f"{card} 的交接范围先写下来。", scope=["交接"],
                     session=f"sess-{card}",
                     sources=[{"id": f"src-{card}", "type": "claimed_firsthand",
                               "verification": "unverified", "claim": "两次交接都吃过口头的亏",
                               "independence_group": f"person-{card}", "scope_note": "同一团队"}])
            self.store.confirm(card, "可讨论，不是真")   # else it is not retrievable at all
            if path:
                self.store.record_acceptance(card, f"sess-{card}", path=path)
        query = "交接范围"
        search = {r["id"]: r for r in self.store.retrieve(query)["results"]}
        chat = {i["id"]: i for i in live._retrieval_for_prompt(self.store, query)["results"]}
        self.assertEqual("discuss_conclusion", chat["d-chat-path"]["acceptance_path"])
        self.assertEqual(search["d-chat-path"]["acceptance_path"],
                         chat["d-chat-path"]["acceptance_path"])
        self.assertNotIn("acceptance_path", chat["d-chat-none"],
                         "a card with no acceptance must not gain an empty route")

    def test_chat_context_says_the_wording_was_never_accepted(self):
        """#1831: `status=discussable` covers both an accepted wording and an unblocked one.

        `list` and `retrieve` already carried `unaccepted_draft`; the chat hand-off did
        not, so the model could not tell "nobody has agreed to this wording" from
        "accepted". The accepted card is the control: if the key appeared on it too, it
        would say nothing about acceptance.
        """
        for card, accepted in (("d-chat-nobody", False), ("d-chat-yes", True)):
            self.add(candidate_id=card, statement=f"{card} 的交接范围先写下来。", scope=["交接"],
                     session=f"sess-{card}",
                     sources=[{"id": f"src-{card}", "type": "model_generated",
                               "verification": "unverified", "claim": "模型这一轮的措辞",
                               "independence_group": f"sess-{card}", "scope_note": ""}])
            if accepted:
                self.store.accept_draft(card, session=f"sess-{card}")
            self.store.confirm(card, "可讨论，不是真")
        query = "交接范围"
        search = {r["id"]: r for r in self.store.retrieve(query)["results"]}
        chat = {i["id"]: i for i in live._retrieval_for_prompt(self.store, query)["results"]}
        self.assertIs(True, chat["d-chat-nobody"].get("unaccepted_draft"))
        self.assertIs(True, search["d-chat-nobody"].get("unaccepted_draft"))
        self.assertNotIn("unaccepted_draft", chat["d-chat-yes"],
                         "an accepted wording must not be handed over as unaccepted")

    def test_chat_context_carries_when_each_source_entered(self):
        """#1831: the provenance dates reach the model, and `search` keeps its shape."""
        self.add(candidate_id="d-chat-basis", statement="交接前先写下范围。", scope=["交接"],
                 session="sess-cb",
                 sources=[{"id": "src-cb", "type": "claimed_firsthand", "verification": "unverified",
                           "claim": "两次交接都吃过口头的亏", "independence_group": "person-cb",
                           "scope_note": "同一团队"}])
        self.store.confirm("d-chat-basis", "可讨论，不是真")
        query = "交接"
        chat = {i["id"]: i for i in live._retrieval_for_prompt(self.store, query)["results"]}
        basis = chat["d-chat-basis"].get("source_basis") or {}
        self.assertIn("src-cb", basis.get("sources") or {})
        self.assertIn("entered_at", (basis["sources"]["src-cb"]))
        search = {r["id"]: r for r in self.store.retrieve(query)["results"]}
        self.assertNotIn("source_basis", search["d-chat-basis"],
                         "this stays out of `search`'s output shape")

    def test_an_acceptance_with_no_recorded_route_prints_no_route(self):
        """An old event carries no `path`; the header must keep exactly its old shape."""
        self.store.add(
            "旧账本里的接受没有记来路。", "application", candidate_id="d-nopath", scope=["交接"],
            session="sess-np",
            sources=[{"id": "src-np-1", "type": "claimed_firsthand", "verification": "unverified",
                      "claim": "两次交接都吃过口头的亏", "independence_group": "person-np",
                      "scope_note": "同一团队"},
                     {"id": "src-np-2", "type": "abstract_reasoning", "verification": "not_evidence",
                      "claim": "书面范围把隐式假设变成可检查项", "independence_group": "method-v1",
                      "scope_note": "推演"}],
        )
        self.store.confirm("d-nopath", "可讨论，不是真")
        state = self.store.show("d-nopath")["candidate"]
        self.store._event("d-nopath", "wording_accepted", {
            "session": "sess-np", "statement_digest": wording_digest(state),
            "candidate_id": "d-nopath",
        })
        basis = self.store.time_basis("d-nopath")
        self.assertIn("accepted_at", basis)
        self.assertNotIn("acceptance_path", basis, "no recorded route is an absent key, not an empty one")
        exported = self.store.export_prompt("c", ["d-nopath"], 8000, self.root / "exports")
        header = next(line for line in Path(exported["path"]).read_text(encoding="utf-8").splitlines()
                      if line.startswith("[d-nopath"))
        self.assertNotIn("acceptance_path=", header)
        self.assertTrue(header.endswith(f"accepted_at={basis['accepted_at']}]"))

    def test_a_backfilled_acceptance_can_state_when_the_agreement_happened(self):
        """r1638: the record time and the agreement time are two facts, and both print.

        A reader copying an acceptance out of a trace file writes it weeks after the
        agreement. Before this the writer had no parameter for the moment, so every
        backfill dated the copy -- the real m1.7 card carried 2026-11-21 for a sentence
        agreed 2026-10-17, 34.9 days apart (`.scratch/dojo-1637/probe.json`). The moment
        now rides in `details.agreed_at`, so no column changes and an old event keeps
        exactly the details it had.
        """
        self.add(candidate_id="d-agreed", statement="交接范围应在开始前写下来而不是事后补。",
                 scope=["交接"], session="sess-ag",
                 sources=[{"id": "src-ag-1", "type": "claimed_firsthand", "verification": "unverified",
                           "claim": "两次交接都吃过口头的亏", "independence_group": "person-ag",
                           "scope_note": "两次都在同一团队"},
                          {"id": "src-ag-2", "type": "abstract_reasoning", "verification": "not_evidence",
                           "claim": "书面范围把隐式假设变成可检查项", "independence_group": "method-v1",
                           "scope_note": "推演"}])
        self.store.confirm("d-agreed", "可讨论，不是真")
        self._backdate("d-agreed", 35)
        self.store.record_acceptance("d-agreed", "sess-ag", path="backfill_from_trace",
                                     agreed_at="2026-10-17T22:52:15+00:00")

        basis = self.store.time_basis("d-agreed")
        self.assertEqual("2026-10-17T22:52:15+00:00", basis["agreed_at"])
        self.assertNotEqual(basis["agreed_at"], basis["accepted_at"],
                            "the copy was recorded now; the agreement was a month ago")
        self.assertEqual("backfill_from_trace", basis["acceptance_path"])
        exported = self.store.export_prompt("c", ["d-agreed"], 8000, self.root / "exports")
        header = next(line for line in Path(exported["path"]).read_text(encoding="utf-8").splitlines()
                      if line.startswith("[d-agreed"))
        self.assertIn("| accepted_at=", header)
        self.assertIn("| agreed_at=2026-10-17T22:52:15+00:00]", header,
                      "the agreement moment is the last field, inside the same bracket")
        self.assertLess(header.index("acceptance_path="), header.index("agreed_at="),
                        "appended after the fields r1627 added, not interleaved")

    def test_the_record_time_and_the_agreement_time_are_both_kept(self):
        """The fix must add a fact, not move `accepted_at` onto the older moment.

        If the change had overwritten the record time, a reader could no longer tell
        that the acceptance was written later than agreed -- exactly what r1627's
        `acceptance_path` was added to expose. Both keys, distinct values.
        """
        self.add(candidate_id="d-both-times", statement="跨团队交接先写范围再开工。",
                 scope=["交接"], session="sess-bt",
                 sources=[{"id": "src-bt-1", "type": "claimed_firsthand", "verification": "unverified",
                           "claim": "两次交接都吃过口头的亏", "independence_group": "person-bt",
                           "scope_note": "同一团队"},
                          {"id": "src-bt-2", "type": "abstract_reasoning", "verification": "not_evidence",
                           "claim": "书面范围把隐式假设变成可检查项", "independence_group": "method-v1",
                           "scope_note": "推演"}])
        self.store.confirm("d-both-times", "可讨论，不是真")
        self.store.record_acceptance("d-both-times", "sess-bt", path="backfill_from_trace",
                                     agreed_at="2026-10-17T22:52:15+00:00")
        event = [e for e in self.store.history("d-both-times")["events"]
                 if e["event"] == "wording_accepted"][-1]
        basis = self.store.time_basis("d-both-times")
        self.assertEqual(event["created_at"], basis["accepted_at"],
                         "accepted_at stays the event row's own time")
        self.assertEqual("2026-10-17T22:52:15+00:00", event["details"]["agreed_at"])

    def test_an_event_without_the_moment_prints_no_invented_time(self):
        """An old ledger row has no `agreed_at`; the header must not gain one.

        The tempting shortcut is to fall back to `versioned_at` (the sentence and the
        agreement usually share a day) or to `accepted_at`. Either would print a moment
        the ledger never recorded, which is the same falsehood in a new field.
        """
        self.add(candidate_id="d-no-moment", statement="旧账本里的接受没有记当时那一刻。",
                 scope=["交接"], session="sess-nm",
                 sources=[{"id": "src-nm-1", "type": "claimed_firsthand", "verification": "unverified",
                           "claim": "两次交接都吃过口头的亏", "independence_group": "person-nm",
                           "scope_note": "同一团队"},
                          {"id": "src-nm-2", "type": "abstract_reasoning", "verification": "not_evidence",
                           "claim": "书面范围把隐式假设变成可检查项", "independence_group": "method-v1",
                           "scope_note": "推演"}])
        self.store.confirm("d-no-moment", "可讨论，不是真")
        state = self.store.show("d-no-moment")["candidate"]
        self.store._event("d-no-moment", "wording_accepted", {
            "session": "sess-nm", "path": "backfill_from_trace",
            "statement_digest": wording_digest(state), "candidate_id": "d-no-moment",
        })
        basis = self.store.time_basis("d-no-moment")
        self.assertIn("accepted_at", basis)
        self.assertNotIn("agreed_at", basis, "no recorded moment is an absent key")
        exported = self.store.export_prompt("c", ["d-no-moment"], 8000, self.root / "exports")
        header = next(line for line in Path(exported["path"]).read_text(encoding="utf-8").splitlines()
                      if line.startswith("[d-no-moment"))
        self.assertNotIn("agreed_at=", header)
        self.assertTrue(header.endswith("acceptance_path=backfill_from_trace]"),
                        "the old header keeps exactly the fields r1627 gave it")

    def test_accept_draft_records_the_moment_too(self):
        """Both acceptance writers drop the moment or neither does.

        `accept_draft` is the resumed-conversation route and writes its own event shape.
        A fix applied only to `record_acceptance` would leave every resumed acceptance
        dating the write, so this arm is checked separately rather than inferred.
        """
        self.add(candidate_id="d-draft-moment", statement="会话结束时留下的那句草稿。",
                 session="sess-dm",
                 sources=[{"id": "src-dm-1", "type": "model_generated", "verification": "unverified",
                           "claim": "模型写的草稿", "independence_group": "sess-dm",
                           "scope_note": "单一会话"}])
        self.store.accept_draft("d-draft-moment", session="sess-dm",
                                agreed_at="2026-10-17T22:52:15+00:00")
        event = [e for e in self.store.history("d-draft-moment")["events"]
                 if e["event"] == "draft_accepted"][-1]
        self.assertEqual("2026-10-17T22:52:15+00:00", event["details"].get("agreed_at"))
        self.assertEqual("2026-10-17T22:52:15+00:00",
                         self.store.time_basis("d-draft-moment")["agreed_at"])

    def test_a_moment_that_is_not_an_aware_instant_is_refused(self):
        """A string that only looks like a time must not enter the ledger.

        Stored times carry an offset and second resolution. A naive value would compare
        as earlier on one platform and later on another, and a value with microseconds
        can exceed `created_at` by rounding alone when the two are the same moment.
        """
        self.add(candidate_id="d-bad-moment", statement="这条的接受时刻会被拒。", session="sess-bm")
        for bad in ("2026-10-17T22:52:15", "yesterday", ""):
            with self.assertRaises(DojoError, msg=f"{bad!r} must be refused"):
                self.store.record_acceptance("d-bad-moment", "sess-bm", path="backfill",
                                             agreed_at=bad)
        self.assertEqual([], [e for e in self.store.history("d-bad-moment")["events"]
                              if e["event"] == "wording_accepted"],
                         "a refused moment writes no event at all")
        self.store.record_acceptance("d-bad-moment", "sess-bm", path="backfill",
                                     agreed_at="2026-10-17T22:52:15.681885+00:00")
        event = [e for e in self.store.history("d-bad-moment")["events"]
                 if e["event"] == "wording_accepted"][-1]
        self.assertEqual("2026-10-17T22:52:15+00:00", event["details"]["agreed_at"],
                         "sub-second precision is truncated to the ledger's resolution")

    # --- merge must not silently cost a recorded acceptance (r1653) ----------------
    #
    # Four arms, because a guard that only refuses is as wrong as one that never does:
    # "refuse every merge" passes the first two assertions and breaks the library.

    def _two_cards(self, accepted_id="d-keep", other_id="d-other"):
        self.add(candidate_id=accepted_id,
                 statement="对普通自行车，自动分配前后制动力可作为待检验的设计目标。",
                 sources=[{"id": "src-keep", "type": "claimed_firsthand", "claim": "甲",
                           "verification": "unverified"}])
        self.add(candidate_id=other_id,
                 statement="普通自行车下，前后制动力自动分配是一个值得检验的设计目标。",
                 sources=[{"id": "src-other", "type": "claimed_firsthand", "claim": "乙",
                           "verification": "unverified"}])

    def test_merging_away_an_accepted_card_is_refused_and_names_both_cards(self):
        """Arm 1. The sentence would survive unchanged and the acceptance would not.

        Before r1653 this merged, left the canonical card byte-identical and unaccepted:
        `has_acceptance` false, gone from search, no `accepted_at` in the export header.
        Nothing raised, so a reader could not tell that apart from a card nobody had
        ever accepted.
        """
        self._two_cards()
        self.store.record_acceptance("d-keep", "sess-a", path="discuss_conclusion")
        versions_before = {cid: self.store.history(cid)["versions"] for cid in ("d-keep", "d-other")}
        with self.assertRaises(MergeRefused) as caught:
            self.store.merge("d-keep", "d-other", confirmed=True, reason="主持人判断等价")

        # Red on the refusal's own content first: which card was protected, which way.
        details = caught.exception.details
        self.assertEqual("d-keep", details["accepted_card"])
        self.assertEqual(("d-keep", "d-other"), (details["source"], details["target"]))
        self.assertIn("d-keep", str(caught.exception))
        self.assertIn("accept", str(caught.exception))

        # And the refusal really did not half-apply.
        self.assertEqual("d-keep", self.store.show("d-keep")["resolved_id"])
        self.assertEqual(versions_before,
                         {cid: self.store.history(cid)["versions"] for cid in ("d-keep", "d-other")})
        self.assertTrue(self.store.has_acceptance("d-keep"))
        self.assertEqual(["d-keep"], [r["id"] for r in self.store.retrieve("自行车 制动力")["results"]],
                         "the accepted card must still be the one search hands back")

        # The refusal is on the ledger, appended, with no version of its own.
        events = self.store.history("d-keep")["events"]
        refusals = [event for event in events if event["event"] == "merge_refused"]
        self.assertEqual(1, len(refusals))
        self.assertEqual({"d-keep", "d-other"},
                         {refusals[0]["details"]["source"], refusals[0]["details"]["target"]})
        self.assertTrue(refusals[0]["details"]["reasons"], "a refusal must say why")
        self.assertNotIn("version", refusals[0]["details"], "refusing is not a change to the card")

    def test_merging_into_an_accepted_card_is_refused_when_the_union_changes_the_wording(self):
        """Arm 2. The same failure reached from the other side.

        `merge` unions `premises`/`scope`/..., and those are part of the digest an
        acceptance is bound to. So absorbing a second card silently turned the
        acceptance into "accepted a sentence that is no longer here": `accepted_at`
        disappeared and the audit filed it as superseded, with no complaint.
        """
        self.add(candidate_id="d-keep", statement="长途骑行时，坐垫高度与髋关节角度相关。",
                 premises=["甲会话的前提"],
                 sources=[{"id": "src-keep", "type": "claimed_firsthand", "claim": "甲",
                           "verification": "unverified"}])
        self.add(candidate_id="d-other", statement="长途骑行时，坐垫高度与髋关节角度相关，不宜作为唯一依据。",
                 premises=["乙会话的前提"],
                 sources=[{"id": "src-other", "type": "claimed_firsthand", "claim": "乙",
                           "verification": "unverified"}])
        self.store.record_acceptance("d-keep", "sess-a", path="discuss_conclusion")
        basis_before = self.store.time_basis("d-keep")
        self.assertIn("accepted_at", basis_before)

        with self.assertRaises(MergeRefused) as caught:
            self.store.merge("d-other", "d-keep", confirmed=True, reason="主持人判断等价")

        details = caught.exception.details
        self.assertEqual("d-keep", details["accepted_card"])
        self.assertTrue(details["wording_changed"])
        self.assertEqual(["premises"], details["changed_content_fields"])
        self.assertIn("premises", str(caught.exception))
        # The acceptance is untouched, and the card still says what it said.
        self.assertEqual(basis_before, self.store.time_basis("d-keep"))
        self.assertEqual(["甲会话的前提"], self.store.show("d-keep")["candidate"]["premises"])

    def test_merging_two_cards_nobody_accepted_still_works(self):
        """Arm 3, the anti-over-tightening control.

        Without this arm the guard could be "refuse every merge" and the first two
        assertions would still pass while the command stopped being a merge.
        """
        self._two_cards()
        merged = self.store.merge("d-other", "d-keep", confirmed=True, reason="主持人判断等价")
        self.assertEqual({"src-keep", "src-other"}, {item["id"] for item in merged["sources"]})
        self.assertIn("普通自行车下，前后制动力自动分配是一个值得检验的设计目标。", merged["aliases"])
        self.assertEqual("d-keep", self.store.show("d-other")["resolved_id"])
        refusals = [event for cid in ("d-keep", "d-other")
                    for event in self.store.history(cid)["events"] if event["event"] == "merge_refused"]
        self.assertEqual([], refusals)

    def test_an_accepted_card_may_absorb_a_card_that_does_not_change_its_wording(self):
        """Arm 4. The rule is "the acceptance must still hold", not "accepted cards freeze".

        The union adds sources and an alias but no content field, so the digest is
        unchanged and the acceptance is still an acceptance of this sentence.
        """
        self._two_cards()
        self.store.record_acceptance("d-keep", "sess-a", path="discuss_conclusion")
        basis_before = self.store.time_basis("d-keep")
        merged = self.store.merge("d-other", "d-keep", confirmed=True, reason="主持人判断等价")
        self.assertEqual({"src-keep", "src-other"}, {item["id"] for item in merged["sources"]})
        self.assertEqual(basis_before, self.store.time_basis("d-keep"),
                         "an unchanged wording keeps the acceptance and its recorded moment")
        self.assertTrue(self.store.has_acceptance("d-keep"))
        self.assertEqual(["d-keep"], [r["id"] for r in self.store.retrieve("自行车 制动力")["results"]])
        # And it is still reversible, which is what makes this allowed branch safe.
        restored = self.store.unmerge("d-other", "复核后撤销")
        self.assertEqual(["src-keep"], [item["id"] for item in restored["target"]["sources"]])
        self.assertTrue(self.store.has_acceptance("d-keep"))

    # ---- #1801: when did each source record enter the library -------------------
    #
    # `time_basis` dates the wording and says nothing about the provenance rows beside
    # it, so a reader weighing a source could not say whether the evidence arrived
    # before or after the claim it is offered for.

    def _two_sources(self, candidate_id="d-src-time"):
        self.add(
            candidate_id=candidate_id, statement="来源的入库时刻应当可读，而不是靠猜。",
            session="sess-a",
            sources=[{"id": "src-first", "type": "unknown", "claim": "第一份材料",
                      "independence_group": "sess-a", "verification": "unknown"}],
        )
        self.store.attach_source(candidate_id, {
            "id": "src-second", "type": "unknown", "claim": "第二个会话带来的材料",
            "independence_group": "sess-b", "verification": "unknown",
        }, session="sess-b")
        return candidate_id

    def _ledger_at(self, candidate_id, event_name):
        return next(event["created_at"] for event in self.store.history(candidate_id)["events"]
                    if event["event"] == event_name)

    def _backdate_event(self, candidate_id, event_name, days):
        """Move one ledger row back, so a value read from today cannot match it.

        Moving the whole card would move both sources' moments together and let a
        constant satisfy "two different moments"; moving one row keeps them apart.
        """
        row = self.store.connection.execute(
            "SELECT seq,created_at FROM events WHERE candidate_id=? AND event=? ORDER BY seq",
            (candidate_id, event_name),
        ).fetchone()
        self.assertIsNotNone(row, f"no {event_name} event to backdate")
        moved = (datetime.fromisoformat(row["created_at"]) - timedelta(days=days)).isoformat(timespec="seconds")
        self.store.connection.execute("UPDATE events SET created_at=? WHERE seq=?", (moved, row["seq"]))
        if event_name in ("add", "load_simulated_seed"):
            version = json.loads(self.store.connection.execute(
                "SELECT details_json FROM events WHERE seq=?", (row["seq"],)).fetchone()[0]).get("version", 1)
            self.store.connection.execute(
                "UPDATE snapshots SET created_at=? WHERE candidate_id=? AND version=?",
                (moved, candidate_id, version))
        self.store.connection.commit()
        return moved

    def test_each_source_reports_the_event_that_introduced_it(self):
        """Two acquisitions, two ledger rows, two different moments.

        A constant, a card-level date or one read of the clock cannot satisfy this: the
        two values must differ *and* each must equal the row that introduced it.
        """
        cid = self._two_sources()
        moved = self._backdate_event(cid, "add", 3)
        attach_at = self._ledger_at(cid, "attach_source")
        # Broadcast carries discussable cards only; without this the row would be
        # absent and the assertion at the end would prove nothing.
        self.store.confirm(cid, "值得讨论", session="sess-a")

        basis = self.store.source_basis(cid)
        self.assertEqual({"src-first": {"entered_at": moved, "entered_by": "add"},
                          "src-second": {"entered_at": attach_at, "entered_by": "attach_source"}},
                         basis["sources"])
        self.assertNotEqual(basis["sources"]["src-first"]["entered_at"],
                            basis["sources"]["src-second"]["entered_at"],
                            "one moment for two acquisitions means the clock was read once, not the ledger")

        shown = self.store.show(cid)
        self.assertEqual(basis, shown["source_basis"], "show must report the ledger's rows")

        row = next(r for r in self.store.broadcast("来源 入库 时刻")["results"] if r["id"] == cid)
        self.assertEqual(basis, row["source_basis"], "broadcast must report the same rows")

    def test_the_source_time_is_the_ledger_row_not_the_current_clock(self):
        """The likeliest false green: the field filled from `_now()`.

        One acquisition row is moved four days back. An implementation that stamps the
        read (or reuses `versioned_at`) reports something else for that source and fails
        here, while the untouched source still matches.
        """
        cid = self._two_sources()
        moved = self._backdate_event(cid, "attach_source", 4)
        basis = self.store.source_basis(cid)
        self.assertEqual(moved, basis["sources"]["src-second"]["entered_at"],
                         "the moment is the attachment row's, not the moment of the read")
        self.assertNotEqual(basis["sources"]["src-second"]["entered_at"],
                            self.store.show(cid)["time_basis"]["versioned_at"],
                            "an acquisition is not the wording's date")
        # Sanity: the moved row really is days in the past, so "today" is distinguishable.
        gap = datetime.now(datetime.fromisoformat(moved).tzinfo) - datetime.fromisoformat(moved)
        self.assertGreater(gap.days, 3, "the control moment must be distinguishable from now")

    def test_a_source_copied_by_a_merge_dates_from_where_it_entered(self):
        """A merged card holds a source it did not introduce.

        The naive join -- "the first snapshot that mentions this id" -- answers the copy
        time. #1801 measured both over every library on this disk and they differ on 11
        records, so the copy has to be named rather than silently dated.
        """
        self.add(candidate_id="d-origin", statement="第一条要被合并的记录。", session="sess-a",
                 sources=[{"id": "src-moved", "type": "unknown", "claim": "原始材料",
                           "independence_group": "sess-a", "verification": "unknown"}])
        self.add(candidate_id="d-target", statement="第二条记录，合并到这里。", session="sess-c",
                 sources=[{"id": "src-own", "type": "unknown", "claim": "自己的材料",
                           "independence_group": "sess-c", "verification": "unknown"}])
        moved = self._backdate_event("d-origin", "add", 3)

        self.store.merge("d-origin", "d-target", confirmed=True, reason="主持人判断等价")
        basis = self.store.source_basis("d-target")
        self.assertEqual(moved, basis["sources"]["src-moved"]["entered_at"],
                         "the record entered when its own card was written, not when it was copied")
        self.assertEqual("d-origin", basis["sources"]["src-moved"]["entered_on"],
                         "and the answer says which card it entered on")
        self.assertNotIn("entered_on", basis["sources"]["src-own"],
                         "a source that entered on this card needs no pointer back")

    def test_a_card_with_no_sources_gets_no_source_basis_key(self):
        """Absent fact, absent key -- the r115 rule, on the new surface."""
        self.add(candidate_id="d-bare", statement="没有任何来源的记录。")
        self.assertNotIn("source_basis", self.store.show("d-bare"))
        self.assertEqual({}, self.store.source_basis("d-bare"))

    def test_the_stored_source_records_keep_exactly_their_old_keys(self):
        """`candidate` is the stored state byte for byte; the times sit beside it."""
        cid = self._two_sources()
        shown = self.store.show(cid)
        for source in shown["candidate"]["sources"]:
            self.assertEqual({"id", "type", "claim", "independence_group", "verification", "scope_note"},
                             set(source))


    def test_the_entry_comes_from_the_event_not_a_snapshot_written_to_an_older_date(self):
        """The two rows are not interchangeable, so they must be separated by a fixture.

        `_insert_candidate` writes version 1's snapshot and its creating event with one
        timestamp, so a fixture made only by `add` cannot tell "read the event" apart
        from "read the first snapshot" or "read `versioned_at`". Both of those mutants
        survive such a fixture (measured: M3-naive-join and M4-card-date stayed green).

        On this disk they are not interchangeable at all. #1801 walked every library
        for the rule and ran the naive join beside it: 11 records disagree, e.g.
        `docs/evidence/2026-11-12-demo`'s `src-5cc6d4500a9e` reads 2026-11-12T01:10:17
        from the ledger and 2026-10-02T09:00:00 from the first snapshot, because a
        backfill tool wrote a snapshot dated weeks earlier than the event that created
        the card. So this fixture writes exactly that shape.
        """
        cid = self._two_sources()
        self._backdate_event(cid, "add", 2)  # keeps the two acquisitions apart as well
        add_at = self._ledger_at(cid, "add")
        # Only the snapshot is moved: the event keeps the moment the record really
        # entered. This is the backfilled shape, not a hypothetical.
        stale = (datetime.fromisoformat(add_at) - timedelta(days=40)).isoformat(timespec="seconds")
        self.store.connection.execute(
            "UPDATE snapshots SET created_at=? WHERE candidate_id=? AND version=1", (stale, cid))
        self.store.connection.commit()

        basis = self.store.source_basis(cid)
        self.assertEqual(add_at, basis["sources"]["src-first"]["entered_at"],
                         "the record entered when the event says, not when a row was dated")
        self.assertNotEqual(stale, basis["sources"]["src-first"]["entered_at"],
                            "the fixture must actually separate the two rows, or this proves nothing")
        self.assertEqual(stale, self.store.time_basis(cid)["versioned_at"],
                         "and the wording date really did move -- that is what M4 prints instead")


    def test_the_frozen_prompt_dates_each_source_it_asks_a_reader_to_weigh(self):
        """The exit a real downstream reads, not just the JSON surfaces.

        `export` mode C writes the prompt a participant is handed. Its header already
        dates the wording (r115/r1627), but the source lines carried every field except
        when the source arrived -- so the person asked to weigh the evidence could not
        say whether it predated the claim. Appended after `scope_note`, so the prefix
        bytes other readers match on are unchanged.
        """
        self.add(candidate_id="d-exp-src", statement="导出里的来源也应当带入库时刻。",
                 session="sess-a",
                 sources=[{"id": "src-e1", "type": "claimed_firsthand", "verification": "unverified",
                           "claim": "第一次交接里出过问题", "independence_group": "person-e1",
                           "scope_note": "两次都在同一团队"}])
        # A second source arrives later. Without it the card has one event, so
        # `versioned_at` and the source's entry are the same string and a surface
        # printing the card's date would pass -- measured: the E1 arm survived the
        # single-source fixture for exactly that reason.
        entered_e1 = self._backdate_event("d-exp-src", "add", 5)
        self.store.attach_source("d-exp-src", {
            "id": "src-e2", "type": "abstract_reasoning", "verification": "not_evidence",
            "claim": "后来补上的一条推演", "independence_group": "method-v1",
        }, session="sess-b")
        entered_e2 = self._backdate_event("d-exp-src", "attach_source", 2)
        # The wording has to move after the card was created, or `versioned_at` *is* the
        # creating event and the two facts coincide by construction. Measured: with no
        # revision, `versioned_at == entered_e1` and the E1 arm passed.
        self.store.revise("d-exp-src", "导出里的每个来源也应当带自己的入库时刻。", "补上更明确的说法",
                          session="sess-a")
        self.store.confirm("d-exp-src", "可讨论，不是真", session="sess-a")
        wording_at = self.store.time_basis("d-exp-src")["versioned_at"]
        self.assertIn("revise", [e["event"] for e in self.store.history("d-exp-src")["events"]],
                      "the fixture needs the revision to have happened")
        self.assertNotIn(wording_at, {entered_e1, entered_e2},
                         "the fixture must keep the wording's date apart from both entries, "
                         "or printing the card date would look correct")

        exported = self.store.export_prompt("c", ["d-exp-src"], 8000, self.root / "exports")
        text = Path(exported["path"]).read_text(encoding="utf-8")
        line = next(l for l in text.splitlines() if l.startswith("- src-e1"))
        self.assertIn(f"entered_at: {entered_e1}", line)
        self.assertTrue(line.index("scope_note") < line.index("entered_at"),
                        "the new field goes after the existing ones, not in the middle")
        self.assertTrue(line.startswith("- src-e1 | claimed_firsthand | verification=unverified "
                                         "| independence_group=person-e1 | 第一次交接里出过问题 "
                                         "| scope_note: 两次都在同一团队"),
                        "every byte before the appended field is unchanged")
        line2 = next(l for l in text.splitlines() if l.startswith("- src-e2"))
        self.assertIn(f"entered_at: {entered_e2}", line2,
                      "each source gets its own moment; one value for both means the card's date")

    def test_a_source_the_ledger_cannot_date_prints_no_entered_at_in_the_prompt(self):
        """Absent fact, absent field -- the same rule on the text surface.

        The fixture removes the card's creating event, which is the only row that could
        say when its sources arrived. The honest output is then no field at all: putting
        the card's own date (or `_now()`) there is exactly the substitution this field
        exists to prevent, and it would be invisible to a reader.
        """
        self.add(candidate_id="d-no-entry", statement="没有任何账本行说得出来源何时入库。",
                 session="sess-a",
                 sources=[{"id": "src-nx", "type": "unknown", "verification": "unknown",
                           "claim": "来历不明的一份材料", "independence_group": "person-nx"}])
        self.store.confirm("d-no-entry", "可讨论，不是真", session="sess-a")
        self.store.connection.execute(
            "DELETE FROM events WHERE candidate_id='d-no-entry' AND event='add'")
        self.store.connection.commit()

        basis = self.store.source_basis("d-no-entry")
        self.assertEqual(["src-nx"], basis["undetermined_source_ids"])
        self.assertNotIn("src-nx", basis.get("sources", {}),
                         "an undated source must not get a guessed row")

        exported = self.store.export_prompt("c", ["d-no-entry"], 8000, self.root / "exports")
        text = Path(exported["path"]).read_text(encoding="utf-8")
        line = next(l for l in text.splitlines() if l.startswith("- src-nx"))
        self.assertNotIn("entered_at", line)
        # The card's own date is still printed, so this is not "no time anywhere".
        header = next(l for l in text.splitlines() if l.startswith("[d-no-entry"))
        self.assertIn("versioned_at=", header)


if __name__ == "__main__":
    unittest.main()
