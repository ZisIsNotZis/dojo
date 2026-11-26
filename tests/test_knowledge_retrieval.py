from pathlib import Path
import tempfile
import unittest

from dojo.inquiry import Inquiry
from tests.test_knowledge import Client, proposal


class KnowledgeRetrievalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.q = Inquiry(Path(self.tmp.name) / 'db', Client(), synthetic=True)

    def tearDown(self):
        self.q.close()
        self.tmp.cleanup()

    def add(self, statement, quote, conditions=None):
        source = self.q.record('user', {'text': quote, 'synthetic': True})
        p = proposal(statement, source, quote)
        if conditions is not None:
            p['conditions'] = conditions
        return self.q.knowledge.accept(self.q.run, p, {source}, synthetic=True)

    def test_long_off_topic_provenance_does_not_evict_topic_claim(self):
        target = self.add('queue closure does not certify review', 'one reported process')
        for i in range(3):
            self.add('unrelated observation number ' + str(i),
                     'queue closure review ownership calendar deadline backlog evidence')
        matches = self.q.retrieve_knowledge('queue review ownership calendar deadline backlog evidence')
        self.assertEqual(target, matches[0]['event'])
        self.assertEqual('queue closure does not certify review', matches[0]['proposal']['statement'])

    def test_applicability_condition_is_searchable_before_incidental_quote(self):
        target = self.add('a bounded process certificate', 'reported finite model',
                          ['applicable to calendar transitions'])
        for i in range(3):
            self.add('another result ' + str(i), 'calendar transitions mentioned in background only')
        self.assertEqual(target, self.q.retrieve_knowledge('calendar transitions')[0]['event'])

    def test_provenance_only_lookup_keeps_complete_source_packet(self):
        event = self.add('a limited observation', 'UNIQUE_ARCHIVE_LOCATOR')
        found = self.q.retrieve_knowledge('UNIQUE_ARCHIVE_LOCATOR')
        self.assertEqual([event], [m['event'] for m in found])
        self.assertIn('UNIQUE_ARCHIVE_LOCATOR', str(found[0]['review_packet']))
        self.assertEqual('model_proposal_not_certified', found[0]['epistemic_status'])


if __name__ == '__main__':
    unittest.main()
