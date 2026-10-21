kind:    report
from:    dojo (manager)
spend:   machine_time, idle class; no device; no money; ~28 min wall clock
id:      inbox/2026-10-21-next-contract.md — read, landed in docs/plan.md, file deleted; git bd4c298 still holds it

# The three defects are closed at `10cdc00`, and the M2 gate has not moved

## What changes on your roadmap

Nothing about M2: the gate still waits for the person, `m2e` is not started, no distillation list exists, and ① is still unjudgeable (`classify` reports `unavailable`). What changed is that each of the verdict's three defects now has a reproduction that ran before and after at named revisions.

| defect | before | after |
|---|---|---|
| ① the guard admitted a card with no provenance group | at `bd4c298`: `broadcast` → `['d-75d7a6d89fe6']`, `suppressed: []`, `independence {groups: [], sessions: ['sess-A'], single_session: false}`; `export --mode c` exit 0 | at `10cdc00`: `broadcast` → `results: []`, `suppressed: [{"id": ..., "reason": "single-session provenance: the card's whole provenance is the one session that wrote it"}]`; `export --mode c` exit 2 |
| ② the scan was narrower than its claim | at `bd4c298`: `HTTP_MODEL_MODULES = ("live.py", "discuss.py")`; a hyphen id injected into `dojo/search.py` left `test_live.py` OK | at `10cdc00`: the module set is derived from the code (any `dojo/*.py` importing `urllib.request`/`http.client`/`litellm`/`requests`); the same injection in an isolated copy → `test_live.py` FAILED, `['search.py: github-copilot/gpt-6-luna']`; the derivation is asserted to contain `live.py` and `search.py` |
| ③ the report's evidence printed a count its command does not return | the line stood | withdrawn in `docs/plan.md` `## 证据卫生` as a current fact (the count came from memory, not from the command); the file that carried it is deleted |

The cure I chose for ① is the class, not the site: provenance is now the card's source groups ∪ the sessions that wrote it, and `provenance_status` names three cases instead of computing two booleans, so an absent provenance group is *named* (`unidentified`) instead of defaulting to "pass". The asking session is now excluded when only a source group names it, too.

Not asked for but inside the same class: `test_passes_run_in_the_declared_order` compared the report to `PASS_ORDER` and so could not fail when the constant was reordered. It now spells `["classify", "locate", "challenge"]`; reordering `PASS_ORDER` in an isolated copy → FAILED.

Also landed and not ordered: the second verdict is archived at `docs/evidence/reviews/2026-10-21-advance-review-verdict-d915520.md` with a banner naming the revision it binds to, because it is the only independent record this advance has.

## Evidence, at `10cdc00`, worktree clean, branch `master`, nothing pushed

```
git status --porcelain -uall          -> 0 lines
python3 -m unittest discover -s tests -> Ran 125 tests in 36.323s, OK      (121 at bd4c298; +4 are the new guard tests)
python3 -m unittest discover -s tests -p 'test_storage.py' -k broadcast -> Ran 4 tests, OK
python3 -m unittest discover -s tests -p 'test_live.py'                 -> Ran 5 tests, OK   (was 4: +1 pins the derivation)
python3 -m compileall -q dojo tests   -> rc=0
git log --oneline origin/master..HEAD | wc -l -> 19
```

**Those five lines were run at `10cdc00` and copied from the output.** The last one is what the command returns; I did not convert it into a claim about which commits are whose.

Reproductions live in `/tmp/rp/repro.py` (defect ① shape A), `/tmp/rp/reproB.py` (the shape-B boundary) and `/tmp/rp/mut` (the mutation copies); none of them is in the repo, so they are re-derived from this file rather than reused.

## The decision I need

**None for this advance.** One open scope call, which is the person's and not mine, and which I did not take: a card whose single provenance group is not a session the store can see — the four seeds, simulated methodology material, and a write that puts a session name in a source group but passes no `--session` — is still admitted to `broadcast`, now reported as `provenance_status: unidentified` and `independent: false` instead of being silently read as "not single-session". If ② was meant as "two independent groups or nothing", the seeds lose broadcast and M3's demo material needs a replacement; that costs the person a decision about what M3 opens with. It is recorded in `docs/plan.md` on the boundary paragraph, not decided quietly.

## Residual risks

- **My own word still does not count.** These three closures have no independent verdict; the fail that produced them is fixed by the author of the fail. A second review of `e39e2dc..10cdc00` would be the check, and root decides whether it is worth it.
- **The ② derivation is a heuristic.** "Imports an HTTP client" is the best available reading of "发 HTTP 请求的模块"; a module that builds a request through a helper it imports but does not name would still be missed. The two tests assert the set is not empty and contains the two real builders, which is the falsifiable part.
- **`provenance_status: unidentified` changes a shape M3 will consume**, not just a report field: narration must say "one unidentified source" rather than "another stranger". That is M3's work and it is now stated in `docs/plan.md` and `docs/cli-guide.md`.
- **The gate is untouched and the M1/M1.5 checkpoint remains unanswered.** Nothing here presumes M2 passed.

Effort: about 28 minutes wall clock, no model call, no search call, no device, no money, two commits, nothing pushed, no file outside `/home/z/vibe/dojo/` touched.
