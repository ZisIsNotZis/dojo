"""Receipts distinguish no material, a draft, and a version approved before EOF."""
from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import shlex
import tempfile
import unittest

from dojo.cli import main
from dojo.discuss import run_discuss
from dojo.pipeline import distill
from dojo.storage import Store
from test_discuss import CONCLUSION, FakeClient, read_lines, result


class CloseReadbackTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = Store(Path(temp.name) / "library with spaces.sqlite3")
        self.addCleanup(self.store.close)

    def session(self, turns):
        output = io.StringIO()
        client = FakeClient([result("先试一下。", CONCLUSION)] if turns else [])
        code = run_discuss(self.store, client=client, read_line=read_lines(turns),
                           output=output, no_trace=True, no_profile=True, environ={})
        self.assertEqual(0, code, output.getvalue())
        self.assertEqual(1 if turns else 0, len(client.messages))
        return output.getvalue()

    def read_from(self, text):
        line, = [line for line in text.splitlines() if line.startswith("稍后看本场留下的版本和草稿")]
        self.assertIn("只读，不请求模型", line)
        args = shlex.split(line.split("：", 1)[1])
        self.assertEqual(str(self.store.path), args[args.index("--db") + 1])
        return distill(self.store, args[args.index("--session") + 1])

    def show(self, card_id):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(0, main(["--db", str(self.store.path), "show", card_id]))
        value = json.loads(output.getvalue())
        reading = value.pop("approval_reading")
        self.assertEqual(self.store.show(card_id), value)
        self.assertIn("不能证明内容已由他人独立核验", reading["独立核验"])
        return reading, value["candidate"]

    def test_no_record_does_not_offer_a_card_command(self):
        text = self.session([])
        self.assertIn("本场没有留下认可版本或待看草稿", text)
        self.assertNotIn("distill --session", text)

    def test_draft_only_can_be_read_without_trace(self):
        text = self.session(["先试在桌上只写下一步"])
        self.assertIn("资料库统计（不数轨迹里的轮次）｜本场留下：0 个已认可版本，1 份未认可草稿", text)
        row, = self.read_from(text)["cards"]
        self.assertEqual("unaccepted_draft", row["approval_status"])
        self.assertIsNone(row["classification"])
        reading, card = self.show(row["id"])
        self.assertIn("这是讨论材料", reading["措辞"])
        self.assertEqual("draft", card["status"])

    def test_approved_version_can_be_read_without_trace(self):
        text = self.session(["先试在桌上只写下一步", "/认可"])
        self.assertIn("本场留下：1 个已认可版本，0 份未认可草稿", text)
        row, = self.read_from(text)["cards"]
        self.assertEqual("approved", row["approval_status"])
        self.assertEqual(1, row["version"])
        self.assertIsNone(row["classification"])
        reading, card = self.show(row["id"])
        self.assertEqual("当前措辞有认可记录。", reading["措辞"])
        self.assertEqual("draft", card["status"])
        self.store.confirm(row["id"], "愿意继续讨论")
        reading, card = self.show(row["id"])
        self.assertEqual("当前措辞有认可记录。", reading["措辞"])
        self.assertEqual(2, card["version"])
        self.assertEqual(1, self.read_from(text)["cards"][0]["version"])
        self.store.revise(row["id"], "这是后来改写的句子", "换了措辞")
        reading, _ = self.show(row["id"])
        self.assertIn("未找到当前措辞的认可记录", reading["措辞"])

    def test_confirmation_and_source_label_cannot_prove_approval_or_verification(self):
        self.store.add("窗台要不要加挡光板？", "question", candidate_id="q-plant")
        self.store.confirm("q-plant", "本地确认可讨论")
        self.store.attach_source("q-plant", {"id": "src-label", "type": "claimed_firsthand",
                                            "claim": "这里只记录来源标签", "independence_group": "external",
                                            "verification": "independently_checked"})
        reading, card = self.show("q-plant")
        self.assertTrue(card["confirmation"]["active"])
        self.assertIn("未找到当前措辞的认可记录", reading["措辞"])


if __name__ == "__main__":
    unittest.main()
