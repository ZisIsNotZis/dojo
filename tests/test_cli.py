import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CliEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / "cli.sqlite3"
        self.exports = self.root / "exports"
        self.env = {**os.environ, "DOJO_DB": str(self.db), "DOJO_EXPORTS": str(self.exports)}

    def tearDown(self):
        self.temp.cleanup()

    def run_cli(self, *args, success=True):
        result = subprocess.run(
            [sys.executable, "-m", "dojo", *args], cwd=ROOT, env=self.env,
            text=True, capture_output=True, timeout=20,
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
            env=self.env if env is None else env, text=True, input=input_text,
            capture_output=True, timeout=30,
        )

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
        self.assertFalse((workdir / "summary.md").stat().st_mode & 0o077)
        self.assertFalse((workdir / "dojo.sqlite3").stat().st_mode & 0o077)
        with sqlite3.connect(workdir / "dojo.sqlite3") as connection:
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
        with sqlite3.connect(workdir / "dojo.sqlite3") as connection:
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
        with sqlite3.connect(eof_dir / "dojo.sqlite3") as connection:
            self.assertEqual(0, connection.execute("SELECT count(*) FROM candidates").fetchone()[0])

        custom_dir = self.root / "demo-custom"
        custom_text = "我自己的真实项目想法不应被模拟脚本理解"
        custom = self.run_text_cli("demo", "--workdir", str(custom_dir), input_text=f"\n{custom_text}\nq\n")
        self.assertEqual(0, custom.returncode, custom.stderr)
        self.assertIn("不会假装已理解", custom.stdout)
        self.assertNotIn(custom_text, (custom_dir / "summary.md").read_text(encoding="utf-8"))
        with sqlite3.connect(custom_dir / "dojo.sqlite3") as connection:
            self.assertEqual(0, connection.execute("SELECT count(*) FROM candidates").fetchone()[0])

        # start, skip custom text, reject 甲's card, reject 丙's card, decline the revision.
        reject_dir = self.root / "demo-rejected"
        rejected = self.run_text_cli("demo", "--workdir", str(reject_dir), input_text="\n\nn\nn\nn\n")
        self.assertEqual(0, rejected.returncode, rejected.stderr)
        self.assertIn("贡献者拒绝了这张候选", rejected.stdout)
        self.assertIn("已保存挑战", rejected.stdout)
        self.assertIn("修订未被接受", rejected.stdout)
        with sqlite3.connect(reject_dir / "dojo.sqlite3") as connection:
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
        with sqlite3.connect(edit_dir / "dojo.sqlite3") as connection:
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
        self.assertFalse(Path(self.db).stat().st_mode & 0o077)


if __name__ == "__main__":
    unittest.main()
