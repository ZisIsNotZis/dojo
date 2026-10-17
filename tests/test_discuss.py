import io
import json
import stat
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from dojo.discuss import SYSTEM_PROMPT, _conclusion_sentence, run_discuss, validate_conclusion
from dojo.live import LiveConfig, LiveError
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
        self.assertEqual("no_pending", first["reason"])
        self.assertEqual("written", second["decision"])
        self.assertEqual("accepted_and_written", second["reason"])
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
            read_line=read_lines(["提出一个想法", "补充适用范围", "是的，我认可"]), output=output,
        )

        self.assertEqual(0, code)
        self.assertEqual(3, len(client.messages))
        self.assertEqual(1, len(self.store.list_candidates()))
        self.assertNotIn(invalid["statement"], json.dumps(self.store.list_candidates(), ensure_ascii=False))
        self.assertIn("我还没把边界说清楚，我们继续。", output.getvalue())

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
        self.assertEqual("no_pending", records[0]["reason"])

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
        self.assertEqual("no_pending", records[0]["reason"])
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
                self.assertEqual(2, records[-1]["requests_sent"])

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
        sentence = _conclusion_sentence(CONCLUSION)
        self.assertIn("我先这样记下来，你看有没有要改的", sentence)
        self.assertIn(CONCLUSION["statement"], sentence)
        self.assertNotIn("一致的结论", sentence)
        self.assertNotIn("双方认同", sentence)

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
