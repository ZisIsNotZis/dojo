"""Receipts distinguish no material, a draft, and a version approved before EOF."""
from __future__ import annotations

import io
from pathlib import Path
import shlex
import tempfile
import unittest

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

    def test_no_record_does_not_offer_a_card_command(self):
        text = self.session([])
        self.assertIn("本场没有留下认可版本或待看草稿", text)
        self.assertNotIn("distill --session", text)

    def test_draft_only_can_be_read_without_trace(self):
        text = self.session(["先试在桌上只写下一步"])
        self.assertIn("本场留下：0 个已认可版本，1 份未认可草稿", text)
        row, = self.read_from(text)["cards"]
        self.assertEqual("unaccepted_draft", row["approval_status"])
        self.assertIsNone(row["classification"])

    def test_approved_version_can_be_read_without_trace(self):
        text = self.session(["先试在桌上只写下一步", "/认可"])
        self.assertIn("本场留下：1 个已认可版本，0 份未认可草稿", text)
        row, = self.read_from(text)["cards"]
        self.assertEqual("approved", row["approval_status"])
        self.assertEqual(1, row["version"])
        self.assertIsNone(row["classification"])


if __name__ == "__main__":
    unittest.main()
