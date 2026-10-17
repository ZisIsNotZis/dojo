import io
import json
import tempfile
import unittest
from pathlib import Path

from dojo.discuss import run_discuss, validate_conclusion
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
        self.assertIn("你可以直接纠正", transcript)
        self.assertNotIn("[y/N]", transcript)
        self.assertNotIn("编号选项", transcript)

    def test_empty_scope_candidate_is_discarded_and_discussion_continues(self):
        invalid = {**CONCLUSION, "statement": "不能写入的空范围结论。", "scope": []}
        client = FakeClient([
            result("我听到你开始前常会拖延。", invalid),
            result("把任务缩成第一步可能降低启动阻力。", CONCLUSION),
            result("这条结论和范围都没有需要修正的地方。", CONCLUSION),
        ])
        answers = ["我开始前总是拖延。", "也许拆小第一步有帮助。", "是的，这准确表达了我的意思。", ""]
        output = io.StringIO()

        code = run_discuss(self.store, client=client, read_line=read_lines(answers), output=output)

        self.assertEqual(0, code)
        self.assertEqual(3, len(client.messages))
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

    def test_request_keeps_litellm_json_workaround_and_transcript_is_not_stored(self):
        client = FakeClient([result("我们还需要了解这件事。")])
        answers = ["这是只存在于本次内存的原文。", ""]
        output = io.StringIO()
        code = run_discuss(
            self.store, config=LiveConfig("http://127.0.0.1:4000/v1/chat/completions", "test", None),
            client=client, read_line=read_lines(answers), output=output,
        )
        self.assertEqual(0, code)
        user_messages = [message["content"] for turn in client.messages for message in turn if message["role"] == "user"]
        self.assertIn("json", user_messages[-1])
        self.assertIn("这是只存在于本次内存的原文", user_messages[-1])
        self.assertEqual([], self.store.list_candidates())


if __name__ == "__main__":
    unittest.main()
