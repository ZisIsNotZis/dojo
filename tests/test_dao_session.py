import io
import json
import shutil
import sys
import tempfile
import unittest
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
        data["daos"][0]["part_sources"] = {"situation":"他的原话", "tension":"他的原话", "move":"他的原话", "price":"他的原话", "off":"他的原话", "provenance":"他的原话"}
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def test_real_discuss_trace_exports_parses_and_builds(self):
        rows = [json.loads(line) for line in self.trace.read_text(encoding="utf-8").splitlines()]
        self.assertTrue(any(r.get("decision") == "written" for r in rows))
        self.assertEqual(sum(r.get("event") == "elicitation" for r in rows), 4)
        self.assertEqual(self.run_export(), 0)
        note = dao_life._parse_note(self.out / "note.md")
        written = next(r for r in rows if r.get("decision") == "written")
        self.assertEqual(note["tensions"][0]["direction"], written["candidate"]["statement"])
        self.prepare_extraction(self.out)
        dao = dao_life.build_library_from_note(self.out)["daos"]["daos"][0]
        self.assertEqual(dao["tension"]["name"], "省力 ↔ 练习")

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
        trace = self.make_real_trace([ANSWERS[0], "没有成对表达", ANSWERS[2], ANSWERS[3]])
        import contextlib
        capture = io.StringIO()
        with contextlib.redirect_stderr(capture):
            self.assertNotEqual(self.run_export(trace, self.out), 0)
        self.assertIn("张力", capture.getvalue())
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
        extraction = json.loads((self.out / "extraction.json").read_text(encoding="utf-8"))
        extraction["daos"][0]["part_sources"] = {"situation":"他的原话", "tension":"他的原话", "move":"他的原话", "price":"他的原话", "off":"他的原话", "provenance":"他的原话"}
        (self.out / "extraction.json").write_text(json.dumps(extraction, ensure_ascii=False), encoding="utf-8")
        session_path = self.out / "session.json"
        session = json.loads(session_path.read_text(encoding="utf-8"))
        session["tensions"][0]["parts"]["price"]["promoted"] = False
        session_path.write_text(json.dumps(session, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(dao_life.NoteError, "作者冲突"):
            dao_life.build_library_from_note(self.out)

if __name__ == "__main__":
    unittest.main()
