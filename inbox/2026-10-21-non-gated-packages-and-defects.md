kind:    report
from:    dojo (manager, launched by root's `go` second contract)
spend:   machine_time, idle class; no device held exclusively; no money spent
id:      inbox/2026-10-21-next-contract.md — read, landed in docs/plan.md, file deleted; git 2a17e17 still holds it

# The non-gated M2 packages are code with commands this time, and three of M2's five items can now be re-derived

## What changes on your roadmap

M2 as a milestone has **not** moved and its gate still waits for the person: I did not deliver a distillation list, did not start M3, and did not answer the M1/M1.5 checkpoint on their behalf. What changed is that the four items of M2 that are code are now code, each with the command that shows it, and the two defects your contract named are closed.

| package | what is now true | the command |
|---|---|---|
| `inbox-migrate` | `mail/` no longer exists; messages live in `inbox/` with the four header lines; the answered gate report and your contract are deleted after landing; the verdict is archived with a banner binding it to `939bf90` | `ls inbox docs/evidence/reviews` |
| `default-model` | `DEFAULT_MODEL` is `github_copilot/gpt-6-luna`, so an unset `DOJO_LLM_MODEL` no longer 400s on every request; a test pins it and fails if any module that builds an HTTP request spells it with a hyphen | `python3 -m unittest discover -s tests -p 'test_live.py'` → 4 tests, OK |
| `isolation-guard` (②) | `broadcast` refuses cards whose only independence source is the session that wrote them, and refuses the asking session's own cards, listing each with its reason in `suppressed`; `export --mode c` refuses them outright and stamps `independence_groups`/`independent` on every excerpt | `python3 -m unittest discover -s tests -p 'test_storage.py' -k broadcast` → 3 tests, OK |
| `duplicate-content` (③) | the same claim written twice produces one card: `add` compares content, ignores spacing and list order, and raises naming the existing card, writing nothing; a second independent session reaches the same conclusion by `attach-source` instead, which is what makes it a second independence group, and re-attaching the same session is a no-op | `python3 -m unittest discover -s tests -p 'test_storage.py' -k duplicate` → 4 tests, OK |
| `pipe-core` (M2's `m2a`, ④) | `pipeline --session <s>` runs `classify → locate → challenge` over that session's cards, marks each pass at the card version it processed, and a rerun skips everything and writes no event; a revised card is picked up again; passes propose, never merge or rewrite | `python3 -m unittest discover -s tests -p 'test_pipeline.py'` → 8 tests, OK |

M2's five acceptance items, item by item, at `63c46a7`: ① **still cannot be judged** — there is no distillation output to sample, and `classify` reports itself `unavailable` with the reason instead of inventing a `kind`; ② ③ ④ now have implementations and commands; ⑤ is unchanged as a store capability with its existing test. That is **not** M2 passing, and `docs/plan.md` now says so per item.

## Evidence, bound to `63c46a7`, worktree clean, branch `master`, ahead of `origin/master`, nothing pushed

```
python3 -m unittest discover -s tests        → Ran 121 tests in 40.755s, OK
git log --oneline origin/master..HEAD        → 8 commits, the 6 of this advance on top of the 2 inherited
```

The verdict's own ② probe, re-run at HEAD with the store in `/tmp/m2ev` (a card written by `sess-a` with `sess-a` as its only independence group, then confirmed):

```
search    → results ['d-7f1e9d308914']                       # the old surface still sees it
broadcast → results []; suppressed [{id: d-7f1e9d308914,
             reason: 'single-session provenance: no second independent group backs it'}]
export --mode c → error: single-session provenance cannot be exported as cross-session material
add (same content, sess-b) → error: duplicate content already stored as d-7f1e9d308914 (status discussable, v2); no new version was created
pipeline --session sess-a (run 1) → events_written 2
pipeline --session sess-a (run 2) → events_written 0; locate skipped 1; challenge skipped 1
events → ['add', 'confirm_discussable', 'pipeline_pass', 'pipeline_pass']   # run 2 added nothing
list → 1 candidate
```

The verdict's document finding is closed: `grep -c "Ran 98" docs/plan.md` → 0, and the baseline line now stores the command rather than a number.

## The decision I need

**One: an independent verdict on this advance, or an explicit waiver.** `981f979..63c46a7` is my own work and my own word does not count; my contract did not authorise me to fan out, so I dispatched nothing. Six commits. The failure this would catch, stated so it is falsifiable: a claim in `docs/plan.md`, `README.md` or `docs/cli-guide.md` that the code does not do, or a guard that passes on absence the way ② did before. The cheapest way to expose the second is to try to make a single-session card reach `broadcast` or `export --mode c`; the first is the three files' diff.

**Nothing else.** The M1/M1.5 checkpoint is still the person's to answer and it is not a question for you; when it lands, M2 is dispatch-ready and `m2e` is the package that closes it.

## What I did that you did not order, so you can reverse it

- **I read the gate as covering delivery, not code.** Your contract says to land what M2 needs and that nothing depending on the gate is dispatched; I took that to permit `pipe-core`, `isolation-guard` and `duplicate-content`, because they change no M1 behaviour and call no model. If you meant the gate to cover M2 code too, `b5be333`, `9cea94c`, `1452d53` are the three to reverse, in that order.
- **I changed one existing test** (`tests/test_conversation.py:538`): it asserted the hyphenated default, i.e. it pinned the defect. It now asserts the published spelling.
- **I moved the wording comparison out of `discuss.py`** into `storage.py`, because the new pipeline needed the same judgement and two copies would have been two homes for one rule.
- **I did not wire the guard into `discuss`'s mid-session retrieval.** It still uses plain `retrieve`, so a session can retrieve its own conclusion back. Changing that touches delivered M1 behaviour and belongs to M3's narration; it is recorded as an open question in `docs/plan.md` rather than decided quietly.
- **I archived the verdict** at `docs/evidence/reviews/2026-10-21-advance-review-verdict.md` instead of deleting it after reading: it is the only review record M2 has, and the banner says which revision it binds to and that its counts expire.

## Residual risks

- **No independent verdict on any of this.** My reading of my own diff is not evidence.
- **`isolation-guard` enforces exactly the sentence design.md writes, and no more.** A card whose one provenance group is a methodology rather than a session (the seeds, the simulated material) still broadcasts, carrying `independence: false` in the result. A live `chat` card is in that category too. If the invariant was meant to be "two independent groups or nothing enters broadcast", the seeds would all be suppressed and M3's demo material would need a decision from the person — that is a scope call I did not take.
- **`classify` is declared and unavailable, so ① is unjudged rather than judged.** No endpoint answers here (`curl -m 3 http://127.0.0.1:4000/v1/models` → HTTP 401), so the m2.0/m2.1 live scripts were not re-run either and carry no M2 weight.
- **The pipeline's `locate` and `challenge` are lexical rules, not judgement.** `locate` proposes 变体 where wording is equivalent but content differs, and 重复 only for data that predates the `add` guard; `challenge` proposes where two neighbours share three bigrams and one negates the other. Both are transparent and both are proposals. Neither claims to be the classify step's judgement.
- **`add` now scans every candidate before writing.** Correct for this POC's size; it is a linear scan, not an index, and would need one before the card count is large.

## Effort

Roughly 75 minutes of wall clock, no model call, no search call, no device, no money. Six commits, nothing pushed, no file outside `/home/z/vibe/dojo/` touched. The review above is yours to price.
