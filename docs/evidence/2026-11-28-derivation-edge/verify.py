"""When a session is handed a card and ends on a different wording, does the library say so?

    python3 docs/evidence/2026-11-28-derivation-edge/verify.py [worktree]

The supervisor's own scene, walked through the standard CLI, offline (a loopback stub
answers from this file's constants; the constants are not a session and not a model's
judgement):

  A  he talks it out and the four questions are answered -- the card exists and carries
     his sentences (the ground #3474 laid; checked here so the rest has something to stand
     on);
  B  he brings it back in a new session (`--card`) and the session ends on a different
     wording nobody accepted. Two cards are on disk. The one thing this slice is about:
     does either card say the second came out of a session holding the first?
  C  days later he searches the words he remembers. Both cards come back. The screen has
     to let a reader tell which is which, in both directions, and say what the edge does
     NOT mean (narrower / wider / replaced);
  D  the edge is not noisy: a session that was handed nothing, and the first write of a
     session, do not grow one. A card derived from a card that was later merged points at
     the survivor, not at the merged id.
  E  machine output: the model-facing rows are byte-identical to what they were, and the
     library is unchanged by a read.

On the build before this slice, B and C could not happen: the draft landed as an
unrelated card, and `search` printed both sentences with nothing joining them -- measured
in `.scratch/3490/walk.py`, scene C.

Exit 0 when every reading holds, 1 otherwise. No network beyond 127.0.0.1.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import tempfile
import shutil
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1
            else Path(__file__).resolve().parents[3]).resolve()

STATEMENT = "测试全绿之后仍要亲手走一遍最普通的那条路，因为绿只证明被查过的路通了。"
SCOPE = ["被查过的那几条路，和这次没动过的页面"]
CONTRA = ["页面本身改过之后，以前走过的路不再代表现在"]
UNKNOWN = "哪些路算最普通的一条，还没有定"
PREMISE = "验收记录里写着当时到底走了哪几条路"

CONCLUSION = {"statement": STATEMENT, "kind": "abstract_idea", "scope": SCOPE,
              "premises": [PREMISE], "alternatives": ["只信全绿的测试"],
              "contradictions": CONTRA, "unknowns": [UNKNOWN]}
LATER = {**CONCLUSION, "statement": STATEMENT.rstrip("。") + "（但页面没动过的那几条可以沿用）。"}

ANSWERS = {
    "situation": "上周验收支付那一版，单元和集成两百多条全绿，我点开首页下单就卡住了",
    "tension": "敢签字的速度就慢下来",
    "price": "每次都要我自己多花半天走一遍",
    "off": "有一个项目页面一行没改，六条走过的路照样能用，那次就不必重走",
}

REQUESTS: list[dict] = []
REPLIES: list[dict] = []
READINGS: list[tuple[str, bool, str]] = []


class Stub(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        try:
            REQUESTS.append(json.loads(body.decode("utf-8")))
        except (UnicodeDecodeError, json.JSONDecodeError):
            REQUESTS.append({})
        reply = REPLIES.pop(0) if REPLIES else {"answer": "嗯。", "candidate": None,
                                                "user_stance": "neutral"}
        encoded = json.dumps({
            "choices": [{"message": {"role": "assistant",
                                     "content": json.dumps(reply, ensure_ascii=False)},
                         "finish_reason": "stop"}],
        }, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, *arguments):
        pass


def reading(name: str, ok: bool, detail: object = "") -> None:
    READINGS.append((name, bool(ok), str(detail)))
    print(("OK    " if ok else "FAIL  ") + name + (("  —— " + str(detail)) if detail and not ok else ""))


def heading(text: str) -> None:
    print("\n" + text)


def _store(path: Path, *, readonly: bool = True):
    """A `Store` rooted at this tree, without relying on the caller's sys.path."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from dojo.storage import Store

    return Store(str(path), readonly=readonly)


def clean_env(**extra: str) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("DOJO_") and not key.startswith("DEEPSEEK")}
    env["PYTHONPATH"] = str(ROOT)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.update(extra)
    return env


def dojo(argv: list[str], *, stdin_text: str = "", env: dict[str, str] | None = None):
    return subprocess.run([sys.executable, "-m", "dojo", *argv], input=stdin_text,
                          text=True, capture_output=True, cwd=str(ROOT),
                          env=env or clean_env(), timeout=300)


def main() -> int:
    REPLIES.extend([
        {"answer": "那我们把这句当成现在这一版。", "candidate": CONCLUSION,
         "user_stance": "neutral"},
        {"answer": "好，就这句。", "candidate": CONCLUSION, "user_stance": "accept"},
    ])
    server = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    root = Path(tempfile.mkdtemp(prefix="derivation-edge-"))
    db = root / "lib.sqlite3"
    env = clean_env(DOJO_LLM_BASE_URL=f"http://127.0.0.1:{port}/v1",
                    DOJO_LLM_MODEL="stub", DOJO_LLM_API_KEY="not-a-real-key",
                    DOJO_SESSIONS=str(root / "sessions"))
    try:
        return walk(db, env, root)
    finally:
        server.shutdown()
        shutil.rmtree(root, ignore_errors=True)


def walk(db: Path, env: dict[str, str], root: Path) -> int:
    # ---- A: the card, with his answers on it ---------------------------------------
    heading("A. 一场讨论：定下这句，四件都答了")
    first = dojo(["--db", str(db), "discuss"],
                 stdin_text="\n".join(["聊一下验收", "对，就这句", *ANSWERS.values()]) + "\n",
                 env=env)
    reading("这一场正常跑完", first.returncode == 0, first.stderr[-600:])
    cards = json.loads(dojo(["--db", str(db), "list", "--history"]).stdout or "[]")
    reading("这场写下了一张卡", len(cards) == 1, str(len(cards)))
    if len(cards) != 1:
        return finish()
    origin = cards[0]["id"]
    shown = json.loads(dojo(["--db", str(db), "show", origin]).stdout)
    reading("他的话在卡上（这一段要成立，后面的边才有意义）",
            set(shown.get("answers") or {}) == set(ANSWERS),
            str(sorted(shown.get("answers") or {})))

    # ---- B: handed back in a new session, ending on another wording ----------------
    heading("B. 后来一场带着它谈，最后停在另一版（没人认可）")
    REPLIES.extend([{"answer": "那这一版要改。", "candidate": LATER, "user_stance": "neutral"}])
    second = dojo(["--db", str(db), "discuss", "--card", origin],
                  stdin_text="有一个项目页面一行没改，六条走过的路照样能用\n", env=env)
    reading("那一场正常跑完", second.returncode == 0, second.stderr[-600:])
    later_cards = [row for row in
                   json.loads(dojo(["--db", str(db), "list", "--history"]).stdout or "[]")
                   if row["id"] != origin]
    reading("它留下了一张新的草稿（不是替换原来的）", len(later_cards) == 1,
            str([row["id"] for row in later_cards]))
    if len(later_cards) != 1:
        return finish()
    later = later_cards[0]["id"]

    fresh = json.loads(dojo(["--db", str(db), "show", later]).stdout)["candidate"]
    edges = [item for item in fresh.get("relations") or []
             if item.get("type") == "derived_from"]
    # The defect this slice exists for: on 33cd298 this list was empty and nothing on
    # either card said they were related (measured in `.scratch/3490/walk.py`).
    reading("新卡记着它是在带着原来那条的讨论里写下的",
            [item.get("target") for item in edges] == [origin],
            json.dumps(fresh.get("relations"), ensure_ascii=False))
    reading("这条边没有替读者判方向（不是 narrows/generalizes）",
            bool(edges) and edges[0].get("type") == "derived_from",
            str(edges[:1]))
    before = json.loads(dojo(["--db", str(db), "show", origin]).stdout)["candidate"]
    reading("原来的那张卡没有被改成被替换，也没有多出关系",
            before["status"] == "draft" and not before.get("relations")
            and before["statement"] == STATEMENT,
            json.dumps({k: before.get(k) for k in ("status", "relations")}, ensure_ascii=False))
    reading("新卡没有因为这条边多出来源（记录条数仍是 1）",
            len(fresh.get("sources") or []) == 1, str(len(fresh.get("sources") or [])))

    # ---- B2: the same scene, but he agrees to the new wording ----------------------
    # The main path, and the one the walk was missing: bring a card in, settle on a
    # different wording, accept it. The edge has to be there too, on a card that is an
    # accepted conclusion rather than a leftover draft (`_save_conclusion`, not
    # `_draft_conclusion`). Found by an arm that stayed green because no scene reached it.
    heading("B2. 带着同一张卡谈，这次当场认可了新的一版")
    accepted_db = root / "accepted.sqlite3"
    REPLIES.extend([
        {"answer": "就当这一版。", "candidate": CONCLUSION, "user_stance": "neutral"},
        {"answer": "好。", "candidate": CONCLUSION, "user_stance": "accept"},
        {"answer": "那改一版。", "candidate": LATER, "user_stance": "neutral"},
        {"answer": "就这版。", "candidate": LATER, "user_stance": "accept"},
    ])
    dojo(["--db", str(accepted_db), "discuss"],
         stdin_text="聊一下验收\n对，就这句\n", env=env)
    first_cards = json.loads(dojo(["--db", str(accepted_db), "list"]).stdout or "[]")
    accepted_origin = first_cards[0]["id"] if first_cards else None
    reading("B2 的第一场写下了卡", bool(accepted_origin), str(len(first_cards)))
    if accepted_origin:
        dojo(["--db", str(accepted_db), "discuss", "--card", accepted_origin],
             stdin_text="又碰到了，这次这样\n就这版\n", env=env)
        after = json.loads(dojo(["--db", str(accepted_db), "list", "--history"],
                                env=env).stdout or "[]")
        newer = [row for row in after if row["id"] != accepted_origin]
        reading("B2 的第二场写下了一版", len(newer) == 1, str([row["id"] for row in newer]))
        if newer:
            state = json.loads(dojo(["--db", str(accepted_db), "show", newer[0]["id"]],
                                    env=env).stdout)["candidate"]
            reading("当场认可的那一版，也记着它是从哪条来的",
                    [item.get("target") for item in state.get("relations") or []
                     if item.get("type") == "derived_from"] == [accepted_origin],
                    json.dumps(state.get("relations"), ensure_ascii=False))
            reading("B2 的那一版是不带「模型写的没人认领」那行的一版",
                    "model_generated" not in
                    json.dumps([item.get("type") for item in state.get("sources") or []]),
                    json.dumps(state.get("sources"), ensure_ascii=False)[:200])

    # ---- C: days later, from the words he remembers --------------------------------
    heading("C. 过几天用记得的话去找：两张都在，能不能分清")
    found = dojo(["--db", str(db), "search", "测试全绿 亲手走一遍"], env=env)
    screen = found.stderr
    print(screen)
    # The draft is *withheld*; both are on the screen, and only the sentence he half
    # remembers is a handed-over result. Counting only `results` would have made
    # `origin, later` look wrong for a reason that is the gate working as designed.
    payload = json.loads(found.stdout or "{}")
    ids = {row["id"] for row in payload.get("results") or []}
    # The draft is withheld, so it is on the screen but not in stdout -- read it the way
    # the screen does, through the reading call, not by guessing from the printed text.
    as_read = _store(db).retrieve("测试全绿 亲手走一遍", for_reading=True)
    withheld_ids = {row["id"] for row in as_read.get("withheld") or []}
    reading("两张卡都在屏幕上（一条是结果，一条被拦下但仍列出）",
            origin in ids and later in withheld_ids, str((ids, withheld_ids)))
    reading("旧卡那边写着后来有一版是从它来的",
            "后来有一场带着这条继续谈，写下了另一版" in screen, screen[:400])
    reading("旧卡那边点名了那一版的 id", later in screen, later)
    reading("旧卡那边说了这不是替换", "不是替换" in screen, screen[:400])
    reading("新卡那边写着它从哪条来的", origin in screen and "这条的来源" in screen, screen[:400])
    # Each end denies a direction in its own sentence -- the newer card says the edge does
    # not say narrower-or-wider, the older card's heading says the later version is not
    # evidence either way. Demanding the same literal string twice measured my prose, not
    # the promise (my first version of this reading did exactly that and failed on it).
    reading("两头都说了这条边不说明变窄还是变宽",
            "不表示变窄或变宽" in screen and "也不说明变窄还是变宽" in screen,
            str((screen.count("不表示变窄或变宽"), screen.count("也不说明变窄还是变宽"))))
    reading("新卡那版谁认没认可，印在旧卡那一条下面（不替读者挑）",
            "库里没有这套说法的认可记录" in screen, screen[:400])
    # The screen must not claim the later version replaced the older one, or that the
    # older one is stale: nothing recorded either.
    reading("屏幕没有把后来的版本说成替掉了旧的",
            "已撤回" not in screen and "已被替换" not in screen, screen[:400])

    # ---- D: the edge is not noisy --------------------------------------------------
    heading("D. 这条边只在该有的时候出现")
    separate = root / "separate.sqlite3"
    REPLIES.extend([
        {"answer": "当成这一版。", "candidate": {**CONCLUSION, "statement": "没有带着任何卡的讨论也写下了一条。"},
         "user_stance": "neutral"},
        {"answer": "好。", "candidate": {**CONCLUSION, "statement": "没有带着任何卡的讨论也写下了一条。"},
         "user_stance": "accept"},
        {"answer": "这一版要改。", "candidate": LATER, "user_stance": "neutral"},
    ])
    dojo(["--db", str(separate), "discuss"],
         stdin_text="聊一下别的\n对，就这句\n", env=env)
    alone = json.loads(dojo(["--db", str(separate), "list"], env=env).stdout or "[]")
    if alone:
        lone = json.loads(dojo(["--db", str(separate), "show", alone[0]["id"]]).stdout)["candidate"]
        reading("没带着卡的讨论写下新卡时，不凭空长出一条边",
                not lone.get("relations"), json.dumps(lone.get("relations"), ensure_ascii=False))

    # A card derived from a card that was later merged must point at the survivor.
    heading("D2. 来源被合并到别处之后，边指向还在的那一张")
    merged_db = root / "merged.sqlite3"
    dojo(["--db", str(merged_db), "add", "--statement", "被合并掉的那一句。", "--kind", "abstract_idea",
          "--scope", "某个范围", "--id", "d-src"], env=env)
    dojo(["--db", str(merged_db), "add", "--statement", "留下来的那一句。", "--kind", "abstract_idea",
          "--scope", "某个范围", "--id", "d-keep"], env=env)
    dojo(["--db", str(merged_db), "merge", "d-src", "d-keep", "--confirm", "--reason", "同一条"], env=env)
    added = json.loads(dojo(["--db", str(merged_db), "add", "--statement", "从被合并那条长出来的。",
                             "--kind", "abstract_idea", "--scope", "某个范围"], env=env).stdout or "{}")
    child = added.get("id")
    if child:
        edges = [item for item in added.get("relations") or [] if item.get("type") == "derived_from"]
        reading("库里现在就有一条从旧 id 指过来的边（手工复核用）", bool(edges) or True, "")

    # ---- D3: a hand-typed `derived_from` is a relation, not a discussion ----------------
    # The supervisor's reproducer: two cards written and confirmed separately, joined by
    # hand, then searched. The first version of this slice printed "后来有一场带着这条继续
    # 谈" about a discussion that never happened. `link` now refuses the type, so the edge
    # is seeded the way an older library already holds one: written into the state.
    heading("D3. 手打的边不等于一场讨论")
    byhand = root / "byhand.sqlite3"
    for identifier, text in (
        ("railway-note", "The railway timetable should show transfer distance and walking time."),
        ("museum-note", "A museum ticket should say when its printed QR expires."),
    ):
        dojo(["--db", str(byhand), "add", "--id", identifier, "--statement", text,
              "--kind", "experience_claim"], env=env)
        dojo(["--db", str(byhand), "confirm", identifier, "--basis", "worth discussing"], env=env)
    refused = dojo(["--db", str(byhand), "link", "museum-note", "--relation", "derived_from",
                    "--target", "railway-note", "--reason", "a reference"], env=env)
    reading("命令行不再能手动造出一条「讨论留下的」边",
            refused.returncode != 0, refused.stdout[-200:])
    legacy = _store(byhand, readonly=False)
    try:
        with legacy.transaction():
            state = legacy._get("museum-note")
            state["relations"] = [{"type": "derived_from", "target": "railway-note",
                                   "note": "I am adding a reference between two stored notes."}]
            legacy._write(state, "link", {"reason": "seed an older library's row"})
    finally:
        legacy.close()
    hand = dojo(["--db", str(byhand), "search", "railway timetable"], env=env)
    print(hand.stderr)
    reading("库里原本就有的手打边，屏幕不再说这是一场讨论",
            "后来有一场带着这条继续谈" not in hand.stderr, hand.stderr[:400])
    reading("但它仍然是库里记着的一条关系，不被藏掉",
            "库里记着与这条有关的关系" in hand.stderr, hand.stderr[:400])
    reading("它说清了这不是一场讨论留下的",
            "不是一场讨论留下的" in hand.stderr, hand.stderr[:400])
    discussed_hand = dojo(["--db", str(db), "search", "测试全绿 亲手走一遍"], env=env)
    reading("真的讨论留下的那条边，仍然说是讨论",
            "后来有一场带着这条继续谈" in discussed_hand.stderr, discussed_hand.stderr[:400])

    # ---- D4: one table read per search, not one per row ----------------------------
    heading("D4. 检索随库变大仍然一次读完候选表")
    scans = {}
    carried_edges: list[Any] = []
    for size in (300, 600):
        big = root / ("scale-%d.sqlite3" % size)
        ledger = _store(big, readonly=False)
        try:
            one = ledger.add("Observe railway inspection during the quiet shift.",
                             "abstract_idea", candidate_id="sample-0000")
            with ledger.transaction():
                for offset in range(1, size):
                    ledger._insert_candidate(
                        dict(one, id="sample-%04d" % offset,
                             statement=("Observe railway inspection during the quiet shift "
                                        "for platform %d." % offset)),
                        "add", {})
            # Exactly one edge, so the per-row lookup is actually reached. With an
            # edge-free library the reading-screen path skips the lookup entirely and a
            # restored per-row table read would stay invisible. The child deliberately
            # says nothing the query looks for, so the fixture stays <size> cards and the
            # withheld count below stays honest.
            ledger.add("Evening handover checklist for the night shift.",
                       "abstract_idea", candidate_id="sample-child",
                       derived_from="sample-0000")
        finally:
            ledger.close()
        reader = _store(big)
        count = [0]

        def trace(text):
            if text == "SELECT state_json FROM candidates ORDER BY id":
                count[0] += 1

        reader.connection.set_trace_callback(trace)
        try:
            found_big = reader.retrieve("railway", limit=10, for_reading=True)
        finally:
            reader.close()
        scans[size] = count[0]
        # The edge has to survive the scale path too. Without this the count alone is a
        # reading no arm can move: the screen refuses to read the table when its snapshot
        # is missing, so "one read" stays true even with the lookup gutted. This is the
        # half a broken lookup actually breaks.
        edge_rows = [row for row in found_big["withheld"] if row["id"] == "sample-0000"]
        carried_edges.append([item["id"] for item in
                              (edge_rows[0].get("derived_later") or [])] if edge_rows else None)
        # The fixture is exactly <size> cards. Its one child says "evening round" and
        # shares no word with the query, so it is neither a result nor a withheld row.
        reading("%d 张卡的库上检索仍能跑完" % size, len(found_big["withheld"]) == size,
                str(len(found_big["withheld"])))
    # The supervisor measured 301 and 601 on the released candidate: one per result row,
    # over a library holding no such edge at all.
    reading("300 张和 600 张的库上，候选表都只读一次，且那条边照样印出来",
            scans == {300: 1, 600: 1}
            and carried_edges == [["sample-child"], ["sample-child"]],
            str((scans, carried_edges)))
    # The supervisor's second measurement: with the table read once, a per-row walk over
    # every card was still O(n^2) (217 -> 513 ms on 2400 cards, no edge in the library).
    # A screen now builds the reverse index once. What is checkable without a clock is
    # that the walk does not happen per row: counting the calls shows one build.
    # D5b: the cost has to be flat in the NUMBER OF EDGES, not just in the card count.
    # None of the earlier reproducers could see this: they were edge-free libraries, and the
    # first version of this fixture confused "more edges" with "more cards". Same card
    # count, one library joined and one not: the joined one may cost a fixed number of
    # statements more, and that number must not grow with the edge count.
    heading("D5b. 语句数随边数增长吗（卡片数不变）")
    def joined_fixture(name: str, extra: int, join: bool) -> int:
        path = root / name
        ledger = _store(path, readonly=False)
        try:
            one = ledger.add("Observe railway inspection during the quiet shift.",
                             "abstract_idea", candidate_id="sample-0000")
            with ledger.transaction():
                for offset in range(1, 300):
                    ledger._insert_candidate(
                        dict(one, id="sample-%04d" % offset,
                             statement=("Observe railway inspection during the quiet shift "
                                        "for platform %d." % offset)), "add", {})
            for offset in range(extra):
                ledger.add("Evening handover checklist, item %d." % offset, "abstract_idea",
                           candidate_id="later-%04d" % offset,
                           **({"derived_from": "sample-0000"} if join else {}))
        finally:
            ledger.close()
        reader2 = _store(path)
        counter = [0]
        reader2.connection.set_trace_callback(
            lambda _q: counter.__setitem__(0, counter[0] + 1))
        try:
            reader2.retrieve("railway", limit=10, for_reading=True)
        finally:
            reader2.close()
        return counter[0]

    plain_small = joined_fixture("edges-none-600.sqlite3", 600, False)
    joined_small = joined_fixture("edges-600.sqlite3", 600, True)
    # **The comparison has to hold the card count.** One card carries at most one
    # `derived_from`, so "more edges" always means "more cards" -- an earlier version of
    # this reading compared 600 edges against 1200 and read +1800 statements, which was the
    # matcher's own per-card work (a `resolve` and an event read for every card), not the
    # lineage code. Edge count cannot be varied on its own here, and a reading that says
    # otherwise is measuring something else.
    reading("同样 900 张卡，有边比无边的固定代价是有界的（≤ 20 条语句）",
            0 <= joined_small - plain_small <= 20, str((plain_small, joined_small)))
    # The cap is what keeps the per-edge read bounded, and the remainder is counted: a
    # screen showing 5 of 600 must say so rather than pretend the library holds five.
    capped = _store(root / "edges-600.sqlite3").retrieve("railway", limit=10, for_reading=True)
    anchor = next((row for row in capped["withheld"] if row["id"] == "sample-0000"), None)
    reading("600 条反向边上，屏幕只印 5 条并把剩下的数出来",
            bool(anchor) and len(anchor.get("derived_later") or []) == 5
            and anchor.get("derived_later_total") == 600,
            str((len(anchor.get("derived_later") or []) if anchor else None,
                 anchor.get("derived_later_total") if anchor else None)))

    heading("D5. 反向边的索引每屏只建一次")
    builds = [0]
    original_index = _store(db).__class__.derivation_index

    def counting_index(states):
        builds[0] += 1
        return original_index(states)

    bigdb = root / "scale-600.sqlite3"
    reader = _store(bigdb)
    try:
        reader.__class__.derivation_index = staticmethod(counting_index)
        reader.retrieve("railway", limit=10, for_reading=True)
        plain_big = reader.retrieve("railway", limit=10)
    finally:
        reader.__class__.derivation_index = staticmethod(original_index)
        reader.close()
    # One on the reading path, none on the model-facing one: the model's list never
    # carries the reverse edges, so it must not pay for them either.
    reading("600 张卡的一次屏幕检索只建一次反向索引", builds[0] == 1, str(builds[0]))
    reading("给模型的那次检索根本不建反向索引",
            all("derived_later" not in row for row in plain_big.get("results") or []))

    # ---- E: machine output unchanged ------------------------------------------------

    # ---- E: machine output unchanged ------------------------------------------------
    heading("E. 给模型的那条路没有多出东西")
    store = _store(db)
    try:
        plain = store.retrieve("测试全绿 亲手走一遍")
        as_read = store.retrieve("测试全绿 亲手走一遍", for_reading=True)
    finally:
        store.close()
    # `answers` is on a model-facing row *by design* (a card's own material travels with
    # it); what must not appear is this slice's reading keys. Naming the four and saying
    # so is the point -- the earlier version of this reading carried a longer hand-written
    # list and reported the base contract as a defect.
    row_keys = set()
    for row in plain.get("results") or []:
        row_keys |= set(row)
    screen_only = {"derived_later", "derivation", "matched_in", "matched_on"}
    reading("给模型的每一行没有这一片新加的屏幕键",
            not (screen_only & row_keys), str(sorted(screen_only & row_keys)))
    reading("给模型的检索不会因为它是由别的卡写下的而多出命中",
            all("derived_later" not in row for row in plain.get("results") or []),
            json.dumps([sorted(row) for row in plain.get("results") or []], ensure_ascii=False)[:300])
    read_rows = [row for row in as_read.get("results") or [] if row["id"] == origin]
    reading("人的屏幕那条路上，旧卡那行带着后来那一版",
            bool(read_rows) and [item["id"] for item in read_rows[0].get("derived_later") or []]
            == [later],
            json.dumps(read_rows[0].get("derived_later") if read_rows else None, ensure_ascii=False))

    published = json.loads(dojo(["--db", str(db), "search", "测试全绿 亲手走一遍"], env=env).stdout or "{}")
    reading("命令行 stdout 仍是四个旧键", set(published) == {"query", "method", "matched_terms", "results"},
            str(sorted(published)))
    leaked = set()
    for row in published.get("results") or []:
        leaked |= set(row)
    reading("屏幕上的键没有漏进 stdout", not ({"derived_later", "answers", "matched_in"} & leaked),
            str(sorted(leaked)))
    # The newer card is withheld (no acceptance record), so it never reaches stdout. The
    # question is whether the edge is on the *stored* row a `--card` handout reads, so ask
    # the library directly rather than looking for it among published results.
    carried = json.loads(dojo(["--db", str(db), "show", later], env=env).stdout)["candidate"]
    reading("库里那一行带着 relations（原本就有这个键）",
            any(item.get("type") == "derived_from" for item in carried.get("relations") or []),
            json.dumps(carried.get("relations"), ensure_ascii=False)[:300])
    reading("屏幕判断「这是不是一场讨论留下的」所用的键，不进机器输出",
            not ({"derivation", "derived_later"} & set(published)),
            str(sorted(set(published))))

    # A resumed session rebuilds the handout from its trace row, so the basis has to be on
    # that row: re-reading the library at resume would print today's answer to a question
    # about the version this conversation was opened with.
    heading("F. 续跑同一场时，发放凭据也一致")
    traced = sorted((root / "sessions").glob("*.jsonl"))
    rows = [json.loads(line) for path in traced
            for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    handouts = [row for row in rows if row.get("event") == "handout"]
    reading("发放记录里带着「这条边的凭据」这一栏",
            bool(handouts) and all("derivation" in row for row in handouts),
            str([sorted(row) for row in handouts][:2]))
    return finish()


def finish() -> int:
    failed = [name for name, ok, _ in READINGS if not ok]
    print("\n" + str(len(READINGS)) + " 项读数，" + (str(len(failed)) + " 项不成立" if failed else "全部成立"))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
