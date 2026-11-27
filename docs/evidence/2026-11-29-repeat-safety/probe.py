#!/usr/bin/env python3
"""Re-measure both decisions in this slice. Offline; no network, no model.

    python3 -B docs/evidence/2026-11-29-repeat-safety/probe.py

Scenario A drives the real `OpenAICompatibleClient` and the real `run_discuss`
against a local stub that answers 200 with a Content-Length and then sends fewer
bytes. It counts the requests the server actually received: the published
behaviour sent three for one user turn.

Scenario B drives the real store. It confirms a card, marks it "processed to
version N" the way a pipeline pass does, then confirms it with the identical
request and asks whether the mark still holds.

Both halves print one JSON object. Nothing here writes outside a temp directory.
"""
import io
import json
import socket
import sqlite3
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[3]))

from dojo.discuss import run_discuss                       # noqa: E402
from dojo.live import LiveConfig, LiveError, OpenAICompatibleClient  # noqa: E402
from dojo.storage import Store                             # noqa: E402

PARTIAL = b'{"choices":[{"message":{"content":"half an answer'


class _Cut(BaseHTTPRequestHandler):
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


def scenario_a():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Cut)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    _Cut.seen = 0
    try:
        config = LiveConfig(
            f"http://127.0.0.1:{server.server_address[1]}/v1/chat/completions",
            "stub-model", None, 5)
        client = OpenAICompatibleClient(config)

        # What does the client call this, before any discussion logic sees it?
        try:
            client.complete([{"role": "user", "content": "hi"}])
            kind, requests_for_one_call = "no_error", _Cut.seen
        except LiveError as exc:
            kind, requests_for_one_call = exc.kind, _Cut.seen

        _Cut.seen = 0
        store = Store(str(Path(tempfile.mkdtemp(prefix="probe-a-")) / "lib.sqlite3"))
        lines = iter(["提出一个想法"])

        def read_line(_prompt):
            try:
                return next(lines)
            except StopIteration:
                raise EOFError

        output = io.StringIO()
        code = run_discuss(store, client=client, read_line=read_line, output=output)
        said = output.getvalue()
        return {
            "client_error_kind_for_a_cut_body": kind,
            "requests_for_one_completed_call": requests_for_one_call,
            "requests_received_for_one_user_turn": _Cut.seen,
            "run_discuss_exit_code": code,
            "candidates_written": len(store.list_candidates()),
            "told_the_user_the_model_format_was_invalid": "格式不合法" in said,
            "told_the_user_the_request_was_not_resent": "没有据此重发请求" in said,
        }
    finally:
        server.shutdown()
        server.server_close()


def scenario_b():
    store = Store(str(Path(tempfile.mkdtemp(prefix="probe-b-")) / "lib.sqlite3"))
    store.add("重复请求是否同一效果", "abstract_idea", candidate_id="c-one", scope=["探针"])
    first = store.confirm("c-one", "worth discussing")
    version = store.show("c-one")["candidate"]["version"]
    snapshots = len(store.history("c-one")["versions"])

    # Stand in for a pipeline pass that has dealt with this exact version.
    store.connection.execute(
        "INSERT INTO pipeline_marks(session,pass_name,candidate_id,version,created_at)"
        " VALUES('s1','distill','c-one',?,'2026-11-27T00:00:00Z')", (version,))
    store.connection.commit()

    again = store.confirm("c-one", "worth discussing")
    after = store.show("c-one")["candidate"]["version"]
    mark = store.connection.execute(
        "SELECT version FROM pipeline_marks WHERE candidate_id='c-one'").fetchone()[0]
    events = store.history("c-one")["events"]
    repeat = [e for e in events if e["event"].endswith(".repeat")]

    # A real second decision must still write.
    before_real = after
    store.confirm("c-one", "a different basis")
    real = store.show("c-one")["candidate"]["version"]

    return {
        "version_after_first_confirm": first["version"],
        "version_after_identical_repeat": again["version"],
        "snapshots_before_repeat": snapshots,
        "snapshots_after_repeat": len(store.history("c-one")["versions"]) - 1,
        "pipeline_mark_still_matches_the_card": mark == after,
        "repeat_is_named_in_the_ledger": bool(repeat),
        "repeat_event": repeat[0]["event"] if repeat else None,
        "repeat_points_at_the_original": bool(repeat and repeat[0]["details"].get("repeat_of")),
        "a_different_confirm_still_writes": real > before_real,
    }


if __name__ == "__main__":
    print(json.dumps({"scenario_a": scenario_a(), "scenario_b": scenario_b()},
                     ensure_ascii=False, indent=2))
