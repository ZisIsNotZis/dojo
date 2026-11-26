"""A takeover reader needs one thing the context view did not say: which URLs a
real search listed and nobody ever tried to read.

The rule pinned here: 'unopened' means no read_source receipt in this story at
all. A failed attempt is pending work with its own next step, so it is not
re-offered as untouched. Nothing here claims a URL is reachable, current, or
relevant -- only that this ledger holds no attempt against it.

These fixtures are ordinary (non-synthetic) throwaway libraries with hand-
written receipts; they pin the view's arithmetic, not a real conversation.
"""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from dojo.inquiry import Inquiry
from dojo.stories import reading_context


class UnopenedSearchSourcesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'db.sqlite'
        self.q = Inquiry(self.path, SimpleNamespace(config=SimpleNamespace(model='offline-fixture')),
                         synthetic=False)
        self.story = self.q.story

    def tearDown(self):
        self.q.close()
        self.tmp.cleanup()

    def search(self, urls):
        self.q.record('tool_result', {'action': {'kind': 'search', 'query': 'q'}, 'status': 'executed',
                                      'result': {'sources': [{'title': f'条目 {i}', 'url': u}
                                                             for i, u in enumerate(urls)]}})

    def read(self, url, text='正文'):
        return self.q.record('tool_result', {'action': {'kind': 'read_source', 'url': url},
                                             'status': 'executed', 'result': {'url': url, 'text': text}})

    def context(self):
        return reading_context(self.path, self.story)['story_coverage']

    def test_read_and_failed_urls_are_not_offered_as_unopened(self):
        manual = 'https://example.org/manual'
        self.read(manual)
        failed_url = 'https://example.org/broken'
        event = self.q.record('tool_result', {'action': {'kind': 'read_source', 'url': failed_url},
                                              'status': 'failed', 'error_kind': 'source_type'})
        self.search([manual + '#spec', failed_url, 'https://example.org/forum'])
        context = reading_context(self.path, self.story)
        self.assertEqual(['https://example.org/forum'], [item['url'] for item in
                         context['story_coverage']['unopened_search_sources']])
        self.assertNotIn('source_read_failures', context)
        failures = context['source_read_failures_without_visible_body']['items']
        self.assertEqual([(event, failed_url, 'source_type', 'recorded')], [
            (item['event'], item['read_url'], item['error_kind'], item['recorded_at_status'])
            for item in failures])

    def test_a_later_read_retires_the_candidate(self):
        self.search(['https://example.org/forum'])
        self.assertEqual(1, len(self.context()['unopened_search_sources']))
        self.read('https://example.org/forum')
        self.assertEqual([], self.context()['unopened_search_sources'])

    def test_cap_and_omission_count_are_reported(self):
        self.search([f'https://example.org/{i}' for i in range(7)])
        coverage = self.context()
        self.assertEqual(4, len(coverage['unopened_search_sources']))
        self.assertEqual(3, coverage['unopened_omitted'])

    def test_a_search_outside_the_recent_window_is_not_resurrected(self):
        self.search(['https://example.org/forum'])
        for _ in range(12):
            self.q.record('tool_result', {'action': {'kind': 'calculate', 'expression': '1+1'},
                                          'status': 'executed', 'result': {'value': 2}})
        coverage = self.context()
        self.assertEqual([], coverage['unopened_search_sources'])
        self.assertEqual(0, coverage['search_listings_considered'])

    def test_no_search_and_no_receipts_is_an_empty_block_not_a_claim(self):
        self.q.record('user', {'text': '只有用户陈述。'})
        coverage = self.context()
        self.assertEqual([], coverage['unopened_search_sources'])
        self.assertEqual(0, coverage['search_listings_considered'])
        self.assertEqual(0, coverage['visible_source_bodies'])

    def test_malformed_and_unusable_listings_are_ignored_without_crashing(self):
        self.q.record('tool_result', {'action': {'kind': 'search', 'query': 'q'}, 'status': 'executed',
                                      'result': {'sources': 'not-a-list'}})
        self.q.record('tool_result', {'action': {'kind': 'search', 'query': 'q'}, 'status': 'failed',
                                      'error_kind': 'tool_error',
                                      'result': {'sources': [{'title': 'x', 'url': 'https://example.org/a'}]}})
        self.search([])
        self.q.record('tool_result', {'action': {'kind': 'search', 'query': 'q'}, 'status': 'executed',
                                      'result': {'sources': [{'title': '', 'url': 'https://example.org/b'},
                                                             {'title': 'http', 'url': 'http://insecure.example'},
                                                             {'title': 'ok', 'url': 'https://example.org/c'}]}})
        self.assertEqual(['https://example.org/c'],
                         [item['url'] for item in self.context()['unopened_search_sources']])

    def test_another_storys_read_does_not_retire_this_storys_candidate(self):
        self.search(['https://example.org/forum'])
        other = Inquiry(self.path, SimpleNamespace(config=SimpleNamespace(model='offline-fixture')),
                        synthetic=False)
        try:
            other.record('tool_result', {'action': {'kind': 'read_source', 'url': 'https://example.org/forum'},
                                         'status': 'executed',
                                         'result': {'url': 'https://example.org/forum', 'text': '论坛'}})
        finally:
            other.close()
        self.assertEqual(['https://example.org/forum'],
                         [item['url'] for item in self.context()['unopened_search_sources']])

    def test_the_reading_keeps_the_three_limits_apart(self):
        coverage = self.context()
        reading = reading_context(self.path, self.story)['story_coverage_reading']
        # absence is not a claim about the URL, and the record time is not the source time
        self.assertIn('未被列出不表示检索没返回过它', reading)
        self.assertIn('不说明外部正文也旧', reading)
        # a fresh story still has its start row, so the time is known
        self.assertEqual('recorded', coverage['latest_record_at_status'])

    def test_an_unstored_time_is_missing_not_invented(self):
        import sqlite3
        con = sqlite3.connect(self.path)
        con.execute('UPDATE inquiry_events SET at=NULL')
        con.commit()
        con.close()
        coverage = self.context()
        self.assertEqual('missing', coverage['latest_record_at_status'])
        self.assertIsNone(coverage['latest_record_at'])
        self.assertIsNotNone(coverage['latest_record_event'])

    def test_the_event_count_is_not_a_read_count(self):
        # Found on a real ledger: a story with 19 decoded events, 2 tool receipts
        # and 0 readable bodies. The old key was named 'read_events_in_this_view'
        # while counting every decoded event, so a taker could read '19 reads'.
        self.q.record('user', {'text': '只有用户陈述，没有任何读取。'})
        self.q.record('reflection', {'reflection': {'answer': '模型答复也不算核验。'}})
        coverage = self.context()
        self.assertNotIn('read_events_in_this_view', coverage)
        self.assertEqual([], coverage['unopened_search_sources'])
        self.assertEqual(0, coverage['visible_source_bodies'])
        self.assertGreater(coverage['decoded_events_in_this_view'],
                           coverage['tool_receipts_in_this_view'])

    def test_the_view_is_read_only(self):
        self.search(['https://example.org/forum'])
        before = json.dumps(self.context(), ensure_ascii=False)
        self.assertEqual(before, json.dumps(self.context(), ensure_ascii=False))
        self.assertEqual(before, json.dumps(self.context(), ensure_ascii=False))
        stamp = self.path.read_bytes()
        reading_context(self.path, self.story)
        self.assertEqual(stamp, self.path.read_bytes())


if __name__ == '__main__':
    unittest.main()
