import io
import json
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from dojo.demo import CHALLENGE, TARGET_FACTS, freeze_materials
from dojo.discuss import run_discuss
from dojo.live import (
    LiveConfig,
    LiveError,
    MAX_DISCUSS_ANSWER_CHARS,
    MAX_DISCUSS_FIELD_CHARS,
    MAX_DISCUSS_FIELDS_PER_LIST,
    MAX_DISCUSS_RAW_RESPONSE_CHARS,
    MAX_DISCUSS_REQUEST_CHARS,
    MAX_DISCUSS_RESPONSE_BYTES,
    MAX_DISCUSS_STATEMENT_CHARS,
    MAX_DISCUSS_USER_TURN_CHARS,
    MAX_HTTP_RESPONSE_BYTES,
    MAX_REQUEST_CHARS,
    OpenAICompatibleClient,
    _validate_model_content,
    run_chat,
)
from dojo.storage import DojoError, Store, load_simulated_seeds


VALID_CANDIDATE = {
    "statement": "候选原文：交界约定可能需要单独讨论",
    "kind": "abstract_idea",
    "premises": ["存在共享交界"],
    "scope": ["当前讨论项目"],
    "alternatives": ["若边界不在支持范围则不适用"],
    "contradictions": [],
    "unknowns": ["支持范围未核验"],
}
VALID_MODEL_RESULT = {"answer": "先区分已知条件与缺失证据。", "candidate": VALID_CANDIDATE}


def endpoint_response(content, *, status=200, finish_reason="stop"):
    if isinstance(content, str):
        message_content = content
    else:
        message_content = json.dumps(content, ensure_ascii=False)
    body = json.dumps({"choices": [{"message": {"content": message_content}, "finish_reason": finish_reason}]}, ensure_ascii=False).encode()
    return {"status": status, "body": body}


class LocalMockEndpoint:
    """Loopback-only deterministic OpenAI-compatible endpoint for tests."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                request_body = self.rfile.read(length)
                owner.requests.append({
                    "path": self.path,
                    "headers": dict(self.headers.items()),
                    "payload": json.loads(request_body),
                })
                response = owner.responses.pop(0)
                if response.get("delay"):
                    time.sleep(response["delay"])
                body = response["body"]
                self.send_response(response.get("status", 200))
                self.send_header("Content-Type", "application/json")
                for name, value in response.get("headers", {}).items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, _format, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}/v1"

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()


class ConversationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "dojo.sqlite3")
        load_simulated_seeds(self.store)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def new_store(self, name):
        store = Store(self.root / name)
        load_simulated_seeds(store)
        self.addCleanup(store.close)
        return store

    def test_live_http_retrieves_context_allows_human_edit_and_preserves_revisions(self):
        with LocalMockEndpoint([endpoint_response(VALID_MODEL_RESULT)]) as endpoint:
            config = LiveConfig.from_environment({
                "DOJO_LLM_BASE_URL": endpoint.base_url,
                "DOJO_LLM_MODEL": "github-copilot/gpt-6-luna",
                "DOJO_LLM_API_KEY": "test-only-secret-token",
            })
            state = {"chat_turn": 0, "candidate_id": None}

            def read_line(prompt):
                if prompt == "你> ":
                    state["chat_turn"] += 1
                    if state["chat_turn"] == 1:
                        return "降低摩擦让行为更容易持续，但哪些难度该保留还不知道。"
                    candidates = self.store.list_candidates()
                    saved = [item for item in candidates if item["id"].startswith("d-")]
                    self.assertEqual(1, len(saved), candidates)
                    state["candidate_id"] = saved[0]["id"]
                    if state["chat_turn"] == 2:
                        return f"/challenge {state['candidate_id']} | 旧端是否仍受支持尚不清楚"
                    if state["chat_turn"] == 3:
                        return f"/revise {state['candidate_id']} | 仅在支持范围明确时检查交界 | 加入支持条件"
                    if state["chat_turn"] == 4:
                        return f"/history {state['candidate_id']}"
                    return "/quit"
                if prompt.startswith("保存为道场草稿"):
                    return "e"
                if prompt.startswith("输入要保存的观点"):
                    return "人工编辑后的抽象候选"
                if prompt.startswith("是否确认"):
                    return "y"
                self.fail(f"unexpected prompt: {prompt}")

            output = io.StringIO()
            code = run_chat(self.store, config=config, read_line=read_line, output=output)

        self.assertEqual(0, code)
        self.assertEqual(1, len(endpoint.requests))
        request = endpoint.requests[0]
        self.assertEqual("/v1/chat/completions", request["path"])
        self.assertEqual("Bearer test-only-secret-token", request["headers"]["Authorization"])
        payload = request["payload"]
        self.assertEqual("github-copilot/gpt-6-luna", payload["model"])
        self.assertEqual(900, payload["max_tokens"])
        self.assertEqual({"type": "json_object"}, payload["response_format"])
        self.assertNotIn("reasoning_effort", payload)
        serialized_messages = json.dumps(payload["messages"], ensure_ascii=False)
        self.assertIn("降低摩擦让行为更容易持续", serialized_messages)
        self.assertIn("seed-m01", serialized_messages)
        self.assertNotIn("facilitator", serialized_messages.lower())
        self.assertNotIn("裁判笔记", serialized_messages)
        self.assertIn("模型生成的候选草稿", output.getvalue())
        self.assertNotIn("test-only-secret-token", output.getvalue())
        self.assertNotIn("降低摩擦让行为更容易持续", output.getvalue())

        state = self.store.show(state["candidate_id"])["candidate"]
        self.assertEqual("仅在支持范围明确时检查交界", state["statement"])
        self.assertEqual("discussable", state["status"])
        history = self.store.history(state["id"])["versions"]
        self.assertEqual([1, 2, 3, 4, 5], [item["version"] for item in history])
        self.assertEqual("draft", history[0]["state"]["status"])
        self.assertEqual("人工编辑后的抽象候选", history[1]["state"]["statement"])
        self.assertEqual("challenged", history[2]["state"]["status"])
        self.assertIn("旧端是否仍受支持尚不清楚", history[2]["state"]["contradictions"])
        self.assertEqual("仅在支持范围明确时检查交界", history[3]["state"]["statement"])
        source_types = {item["type"] for item in state["sources"]}
        self.assertEqual({"unknown", "model_generated"}, source_types)
        serialized_database = json.dumps(state, ensure_ascii=False)
        self.assertNotIn("降低摩擦让行为更容易持续", serialized_database)
        self.assertNotIn("候选原文：交界约定可能需要单独讨论", serialized_database)

    def test_chat_schema_stays_strict_while_discuss_opts_into_user_stance(self):
        discuss_result = {**VALID_MODEL_RESULT, "user_stance": "neutral"}
        content = json.dumps(discuss_result, ensure_ascii=False)

        with self.assertRaises(LiveError):
            _validate_model_content(content)
        self.assertEqual(
            discuss_result,
            _validate_model_content(content, allowed_extra_keys=frozenset({"user_stance"})),
        )

    def test_discuss_search_response_is_opt_in_and_query_is_validated(self):
        query = "site:example.test lang:zh after:2025-01-01 bicycle"
        content = json.dumps({
            "answer": "我需要查一下。",
            "search": {"query": query},
            "user_stance": "neutral",
        }, ensure_ascii=False)
        with self.assertRaises(LiveError):
            _validate_model_content(content, allowed_extra_keys=frozenset({"user_stance"}))
        checked = _validate_model_content(
            content, allowed_extra_keys=frozenset({"user_stance"}), allow_search=True,
        )
        self.assertEqual(query, checked["search"]["query"])
        self.assertNotIn("candidate", checked)
        with LocalMockEndpoint([endpoint_response(content)]) as endpoint:
            client = OpenAICompatibleClient(
                LiveConfig(endpoint.base_url, "test-model", None),
                allowed_extra_keys=frozenset({"user_stance"}), allow_search=True,
            )
            completed = client.complete([{"role": "user", "content": "test"}])
        self.assertEqual(query, completed["search"]["query"])
        for invalid in (
            {"answer": "查询", "search": {"query": " "}, "user_stance": "neutral"},
            {"answer": "查询", "search": {"query": "x" * 129}, "user_stance": "neutral"},
            {"answer": "查询", "search": {"query": "valid"}, "candidate": None, "user_stance": "neutral"},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(LiveError):
                _validate_model_content(
                    json.dumps(invalid, ensure_ascii=False),
                    allowed_extra_keys=frozenset({"user_stance"}), allow_search=True,
                )

    def test_openai_client_exposes_finish_reason_and_raw_output_and_detects_truncation(self):
        raw_content = json.dumps({"answer": "raw response", "candidate": None}, ensure_ascii=False)
        with LocalMockEndpoint([endpoint_response(raw_content)]) as endpoint:
            client = OpenAICompatibleClient(LiveConfig(endpoint.base_url, "test", None))
            completed = client.complete([{"role": "user", "content": "test"}])
        self.assertEqual("stop", completed["finish_reason"])
        self.assertEqual(raw_content, completed["raw_response"])

        with LocalMockEndpoint([endpoint_response('{"partial":', finish_reason="length")]) as endpoint:
            client = OpenAICompatibleClient(LiveConfig(endpoint.base_url, "test", None))
            with self.assertRaises(LiveError) as caught:
                client.complete([{"role": "user", "content": "test"}])
        self.assertEqual("truncated", caught.exception.kind)
        self.assertEqual("length", caught.exception.finish_reason)
        self.assertEqual('{"partial":', caught.exception.raw_response)

        with LocalMockEndpoint([endpoint_response("{not strict JSON")]) as endpoint:
            client = OpenAICompatibleClient(LiveConfig(endpoint.base_url, "test", None))
            with self.assertRaises(LiveError) as caught:
                client.complete([{"role": "user", "content": "test"}])
        self.assertEqual("not_json", caught.exception.kind)
        self.assertEqual("{not strict JSON", caught.exception.raw_response)

    def test_discuss_accepts_long_answers_without_loosening_chat_contract(self):
        long_answer = "长" * 30_000
        discuss_result = {"answer": long_answer, "candidate": None, "user_stance": "neutral"}
        turns = iter(["请继续讨论"])

        def read_line(_prompt):
            try:
                return next(turns)
            except StopIteration:
                raise EOFError

        with LocalMockEndpoint([endpoint_response(discuss_result)]) as endpoint:
            output = io.StringIO()
            code = run_discuss(
                self.store,
                config=LiveConfig(endpoint.base_url, "github_copilot/gpt-6-luna", None),
                environ={}, read_line=read_line, output=output,
            )
        self.assertEqual(0, code, output.getvalue())
        self.assertIn(long_answer, output.getvalue())
        trace_path = Path([
            line.split("：", 1)[1].strip()
            for line in output.getvalue().splitlines()
            if line.startswith("本场会话轨迹：")
        ][0])
        row = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(len(json.dumps(discuss_result, ensure_ascii=False)), len(row["raw_response"]))
        self.assertEqual(long_answer, row["answer"])
        self.assertEqual("medium", row["reasoning_effort"])
        self.assertFalse(row["reasoning_effort_fallback"])

    def test_discuss_sends_long_user_input_with_the_larger_request_envelope(self):
        long_input = "用户补充的真实讨论上下文。" * 2_500
        response = {"answer": "已收到较长上下文。", "candidate": None, "user_stance": "neutral"}
        turns = iter([long_input])

        def read_line(_prompt):
            try:
                return next(turns)
            except StopIteration:
                raise EOFError

        with LocalMockEndpoint([endpoint_response(response)]) as endpoint:
            output = io.StringIO()
            code = run_discuss(
                self.store,
                config=LiveConfig(endpoint.base_url, "github_copilot/gpt-6-luna", None),
                environ={}, read_line=read_line, output=output,
            )

        self.assertEqual(0, code, output.getvalue())
        self.assertEqual(1, len(endpoint.requests))
        payload = endpoint.requests[0]["payload"]
        serialized_request = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.assertGreater(len(long_input), 1_600)
        self.assertLessEqual(len(long_input), MAX_DISCUSS_USER_TURN_CHARS)
        self.assertGreater(len(serialized_request), MAX_REQUEST_CHARS)
        self.assertLessEqual(len(serialized_request), MAX_DISCUSS_REQUEST_CHARS)
        self.assertIn(long_input, json.dumps(payload["messages"], ensure_ascii=False))

    def test_discuss_reasoning_effort_environment_override_is_sent_and_traced(self):
        response = {"answer": "按中等级继续讨论。", "candidate": None, "user_stance": "neutral"}
        with LocalMockEndpoint([endpoint_response(response)]) as endpoint:
            output = io.StringIO()
            answers = iter(["继续讨论"])

            def read_line(_prompt):
                try:
                    return next(answers)
                except StopIteration:
                    raise EOFError

            code = run_discuss(
                self.store,
                config=LiveConfig(endpoint.base_url, "github_copilot/gpt-6-luna", None),
                environ={"DOJO_LLM_REASONING": "medium"},
                read_line=read_line, output=output,
            )
        self.assertEqual(0, code, output.getvalue())
        self.assertEqual("medium", endpoint.requests[0]["payload"]["reasoning_effort"])
        trace_path = Path([
            line.split("：", 1)[1].strip()
            for line in output.getvalue().splitlines()
            if line.startswith("本场会话轨迹：")
        ][0])
        row = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual("medium", row["reasoning_effort"])
        self.assertFalse(row["reasoning_effort_fallback"])

    def test_discuss_response_body_uses_the_documented_safety_envelope(self):
        oversized = {"status": 200, "body": b"x" * (MAX_DISCUSS_RESPONSE_BYTES + 1)}
        with LocalMockEndpoint([oversized]) as endpoint:
            client = OpenAICompatibleClient(
                LiveConfig(endpoint.base_url, "test-model", None),
                max_response_bytes=MAX_DISCUSS_RESPONSE_BYTES,
                max_raw_response_chars=MAX_DISCUSS_RAW_RESPONSE_CHARS,
                max_answer_chars=MAX_DISCUSS_ANSWER_CHARS,
            )
            with self.assertRaises(LiveError) as caught:
                client.complete([{"role": "user", "content": "test"}])
        self.assertIn("exceeded 1000000 bytes", str(caught.exception))

    def test_discuss_accepts_documented_candidate_output_envelopes(self):
        oversized = {
            "answer": "答" * MAX_DISCUSS_ANSWER_CHARS,
            "candidate": {
                "statement": "结" * MAX_DISCUSS_STATEMENT_CHARS,
                "kind": "abstract_idea",
                "premises": ["前" * MAX_DISCUSS_FIELD_CHARS] * 9,
                "scope": ["范"],
                "alternatives": [],
                "contradictions": [],
                "unknowns": [],
            },
            "user_stance": "neutral",
        }
        validated = _validate_model_content(
            json.dumps(oversized, ensure_ascii=False),
            allowed_extra_keys=frozenset({"user_stance"}),
            max_answer_chars=MAX_DISCUSS_ANSWER_CHARS,
            max_statement_chars=MAX_DISCUSS_STATEMENT_CHARS,
            max_field_chars=MAX_DISCUSS_FIELD_CHARS,
            max_fields_per_list=MAX_DISCUSS_FIELDS_PER_LIST,
        )
        self.assertEqual(MAX_DISCUSS_ANSWER_CHARS, len(validated["answer"]))
        self.assertEqual(MAX_DISCUSS_STATEMENT_CHARS, len(validated["candidate"]["statement"]))
        self.assertEqual(9, len(validated["candidate"]["premises"]))
        self.assertEqual(MAX_DISCUSS_RAW_RESPONSE_CHARS, 65_536)

    def test_discuss_http_contract_accepts_user_stance(self):
        empty_store = Store(self.root / "discuss-http.sqlite3")
        self.addCleanup(empty_store.close)
        discuss_result = {**VALID_MODEL_RESULT, "user_stance": "neutral"}
        accepted_result = {**VALID_MODEL_RESULT, "user_stance": "accept"}
        with LocalMockEndpoint([endpoint_response(discuss_result), endpoint_response(accepted_result)]) as endpoint:
            answers = iter(["讨论一个想法", "是的，我明确认可这条结论"])

            def read_line(_prompt):
                try:
                    return next(answers)
                except StopIteration:
                    raise EOFError

            output = io.StringIO()
            code = run_discuss(
                empty_store,
                config=LiveConfig(endpoint.base_url, "github-copilot/gpt-6-luna", None),
                environ={}, read_line=read_line, output=output,
            )

        self.assertEqual(0, code)
        self.assertEqual(2, len(endpoint.requests))
        self.assertTrue(all(item["payload"]["max_tokens"] == 65_536 for item in endpoint.requests))
        self.assertTrue(all(item["payload"]["reasoning_effort"] == "medium" for item in endpoint.requests))
        self.assertEqual(1, len(empty_store.list_candidates()))

    def test_model_candidate_reject_and_eof_leave_store_unchanged(self):
        before_ids = {item["id"] for item in self.store.list_candidates()}
        with LocalMockEndpoint([endpoint_response(VALID_MODEL_RESULT), endpoint_response(VALID_MODEL_RESULT)]) as endpoint:
            responses = iter(["有一个需要讨论的想法", "n", "/quit"])
            output = io.StringIO()
            code = run_chat(self.store, config=LiveConfig(endpoint.base_url, "test-model", None), read_line=lambda _prompt: next(responses), output=output)
            self.assertEqual(0, code)
            self.assertIn("没有保存模型候选", output.getvalue())
            self.assertEqual(before_ids, {item["id"] for item in self.store.list_candidates()})

            second = self.new_store("eof.sqlite3")
            calls = iter(["另一个想法"])

            def eof_at_save(prompt):
                if prompt == "你> ":
                    return next(calls)
                raise EOFError

            output = io.StringIO()
            code = run_chat(second, config=LiveConfig(endpoint.base_url, "test-model", None), read_line=eof_at_save, output=output)
            self.assertEqual(0, code)
            self.assertIn("EOF/取消", output.getvalue())
            self.assertEqual(4, len(second.list_candidates()))
            self.assertEqual(2, len(endpoint.requests))

    def test_bad_schema_http_error_and_secret_redaction_do_not_save(self):
        bad = endpoint_response("{ not strict json")
        wrong_schema = endpoint_response({"answer": "answer", "candidate": None, "unexpected": True})
        unauthorized = {"status": 401, "body": b"the body repeats secret-marker; do not print"}
        with LocalMockEndpoint([bad, wrong_schema, unauthorized]) as endpoint:
            for _ in range(3):
                output = io.StringIO()
                code = run_chat(
                    self.store,
                    config=LiveConfig(endpoint.base_url, "test-model", "secret-marker"),
                    read_line=lambda _prompt: "请检查兼容协议交接。",
                    output=output,
                )
                self.assertEqual(2, code)
                self.assertNotIn("secret-marker", output.getvalue())
                self.assertEqual(4, len(self.store.list_candidates()))
        self.assertEqual(3, len(endpoint.requests))
        self.assertTrue(all(item["headers"]["Authorization"] == "Bearer secret-marker" for item in endpoint.requests))

    def test_endpoint_redirect_is_rejected_without_following_it(self):
        redirect = {
            "status": 302,
            "headers": {"Location": "http://127.0.0.1:1/redirected"},
            "body": b"redirect body",
        }
        with LocalMockEndpoint([redirect]) as endpoint:
            output = io.StringIO()
            code = run_chat(
                self.store, config=LiveConfig(endpoint.base_url, "test-model", "not-to-leak"),
                read_line=lambda _prompt: "user turn", output=output,
            )
        self.assertEqual(2, code)
        self.assertIn("HTTP 302", output.getvalue())
        self.assertNotIn("not-to-leak", output.getvalue())
        self.assertEqual(1, len(endpoint.requests))
        self.assertEqual(4, len(self.store.list_candidates()))

    def test_response_size_and_timeout_are_bounded_and_do_not_save(self):
        oversized = {"status": 200, "body": b"x" * (MAX_HTTP_RESPONSE_BYTES + 100)}
        slow = {"status": 200, "body": endpoint_response(VALID_MODEL_RESULT)["body"], "delay": 0.2}
        with LocalMockEndpoint([oversized, slow]) as endpoint:
            output = io.StringIO()
            code = run_chat(self.store, config=LiveConfig(endpoint.base_url, "test-model", None), read_line=lambda _prompt: "用户输入", output=output)
            self.assertEqual(2, code)
            self.assertIn("exceeded", output.getvalue())
            self.assertEqual(4, len(self.store.list_candidates()))

            output = io.StringIO()
            code = run_chat(
                self.store, config=LiveConfig(endpoint.base_url, "test-model", None, 0.05),
                read_line=lambda _prompt: "用户输入", output=output,
            )
            self.assertEqual(2, code)
            self.assertIn("timed out", output.getvalue())
            self.assertEqual(4, len(self.store.list_candidates()))

    def test_request_output_user_and_request_count_budgets_are_enforced(self):
        client = OpenAICompatibleClient(LiveConfig("http://127.0.0.1:1/v1/chat/completions", "test", None))
        with self.assertRaises(LiveError):
            client.complete([{"role": "user", "content": "x" * (MAX_REQUEST_CHARS + 10)}])
        bad_output = {"answer": "a" * 4_001, "candidate": None}
        with self.assertRaises(LiveError):
            _validate_model_content(json.dumps(bad_output))

        # Oversized user turns do not reach HTTP; the next local command still works.
        with LocalMockEndpoint([]) as endpoint:
            output = io.StringIO()
            answers = iter(["x" * 1_601, "/quit"])
            code = run_chat(
                self.store, config=LiveConfig(endpoint.base_url, "test", None),
                read_line=lambda _prompt: next(answers), output=output,
            )
            self.assertEqual(0, code)
            self.assertIn("最多 1600 字", output.getvalue())
            self.assertEqual([], endpoint.requests)

        with LocalMockEndpoint([endpoint_response({"answer": "bounded response", "candidate": None})]) as endpoint:
            output = io.StringIO()
            with patch("dojo.live.MAX_MODEL_REQUESTS", 1):
                code = run_chat(
                    self.store, config=LiveConfig(endpoint.base_url, "test", None),
                    read_line=lambda _prompt: "one bounded turn", output=output,
                )
            self.assertEqual(0, code)
            self.assertEqual(1, len(endpoint.requests))
            self.assertIn("请求上限", output.getvalue())

    def test_http_configuration_refuses_remote_plaintext_and_embedded_credentials(self):
        for values in (
            {"DOJO_LLM_BASE_URL": "http://example.invalid/v1"},
            {"DOJO_LLM_BASE_URL": "https://user:pass@example.invalid/v1"},
            {"DOJO_LLM_BASE_URL": "ftp://localhost/v1"},
        ):
            with self.assertRaises(LiveError):
                LiveConfig.from_environment(values)
        config = LiveConfig.from_environment({"DOJO_LLM_BASE_URL": "http://127.0.0.1:1234/v1"})
        self.assertEqual("github_copilot/gpt-6-luna", config.model)
        self.assertIsNone(config.api_key)

    def test_model_timeout_is_configurable_with_a_bounded_default(self):
        config = LiveConfig.from_environment({"DOJO_LLM_BASE_URL": "http://127.0.0.1:1234/v1"})
        self.assertEqual(60, config.timeout)
        slow = LiveConfig.from_environment({
            "DOJO_LLM_BASE_URL": "http://127.0.0.1:1234/v1", "DOJO_LLM_TIMEOUT": "120",
        })
        self.assertEqual(120, slow.timeout)
        for invalid in ("0", "4", "601", "60s"):
            with self.subTest(invalid=invalid), self.assertRaises(LiveError):
                LiveConfig.from_environment({
                    "DOJO_LLM_BASE_URL": "http://127.0.0.1:1234/v1", "DOJO_LLM_TIMEOUT": invalid,
                })
        with LocalMockEndpoint([]) as endpoint:
            client = OpenAICompatibleClient(LiveConfig.from_environment({
                "DOJO_LLM_BASE_URL": endpoint.base_url, "DOJO_LLM_TIMEOUT": "90",
            }))
            self.assertEqual(90, client.timeout)

    def test_frozen_c_packet_uses_actual_retrieval_and_matches_b_target(self):
        outdir = self.root / "packets"
        result = freeze_materials(self.store, outdir)
        self.assertEqual({"source-contribution.md", "target-no-dojo-b.md", "target-with-retrieved-dojo-c.md", "challenge.md"}, set(result["files"]))
        b = (outdir / "target-no-dojo-b.md").read_text(encoding="utf-8")
        c = (outdir / "target-with-retrieved-dojo-c.md").read_text(encoding="utf-8")
        self.assertIn(TARGET_FACTS, b)
        self.assertIn(TARGET_FACTS, c)
        self.assertNotIn("seed-m01", b)
        self.assertEqual(set(result["retrieved_source_candidate_ids"]), {line[3:].split(" v", 1)[0] for line in c.splitlines() if line.startswith("## seed-")})
        self.assertIn("verification=unverified", c)
        self.assertIn("seed-m04", c)
        self.assertIn("independence_group=unknown", c)
        self.assertIn("Store.retrieve", c)
        self.assertNotIn("facilitator-notes", c)
        self.assertIn("先问一个能区分", (outdir / "source-contribution.md").read_text(encoding="utf-8"))
        self.assertIn(CHALLENGE, (outdir / "challenge.md").read_text(encoding="utf-8"))
        with self.assertRaises(FileExistsError):
            freeze_materials(self.store, outdir)
        self.assertTrue((outdir / "target-no-dojo-b.md").is_file())


if __name__ == "__main__":
    unittest.main()
