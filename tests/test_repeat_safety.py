"""Two decisions, one rule: a repeat must not read as a second action.

RFC 9110 section 9.2.2 defines idempotency by *intended effect*, not by whether a
server happens to log the request twice, and it calls it a riskier approach when a
client retries only because the connection died before the response was read.

Both halves are tested here against the real entry points: the discussion loop over
a real socket at one end, and the store's version ledger at the other.
"""
import http.client
import io
import json
import socket
import sqlite3
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from dojo.discuss import run_discuss
from dojo.live import LiveConfig, LiveError, OpenAICompatibleClient
from dojo.storage import Store

PARTIAL = b'{"choices":[{"message":{"content":"half an answer'


class _Cut(BaseHTTPRequestHandler):
    """Answer 200 with a Content-Length, then send fewer bytes and hang up."""
    protocol_version = "HTTP/1.1"
    seen = 0

    def log_message(self, *args):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        type(self).seen += 1
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(PARTIAL) + 4096))
        self.end_headers()
        self.wfile.write(PARTIAL)
        self.wfile.flush()
        self.close_connection = True
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.connection.close()


class IncompleteResponseIsNotARetry(unittest.TestCase):
    """A cut body is a transport fact about reading the answer, not a bad answer."""

    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Cut)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.port = cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def client(self):
        return OpenAICompatibleClient(LiveConfig(
            f"http://127.0.0.1:{self.port}/v1/chat/completions", "stub-model", None, 5))

    def test_a_short_body_is_named_for_the_framing_not_for_the_model(self):
        """`not_json` would blame the model; the bytes never all arrived."""
        _Cut.seen = 0
        with self.assertRaises(LiveError) as caught:
            self.client().complete([{"role": "user", "content": "hi"}])
        self.assertEqual("incomplete_response", caught.exception.kind)
        self.assertEqual(1, _Cut.seen)
        # A cut body is not kept: a partial answer must never be shown as the answer.
        self.assertFalse(caught.exception.raw_response)

    def test_one_user_turn_sends_exactly_one_request(self):
        """The published behaviour sent three, and blamed the model for it."""
        _Cut.seen = 0
        store = Store(str(Path(tempfile.mkdtemp()) / "gate.sqlite3"))
        lines = iter(["提出一个想法"])

        def read_line(_prompt):
            try:
                return next(lines)
            except StopIteration:
                raise EOFError

        output = io.StringIO()
        run_discuss(store, client=self.client(), read_line=read_line, output=output)
        self.assertEqual(1, _Cut.seen, "a cut response must not be re-sent")
        self.assertEqual([], store.list_candidates())
        said = output.getvalue()
        self.assertIn("没有据此重发请求", said)
        # The old wording claimed the model returned a malformed format. It did not.
        self.assertNotIn("格式不合法", said)


class OversizeBodyIsNotReportedAsIncomplete(unittest.TestCase):
    """The size bound reads one byte past the cap on purpose.

    So an oversized body also arrives short of its Content-Length, and a naive
    completeness check calls it an interruption. Sending the reader after a
    network fault when the answer was simply too big is the same class of
    misdiagnosis this slice set out to remove, so it is pinned here rather than
    left to whichever existing test happens to cover it.
    """

    def test_the_size_bound_is_decided_before_completeness(self):
        class Oversized:
            headers = {"Content-Length": "900"}

            def read(self, _n):
                return b"x" * 10

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        from unittest.mock import Mock, patch
        client = OpenAICompatibleClient(LiveConfig(
            "http://127.0.0.1:1/v1/chat/completions", "m", None, 5))
        client.max_response_bytes = 5
        opener = Mock()
        opener.open.return_value = Oversized()
        with patch("dojo.live.urllib.request.build_opener", return_value=opener):
            with self.assertRaises(LiveError) as caught:
                client.complete([{"role": "user", "content": "hi"}])
        self.assertNotEqual("incomplete_response", caught.exception.kind)
        self.assertIn("exceeded", str(caught.exception))


class ARepeatIsNotASecondAction(unittest.TestCase):
    """The same request twice must leave the version where it was."""

    def setUp(self):
        self.store = Store(str(Path(tempfile.mkdtemp()) / "lib.sqlite3"))
        self.store.add("重复请求是否同一效果", "abstract_idea", candidate_id="c-one",
                       scope=["探针"])

    def test_an_identical_confirm_does_not_move_the_version(self):
        first = self.store.confirm("c-one", "worth discussing")
        after_first = first["version"]
        again = self.store.confirm("c-one", "worth discussing")
        self.assertEqual(after_first, again["version"])
        self.assertEqual(self.store.show("c-one")["candidate"]["version"], after_first)
        # No second snapshot either: the stored wording never changed.
        self.assertEqual([after_first],
                         [v["version"] for v in self.store.history("c-one")["versions"]][-1:])
        self.assertEqual(2, len(self.store.history("c-one")["versions"]))

    def test_a_repeat_leaves_a_row_that_says_it_was_a_repeat(self):
        """Logging the repeat is allowed; making it indistinguishable is not."""
        self.store.confirm("c-one", "worth discussing")
        self.store.confirm("c-one", "worth discussing")
        events = self.store.history("c-one")["events"]
        repeat = events[-1]
        self.assertEqual("confirm_discussable.repeat", repeat["event"])
        details = repeat["details"]
        self.assertEqual("unchanged", details["effect"])
        earlier = [e for e in events if e["event"] == "confirm_discussable"]
        self.assertEqual(1, len(earlier))
        # The pointer must land on that one original row, not merely be an integer.
        row = self.store.connection.execute(
            "SELECT event FROM events WHERE seq=?", (details["repeat_of"],)).fetchone()
        self.assertEqual("confirm_discussable", row["event"])

    def test_the_pipeline_mark_stays_valid_across_a_repeat(self):
        """`pipeline_marks` compares versions, so a bumped version fakes new work."""
        self.store.confirm("c-one", "worth discussing")
        version = self.store.show("c-one")["candidate"]["version"]
        self.store.connection.execute(
            "INSERT INTO pipeline_marks(session,pass_name,candidate_id,version,created_at)"
            " VALUES('s1','distill','c-one',?,'2026-11-27T00:00:00Z')", (version,))
        self.store.connection.commit()
        self.store.confirm("c-one", "worth discussing")
        self.assertEqual(version, self.store.show("c-one")["candidate"]["version"])

    def test_a_real_second_action_still_writes(self):
        """The guard must not swallow what the user actually said the second time."""
        self.store.confirm("c-one", "worth discussing")
        version = self.store.show("c-one")["candidate"]["version"]
        self.store.confirm("c-one", "a different basis")
        self.assertGreater(self.store.show("c-one")["candidate"]["version"], version)

    def test_two_different_revisions_are_two_versions(self):
        self.store.revise("c-one", "第一次改", "补条件")
        middle = self.store.show("c-one")["candidate"]["version"]
        self.store.revise("c-one", "第二次改", "再补条件")
        self.assertGreater(self.store.show("c-one")["candidate"]["version"], middle)

    def test_a_repeated_challenge_does_not_inflate_the_version(self):
        self.store.challenge("c-one", "未必有益")
        version = self.store.show("c-one")["candidate"]["version"]
        self.store.challenge("c-one", "未必有益")
        self.assertEqual(version, self.store.show("c-one")["candidate"]["version"])


if __name__ == "__main__":
    unittest.main()
