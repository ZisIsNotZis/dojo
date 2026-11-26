"""Offline, allowlisted response-shape diagnostics; never an extra model request."""

import io
import json
import tempfile
import unittest
import urllib.error
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock, patch

from dojo.discuss import run_discuss
from dojo.live import LiveConfig, LiveError, OpenAICompatibleClient
from dojo.storage import Store


SECRET = "SHAPE-PRIVATE-SENTINEL"


def response_bytes(message, finish_reason="stop", **extra):
    return json.dumps({
        "choices": [{"message": message, "finish_reason": finish_reason}],
        **extra,
    }, ensure_ascii=False).encode("utf-8")


def stream(body):
    return io.BytesIO(body)


def make_client():
    return OpenAICompatibleClient(
        LiveConfig("http://127.0.0.1:1/v1/chat/completions", "fixture", SECRET),
        allowed_extra_keys=frozenset({"user_stance", "person_updates"}),
    )


class ResponseShapeTests(unittest.TestCase):
    def test_only_allowlisted_structure_is_recorded_not_response_values_or_unknown_keys(self):
        content = json.dumps({"answer": SECRET, "candidate": None, "user_stance": "neutral"})
        value = {
            "id": SECRET, "model": SECRET, "url": SECRET,
            "error": {"message": SECRET}, SECRET: SECRET,
            "choices": [{
                "message": {
                    "role": SECRET, "content": content, "reasoning_content": SECRET,
                    "tool_calls": [{"function": {"arguments": SECRET}}],
                    "refusal": SECRET, SECRET: SECRET,
                },
                "finish_reason": SECRET, SECRET: SECRET,
            }],
        }
        client = make_client()
        opener = Mock()
        opener.open.return_value = stream(json.dumps(value).encode())
        with patch("dojo.live.urllib.request.build_opener", return_value=opener):
            result = client.complete([{"role": "user", "content": SECRET}])
        shape = client.last_response_shape
        self.assertNotIn(SECRET, json.dumps(shape))
        self.assertEqual(["choices", "error"], shape["top_keys"])
        self.assertEqual(4, shape["top_unknown_keys_count"])
        self.assertEqual(["message", "finish_reason"], shape["choice_keys"])
        self.assertEqual(1, shape["choice_unknown_keys_count"])
        self.assertEqual(["role", "content", "reasoning_content", "tool_calls", "refusal"], shape["message_keys"])
        self.assertEqual(1, shape["message_unknown_keys_count"])
        self.assertEqual("string", shape["content_type"])
        self.assertEqual(len(content), shape["content_chars"])
        self.assertEqual(len(SECRET), shape["reasoning_content_chars"])
        self.assertTrue(shape["tool_calls_present"])
        self.assertEqual("other", shape["finish_reason"])
        self.assertEqual(SECRET, result["answer"], "Existing business completion semantics are unchanged")
        self.assertNotIn("response_shape", result, "Metadata must not enter model schema validation")
        self.assertEqual(1, opener.open.call_count)

    def test_empty_schema_and_truncated_responses_keep_shape_without_relaxing_validation(self):
        cases = [
            ({"reasoning_content": SECRET}, "stop", "empty_content", "missing", None),
            ({"content": None}, "stop", "empty_content", "null", None),
            ({"content": [SECRET]}, "stop", "empty_content", "array", None),
            ({"content": {SECRET: SECRET}}, "stop", "empty_content", "object", None),
            ({"content": "  "}, "stop", "empty_content", "string", 2),
            ({"content": '{"answer":"x","candidate":null,"extra":1}'}, "stop", "schema_violation", "string", 41),
            ({"content": "{"}, "length", "truncated", "string", 1),
        ]
        client = make_client()
        for message, finish, kind, content_type, count in cases:
            with self.subTest(kind=kind, content_type=content_type):
                opener = Mock()
                opener.open.return_value = stream(response_bytes(message, finish))
                with patch("dojo.live.urllib.request.build_opener", return_value=opener):
                    with self.assertRaises(LiveError) as caught:
                        client.complete([{"role": "user", "content": "fixture"}])
                self.assertEqual(kind, caught.exception.kind)
                shape = client.last_response_shape
                self.assertEqual(content_type, shape["content_type"])
                self.assertEqual(count, shape["content_chars"])
                self.assertEqual(finish, shape["finish_reason"])
                self.assertNotIn(SECRET, json.dumps(shape))
                self.assertEqual(1, opener.open.call_count)
                if isinstance(message.get('content'),str):
                    self.assertEqual(sum(not char.isspace() for char in message['content']),shape['content_non_whitespace_chars'])

    def test_text_transport_preserves_strict_json_validation_without_automatic_retry(self):
        client=OpenAICompatibleClient(LiveConfig('http://127.0.0.1:1/v1/chat/completions','fixture',SECRET),json_output=False)
        opener=Mock()
        opener.open.side_effect=[stream(response_bytes({'content':'```json\n{"answer":"x","candidate":null}\n```'})),
            stream(response_bytes({'content':'{"answer":"x","candidate":null}'}))]
        with patch('dojo.live.urllib.request.build_opener',return_value=opener):
            with self.assertRaises(LiveError) as caught:client.complete([])
            self.assertEqual('not_json',caught.exception.kind)
            self.assertEqual(1,opener.open.call_count)
            self.assertEqual({'type':'text'},json.loads(opener.open.call_args.args[0].data)['response_format'])
            self.assertEqual('x',client.complete([])['answer'])
        self.assertEqual(2,opener.open.call_count)

    def test_shape_resets_before_request_budget_parse_and_transport_failures(self):
        client = make_client()
        opener = Mock()
        opener.open.side_effect = [
            stream(response_bytes({"content": '{"answer":"ok","candidate":null}'})),
            stream(b"not-json"),
            urllib.error.URLError("offline failure"),
        ]
        with patch("dojo.live.urllib.request.build_opener", return_value=opener):
            self.assertIsNone(client.last_response_shape)
            client.complete([])
            previous = client.last_response_shape
            self.assertIsNotNone(previous)
            client.max_request_chars = 0
            with self.assertRaises(LiveError):
                client.complete([])
            self.assertIsNone(client.last_response_shape)
            client.max_request_chars = 12_000
            for _ in range(2):
                with self.assertRaises(LiveError):
                    client.complete([])
                self.assertIsNone(client.last_response_shape)
            self.assertEqual("string", previous["content_type"])
            self.assertEqual(3, opener.open.call_count, "No request on budget failure and no adapter retry")

    def test_attempt_trace_matches_each_empty_schema_and_valid_response(self):
        invalid = '{"answer":"bad","candidate":null,"extra":true}'
        valid = json.dumps({"answer": "继续讨论。", "candidate": None, "user_stance": "neutral"})
        bodies = [
            response_bytes({"content": "", "reasoning_content": SECRET}),
            response_bytes({"content": invalid}),
            response_bytes({"content": valid}),
        ]
        client = make_client()
        opener = Mock()
        opener.open.side_effect = [stream(body) for body in bodies]
        with tempfile.TemporaryDirectory() as temp, closing(Store(Path(temp) / "dojo.sqlite3")) as store:
            lines = iter(["fixture user input"])
            with patch("dojo.live.urllib.request.build_opener", return_value=opener):
                code = run_discuss(
                    store, client=client, environ={}, no_profile=True,
                    read_line=lambda _prompt: next(lines, None), output=io.StringIO(),
                )
            rows = [json.loads(line) for line in next((Path(temp) / "sessions").glob("*.jsonl")).read_text(encoding="utf-8").splitlines()]
            attempts = rows[0]["attempts"]
            self.assertEqual(0, code)
            self.assertEqual(3, len(attempts))
            self.assertEqual([0, len(invalid), len(valid)], [item["response_shape"]["content_chars"] for item in attempts])
            self.assertEqual([len(SECRET), None, None], [item["response_shape"]["reasoning_content_chars"] for item in attempts])
            self.assertEqual(["empty_content", "schema_violation"], [item["error"]["kind"] for item in attempts[:2]])
            self.assertNotIn("error", attempts[-1])
            self.assertNotIn(SECRET, json.dumps([item["response_shape"] for item in attempts]))
            self.assertEqual(3, opener.open.call_count, "Existing invalid-output retry budget is unchanged")

    def test_transport_attempts_do_not_inherit_a_previous_success_shape(self):
        valid = json.dumps({"answer": "继续讨论。", "candidate": None, "user_stance": "neutral"})
        client = make_client()
        opener = Mock()
        opener.open.side_effect = [
            stream(response_bytes({"content": valid})),
            urllib.error.URLError("offline failure"),
            urllib.error.URLError("offline failure"),
        ]
        with tempfile.TemporaryDirectory() as temp, closing(Store(Path(temp) / "dojo.sqlite3")) as store:
            lines = iter(["first", "second"])
            with patch("dojo.live.urllib.request.build_opener", return_value=opener):
                code = run_discuss(
                    store, client=client, environ={}, no_profile=True,
                    read_line=lambda _prompt: next(lines, None), output=io.StringIO(),
                )
            rows = [json.loads(line) for line in next((Path(temp) / "sessions").glob("*.jsonl")).read_text(encoding="utf-8").splitlines()]
            self.assertEqual(2, code)
            self.assertEqual(len(valid), rows[0]["attempts"][0]["response_shape"]["content_chars"])
            self.assertEqual([None, None], [item["response_shape"] for item in rows[1]["attempts"]])
            self.assertEqual(3, opener.open.call_count)


if __name__ == "__main__":
    unittest.main()
