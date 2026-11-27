"""What `dojo search` must say when a person half-remembers a sentence (#3436).

Each test names the defect it exists for. The end-to-end evidence lives in
`docs/evidence/2026-11-28-find-remembered/`; these are the facts that path rests on,
asserted close to the code so a change that quietly re-hides a card fails here first.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from dojo.finding import search_screen
from dojo.storage import Store


def _repo_root():
    for parent in Path(__file__).resolve().parents:
        if (parent / "dojo" / "finding.py").is_file():
            return parent
    raise RuntimeError("cannot locate the dojo repository root")


ROOT = _repo_root()


class FindRememberedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / "dojo.sqlite3"
        self.store = Store(self.db)
        self.addCleanup(self.store.close)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("DOJO_")}
        self.env.update({"PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1",
                         "HOME": str(self.root / "home")})
        (self.root / "home").mkdir(exist_ok=True)

    # ---- helpers -------------------------------------------------------------------
    def add(self, statement, *, candidate_id, scope=(), contradictions=(), unknowns=(),
            session="sess-one", source_type="claimed_firsthand"):
        return self.store.add(
            statement, "abstract_idea", candidate_id=candidate_id, scope=list(scope),
            contradictions=list(contradictions), unknowns=list(unknowns), session=session,
            sources=[{"id": "src-" + candidate_id, "type": source_type,
                      "verification": "unverified", "claim": "他这样值过两次班",
                      "independence_group": "group-" + candidate_id, "scope_note": "同一个组"}],
        )

    def cli(self, *args):
        return subprocess.run([sys.executable, "-B", "-m", "dojo", "--db", str(self.db), *args],
                              cwd=str(ROOT), env=self.env, text=True,
                              capture_output=True, timeout=180)

    def screen_of(self, query):
        result = self.store.retrieve(query, for_reading=True)
        return "\n".join(search_screen(result, database=self.db)), result

    # ---- the report from the released build ----------------------------------------
    def test_a_challenged_card_is_still_shown_next_to_the_one_that_contradicts_it(self):
        """The supervisor's case: after a doubt, the words found only the opposite card."""
        self.add("值班通知交系统跑，只在结果会打断他时才叫醒他。", candidate_id="d-slow",
                 scope=["他已经抽身、这条提醒的失败不会当场伤人时"])
        self.store.record_acceptance("d-slow", "sess-one", path="discuss_conclusion")
        self.add("冷库越限就立刻打电话叫醒负责人。", candidate_id="d-close",
                 scope=["越限会当场损坏货物时"])
        self.store.confirm("d-close", "值得讨论")
        self.store.challenge("d-slow", "第三个团队里更糟：提醒他根本没看")

        text, result = self.screen_of("值班 通知 打电话")
        self.assertIn("d-slow", text, "his own card must not vanish from the same words")
        self.assertIn("d-close", text)
        self.assertIn("（这张卡被人质疑过）", text, "the refusal has to say why, on the same line")
        self.assertIn("这不等于库里没有它", text)
        self.assertIn("第三个团队里更糟", text, "the doubt itself is what he needs to read")
        # The gate is unchanged: only the confirmed card is handed over, and the screen's
        # own list keeps both. Order is by word overlap, which this test does not pin.
        self.assertEqual(["d-close"], [row["id"] for row in result["results"]])
        self.assertEqual(["d-slow"], [row["id"] for row in result["withheld"]])

    def test_the_gate_still_decides_what_a_model_may_be_given(self):
        """The screen looks; the gate is not loosened by it."""
        self.add("值班通知交系统跑。", candidate_id="d-slow")
        self.store.record_acceptance("d-slow", "sess-one", path="discuss_conclusion")
        self.store.challenge("d-slow", "有人没看提醒")
        self.assertEqual([], [row["id"] for row in self.store.retrieve("值班")["results"]])
        self.assertNotIn("withheld", self.store.retrieve("值班"),
                         "the model-facing call grows no screen-only key")

    # ---- a miss must be about words, not about the library -------------------------
    def test_a_miss_says_the_method_and_offers_recent_cards_as_another_method(self):
        self.add("日报连续两次失败后才呼叫负责人。", candidate_id="d-report")
        text, _ = self.screen_of("半夜别老把人叫起来")
        self.assertIn("只比字词，不认意思", text)
        self.assertNotIn("库里没有这句", text)
        self.assertIn("最近写下的", text)
        self.assertIn("不是按意思找出来的", text)
        self.assertIn("d-report", text, "the card he cannot name is at least reachable")
        self.assertIn("不替你挑", text)

    def test_an_empty_topic_invents_nothing(self):
        self.add("日报连续两次失败后才呼叫负责人。", candidate_id="d-report")
        text, result = self.screen_of("量子色动力学里的渐近自由")
        self.assertEqual([], result["results"])
        self.assertIn("没有一张卡的字和这些词重叠", text)
        self.assertIn("d-report", text)

    def test_an_empty_query_does_not_claim_a_word_comparison(self):
        self.add("日报连续两次失败后才呼叫负责人。", candidate_id="d-report")
        text, result = self.screen_of("")
        self.assertIn("没有给出可以找的词", text)
        self.assertNotIn("没有一张卡的字和这些词重叠", text)
        self.assertIn("d-report", text, "the way in is still offered")

    def test_nothing_at_all_is_a_shorter_screen_without_the_offer(self):
        text, result = self.screen_of("量子色动力学")
        self.assertEqual([], result["results"])
        self.assertNotIn("换个办法", text, "no cards, so no recent-cards list to offer")

    # ---- a sentence that was rewritten --------------------------------------------
    def test_the_replaced_wording_can_be_found_and_is_named_as_replaced(self):
        self.add("只有普通日报才等两次失败再呼叫负责人。", candidate_id="d-report")
        self.store.record_acceptance("d-report", "sess-one", path="discuss_conclusion")
        self.store.revise("d-report", "值班通知一律先等两次失败再呼叫负责人。",
                          "想把做法推广到所有值班通知。")
        text, result = self.screen_of("只有普通日报")
        self.assertIn("d-report", text)
        self.assertIn("你记得的字对上的是它以前的说法", text)
        self.assertIn("只有普通日报才等两次失败再呼叫负责人。", text)
        self.assertIn("值班通知一律先等两次失败", text)
        # The note must not point by position: the current sentence is printed above it, so
        # a direction word inverts the two readings (the supervisor caught "下面这包" on a
        # terminal). It names the sentence's place in the entry instead.
        self.assertIn("本条目开头引的那句", text)
        self.assertNotIn("下面这句", text)
        self.assertNotIn("上面", text)
        row = (result["results"] + result["withheld"])[0]
        self.assertEqual("earlier", row["matched_on"])
        self.assertEqual("只有普通日报才等两次失败再呼叫负责人。", row["matched_wording"])

    def test_the_model_never_sees_the_earlier_wording_as_though_the_card_said_it(self):
        self.add("只有普通日报才等两次失败再呼叫负责人。", candidate_id="d-report")
        self.store.record_acceptance("d-report", "sess-one", path="discuss_conclusion")
        self.store.revise("d-report", "值班通知一律先等两次失败再呼叫负责人。", "推广")
        # The model-facing call does not search earlier wordings at all; the reading call
        # does, and its row still reports the card's current sentence as the statement.
        self.assertEqual([], self.store.retrieve("只有普通日报")["results"])
        reading = self.store.retrieve("只有普通日报", for_reading=True)
        # After a rewrite the card is a `draft` whose only acceptance speaks for the old
        # sentence, so it is shown as refused -- not handed over -- while still findable.
        self.assertEqual([], reading["results"])
        row = reading["withheld"][0]
        self.assertEqual("值班通知一律先等两次失败再呼叫负责人。", row["statement"])
        self.assertEqual("earlier", row["matched_on"])
        # Once the new wording is accepted, the model-facing call finds it by the current
        # words -- and still carries no trace of the earlier sentence beyond
        # `revision_basis.left_wording`, which is the ledger's own field and says so.
        self.store.record_acceptance("d-report", "sess-two", path="discuss_conclusion")
        plain = self.store.retrieve("值班通知")["results"][0]
        self.assertNotIn("matched_wording", plain)
        self.assertNotIn("matched_on", plain)

    # ---- a drafted card nobody accepted is not an unexplained rejection ------------
    def test_a_card_with_no_acceptance_record_says_so_and_says_what_that_means(self):
        self.add("环境与流程的设计更能稳住重复行为。", candidate_id="d-plain",
                 source_type="abstract_reasoning")
        text, result = self.screen_of("环境与流程")
        self.assertEqual([], result["results"])
        held = result["withheld"]
        self.assertEqual(["no_acceptance_record"], held[0]["refused"]["codes"])
        self.assertIn("这个库里没有这套说法的认可记录", text)
        self.assertIn("这不等于没人认可过它", text)
        self.assertIn("这不等于库里没有它", text)

    # ---- the command a reader is given -------------------------------------------
    def test_every_entry_prints_a_command_that_names_the_library_absolutely(self):
        self.add("值班通知交系统跑。", candidate_id="d-slow")
        self.store.confirm("d-slow", "值得讨论")
        text, _ = self.screen_of("值班")
        command = [line for line in text.splitlines() if line.startswith("  带进一场新讨论：")][0]
        self.assertIn("--db " + str(self.db), command)
        self.assertIn("--card d-slow", command)

    def test_a_relative_library_still_yields_a_command_that_works_elsewhere(self):
        """The supervisor's ordinary-path case: `--db lib.sqlite3` from another directory."""
        self.add("值班通知交系统跑。", candidate_id="d-slow")
        self.store.confirm("d-slow", "值得讨论")
        result = Store(self.db).retrieve("值班", for_reading=True)
        text = "\n".join(search_screen(result, database="lib.sqlite3"))
        command = [line for line in text.splitlines() if line.startswith("  带进一场新讨论：")][0]
        self.assertIn(str(Path("lib.sqlite3").resolve()), command)
        self.assertNotIn("--db lib.sqlite3", command)

    def test_a_terminal_gets_the_screen_and_a_pipe_gets_the_json(self):
        """`search` at a terminal must not bury its own last line under the JSON block."""
        import pty
        self.add("值班通知交系统跑。", candidate_id="d-slow")
        self.store.confirm("d-slow", "值得讨论")
        read_fd, write_fd = pty.openpty()
        subprocess.run([sys.executable, "-B", "-m", "dojo", "--db", str(self.db), "search", "值班"],
                       cwd=str(ROOT), env=self.env, text=True, timeout=180,
                       stdin=subprocess.DEVNULL, stdout=write_fd, stderr=write_fd)
        os.close(write_fd)
        chunks = []
        try:
            while True:
                try:
                    chunk = os.read(read_fd, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                chunks.append(chunk)
        finally:
            os.close(read_fd)
        terminal = b"".join(chunks).decode("utf-8", "replace")
        self.assertIn("在这个库里找：", terminal)
        self.assertNotIn('"matched_terms"', terminal)
        self.assertIn("json.tool", terminal)
        piped = self.cli("search", "值班")
        self.assertEqual({"query", "method", "matched_terms", "results"},
                         set(json.loads(piped.stdout)))

    def test_looking_does_not_change_the_file_it_looks_at(self):
        """A read-only library stays 0444 and keeps its bytes and tables."""
        import sqlite3

        def tables():
            connection = sqlite3.connect(self.db)
            try:
                return {row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
            finally:
                connection.close()

        self.add("值班通知交系统跑。", candidate_id="d-ro")
        self.store.confirm("d-ro", "值得讨论")
        self.store.close()
        before_tables, before_bytes = tables(), self.db.read_bytes()
        self.db.chmod(0o444)
        self.addCleanup(self.db.chmod, 0o644)
        done = self.cli("search", "值班")
        self.assertEqual(0, done.returncode, done.stderr)
        self.assertEqual(0o444, self.db.stat().st_mode & 0o777, "a look must not rewrite the mode")
        self.assertEqual(before_bytes, self.db.read_bytes())
        self.assertNotIn("reads", tables(), "no read log unless a reader was named")
        self.assertEqual(before_tables, tables())

    def test_another_applications_database_is_refused_and_left_alone(self):
        import sqlite3

        foreign = self.root / "foreign.sqlite3"
        connection = sqlite3.connect(foreign)
        connection.execute("CREATE TABLE stock(id INTEGER)")
        connection.commit()
        connection.close()
        before = foreign.read_bytes()
        done = subprocess.run([sys.executable, "-B", "-m", "dojo", "--db", str(foreign), "search", "值班"],
                              cwd=str(ROOT), env=self.env, text=True, capture_output=True, timeout=180)
        self.assertEqual(2, done.returncode)
        self.assertEqual(before, foreign.read_bytes())

    def test_naming_a_reader_is_what_records_the_read(self):
        self.add("值班通知交系统跑。", candidate_id="d-word")
        self.store.confirm("d-word", "值得讨论")
        self.cli("search", "值班")
        self.assertFalse(self.store.reads("d-word")["holds_table"],
                         "an unnamed look is not a read to record")
        self.cli("search", "值班", "--session", "reader-1")
        screen = json.loads(self.cli("reads", "--id", "d-word").stdout)
        self.assertEqual(1, len(screen["rows"]))
        self.assertEqual("search", screen["rows"][0]["surface"])

    def test_searching_a_library_that_does_not_exist_refuses_instead_of_creating_it(self):
        """A missing file is not an empty collection, and the screen must not say it is."""
        absent = self.root / "nothing-here.sqlite3"
        done = subprocess.run([sys.executable, "-B", "-m", "dojo", "--db", str(absent), "search", "值班"],
                              cwd=str(ROOT), env=self.env, text=True,
                              capture_output=True, timeout=180)
        self.assertEqual(2, done.returncode, done.stderr)
        self.assertFalse(absent.exists(), "search must not create the library it was asked about")
        self.assertIn("不存在", done.stderr)
        self.assertNotIn("没有一张卡的字和这些词重叠", done.stderr)

    def test_the_published_stdout_shape_is_unchanged(self):
        self.add("值班通知交系统跑。", candidate_id="d-slow")
        self.store.confirm("d-slow", "值得讨论")
        done = self.cli("search", "值班")
        self.assertEqual(0, done.returncode, done.stderr)
        payload = json.loads(done.stdout)
        self.assertEqual({"query", "method", "matched_terms", "results"}, set(payload))
        self.assertNotIn("matched_on", payload["results"][0])
        self.assertIn("带进一场新讨论", done.stderr, "the screen is on stderr")


if __name__ == "__main__":
    unittest.main()
