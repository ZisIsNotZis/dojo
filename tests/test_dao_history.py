"""Append-only receipts: CPU-only disposable-library acceptance checks."""
import importlib.util
import hashlib
import io
import contextlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("dao_life_history", ROOT / "scripts/dao_life.py")
life = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(life)
SEED_SPEC = importlib.util.spec_from_file_location("seed_dao", ROOT / "fixtures/seed_dao.py")
seed = importlib.util.module_from_spec(SEED_SPEC)
SEED_SPEC.loader.exec_module(seed)
AT = seed.AT


class DaoHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dao-history-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "dao"
        seed.build(self.root)
        self.lib = self.root / seed.A
        seed.put(self.lib / "record_checks.json", {"checks": []})
        (self.root / seed.B / "receipts.json").write_bytes(seed.OLD_BYTES)
        (self.lib / "对比.md").write_text("虚构的旧比较投影。\n", encoding="utf-8")
        self.assertFalse((self.lib / "history").exists())

    def run_cli(self, *args):
        return life.main(["dao-life", str(self.lib), "--at", AT, *args])

    def tree_bytes(self):
        return {str(p.relative_to(self.root)): p.read_bytes()
                for p in self.root.rglob("*") if p.is_file()}

    def runs(self):
        return sorted((self.lib / "history").glob("[0-9a-f]" * 64 + ".json"))

    def test_versions_survive_and_identical_content_is_idempotent(self):
        old = (self.lib / "receipts.json").read_bytes()
        self.assertEqual(self.run_cli(), 0)
        first = self.runs()
        self.assertEqual(len(first), 1)
        original = first[0].read_bytes()
        before = {str(p): (p.read_bytes(), p.stat().st_mtime_ns)
                  for p in (self.lib / "history").iterdir()}
        self.assertEqual(self.run_cli(), 0)
        self.assertEqual(before, {str(p): (p.read_bytes(), p.stat().st_mtime_ns)
                                  for p in (self.lib / "history").iterdir()})
        legacy = list((self.lib / "history").glob("legacy-*.json"))
        self.assertEqual(len(legacy), 1)
        self.assertEqual(legacy[0].stem, "legacy-" + hashlib.sha256(old).hexdigest())
        self.assertEqual(bytes.fromhex(json.loads(legacy[0].read_text(encoding="utf8"))["receipts_hex"]), old)
        data = json.loads((self.lib / "daos.json").read_text(encoding="utf8"))
        data["daos"][0]["version"] += 1
        (self.lib / "daos.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf8")
        self.assertEqual(self.run_cli(), 0)
        self.assertEqual(len(self.runs()), 2)
        self.assertEqual(first[0].read_bytes(), original)
        self.assertEqual(json.loads((self.lib / "receipts.json").read_text(encoding="utf8"))["daos"]["ring-d-1"]["version"], 3)

    def test_crash_after_history_commit_can_repair_projections(self):
        old = (self.lib / "receipts.json").read_bytes()
        # History commit must precede projection writes.
        with patch.object(life, "_atomic_projection", side_effect=OSError("injected after commit"), create=True):
            self.assertEqual(self.run_cli(), 1)
        self.assertEqual(len(self.runs()), 1)
        self.assertEqual((self.lib / "receipts.json").read_bytes(), old)
        committed = self.runs()[0].read_bytes()
        self.assertEqual(self.run_cli(), 0)
        self.assertEqual(len(self.runs()), 1)
        self.assertEqual(self.runs()[0].read_bytes(), committed)
        bundle = json.loads(committed)
        self.assertEqual(json.loads((self.lib / "receipts.json").read_text(encoding="utf8")), bundle["receipts"])
        self.assertEqual((self.lib / "道图.md").read_text(encoding="utf8"), bundle["map_markdown"])

    def test_check_never_imports_legacy_or_creates_history(self):
        before = self.tree_bytes()
        self.assertEqual(self.run_cli("--check"), 0)
        self.assertEqual(before, self.tree_bytes())
        self.assertFalse((self.lib / "history").exists())

    def test_bundle_hash_and_all_input_digests_are_verifiable(self):
        before = self.tree_bytes()
        self.assertEqual(self.run_cli(), 0)
        bundle = json.loads(self.runs()[0].read_text(encoding="utf8"))
        self.assertEqual(life.digest(bundle), self.runs()[0].stem)
        hashes = bundle["receipts"]["inputs"]
        for name in ("record_checks", "promotions"):
            self.assertEqual(hashes[name], life.digest(life.load(self.lib / (name + ".json"))))
        self.assertEqual(hashes["vocabulary"], life.digest(life.load(self.root / "vocabulary.json")))
        self.assertIn("之前历史未知或缺失", bundle["map_markdown"])
        self.assertEqual(bundle["history_coverage"]["prior_history"], "unknown_or_missing")
        after = self.tree_bytes()
        for name, content in before.items():
            if not name.endswith(("receipts.json", "道图.md")):
                self.assertEqual(after[name], content, name)

    def test_unsupported_atomic_publish_leaves_no_fake_receipt(self):
        before = self.tree_bytes()
        with patch.object(life.os, "link", side_effect=OSError("links unsupported")):
            self.assertEqual(self.run_cli(), 1)
        self.assertEqual(before, self.tree_bytes())
        self.assertEqual(list((self.lib / "history").iterdir()), [])

    def test_partial_staging_failure_does_not_publish(self):
        target = self.lib / "temporary-probe.json"
        with patch.object(life.os, "fsync", side_effect=OSError("injected flush failure")):
            with self.assertRaises(OSError):
                life._publish_immutable(target, b'{"not":"complete"}')
        self.assertFalse(target.exists())
        self.assertFalse(list(self.lib.glob(".dao-pending-*")))

    def test_history_corruption_is_not_overwritten(self):
        self.assertEqual(self.run_cli(), 0)
        path = self.runs()[0]
        path.write_bytes(b'{"corrupt":true}')
        projection = (self.lib / "receipts.json").read_bytes()
        self.assertEqual(self.run_cli(), 1)
        self.assertEqual(path.read_bytes(), b'{"corrupt":true}')
        self.assertEqual((self.lib / "receipts.json").read_bytes(), projection)

    def test_comparison_reports_partial_commit_and_preserves_old_comparison(self):
        other = self.root / seed.B
        old_other = (other / "receipts.json").read_bytes()
        old_comparison = (self.lib / "对比.md").read_bytes()
        original = life.commit_history
        def fail_second(root, bundle):
            if root == other:
                raise OSError("injected second library failure")
            return original(root, bundle)
        output = io.StringIO()
        with patch.object(life, "commit_history", side_effect=fail_second), contextlib.redirect_stdout(output):
            self.assertEqual(self.run_cli("--compare", str(other)), 1)
        self.assertEqual(len(self.runs()), 1)
        self.assertEqual((other / "receipts.json").read_bytes(), old_other)
        self.assertEqual((self.lib / "对比.md").read_bytes(), old_comparison)
        self.assertIn("未宣称全部成功", output.getvalue())
        self.assertIn(str(self.lib), output.getvalue())

    def test_missing_legacy_is_disclosed_without_fabricated_snapshot(self):
        (self.lib / "receipts.json").unlink()
        self.assertEqual(self.run_cli(), 0)
        self.assertFalse(list((self.lib / "history").glob("legacy-*")))
        bundle = json.loads(self.runs()[0].read_text(encoding="utf8"))
        self.assertEqual(bundle["history_coverage"]["prior_history"], "unknown_or_missing")
