import unittest
from dojo.stories import _resume_tool_receipts


def event(n, kind='calculate', **fields):
    return {'event': n, 'payload': {'action': {'kind': kind}, 'status': 'executed', **fields}}


def source(n, text='正文', url=None):
    url = url or f'https://example.org/{n}'
    return event(n, action={'kind': 'read_source', 'url': url}, result={'url': url, 'text': text})


def selected(*events):
    return [e['event'] for e in _resume_tool_receipts(events)]


class ReceiptSelection(unittest.TestCase):
    def test_four_distinct_sources_respect_cap(self):
        self.assertEqual([4, 3, 2], selected(*(source(i) for i in range(1, 5)), event(5)))

    def test_duplicates_do_not_come_back_in_fill(self):
        first = source(1)
        duplicate = source(4, url='https://example.org/1')
        self.assertEqual([5, 4, 3], selected(first, event(3, 'search'), duplicate, source(5)))
        self.assertEqual([4], selected(first, duplicate))
        self.assertEqual([4, 1], selected(first, source(4, text='同址的新正文', url='https://example.org/1')))

    def test_failed_and_malformed_reads_do_not_displace_real_receipts(self):
        failed = source(3)
        failed['payload']['status'] = 'failed'
        missing_body = source(4, text=None)
        mismatched = source(5)
        mismatched['payload']['result']['url'] = 'https://example.org/other'
        bad_result = source(6)
        bad_result['payload']['result'] = ['not a receipt body']
        self.assertEqual([7, 2, 1], selected(source(1), event(2, 'search'), failed, missing_body, mismatched, bad_result, event(7)))

    def test_cpu_and_search_keep_ordinary_recency_without_source_bodies(self):
        self.assertEqual([4, 3, 2], selected(event(1), event(2, 'search'), event(3, 'experiment'), event(4)))

    def test_rescue_window_is_bounded(self):
        self.assertEqual([13, 12, 11], selected(source(1), *(event(i) for i in range(2,14))))


class StoryScopedOverflow(unittest.TestCase):
    def test_normal_turns_only_keep_three_of_four_and_hide_foreign_read(self):
        import json
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        from dojo.inquiry import Inquiry
        from dojo.stories import reading_context

        urls = [f'https://example.org/source-{i}' for i in range(5)]

        class Host:
            config = SimpleNamespace(model='offline-fixture', api_key='offline-fixture')

            def __init__(self, indexes):
                self.actions = iter([dict(kind='search', query='来源', prediction='列出公开正文'),
                    *[dict(kind='read_source', url=urls[i], prediction='看正文') for i in indexes], None])

            def complete(self, messages):
                return dict(answer='合成读取完成', understanding='', hypotheses=[], unknowns=[], revision='', action=next(self.actions))

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'story.sqlite3'

            def turn(indexes, story=None):
                i = Inquiry(path, Host(indexes), story=story, synthetic=True,
                    search_fn=lambda *a, **k: [dict(url=urls[j], title='合成条目') for j in indexes],
                    source_fn=lambda url: dict(url=url, text='合成正文：'+url, scope='不代表独立复现'))
                try:
                    i.turn('读取合成外部材料。')
                    return i.story
                finally:
                    i.close()

            same = turn([0,1,2])
            self.assertEqual(same, turn([3], same))
            foreign = turn([4])
            self.assertNotEqual(same, foreign)
            for story, expected in [(same, set(urls[1:4])), (foreign, {urls[4]})]:
                receipts = [json.loads(s['text']) for s in reading_context(path, story, synthetic=True)['sources']
                            if s['kind']=='tool_result']
                self.assertEqual(expected, {r['result']['url'] for r in receipts if r['action']['kind']=='read_source'})


if __name__ == '__main__':
    unittest.main()
