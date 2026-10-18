import io
import json
import socket
import unittest
import urllib.error

from dojo.search import (
    DEFAULT_COUNT,
    REQUEST_TIMEOUT_SECONDS,
    SEARCH_ENDPOINT,
    SearchError,
    search,
)


RESULT = {
    "rerank_score": 0.91,
    "title": "Example result",
    "url": "https://example.test/article",
    "snippet": "Short source excerpt",
    "summary": "Source summary",
    "content": "Full source content",
}


class FakeResponse:
    def __init__(self, value):
        self.value = value

    def read(self):
        return self.value

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class FakeOpener:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.requests = []
        self.timeouts = []

    def open(self, request, timeout):
        self.requests.append(request)
        self.timeouts.append(timeout)
        if self.error is not None:
            raise self.error
        return FakeResponse(json.dumps(self.response, ensure_ascii=False).encode("utf-8"))


class SearchTests(unittest.TestCase):
    def test_search_posts_unmodified_query_with_defaults_and_returns_results(self):
        query = "site:example.test lang:zh after:2024-01-01 自行车联动刹车"
        opener = FakeOpener({"results": [RESULT]})

        results = search(query, environ={"DEEPSEEK_API_KEY": "secret"}, opener=opener)

        self.assertEqual([RESULT], results)
        request = opener.requests[0]
        self.assertEqual(SEARCH_ENDPOINT, request.full_url)
        self.assertEqual("POST", request.get_method())
        self.assertEqual("Bearer secret", request.get_header("Authorization"))
        self.assertEqual("application/json", request.get_header("Content-type"))
        self.assertEqual(
            {"query": query, "count": DEFAULT_COUNT, "need_content": False},
            json.loads(request.data.decode("utf-8")),
        )
        self.assertEqual([REQUEST_TIMEOUT_SECONDS], opener.timeouts)

    def test_search_returns_empty_results(self):
        opener = FakeOpener({"results": []})
        self.assertEqual([], search("no matches", environ={"DEEPSEEK_API_KEY": "key"}, opener=opener))

    def test_search_without_key_is_classified_chinese_error_without_http_call(self):
        opener = FakeOpener({"results": []})

        with self.assertRaises(SearchError) as raised:
            search("question", environ={}, opener=opener)

        self.assertEqual("no_key", raised.exception.kind)
        self.assertIn("搜索不可用", raised.exception.user_message)
        self.assertEqual([], opener.requests)

    def test_search_timeout_is_classified_chinese_error(self):
        opener = FakeOpener(error=socket.timeout("slow"))

        with self.assertRaises(SearchError) as raised:
            search("question", environ={"DEEPSEEK_API_KEY": "key"}, opener=opener)

        self.assertEqual("timeout", raised.exception.kind)
        self.assertIn("超时", raised.exception.user_message)

    def test_search_http_error_keeps_status_classification_and_chinese_message(self):
        http_error = urllib.error.HTTPError(SEARCH_ENDPOINT, 429, "limited", {}, io.BytesIO(b""))
        opener = FakeOpener(error=http_error)

        with self.assertRaises(SearchError) as raised:
            search("question", environ={"DEEPSEEK_API_KEY": "key"}, opener=opener)

        self.assertEqual("http_429", raised.exception.kind)
        self.assertIn("HTTP 429", raised.exception.user_message)
        self.assertIn("无法核实", raised.exception.user_message)

    def test_search_malformed_response_is_classified(self):
        opener = FakeOpener({"results": [{"title": "Missing URL"}]})

        with self.assertRaises(SearchError) as raised:
            search("question", environ={"DEEPSEEK_API_KEY": "key"}, opener=opener)

        self.assertEqual("bad_response", raised.exception.kind)
        self.assertIn("无法识别", raised.exception.user_message)

    def test_search_validates_query_count_and_need_content(self):
        for query in ("", "  ", "x" * 129):
            with self.subTest(query=query), self.assertRaises(SearchError) as raised:
                search(query, environ={"DEEPSEEK_API_KEY": "key"}, opener=FakeOpener())
            self.assertEqual("bad_response", raised.exception.kind)
            self.assertIn("搜索词", raised.exception.user_message)
        for kwargs in ({"count": 0}, {"count": 51}, {"count": True}, {"need_content": 1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(SearchError) as raised:
                search("question", environ={"DEEPSEEK_API_KEY": "key"}, opener=FakeOpener(), **kwargs)
            self.assertEqual("bad_response", raised.exception.kind)


if __name__ == "__main__":
    unittest.main()
