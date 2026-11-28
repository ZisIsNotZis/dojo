import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from dojo import draft_review, distillation
from dojo.storage import DojoError, Store


class DraftReviewTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.path = root / 'discuss-0123456789abcdef0123456789abcdef.jsonl'
        self.db = root / 'notes.sqlite3'
        Store(self.db).close()
        self.card = dict(statement='两次白墙彩排看到不同的细边。', kind='application',
                         scope=['这两次白墙彩排'], unknowns=['原因不明'],
                         premises=[], alternatives=[], contradictions=[])
        self.round = dict(seq=1, user='我只说两次看到的差别。', answer='只写看到的两回。',
                          candidate=self.card, stance='neutral', decision='none',
                          reason='proposed_new_pending', pending_after=self.card['statement'],
                          pending_snapshot=self.card)
        self.end = dict(event='session_end', session=self.path.stem, reason='eof', saved=[], requests_sent=1)
        self.write_trace(self.round, self.end)

    def write_trace(self, *rows):
        self.raw = ''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows).encode()
        self.path.write_bytes(self.raw)
        self.digest = hashlib.sha256(self.raw).hexdigest()

    def review(self, *actions, digest=None):
        actions = iter(actions)
        output = io.StringIO()

        def read(_):
            try:
                action = next(actions)
            except StopIteration:
                raise EOFError from None
            if callable(action):
                return action()
            return action

        self.assertEqual(0, draft_review.run(self.path, self.db, digest or self.digest, read=read, output=output))
        return output.getvalue()

    def approvals(self):
        store = Store(self.db, readonly=True)
        try:
            return distillation.approvals(store, self.path.stem)
        finally:
            store.close()

    def test_skip_and_eof_after_boundary_do_not_write(self):
        before = self.db.read_bytes()
        screen = self.review('1', '/补边界 布幕没试过', '/略过', '1', '/补边界 别写入')
        self.assertIn('未保存本次补注', screen)
        self.assertIn('当前拟写和补注未写入', screen)
        self.assertEqual(before, self.db.read_bytes())
        self.assertEqual(self.raw, self.path.read_bytes())

    def test_keep_only_edited_wording_and_bind_original_turn(self):
        screen = self.review('1', '/补边界 布幕没试过', '/留下')
        self.assertIn('已留下并认可第 1 轮', screen)
        self.assertIn(self.round['user'], screen)
        approved, unbound = self.approvals()
        self.assertFalse(unbound)
        (saved, records), = approved
        self.assertEqual({**self.card, 'scope': ['这两次白墙彩排', '布幕没试过']}, distillation.fields(saved))
        self.assertEqual(self.path.stem, saved['sources'][0]['independence_group'])
        self.assertFalse(saved['confirmation']['active'])
        self.assertEqual(1, distillation.draft_review_turn(saved, records, [self.round], self.digest))
        self.assertIsNone(distillation.draft_review_turn(saved, records, [self.round], 'wrong digest'))
        self.assertEqual([], distillation.readback_turns(saved, records, [self.round]))
        self.assertEqual(self.raw, self.path.read_bytes())

    def test_keep_existing_exact_draft_without_adding_source_or_new_card(self):
        store = Store(self.db)
        try:
            draft = store.add(**self.card, session=self.path.stem, sources=[dict(
                type='model_generated', verification='unverified', independence_group=self.path.stem)])
        finally:
            store.close()
        self.review('1', '/留下')
        approved, unbound = self.approvals()
        self.assertFalse(unbound)
        (saved, records), = approved
        self.assertEqual(draft['id'], saved['id'])
        self.assertEqual(draft['version'] + 1, saved['version'])
        self.assertEqual(1, len(saved['sources']))
        self.assertEqual(1, distillation.draft_review_turn(saved, records, [self.round], self.digest))
        self.assertIn('原拟写已有本场认可', self.review())

    def test_broken_or_changed_trace_does_not_write(self):
        before = self.db.read_bytes()
        with self.assertRaises(DojoError):
            self.review('1', '/留下', digest='0' * 64)

        def change_trace():
            self.path.write_bytes(self.raw + b' ')
            return '/留下'

        with self.assertRaises(DojoError):
            self.review('1', change_trace)
        self.assertEqual(before, self.db.read_bytes())

    def test_hidden_candidates_are_not_recovered_as_displayed_drafts(self):
        self.write_trace({**self.round, 'pending_snapshot': None}, self.end)
        self.assertIsNone(draft_review.review_hint(self.path, self.path.stem, self.db))
        self.assertIn('没有可复核的完整拟写', self.review())
