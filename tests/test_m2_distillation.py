import tempfile
import unittest
from pathlib import Path

from dojo.distillation import _input, fields
from dojo.pipeline import distill
from dojo.storage import Store


class M2DistillationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = Store(Path(tmp.name) / 'dojo.sqlite3')
        self.addCleanup(self.store.close)

    def test_same_second_restore_uses_the_actual_approval_turn(self):
        store = self.store
        first = store.add('试试桌面卡。', 'application', session='session')
        middle = store.revise(first['id'], '两次彩排观察。', '记录不同内容')
        final = store.revise(first['id'], first['statement'], '恢复原句')
        self.assertEqual(fields(first), fields(final))
        when = '2026-11-28T10:00:00+00:00'
        rounds = []
        for index, card in enumerate((first, middle, final)):
            rounds.extend(({'seq': 2 * index + 1, 'user': f'原话 {index + 1}'},
                           {'seq': 2 * index + 2, 'user': '/认可', 'stance': 'accept', 'candidate': fields(card),
                            'approval': {'id': card['id'], 'version': card['version'], 'agreed_at': when}}))
        result = _input(final, [{'agreed_at': when}], rounds)
        self.assertEqual(6, result['approval_seq'])
        self.assertEqual({'seq': 5, 'text': '原话 3'}, result['turns'][-1])
        self.assertIsNone(_input(final, [{'agreed_at': when}], rounds[:-1]))

    def test_exact_echo_is_an_approval_but_not_a_new_claim_or_source(self):
        store = self.store
        old = store.add('把交接步骤写在桌面卡上。', 'application', session='old')
        store.record_acceptance(old['id'], 'echo', path='discuss_conclusion')
        item, = distill(store, 'echo')['cards']
        self.assertEqual('approved', item['approval_status'])
        self.assertEqual(('duplicate', old['id'], 1), (item['verdict'], item['of'], item['of_version']))
        self.assertEqual(old, store.show(old['id'])['candidate'])

    def test_missing_approval_snapshot_cannot_bind_to_new_scope(self):
        store = self.store
        card = store.add('把交接步骤写在桌面卡上。', 'application', session='session', scope=['仅彩排'])
        event = store.record_acceptance(card['id'], 'session', path='discuss_conclusion')
        store.revise(card['id'], card['statement'], '未认可的范围改写', scope=['适用所有场次'])
        store.connection.execute('DELETE FROM snapshots WHERE candidate_id=? AND version=1', (card['id'],))
        report = distill(store, 'session')
        self.assertEqual([event], report['unbound_approval_events'])
        item, = report['cards']
        self.assertEqual('unproven', item['approval_status'])
        self.assertIsNone(item['classification'])
