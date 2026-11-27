"""`discuss --card`: a later session really is changed by an earlier card.

The subject is one sentence the product used to say and could not support: "新开一场不会
自动带上以前讨论过的结论". With `--card` the session is handed one card, and then three
things have to be true at once, or the flag is a lie in the other direction:

  1. the screen names the wording, and says when it was narrowed and why;
  2. the model's request actually carries it -- a screen that says "这一场带上了这张卡"
     over a payload without it is the same defect as a receipt describing a receipt;
  3. repeating it is not a second arrival, because the handout writes the read row the
     echo gate reads.

Each check reads the record, not just the screen, for the reason this whole line of work
exists: the two came apart before and the screen was the one that lied.
"""
import io
import json
import tempfile
import unittest
from pathlib import Path

from dojo.discuss import (
    NEW_SESSION_LIMIT_NOTE, handoff_block, handoff_for_model, run_discuss,
)
from dojo.storage import Store


STATEMENT = "持续检查交给系统自己跑，只有结果会打断他时才叫醒他。"
LEFT = "持续检查交给系统自己跑，人只在想推翻的时候回来。"
REASON = "原来那句没写清楚什么时候该叫醒他，所以第三次更糟。"
DOUBT = "第三次在同一团队反而更糟：检查结果他根本没看。"


def conclusion(statement=STATEMENT):
    return {
        "statement": statement,
        "kind": "abstract_idea",
        "scope": ["他已经抽身的时候"],
        "premises": ["系统能自己跑检查"],
        "alternatives": ["把检查留给人"],
        "contradictions": [DOUBT],
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


def last_context(client):
    for message in reversed(client.calls[-1]):
        if message["role"] == "user":
            return message["content"]
    raise AssertionError("no user message in the last request")


class HandoffCase(unittest.TestCase):
    """The fixtures both halves share: a narrowed card and the trace it leaves."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "dojo.sqlite3")
        self.addCleanup(self.store.close)

    def narrowed_card(self):
        """A card he accepted, then doubted, then narrowed with a stated reason."""
        card = self.store.add(
            statement=LEFT, kind="abstract_idea",
            scope=["他已经抽身的时候"], premises=["系统能自己跑检查"],
            alternatives=["把检查留给人"], contradictions=[DOUBT],
            unknowns=["他会不会来看回执"],
            sources=[{"id": "s1", "type": "claimed_firsthand", "verification": "unverified",
                      "independence_group": "gA", "claim": "他这样做过两次",
                      "scope_note": "两次都在同一团队"}],
            session="sess-A",
        )
        candidate_id = card["id"]
        self.store.record_acceptance(candidate_id, "sess-A", path="discuss_conclusion")
        self.store.confirm(candidate_id, "他在会话里认可了这句；不表示为真", session="sess-A")
        self.store.challenge(candidate_id, DOUBT)
        self.store.revise(
            candidate_id, STATEMENT, REASON, scope=["他已经抽身的时候"],
            premises=["系统能自己跑检查"], alternatives=["把检查留给人"],
            contradictions=[DOUBT], unknowns=["打断多少次会变成骚扰"], session="sess-B",
        )
        self.store.record_acceptance(candidate_id, "sess-C", path="discuss_conclusion")
        self.store.confirm(candidate_id, "新一场里他认可了改写后的这句", session="sess-C")
        return candidate_id

    def trace_records(self):
        records = []
        for path in sorted((self.root / "sessions").glob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                records.append(json.loads(line))
        return records


class HandoffTests(HandoffCase):
    def test_a_new_session_says_nothing_was_carried_over_when_no_card_is_named(self):
        """The default must not change: without `--card` no card goes in, and the old
        note is still printed. This is the control against "fix it by always handing
        something over", which would make the opening note untrue instead.

        The library is *not* empty here. A control on an empty library would pass even if
        the code quietly handed over the most recent card, which is exactly the shape of
        over-eager fix this project keeps having to remove.
        """
        self.narrowed_card()
        client = FakeClient([
            {"answer": "先说你想解决的。", "candidate": None, "user_stance": "neutral"},
        ])
        output = io.StringIO()
        self.assertEqual(0, run_discuss(
            self.store, client=client, read_line=read_lines(["我想想"]),
            output=output, environ={},
        ))
        self.assertEqual(1, output.getvalue().count(NEW_SESSION_LIMIT_NOTE))
        self.assertNotIn(STATEMENT, last_context(client))
        self.assertEqual([], self.store.reads()["rows"])

    def test_the_screen_names_the_wording_the_narrowing_and_his_reason(self):
        candidate_id = self.narrowed_card()
        client = FakeClient([
            {"answer": "那我们接着这句谈。", "candidate": None, "user_stance": "neutral"},
        ])
        output = io.StringIO()
        self.assertEqual(0, run_discuss(
            self.store, client=client, card=candidate_id,
            read_line=read_lines(["接着上次那条说"]), output=output, environ={},
        ))
        screen = output.getvalue()
        self.assertIn(candidate_id, screen)
        self.assertIn(STATEMENT, screen)
        # The narrowing and the reason, because a session arguing about the old sentence
        # is arguing about something the library no longer holds.
        self.assertIn(LEFT, screen)
        self.assertIn(REASON, screen)
        # And the promise this flag keeps: repeating it is not a second arrival.
        self.assertIn("不会把本场算成第二个独立来源", screen)
        self.assertNotIn(NEW_SESSION_LIMIT_NOTE, screen)

    def test_the_request_really_carries_the_card_and_its_reason(self):
        """The screen claim is only worth having if the payload matches it."""
        candidate_id = self.narrowed_card()
        client = FakeClient([
            {"answer": "那我们接着这句谈。", "candidate": None, "user_stance": "neutral"},
        ])
        run_discuss(
            self.store, client=client, card=candidate_id,
            read_line=read_lines(["接着上次那条说"]), output=io.StringIO(), environ={},
        )
        context = last_context(client)
        self.assertIn(STATEMENT, context)
        self.assertIn(REASON, context)
        self.assertIn(LEFT, context)
        self.assertIn("资料，不是用户本轮说的话", context)

    def test_the_handout_is_sent_once_and_survives_a_failed_first_turn(self):
        """Two properties that only show up over more than one request.

        The card is not a turn: repeating it every round invites the model to read it as
        the user's newest words. But a first request that fails before the model answers
        must not lose it either, or the session talks on without the thing it claims to
        have been given.
        """
        candidate_id = self.narrowed_card()
        client = FakeClient([
            {"answer": "接着这句。", "candidate": None, "user_stance": "neutral"},
            {"answer": "好。", "candidate": None, "user_stance": "neutral"},
        ])
        run_discuss(
            self.store, client=client, card=candidate_id,
            read_line=read_lines(["接着上次那条说", "继续说"]),
            output=io.StringIO(), environ={},
        )
        self.assertEqual(2, len(client.calls))
        self.assertIn(STATEMENT, client.calls[0][-1]["content"])
        self.assertNotIn(STATEMENT, client.calls[1][-1]["content"])

    def echo_card(self):
        """A card whose content key matches `conclusion()` exactly.

        The echo gate is reached only through `Store.add`'s duplicate check, which
        compares `content_key`: statement, kind and the four content fields. A card that
        differs in any field is not an echo -- it is a second card -- so a test built on
        the narrowed card would be testing the wrong branch.
        """
        card = self.store.add(
            statement=STATEMENT, kind="abstract_idea",
            scope=["他已经抽身的时候"], premises=["系统能自己跑检查"],
            alternatives=["把检查留给人"], contradictions=[DOUBT],
            unknowns=["他会不会来看回执"],
            sources=[{"id": "s1", "type": "claimed_firsthand", "verification": "unverified",
                      "independence_group": "gA", "claim": "他这样做过两次",
                      "scope_note": "两次都在同一团队"}],
            session="sess-A",
        )
        self.store.record_acceptance(card["id"], "sess-A", path="discuss_conclusion")
        self.store.confirm(card["id"], "他在会话里认可了这句；不表示为真", session="sess-A")
        return card["id"]

    def test_the_handout_writes_the_read_row_the_echo_gate_reads(self):
        candidate_id = self.echo_card()
        client = FakeClient([
            {"answer": "你就是这个意思。", "candidate": conclusion(), "user_stance": "neutral"},
            {"answer": "那我记成你同意。", "candidate": conclusion(), "user_stance": "accept"},
        ])
        output = io.StringIO()
        code = run_discuss(
            self.store, client=client, card=candidate_id,
            read_line=read_lines(["就是以前那条，我同意", "对"]),
            output=output, environ={},
        )
        self.assertEqual(0, code)
        rows = self.store.reads(candidate_id)["rows"]
        self.assertEqual(["discuss"], [row["surface"] for row in rows],
                         "the handout did not record the read the gate depends on")
        state = self.store.show(candidate_id)["candidate"]
        # The session really was shown it, so restating it is not a second arrival.
        self.assertNotIn("discuss-", " ".join(state["sessions"]),
                         "a session that was handed the card was counted as a second source")
        self.assertEqual(["gA"], [row.get("independence_group") for row in state["sources"]],
                         "a repeat arrival added a provenance group")
        self.assertIn("本场不算第二个独立来源", output.getvalue())

    def test_the_trace_records_which_wording_was_handed(self):
        candidate_id = self.narrowed_card()
        client = FakeClient([
            {"answer": "接着这句。", "candidate": None, "user_stance": "neutral"},
            {"answer": "好。", "candidate": None, "user_stance": "neutral"},
        ])
        run_discuss(
            self.store, client=client, card=candidate_id,
            read_line=read_lines(["接着上次那条说", "继续说"]),
            output=io.StringIO(), environ={},
        )
        handout = [row for row in self.trace_records() if row.get("event") == "handout"]
        self.assertEqual(1, len(handout))
        self.assertEqual(candidate_id, handout[0]["candidate"])
        self.assertEqual(STATEMENT, handout[0]["statement"])
        self.assertEqual(REASON, handout[0]["revision_basis"]["reason"])
        self.assertEqual(LEFT, handout[0]["revision_basis"]["left_wording"])

    def test_a_card_that_was_never_narrowed_says_nothing_about_narrowing(self):
        """An absent fact gets no line -- the same rule `time_basis` follows.

        Printing "没有被改过" would be a claim about a library that may simply have no
        `revise` row, which is not the same thing.
        """
        card = self.store.add(
            statement=STATEMENT, kind="abstract_idea", scope=["他已经抽身的时候"],
            session="sess-A",
        )
        self.store.record_acceptance(card["id"], "sess-A", path="discuss_conclusion")
        self.store.confirm(card["id"], "认可；不表示为真", session="sess-A")
        shown = self.store.show(card["id"])
        block = handoff_block(shown["candidate"], shown.get("revision_basis"))
        model_text = handoff_for_model(shown["candidate"], shown.get("revision_basis"))
        for text in (block, model_text):
            self.assertNotIn("之前是", text)
            self.assertNotIn("改动理由", text)
        self.assertIn(STATEMENT, block)

    def test_an_unreadable_card_starts_nothing(self):
        client = FakeClient([])
        output = io.StringIO()
        code = run_discuss(
            self.store, client=client, card="no-such-card",
            read_line=read_lines(["你好"]), output=output, environ={},
        )
        self.assertEqual(2, code)
        self.assertEqual([], client.calls, "a request was sent for a card that does not exist")
        self.assertIn("未发送网络请求", output.getvalue())

    def test_a_bad_card_id_on_a_fresh_path_creates_no_library(self):
        """The CLI checks the card before reading the endpoint, and it must not create a
        library merely to answer a question about a name.

        Caught by the full suite: opening the store for writing left an empty database
        behind, which two published CLI tests forbid for the no-endpoint failure. This is
        the same invariant on the `--card` path, kept here so it stays true.
        """
        import subprocess
        import sys as _sys
        import os

        fresh = Path(self.temp.name) / "fresh.sqlite3"
        env = {k: v for k, v in os.environ.items() if not k.startswith("DOJO_")}
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        done = subprocess.run(
            [_sys.executable, "-m", "dojo", "--db", str(fresh),
             "discuss", "--card", "no-such-card"],
            cwd=str(Path(__file__).resolve().parents[1]), env=env,
            text=True, input="", capture_output=True, timeout=60,
        )
        self.assertEqual(2, done.returncode)
        self.assertIn("这张卡读不出来", done.stderr)
        self.assertFalse(fresh.exists(), "a failed card lookup created a library")

    def test_a_bad_card_id_is_a_local_answer_not_an_endpoint_problem(self):
        """Found by walking the real CLI with no endpoint configured.

        The refusal used to come from the endpoint check, so a person who mistyped a card
        id was sent to look at DOJO_LLM_BASE_URL. A local lookup that failed locally has
        to say so; the endpoint is not needed to decide it.
        """
        output = io.StringIO()
        code = run_discuss(
            self.store, card="no-such-card", read_line=read_lines(["你好"]),
            output=output, environ={},
        )
        self.assertEqual(2, code)
        message = output.getvalue()
        self.assertIn("这张卡读不出来", message)
        self.assertNotIn("DOJO_LLM_BASE_URL", message)

    def test_a_merged_card_is_followed_and_said_out_loud(self):
        """`redirect_chain` always contains the requested id, so "was it merged" is a
        chain longer than one. Testing truthiness printed 已被合并 over ordinary cards."""
        target = self.store.add(
            statement=STATEMENT, kind="abstract_idea", scope=["他已经抽身的时候"], session="sess-A",
        )
        alias = self.store.add(
            statement="把持续检查交给系统，他只保留推翻的位置。", kind="abstract_idea",
            scope=["他已经抽身的时候"], session="sess-A",
        )
        self.store.merge(alias["id"], target["id"], reason="主持人核对可互换", confirmed=True)
        client = FakeClient([
            {"answer": "接着说。", "candidate": None, "user_stance": "neutral"},
        ])
        output = io.StringIO()
        self.assertEqual(0, run_discuss(
            self.store, client=client, card=alias["id"],
            read_line=read_lines(["接着那条说"]), output=output, environ={},
        ))
        screen = output.getvalue()
        self.assertIn("已被合并到 " + target["id"], screen)
        self.assertIn(STATEMENT, last_context(client))

    def test_an_ordinary_card_is_not_reported_as_merged(self):
        candidate_id = self.narrowed_card()
        client = FakeClient([
            {"answer": "接着说。", "candidate": None, "user_stance": "neutral"},
        ])
        output = io.StringIO()
        run_discuss(
            self.store, client=client, card=candidate_id,
            read_line=read_lines(["接着那条说"]), output=output, environ={},
        )
        self.assertNotIn("已被合并到", output.getvalue())

    def test_resume_and_card_together_are_refused(self):
        first = FakeClient([
            {"answer": "先谈一句。", "candidate": None, "user_stance": "neutral"},
        ])
        run_discuss(
            self.store, client=first, read_line=read_lines(["你好"]),
            output=io.StringIO(), environ={},
        )
        path = next((self.root / "sessions").glob("*.jsonl"))
        client = FakeClient([])
        output = io.StringIO()
        code = run_discuss(
            self.store, client=client, card="whatever", resume=path,
            read_line=read_lines(["继续"]), output=output, environ={},
        )
        self.assertEqual(2, code)
        self.assertEqual([], client.calls)
        self.assertIn("不能同时使用", output.getvalue())

    def test_a_resumed_session_with_a_handout_still_loads(self):
        """The handout record is in the trace. If the resume validator does not know it,
        the session it was written into can never be resumed -- a new way to lose a
        conversation, introduced by the fix."""
        candidate_id = self.narrowed_card()
        client = FakeClient([
            {"answer": "接着这句。", "candidate": None, "user_stance": "neutral"},
        ])
        run_discuss(
            self.store, client=client, card=candidate_id,
            read_line=read_lines(["接着上次那条说"]), output=io.StringIO(), environ={},
        )
        path = next((self.root / "sessions").glob("*.jsonl"))
        resumed = FakeClient([
            {"answer": "继续说。", "candidate": None, "user_stance": "neutral"},
        ])
        output = io.StringIO()
        code = run_discuss(
            self.store, client=resumed, resume=path,
            read_line=read_lines(["继续"]), output=output, environ={},
        )
        self.assertEqual(0, code, output.getvalue())
        self.assertIn("历史与待处理内容已恢复", output.getvalue())

    def test_the_source_record_reaches_the_model_and_the_trace(self):
        """The card's provenance used to stop at the library boundary.

        The handout told the model to "照旧区分已核实、推断与未知" and then gave it no
        verification state at all: `type`, `verification`, `claim` and `scope_note`
        reached neither the request nor the screen, only the database. A card standing
        on one unverified first-hand claim and a card standing on a checked observation
        read the same to the model, so the one evidence instruction had nothing under
        it. Measured on the real CLI before the fix -- see
        `.scratch/3363/probe_handoff_facts.py`.
        """
        candidate_id = self.narrowed_card()
        client = FakeClient([
            {"answer": "接着说。", "candidate": None, "user_stance": "neutral"},
        ])
        output = io.StringIO()
        run_discuss(
            self.store, client=client, card=candidate_id,
            read_line=read_lines(["接着那条说"]), output=output, environ={},
        )
        context = last_context(client)
        for piece in ("他这样做过两次", "两次都在同一团队", "claimed_firsthand",
                      "unverified"):
            self.assertIn(piece, context, piece)
        handout = [row for row in self.trace_records() if row.get("event") == "handout"]
        self.assertEqual(1, len(handout))
        self.assertEqual("unverified", handout[0]["sources"][0]["verification"])
        self.assertEqual("他这样做过两次", handout[0]["sources"][0]["claim"])

    def test_the_screen_counts_source_records_rather_than_people(self):
        """Two stored records are not two people, and an unverified one is said to be.

        #1763 measured that an echo and a genuinely independent second arrival write
        byte-identical provenance, so the line may count records and must not count
        persons. The verification state is printed beside the count for the same reason:
        "2 条来源记录" alone reads as "two things that were checked".
        """
        candidate_id = self.narrowed_card()
        shown = self.store.show(candidate_id)
        block = handoff_block(shown["candidate"], shown.get("revision_basis"))
        self.assertIn("1 条来源记录", block)
        self.assertIn("未经核验", block)
        self.assertIn("不是人数", block)
        for word in ("两个人", "两位", "两人"):
            self.assertNotIn(word, block, word)

    def test_a_card_without_sources_says_nothing_about_sources(self):
        """An absent fact gets no line -- the same rule the narrowing line follows."""
        card = self.store.add(
            statement=STATEMENT, kind="abstract_idea", scope=["他已经抽身的时候"],
            session="sess-A",
        )
        shown = self.store.show(card["id"])
        block = handoff_block(shown["candidate"], shown.get("revision_basis"))
        model_text = handoff_for_model(shown["candidate"], shown.get("revision_basis"))
        for text in (block, model_text):
            self.assertNotIn("来源记录", text)

    def test_the_real_cli_gets_a_working_store_for_discuss(self):
        """The crash the supervisor hit, pinned at the entry point it was hit at.

        The handoff slice replaced the discuss branch's `store = Store(db_path)` with a
        readonly probe and let `run_discuss` keep the branch's `store`, which was still
        None: the first `store.show` died with `'NoneType' object has no attribute
        'show'` after zero requests. In-process tests could not see it because every one
        of them builds a store and passes a client. This test runs the CLI itself into a
        loopback endpoint, which is the only path where the branch owns the store.
        """
        import os
        import subprocess
        import sys as _sys
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        candidate_id = self.narrowed_card()

        class Handler(BaseHTTPRequestHandler):
            received = []

            def do_POST(self):  # noqa: N802
                Handler.received.append(
                    self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode())
                payload = json.dumps({"choices": [{"message": {
                    "role": "assistant", "content": json.dumps({
                        "answer": "接着说。", "candidate": None,
                        "user_stance": "neutral"}, ensure_ascii=False)},
                    "finish_reason": "stop"}]}, ensure_ascii=False).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        env = {k: v for k, v in os.environ.items() if not k.startswith("DOJO_")}
        env.update({
            "DOJO_DB": str(self.root / "dojo.sqlite3"),
            "DOJO_LLM_BASE_URL": f"http://127.0.0.1:{server.server_address[1]}/v1",
            "DOJO_LLM_MODEL": "loopback",
            "PYTHONDONTWRITEBYTECODE": "1",
        })
        done = subprocess.run(
            [_sys.executable, "-m", "dojo", "discuss", "--card", candidate_id],
            cwd=str(Path(__file__).resolve().parents[1]), env=env, text=True,
            input="接着上次那条说\n", capture_output=True, timeout=120,
        )
        self.assertEqual(0, done.returncode, done.stdout + done.stderr)
        self.assertNotIn("Traceback", done.stderr)
        self.assertIn(STATEMENT, done.stdout)
        self.assertEqual(1, len(Handler.received), "the endpoint got no request")
        self.assertIn(LEFT, Handler.received[0])
        self.assertIn(REASON, Handler.received[0])
        self.assertIn("他这样做过两次", Handler.received[0])


class ResumeTests(HandoffCase):
    """The second half of one session, measured at the wire and not on the screen.

    The supervisor resumed a session that had been handed a card and watched the CLI
    answer while the outbound request carried none of it: no wording, no narrowing, no
    reason, no sources. The trace had all four -- `_load_resume_trace` validated the
    handout row and then dropped it -- and the screen said "历史与待处理内容已恢复",
    which is true of the turns and was false of the handout.

    Every check here reads `client.calls`, the bytes that would have gone to the model.
    A resumed run that prints the right opening line over a request missing the card is
    the same defect this whole slice exists to remove.
    """

    def first_half(self, candidate_id, lines=("接着上次那条说",)):
        client = FakeClient([
            {"answer": "接着这句。", "candidate": None, "user_stance": "neutral"},
        ])
        run_discuss(
            self.store, client=client, card=candidate_id,
            read_line=read_lines(list(lines)), output=io.StringIO(), environ={},
        )
        self.assertEqual(1, len(client.calls))
        return next((self.root / "sessions").glob("*.jsonl"))

    def test_resume_sends_the_same_handout_the_live_session_sent(self):
        candidate_id = self.narrowed_card()
        path = self.first_half(candidate_id)
        resumed = FakeClient([
            {"answer": "继续说。", "candidate": None, "user_stance": "neutral"},
        ])
        output = io.StringIO()
        code = run_discuss(
            self.store, client=resumed, resume=path,
            read_line=read_lines(["继续"]), output=output, environ={},
        )
        self.assertEqual(0, code, output.getvalue())
        self.assertEqual(1, len(resumed.calls), "the resumed session sent nothing")
        wire = json.dumps(resumed.calls[0], ensure_ascii=False)
        # The whole card, not just its statement: the trace row has to carry every
        # content field the live handout sent, or a resumed request is quietly poorer
        # than the one it continues. `narrowed_card` ends on unknowns="打断多少次会变成
        # 骚扰" -- the earlier "他会不会来看回执" was replaced by the revise, so asserting
        # it here would fail on a correct tree (the supervisor caught exactly that).
        shown = self.store.show(candidate_id)["candidate"]
        self.assertEqual(["打断多少次会变成骚扰"], shown["unknowns"])
        for piece in (STATEMENT, LEFT, REASON, *shown["scope"], *shown["premises"],
                      *shown["alternatives"], *shown["contradictions"], *shown["unknowns"],
                      "他这样做过两次", "两次都在同一团队",
                      "claimed_firsthand", "unverified"):
            self.assertIn(piece, wire, piece)

    def test_resume_keeps_the_version_this_conversation_started_with(self):
        """The card changes between the two halves. The session must not change with it.

        This is the supervisor's second requirement, and it is the reason the handout is
        rebuilt from the trace rather than from `store.show`: a conversation that was
        opened on one sentence, argued about it, and then continues is still about that
        sentence. Handing the model a newer wording under the same session id would make
        "这一段说的是哪句" unanswerable from the record.
        """
        candidate_id = self.narrowed_card()
        path = self.first_half(candidate_id)
        LATER = "持续检查交给系统自己跑，只在他说停的时候才停。"
        self.store.revise(
            candidate_id, LATER, "后来觉得叫醒的门槛还是太低。",
            scope=["他已经抽身的时候"], premises=["系统能自己跑检查"],
            alternatives=["把检查留给人"], contradictions=[DOUBT],
            unknowns=["他会不会来看回执"], session="sess-D",
        )
        resumed = FakeClient([
            {"answer": "继续说。", "candidate": None, "user_stance": "neutral"},
        ])
        run_discuss(
            self.store, client=resumed, resume=path,
            read_line=read_lines(["继续"]), output=io.StringIO(), environ={},
        )
        wire = json.dumps(resumed.calls[0], ensure_ascii=False)
        self.assertIn(STATEMENT, wire, "the resumed session lost the wording it started on")
        self.assertNotIn(LATER, wire, "a later revision was slipped into an older session")

    def test_resume_does_not_spend_a_second_read_row_on_one_session(self):
        """The read log counts sessions, and a resume is the same session.

        Without the guard this ending prints "被交付过 2 次" about one conversation, which
        is a count inflated by the act of continuing -- the same class of claim this
        project keeps having to remove.
        """
        candidate_id = self.narrowed_card()
        path = self.first_half(candidate_id)
        resumed = FakeClient([
            {"answer": "继续说。", "candidate": None, "user_stance": "neutral"},
        ])
        run_discuss(
            self.store, client=resumed, resume=path,
            read_line=read_lines(["继续"]), output=io.StringIO(), environ={},
        )
        rows = self.store.reads(candidate_id)["rows"]
        self.assertEqual(1, len(rows), [row["reader_session"] for row in rows])
        self.assertEqual("discuss", rows[0]["surface"])

    def test_a_trace_with_two_handout_rows_is_refused(self):
        """`--card` is a start-of-session flag, so two rows cannot be one session."""
        candidate_id = self.narrowed_card()
        path = self.first_half(candidate_id)
        lines = path.read_text(encoding="utf-8").splitlines()
        end = json.loads(lines[-1])
        handout = next(row for row in map(json.loads, lines) if row.get("event") == "handout")
        lines.insert(len(lines) - 1, json.dumps(handout, ensure_ascii=False))
        self.assertEqual("session_end", end["event"])
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        client = FakeClient([])
        output = io.StringIO()
        code = run_discuss(
            self.store, client=client, resume=path,
            read_line=read_lines(["继续"]), output=output, environ={},
        )
        self.assertEqual(2, code)
        self.assertEqual([], client.calls)
        self.assertIn("交付卡片记录重复", output.getvalue())

    def test_a_seed_card_can_be_handed_to_a_session(self):
        """`dojo seed` is the first thing the README tells a person to run.

        The seed pack writes no `contradictions`, and `_candidate_fields` subscripted it,
        so `--card seed-m01` died on the first turn with `KeyError: 'contradictions'`.
        The absent field is omitted, not filled in: telling the model "he ruled nothing
        out" about a card that never recorded the question is a claim the library never
        made.
        """
        from dojo.storage import load_simulated_seeds

        load_simulated_seeds(self.store)
        client = FakeClient([
            {"answer": "这几条是模拟材料。", "candidate": None, "user_stance": "neutral"},
        ])
        output = io.StringIO()
        code = run_discuss(
            self.store, client=client, card="seed-m01",
            read_line=read_lines(["我们谈谈这一条"]), output=output, environ={},
        )
        self.assertEqual(0, code, output.getvalue())
        self.assertNotIn("Traceback", output.getvalue())
        context = last_context(client)
        self.assertIn("环境与流程的设计", context)
        self.assertIn("abstract_reasoning", context)


if __name__ == "__main__":
    unittest.main()
