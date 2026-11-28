"""One conversation is about one sentence -- including when the library moves under it.

The independent review of this chain (task #3396) found two sentences that spoke for facts
the program had not checked:

  1. On `--resume` after a `--card` start, one request carried the card twice in two
     versions: the handout row (the wording that was on screen) and `本场已有的结论`,
     which was read out of the library at resume time. Revise the card between the two
     halves of the conversation and the model is told the session holds the old sentence
     and the new one at once. Reproduced on `4cd8905`, so it is older than this slice.
  2. The receipt's last clause said the card 之后没改过 -- a claim about the library. Run
     `revise` on that card while the four questions are being asked and the library holds
     a newer version, so the sentence is false. What this session can know is what this
     session did: the four answers did not change the card.

Both are checked here against the request the model actually receives and the receipt the
person actually reads, not against what the code intends.
"""
import io
import json
import re
import tempfile
import unittest
from pathlib import Path

from dojo.discuss import run_discuss
from dojo.storage import Store

OPENED = "持续检查交给系统自己跑，但只在检查结果会打断他时才叫醒他。"
NARROWED = "持续检查交给系统自己跑，只在结果会打断他、而且他真的会看时才叫醒他。"
REASON = "上一次是检查跑完了我也没看，所以叫醒的条件得更窄。"


def conclusion(statement=OPENED):
    return {
        "statement": statement, "kind": "abstract_idea",
        "scope": ["他已经抽身的时候"], "premises": ["系统能自己跑检查"],
        "alternatives": ["把检查留给人"], "contradictions": ["检查必须发生在世界里时"],
        "unknowns": ["他会不会来看回执"],
    }


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete(self, messages):
        self.calls.append(messages)
        return self.responses.pop(0)


def read_lines(lines):
    iterator = iter(lines)

    def read_line(_prompt):
        try:
            return next(iterator)
        except StopIteration:
            raise EOFError
    return read_line


def user_context(call):
    for message in reversed(call):
        if message["role"] == "user":
            return message["content"]
    raise AssertionError("no user message in the request")


class OpenedCardStaysOneVersion(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "dojo.sqlite3")
        self.addCleanup(self.store.close)

    def card(self):
        # Field for field the same content the model will hand back, so the session's
        # save lands on *this* card (same id) rather than minting a second one. The
        # reviewer's reproduction depends on that: only when the saved id is the handed
        # id does the resume path take the branch that reached into the library.
        fields = conclusion(OPENED)
        added = self.store.add(
            statement=OPENED, kind="abstract_idea", scope=fields["scope"],
            premises=fields["premises"], alternatives=fields["alternatives"],
            contradictions=fields["contradictions"], unknowns=fields["unknowns"],
            session="sess-A",
        )
        self.store.record_acceptance(added["id"], "sess-A", path="discuss_conclusion")
        self.store.confirm(added["id"], "他在会话里认可了这句；不表示为真", session="sess-A")
        return added["id"]

    def trace(self):
        return next((self.root / "sessions").glob("*.jsonl"))

    def test_a_revise_between_the_halves_does_not_put_two_versions_in_one_request(self):
        candidate_id = self.card()
        first = FakeClient([
            {"answer": "那我们把这句当成现在这一版。", "candidate": conclusion(),
             "user_stance": "neutral"},
            {"answer": "好，就这句。", "candidate": conclusion(), "user_stance": "accept"},
            {"answer": "接着说。", "candidate": None, "user_stance": "neutral"},
        ])
        code = run_discuss(
            self.store, client=first, card=candidate_id,
            read_line=read_lines(["接着上次那条说", "对，就这么定", "还有一点"]),
            output=io.StringIO(), environ={},
        )
        self.assertEqual(0, code)

        # The library moves under the conversation, exactly as a second terminal could.
        self.store.revise(
            candidate_id, NARROWED, REASON, scope=["他已经抽身的时候"],
            premises=["系统能自己跑检查"], session="sess-B",
        )

        resumed_client = FakeClient([
            {"answer": "继续说。", "candidate": None, "user_stance": "neutral"},
        ])
        output = io.StringIO()
        code = run_discuss(
            self.store, client=resumed_client, resume=self.trace(),
            read_line=read_lines(["继续"]), output=output, environ={},
        )
        self.assertEqual(0, code, output.getvalue())
        sent = user_context(resumed_client.calls[-1])
        # One conversation, one sentence: the version that was on screen.
        self.assertIn(OPENED, sent)
        self.assertNotIn(NARROWED, sent,
                         "the resumed request carried a version the session never showed")
        self.assertNotIn(REASON, sent)

    def test_the_same_session_keeps_the_opened_wording_on_screen_too(self):
        """The screen and the request agree -- the failure this project keeps finding is
        one of them moving without the other."""
        candidate_id = self.card()
        client = FakeClient([
            {"answer": "那我们把这句当成现在这一版。", "candidate": conclusion(),
             "user_stance": "neutral"},
            {"answer": "好，就这句。", "candidate": conclusion(), "user_stance": "accept"},
            {"answer": "接着说。", "candidate": None, "user_stance": "neutral"},
        ])
        run_discuss(self.store, client=client, card=candidate_id,
                    read_line=read_lines(["接着上次那条说", "对，就这么定", "还有一点"]),
                    output=io.StringIO(), environ={})
        self.store.revise(candidate_id, NARROWED, REASON, session="sess-B")
        output = io.StringIO()
        run_discuss(self.store, client=FakeClient([
            {"answer": "继续说。", "candidate": None, "user_stance": "neutral"}]),
            resume=self.trace(), read_line=read_lines(["继续"]), output=output, environ={})
        self.assertNotIn(NARROWED, output.getvalue())


class TheReceiptDoesNotSpeakForTheLibrary(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "dojo.sqlite3")
        self.addCleanup(self.store.close)

    def receipt(self, text):
        for line in text.splitlines():
            if line.startswith("主持人> ") and ("四件问完了" in line or "问到这里停了" in line):
                return line
        return ""

    def session(self, answers, during=None):
        client = FakeClient([
            {"answer": "那我们把这句当成现在这一版。", "candidate": conclusion(),
             "user_stance": "neutral"},
            {"answer": "好，就这句。", "candidate": conclusion(), "user_stance": "accept"},
        ])
        output = io.StringIO()
        code = run_discuss(self.store, client=client,
                           read_line=read_lines(["讲一条做法", "对，就这么定", *answers]),
                           output=output, environ={})
        return code, output.getvalue()

    def test_the_last_clause_is_about_this_session_not_about_the_library(self):
        """`revise` during the four questions: the library now holds a newer version.

        The receipt may not say the card was never changed anywhere -- it was. It says
        the four answers did not change it, which is what this session did.
        """
        code, text = self.session(["那天我把检查交出去了", "我少了判断的机会",
                                   "没人再复核", "有一次反而漏了"])
        self.assertEqual(0, code)
        line = self.receipt(text)
        # The receipt now has two shapes and both must keep the claim: the card's
        # own sentence is the one written before the questions. The promoted shape
        # names it in the same words ("卡片上那句子还是提问前写下的那一句").
        self.assertIn("提问前写下", line)
        self.assertIn("这场问答没有改过它", line)
        self.assertNotIn("之后没改过", line)

    def test_the_claim_it_does_make_is_true(self):
        """The card in the library is byte-identical across the four questions."""
        code, text = self.session(["那天我把检查交出去了", "我少了判断的机会",
                                   "没人再复核", "有一次反而漏了"])
        self.assertEqual(0, code)
        saved = re.search(r"本场结论卡片 ID：([^\s，、]+)", text)
        if saved is None:
            # No card written in this session: the clause is about whatever was on the
            # table, and the receipt still must not claim anything about the library.
            self.assertIn("卡片是提问前写下的那句", self.receipt(text))
            return
        first = self.store.show(saved.group(1))["candidate"]["statement"]
        self.assertIn("这场问答没有改过它", self.receipt(text))
        self.assertEqual(first, self.store.show(saved.group(1))["candidate"]["statement"])


if __name__ == "__main__":
    unittest.main()
