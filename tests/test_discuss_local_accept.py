"""Offline regression for the interactive approval boundary (standard library only).

    PYTHONPATH=/path/to/candidate-checkout python3 -BP /path/to/test_discuss_local_accept.py -v

Uses the actual discuss loop and a temporary on-disk library. The line reader inspects
what is already visible and what has already been recorded before typing the next line.
"""
import copy
import io
import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from dojo.discuss import run_discuss
from dojo.elicit import QUESTIONS
from dojo.storage import DojoError, Store, wording_digest

SAME_WORDS = "  我只是启动时有点卡；他说过\u300c先等等\u300d。  "
CLOSING = "差不多，就这样吧。"
CANDIDATE = {
    "statement": "把任务缩成一个能执行的第一步，可能减轻启动阻力。",
    "kind": "application",
    "scope": ["已经知道任务目标，但没开始时"],
    "premises": ["每周至少安排三次二十五分钟", "阻力可能来自任务规模"],
    "alternatives": ["疲劳也可能是主要原因"],
    "contradictions": ["第一步仍不明确时未必奏效"],
    "unknowns": ["没有验证这位用户会不会因此更容易开始"],
}


def reply(candidate=CANDIDATE, stance="neutral"):
    return {"answer": "有一种可能的整理方式。", "candidate": candidate,
            "user_stance": stance, "person_updates": []}


class DiscussionLocalApproval(unittest.TestCase):
    def exercise(self, responses, turns, *, seed=None):
        with tempfile.TemporaryDirectory() as directory, closing(
                Store(Path(directory) / "dojo.sqlite3")) as store:
            root = Path(directory)
            if seed is not None:
                seed(store)
            screen = io.StringIO()
            calls = []
            replies = iter(responses)
            lines = iter(turns)

            class Stub:
                def complete(self, messages):
                    calls.append(copy.deepcopy(messages))
                    try:
                        return copy.deepcopy(next(replies))
                    except StopIteration:
                        raise AssertionError("Unexpected request to the discussion model")

            def read_line(_prompt):
                try:
                    step = next(lines)
                except StopIteration:
                    raise EOFError
                if callable(step):
                    return step(screen.getvalue(), store, calls)
                return step

            code = run_discuss(
                store, client=Stub(), read_line=read_line, output=screen,
                environ={"DOJO_SESSIONS": str(root / "sessions"),
                         "DOJO_PERSON": str(root / "person.md")},
                no_trace=True, no_profile=True,
                searcher=lambda _: self.fail("Unexpected request to search"),
            )
            self.assertEqual(code, 0, screen.getvalue())
            self.assertEqual(len(calls), len(responses), screen.getvalue())
            self.assertEqual(list(lines), [], "Discussion exited before all inputs were consumed")
            cards = store.list_candidates(include_history=True)
            return screen.getvalue(), cards, self.acceptances(store)

    @staticmethod
    def acceptances(store):
        return [event for card in store.list_candidates()
                for event in store.history(card["id"])["events"]
                if event["event"] in {"wording_accepted", "draft_accepted"}
                or event["details"].get("wording_accepted")]

    def assert_no_four_questions(self, screen):
        for question in QUESTIONS.values():
            self.assertNotIn(question["ask"], screen)

    def assert_review(self, screen, original, candidate):
        block = screen.rsplit("【写入前核对", 1)
        self.assertEqual(len(block), 2, screen)
        review = block[1]
        self.assertIn("逐字", review)
        self.assertIn(original, review, "Original text, including surrounding spaces, must be visible")
        self.assertIn("主持人拟写", review)
        self.assertRegex(review, r"未经独立核验|不是你的原话")
        self.assertRegex(review, r"条件与边界|适用边界")
        self.assertRegex(review, r"未覆盖|没覆盖|未知")
        self.assertIn("推断", review)
        self.assertIn("/认可", review)
        for value in candidate.values():
            for item in value if isinstance(value, list) else [value]:
                self.assertIn(item, review, f"Review omitted {item!r}")
        self.assert_no_four_questions(screen)

    def test_model_reports_accept_for_normal_input_but_cannot_write_acceptance(self):
        # Match the prior bypass (same candidate, closing phrase); also catch a
        # substring parser accepting a mention of the proposed local command.
        for last in (CLOSING, "我还没决定要不要输入 /认可。", "我同意这一版。"):
            with self.subTest(last=last):
                screen, cards, accepted = self.exercise(
                    [reply(), reply(stance="accept")], [SAME_WORDS, last],
                )
                self.assertEqual(accepted, [], screen)
                self.assert_no_four_questions(screen)
                self.assertTrue(all(card.get("unaccepted_draft") for card in cards), cards)

    def test_local_command_without_a_display_is_not_sent_to_the_model(self):
        screen, cards, accepted = self.exercise([], ["/认可"])
        self.assertEqual(cards, [])
        self.assertEqual(accepted, [])
        self.assert_no_four_questions(screen)

    def test_display_then_exact_local_command_records_only_displayed_wording(self):
        # Amend the candidate before approval; the screen must quote the current
        # operator line *verbatim*, and the ledger must bind to what replaced V1.
        amended = {**CANDIDATE, "premises": ["只要试一次，不设置每周频次"]}
        correction = "  别填每周频次，只试一次。  "

        def approve(screen, store, calls):
            self.assert_review(screen, correction, amended)
            self.assertNotIn(CANDIDATE["premises"][0], screen.rsplit("【写入前核对", 1)[1])
            self.assertEqual(len(calls), 2)
            self.assertEqual(store.list_candidates(), [], "A card was written before approval")
            return "/认可"

        def skip(part, expected_seen):
            def at_question(screen, store, calls):
                self.assertEqual(len(calls), 2, "Approval or four questions called the model")
                self.assertIn(QUESTIONS[part]["ask"], screen)
                self.assertEqual([name for name in ("情境", "张力", "代价", "失效")
                                  if QUESTIONS[name]["ask"] in screen], expected_seen)
                self.assertEqual(len(self.acceptances(store)), 1,
                                 "Four questions started without a recorded approval")
                return "跳过"
            return at_question

        parts = ["情境", "张力", "代价", "失效"]
        screen, cards, accepted = self.exercise(
            [reply(), reply(amended, stance="accept")],
            [SAME_WORDS, correction, approve] +
            [skip(part, parts[:i + 1]) for i, part in enumerate(parts)],
        )
        self.assertEqual(len(accepted), 1, screen)
        self.assertEqual(len(cards), 1, cards)
        self.assertFalse(cards[0].get("unaccepted_draft"), cards)
        for key, expected in amended.items():
            self.assertEqual(cards[0][key], expected, key)
        details = accepted[0]["details"]
        self.assertEqual(details.get("path"), "discuss_conclusion")
        self.assertEqual(details.get("candidate_id"), cards[0]["id"])
        self.assertEqual(details.get("statement_digest"), wording_digest(amended))
        self.assertEqual(details.get("version"), cards[0]["version"])
        self.assertTrue(details.get("agreed_at"), details)

    def test_same_statement_different_scope_does_not_accept_the_old_card(self):
        old = {**CANDIDATE, "scope": ["先用于文档草稿"]}
        proposed = {**CANDIDATE, "scope": ["只用于新建的订单导出页"]}

        snapshot = {}

        def seed(store):
            store.add(**old, candidate_id="old-card", session="earlier", sources=[{
                "type": "claimed_firsthand", "claim": "旧会话只试了文档草稿。",
                "independence_group": "earlier", "verification": "unknown",
            }])
            snapshot.update(store.show("old-card"), history=store.history("old-card"))

        def approve(screen, store, calls):
            self.assert_review(screen, SAME_WORDS, proposed)
            return "/认可"

        def first_question(screen, store, calls):
            self.assertIn(QUESTIONS["情境"]["ask"], screen)
            self.assertEqual(snapshot,
                             dict(store.show("old-card"), history=store.history("old-card")))
            accepted, = self.acceptances(store)
            self.assertNotEqual(accepted["details"]["candidate_id"], "old-card",
                                "Approval for the new scope was recorded against the old card")
            return "跳过"

        screen, cards, accepted = self.exercise(
            [reply(proposed)], [SAME_WORDS, approve, first_question], seed=seed,
        )
        self.assertEqual(len(cards), 2, screen)
        self.assertEqual(accepted[0]["details"]["statement_digest"], wording_digest(proposed))

    def test_ledger_write_failure_rolls_back_the_reviewed_card(self):
        with patch.object(Store, "record_acceptance", side_effect=DojoError("fixture ledger failure")):
            screen, cards, accepted = self.exercise([reply()], [SAME_WORDS, "/认可"])
        self.assertIn("没有写下认可", screen)
        self.assertEqual([], cards)
        self.assertEqual([], accepted)
        self.assert_no_four_questions(screen)


if __name__ == "__main__":
    unittest.main()
