import io
import json
import tempfile
import unittest
from pathlib import Path

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


def result(answer, candidate=None):
    return {"answer": answer, "candidate": candidate}


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

    def test_conclusion_validation_requires_storage_fields_kind_and_scope(self):
        self.assertEqual(CONCLUSION, validate_conclusion(result("对话", CONCLUSION)))
        self.assertIsNone(validate_conclusion(result("继续了解")))
        for invalid in (
            {**CONCLUSION, "kind": "made_up"},
            {key: value for key, value in CONCLUSION.items() if key != "alternatives"},
            {**CONCLUSION, "scope": []},
            {**CONCLUSION, "unknowns": "还不知道"},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(LiveError):
                validate_conclusion(result("对话", invalid))

    def test_correction_cannot_save_old_conclusion_and_revised_conclusion_needs_silence(self):
        revised = {
            **CONCLUSION,
            "statement": "若目标已明确且不是疲劳或不认同导致的拖延，把任务缩成第一步可能降低启动阻力。",
            "scope": ["目标明确，且拖延并非主要由疲劳或不认同目标导致时"],
        }
        client = FakeClient([
            result("听起来你知道要做什么，但真正开始前常被其他事带走。", CONCLUSION),
            result("你指出了关键边界：拖延也可能来自疲劳或不认同，我先撤回原先过宽的说法。"),
            result("这样看来，第一步变小只对部分原因有帮助。", revised),
            result("这条修订表述得到确认。", revised),
        ])
        answers = [
            "我总在开始动手前就拖延。",
            "不对，因为有时我其实是太累了，不是任务太大。",
            "对，如果不是疲劳或不认同，拆出第一步可能有帮助。",
            "",
        ]
        output = io.StringIO()
        code = run_discuss(self.store, client=client, read_line=read_lines(answers), output=output)

        self.assertEqual(0, code)
        saved = self.store.list_candidates()
        self.assertEqual(1, len(saved))
        state = self.store.show(saved[0]["id"])["candidate"]
        self.assertEqual(revised["statement"], state["statement"])
        self.assertEqual(revised["scope"], state["scope"])
        self.assertEqual(["add"], [item["event"] for item in self.store.history(state["id"])["events"]])
        source = state["sources"][0]
        self.assertEqual("unknown", source["type"])
        self.assertEqual(source["independence_group"], state["sessions"][0])
        self.assertIn("单一会话来源", source["scope_note"])
        self.assertNotIn("我总在开始动手前就拖延", json.dumps(state, ensure_ascii=False))
        transcript = output.getvalue()
        self.assertIn("不对", " ".join(message["content"] for turn in client.messages for message in turn))
        self.assertIn("你看有没有要改的", transcript)
        self.assertNotIn("[y/N]", transcript)
        self.assertNotIn("编号选项", transcript)

    def test_empty_scope_candidate_is_discarded_and_discussion_continues(self):
        invalid = {**CONCLUSION, "statement": "不能写入的空范围结论。", "scope": []}
        client = FakeClient([
            result("我听到你开始前常会拖延。", invalid),
            result("把任务缩成第一步可能降低启动阻力。", CONCLUSION),
            result("这条结论和范围都没有需要修正的地方。", CONCLUSION),
            result("收到，你没有补充。", CONCLUSION),
        ])
        answers = ["我开始前总是拖延。", "也许拆小第一步有帮助。", "是的，这准确表达了我的意思。", ""]
        output = io.StringIO()

        code = run_discuss(self.store, client=client, read_line=read_lines(answers), output=output)

        self.assertEqual(0, code)
        self.assertEqual(4, len(client.messages))
        self.assertIn("我还没把边界说清楚，我们继续。", output.getvalue())
        saved = self.store.list_candidates()
        self.assertEqual(1, len(saved))
        state = self.store.show(saved[0]["id"])["candidate"]
        self.assertEqual(CONCLUSION["statement"], state["statement"])
        self.assertNotEqual(invalid["statement"], state["statement"])

    def test_explicit_affirmation_or_silence_saves_a_draft(self):
        for name, answers in (
            ("affirm", ["我遇到的情况", "是的，这准确表达了我的意思。"]),
            ("silent", ["我遇到的情况", ""]),
        ):
            with self.subTest(name=name):
                store = Store(self.root / f"{name}.sqlite3")
                self.addCleanup(store.close)
                client = FakeClient([
                    result("我听到的是，开始前的阻力可能和任务太大有关。", CONCLUSION),
                    result("好，这条表述与适用条件都清楚。", CONCLUSION),
                ])
                output = io.StringIO()
                code = run_discuss(store, client=client, read_line=read_lines(answers), output=output)
                self.assertEqual(0, code)
                self.assertEqual(1, len(store.list_candidates()))
                state = store.show(store.list_candidates()[0]["id"])["candidate"]
                self.assertEqual("draft", state["status"])
                self.assertEqual(CONCLUSION["statement"], state["statement"])

    def test_unset_endpoint_http_failure_and_timeout_are_clear_and_do_not_write(self):
        output = io.StringIO()
        code = run_discuss(self.store, environ={}, read_line=lambda _prompt: "", output=output)
        self.assertEqual(2, code)
        self.assertIn("DOJO_LLM_BASE_URL", output.getvalue())
        self.assertIn("未发送网络请求", output.getvalue())
        self.assertEqual([], self.store.list_candidates())

        for message, expected in (
            ("model endpoint returned HTTP 503; no candidate was saved", "HTTP 503"),
            ("model request timed out after 20 seconds; no candidate was saved", "超时"),
        ):
            with self.subTest(message=message):
                output = io.StringIO()
                client = FakeClient(error=LiveError(message))
                code = run_discuss(
                    self.store, client=client, read_line=lambda _prompt: "自然语言输入", output=output,
                )
                self.assertEqual(2, code)
                self.assertIn(expected, output.getvalue())
                self.assertIn("未写入", output.getvalue())
                self.assertEqual([], self.store.list_candidates())

    def test_prompt_requires_scoped_settlement_closure_and_identical_candidate_repeat(self):
        for instruction in (
            "适用范围、前提和未知这三样信息",
            "用户表示“我没有更多能确定的”",
            "必须立刻落定，不得追问",
            "结论可以明确带有 unknowns",
            "必须落定，并留出一轮让用户回应",
            "完全相同的 candidate 让它入库",
            "只按回车、表示没有补充或沉默，本身不自动等于认可",
            "只有用户没有对当前这条结论提出异议时",
            "即使主持人后来提出了更窄或改写后的版本",
            "必须等用户明确认可这一具体版本后",
            "若历史中存在上述异议且用户没有明确认可当前版本，必须返回 candidate=null",
        ):
            with self.subTest(instruction=instruction):
                self.assertIn(instruction, SYSTEM_PROMPT)

    def test_empty_line_calls_model_and_different_candidate_does_not_save(self):
        revised = {
            **CONCLUSION,
            "statement": "空行后模型提出了不同版本，但尚未得到用户认可。",
        }
        client = FakeClient([
            result("先形成一条待复核结论。", CONCLUSION),
            result("我根据上下文调整了结论。", revised),
        ])
        output = io.StringIO()

        code = run_discuss(
            self.store, client=client, read_line=read_lines(["提出一个想法", ""]), output=output,
        )

        self.assertEqual(0, code)
        self.assertEqual(2, len(client.messages))
        empty_turn = client.messages[1][-1]["content"]
        self.assertIn("用户这一轮没有输入内容，只按了回车表示没有要补充的", empty_turn)
        self.assertIn("空行判定约束", empty_turn)
        self.assertEqual([], self.store.list_candidates())
        self.assertIn(revised["statement"], output.getvalue())

    def test_empty_line_and_null_model_candidate_does_not_save(self):
        client = FakeClient([
            result("先形成一条待复核结论。", CONCLUSION),
            result("我先不重复这条结论。"),
        ])
        output = io.StringIO()

        code = run_discuss(
            self.store, client=client, read_line=read_lines(["提出一个想法", ""]), output=output,
        )

        self.assertEqual(0, code)
        self.assertEqual(2, len(client.messages))
        self.assertEqual([], self.store.list_candidates())
        self.assertNotIn("已写入本地草稿", output.getvalue())

    def test_empty_line_and_identical_model_candidate_saves(self):
        client = FakeClient([
            result("先形成一条待复核结论。", CONCLUSION),
            result("我判断当前结论可以按默认接受处理。", CONCLUSION),
        ])
        output = io.StringIO()

        code = run_discuss(
            self.store, client=client, read_line=read_lines(["提出一个想法", ""]), output=output,
        )

        self.assertEqual(0, code)
        self.assertEqual(2, len(client.messages))
        self.assertEqual(1, len(self.store.list_candidates()))
        self.assertIn("用户这一轮没有输入内容，只按了回车表示没有要补充的", client.messages[1][-1]["content"])

    def test_empty_line_model_timeout_does_not_save_pending_conclusion(self):
        class TimeoutOnSecondRequest:
            def __init__(self):
                self.messages = []

            def complete(self, messages):
                self.messages.append(messages)
                if len(self.messages) == 1:
                    return result("先形成一条待复核结论。", CONCLUSION)
                raise LiveError("model request timed out after 20 seconds; no candidate was saved")

        client = TimeoutOnSecondRequest()
        output = io.StringIO()

        code = run_discuss(
            self.store, client=client, read_line=read_lines(["提出一个想法", ""]), output=output,
        )

        self.assertEqual(2, code)
        self.assertEqual(2, len(client.messages))
        self.assertIn("模型请求超时", output.getvalue())
        self.assertEqual([], self.store.list_candidates())

    def test_eof_before_user_response_does_not_save_pending_conclusion(self):
        client = FakeClient([result("我听到你开始前会被任务的庞大感卡住。", CONCLUSION)])
        output = io.StringIO()

        code = run_discuss(
            self.store, client=client, read_line=read_lines(["我总难以开始。"]), output=output,
        )

        self.assertEqual(0, code)
        self.assertEqual([], self.store.list_candidates())
        transcript = output.getvalue()
        self.assertIn("我先这样记下来", transcript)
        self.assertIn("讨论在你表态前结束，这条结论未保存。", transcript)
        self.assertIn("讨论已结束；会话原文未保存。", transcript)
        self.assertNotIn(CONCLUSION["statement"], json.dumps(self.store.list_candidates(), ensure_ascii=False))

    def test_conclusion_sentence_invites_correction_without_presuming_agreement(self):
        sentence = _conclusion_sentence(CONCLUSION)
        self.assertIn(f"我先这样记下来，你看有没有要改的：『{CONCLUSION['statement']}』", sentence)
        self.assertIn("适用范围是知道目标但因任务显得庞大而迟迟未开始时", sentence)
        self.assertNotIn("一致的结论", sentence)
        self.assertNotIn("双方认同", sentence)

    def test_model_context_includes_round_number_and_late_round_convergence_signal(self):
        answers = [f"第 {number} 轮的自然语言输入" for number in range(1, 10)]
        client = FakeClient([result("我会继续理解这件事。") for _ in answers])
        output = io.StringIO()

        code = run_discuss(self.store, client=client, read_line=read_lines(answers), output=output)

        self.assertEqual(0, code)
        self.assertEqual(9, len(client.messages))
        user_contexts = [turn[-1]["content"] for turn in client.messages]
        for number, context in enumerate(user_contexts, start=1):
            with self.subTest(round_number=number):
                self.assertIn(f"本次讨论第 {number} 轮 / 最多 12 轮。", context)
        self.assertNotIn("轮次已接近上限", user_contexts[7])
        self.assertIn("轮次已接近上限，请尽快落定", user_contexts[8])

    def test_request_keeps_litellm_json_workaround_and_transcript_is_not_stored(self):
        client = FakeClient([result("我们还需要了解这件事。"), result("收到，没有补充。")])
        answers = ["这是只存在于本次内存的原文。", ""]
        output = io.StringIO()
        code = run_discuss(
            self.store, config=LiveConfig("http://127.0.0.1:4000/v1/chat/completions", "test", None),
            client=client, read_line=read_lines(answers), output=output,
        )
        self.assertEqual(0, code)
        self.assertEqual(2, len(client.messages))
        user_messages = [message["content"] for turn in client.messages for message in turn if message["role"] == "user"]
        self.assertIn("json", user_messages[-1])
        self.assertIn("这是只存在于本次内存的原文", user_messages[-2])
        self.assertIn("用户这一轮没有输入内容，只按了回车表示没有要补充的", user_messages[-1])
        self.assertEqual([], self.store.list_candidates())


if __name__ == "__main__":
    unittest.main()
