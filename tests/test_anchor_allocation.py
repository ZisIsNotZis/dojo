import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from dojo.anchors import anchor_catalog
from dojo.inquiry import Inquiry
from dojo.progress_checks import check
from tests.test_knowledge import Client, proposal


class AnchorAllocationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.q = Inquiry(Path(self.tmp.name) / 'db', Client(), synthetic=True)
        action = dict(kind='check_progress', states={'W': 'INPUT_ONLY_SENTINEL', 'D': 'Declared goal'},
                      initial='W', goals=['D'], transitions=[dict(source='W', target='D', label='assumed event')],
                      assumptions=['Hypothetical transitions only'], prediction='A finite graph certificate')
        self.events = []
        for _ in range(8):
            self.events.append(self.q.record('tool_result', {'action': action, 'status': 'executed', 'result': check(action)}))
        self.user = self.q.record('user', {'text': 'Preserve the actual comparison', 'synthetic': True})
        self.events.append(self.user)

    def tearDown(self):
        self.q.close()
        self.tmp.cleanup()

    def test_old_receipts_cannot_exhaust_handles_before_recent_sources(self):
        anchors = anchor_catalog(self.q.knowledge, [self.q.knowledge.source(e) for e in self.events])
        self.assertEqual(set(self.events), {a['source_event'] for a in anchors})
        self.assertEqual(self.events, [a['source_event'] for a in anchors[:len(self.events)]])
        self.assertEqual(list(range(1, len(anchors)+1)), [a['anchor'] for a in anchors])
        self.assertLessEqual(len(anchors), 64)
        self.assertLessEqual(sum(len(a['quote']) for a in anchors), 24000)
        self.assertFalse(any('INPUT_ONLY_SENTINEL' in a['quote'] for a in anchors))

    def test_distillation_can_ground_a_proposal_in_the_late_actual_receipt(self):
        for e in self.events:
            self.q.visible_source_text[e] = self.q.knowledge.source(e)['text']
        self.q.user_sources[self.user] = 'Preserve the actual comparison'
        late = self.events[-2]

        def scribe(messages):
            packet = json.loads(messages[-1]['content'])
            anchor = next(a for a in packet['anchors'] if a['source_event'] == late)
            p = proposal('The supplied finite graph reaches its declared goal', late, 'placeholder')
            p['premises'] = [{'anchor': anchor['anchor'], 'role': 'evidence'}]
            return {'intent': dict(goals=[], motivations=[], inferred_needs=[], unresolved=[]), 'knowledge': [p]}

        result = self.q.distill(SimpleNamespace(complete=scribe))
        self.assertEqual('distilled', result['status'])
        saved = self.q.knowledge.source(result['proposal_events'][0])['proposal']
        self.assertEqual(late, saved['premises'][0]['event'])
        self.assertIn(saved['premises'][0]['quote'], self.q.knowledge.observed_tool_text(late))
        attempt = json.loads(self.q.db.execute("SELECT payload FROM inquiry_events WHERE kind='distill_request_started'").fetchone()[0])
        self.assertEqual(self.events, attempt['source_events'])
        self.assertEqual([], attempt['unanchored_source_events'])

    def test_character_budget_does_not_prevent_a_later_short_valid_quote(self):
        large = self.q.record('user', {'text': 'x'*1000, 'synthetic': True})
        anchors = anchor_catalog(self.q.knowledge, [self.q.knowledge.source(large), self.q.knowledge.source(self.user)], max_characters=40)
        self.assertEqual([self.user], [a['source_event'] for a in anchors])
        self.assertLessEqual(sum(len(a['quote']) for a in anchors), 40)


if __name__ == '__main__':
    unittest.main()
