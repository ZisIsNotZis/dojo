"""Two decisions, one rule: a repeat must not read as a second action.

RFC 9110 section 9.2.2 defines idempotency by *intended effect*, not by whether a
server happens to log the request twice, and it calls it a riskier approach when a
client retries only because the connection died before the response was read.

Both halves are tested here against the real entry points: the discussion loop over
a real socket at one end, and the store's version ledger at the other.
"""
import ast
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

    # --- same effect is not the same request -----------------------------------
    # Merging those two questions is what filed a second argument under the first:
    # the card reached the same wording either way, so "state unchanged" was read
    # as "the same request again". Both halves are asserted, because a fix that
    # kept every row distinct by bumping the version would pass the first alone.

    def test_two_reasons_for_one_sentence_are_two_rows(self):
        self.store.revise("c-one", "同一句话", "移动端同伴看不见活动灯")
        self.store.revise("c-one", "同一句话", "触屏读屏需要一个可读状态")
        events = self.store.history("c-one")["events"]
        revisals = [e for e in events if e["event"].startswith("revise")]
        self.assertEqual(
            ["移动端同伴看不见活动灯", "触屏读屏需要一个可读状态"],
            [e["details"].get("reason") for e in revisals])
        # Neither is a replay of the other, so the second carries no pointer back.
        self.assertNotIn("repeat_of", revisals[-1]["details"])
        # The wording never changed, so the version did not move either: add=1,
        # first revise=2, and the second reason leaves it at 2.
        self.assertEqual(2, self.store.show("c-one")["candidate"]["version"])

    def test_the_same_reason_twice_is_still_a_replay(self):
        """The distinction must not turn into 'every revise is new'."""
        self.store.revise("c-one", "同一句话", "移动端同伴看不见活动灯")
        self.store.revise("c-one", "同一句话", "移动端同伴看不见活动灯")
        events = self.store.history("c-one")["events"]
        self.assertEqual("revise.repeat", events[-1]["event"])
        # One real revise row, one replay row -- not two real ones.
        self.assertEqual(1, len([e for e in events if e["event"] == "revise"]))
        # ... and the pointer names the row for that same reason, not any revise.
        row = self.store.connection.execute(
            "SELECT details_json FROM events WHERE seq=?",
            (events[-1]["details"]["repeat_of"],)).fetchone()
        self.assertEqual("移动端同伴看不见活动灯",
                         json.loads(row["details_json"])["reason"])

    def test_one_reason_two_targets_is_not_a_replay(self):
        """The ask is the reason *and* the wording it asks for.

        A card is taken to "narrow screens only" citing accessibility, then to "all
        viewports" for another reason, then back to "all viewports" citing
        accessibility again. That last request repeats a *reason* but not a
        *request*: its target is a sentence the first accessibility revise never
        asked for. Comparing reasons alone filed it under the first one, so the row
        it named recorded a different target than the one the reader was looking at.
        """
        self.store.revise("c-one", "窄屏显示状态", "无障碍需求")
        self.store.revise("c-one", "所有视口显示状态", "布局复核")
        self.store.revise("c-one", "所有视口显示状态", "无障碍需求")
        events = self.store.history("c-one")["events"]
        revisals = [e for e in events if e["event"].startswith("revise")]
        self.assertEqual(["revise", "revise", "revise"],
                         [e["event"] for e in revisals])
        self.assertNotIn("repeat_of", revisals[-1]["details"])
        # The target is recorded, so "asked for" is answerable from the ledger.
        self.assertEqual("所有视口显示状态", revisals[-1]["details"]["to_statement"])
        # Wording never changed after the second revise: add=1, first=2, second=3,
        # third stays at 3.
        self.assertEqual(3, self.store.show("c-one")["candidate"]["version"])

    def test_optional_inputs_are_part_of_the_request(self):
        """`scope` is an input, so a different scope is a different request.

        Same wording, same reason, two scopes: "narrow screens only" for
        accessibility, then "all viewports" for accessibility. The second asks for
        something the first never did. Recording only the *names* of the fields that
        moved ("statement, scope") made the two look identical, so the second was
        filed as a replay of the first -- and re-asking for "all viewports" then
        pointed back at the narrow-screen row.
        """
        self.store.revise("c-one", "卡片显示状态", "无障碍需求", scope=["窄屏"])
        self.store.revise("c-one", "卡片显示状态", "无障碍需求", scope=["所有视口"])
        self.store.revise("c-one", "卡片显示状态", "无障碍需求", scope=["所有视口"])
        events = self.store.history("c-one")["events"]
        revisals = [e for e in events if e["event"].startswith("revise")]
        self.assertEqual(["revise", "revise", "revise.repeat"],
                         [e["event"] for e in revisals])
        # The replay names the all-viewports row, not the narrow-screens one.
        named = [e for e in events
                 if e.get("sequence") == revisals[-1]["details"]["repeat_of"]]
        self.assertEqual(1, len(named))
        self.assertEqual(["所有视口"], named[0]["details"]["request"]["scope"])

    def test_every_optional_input_reaches_the_recorded_request(self):
        """Not just `scope`: any input the caller can supply is part of the ask."""
        self.store.revise(
            "c-one", "同一句话", "同一个理由",
            kind="application", scope=["窄屏"], premises=["前提甲"],
            alternatives=["替代甲"], contradictions=["矛盾甲"], unknowns=["未知甲"],
        )
        recorded = self.store.history("c-one")["events"][-1]["details"]["request"]
        for key in ("kind", "premises", "scope", "alternatives",
                    "contradictions", "unknowns"):
            self.assertIn(key, recorded, 'the ask dropped the value of %s' % key)
        self.assertEqual(["窄屏"], recorded["scope"])
        self.assertEqual(["前提甲"], recorded["premises"])
        # A second call with one of those values changed is a new request.
        self.store.revise(
            "c-one", "同一句话", "同一个理由",
            kind="application", scope=["所有视口"], premises=["前提甲"],
            alternatives=["替代甲"], contradictions=["矛盾甲"], unknowns=["未知甲"],
        )
        self.assertEqual("revise", self.store.history("c-one")["events"][-1]["event"])

    def test_a_row_without_a_recorded_ask_is_not_silently_called_a_new_request(self):
        """Old rows have no `request`; "no earlier match" is not "nothing to compare".

        Rows written before the ask was stored cannot be compared at all. Writing the
        new row under its own name is right, but saying nothing would present the
        absence of evidence as a verdict, so the row counts what it could not check.
        """
        self.store.revise("c-one", "同一句话", "同一个理由")
        # Make the row look like one written before `request` existed.
        row = self.store.connection.execute(
            "SELECT seq,details_json FROM events WHERE event='revise' ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        details = json.loads(row["details_json"])
        details.pop("request", None)
        self.store.connection.execute(
            "UPDATE events SET details_json=? WHERE seq=?", (json.dumps(details), row["seq"]))
        self.store.connection.commit()

        self.store.revise("c-one", "同一句话", "同一个理由")
        last = self.store.history("c-one")["events"][-1]
        self.assertEqual("revise", last["event"], 'an uncomparable row must not be a match')
        self.assertEqual(1, last["details"]["earlier_rows_without_a_recorded_request"])
        # A comparable replay still resolves normally and carries no such note.
        self.store.revise("c-one", "同一句话", "同一个理由")
        last = self.store.history("c-one")["events"][-1]
        self.assertEqual("revise.repeat", last["event"])
        self.assertNotIn("earlier_rows_without_a_recorded_request", last["details"])

    def test_a_replay_names_a_row_that_asked_for_the_same_thing(self):
        """`repeat_of` must be followable to a row with the same ask, not just a seq.

        The pointer is only useful if the row it names answers the same request.
        Reading the named row back through `history` (not through raw SQL) is also
        what a reader of `show --history` has to do.
        """
        self.store.revise("c-one", "窄屏显示状态", "无障碍需求")
        self.store.revise("c-one", "所有视口显示状态", "布局复核")
        self.store.revise("c-one", "所有视口显示状态", "无障碍需求")
        self.store.revise("c-one", "所有视口显示状态", "无障碍需求")   # the real replay
        events = self.store.history("c-one")["events"]
        repeat = events[-1]
        self.assertEqual("revise.repeat", repeat["event"])
        # Every event carries the number `repeat_of` speaks in, so no second query.
        self.assertEqual([e["sequence"] for e in events], sorted(e["sequence"] for e in events))
        original = [e for e in events if e.get("sequence") == repeat["details"]["repeat_of"]]
        self.assertEqual(1, len(original), 'repeat_of names no row in this history')
        self.assertEqual("revise", original[0]["event"])
        self.assertEqual(repeat["details"]["reason"], original[0]["details"]["reason"])
        self.assertEqual(repeat["details"]["to_statement"],
                         original[0]["details"]["to_statement"])
        self.assertNotEqual("窄屏显示状态", original[0]["details"]["to_statement"],
                            'the pointer landed on the same-reason row with another target')

    def test_a_second_reason_does_not_reopen_the_pipeline(self):
        self.store.revise("c-one", "同一句话", "移动端同伴看不见活动灯")
        version = self.store.show("c-one")["candidate"]["version"]
        self.store.connection.execute(
            "INSERT INTO pipeline_marks(session,pass_name,candidate_id,version,created_at)"
            " VALUES('s1','distill','c-one',?,'2026-11-27T00:00:00Z')", (version,))
        self.store.connection.commit()
        self.store.revise("c-one", "同一句话", "触屏读屏需要一个可读状态")
        self.assertEqual(version, self.store.show("c-one")["candidate"]["version"])
        mark = self.store.connection.execute(
            "SELECT version FROM pipeline_marks WHERE candidate_id='c-one'").fetchone()[0]
        self.assertEqual(version, mark)


class EveryWriterStatesItsWholeRequest(unittest.TestCase):
    """The rule cannot be "remember to record the new field too".

    Both defects in this slice were the same shape: a writer recorded part of what
    the caller asked for, and the comparison believed the part was the whole. Each
    fix added one more field, which is how a rule rots. The contract is enforced
    instead: `_write` takes the ask as its own argument, and every call site must
    pass one. A writer added later that forgets fails here rather than silently
    making "no earlier match" mean "not the same request".

    This is a source check, not a behaviour check. It is here because the failure it
    prevents is an omission -- and an omission cannot be caught by exercising the
    writers that exist.
    """

    def setUp(self):
        import dojo.storage as storage
        self.path = Path(storage.__file__)
        self.tree = ast.parse(self.path.read_text(encoding='utf-8'))

    def _write_calls(self):
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "_write":
                yield node

    def test_write_has_a_dedicated_request_parameter(self):
        methods = {n.name: n for n in ast.walk(self.tree)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        self.assertIn("_write", methods)
        params = [a.arg for a in methods["_write"].args.args]
        self.assertIn("request", params,
                      '_write no longer takes the ask as its own argument')
        # ... and it is stored, not merely compared, or a later row cannot answer
        # "was this a replay of that?".
        body = ast.get_source_segment(self.path.read_text(encoding='utf-8'),
                                      methods["_write"])
        self.assertIn('"request": request', body,
                      '_write stopped recording the ask it compares')

    def test_no_call_site_omits_its_request(self):
        misses = []
        for call in self._write_calls():
            has_kw = any(k.arg == "request" for k in call.keywords)
            # state, event, details, request
            has_pos = len([a for a in call.args if not isinstance(a, ast.Starred)]) >= 4 or any(
                isinstance(a, ast.Starred) for a in call.args)
            if not (has_kw or has_pos):
                misses.append(call.lineno)
        self.assertEqual([], misses,
                         '_write call sites pass no request (lines %s); a writer that '
                         'records part of the ask is how both defects in this slice '
                         'happened' % misses)

    def test_the_bookkeeping_subtraction_is_still_gone(self):
        """The set of keys to subtract was the bug, so it must not come back."""
        source = self.path.read_text(encoding='utf-8')
        self.assertNotIn("_REQUEST_BOOKKEEPING", source,
                         'the "ignore these keys" set is back; it was wrong twice')


if __name__ == "__main__":
    unittest.main()
