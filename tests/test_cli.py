import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

from dojo.inquiry import Inquiry

from dojo.storage import Store


ROOT = Path(__file__).resolve().parents[1]


class CliEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / "cli.sqlite3"
        self.exports = self.root / "exports"
        self.env = {**os.environ, "DOJO_DB": str(self.db), "DOJO_EXPORTS": str(self.exports),
                    "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}

    def tearDown(self):
        self.temp.cleanup()

    def run_cli(self, *args, success=True):
        result = subprocess.run(
            [sys.executable, "-m", "dojo", *args], cwd=ROOT, env=self.env,
            text=True, encoding="utf-8", capture_output=True, timeout=20,
        )
        if success:
            self.assertEqual(0, result.returncode, result.stderr)
            return json.loads(result.stdout)
        self.assertNotEqual(0, result.returncode)
        self.assertTrue(result.stderr.startswith(("error:", "usage:")), result.stderr)
        return result

    def run_text_cli(self, *args, input_text=None, env=None):
        return subprocess.run(
            [sys.executable, "-m", "dojo", *args], cwd=ROOT,
            env=self.env if env is None else env, text=True, encoding="utf-8", input=input_text,
            capture_output=True, timeout=30,
        )

    def read_story(self, *args, error=None):
        # Preserve the signed probes' before/after check for DB and sidecars.
        def snapshot():
            return {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()}

        before = snapshot()
        result = self.run_text_cli("--db", str(self.db), "stories", *args)
        self.assertEqual(before, snapshot())
        if error is not None:
            self.assertEqual((2, "", error),
                             (result.returncode, result.stdout, result.stderr.strip()))
            return
        self.assertEqual((0, ""), (result.returncode, result.stderr))
        return json.loads(result.stdout)

    def test_story_report_reads_visible_replacement_outside_context_window(self):
        model = SimpleNamespace(config=SimpleNamespace(model="offline-fixture"))
        with closing(Inquiry(self.db, model)) as q:
            story = q.story
            old = q.record("user", {"text": "原值 UTC+8"})
            text = "更正：原值应为 UTC+09:00；未附台账。"
            new = q.record("user", {"text": text})
            for n in range(11):
                q.record("user", {"text": f"补记 {n}"})
            dependent = q.record("user", {"text": "引用原值形成的说明"})
            q.dependencies.link(dependent, [old])
            q.dependencies.revise(old, new, "收到原记录的修订")

        context = self.read_story(story, "--context")
        sources = {s["event"]: s for s in context["sources"]}
        status = sources[old]["dependency_status"]
        self.assertEqual(("superseded", new), (status["state"], status["replacement"]))
        self.assertNotIn(new, sources)
        self.assertNotIn(text, json.dumps(context, ensure_ascii=False))
        report = self.read_story(story, "--report", str(status["replacement"]))
        self.assertEqual(text, report["text"])
        self.assertEqual("user_report_not_independently_verified", report["epistemic_status"])
        expected = {"state": "needs_review", "causes": [old]}
        self.assertEqual(expected, sources[dependent]["dependency_status"])
        self.assertEqual(expected, self.read_story(story, "--report", str(dependent))["dependency_status"])

    def test_story_report_follows_successive_corrections_outside_context_window(self):
        model = SimpleNamespace(config=SimpleNamespace(model="offline-fixture"))
        original = "交接便条：东门周一 06:10 开门。"
        first_correction = "更正：转述说是 06:40，应查值班表。"
        latest_correction = "再更正：值班表只写计划；实际开门据口头转述是 07:10，尚待查周一东门门禁日志。"
        with closing(Inquiry(self.db, model)) as q:
            story = q.story
            old = q.record("user", {"text": original})
            middle = q.record("user", {"text": first_correction})
            latest = q.record("user", {"text": latest_correction})
            q.dependencies.revise(old, middle, "第一次更正")
            q.dependencies.revise(middle, latest, "第二次更正")
            for n in range(12):
                q.record("user", {"text": f"无关补记 {n}"})

        context = self.read_story(story, "--context")
        sources = {s["event"]: s for s in context["sources"]}
        self.assertEqual(original, sources[old]["text"])
        self.assertNotIn(middle, sources)
        self.assertNotIn(latest, sources)
        self.assertIn("--report EVENT", context["report_lookup"])

        source = sources[old]
        for event, text in ((middle, first_correction), (latest, latest_correction)):
            status = source["dependency_status"]
            self.assertEqual(("superseded", event), (status["state"], status["replacement"]))
            source = self.read_story(story, "--report", str(status["replacement"]))
            self.assertEqual((event, text), (source["event"], source["text"]))
            self.assertEqual("user_report_not_independently_verified", source["epistemic_status"])
        self.assertEqual({"state": "current_interpretation", "truth": "not_certified"},
                         source["dependency_status"])

    def test_story_context_hides_unreadable_report_replacements(self):
        model = SimpleNamespace(config=SimpleNamespace(model="offline-fixture"))
        for cross_story in (True, False):
            with self.subTest(cross_story=cross_story):
                secret = "另一故事的报告。"
                reason = "不可读替代的修订理由。"
                with closing(Inquiry(self.db, model)) as q:
                    story = q.story
                    old = q.record("user", {"text": "值班记录：东门在 06:10 开门。"})
                    if not cross_story:
                        replacement = q.record("reflection", {"reflection": {"answer": "内部解释", "action": None}})
                        q.dependencies.revise(old, replacement, reason)
                if cross_story:
                    with closing(Inquiry(self.db, model)) as q:
                        replacement = q.record("user", {"text": secret})
                        q.dependencies.revise(old, replacement, reason)

                context = self.read_story(story, "--context")
                old_source = next(s for s in context["sources"] if s["event"] == old)
                self.assertEqual({"state": "superseded"}, old_source["dependency_status"])
                self.assertIn("--report EVENT", context["report_lookup"])
                output = json.dumps(context, ensure_ascii=False)
                self.assertNotIn(reason, output)
                if cross_story:
                    self.assertNotIn(secret, output)
                self.read_story(story, "--report", str(replacement), error="error: 没有可见的用户报告")

    def test_story_context_separates_revised_explanation_from_missing_evidence(self):
        original = "周一东门值班表写 06:10；我没有看到门禁日志。"
        old_answer = "实际开门就是 06:10。"
        new_answer = "值班表只写计划，不能证明实际开门。请查周一东门门禁日志。"
        clarification = "我拿到的只有计划表，不是门禁日志；实际开门时间未知。"

        class OfflineClient:
            config = SimpleNamespace(model="offline-fixture")
            answers = iter((old_answer, new_answer))

            def complete(self, messages):
                return dict(answer=next(self.answers), understanding="核对实际开门时间",
                            hypotheses=[], unknowns=["未见门禁日志"], revision="区分计划与实测",
                            action=None)

        with closing(Inquiry(self.db, OfflineClient())) as q:
            story = q.story
            self.assertEqual(old_answer, q.turn(original))
            old = q.last_reflection
            before = self.read_story(story, "--context")
            self.assertEqual(new_answer, q.turn(clarification))
            replacement = q.last_reflection
            status = q.dependencies.status(old)
            self.assertEqual(("superseded", replacement), (status["state"], status["replacement"]))

        self.assertFalse(before["synthetic"])
        self.assertIn(old, {source["event"] for source in before["sources"]})
        context = self.read_story(story, "--context")
        sources = {source["event"]: source for source in context["sources"]}
        self.assertNotIn(old, sources)
        self.assertNotIn(old_answer, json.dumps(context, ensure_ascii=False))
        self.assertIn(new_answer, sources[replacement]["text"])
        self.assertEqual("reflection", sources[replacement]["kind"])
        self.assertIn("模型答复和审查意见不证明事实", context["reading"])
        self.assertFalse(any(source["kind"] == "tool_result" for source in sources.values()))
        self.read_story(story, "--report", str(replacement), error="error: 没有可见的用户报告")
        reports = {source["text"]: event for event, source in sources.items() if source["kind"] == "user"}
        self.assertEqual({original, clarification}, set(reports))
        for text in reports:
            report = self.read_story(story, "--report", str(reports[text]))
            self.assertEqual(text, report["text"])
            self.assertEqual("user_report_not_independently_verified", report["epistemic_status"])

    def test_demo_auto_persists_summary_and_refuses_workdir_overwrite(self):
        workdir = self.root / "demo-work"
        result = self.run_text_cli("demo", "--auto", "--workdir", str(workdir), input_text=None)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("离线预设故事", result.stdout)
        self.assertIn("真实词汇检索", result.stdout)
        self.assertIn("seed-m01", result.stdout)
        self.assertIn("seed-m02", result.stdout)
        self.assertIn("seed-m03", result.stdout)
        self.assertIn("claimed_firsthand/unverified", result.stdout)
        self.assertIn("版本轨迹", result.stdout)
        self.assertIn("学到：", result.stdout)
        self.assertTrue((workdir / "summary.md").is_file())
        summary_text = (workdir / "summary.md").read_text(encoding="utf-8")
        self.assertNotIn("甲（空间整洁）", summary_text)
        self.assertNotIn("丙（抽象挑战）", summary_text)
        # Windows mode bits do not represent discretionary ACL permissions.
        if os.name == "posix":
            self.assertFalse((workdir / "summary.md").stat().st_mode & 0o077)
            self.assertFalse((workdir / "dojo.sqlite3").stat().st_mode & 0o077)
        with closing(sqlite3.connect(workdir / "dojo.sqlite3")) as connection:
            rows = connection.execute("SELECT id,version,state_json FROM candidates ORDER BY id").fetchall()
        self.assertEqual(7, len(rows))
        states = {row[0]: json.loads(row[2]) for row in rows}
        abstract = next(
            state for state in states.values()
            if state["kind"] == "abstract_idea" and "要让一种想要的行为持续发生" in state["statement"]
        )
        application = next(state for state in states.values() if state["kind"] == "application")
        self.assertEqual(5, abstract["version"])
        self.assertEqual("discussable", abstract["status"])
        self.assertIn("能力的练习", abstract["statement"])
        self.assertNotIn("需求", abstract["statement"])
        self.assertNotIn("返工", abstract["statement"])
        self.assertEqual("synthetic_roleplay", abstract["sources"][0]["type"])
        self.assertEqual("not_evidence", abstract["sources"][0]["verification"])
        self.assertEqual("application", application["kind"])
        self.assertEqual("instantiates", application["relations"][0]["type"])
        self.assertEqual(abstract["id"], application["relations"][0]["target"])
        with closing(sqlite3.connect(workdir / "dojo.sqlite3")) as connection:
            history = connection.execute(
                "SELECT state_json FROM snapshots WHERE candidate_id=? ORDER BY version", (abstract["id"],)
            ).fetchall()
        versions = [json.loads(item[0]) for item in history]
        self.assertEqual([1, 2, 3, 4, 5], [item["version"] for item in versions])
        self.assertEqual("challenged", versions[2]["status"])
        self.assertIn("有意义的训练难度", versions[2]["contradictions"][0])
        self.assertEqual(versions[0]["kind"], versions[4]["kind"])
        self.assertEqual(versions[0]["sources"], versions[4]["sources"])
        self.assertIn("保留", versions[4]["statement"])
        self.assertNotIn("需求", versions[4]["statement"])
        self.assertNotIn("返工", json.dumps(versions, ensure_ascii=False))
        before = (workdir / "dojo.sqlite3").read_bytes()
        again = self.run_text_cli("demo", "--auto", "--workdir", str(workdir), input_text=None)
        self.assertNotEqual(0, again.returncode)
        self.assertIn("refusing to overwrite", again.stderr)
        self.assertEqual(before, (workdir / "dojo.sqlite3").read_bytes())

    def test_demo_interactive_reject_edit_custom_input_and_eof(self):
        # EOF at the first prompt is cancellation, not an implicit user choice.
        eof_dir = self.root / "demo-eof"
        eof = self.run_text_cli("demo", "--workdir", str(eof_dir), input_text="")
        self.assertEqual(0, eof.returncode, eof.stderr)
        self.assertIn("没有将沉默或 EOF 当作同意", eof.stdout)
        with closing(sqlite3.connect(eof_dir / "dojo.sqlite3")) as connection:
            self.assertEqual(0, connection.execute("SELECT count(*) FROM candidates").fetchone()[0])

        custom_dir = self.root / "demo-custom"
        custom_text = "我自己的真实项目想法不应被模拟脚本理解"
        custom = self.run_text_cli("demo", "--workdir", str(custom_dir), input_text=f"\n{custom_text}\nq\n")
        self.assertEqual(0, custom.returncode, custom.stderr)
        self.assertIn("不会假装已理解", custom.stdout)
        self.assertNotIn(custom_text, (custom_dir / "summary.md").read_text(encoding="utf-8"))
        with closing(sqlite3.connect(custom_dir / "dojo.sqlite3")) as connection:
            self.assertEqual(0, connection.execute("SELECT count(*) FROM candidates").fetchone()[0])

        # start, skip custom text, reject 甲's card, reject 丙's card, decline the revision.
        reject_dir = self.root / "demo-rejected"
        rejected = self.run_text_cli("demo", "--workdir", str(reject_dir), input_text="\n\nn\nn\nn\n")
        self.assertEqual(0, rejected.returncode, rejected.stderr)
        self.assertIn("贡献者拒绝了这张候选", rejected.stdout)
        self.assertIn("已保存挑战", rejected.stdout)
        self.assertIn("修订未被接受", rejected.stdout)
        with closing(sqlite3.connect(reject_dir / "dojo.sqlite3")) as connection:
            self.assertEqual(4, connection.execute("SELECT count(*) FROM candidates").fetchone()[0])
            versions = connection.execute(
                "SELECT state_json FROM snapshots WHERE candidate_id='seed-m01' ORDER BY version"
            ).fetchall()
        self.assertEqual(2, len(versions))
        self.assertEqual("challenged", json.loads(versions[-1][0])["status"])

        # start, skip custom text, edit 甲's card, skip 乙's card, save 丙's card, accept revision.
        edit_dir = self.root / "demo-edited"
        edited = self.run_text_cli(
            "demo", "--workdir", str(edit_dir),
            input_text="\n\ne\n贡献者编辑后的初始观点\ny\ny\nn\ny\ny\ny\n",
        )
        self.assertEqual(0, edited.returncode, edited.stderr)
        self.assertIn("预设不会解释你自编辑的抽象卡", edited.stdout)
        with closing(sqlite3.connect(edit_dir / "dojo.sqlite3")) as connection:
            non_seed = connection.execute("SELECT id,state_json FROM candidates WHERE id NOT LIKE 'seed-%'").fetchall()
            self.assertEqual(2, len(non_seed))
            editor_id = next(
                row[0] for row in non_seed
                if "贡献者编辑后的初始观点" in json.loads(row[1])["statement"]
            )
            edit_versions = connection.execute(
                "SELECT state_json FROM snapshots WHERE candidate_id=? ORDER BY version", (editor_id,)
            ).fetchall()
            abstract_versions = connection.execute(
                "SELECT state_json FROM snapshots WHERE candidate_id='seed-m01' ORDER BY version"
            ).fetchall()
        edited_states = [json.loads(item[0]) for item in edit_versions]
        self.assertEqual(2, len(edited_states))
        self.assertEqual("贡献者编辑后的初始观点", edited_states[0]["statement"])
        self.assertEqual("abstract_idea", edited_states[0]["kind"])
        self.assertEqual("unknown", edited_states[0]["sources"][0]["type"])
        self.assertEqual("unknown", edited_states[0]["sources"][0]["verification"])
        self.assertEqual("discussable", edited_states[1]["status"])
        abstract_states = [json.loads(item[0]) for item in abstract_versions]
        self.assertEqual(4, len(abstract_states))
        self.assertEqual("challenged", abstract_states[1]["status"])
        self.assertEqual("abstract_idea", abstract_states[2]["kind"])
        self.assertIn("保留", abstract_states[2]["statement"])
        self.assertIn("v1:discussable, v2:challenged, v3:draft, v4:discussable", edited.stdout)

    def test_default_auto_demo_is_noninteractive_and_cleans_temp_database(self):
        temp_root = self.root / "isolated-temp"
        temp_root.mkdir(mode=0o700)
        env = {**self.env, "TMPDIR": str(temp_root)}
        result = self.run_text_cli("demo", "--auto", env=env)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("学到：", result.stdout)
        self.assertLessEqual(len(result.stdout.splitlines()), 120)
        self.assertIn("seed-m02", result.stdout)
        self.assertIn("seed-m03", result.stdout)
        self.assertIn("unverified", result.stdout)
        self.assertIn("未知：", result.stdout)
        self.assertEqual([], list(temp_root.iterdir()))

        detailed = self.run_text_cli("demo", "--auto", "--details", env=env)
        self.assertEqual(0, detailed.returncode, detailed.stderr)
        self.assertGreater(len(detailed.stdout.splitlines()), len(result.stdout.splitlines()))
        self.assertIn("前提：", detailed.stdout)
        self.assertIn("来源：", detailed.stdout)
        self.assertEqual([], list(temp_root.iterdir()))

    def test_discuss_without_endpoint_fails_in_chinese_before_creating_database(self):
        env = {key: value for key, value in self.env.items() if key not in {"DOJO_LLM_BASE_URL", "DOJO_LLM_MODEL", "DOJO_LLM_API_KEY"}}
        result = subprocess.run(
            [sys.executable, "-m", "dojo", "--db", str(self.root / "discuss.sqlite3"), "discuss"],
            cwd=ROOT, env=env, text=True, input="", capture_output=True, timeout=10,
        )
        self.assertEqual(2, result.returncode)
        self.assertIn("未配置 DOJO_LLM_BASE_URL", result.stderr)
        self.assertIn("未发送网络请求", result.stderr)
        self.assertFalse((self.root / "discuss.sqlite3").exists())

    def test_discuss_no_trace_flag_is_accepted_without_creating_a_trace(self):
        env = {key: value for key, value in self.env.items() if key not in {"DOJO_LLM_BASE_URL", "DOJO_LLM_MODEL", "DOJO_LLM_API_KEY"}}
        db_path = self.root / "no-trace.sqlite3"
        result = subprocess.run(
            [sys.executable, "-m", "dojo", "--db", str(db_path), "discuss", "--no-trace"],
            cwd=ROOT, env=env, text=True, input="", capture_output=True, timeout=10,
        )
        self.assertEqual(2, result.returncode)
        self.assertIn("未配置 DOJO_LLM_BASE_URL", result.stderr)
        self.assertFalse(db_path.exists())
        self.assertFalse((self.root / "sessions").exists())

    def test_discuss_resume_invalid_trace_fails_in_chinese_without_creating_files(self):
        path = self.root / ("discuss-" + "0" * 32 + ".jsonl")
        for create_invalid in (False, True):
            if create_invalid:
                path.write_text("not json\n", encoding="utf-8")
            db_path = self.root / f"resume-{create_invalid}.sqlite3"
            result = self.run_text_cli("--db", str(db_path), "discuss", "--resume", str(path))
            self.assertEqual(2, result.returncode)
            self.assertIn("无法续跑轨迹", result.stderr)
            self.assertFalse(db_path.exists())
            if not create_invalid:
                self.assertFalse(path.exists())

        conflict = self.run_text_cli(
            "--db", str(self.root / "conflict.sqlite3"), "discuss",
            "--resume", str(path), "--no-trace",
        )
        self.assertEqual(2, conflict.returncode)
        self.assertIn("不能同时使用", conflict.stderr)
        self.assertFalse((self.root / "conflict.sqlite3").exists())

    def test_live_command_without_endpoint_fails_before_creating_default_database(self):
        env = {key: value for key, value in self.env.items() if key not in {"DOJO_LLM_BASE_URL", "DOJO_LLM_MODEL", "DOJO_LLM_API_KEY"}}
        db_path = self.root / "must-not-be-created.sqlite3"
        result = subprocess.run(
            [sys.executable, "-m", "dojo", "--db", str(db_path), "chat"], cwd=ROOT,
            env=env, text=True, input="", capture_output=True, timeout=10,
        )
        self.assertEqual(2, result.returncode)
        self.assertIn("no network request was made", result.stderr)
        self.assertFalse(db_path.exists())

    def test_show_reads_explicit_cross_session_link_at_its_recorded_versions(self):
        def add(identifier, kind, statement, scope):
            return self.run_cli(
                "add", "--id", identifier, "--kind", kind, "--statement", statement,
                "--scope", scope, "--session", "session-" + identifier,
                "--source-json", json.dumps({
                    "id": "src-" + identifier, "type": "synthetic_roleplay",
                    "verification": "unverified", "independence_group": "group-" + identifier,
                    "claim": statement,
                }),
            )

        original = "光面硬纸板斜坡上，木珠滚过了标线。"
        exception = "粗布斜坡上，同尺寸木珠停在标线前。"
        add("ramp-a", "experience_claim", original, "只试了光面硬纸板")
        self.run_cli("confirm", "ramp-a", "--basis", "保留供讨论，不确认真实性")
        second = add("ramp-b", "counterexample", exception, "只试了粗布")
        before = self.run_cli("show", "ramp-a", "--history")
        self.assertNotIn("incoming_links", before)
        reason = "只收窄适用范围，不把两场并为同一观察"
        linked = self.run_cli("link", "ramp-b", "--relation", "narrows",
                              "--target", "ramp-a", "--reason", reason)
        self.assertEqual(second["status"], linked["status"])
        self.assertEqual(second["sources"], linked["sources"])

        self.db.chmod(0o444)
        db_bytes = self.db.read_bytes()
        after = self.run_cli("show", "ramp-a", "--history")
        self.assertEqual(db_bytes, self.db.read_bytes())
        self.assertEqual(0o444, self.db.stat().st_mode & 0o777)
        self.db.chmod(0o600)
        for key in before:
            self.assertEqual(before[key], after[key], key)
        self.assertIn("不计入本卡的来源", after["incoming_links_reading"])
        link, = after["incoming_links"]
        self.assertEqual(("narrows", reason), (link["relation"], link["reason"]))
        source_events = self.run_cli("show", "ramp-b", "--history")["history"]["events"]
        event = source_events[-1]
        self.assertEqual(("link", link["sequence"], link["recorded_at"]),
                         (event["event"], event["sequence"], event["created_at"]))
        for key, state in (("source", linked), ("target", before["candidate"])):
            for field in ("id", "version", "statement", "scope", "sessions", "sources"):
                self.assertEqual(state[field], link[key][field], (key, field))

        self.run_cli("revise", "ramp-a", "--statement", original + "只测了一次。", "--reason", "补边界")
        self.run_cli("revise", "ramp-b", "--statement", exception + "只试了粗布。", "--reason", "补边界")
        revised = self.run_cli("show", "ramp-a")
        self.assertGreater(revised["candidate"]["version"], link["target"]["version"])
        self.assertEqual([link], revised["incoming_links"])

        add("ramp-survivor", "experience_claim", original + "仅有一次记录。", "只试了光面硬纸板")
        self.run_cli("merge", "ramp-a", "ramp-survivor", "--confirm", "--reason", "确认是同一条观察的等价措辞")
        redirected = self.run_cli("show", "ramp-a")
        self.assertEqual([link], redirected["incoming_links"])
        self.assertIn("show ramp-survivor", redirected["redirect_links_reading"])
        self.assertNotIn("incoming_links", self.run_cli("show", "ramp-survivor"))

    def test_show_groups_registered_links_and_distinguishes_adoption(self):
        def add(card, group=None):
            source = {"id": "src-" + card, "type": "synthetic_roleplay", "claim": card}
            if group:
                source["independence_group"] = group
            self.run_cli("add", "--id", card, "--kind", "experience_claim", "--statement", card,
                         "--source-json", json.dumps(source))

        def link(card, relation):
            self.run_cli("link", card, "--relation", relation, "--target", "claim", "--reason", relation)
            return self.run_cli("show", "claim")["incoming_links"][-1]["sequence"]

        add("claim", "own-group")
        add("note", "notebook")
        old = link("note", "supports")
        now = self.run_cli("revise", "claim", "--statement", "限于一次记录", "--reason", "补范围")
        self.run_cli("revise", "note", "--statement", "只记了桌面的情况", "--reason", "补范围")
        selected = link("note", "narrows")
        # The original `note` snapshot is retained when a new group is later attached.
        self.run_cli("attach-source", "note", "--source-json", json.dumps({
            "id": "src-later", "type": "synthetic_roleplay", "claim": "复查", "independence_group": "later",
        }))
        add("unsigned")
        objection = link("unsigned", "challenges")
        unchanged = self.db.read_bytes()
        shown = self.run_cli("show", "claim", "--history")
        self.assertEqual(now, shown["candidate"])
        self.assertEqual(unchanged, self.db.read_bytes())
        self.assertEqual({
            "declared_group_count": 1,
            "by_target_version": [
                {"target_version": 1, "is_current": False,
                 "declared_groups": [{"group": "notebook", "link_sequences": [old]}],
                 "unknown_group_link_sequences": [], "relations": {"supports": [old]}},
                {"target_version": 2, "is_current": True,
                 "declared_groups": [{"group": "notebook", "link_sequences": [selected]}],
                 "unknown_group_link_sequences": [objection],
                 "relations": {"narrows": [selected], "challenges": [objection]}},
            ],
        }, shown["incoming_link_summary"])
        self.assertTrue(all("adopted_by" not in link for link in shown["incoming_links"]))
        for flags, statement in [([old], "新措辞"), ([selected], now["statement"]),
                                 ([selected, objection], "新措辞"), ([10**30], "新措辞")]:
            with self.subTest(flags=flags, statement=statement):
                result = self.run_cli("revise", "claim", "--statement", statement, "--reason", "不应写入",
                                      *(s for seq in flags for s in ("--adopt-link", str(seq))), success=False)
                self.assertEqual(2, result.returncode)
                self.assertEqual(unchanged, self.db.read_bytes())
        with closing(sqlite3.connect(self.db)) as conn, conn:
            raw, = conn.execute("SELECT details_json FROM events WHERE seq=?", (objection,)).fetchone()
            details = json.loads(raw)
            del details["target_version"]
            conn.execute("UPDATE events SET details_json=? WHERE seq=?", (json.dumps(details), objection))
        no_version = self.run_cli("show", "claim")["incoming_link_summary"]["by_target_version"][-1]
        self.assertEqual((None, False, [objection]), (no_version["target_version"],
                         no_version["is_current"], no_version["unknown_group_link_sequences"]))
        unchanged = self.db.read_bytes()
        self.run_cli("revise", "claim", "--statement", "不猜版本", "--reason", "拒绝",
                     "--adopt-link", str(objection), success=False)
        self.assertEqual(unchanged, self.db.read_bytes())
        revised = self.run_cli("revise", "claim", "--statement", "桌面上的一次记录", "--reason", "纳入桌面条件",
                               "--adopt-link", str(selected))
        self.assertEqual((3, "draft", now["sources"], now["relations"]),
                         (revised["version"], revised["status"], revised["sources"], revised["relations"]))
        read = self.run_cli("show", "claim", "--history")
        changed = read["history"]["events"][-1]
        self.assertEqual(("revise", selected), (changed["event"], changed["details"]["adopt_link_sequence"]))
        adopted, = [edge for edge in read["incoming_links"] if "adopted_by" in edge]
        self.assertEqual(selected, adopted["sequence"])
        expected_adoption = {"sequence": changed["sequence"], "version": 3, "reason": "纳入桌面条件"}
        self.assertEqual({**expected_adoption, "is_current": True}, adopted["adopted_by"])
        self.run_cli("revise", "claim", "--statement", "普通的新修订", "--reason", "不再采纳任何关联")
        final = self.run_cli("show", "claim")
        adopted, = [edge for edge in final["incoming_links"] if "adopted_by" in edge]
        self.assertEqual({**expected_adoption, "is_current": False}, adopted["adopted_by"])

    def test_real_cli_seed_add_confirm_search_revoke_merge_restore_and_export(self):
        seeded = self.run_cli("seed")
        self.assertTrue(seeded["loaded"])
        self.assertEqual(4, len(self.run_cli("list")))
        candidate = self.run_cli(
            "add", "--id", "d-cli", "--kind", "abstract_idea",
            "--statement", "减少无谓摩擦能让重复行为更容易持续", "--scope", "日常整理",
        )
        self.assertEqual(1, candidate["version"])
        self.run_cli("confirm", "d-cli", "--basis", "表述可检索", "--session", "anon-a")
        found = self.run_cli("search", "无谓摩擦")
        self.assertEqual("d-cli", found["results"][0]["id"])
        shown = self.run_cli("show", "d-cli", "--history")
        self.assertEqual([1, 2], [item["version"] for item in shown["history"]["versions"]])
        self.run_cli("revoke", "d-cli", "--reason", "撤销可检索状态")
        self.assertNotIn("d-cli", [item["id"] for item in self.run_cli("search", "摩擦")["results"]])

        self.run_cli("add", "--id", "d-equivalent", "--kind", "abstract_idea", "--statement", "减少无谓摩擦能让重复行为更容易持续")
        self.run_cli("merge", "d-equivalent", "d-cli", "--confirm", "--reason", "主持人确认措辞与范围等价")
        self.assertEqual("d-cli", self.run_cli("show", "d-equivalent")["resolved_id"])
        self.run_cli("unmerge", "d-equivalent", "--reason", "演示恢复")
        self.assertEqual("d-equivalent", self.run_cli("show", "d-equivalent")["resolved_id"])
        self.run_cli("abstain", "--id", "d-cli", "--reason", "适用性未知", "--next-question", "确认哪些行为值得降低摩擦")
        events = self.run_cli("events", "--id", "d-cli")
        self.assertIn("abstain", [item["event"] for item in events])

        export = self.run_cli("export", "--mode", "b", "--budget-chars", "4000")
        prompt = Path(export["path"]).read_text(encoding="utf-8")
        self.assertIn("Target case:", prompt)
        self.assertEqual("B", export["mode"])
        denied = self.run_cli("merge", "d-equivalent", "d-cli", "--reason", "missing flag", success=False)
        self.assertNotEqual(0, denied.returncode)
        if os.name == "posix":
            self.assertFalse(Path(self.db).stat().st_mode & 0o077)

    def test_reads_command_tells_a_read_before_acceptance_from_one_after(self):
        """#1537 wrote the read log; only a probe could read it back. This is the exit.

        A conclusion that holds only inside the repository's own script is not a
        conclusion the second person can use. The two rows below are the same card,
        the same reader and the same surface: the single difference is whether the
        wording had been accepted at the moment it left the library, and the command
        prints that as a field rather than leaving it to a timestamp comparison.
        """
        from dojo.storage import Store
        self.run_cli(
            "add", "--id", "d-reads", "--kind", "experience_claim",
            "--statement", "先把需求写清楚再动手", "--session", "sess-writer",
            "--source-json", json.dumps({
                "id": "src-reads", "type": "claimed_firsthand", "verification": "unknown",
                "claim": "用户本人陈述", "independence_group": "grp-user",
            }),
        )
        self.run_cli("confirm", "d-reads", "--basis", "值得继续讨论", "--session", "sess-facilitator")
        self.run_cli("search", "需求", "--session", "sess-reader")
        store = Store(self.db)
        try:
            store.record_acceptance("d-reads", "sess-reader", path="discuss_conclusion")
        finally:
            store.close()
        self.run_cli("search", "需求", "--session", "sess-reader")
        screen = self.run_cli("reads", "--id", "d-reads")
        self.assertTrue(screen["holds_table"], "the log exists because two reads were made")
        self.assertEqual(
            ["no_acceptance_at_read_time", "accepted_before_this_read"],
            [row["accepted_when_read"] for row in screen["rows"]],
            "same card, same reader, same surface: only the acceptance state differs",
        )
        self.assertEqual({"sess-reader"}, {row["reader_session"] for row in screen["rows"]})
        self.assertEqual({"search"}, {row["surface"] for row in screen["rows"]})
        first, second = screen["rows"]
        self.assertIsNone(first["accepted_at_at_read"],
                          "the first read happened before the card held any acceptance")
        self.assertIsNotNone(second["accepted_at_at_read"],
                             "the second read happened after it, and carries that moment")
        # Clock-independent facts about the two rows. The string comparison this test
        # used to make is in `test_the_naive_clock_comparison_would_invert_these_reads`,
        # where it is set up by a fixture instead of by hoping two CLI calls land inside
        # one second.
        self.assertGreaterEqual(second["at"], first["at"],
                                "the read log's sequence and its clock must agree")
        self.assertGreaterEqual(second["accepted_at_at_read"], first["at"][:19],
                                "the acceptance cannot precede the read that came before it")

    def test_the_naive_clock_comparison_would_invert_these_reads(self):
        """#1534's trap, set up by a fixture so it is asserted every run.

        A read taken before the card held any acceptance records
        `accepted_at_at_read = NULL`, and its `at` carries microseconds. Any derivation
        that compares clock strings -- `at > (accepted or '')` -- finds the microsecond
        string greater than the empty string and reports "accepted before this read",
        which is the opposite of what happened. The command must report the state
        recorded at read time.
        """
        self.run_cli(
            "add", "--id", "d-trap", "--kind", "experience_claim",
            "--statement", "先把需求写清楚再动手", "--session", "sess-writer",
            "--source-json", json.dumps({
                "id": "src-trap", "type": "claimed_firsthand", "verification": "unknown",
                "claim": "用户本人陈述", "independence_group": "grp-user",
            }),
        )
        self.run_cli("confirm", "d-trap", "--basis", "值得继续讨论", "--session", "sess-facilitator")
        self.run_cli("search", "需求", "--session", "sess-reader")
        con = sqlite3.connect(self.db)
        try:
            # Exactly what the real write point stores for a read that precedes any
            # acceptance: NULL recorded state, microsecond `at`.
            con.execute("UPDATE reads SET accepted_at_at_read=NULL, at=? "
                        "WHERE candidate_id='d-trap'", ("2999-12-31T23:59:30.999999+00:00",))
            con.commit()
        finally:
            con.close()
        row = self.run_cli("reads", "--id", "d-trap")["rows"][0]
        self.assertIsNone(row["accepted_at_at_read"],
                          "fixture premise: nothing was accepted when this read happened")
        self.assertGreater(row["at"], row["accepted_at_at_read"] or "",
                           "fixture premise: the naive string comparison would say "
                           "'accepted before', which is the inversion #1534 recorded")
        self.assertEqual(row["accepted_when_read"], "no_acceptance_at_read_time",
                         "the field follows the recorded state, not the clock strings")
    def test_reads_reader_filter_answers_without_knowing_a_sequence(self):
        """#1551: two sessions were handed the same card, so the second person needs a line
        that is his. `--reader` narrows to him and states the verdict; `sequence` is the one
        thing he does not have.
        """
        self.run_cli(
            "add", "--id", "d-two-readers", "--kind", "experience_claim",
            "--statement", "先把需求写清楚再动手", "--session", "sess-writer",
            "--source-json", json.dumps({
                "id": "src-two", "type": "claimed_firsthand", "verification": "unknown",
                "claim": "用户本人陈述", "independence_group": "grp-user",
            }),
        )
        self.run_cli("confirm", "d-two-readers", "--basis", "值得继续讨论",
                     "--session", "sess-facilitator")
        self.run_cli("search", "需求", "--session", "sess-early")
        from dojo.storage import Store
        store = Store(self.db)
        try:
            store.record_acceptance("d-two-readers", "sess-writer", path="discuss_conclusion")
        finally:
            store.close()
        self.run_cli("search", "需求", "--session", "sess-late")

        early = self.run_cli("reads", "--id", "d-two-readers", "--reader", "sess-early")
        late = self.run_cli("reads", "--id", "d-two-readers", "--reader", "sess-late")
        self.assertEqual("sess-early", early["reader"])
        self.assertEqual(1, len(early["rows"]), "only the early reader's own row comes back")
        self.assertEqual(1, len(late["rows"]))
        self.assertEqual("no_acceptance_at_read_time", early["rows"][0]["accepted_when_read"])
        self.assertEqual("accepted_before_this_read", late["rows"][0]["accepted_when_read"])
        self.assertIn("接受之前", early["verdict"])
        self.assertIn("接受之后", late["verdict"])
        # And the whole log still shows both, so the filter narrows and does not rewrite.
        everything = self.run_cli("reads", "--id", "d-two-readers")
        self.assertEqual(2, len(everything["rows"]))
        self.assertNotIn("reader", everything)

    def test_reads_reader_filter_keeps_the_two_silences_apart(self):
        """The new flag must not turn "never logged" into "logged and empty".

        A reader asking about himself on a library that never recorded a read is exactly
        the case where an empty list would be the stronger, false claim: `holds_table`
        has to stay false and the stderr sentence has to say so.
        """
        from dojo.storage import Store
        never = self.run_text_cli("reads", "--reader", "sess-nobody")
        self.assertEqual(0, never.returncode, never.stderr)
        self.assertEqual({"holds_table": False, "rows": []}, json.loads(never.stdout))
        self.assertIn("从来没有记过读取", never.stderr)

        blank_db = self.root / "blank-reader.sqlite3"
        env = {**self.env, "DOJO_DB": str(blank_db)}
        store = Store(blank_db)
        try:
            store.add("另一张从没有人读过它的卡。", "abstract_idea",
                      candidate_id="d-blank-reader", session="sess-writer")
            store.ensure_reads_table()
        finally:
            store.close()
        empty = self.run_text_cli("reads", "--reader", "sess-nobody", env=env)
        self.assertEqual(0, empty.returncode, empty.stderr)
        payload = json.loads(empty.stdout)
        self.assertTrue(payload["holds_table"])
        self.assertEqual([], payload["rows"])
        self.assertEqual("sess-nobody", payload["reader"],
                         "the filter is echoed, so a reader knows whose answer this is")
        self.assertIn("没有被交付过", payload["verdict"])
        self.assertNotEqual(json.loads(never.stdout), payload,
                            "never-logged and logged-but-empty are not one state")

    def test_reads_command_keeps_never_recorded_apart_from_recorded_and_empty(self):
        """Two silences, two sentences. An empty list is the stronger, false claim.

        A library that never had a `reads` table has never recorded a read; a library
        whose table exists but holds nothing has. Both print the same JSON contract
        shape, so the difference must survive to the screen -- `holds_table` plus one
        stderr line -- or a person cannot tell "nobody read this" from "nobody logged".
        """
        from dojo.storage import Store
        self.run_cli("add", "--id", "d-quiet", "--kind", "abstract_idea",
                     "--statement", "一张从没有人读过它的卡。", "--session", "sess-writer")
        never = self.run_text_cli("reads")
        self.assertEqual(0, never.returncode, never.stderr)
        self.assertNotIn("Traceback", never.stderr)
        self.assertEqual({"holds_table": False, "rows": []}, json.loads(never.stdout))
        self.assertIn("从来没有记过读取", never.stderr)
        self.assertIn("不是「记过但为空」", never.stderr)

        blank_db = self.root / "blank.sqlite3"
        blank_exports = self.root / "blank-exports"
        env = {**self.env, "DOJO_DB": str(blank_db), "DOJO_EXPORTS": str(blank_exports)}
        store = Store(blank_db)
        try:
            store.add("另一张从没有人读过它的卡。", "abstract_idea",
                      candidate_id="d-blank", session="sess-writer")
            store.ensure_reads_table()
        finally:
            store.close()
        empty = self.run_text_cli("reads", env=env)
        self.assertEqual(0, empty.returncode, empty.stderr)
        self.assertEqual({"holds_table": True, "rows": []}, json.loads(empty.stdout))
        self.assertIn("没有任何一条读记录", empty.stderr)
        self.assertNotEqual(json.loads(never.stdout), json.loads(empty.stdout),
                            "never-logged and logged-but-empty are not one state")

    def test_a_merge_that_would_drop_an_acceptance_is_refused_with_a_readable_reason(self):
        """The refusal has to reach an operator, not just a Python caller.

        #1647 measured this same merge dropping an acceptance out of `search` and the
        export header while the sentence stayed byte-identical and the CLI exited 0.
        A guard that only raises inside the library would leave that screen unchanged.
        """
        self.run_cli("add", "--id", "d-keep", "--kind", "abstract_idea",
                     "--statement", "对普通自行车，自动分配前后制动力可作为待检验的设计目标。",
                     "--source-json", json.dumps({"id": "src-keep", "type": "claimed_firsthand",
                                                  "claim": "甲", "verification": "unverified"},
                                                 ensure_ascii=False))
        self.run_cli("add", "--id", "d-other", "--kind", "abstract_idea",
                     "--statement", "普通自行车下，前后制动力自动分配是一个值得检验的设计目标。",
                     "--source-json", json.dumps({"id": "src-other", "type": "claimed_firsthand",
                                                  "claim": "乙", "verification": "unverified"},
                                                 ensure_ascii=False))
        # Accept it the way the conversation path does, through the library, then read
        # the CLI: the merge has to fail with a reason a person can act on.
        with closing(Store(self.db)) as store:
            store.record_acceptance("d-keep", "sess-a", path="discuss_conclusion")

        denied = self.run_cli("merge", "d-keep", "d-other", "--confirm", "--reason", "等价", success=False)
        self.assertIn("merge refused", denied.stderr)
        self.assertIn("d-keep", denied.stderr)
        self.assertIn("accept", denied.stderr)

        # Nothing moved, and search still hands back the accepted card.
        self.assertEqual("d-keep", self.run_cli("show", "d-keep")["resolved_id"])
        self.assertEqual(["d-keep"], [row["id"] for row in self.run_cli("search", "自行车 制动力")["results"]])
        # And the refusal is reviewable afterwards, not just a message nobody kept.
        events = self.run_cli("events", "--id", "d-keep")
        self.assertIn("merge_refused", [item["event"] for item in events])


    def test_freeze_materials_requires_a_named_library_and_reads_its_ledger(self):
        """#1893: a packet may only print entry times it read out of a named library.

        Three cells. The middle one is the sensitive one: the ledger is moved to 2019
        before freezing, so a packet that prints the run's own clock -- which is what
        this command did while it built a throwaway library internally -- cannot pass.
        """
        self.run_cli("seed")
        env_without_db = {key: value for key, value in self.env.items() if key != "DOJO_DB"}

        # A. no library named: refuse, and do not leave a directory behind.
        unnamed = self.root / "packets-unnamed"
        refused = self.run_text_cli("freeze-materials", "--outdir", str(unnamed), env=env_without_db)
        self.assertEqual(2, refused.returncode, refused.stdout)
        self.assertIn("entered_at", refused.stderr)
        self.assertFalse(unnamed.exists(), "a refused freeze still wrote a packet directory")

        # A library that does not exist is an error, not an empty library to create.
        missing = self.root / "absent.sqlite3"
        absent = self.run_text_cli("--db", str(missing), "freeze-materials",
                                   "--outdir", str(self.root / "packets-absent"), env=env_without_db)
        self.assertEqual(2, absent.returncode, absent.stdout)
        self.assertFalse(missing.exists(), "freezing created the library it was asked to read")

        # B. move the ledger, then freeze a copy: the packet has to follow the ledger.
        moved = "2019-01-01T00:00:00+00:00"
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute("UPDATE events SET created_at=? WHERE event='load_simulated_seed'", (moved,))
            (ledger_at,) = connection.execute(
                "SELECT DISTINCT created_at FROM events WHERE event='load_simulated_seed'"
            ).fetchone()
        self.assertEqual(moved, ledger_at, "backdating did not take; the cell would prove nothing")
        before = self.db.read_bytes()
        outdir = self.root / "packets-named"
        frozen = self.run_text_cli("--db", str(self.db), "freeze-materials", "--outdir", str(outdir),
                                   env=env_without_db)
        self.assertEqual(0, frozen.returncode, frozen.stderr)
        self.assertIn(str(self.db), frozen.stdout, "the receipt does not name the library it read")
        self.assertEqual(before, self.db.read_bytes(), "describing the library rewrote its bytes")

        packet = (outdir / "target-with-retrieved-dojo-c.md").read_text(encoding="utf-8")
        source_lines = [line for line in packet.splitlines() if line.startswith("来源：")]
        self.assertTrue(source_lines)
        for line in source_lines:
            self.assertIn(f"entered_at: {ledger_at}", line, line)

        # C. --outdir is required: defaulting into the shipped historical packet could
        # only ever produce a refusal that invites deleting that artifact.
        no_outdir = self.run_text_cli("--db", str(self.db), "freeze-materials", env=env_without_db)
        self.assertNotEqual(0, no_outdir.returncode)
        self.assertIn("--outdir", no_outdir.stderr)

    def test_a_library_path_that_cannot_be_read_says_which_path_and_why(self):
        """#1921: the two shapes that produced a bare sqlite message naming no path.

        `--db <a directory>` and `--db <a file that is not sqlite>` both used to print
        only `unable to open database file` / `file is not a database` -- the sqlite
        text, with no path, and with no statement of what the reader should do. The
        assertions below are on stderr from a real run, and they name the failing path,
        because that is the only thing that tells the reader which of their paths it is.
        """
        env_without_db = {key: value for key, value in self.env.items() if key != "DOJO_DB"}

        # A. a directory where a library file was named.
        directory = self.root / "a-directory.sqlite3"
        directory.mkdir()
        as_dir = self.run_text_cli("--db", str(directory), "freeze-materials",
                                   "--outdir", str(self.root / "packets-dir"), env=env_without_db)
        self.assertEqual(2, as_dir.returncode, as_dir.stdout)
        self.assertIn(str(directory), as_dir.stderr, as_dir.stderr)
        self.assertIn("目录", as_dir.stderr, as_dir.stderr)

        # B. a file that exists but is not a sqlite database.
        garbage = self.root / "not-a-library.sqlite3"
        garbage.write_bytes(b"this is not a sqlite database" * 40)
        before = garbage.read_bytes()
        not_db = self.run_text_cli("--db", str(garbage), "freeze-materials",
                                   "--outdir", str(self.root / "packets-garbage"), env=env_without_db)
        self.assertEqual(2, not_db.returncode, not_db.stdout)
        self.assertIn(str(garbage), not_db.stderr, not_db.stderr)
        self.assertEqual(before, garbage.read_bytes(), "a refused freeze rewrote the file it was told to read")
        self.assertFalse((self.root / "packets-garbage").exists(), "a refused freeze wrote a packet directory")

    def test_the_command_a_refusal_prints_can_be_copied_and_run_once(self):
        """#1904: an instruction that fails when followed costs a second round trip.

        The assertion is not on the source text. It reads the stderr a person would see,
        pulls out the dojo command printed there, fills only the placeholders, and runs
        it. Two stderr readers are exercised: the refusal that asks for `--db`, and the
        refusal that asks for `seed` on a library that does not exist yet.
        """
        import re

        def offered(stderr):
            found = [m.group(1).strip() for m in re.finditer(r"`([^`]*python3 -m dojo[^`]*)`", stderr)]
            found += [line.strip() for line in stderr.splitlines() if line.strip().startswith("python3 -m dojo")]
            self.assertTrue(found, f"the refusal offers no command to run:\n{stderr}")
            return found[0]

        def fill(command, library, outdir):
            text = command
            for placeholder in ("<已存在的库>", "<库>"):
                text = text.replace(placeholder, str(library))
            for placeholder in ("<一个新的目录>", "<新目录>", "<目录>"):
                if placeholder in text:
                    text = text.replace(placeholder, str(outdir))
                    break
            tokens = text.split()
            self.assertEqual(["python3", "-m", "dojo"], tokens[:3], text)
            return tokens[3:]

        fresh_library = self.root / "hint-library.sqlite3"
        fresh_outdir = self.root / "hint-packets"
        env = {**self.env, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}

        # A. library that does not exist yet: the hint has to name the creating command.
        missing = self.run_text_cli("--db", str(fresh_library), "freeze-materials",
                                    "--outdir", str(fresh_outdir), env=env)
        self.assertEqual(2, missing.returncode, missing.stdout)
        create = fill(offered(missing.stderr), fresh_library, fresh_outdir)
        made = self.run_text_cli(*create, env=env)
        self.assertEqual(0, made.returncode, made.stderr)

        # B. no --db: the printed command must be complete, --outdir included.
        second_outdir = self.root / "hint-packets-2"
        env_without_db = {key: value for key, value in env.items() if key != "DOJO_DB"}
        refused = self.run_text_cli("freeze-materials", "--outdir", str(second_outdir), env=env_without_db)
        self.assertEqual(2, refused.returncode, refused.stdout)
        argv = fill(offered(refused.stderr), fresh_library, second_outdir)
        self.assertIn("--outdir", argv,
                      f"the printed command omits the required --outdir, so following it fails again: {argv}")
        followed = self.run_text_cli(*argv, env=env_without_db)
        self.assertEqual(0, followed.returncode, followed.stderr)
        self.assertTrue((second_outdir / "target-with-retrieved-dojo-c.md").is_file())

    def test_a_library_that_belongs_to_another_application_is_not_told_to_seed(self):
        """#1921: `seed` writes candidates/events/pipeline_marks/snapshots into the file.

        Every file without a `candidates` table used to be told "run seed on it",
        including a healthy SQLite file belonging to somebody's other application.
        Measured on a copy of exactly that shape: following the hint took the file from
        8192 to 61440 bytes and added four tables, leaving the application's own rows in
        place -- a quiet change to a database the reader never offered to dojo.

        The shapes are now told apart: a new path (absent or 0 bytes), a database with no
        application tables of its own, and an existing database with someone else's
        tables. Only the first two get a command that writes. The assertion looks for a
        runnable seeding command rather than for the word `seed`, because the third
        refusal still has to *warn* about what seed would do.
        """
        import re
        import shlex

        env = {key: value for key, value in self.env.items() if key != "DOJO_DB"}

        def seeding_commands(text):
            return [match.group(0).strip()
                    for match in re.finditer(r"python3 -m dojo[^\n]*\bseed\b[^\n]*", text)]

        def argv_of(command):
            tokens = [token.strip('"') for token in shlex.split(command, posix=False)]
            self.assertEqual(["python3", "-m", "dojo"], tokens[:3], command)
            # `run_text_cli` already prepends the interpreter and `-m dojo`.
            return tokens[3:]

        # C. an existing, healthy SQLite file that belongs to another application.
        foreign = self.root / "orders.sqlite3"
        with closing(sqlite3.connect(foreign)) as connection, connection:
            connection.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, total INTEGER)")
            connection.execute("INSERT INTO orders (total) VALUES (42)")
        before = foreign.read_bytes()
        refused = self.run_text_cli("--db", str(foreign), "freeze-materials",
                                    "--outdir", str(self.root / "packets-foreign"), env=env)
        self.assertEqual(2, refused.returncode, refused.stdout)
        self.assertIn(str(foreign), refused.stderr, refused.stderr)
        self.assertIn("orders", refused.stderr, f"it does not say what it found: {refused.stderr}")
        self.assertEqual([], seeding_commands(refused.stderr),
                         f"it hands the reader a command that seeds somebody else's library:\n{refused.stderr}")
        self.assertEqual(before, foreign.read_bytes(), "a refused freeze wrote to the library it refused")
        self.assertFalse((self.root / "packets-foreign").exists())

        # A and B. A new path, and a database with no tables of its own: seeding one is
        # the step that creates a library, so the command is offered -- and must run.
        for name, prepare in (("empty-bytes.sqlite3", "zeros"), ("no-tables.sqlite3", "dropped")):
            library = self.root / name
            if prepare == "dropped":
                with closing(sqlite3.connect(library)) as connection, connection:
                    connection.execute("CREATE TABLE t (x INTEGER)")
                    connection.execute("DROP TABLE t")
                self.assertGreater(library.stat().st_size, 0, "the sample is not a real sqlite header")
            else:
                library.write_bytes(b"")
            asked = self.run_text_cli("--db", str(library), "freeze-materials",
                                      "--outdir", str(self.root / f"packets-{name}"), env=env)
            self.assertEqual(2, asked.returncode, asked.stdout)
            commands = seeding_commands(asked.stderr)
            self.assertEqual(1, len(commands), f"{name}: no single command to run:\n{asked.stderr}")
            made = self.run_text_cli(*argv_of(commands[0]), env=env)
            self.assertEqual(0, made.returncode, made.stderr)
            with closing(sqlite3.connect(library)) as connection:
                self.assertIsNotNone(connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='candidates'").fetchone())

        # D. A path with spaces: the printed command must arrive as one argument.
        spaced = self.root / "a directory with spaces"
        spaced.mkdir()
        library = spaced / "my dojo.sqlite3"
        hinted = self.run_text_cli("--db", str(library), "freeze-materials",
                                   "--outdir", str(self.root / "packets-spaced"), env=env)
        self.assertEqual(2, hinted.returncode, hinted.stdout)
        commands = seeding_commands(hinted.stderr)
        self.assertEqual(1, len(commands), hinted.stderr)
        argv = argv_of(commands[0])
        self.assertIn(str(library), argv,
                      f"the spaced path would be pasted as two arguments: {argv}")
        made = self.run_text_cli(*argv, env=env)
        self.assertEqual(0, made.returncode, made.stderr)
        self.assertTrue(library.is_file())

    def test_a_library_whose_ledger_has_no_time_column_says_it_never_stored_times(self):
        """#1929: the question this field exists for, answered for a library that can't.

        A dojo-shaped library whose `events` table simply has no `created_at` -- what an
        import that dropped the column looks like. The first time read raises
        `no such column: created_at` from inside a query, naming neither the library nor
        the fact the reader needs. Measured on the old bytes: rc=2 with exactly that
        message and no packet. The refusal must name the library and say there is nothing
        to backfill, because that is the difference between "this tool failed" and
        "this data never had the fact".
        """
        env = {key: value for key, value in self.env.items() if key != "DOJO_DB"}
        library = self.root / "imported.sqlite3"
        self.run_text_cli("--db", str(library), "seed", env=env)
        with closing(sqlite3.connect(library)) as connection, connection:
            connection.execute("ALTER TABLE events DROP COLUMN created_at")

        refused = self.run_text_cli("--db", str(library), "freeze-materials",
                                    "--outdir", str(self.root / "packets-no-time"), env=env)
        self.assertEqual(2, refused.returncode, refused.stdout)
        self.assertIn(str(library), refused.stderr, refused.stderr)
        self.assertIn("created_at", refused.stderr, refused.stderr)
        self.assertNotIn("no such column", refused.stderr, refused.stderr)
        self.assertFalse((self.root / "packets-no-time").exists(), "a refused freeze wrote a packet")


if __name__ == "__main__":
    unittest.main()
