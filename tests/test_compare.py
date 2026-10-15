import hashlib
import io
import subprocess
import sys
import unittest
from pathlib import Path

from dojo.compare import EVIDENCE_DIRECTORY, RUNS, run_compare

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_HASHES = {
    "actual-answer-b.md": "10399d20d308c81b5ea193456c5c66908f51f9fd8d31f9b11cca869a2559bb7b",
    "actual-answer-c.md": "2ed34c12e4c060b01e90837bc39ec9c6625380df7aa7aaba41b12de7235afb3a",
}


class RecordedLunaCompareTests(unittest.TestCase):
    def test_default_compare_is_concise_and_keeps_provenance_and_limits_visible(self):
        before = {run["answer"]: hashlib.sha256((EVIDENCE_DIRECTORY / run["answer"]).read_bytes()).hexdigest() for run in RUNS}
        self.assertEqual(EXPECTED_HASHES, before)
        provenance = (EVIDENCE_DIRECTORY / "provenance.md").read_text(encoding="utf-8")
        self.assertIn("5e00e5f5-e288-487c-a60d-3d6f582b3abd", provenance)
        self.assertIn("72ba1efa-eedc-42ae-b78c-8216839cc900", provenance)
        self.assertIn("target-no-dojo-b.md", provenance)
        self.assertIn("target-with-retrieved-dojo-c.md", provenance)
        self.assertIn("HTTP endpoint 调用", provenance)
        self.assertIn("不是用户研究", provenance)
        output = io.StringIO()
        run_compare(output=output)
        text = output.getvalue()
        self.assertIn("离线回放（不联网、不重新生成）", text)
        self.assertIn("github-copilot/gpt-6-luna", text)
        self.assertIn("5e00e5f5-e288-487c-a60d-3d6f582b3abd", text)
        self.assertIn("72ba1efa-eedc-42ae-b78c-8216839cc900", text)
        self.assertIn("target-no-dojo-b.md", text)
        self.assertIn("target-with-retrieved-dojo-c.md", text)
        self.assertIn("幂等", text)
        self.assertIn("来源 ID", text)
        self.assertIn("不得据此宣布胜负或 C 优于 B", text)
        self.assertLessEqual(len(text.splitlines()), 20)
        self.assertNotIn("目前不能把“重试次数改为 3", text)
        self.assertNotIn("目前能确认的只有：内部 editor bridge", text)
        after = {run["answer"]: hashlib.sha256((EVIDENCE_DIRECTORY / run["answer"]).read_bytes()).hexdigest() for run in RUNS}
        self.assertEqual(before, after)

    def test_full_compare_replays_the_saved_answers_without_altering_them(self):
        originals = {run["answer"]: (EVIDENCE_DIRECTORY / run["answer"]).read_bytes() for run in RUNS}
        output = io.StringIO()
        run_compare(full=True, output=output)
        text = output.getvalue()
        for run in RUNS:
            raw = originals[run["answer"]].decode("utf-8")
            self.assertIn(raw, text)
            self.assertIn(run["answer"], text)
        self.assertEqual(originals, {name: (EVIDENCE_DIRECTORY / name).read_bytes() for name in originals})

    def test_public_compare_command_works_offline_and_full_flag_is_available(self):
        default = subprocess.run(
            [sys.executable, "-m", "dojo", "compare"], cwd=ROOT,
            text=True, capture_output=True, timeout=10,
        )
        self.assertEqual(0, default.returncode, default.stderr)
        self.assertIn("离线回放", default.stdout)
        self.assertNotIn("源头回答全文中完整的", default.stdout)

        full = subprocess.run(
            [sys.executable, "-m", "dojo", "compare", "--full"], cwd=ROOT,
            text=True, capture_output=True, timeout=10,
        )
        self.assertEqual(0, full.returncode, full.stderr)
        self.assertIn("目前不能把“重试次数改为 3", full.stdout)
        self.assertIn("目前能确认的只有：内部 editor bridge", full.stdout)


if __name__ == "__main__":
    unittest.main()
