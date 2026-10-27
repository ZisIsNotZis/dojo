import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))
import dao_session
import dao_life
from dao_live_session import ScriptedHost, DISCUSSION
from dojo.discuss import run_discuss
from dojo.storage import Store

ANSWERS = ["在重复做饭时", "省力 ↔ 练习", "失去一些练习", "当练习本身是目标"]

class DaoSessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.out = self.root / "out"
        self.trace = self.make_real_trace(ANSWERS)

    def tearDown(self):
        self.tmp.cleanup()

    def make_real_trace(self, answers):
        """Produce the fixture with discuss itself: temp SQLite, ScriptedHost, no network."""
        root = self.root / ("run-" + str(len(list(self.root.glob("run-*")))))
        root.mkdir()
        values = [text for _, text in DISCUSSION] + list(answers)
        iterator = iter(values)
        def read_line(_prompt):
            try:
                return next(iterator)
            except StopIteration:
                raise EOFError
        store = Store(root / "dojo.sqlite3")
        try:
            code = run_discuss(
                store, client=ScriptedHost(), read_line=read_line, output=io.StringIO(),
                environ={"DOJO_SESSIONS": str(root / "sessions")}, no_profile=True,
            )
        finally:
            store.close()
        self.assertEqual(code, 0)
        traces = list((root / "sessions").glob("*.jsonl"))
        self.assertEqual(len(traces), 1)
        return traces[0]

    def run_export(self, trace=None, out=None, *, check=False, person="p-demo"):
        return dao_session.main([
            "--trace", str(trace or self.trace), "--out", str(out or self.out),
            "--person", person, "--sample", "acquaintances", *( ["--check"] if check else [] ),
        ])

    def prepare_extraction(self, out):
        shutil.copy(ROOT / "docs/dao/probe-demo/extraction.json", out / "extraction.json")
        path = out / "extraction.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["daos"][0]["tension"] = "省力 ↔ 练习"
        data["attribution"] = "person"
        data["daos"][0]["move"]["direction"] = dao_life._parse_note(out / "note.md")["tensions"][0]["direction"]
        data["daos"][0]["part_sources"] = {"situation":"他的原话", "tension":"他的原话", "move":"他的原话", "price":"他的原话", "off":"他的原话", "provenance":"他的原话"}
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def test_real_discuss_trace_exports_parses_and_builds(self):
        rows = [json.loads(line) for line in self.trace.read_text(encoding="utf-8").splitlines()]
        self.assertTrue(any(r.get("decision") == "written" for r in rows))
        self.assertEqual(sum(r.get("event") == "elicitation" for r in rows), 4)
        self.assertEqual(self.run_export(), 0)
        note_path = self.out / "note.md"
        note = dao_life._parse_note(note_path)
        written = next(r for r in rows if r.get("decision") == "written")
        self.assertEqual(note["tensions"][0]["direction"], written["candidate"]["statement"])
        trace_inputs = []
        for row in rows:
            if isinstance(row.get("user"), str):
                trace_inputs.append((row["at"], row["user"]))
            if row.get("event") == "elicitation" and "answer" in row:
                trace_inputs.append((row["at"], row["answer"] or ""))
        trace_inputs.sort(key=lambda pair: datetime.fromisoformat(pair[0].replace("Z", "+00:00")))
        first_at = datetime.fromisoformat(trace_inputs[0][0].replace("Z", "+00:00"))
        expected = []
        for at_text, text in trace_inputs:
            at = datetime.fromisoformat(at_text.replace("Z", "+00:00"))
            seconds = int((at - first_at).total_seconds())
            expected.append(f"[{seconds // 60:02d}:{seconds % 60:02d}] {text}")
        note_lines = note["text"].splitlines()
        begin = note_lines.index("## 逐字") + 1
        end = next(i for i in range(begin, len(note_lines)) if note_lines[i].startswith("## "))
        section_lines = note_lines[begin:end]
        emitted = [line for line in section_lines if line]
        self.assertTrue(all(re.fullmatch(r"\[\d{2}:\d{2}\] .*", line) for line in emitted))
        self.assertEqual(emitted, expected)
        stamps = [datetime.strptime(line[1:6], "%M:%S") for line in emitted]
        self.assertTrue(all(left <= right for left, right in zip(stamps, stamps[1:])))
        original_tension = next(r["answer"] for r in rows if r.get("event") == "elicitation" and r.get("part") == "张力")
        for side in note["tensions"][0]["sides"]:
            self.assertIn(side, original_tension)
        session_record = json.loads((self.out / "session.json").read_text(encoding="utf-8"))
        self.assertEqual(session_record["trace_sha256"], hashlib.sha256(self.trace.read_bytes()).hexdigest())
        self.assertEqual(session_record["note_sha256"], hashlib.sha256(note_path.read_bytes()).hexdigest())
        self.prepare_extraction(self.out)
        data = dao_life.build_library_from_note(self.out)
        dao = data["daos"]["daos"][0]
        self.assertEqual(dao["tension"]["name"], "省力 ↔ 练习")
        self.assertEqual(dao_life.authorship(dao["part_sources"]), "他的")
        episodes = {episode["id"]: episode for episode in data["episodes"]["episodes"]}
        self.assertEqual(dao_life.base_word(dao, episodes), "自述")

    def test_real_discuss_unanswered_part_refuses_without_output(self):
        answers = list(ANSWERS)
        answers[2:3] = ["", ""]
        trace = self.make_real_trace(answers)
        import contextlib
        capture = io.StringIO()
        with contextlib.redirect_stderr(capture):
            self.assertNotEqual(self.run_export(trace, self.out), 0)
        self.assertFalse(self.out.exists())
        self.assertIn("代价", capture.getvalue())

    def test_trace_without_written_round_before_elicitation_refuses(self):
        rows = [json.loads(line) for line in self.trace.read_text(encoding="utf-8").splitlines()]
        rows = [r for r in rows if r.get("decision") != "written"]
        bad = self.root / "orphan.jsonl"
        bad.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
        import contextlib
        capture = io.StringIO()
        with contextlib.redirect_stderr(capture):
            self.assertNotEqual(self.run_export(bad, self.out), 0)
        self.assertIn("结论", capture.getvalue())
        self.assertFalse(self.out.exists())

    def test_direction_missing_and_check_parser_refusal_do_not_write(self):
        rows = [json.loads(line) for line in self.trace.read_text(encoding="utf-8").splitlines()]
        for row in rows:
            if row.get("decision") == "written": row["candidate"] = None
        bad = self.root / "no-direction.jsonl"
        bad.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
        import contextlib
        capture = io.StringIO()
        with contextlib.redirect_stderr(capture):
            self.assertNotEqual(self.run_export(bad, self.out), 0)
        self.assertIn("方向: 会话里没有写下这条结论的方向", capture.getvalue())
        self.assertFalse(self.out.exists())
        # Header injection makes the would-be note invalid; --check surfaces parser cause and writes nothing.
        capture = io.StringIO()
        with contextlib.redirect_stderr(capture):
            self.assertNotEqual(self.run_export(check=True, person="p-demo\nnot-a-header"), 0)
        self.assertIn("note.md:", capture.getvalue())
        self.assertFalse(self.out.exists())

    def test_real_discuss_tension_without_two_sides_refuses(self):
        for answer, named_empty in (("没有成对表达", "缺少左侧和右侧"), (" ↔ 练习", "左侧为空"), ("省力 ↔ ", "右侧为空")):
            with self.subTest(answer=answer):
                trace = self.make_real_trace([ANSWERS[0], answer, ANSWERS[2], ANSWERS[3]])
                import contextlib
                capture = io.StringIO()
                with contextlib.redirect_stderr(capture):
                    self.assertNotEqual(self.run_export(trace, self.out), 0)
                self.assertIn(named_empty, capture.getvalue())
                self.assertFalse(self.out.exists())

    def test_empty_trace_missing_end_and_missing_elicitation_refuse(self):
        import contextlib
        capture = io.StringIO()
        empty = self.root / "empty.jsonl"
        empty.write_text("", encoding="utf-8")
        with contextlib.redirect_stderr(capture):
            self.assertNotEqual(self.run_export(empty, self.out), 0)
        self.assertIn("empty trace", capture.getvalue())
        self.assertFalse(self.out.exists())
        rows = [json.loads(line) for line in self.trace.read_text(encoding="utf-8").splitlines()]
        for name, filtered, reason in (
            ("no-end", [r for r in rows if r.get("event") != "session_end"], "session_end"),
            ("no-elicitation", [r for r in rows if r.get("event") != "elicitation"], "elicitation"),
        ):
            bad = self.root / f"{name}.jsonl"
            bad.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in filtered) + "\n", encoding="utf-8")
            capture = io.StringIO()
            with contextlib.redirect_stderr(capture):
                self.assertNotEqual(self.run_export(bad, self.out), 0)
            self.assertIn(reason, capture.getvalue())
            self.assertFalse(self.out.exists())

    def test_unrepresentable_promoted_tension_answers_refuse(self):
        for answer, reason in (("省力 ↔ 练习|坏", "张力"), ("省力 ↔ 练习\"坏", "张力"), ("省力 ↔ 练习\n坏", "张力")):
            with self.subTest(answer=answer):
                trace = self.make_real_trace([ANSWERS[0], answer, ANSWERS[2], ANSWERS[3]])
                import contextlib
                capture = io.StringIO()
                with contextlib.redirect_stderr(capture):
                    self.assertNotEqual(self.run_export(trace, self.root / "invalid"), 0)
                self.assertIn(reason, capture.getvalue())
                self.assertFalse((self.root / "invalid").exists())

    def test_empty_promoted_answer_is_named_refusal(self):
        rows = [json.loads(line) for line in self.trace.read_text(encoding="utf-8").splitlines()]
        event = next(r for r in rows if r.get("event") == "elicitation" and r.get("part") == "代价")
        event["answer"] = ""
        bad = self.root / "empty-promoted.jsonl"
        bad.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
        import contextlib
        capture = io.StringIO()
        with contextlib.redirect_stderr(capture):
            self.assertNotEqual(self.run_export(bad, self.out), 0)
        self.assertIn("代价", capture.getvalue())
        self.assertFalse(self.out.exists())

    def test_check_is_nonwriting_and_session_authorship_overclaim_fails(self):
        self.assertEqual(self.run_export(check=True), 0)
        self.assertFalse(self.out.exists())
        self.assertEqual(self.run_export(), 0)
        self.prepare_extraction(self.out)
        extraction_path = self.out / "extraction.json"
        extraction = json.loads(extraction_path.read_text(encoding="utf-8"))
        session_path = self.out / "session.json"
        session = json.loads(session_path.read_text(encoding="utf-8"))
        session["tensions"][0]["parts"]["price"]["answer"] = "伪造答案不在笔记中"
        session_path.write_text(json.dumps(session, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(dao_life.NoteError, "作者冲突：代价 的回答不在笔记逐字里"):
            dao_life.build_library_from_note(self.out)
        # Restore the session before independently testing the note digest.
        self.assertEqual(self.run_export(), 0)
        self.prepare_extraction(self.out)
        with (self.out / "note.md").open("a", encoding="utf-8") as note_file:
            note_file.write("\n<!-- altered -->\n")
        with self.assertRaisesRegex(dao_life.NoteError, "note_sha256"):
            dao_life.build_library_from_note(self.out)

    def test_move_direction_exact_is_accepted_but_paraphrase_is_refused(self):
        self.assertEqual(self.run_export(), 0)
        self.prepare_extraction(self.out)
        path = self.out / "extraction.json"
        extraction = json.loads(path.read_text(encoding="utf-8"))
        note_direction = dao_life._parse_note(self.out / "note.md")["tensions"][0]["direction"]
        extraction["daos"][0]["move"]["direction"] = note_direction
        path.write_text(json.dumps(extraction, ensure_ascii=False), encoding="utf-8")
        dao = dao_life.build_library_from_note(self.out)["daos"]["daos"][0]
        self.assertEqual(dao["move"]["direction"], note_direction)
        extraction["daos"][0]["move"]["direction"] = "由系统持续检查，人保留随时推翻的权利。"
        path.write_text(json.dumps(extraction, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(dao_life.NoteError, "动作方向不在笔记方向里"):
            dao_life.build_library_from_note(self.out)

    def test_extraction_move_overclaim_refuses(self):
        self.assertEqual(self.run_export(), 0)
        self.prepare_extraction(self.out)
        path = self.out / "extraction.json"
        extraction = json.loads(path.read_text(encoding="utf-8"))
        extraction["daos"][0]["move"]["direction"] = "伪造动作方向"
        path.write_text(json.dumps(extraction, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(dao_life.NoteError, "作者冲突：.*动作方向"):
            dao_life.build_library_from_note(self.out)

    def test_every_stored_provenance_status_matches_episode_source_negative_control(self):
        data = json.loads((ROOT / "docs/dao/person-dojo/daos.json").read_text(encoding="utf-8"))
        episodes = {row["id"]: row for row in json.loads((ROOT / "docs/dao/person-dojo/episodes.json").read_text(encoding="utf-8"))["episodes"]}
        independent_words = {"person":"自述", "relayed":"转述", "synthetic":"模拟", "unverified":"未核"}
        pairs = []
        for dao in data["daos"]:
            for item in dao.get("provenance") or []:
                episode = episodes[item["episode"]]
                expected = independent_words[episode["attribution"]]
                rendered = dao_life.provenance_status_for(episode)
                self.assertEqual(item["status"], rendered, (dao["id"], item["episode"], item["status"], rendered))
                self.assertEqual(rendered, expected, (dao["id"], item["episode"], expected, rendered))
                pairs.append((item, episode, expected))
        chart = (ROOT / "docs/dao/person-dojo/道图.md").read_text(encoding="utf-8")
        for item, episode, expected in pairs:
            self.assertIn(f"{item['person']} · {item['episode']} · {expected} ·", chart)
        self.assertIn("root 转达的一句话，本仓没有那一场的 trace。", chart)
        # Negative control: corrupting one stored status makes the exact assertion fail.
        negative = json.loads(json.dumps(data, ensure_ascii=False))
        first = negative["daos"][0]["provenance"][0]
        first["status"] = "错误标签"
        self.assertNotEqual(first["status"], dao_life.provenance_status_for(episodes[first["episode"]]))

    def test_export_and_dao_life_cli_pair_with_vocabulary(self):
        library = self.root / "lib"
        library.mkdir()
        export = subprocess.run(
            [sys.executable, str(ROOT / "scripts/dao_session.py"), "--trace", str(self.trace),
             "--out", str(library), "--person", "p-demo", "--sample", "acquaintances"],
            capture_output=True, text=True,
        )
        self.assertEqual(export.returncode, 0, export.stderr)
        self.assertIn("--vocabulary docs/dao/vocabulary.json --check", export.stdout)
        self.prepare_extraction(library)
        extraction_path = library / "extraction.json"
        extraction = json.loads(extraction_path.read_text(encoding="utf-8"))
        extraction["attribution"] = "synthetic"
        extraction_path.write_text(json.dumps(extraction, ensure_ascii=False), encoding="utf-8")
        vocabulary = self.root / "vocabulary.json"
        shutil.copy(ROOT / "docs/dao/vocabulary.json", vocabulary)
        check = subprocess.run(
            [sys.executable, str(ROOT / "scripts/dao_life.py"), str(library),
             "--vocabulary", str(vocabulary), "--check"],
            capture_output=True, text=True,
        )
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)

if __name__ == "__main__":
    unittest.main()
