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
python3 -m dojo add --id idea-01 --kind abstract_idea \
  --statement '降低与目标无关的摩擦能让重复行为更容易持续' \
  --scope '日常重复行为' --unknown '哪些难度是有意义的训练而非无谓摩擦'
python3 -m dojo confirm idea-01 --basis '表述清楚，值得检索；不表示为真'
python3 -m dojo search '摩擦 持续 行为'          # lexical overlap, hit words shown
python3 -m dojo show idea-01 --history          # versions and events
python3 -m dojo challenge idea-01 --text '把一切变容易未必有益'
python3 -m dojo revise idea-01 --statement '在难度不是训练的情况下，降低无关摩擦才让重复行为更容易持续' \
  --reason '补上失效条件，保留旧版本'
python3 -m dojo revoke idea-01 --reason '范围仍不清楚'   # revoking discussability, not deleting history
```


What the demo is, and what it is not: three strangers with independent problems — making tidiness stick, writing code before the requirement is clear, and the objection that some ability is built by difficulty — each get a candidate, a retrieval from the real local store, and a challenge that produces a new version without deleting the old one. Every line is scripted, the seed records `seed-m01`–`seed-m04` are simulated material, and the personas are not user research. `compare --full` replays two archived Luna answers offline (old editor-bridge evaluation material, not the current story); `freeze-materials` writes four frozen model inputs with C condition drawn from a real store retrieval; `demo --workdir ./run` keeps the database and a short summary in a new or empty directory and refuses to overwrite.


Merging is never automatic; it needs an explicit human judgement and is reversible:

```sh
python3 -m dojo merge idea-alias idea-01 --confirm --reason '主持人核对主张及范围可互换'
python3 -m dojo show idea-alias      # canonical ID plus redirect chain
python3 -m dojo unmerge idea-alias --reason '复核后撤销'
```

Natural-language discussion against a model endpoint is opt-in and is the only path that touches the network:

```sh
export DOJO_LLM_BASE_URL=http://127.0.0.1:4000/v1
export DOJO_LLM_MODEL=github_copilot/gpt-6-luna   # must match the endpoint's registered id
# then set DOJO_LLM_API_KEY in this shell from your endpoint's key store; the repo never holds it
python3 -m dojo discuss            # zero forms, zero y/n prompts; writes only on agreement
python3 -m dojo discuss --verbose  # live request/retrieval progress on stderr
```

## What it can do now

- **Candidate ledger with provenance.** Each record carries statement, kind, premises, scope, alternatives, contradictions, unknowns, and structured sources — never a raw chat transcript.
- **Discussability ≠ truth.** `confirm` marks a candidate as worth discussing and retrieving; `revoke` withdraws that mark; `abstain` records uncertainty without touching a version.
- **Immutable versions.** `revise`, `challenge`, `link`, `split` and `merge` all keep prior versions and the reason for the change; `unmerge` restores an exact pre-merge record as a new version.
- **Transparent retrieval.** `search` is lexical overlap with the hit words printed — CJK multi-character queries match adjacent bigrams, single characters match themselves. No embeddings, no hidden ranking; only `discussable` candidates are returned and merge redirects resolve to the canonical ID.
- **No double-entry inflation.** Re-adding the same content is refused and reports the existing card ID; a second independent session that reaches the same conclusion uses `attach-source` instead of writing a second card.
- **Independence guard on broadcast.** `broadcast` suppresses cards whose only independent source is the session that wrote them, and cards written by the session asking; suppressed cards are listed with the reason rather than silently dropped.
- **Idempotent end-of-session passes.** `pipeline --session <id>` runs `classify → locate → challenge` once per card per revision; a re-run writes nothing, and every pass only proposes.
- **Bounded prompt export.** `export --mode b` (shared goal, no seeds) or `--mode c --id …` (goal plus explicitly chosen candidates) with `--budget-chars` as a hard character cap; exports carry no actor or judge notes.
- **Discussion that stores the price.** `discuss` asks four things per rule — situation, tension, cost, failure — with the author of each part recorded and the weakest part capping the grade (`合写` whenever any part was filled by the system).
- **A host that answers instead of stalling.** It infers the parameters you did not state and writes their conditions, does the arithmetic it can, and hands off real computation as a `## 计算交接单` section that lands on disk as `<session dir>/compute-<id>-<turn>.md` for an external runner — it has no code execution and never claims to have run something.
- **Bounded requests.** Retrieval brings page text back with caps of 1200 characters per excerpt and 6000 per session; reasoning level is `DOJO_LLM_REASONING` (default `medium`); one request times out at 60 s and `DOJO_LLM_TIMEOUT` accepts 5–600.
- **Local trace of every session.** One JSON line per turn: your words, the host's answer, the candidate, the stance decision and its reason, token counts, failures. Default on, `--no-trace` removes it entirely, `--resume <trace>` continues the same session.
- **Offline replay.** `compare` prints the two archived Luna answers with their provenance and sha256; `freeze-materials` regenerates the four frozen model inputs, C condition from a real local retrieval.
- **The "life of one dao" loop.** `scripts/dao_life.py` builds a dao library from concrete episodes, checks self-consistency and refutability, prints which observations were never run and what would be needed, and compares two libraries pair by pair — no model, no network, no database.
- **A real conversation becomes a probe note.** `scripts/dao_session.py` turns a `discuss` JSONL trace into the probe note plus `session.json`, the record of which four parts he actually answered. An unanswered part, a tension without two sides, or an answer the note format cannot carry refuses by name and writes nothing; `dao_life.py` then takes authorship from the session, so an `extraction.json` that claims a part the session did not promote is refused.

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
docs/dao/        K1 data: person-dojo, demo-strangers, probe-demo, vocabulary.json
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
- [`docs/dao/README.md`](docs/dao/README.md) — the K1 library: what each file is, who writes it, and what is still weak.
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
- `discuss`: zero-structure natural-language loop, write on the turn agreement happens, local traces, `--resume`, `person.md` profile, compute handoff file when an answer needs a real calculation.
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
