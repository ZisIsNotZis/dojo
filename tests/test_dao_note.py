"""探针笔记进同一条 loop：一场笔记 + 一份提炼 → 四件套（笔记、提取、回执、道图），不写一行代码。

这里最重要的不是「能跑通」，是「坏的不进半截」：缺头部行、锚对不上、少一格、词表没有那一对、
来源类别没写，每一种都必须被拒并说出是哪一样，且盘上不留任何文件。
"""

import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DAO = ROOT / "docs" / "dao"
DEMO = DAO / "probe-demo"
SPEC = importlib.util.spec_from_file_location("dao_life", ROOT / "scripts" / "dao_life.py")
dao_life = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dao_life)

AT = "2026-10-23T22:00:00Z"


class NoteIngestTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="dojo-note-"))
        shutil.copy(DAO / "vocabulary.json", self.dir / "vocabulary.json")
        self.session = self.dir / "session"
        self.session.mkdir()
        shutil.copy(DEMO / "note.md", self.session / "note.md")
        shutil.copy(DEMO / "extraction.json", self.session / "extraction.json")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    # --- helpers ---------------------------------------------------------
    def note(self):
        return (self.session / "note.md").read_text(encoding="utf-8")

    def write_note(self, text):
        (self.session / "note.md").write_text(text, encoding="utf-8")

    def extraction(self):
        return json.loads((self.session / "extraction.json").read_text(encoding="utf-8"))

    def write_extraction(self, value):
        (self.session / "extraction.json").write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def run_command(self, *extra):
        return dao_life.main(["dao_life", str(self.session), "--at", AT, *extra])

    def written(self):
        return sorted(path.name for path in self.session.iterdir() if path.name not in {"note.md", "extraction.json"})

    # --- the path works --------------------------------------------------
    def test_a_probe_session_comes_out_as_a_dao_with_receipts(self):
        self.assertEqual(self.run_command(), 0)
        data = dao_life.load_library(self.session)
        self.assertEqual(len(data["daos"]["daos"]), 1)
        dao = data["daos"]["daos"][0]
        self.assertEqual(dao["situation"]["when"], "这个行为会重复发生，而正确动作的准备太麻烦")
        self.assertEqual(dao["tension"]["sides"], ["省力", "练习"])
        self.assertEqual(dao["provenance"][0]["episode"], "ep-p-demo-T1")
        receipts = dao_life.run_bench(data, AT, json.loads((self.dir / "vocabulary.json").read_text(encoding="utf-8")))
        self.assertEqual(receipts["dao-p-demo-T1"]["structure"]["verdict"], "pass")
        self.assertEqual(receipts["dao-p-demo-T1"]["falsifiable"]["verdict"], "pass")
        self.assertGreaterEqual(len(receipts["dao-p-demo-T1"]["falsifiable"]["cases"]), 2)
        self.assertEqual(receipts["dao-p-demo-T1"]["field"]["verdict"], "not_run")
        self.assertTrue((self.session / "道图.md").exists())
        self.assertTrue((self.session / "receipts.json").exists())
        page = (self.session / "道图.md").read_text(encoding="utf-8")
        self.assertIn("模拟来源", page)

    def test_a_note_library_is_derived_not_copied(self):
        self.assertEqual(self.run_command(), 0)
        # 没有生成 episodes.json / daos.json：笔记是唯一的事实出处，不做第二份拷贝
        self.assertEqual(self.written(), ["receipts.json", "道图.md"])

    # --- refusals --------------------------------------------------------
    def assert_refused(self, fragment):
        code = self.run_command()
        self.assertEqual(code, 1)
        self.assertEqual(self.written(), [])
        return code

    def test_a_note_missing_a_header_line_is_refused_by_name(self):
        text = self.note().replace("minutes: 20\n", "")
        self.write_note(text)
        with self.assertRaises(dao_life.NoteError) as caught:
            dao_life.load_library(self.session)
        self.assertIn("minutes", str(caught.exception))
        self.assert_refused("minutes")

    def test_an_anchor_that_is_not_in_the_transcript_is_refused(self):
        text = self.note().replace("锚: 03:10", "锚: 09:59")
        self.write_note(text)
        with self.assertRaises(dao_life.NoteError) as caught:
            dao_life.load_library(self.session)
        self.assertIn("09:59", str(caught.exception))
        self.assertIn("找不到", str(caught.exception))

    def test_a_tension_line_missing_a_field_is_refused(self):
        text = self.note().replace(" | 方向: 降摩擦", "")
        self.write_note(text)
        with self.assertRaises(dao_life.NoteError) as caught:
            dao_life.load_library(self.session)
        self.assertIn("方向", str(caught.exception))

    def test_an_unquoted_quote_is_refused(self):
        text = self.note().replace('原话: "一想到要收就很烦"', "原话: 一想到要收就很烦")
        self.write_note(text)
        with self.assertRaises(dao_life.NoteError) as caught:
            dao_life.load_library(self.session)
        self.assertIn("逐字带引号", str(caught.exception))

    def test_a_tension_the_vocabulary_does_not_hold_is_refused(self):
        value = self.extraction()
        value["daos"][0]["tension_key"] = "我自己编的一个词"
        self.write_extraction(value)
        self.assertEqual(self.run_command(), 1)
        self.assertEqual(self.written(), [])

    def test_a_note_without_an_extraction_sidecar_is_refused(self):
        (self.session / "extraction.json").unlink()
        with self.assertRaises(dao_life.NoteError) as caught:
            dao_life.load_library(self.session)
        self.assertIn("extraction.json", str(caught.exception))

    def test_a_missing_vocabulary_is_refused_not_crashed(self):
        (self.dir / "vocabulary.json").unlink()
        self.assertEqual(self.run_command(), 1)
        self.assertEqual(self.written(), [])

    def test_an_extraction_without_a_source_class_is_refused(self):
        value = self.extraction()
        del value["attribution"]
        self.write_extraction(value)
        with self.assertRaises(dao_life.NoteError) as caught:
            dao_life.load_library(self.session)
        self.assertIn("来源类别", str(caught.exception))

    def test_an_extraction_that_skips_a_tension_does_not_half_ingest(self):
        value = self.extraction()
        value["daos"][0]["tension"] = "另一个 ↔ 张力"
        self.write_extraction(value)
        with self.assertRaises(dao_life.NoteError) as caught:
            dao_life.load_library(self.session)
        self.assertIn("省力 ↔ 练习", str(caught.exception))

    def test_an_extraction_that_skips_a_required_part_is_refused(self):
        value = self.extraction()
        del value["daos"][0]["price"]
        self.write_extraction(value)
        with self.assertRaises(dao_life.NoteError) as caught:
            dao_life.load_library(self.session)
        self.assertIn("price", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
