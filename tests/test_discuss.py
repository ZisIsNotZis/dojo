import io
import json
import stat
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from dojo.discuss import SYSTEM_PROMPT, _conclusion_sentence, _trace_error, run_discuss, validate_conclusion
from dojo.live import MAX_DISCUSS_ERROR_DETAIL_CHARS, MAX_DISCUSS_RAW_RESPONSE_CHARS, LiveConfig, LiveError
from dojo.storage import Store


CONCLUSION = {
    "statement": "开始前把任务缩成一个可执行的第一步，可能降低启动阻力。",
    "kind": "application",
    "scope": ["知道目标但因任务显得庞大而迟迟未开始时"],
    "premises": ["用户知道自己要做什么"],
    "alternatives": ["疲劳或不认同目标可能是主要原因"],
    "contradictions": ["第一步仍不清楚时，缩小任务未必有帮助"],
    "unknowns": ["这种做法对该用户是否有效尚未验证"],
}

TRACE_FIELDS = {
    "seq", "at", "user", "answer", "candidate", "stance", "decision", "reason", "requests_sent",
    "pending_after", "raw_response", "finish_reason", "error", "reasoning_effort",
    "reasoning_effort_fallback", "attempts",
}


def result(answer, candidate=None, user_stance="neutral"):
    return {"answer": answer, "candidate": candidate, "user_stance": user_stance}


def read_lines(lines):
    iterator = iter(lines)

    def read_line(_prompt):
        try:
            return next(iterator)
        except StopIteration:
            raise EOFError

    return read_line


class FakeClient:
    def __init__(self, responses=None, error=None):
        self.responses = list(responses or [])
        self.error = error
        self.messages = []

    def complete(self, messages):
        self.messages.append(messages)
        if self.error is not None:
            raise self.error
        return self.responses.pop(0)


class DiscussTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "dojo.sqlite3")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def trace_records(self):
        path = next((self.root / "sessions").glob("*.jsonl"))
        return path, [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def test_conclusion_validation_requires_storage_fields_kind_and_scope(self):
        self.assertEqual(CONCLUSION, validate_conclusion(result("对话", CONCLUSION)))
        self.assertIsNone(validate_conclusion(result("继续了解")))
        with self.assertRaises(LiveError):
            validate_conclusion({"answer": "对话", "candidate": CONCLUSION})
        for invalid in (
            {**CONCLUSION, "kind": "made_up"},
            {key: value for key, value in CONCLUSION.items() if key != "alternatives"},
            {**CONCLUSION, "scope": []},
            {**CONCLUSION, "unknowns": "还不知道"},
            {**result("对话", CONCLUSION), "user_stance": "maybe"},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(LiveError):
                validate_conclusion(result("对话", invalid))

    def test_explicit_acceptance_writes_immediately_and_trace_has_complete_rounds(self):
        client = FakeClient([
            result("我听到你开始时常被任务太大卡住。", CONCLUSION),
            result("好，我会按这条具体表述记下来。", CONCLUSION, user_stance="accept"),
        ])
        answers = iter(["  我总在开始动手前就拖延。  ", "是的，这准确表达了我的意思。"])
        prompt_calls = 0

        def read_line(_prompt):
            nonlocal prompt_calls
            prompt_calls += 1
            if prompt_calls == 3:
                self.assertEqual(1, len(self.store.list_candidates()), "acceptance must save before the next prompt")
                raise EOFError
            return next(answers)

        output = io.StringIO()
        code = run_discuss(self.store, client=client, read_line=read_line, output=output)

        self.assertEqual(0, code)
        saved = self.store.list_candidates()
        self.assertEqual(1, len(saved))
        state = self.store.show(saved[0]["id"])["candidate"]
        self.assertEqual(CONCLUSION["statement"], state["statement"])
        self.assertEqual("unknown", state["sources"][0]["type"])
        self.assertEqual(state["sessions"][0], state["sources"][0]["independence_group"])
        self.assertNotIn("我总在开始动手前就拖延", json.dumps(state, ensure_ascii=False))
        path, records = self.trace_records()
        self.assertEqual(0o700, stat.S_IMODE(path.parent.stat().st_mode))
        self.assertEqual(0o600, stat.S_IMODE(path.stat().st_mode))
        self.assertEqual(3, len(records))
        first, second, end = records
        for row in (first, second):
            self.assertEqual(TRACE_FIELDS, set(row))
            datetime.fromisoformat(row["at"])
        self.assertEqual("  我总在开始动手前就拖延。  ", first["user"])
        self.assertEqual(CONCLUSION, first["candidate"])
        self.assertEqual("none", first["decision"])
        self.assertEqual("proposed_new_pending", first["reason"])
        self.assertEqual(CONCLUSION["statement"], first["pending_after"])
        self.assertEqual("written", second["decision"])
        self.assertEqual("accepted_and_written", second["reason"])
        self.assertIsNone(second["pending_after"])
        self.assertEqual(2, second["requests_sent"])
        self.assertEqual({"event", "reason", "saved", "requests_sent"}, set(end))
        self.assertEqual("session_end", end["event"])
        self.assertEqual("eof", end["reason"])
        self.assertEqual([saved[0]["id"]], end["saved"])
        self.assertEqual(2, end["requests_sent"])
        self.assertIn(str(path), output.getvalue())

    def test_empty_line_skips_model_and_trace_then_explicit_acceptance_saves(self):
        client = FakeClient([
            result("先形成一条待复核结论。", CONCLUSION),
            result("你明确认可这条结论，我会记下来。", CONCLUSION, user_stance="accept"),
        ])
        output = io.StringIO()
        code = run_discuss(
            self.store, client=client,
            read_line=read_lines(["提出一个想法", "", "是的，我认可这条表述。"]), output=output,
        )

        self.assertEqual(0, code)
        self.assertEqual(2, len(client.messages), "blank input must not consume a model request")
        self.assertEqual(1, len(self.store.list_candidates()))
        _, records = self.trace_records()
        rounds = records[:-1]
        self.assertEqual(["提出一个想法", "是的，我认可这条表述。"], [row["user"] for row in rounds])
        self.assertNotIn("", [row["user"] for row in rounds])
        self.assertEqual(2, records[-1]["requests_sent"])

    def test_discuss_keeps_history_longer_than_eight_messages_for_the_model(self):
        responses = [result(f"第{index}轮的主持人回答。") for index in range(1, 7)]
        client = FakeClient(responses)
        user_turns = [f"第{index}轮较长讨论输入，继续补充之前的边界。" for index in range(1, 7)]

        code = run_discuss(
            self.store, client=client, read_line=read_lines(user_turns), output=io.StringIO(),
        )

        self.assertEqual(0, code)
        self.assertEqual(6, len(client.messages))
        sixth_request = client.messages[5]
        self.assertEqual(12, len(sixth_request))
        self.assertIn(user_turns[0], sixth_request[1]["content"])
        self.assertEqual("第1轮的主持人回答。", sixth_request[2]["content"])
        self.assertEqual("第5轮的主持人回答。", sixth_request[10]["content"])

    def test_closure_or_uncertainty_is_not_acceptance(self):
        client = FakeClient([
            result("先形成一条待复核结论。", CONCLUSION),
            result("那我这样记下来，行吗？", CONCLUSION, user_stance="neutral"),
        ])
        output = io.StringIO()

        code = run_discuss(
            self.store, client=client,
            read_line=read_lines(["提出一个想法", "不确定，我没有更多了"]), output=output,
        )

        self.assertEqual(0, code)
        self.assertEqual([], self.store.list_candidates())
        self.assertIn("那我这样记下来，行吗？", output.getvalue())
        _, records = self.trace_records()
        self.assertEqual("awaiting_accept", records[1]["reason"])
        self.assertEqual("none", records[1]["decision"])

    def test_revision_after_rejection_requires_acceptance_of_exact_revised_candidate(self):
        revised = {
            **CONCLUSION,
            "statement": "若拖延不是由疲劳或不认同造成，把任务缩成第一步可能降低启动阻力。",
            "scope": ["目标明确且拖延并非主要由疲劳或不认同导致时"],
        }
        client = FakeClient([
            result("先形成一条待复核结论。", CONCLUSION),
            result("你指出了重要边界，我调整结论。", revised, user_stance="reject"),
            result("这样我就按这个带边界的版本记录。", revised, user_stance="accept"),
        ])
        output = io.StringIO()
        code = run_discuss(
            self.store, client=client,
            read_line=read_lines(["提出一个想法", "不对，疲劳时并非任务太大", "是的，修订后的说法准确。"]),
            output=output,
        )

        self.assertEqual(0, code)
        self.assertEqual(1, len(self.store.list_candidates()))
        state = self.store.show(self.store.list_candidates()[0]["id"])["candidate"]
        self.assertEqual(revised["statement"], state["statement"])
        _, records = self.trace_records()
        self.assertEqual("candidate_changed", records[1]["reason"])
        self.assertEqual("written", records[2]["decision"])

    def test_invalid_candidate_is_discarded_before_a_later_valid_acceptance(self):
        invalid = {**CONCLUSION, "statement": "缺少边界的候选。", "scope": []}
        client = FakeClient([
            result("我还没把边界说清楚，我们继续。", invalid),
            result("可以暂定这条带范围的结论。", CONCLUSION),
            result("我明确认可这条结论。", CONCLUSION, user_stance="accept"),
        ])
        output = io.StringIO()
        code = run_discuss(
            self.store, client=client,
            read_line=read_lines(["提出一个想法", "是的，我认可"]), output=output,
        )

        self.assertEqual(0, code)
        self.assertEqual(3, len(client.messages))
        self.assertEqual(1, len(self.store.list_candidates()))
        self.assertNotIn(invalid["statement"], json.dumps(self.store.list_candidates(), ensure_ascii=False))
        self.assertNotIn("我还没把边界说清楚，我们继续。", output.getvalue())

    def test_acceptance_of_a_different_candidate_does_not_write_previous_pending(self):
        changed = {**CONCLUSION, "statement": "和旧候选不同的新版本。"}
        client = FakeClient([
            result("先形成一条待复核结论。", CONCLUSION),
            result("我给出一条修订后的候选。", changed, user_stance="accept"),
        ])
        output = io.StringIO()
        code = run_discuss(
            self.store, client=client,
            read_line=read_lines(["提出一个想法", "我同意你前面说的版本"]), output=output,
        )

        self.assertEqual(0, code)
        self.assertEqual([], self.store.list_candidates())
        _, records = self.trace_records()
        self.assertEqual("candidate_changed", records[1]["reason"])
        self.assertEqual("none", records[1]["decision"])
        self.assertEqual([], records[-1]["saved"])

    def test_eof_before_acceptance_does_not_write_and_records_eof(self):
        client = FakeClient([result("我先复述这条结论。", CONCLUSION)])
        output = io.StringIO()
        code = run_discuss(
            self.store, client=client, read_line=read_lines(["我总难以开始。"]), output=output,
        )

        self.assertEqual(0, code)
        self.assertEqual([], self.store.list_candidates())
        _, records = self.trace_records()
        self.assertEqual("eof", records[-1]["reason"])
        self.assertEqual([], records[-1]["saved"])
        self.assertEqual("proposed_new_pending", records[0]["reason"])
        self.assertEqual(CONCLUSION["statement"], records[0]["pending_after"])

    def test_request_limit_does_not_write_pending_candidate(self):
        client = FakeClient([result("先形成一条待复核结论。", CONCLUSION)])
        output = io.StringIO()
        with patch("dojo.discuss.MAX_MODEL_REQUESTS", 1):
            code = run_discuss(
                self.store, client=client,
                read_line=read_lines(["提出一个想法", "是的，我认可"]), output=output,
            )

        self.assertEqual(0, code)
        self.assertEqual(1, len(client.messages))
        self.assertEqual([], self.store.list_candidates())
        _, records = self.trace_records()
        self.assertEqual("limit", records[-1]["reason"])
        self.assertEqual(1, records[-1]["requests_sent"])

    def test_accept_without_previous_pending_and_reject_do_not_write(self):
        client = FakeClient([
            result("我先给出这条候选，你可以再看。", CONCLUSION, user_stance="accept"),
            result("这条仍然等待明确认可。", CONCLUSION, user_stance="neutral"),
            result("你目前没有同意这条说法。", CONCLUSION, user_stance="reject"),
        ])
        output = io.StringIO()
        code = run_discuss(
            self.store, client=client,
            read_line=read_lines(["提出一个想法", "继续", "我不认可这条表述"]), output=output,
        )

        self.assertEqual(0, code)
        self.assertEqual([], self.store.list_candidates())
        _, records = self.trace_records()
        self.assertEqual("proposed_new_pending", records[0]["reason"])
        self.assertEqual(CONCLUSION["statement"], records[0]["pending_after"])
        self.assertEqual("awaiting_accept", records[1]["reason"])
        self.assertEqual("stance_not_accept", records[2]["reason"])

    def test_keyboard_interrupt_does_not_write_and_records_cancel(self):
        client = FakeClient([result("先形成一条待复核结论。", CONCLUSION)])
        reads = iter(["提出一个想法"])

        def interrupted(_prompt):
            try:
                return next(reads)
            except StopIteration:
                raise KeyboardInterrupt

        output = io.StringIO()
        code = run_discuss(self.store, client=client, read_line=interrupted, output=output)

        self.assertEqual(0, code)
        self.assertEqual([], self.store.list_candidates())
        _, records = self.trace_records()
        self.assertEqual("cancel", records[-1]["reason"])

    def test_keyboard_interrupt_during_request_records_interrupted_round(self):
        client = FakeClient(error=KeyboardInterrupt())
        original_text = "  请求发出后被中断。  "
        output = io.StringIO()
        code = run_discuss(
            self.store, client=client,
            read_line=read_lines([original_text]), output=output,
        )

        self.assertEqual(0, code)
        self.assertEqual([], self.store.list_candidates())
        _, records = self.trace_records()
        self.assertEqual(2, len(records))
        round_record, end = records
        self.assertEqual(original_text, round_record["user"])
        self.assertEqual(1, round_record["seq"])
        self.assertEqual(1, round_record["requests_sent"])
        self.assertIsNone(round_record["candidate"])
        self.assertEqual("none", round_record["decision"])
        self.assertEqual("interrupted", round_record["reason"])
        self.assertIsNone(round_record["pending_after"])
        self.assertEqual("session_end", end["event"])
        self.assertEqual("cancel", end["reason"])
        self.assertEqual(1, end["requests_sent"])

    def test_http_5xx_retries_once_but_http_4xx_exits_immediately(self):
        transient = LiveError("model endpoint returned HTTP 503", kind="http_error", http_status=503, raw_response="busy")
        client = FakeClient([result("恢复后继续。"), result("之后结束。")])
        client.complete = self._responses_then_error(client, [transient])
        output = io.StringIO()
        code = run_discuss(
            self.store, client=client, read_line=read_lines(["先请求", "再请求"]), output=output,
        )
        self.assertEqual(0, code)
        self.assertIn("已重试并恢复", output.getvalue())
        self.assertEqual(3, len(client.messages))
        _, records = self.trace_records()
        self.assertEqual("busy", records[0]["attempts"][0]["raw_response"])
        self.assertEqual(503, records[0]["attempts"][0]["error"]["http_status"])

        unauthorized = LiveError("model endpoint returned HTTP 401", kind="http_error", http_status=401, raw_response="unauthorized")
        output = io.StringIO()
        code = run_discuss(
            self.store, client=FakeClient(error=unauthorized),
            read_line=read_lines(["请求不会自动重复"]), output=output,
        )
        self.assertEqual(2, code)
        self.assertIn("端点配置或请求契约有误", output.getvalue())
        trace_path = Path([
            line.split("：", 1)[1].strip()
            for line in output.getvalue().splitlines()
            if line.startswith("本场会话轨迹：")
        ][0])
        records = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(401, records[-2]["error"]["http_status"])
        self.assertEqual(1, records[-2]["requests_sent"])

    @staticmethod
    def _responses_then_error(client, errors):
        remaining = list(client.responses)
        client.responses.clear()
        planned = list(errors)
        calls = []

        def complete(messages):
            client.messages.append(messages)
            calls.append(len(calls))
            if planned:
                raise planned.pop(0)
            return remaining.pop(0)

        return complete

    def test_http_and_timeout_failure_after_pending_never_write(self):
        for message in (
            "model endpoint returned HTTP 503; no candidate was saved",
            "model request timed out after 20 seconds; no candidate was saved",
        ):
            with self.subTest(message=message):
                class FailAfterFirstResponse:
                    def __init__(self):
                        self.calls = 0

                    def complete(inner_self, _messages):
                        inner_self.calls += 1
                        if inner_self.calls == 1:
                            return result("先形成一条待复核结论。", CONCLUSION)
                        raise LiveError(message)

                client = FailAfterFirstResponse()
                output = io.StringIO()
                code = run_discuss(
                    self.store, client=client,
                    read_line=read_lines(["提出一个想法", "继续回应"]), output=output,
                )

                self.assertEqual(2, code)
                self.assertEqual([], self.store.list_candidates())
                _, records = self.trace_records()
                self.assertEqual("failure", records[-1]["reason"])
                self.assertEqual("failure", records[-2]["reason"])
                self.assertEqual(3, records[-1]["requests_sent"])

    def test_no_trace_creates_no_file_and_does_not_save_raw_input(self):
        trace_dir = self.root / "custom-sessions"
        client = FakeClient([
            result("先形成一条待复核结论。", CONCLUSION),
            result("明确认可。", CONCLUSION, user_stance="accept"),
        ])
        output = io.StringIO()
        code = run_discuss(
            self.store, client=client, no_trace=True,
            environ={"DOJO_SESSIONS": str(trace_dir)},
            read_line=read_lines(["secret raw phrase that must not persist", "我明确认可这条结论"]),
            output=output,
        )

        self.assertEqual(0, code)
        self.assertFalse(trace_dir.exists())
        self.assertIn("--no-trace", output.getvalue())
        self.assertIn("本场会话轨迹：已关闭", output.getvalue())
        self.assertEqual(1, len(self.store.list_candidates()))
        persisted = json.dumps(self.store.show(self.store.list_candidates()[0]["id"]), ensure_ascii=False)
        self.assertNotIn("secret raw phrase that must not persist", persisted)

    def test_trace_write_failure_warns_once_and_discussion_continues(self):
        blocked = self.root / "not-a-directory"
        blocked.write_text("block", encoding="utf-8")
        client = FakeClient([result("我会继续了解。")])
        output = io.StringIO()
        code = run_discuss(
            self.store, client=client, environ={"DOJO_SESSIONS": str(blocked / "sessions")},
            read_line=read_lines(["继续谈这个问题"]), output=output,
        )

        self.assertEqual(0, code)
        self.assertEqual(1, len(client.messages))
        self.assertEqual([], self.store.list_candidates())
        self.assertEqual(1, output.getvalue().count("会话轨迹写入失败"))
        self.assertIn("讨论已结束", output.getvalue())

    def test_environment_override_places_trace_in_requested_directory(self):
        custom = self.root / "sessions-override"
        client = FakeClient([result("继续了解。")])
        output = io.StringIO()
        code = run_discuss(
            self.store, client=client, environ={"DOJO_SESSIONS": str(custom)},
            read_line=read_lines(["一个想法"]), output=output,
        )

        self.assertEqual(0, code)
        paths = list(custom.glob("*.jsonl"))
        self.assertEqual(1, len(paths))
        self.assertIn(str(paths[0]), output.getvalue())
        self.assertEqual(0o700, stat.S_IMODE(custom.stat().st_mode))

    def test_reasoning_effort_rejection_retries_without_field_and_traces_downgrade(self):
        class RejectingClient(FakeClient):
            def __init__(self):
                super().__init__()
                self.reasoning_effort = None
                self.efforts = []

            def complete(inner_self, messages):
                inner_self.messages.append(messages)
                inner_self.efforts.append(inner_self.reasoning_effort)
                if inner_self.reasoning_effort is not None:
                    raise LiveError(
                        "model endpoint returned HTTP 400; no candidate was saved",
                        kind="http_error", http_status=400,
                        raw_response='{"error":{"message":"unsupported reasoning_effort"}}',
                    )
                return result("已在不带推理字段的请求后继续。")

        client = RejectingClient()
        output = io.StringIO()
        code = run_discuss(
            self.store, client=client, environ={"DOJO_LLM_REASONING": "high"},
            read_line=read_lines(["继续讨论"]), output=output,
        )

        self.assertEqual(0, code, output.getvalue())
        self.assertEqual(["high", None], client.efforts)
        self.assertIn("已改为不带该字段重试", output.getvalue())
        _, records = self.trace_records()
        row = records[0]
        self.assertEqual(2, row["requests_sent"])
        self.assertIsNone(row["reasoning_effort"])
        self.assertTrue(row["reasoning_effort_fallback"])
        self.assertTrue(row["attempts"][0]["reasoning_effort_fallback"])
        self.assertIsNone(row["error"])
        self.assertEqual(2, records[-1]["requests_sent"])

    def test_reasoning_effort_invalid_value_fails_before_model_or_trace(self):
        client = FakeClient([result("不会调用")])
        output = io.StringIO()
        code = run_discuss(
            self.store, client=client, environ={"DOJO_LLM_REASONING": "extreme"},
            read_line=read_lines(["不可达"]), output=output,
        )

        self.assertEqual(2, code)
        self.assertIn("DOJO_LLM_REASONING 只允许 low、medium 或 high", output.getvalue())
        self.assertIn("未发送网络请求", output.getvalue())
        self.assertEqual([], client.messages)
        self.assertFalse((self.root / "sessions").exists())

    def test_discuss_error_detail_uses_65536_character_safety_envelope(self):
        error = LiveError("诊断", detail="d" * (MAX_DISCUSS_ERROR_DETAIL_CHARS + 1))
        traced = _trace_error(error)
        self.assertEqual(65_536, len(traced["detail"]))
        self.assertEqual("d" * 65_536, traced["detail"])

    def test_discuss_trace_keeps_full_answer_and_pending_candidate(self):
        statement = "结" * 65_536
        candidate = {
            "statement": statement,
            "kind": "abstract_idea",
            "scope": ["当前经验范围"],
            "premises": [],
            "alternatives": [],
            "contradictions": [],
            "unknowns": [],
        }
        client = FakeClient([result("完整回答保存在轨迹中。", candidate)])
        output = io.StringIO()
        code = run_discuss(
            self.store, client=client, environ={},
            read_line=read_lines(["请保留长候选"]), output=output,
        )

        self.assertEqual(0, code)
        _, records = self.trace_records()
        row = records[0]
        self.assertEqual("完整回答保存在轨迹中。", row["answer"])
        self.assertEqual(statement, row["pending_after"])
        self.assertEqual(statement, row["candidate"]["statement"])

    def test_raw_response_trace_preserves_exactly_the_65536_character_boundary(self):
        self.assertEqual(65_536, MAX_DISCUSS_RAW_RESPONSE_CHARS)
        for raw, expected in (("x" * 65_536, "x" * 65_536), ("y" * 65_537, "y" * 65_536)):
            with self.subTest(source_length=len(raw)):
                client = FakeClient([{
                    **result("有效回答。"),
                    "raw_response": raw,
                }])
                output = io.StringIO()
                code = run_discuss(
                    self.store, client=client, environ={},
                    read_line=read_lines(["记录长响应"]), output=output,
                )
                self.assertEqual(0, code)
                trace_path = Path([
                    line.split("：", 1)[1].strip()
                    for line in output.getvalue().splitlines()
                    if line.startswith("本场会话轨迹：")
                ][0])
                row = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[0])
                self.assertEqual(expected, row["raw_response"])
                self.assertEqual(expected, row["attempts"][0]["raw_response"])

    def test_unset_endpoint_fails_before_trace_or_database_changes(self):
        output = io.StringIO()
        code = run_discuss(self.store, environ={}, read_line=lambda _prompt: "", output=output)
        self.assertEqual(2, code)
        self.assertIn("DOJO_LLM_BASE_URL", output.getvalue())
        self.assertIn("未发送网络请求", output.getvalue())
        self.assertFalse((self.root / "sessions").exists())
        self.assertEqual([], self.store.list_candidates())

    def test_system_prompt_requires_explicit_acceptance_and_neutral_closure(self):
        for instruction in (
            "accept 仅表示用户明确认可当前这条具体结论",
            "用户表示没有更多、不确定、就这样、差不多或类似收束语时必须报告 neutral",
            "自然地询问“那我这样记下来，行吗？”",
            "只有用户明确认可当前这条具体结论时",
            "不得将空行、EOF、取消或沉默当作用户回应",
        ):
            with self.subTest(instruction=instruction):
                self.assertIn(instruction, SYSTEM_PROMPT)

    def test_conclusion_sentence_invites_correction_without_presuming_agreement(self):
        sentence = _conclusion_sentence({**CONCLUSION, "scope": ["适用范围。"]})
        self.assertIn("我先这样记下来，你看有没有要改的", sentence)
        self.assertIn(CONCLUSION["statement"], sentence)
        self.assertNotIn("。。", sentence)
        self.assertEqual("。", sentence[-1])
        self.assertNotIn("一致的结论", sentence)
        self.assertNotIn("双方认同", sentence)

    def test_invalid_output_retries_with_correction_and_records_raw_diagnostics(self):
        invalid = {**result("格式错误", CONCLUSION), "extra": True}
        client = FakeClient([invalid, result("有效输出。", CONCLUSION)])
        output = io.StringIO()
        code = run_discuss(
            self.store, client=client, read_line=read_lines(["提出一个想法"]), output=output,
        )

        self.assertEqual(0, code)
        self.assertEqual(2, len(client.messages))
        self.assertIn("纠正指令", client.messages[1][-1]["content"])
        _, records = self.trace_records()
        row = records[0]
        self.assertEqual("schema_violation", row["attempts"][0]["error"]["kind"])
        self.assertIn('"extra": true', row["attempts"][0]["raw_response"])
        self.assertEqual("有效输出。", json.loads(row["raw_response"])["answer"])
        self.assertIsNone(row["error"])
        self.assertIn("finish_reason", row)

    def test_retry_exhaustion_records_invalid_output_and_keeps_conversation_open(self):
        invalid = {**result("格式错误", CONCLUSION), "extra": True}
        client = FakeClient([invalid, invalid, invalid, result("继续讨论。")])
        output = io.StringIO()
        code = run_discuss(
            self.store, client=client,
            read_line=read_lines(["第一轮", "第二轮仍可继续"]), output=output,
        )

        self.assertEqual(0, code)
        self.assertEqual(4, len(client.messages))
        self.assertIn("自动重试仍未成功", output.getvalue())
        _, records = self.trace_records()
        first, second, end = records
        self.assertEqual("invalid_output", first["reason"])
        self.assertEqual("none", first["decision"])
        self.assertEqual("schema_violation", first["error"]["kind"])
        self.assertEqual(3, first["requests_sent"])
        self.assertEqual("第二轮仍可继续", second["user"])
        self.assertEqual(4, second["requests_sent"])
        self.assertEqual("eof", end["reason"])

    def test_finish_reason_length_is_truncated_and_traced(self):
        truncated = {**result("部分 JSON", None), "finish_reason": "length", "raw_response": '{"partial":'}
        client = FakeClient([truncated, truncated, truncated])
        output = io.StringIO()
        code = run_discuss(
            self.store, client=client, read_line=read_lines(["触发截断"]), output=output,
        )

        self.assertEqual(0, code)
        _, records = self.trace_records()
        row = records[0]
        self.assertEqual("invalid_output", row["reason"])
        self.assertEqual("truncated", row["error"]["kind"])
        self.assertEqual("length", row["error"]["finish_reason"])
        self.assertEqual("length", row["finish_reason"])
        self.assertEqual('{"partial":', row["raw_response"])

    def test_resume_rebuilds_history_and_appends_to_same_trace(self):
        first = FakeClient([result("先讨论了第一点。", CONCLUSION)])
        output = io.StringIO()
        self.assertEqual(0, run_discuss(
            self.store, client=first, read_line=read_lines(["第一轮用户原话"]), output=output,
        ))
        path, original_records = self.trace_records()
        session = path.stem
        second = FakeClient([result("我理解你补充的内容。")])
        output = io.StringIO()
        self.assertEqual(0, run_discuss(
            self.store, client=second, resume=path,
            read_line=read_lines(["续跑补充内容"]), output=output,
        ))

        appended = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(original_records) + 2, len(appended))
        self.assertEqual(session, path.stem)
        self.assertEqual(2, appended[-2]["seq"])
        self.assertEqual(2, appended[-2]["requests_sent"])
        messages = second.messages[0]
        self.assertIn("第一轮用户原话", json.dumps(messages, ensure_ascii=False))
        self.assertIn(CONCLUSION["statement"], json.dumps(messages, ensure_ascii=False))
        self.assertIn("正在续跑会话", output.getvalue())

    def test_round_context_advances_only_for_nonempty_model_requests(self):
        client = FakeClient([result("继续了解。"), result("继续了解。")])
        output = io.StringIO()
        code = run_discuss(
            self.store, client=client,
            read_line=read_lines(["第一轮", "", "第三个输入"]), output=output,
        )

        self.assertEqual(0, code)
        self.assertEqual(2, len(client.messages))
        contexts = [turn[-1]["content"] for turn in client.messages]
        self.assertIn("讨论第 1 轮", contexts[0])
        self.assertIn("讨论第 2 轮", contexts[1])
        self.assertNotIn("用户这一轮没有输入内容", contexts[1])


if __name__ == "__main__":
    unittest.main()
