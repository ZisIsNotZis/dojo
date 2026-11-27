<p align="center"><img src="assets/logo.svg" alt="dojo 道场" width="200" height="40"></p>

**English** | [简体中文](README.zh-CN.md)

# dojo · 道场

A local, no-UI CLI and SQLite proof of concept for keeping ideas, experience claims, counterexamples and unknowns as traceable discussion candidates — with their source, their boundary, and the version they replaced.

**dojo records what was said and on what basis, and refuses to grade it true: `confirm` only means "worth retrieving", every rewrite keeps the version it replaced, and a claim whose only source is the session that wrote it is never broadcast back as corroboration.**

```sh
python3 -m dojo demo     # three-act Chinese story, offline, no dependencies
```

## Quick start

Needs Python 3.10+ and nothing else — the whole runtime is the standard library, so there is no install step. Run from the repository root:

```sh
git clone https://github.com/ZisIsNotZis/dojo.git
cd dojo

python3 -m dojo demo              # offline three-act story, temp DB removed on exit
python3 -m dojo demo --auto       # same story without stdin (no prompts)
python3 -m dojo demo --details    # expand every retrieved card
python3 -m dojo --help            # every operation and flag
```

The demo is simulated dialogue, not live AI and not user research. A real end-to-end walk through every store operation, in a throwaway database:

```sh
sh scripts/storage-smoke.sh
```

The claim lifecycle by hand:

```sh
DEMO=$(mktemp -d)
export DOJO_DB=$DEMO/lifecycle.sqlite3   # throwaway: nothing here touches your own library
python3 -m dojo add --id idea-01 --kind abstract_idea \
  --statement '降低与目标无关的摩擦能让重复行为更容易持续' \
  --scope '日常重复行为' --unknown '哪些难度是有意义的训练而非无谓摩擦'
python3 -m dojo confirm idea-01 --basis '表述清楚，值得检索；不表示为真'
python3 -m dojo search '摩擦 持续 行为'          # lexical overlap, hit words shown
python3 -m dojo show idea-01 --history          # versions and events
python3 -m dojo challenge idea-01 --text '把一切变容易未必有益'
python3 -m dojo revise idea-01 --statement '在难度不是训练的情况下，降低无关摩擦才让重复行为更容易持续' \
  --reason '补上失效条件，保留旧版本'
python3 -m dojo confirm idea-01 --basis '修订后仍值得检索；仍不表示为真'   # challenge and revise each withdrew the mark
python3 -m dojo revoke idea-01 --reason '范围仍不清楚'   # revoking discussability, not deleting history
```


What the demo is, and what it is not: three strangers with independent problems — making tidiness stick, writing code before the requirement is clear, and the objection that some ability is built by difficulty — each get a candidate, a retrieval from the real local store, and a challenge that produces a new version without deleting the old one. Every line is scripted, the seed records `seed-m01`–`seed-m04` are simulated material, and the personas are not user research. `compare --full` replays two archived Luna answers offline (old editor-bridge evaluation material, not the current story); `freeze-materials` writes four frozen model inputs with C condition drawn from a real store retrieval; `demo --workdir ./run` keeps the database and a short summary in a new or empty directory and refuses to overwrite.


Merging is never automatic; it needs an explicit human judgement and is reversible:

```sh
DEMO=$(mktemp -d)
export DOJO_DB=$DEMO/merge.sqlite3        # its own library: an alias has to exist before it can be merged
python3 -m dojo add --id idea-01 --kind abstract_idea \
  --statement '降低与目标无关的摩擦能让重复行为更容易持续' --scope '日常重复行为'
python3 -m dojo add --id idea-alias --kind abstract_idea \
  --statement '与目标无关的摩擦可以降低，重复行为就更容易持续' --scope '日常重复行为'
python3 -m dojo merge idea-alias idea-01 --confirm --reason '主持人核对主张及范围可互换'
python3 -m dojo show idea-alias      # canonical ID plus redirect chain
python3 -m dojo unmerge idea-alias --reason '复核后撤销'
```

Reading a story's knowledge chain back is four read-only views, and none of them writes to the library. The ledger they read is authored as text (`fixtures/comparison-ledger.json`); the `*.sqlite3` it becomes is gitignored, so a checkout builds its own:

```sh
# each run gets its own new directory, so a second run never touches the first one's library
DEMO=$(mktemp -d)
DB=$DEMO/ledger.sqlite3
python3 -B fixtures/build_comparison_ledger.py "$DB"
STORY=$(python3 -m dojo --db "$DB" stories --synthetic | python3 -c 'import json,sys;print(json.load(sys.stdin)[0]["story"])')
python3 -m dojo --db "$DB" stories "$STORY" --context --synthetic
python3 -m dojo --db "$DB" stories "$STORY" --comparison 5 --synthetic
python3 -m dojo --db "$DB" stories "$STORY" --report 2 --synthetic
python3 -m dojo --db "$DB" stories "$STORY" --proposal 5 --synthetic
```

`--context` reads back what the story has not yet checked for source independence; its `omitted_events` (`[5, 15, 16, 17]`) are current proposals the view could not expand, and each is readable as-is by `--comparison`. `--comparison 5` returns `comparison_status: checked` with `source_events: [3, 4]` — a recorded judgement that two receipts were compared, not a certification. `--report 2` returns the user's own words with `epistemic_status: user_report_not_independently_verified`. `--proposal 5` returns the proposal's `statement` and `state`; its `report_review` is empty in this library, and empty means "nothing to list here", not a clean bill. Built with `--revision`, the same library also shows the replaced state, where `--comparison 5` refuses (exit code 2) and names #27 as the version to read instead. The four views are mutually exclusive — one flag per call. [`docs/cli-guide.md`](docs/cli-guide.md) is the full walk, including what each refusal means.

Live chat/discussion, inquiry tools and bounded knowledge rechecks are explicit network paths. The legacy discussion entry is:

```sh
export DOJO_LLM_BASE_URL=http://127.0.0.1:4000/v1
export DOJO_LLM_MODEL=github_copilot/gpt-6-luna   # must match the endpoint's registered id
# then set DOJO_LLM_API_KEY in this shell from your endpoint's key store; the repo never holds it
python3 -m dojo discuss            # zero forms, zero y/n prompts; on agreement it writes the conclusion
python3 -m dojo discuss --verbose  # live request/retrieval progress on stderr
python3 -m dojo list               # a version nobody accepted is kept as `unaccepted_draft: true`
```

### Opening a session on an earlier card, and continuing one

`--card ID` hands the session one card you already have. The opening names the sentence, the
version it replaced, the reason the library recorded, whether the library holds a record that
somebody accepted this content -- and the card's **limits**: when it holds, when it does not,
what is still unmeasured, and what it rests on, one line each, verbatim as stored. Source
records are itemised with what each one actually claims, including the caveat its writer put
on it. The first request that reaches the model carries the same material, marked as material
rather than as your latest words. Repeating the sentence back does not count as a second
independent source: the handout writes the read row that the echo gate reads.

Three lines on that screen are worded deliberately, because each may state only what the
program checked:

- `draft` prints just 草稿. A draft is not a sentence nobody agreed to: a conclusion agreed to
  in conversation stays `draft` until somebody marks it discussable. Whether an acceptance is
  on record is printed from the ledger, as its own sentence, and a missing record reads “this
  library has no such record”, never “nobody agreed”.
- The 可讨论 parenthetical says somebody marked it worth discussing. `confirm` and "accepted
  this wording" are different acts, and one word for both makes one screen contradict itself.
- A revised card prints 库里记着这一句换过说法，之前是…, and never 变窄 or 变宽: a `revise`
  row records which wording it left and the reason it was given, not a direction and not an
  author. A counterexample added by a challenge is printed under 什么时候不成立, beside the
  ones the card already had.

The card's `alternatives` stay off the opening screen: a route it did not take does not help
you decide about your own case, and five lines of limits is already long. `show` and the model
still carry them.

```sh
python3 -m dojo discuss --card c1 --resume discuss-<id>.jsonl   # refused: a card is a start-of-session choice
python3 -m dojo discuss --card c9                               # a typo is answered locally, not by the endpoint
```

```text
无法续跑：--card 与 --resume 不能同时使用。
无法开始讨论：这张卡读不出来（candidate not found: c9）；未发送网络请求。
```

`--resume TRACE` continues the session that wrote that trace, appends to the same file, and
keeps the card this session was *opened* with -- not whichever version the library holds after
a later `revise`. It needs the trace the session itself wrote (`sessions/discuss-<32 hex>.jsonl`
under the library's directory, or wherever `DOJO_SESSIONS` points), and it cannot be combined
with `--no-trace`, because the trace is the thing being continued.

```sh
python3 -m dojo discuss --resume sessions/discuss-0123456789abcdef0123456789abcdef.jsonl
```

Without an endpoint both flags still do their local part and say which part failed: the card is
read before the endpoint is required, so `无法启动讨论：未配置 DOJO_LLM_BASE_URL，未发送网络请求。`
means the card was fine. The full run -- screen and payload -- is in
[`docs/evidence/2026-11-28-card-handoff/WALK.md`](docs/evidence/2026-11-28-card-handoff/WALK.md).

### Reading a finished session back

`transcript TRACE` is the read-only view of one discussion: your lines and the host's replies,
then each of the four questions with the question that was asked, what you said, and what the
record made of it. It opens no store, writes nothing, and makes no request. A trace whose write
died mid-session is still readable, and the screen says which line was cut off; it also says
when the file cannot be resumed instead of printing a `--resume` command that will be refused.

The last line is the one that matters: these words are **material, not a conclusion**. A part
that was collected is material even when it misses the question, so reading it back does not
tell you the question was answered, and nothing here says you endorsed the card.

```sh
python3 -m dojo transcript sessions/discuss-0123456789abcdef0123456789abcdef.jsonl
python3 -m dojo transcript sessions/discuss-0123456789abcdef0123456789abcdef.jsonl --json
```

The receipt at the end of the four questions names this command, so the sentence "your words
stay in this session's record" can be acted on without learning the JSONL format first.

### The commands on screen work as pasted

Every command this program prints is meant to be copied — from any directory, with the
shell history and variable expansion that a real terminal applies. A path with a space, a
single quote, `$` or a backtick arrives as one argument:

```sh
DB="$(mktemp -d)/a library's $HOME dir/my dojo's.sqlite3"
mkdir -p "$(dirname "$DB")"
python3 -m dojo --db "$DB" add --id c1 --kind abstract_idea \
  --statement "把持续检查交给系统，人这一侧只保留随时可以推翻的位置。" \
  --scope "一个人已经抽身、只在自己想推翻时回来时"
python3 -m dojo --db "$DB" show c1
```

What a session opened on that library prints when it ends (recorded from a real run, see
[`docs/evidence/2026-11-28-printed-commands/WALK.md`](docs/evidence/2026-11-28-printed-commands/WALK.md)):

```text
这一场没有写下被认可的卡片；结束时留了一张未认可的草稿：d-1e56e2a1614c（系统整理的那一版，
没有人认可过）。先看它：python3 -m dojo --db "/tmp/x/a library's $HOME dir/my dojo's.sqlite3" show d-1e56e2a1614c
回看这一场说了什么：python3 -m dojo --db "/tmp/x/a library's $HOME dir/my dojo's.sqlite3" transcript "/tmp/x/a library's $HOME dir/sessions/discuss-….jsonl"
```

Pasting that line opens the draft in *that* library, from whatever directory you are in.
Without `--db` it would read the default one and answer `candidate not found`.

There is no short form: **every card and view command names the file, absolutely, and the
environment is not consulted.** A printed line has to mean the same thing wherever it is
pasted, and "the default library" is exactly what terminals disagree about:
`DOJO_DB=chosen.sqlite3` names a different file in every directory, a variable set for one
command is absent in the next terminal, and a terminal that usually works on another
library is not the one the line came from. `--db whatever/dojo.sqlite3` is spelled out for
the same reason. Trace paths are absolute too, since `$DOJO_SESSIONS` can be relative.

The cost is a longer line on the common path. The reason to pay it: with the short form,
pasting `--resume` from a session started on the default library into a shell that uses
another library exited 0 *and* appended the second half of that conversation to that other
library.

The library path is never written into the trace: the record of what you said stays a
record of what you said, wherever the file happens to live.

## What it can do now

- **Candidate ledger with provenance.** Each record carries statement, kind, premises, scope, alternatives, contradictions, unknowns, and structured sources — never a raw chat transcript.
- **Discussability ≠ truth.** `confirm` marks a candidate as worth discussing and retrieving; `revoke` withdraws that mark; `abstain` records uncertainty without touching a version.
- **Immutable versions.** `revise`, `challenge`, `link`, `split` and `merge` all keep prior versions and the reason for the change; `unmerge` restores an exact pre-merge record as a new version.
- **A changed mind travels with the sentence.** When he later narrows a claim, every reader surface — `search`, `broadcast`, `show` and `export` — carries `revision_basis`: the wording he replaced, his own `reason` verbatim, and when he changed it. It speaks only for the wording the card holds now: revise again and the reason attached is the new one, while the earlier reason stays in `show --history` rather than being deleted. A card he never revised keeps exactly the bytes it had (no such key), and a repeated request does not move it. This is not an endorsement of the current sentence — the reason is his words, not the library's judgement.
- **Transparent retrieval.** `search` is lexical overlap with the hit words printed — CJK multi-character queries match adjacent bigrams, single characters match themselves. No embeddings, no hidden ranking; only `discussable` candidates are returned and merge redirects resolve to the canonical ID.
- **No double-entry inflation.** Re-adding the same content is refused and reports the existing card ID; a second independent session that reaches the same conclusion uses `attach-source` instead of writing a second card.
- **Independence guard on broadcast.** `broadcast` suppresses cards whose only independent source is the session that wrote them, and cards written by the session asking; suppressed cards are listed with the reason rather than silently dropped.
- **Idempotent end-of-session passes.** `pipeline --session <id>` runs `classify → locate → challenge` once per card per revision; a re-run writes nothing, and every pass only proposes.
- **Bounded prompt export.** `export --mode b` (shared goal, no seeds) or `--mode c --id …` (goal plus explicitly chosen candidates) with `--budget-chars` as a hard character cap; exports carry no actor or judge notes.
- **Discussion that retains the price and its source.** `discuss` asks four things per rule — situation, tension, cost, failure — and records the exact free-text answer beside its question and field key. Collected answers are not automatically mapped to candidate content or promoted to “the user's own words”: until that mapping exists, model-generated candidate fields remain `系统补`. Useful user contributions are retained in the trace, not certified by a nonempty reply. When the four questions finish — or the session stops early — one closing line says what happened to each part and where the answers went: they stay in this session's record, and the card is the sentence written before the questions, which the questions never rewrite. Every part gets exactly one word, and the word is the one for what actually happened: *his words were kept* (the line says “你在 X 上说了原话”, not “你答了” — the program checked that the reply was not empty, not that it hit the question, and it says so on screen); asked to skip; the input ended while that question was on screen (not “you could not answer it”); put aside by a request covering the questions still to come; asked twice with nothing usable back; or never asked. A request for the questions still to come is read as a scope, not assumed: “接下来两题先跳过” lays down two and the last one is still asked, “这几题我想先跳过” lays down whatever is left, and a request whose count cannot be read leaves the remaining questions *asked* rather than ending the session on the person's behalf. “先跳过这一题” and its plain-speech variants read as a request to skip that question, not as an answer; material that talks about a rule — "我跳过这一步的时候就会出错", "剩下的流程我都不讲给新人听" — is still an answer.
- **A host that answers instead of stalling.** It infers the parameters you did not state and writes their conditions, does the arithmetic it can, and hands off real computation as a `## 计算交接单` section that lands on disk as `<session dir>/compute-<id>-<turn>.md` for an external runner — it has no code execution and never claims to have run something.
- **Bounded requests.** Retrieval brings page text back with caps of 1200 characters per excerpt and 6000 per session; reasoning level is `DOJO_LLM_REASONING` (default `medium`); one request times out at 60 s and `DOJO_LLM_TIMEOUT` accepts 5–600.
- **Local trace of every session.** One JSON line per turn: your words, the host's answer, the candidate, the stance decision and its reason, token counts, failures. Default on, `--no-trace` removes it entirely, `--resume <trace>` continues the same session.
- **Offline replay.** `compare` prints the two archived Luna answers with their provenance and sha256; `freeze-materials` regenerates the four frozen model inputs, C condition from a real local retrieval.
- **The "life of one dao" loop.** `scripts/dao_life.py` builds a dao library from concrete episodes, checks self-consistency and refutability, prints which observations were never run and what would be needed, and compares two libraries pair by pair — no model, no network, no database.
- **A real conversation becomes a probe note.** `scripts/dao_session.py` turns a `discuss` JSONL trace into the probe note plus `session.json`, the record of which four parts he actually answered. An unanswered part, a tension without two sides, or an answer the note format cannot carry refuses by name and writes nothing; `dao_life.py` then takes authorship from the session, so an `extraction.json` that claims a part the session did not promote is refused.

**One judgement, two places it changed a decision.** The rule is that a repeat is judged
by its *intended effect*, and that a client may retry only with evidence that the first
attempt did not take effect. Two decisions in this repository were wrong under it:

- **A cut response was re-sent.** A body shorter than its `Content-Length` was classified
  as a malformed model answer and retried twice — three requests for one user turn, and
  the user told to fix their prompt. It is now `incomplete_response`: not retried, and the
  user is told the transfer broke.
- **A second reason was filed as a replay.** Revising a card to the sentence it already
  has, for a new reason, changes no wording — and the store read "the card did not move"
  as "the same request again", recording the new reason as a repeat of the first. Two
  different arguments ended up in the ledger under one name. The rule now kept is that
  *the version moves only when the stored card changes, but a repeat is decided by the
  request, not by its result.*
  Deciding it by the *reason* alone was half a rule: taking a card to narrow screens for
  accessibility, then to every viewport for another reason, then to every viewport citing
  accessibility again, repeats a reason but not a request — and the pointer named the
  narrow-screen revise, which asked for a different sentence. Deciding it by the *names*
  of the fields that moved was the other half: same wording, same reason, one request
  scoped to narrow screens and the next to every viewport recorded the identical
  `["statement", "scope"]`, so the wider one was filed as a replay of the narrower.
  A repeat is now judged by the whole ask as one object — `request`, holding every input
  the caller supplied, `scope` and premises included — stored on the row rather than
  reconstructed from a list of keys to ignore (that list was wrong twice). Every event in
  `show --history` carries the `sequence` number `repeat_of` speaks in, so you can walk
  from a replay to the row that asked for the same thing, and a row written before asks
  were stored is counted in `earlier_rows_without_a_recorded_request` instead of being
  quietly read as a different request.

The block below shows the second one on a real library: two reasons, two rows; the same
reason again, one row and one `.repeat` that names a row asking for the same wording.

```sh
DEMO=$(mktemp -d)
export DOJO_DB=$DEMO/twice.sqlite3
python3 -m dojo add --id same-words --kind abstract_idea --statement '一键确认很好用'
python3 -m dojo revise same-words --statement '一键确认很快' --reason '移动端同伴看不见活动灯'
python3 -m dojo revise same-words --statement '一键确认很快' --reason '触屏读屏需要一个可读状态'
python3 -m dojo revise same-words --statement '一键确认很快' --reason '触屏读屏需要一个可读状态'
python3 -m dojo events --id same-words   # both reasons, plus one row that says it was a replay
```

The two reasons are separate `revise` rows and neither names the other. The repeat is a
`revise.repeat` naming the row it repeats, and `version` stays at 2 throughout, so no
finished pipeline pass turns back into pending work. Each row carries `to_statement` — the
wording it asked for — beside `from_statement`, which is why the replay cannot name a row
that asked for a different sentence, and `details.request` holds the whole ask so a
changed `scope` counts as a different request even when the wording and the reason match. Before/after readings for both
decisions, and the arms that fail on the old trees, are in
[`docs/evidence/2026-11-27-repeat-safety/`](docs/evidence/2026-11-27-repeat-safety/).

## Architecture

The runtime is deliberately small: one SQLite file is the whole state, the CLI is a thin argparse surface, and everything above the store either proposes or renders.

```
dojo/
  cli.py         argparse surface: one subcommand per store operation
  storage.py     SQLite schema, versions and events, retrieval, merge/split, export
  live.py        bounded OpenAI-compatible HTTP client on urllib
  discuss.py     natural-language loop: write-on-agreement, traces, person.md profile
  elicit.py      the four questions and the "who wrote it" rules, in one place
  pipeline.py    classify → locate → challenge, once per card per revision
  search.py      lexical overlap scoring with visible hit words
  demo.py        three-act simulated story; freeze-materials
  compare.py     offline replay of archived answers
scripts/
  dao_life.py    K1 loop: episodes → daos → receipts → map, with refusals
  dao_session.py discuss trace → probe note + the authorship record
  dao_live_session.py, dao_elicit.py, tension_overlap.py
  demo.sh, storage-smoke.sh
tests/           unittest suite, standard library only
docs/            the layered fact base; index in docs/README.md
docs/dao/        K1 data: repeat-safety, person-dojo, demo-strangers, probe-demo, vocabulary.json
inbox/, mail/    working notes kept as history
idea.md          the original draft, preserved unchanged
```

How the pieces talk: `cli.py` parses a command and hands it to `Store` (`storage.py`), which is the only writer to SQLite and the only reader for retrieval. `discuss.py` composes the host prompt, calls `live.py`, writes the turn to a local JSONL trace, and writes a card only when the model reports the user accepted. `pipeline.py` is a reader/writer over the same store, run after the session. `scripts/dao_life.py` touches no database at all: it reads and writes the JSON library under `docs/dao/` and is reproducible byte for byte for a given `--at`.

State and privacy, stated plainly:

- Default database `~/.local/share/dojo/dojo.sqlite3` (`DOJO_DB` or `--db` to move it); its app directory is created `0700`, the file `0600`.
- `discuss` keeps a fixed `person.md` next to the database, `0600`, append-only after creation; `--no-profile` neither reads nor writes it.
- Session traces live at `<db dir>/sessions/<session>.jsonl`, `0600`; local only, never uploaded.
- Exports go to `~/.local/share/dojo/exports` with unique filenames and never overwrite (`DOJO_EXPORTS`, `--outdir`).
- Model-side privacy constraints are prompt-level, not enforced filtering. The database stores candidates, source summaries, anonymous session IDs, versions and events — not raw chat; the trace is the one place your own words are kept, and it can be turned off.

### Where the facts live

- [`docs/product.md`](docs/product.md) — product direction, quality dimensions, non-goals; the single entry point for what this is meant to be.
- [`docs/design.md`](docs/design.md) — invariants, modules, pipeline, anti-storm and anti-pollution rules.
- [`docs/plan.md`](docs/plan.md) — milestones, acceptance lines, budget, delivery contract; `## 当前推进状态` says where work is stuck right now.
- [`docs/dao/README.md`](docs/dao/README.md) — the K1 library: what each file is, who writes it, and what is still weak. [`docs/dao/repeat-safety/LOOP.md`](docs/dao/repeat-safety/LOOP.md) is the one chain that runs end to end: a sourced account, the judgement drawn from it, and the two decisions that judgement changed — a cut response that was re-sent (3 requests per turn → 1) and an `attach-source` that silently dropped a second source.
- [`docs/cli-guide.md`](docs/cli-guide.md) — a 15-minute store walkthrough; [`docs/demo-guide.md`](docs/demo-guide.md) — the demo, flag by flag.
- [`docs/evidence/`](docs/evidence/) — archived evidence bound to commits, not current fact.

`idea.md` is the preserved original draft: it motivates the direction and is never a behavioral spec.

## Development

```sh
python3 -m unittest discover -s tests -v   # full suite, no install, no network
python3 -m compileall -q dojo tests        # syntax check across the tree
sh scripts/storage-smoke.sh                # end-to-end CLI walk in a temp directory
```

Development conventions and the full layered documentation index are in [`docs/README.md`](docs/README.md); collaboration boundaries (single maintainer, no UI, no scope invented from the draft) are in [`AGENTS.md`](AGENTS.md).

## Contributing

Read [`CONTRIBUTING.md`](CONTRIBUTING.md). In short: this is a scope-disciplined POC — behavior changes need an acceptance line before the code, tests run on the standard library, and no dependency gets added for convenience.

## Roadmap

**Implemented**

- Candidate lifecycle with provenance, immutable versions, reversible merge and split; lexical retrieval with merge redirects; duplicate refusal.
- Broadcast independence guard, session-end `classify → locate → challenge` pipeline, bounded B/C prompt export.
- Three-act offline demo, offline comparison replay, frozen-material generator.
- `discuss`: zero-structure natural-language loop; the accepted version becomes the card, and a version nobody accepted is kept as an `unaccepted_draft` (source `model_generated`/`unverified`, not `discussable`, so no other session receives it as material). Local traces, `--resume`, `person.md` profile, compute handoff file when an answer needs a real calculation.
- K1 "the life of one dao": the loop runs over one real person's record (13 daos, 9 materials that could not be written into a dao, 1 candidate, 1 self-contradicting pair, 26 record checks, 0 promotions), plus a second library that is synthetic by construction and says so.
- A completed `discuss` session can be exported as the probe note; the session, not the handwritten extraction, decides which parts are his, and the library refuses an extraction that claims an unpromoted part.
- A standard-library test suite covering the CLI, store, retrieval, discussion, demo, pipeline and the K1 loop.

**Planned, honestly unfinished**

- M2 is not met: `classify` reports `unavailable` instead of guessing, so it still needs one real model judgement, and the end-of-session distillation list has not been run in full and reviewed.
- The experimental harness and the tension-convergence probe are specified but not run; `docs/probe/notes/` holds zero notes.
- There is exactly one real person's record. The cross-person promise of a shared database of "dao" has no cross-person evidence yet; until a second person's material lands, read this as one person's thought organizer, not as humanity's dao.
- Not built and not planned near-term: UI, server, login, social features, rankings, feeds, billing, multi-node federation.

The direction, if the loop survives contact with more than one person: a claim arrives stripped of the occasion it came from but carrying its boundary, its counterexample and the author of each part — so a stranger facing a real decision gets the method with its conditions attached, disagreement produces a new version instead of a deletion, and nothing is graded true by repetition.

## License

GNU Affero General Public License v3.0 — see [`LICENSE`](LICENSE). Copyright (C) ZisIsNotZis.

`idea.md` is the author's original draft, preserved as historical source and not rewritten. Every demo persona, seed and simulated corpus in this repository is simulated material, not a research result, independent evidence, or a claim of product effect.
