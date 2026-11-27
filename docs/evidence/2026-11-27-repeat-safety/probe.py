#!/usr/bin/env python3
"""Re-measure both decisions in this slice. Offline; no network, no model.

    python3 -B docs/evidence/2026-11-27-repeat-safety/probe.py

Scenario A drives the real `OpenAICompatibleClient` and the real `run_discuss`
against a local stub that answers 200 with a Content-Length and then sends fewer
bytes. It counts the requests the server actually received: the published
behaviour sent three for one user turn.

Scenario B drives the real store. It confirms a card, marks it "processed to
version N" the way a pipeline pass does, then confirms it with the identical
request and asks whether the mark still holds.

Scenario C is the same store seen from the other side: two *different* requests
that leave the card in the same state. Revising a card to the sentence it already
has, for a second and new reason, must keep the version (the wording did not
change) and must not file the new reason as a replay of the first.

Scenario D is the narrow case a re-check found: one *reason*, two different
targets. Taking a card to "narrow screens" citing accessibility and later to "all
viewports" citing the same thing repeats a reason, not a request. It must be its
own row, and a genuine replay must point at a row that asked for the same target.

Scenario E is the same shape one level down: the wording and the reason are
identical and the *scope* differs. Recording which fields moved is not recording
what was asked for, so E checks that the value is in the row and that the replay
names the row carrying the same value.

All five print one JSON object. Nothing here writes outside a temp directory.
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


def scenario_c():
    store = Store(str(Path(tempfile.mkdtemp(prefix="probe-c-")) / "lib.sqlite3"))
    store.add("卡片文案", "abstract_idea", candidate_id="c-one", scope=["探针"])
    store.revise("c-one", "同一句话", "移动端同伴看不见活动灯")
    after_first = store.show("c-one")["candidate"]["version"]
    store.revise("c-one", "同一句话", "触屏读屏需要一个可读状态")
    after_second = store.show("c-one")["candidate"]["version"]
    store.revise("c-one", "同一句话", "触屏读屏需要一个可读状态")   # the actual replay
    events = store.history("c-one")["events"]
    revisals = [e for e in events if e["event"].startswith("revise")]
    second = [e for e in revisals if e["event"] == "revise"
              and e["details"].get("reason") == "触屏读屏需要一个可读状态"]
    repeat = revisals[-1]

    return {
        "version_after_first_reason": after_first,
        "version_after_a_new_reason": after_second,
        "a_new_reason_moves_the_version": after_second != after_first,
        "rows_for_the_two_reasons": [e["event"] for e in revisals[:2]],
        "the_new_reason_is_not_a_repeat": bool(second) and "repeat_of" not in second[0]["details"],
        "reasons_in_the_ledger": [e["details"].get("reason") for e in revisals],
        "the_actual_replay_is_marked": repeat["event"],
        "version_after_the_replay": store.show("c-one")["candidate"]["version"],
    }


def scenario_d():
    """One reason, two targets: the ask is the reason and the wording asked for."""
    store = Store(str(Path(tempfile.mkdtemp(prefix="probe-d-")) / "lib.sqlite3"))
    store.add("卡片文案", "abstract_idea", candidate_id="c-one", scope=["探针"])
    store.revise("c-one", "窄屏显示状态", "无障碍需求")
    store.revise("c-one", "所有视口显示状态", "布局复核")
    store.revise("c-one", "所有视口显示状态", "无障碍需求")   # same reason, new target
    store.revise("c-one", "所有视口显示状态", "无障碍需求")   # the real replay
    events = store.history("c-one")["events"]
    revisals = [e for e in events if e["event"].startswith("revise")]
    repeat = revisals[-1]
    named = [e for e in events if e.get("sequence") == repeat["details"].get("repeat_of")]

    return {
        "rows_for_one_reason_two_targets": [e["event"] for e in revisals[:3]],
        "the_second_target_is_not_a_replay": "repeat_of" not in revisals[2]["details"],
        "the_second_target_is_recorded": revisals[2]["details"].get("to_statement"),
        "version_after_the_two_targets": store.show("c-one")["candidate"]["version"],
        "the_actual_replay_is_marked": repeat["event"],
        "repeat_of_names_the_row_with_the_same_target": bool(named) and (
            named[0]["details"].get("to_statement")
            == repeat["details"].get("to_statement")),
        "repeat_of_does_not_name_the_other_target": bool(named) and (
            named[0]["details"].get("to_statement") != "窄屏显示状态"),
    }


def scenario_e():
    """Same wording and reason, different scope: the value is the request."""
    store = Store(str(Path(tempfile.mkdtemp(prefix="probe-e-")) / "lib.sqlite3"))
    store.add("卡片显示状态", "abstract_idea", candidate_id="c-one", scope=["所有"])
    store.revise("c-one", "卡片显示状态", "无障碍需求", scope=["窄屏"])
    store.revise("c-one", "卡片显示状态", "无障碍需求", scope=["所有视口"])
    store.revise("c-one", "卡片显示状态", "无障碍需求", scope=["所有视口"])   # the replay
    events = store.history("c-one")["events"]
    revisals = [e for e in events if e["event"].startswith("revise")]
    repeat = revisals[-1]
    named = [e for e in events if e.get("sequence") == repeat["details"].get("repeat_of")]

    return {
        "rows_for_one_reason_two_scopes": [e["event"] for e in revisals[:2]],
        "the_second_scope_is_not_a_replay": "repeat_of" not in revisals[1]["details"],
        "scopes_recorded_in_the_asks": [
            (e["details"].get("request") or {}).get("scope") for e in revisals[:2]],
        "the_actual_replay_is_marked": repeat["event"],
        "repeat_of_names_the_row_with_the_same_scope": bool(named) and (
            (named[0]["details"].get("request") or {}).get("scope")
            == (repeat["details"].get("request") or {}).get("scope")),
        "repeat_of_does_not_name_the_other_scope": bool(named) and (
            (named[0]["details"].get("request") or {}).get("scope") != ["窄屏"]),
    }


if __name__ == "__main__":
    print(json.dumps({
        "scenario_a": scenario_a(),
        "scenario_b": scenario_b(),
        "scenario_c": scenario_c(),
        "scenario_d": scenario_d(),
        "scenario_e": scenario_e(),
    }, ensure_ascii=False, indent=2))
