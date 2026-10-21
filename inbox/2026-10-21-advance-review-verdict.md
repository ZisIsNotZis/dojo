Read at `d915520bbc44471115f0bb4252dfc4181807c1ce`, worktree clean (`git status --porcelain -uall` → 0 lines), branch `master`, nothing staged, I wrote no file in the project — every probe ran under `/tmp/rv915/`.

## Base I used, and why

`2a17e17` (root's contract commit, as the task names it) — it is the last commit before the advance's own first act (`981f979`, the `mail/`→`inbox/` migration), so `2a17e17..d915520` = the 8 commits the advance added: `981f979`, `5c2d11c` (default-model), `9cea94c` (isolation), `1452d53` (duplicate), `b5be333` (pipe-core), `63c46a7`, `177598a` (report), `d915520` (plan table). The project's own records name a different base — `git log --oneline origin/master..HEAD`, and `origin/master` is the local ref `621bf26` (I did not fetch), which makes the count 16. Both numbers are below so either base can be checked.

## Verdict: **fail** — every package's named behaviour reproduces, but two document claims at `d915520` are false for inputs the CLI admits, and the report's own evidence block prints a commit count the command does not return

I looked for the counterexample rather than confirming the prose: a single-session card that reaches the fan-out surfaces anyway, a guard whose scan is narrower than its stated scope, and a test that cannot fail for the property it names.

### Defect 1 — M2 ②'s guard admits a session-written card with no provenance group (`dojo/storage.py:932`)

`single_session = len(groups) == 1 and groups[0] in sessions`, so a card with **zero** independence groups is `single_session: False` and passes both surfaces. Criterion violated: `docs/design.md:91` 「单一会话来源不进入广播」, the item `docs/plan.md:134` marks 「有实现与命令」and `docs/cli-guide.md:60,64` present as covered. Reproduction at `d915520` (store in `/tmp`):

```
add(kind=application, scope=[交接], session='sess-A')            # no sources at all
confirm; broadcast('交接 版本 范围')
  -> results ['d-f7c4848300b2']  independence {groups: [], sessions: ['sess-A'], single_session: false, independent: false}
export --mode c --id d-f7c4848300b2  -> WROTE (cli-guide:64 says 单一会话来源的卡会被拒)

add(..., sources=[group='sess-A'], no --session)                  # source itself says 单一会话来源
confirm; broadcast -> results ['d-92e0462c4153'];  export --mode c -> WROTE
```

The report's own probe (session **and** `independence_group` = that session) does reproduce — `broadcast` → `[]` with `suppressed: single-session provenance…`, `export --mode c` → refused. So the guard is real; the hole is the case where the store cannot see the writer: `plan.md:138`'s boundary paragraph discloses the "one group that isn't a session" case and the `unknown` case, not this one. `discuss` is safe (it always writes both fields, `dojo/discuss.py:311-322`) — the exposure is the `add`/`attach-source` CLI path, i.e. exactly what M3 would draw from. This is the same class the previous verdict failed ② on: passing on absence. `-k broadcast` (3 tests) cannot fail on it — none of the three tests writes a card without a group.

### Defect 2 — the `DEFAULT_MODEL` guard's stated scope is wider than its scan (`tests/test_live.py:22,37`)

`HTTP_MODEL_MODULES = ("live.py", "discuss.py")`. The report says the test "fails if any module that builds an HTTP request spells it with a hyphen", and `docs/plan.md:153` says 「任何**发 HTTP 请求的模块**」. `dojo/search.py` builds HTTP requests (`urllib.request`, lines 8-9, 83-92) and is not scanned. Gate probe in an isolated copy: inject `MODEL_FOR_TESTS = 'github-copilot/gpt-6-luna'` into `dojo/search.py` → `test_live.py` still `Ran 4 tests … OK`. No such error exists today (`grep -rn "github-copilot" dojo/` → `compare.py:46`, `demo.py:438`, both deliberate and documented), so this is a false claim about the guard, not a live defect. The guard does work where it is aimed: resetting `DEFAULT_MODEL` to the hyphen spelling in a clean copy fails 3 of the 4 tests, including the module scan.

### Defect 3 — the report's bound evidence prints a count its command does not return (`inbox/2026-10-21-non-gated-packages-and-defects.md:26`)

`git log --oneline origin/master..HEAD → 8 commits, the 6 of this advance on top of the 2 inherited`. At the revision the block binds to (`63c46a7`) that command returns **14**; at `d915520` it returns 16. The "6 of this advance" part is right (`2a17e17..63c46a7` = 6). As printed, one of the three evidence pointers is wrong, so that line cannot be quoted as bound evidence.

## What the plan says each package had to make true, and what each command did at `d915520`

| package (`docs/plan.md` claim) | its command | my run | holds? |
|---|---|---|---|
| `default-model` — unset `DOJO_LLM_MODEL` uses the published underscore id, pinned, hyphen fails | `unittest … -p 'test_live.py'` | Ran 4, OK | **yes** (`DEFAULT_MODEL` = `github_copilot/gpt-6-luna`, `live.py:18`; mutation probe fails it) — scope claim overbroad, defect 2 |
| `pipe-core` (m2a / ④) — `classify → locate → challenge`, "processed to version N", rerun writes nothing, revised card re-runs, passes only propose | `-p 'test_pipeline.py'`; CLI twice | Ran 8, OK; CLI run 1 `events_written 2`, run 2 `0` with `locate`/`challenge` skipped at `processed_version 2`; events `['add','confirm_discussable','pipeline_pass','pipeline_pass']` | **yes** |
| `duplicate-content` (③) — same content writes no second card or version | `-k duplicate`; CLI twice | Ran 4, OK; second `add` → `error: duplicate content already stored as d-2c7462e66697 (status discussable, v2); no new version was created`, `list` still 1 | **yes** |
| `isolation-guard` (②) — refuses single-session cards and the asker's own; export too; reasons in `suppressed` | `-k broadcast`; `broadcast '<q>'` | Ran 3, OK; report's probe reproduces exactly | **no for the class** — defect 1; the tested case holds |
| `inbox-migrate` — `mail/` gone, four header lines, verdict archived | `ls inbox docs/evidence/reviews` | `inbox/` holds `README.md` + the report; no `mail/`; verdict at `docs/evidence/reviews/` | **yes** |

## Your three judgements

- **Is the code code?** Yes. `2a17e17..HEAD` adds 174 lines of `dojo/pipeline.py` and ~250 of `dojo/storage.py`; every package's behaviour is reachable from `python3 -m dojo …` and I reached it. This is not the previous advance's 199 lines of prose.
- **Could any test not fail as written?** One: `test_passes_run_in_the_declared_order` (`tests/test_pipeline.py:60`) asserts the report against `PASS_ORDER` itself, so it cannot fail if `PASS_ORDER` is reordered — it pins the report to the constant, not the constant to 「`classify → locate → challenge`」. Everything else I probed can fail: disabling the duplicate comparison fails 3 of 4 `-k duplicate` tests, forcing `single_session` to `False` fails `-k broadcast`, the hyphen default fails 3 of 4 `test_live.py`. `classify`'s `unavailable` is asserted against its own reason string, and the pipeline's skip counts are exact.
- **Are the M2 items the report says are still missing in fact still missing?** Yes. `grep -c pipeline dojo/discuss.py` → **0** (no session-end trigger; `discuss` still writes only `session_end`), `pass_classify` returns `unavailable`, no distillation list exists anywhere (`grep -rln 提炼清单 docs/` → only `plan.md` and the old verdict's prose), so ① is unjudgeable rather than judged, and ⑤ is inherited — `def challenge` at `dojo/storage.py:345` and `test_challenge_revision…` at `tests/test_storage.py:53` both already exist at `2a17e17`.

## Blocking

1. **Defect 1** — if `broadcast` is handed to M3 as the cross-session outlet, a card carrying one session's word enters it whenever the write did not record that session or any group. The row that says ② now has an implementation is then load-bearing on a property that does not hold; `m2e` cannot be accepted on top of it.
2. **Defect 3** — the report's evidence block is not reproducible as printed; a reviewer downstream who runs the printed command gets 14, not 8, and cannot tell which other numbers in the block were computed the same way.
3. Not blocking, but decided by someone other than the advance: `docs/plan.md` reads the gate as covering delivery and not code, and reversed `b5be333`, `9cea94c`, `1452d53` if root meant otherwise. The gate itself still has no on-disk record and the M1/M1.5 checkpoint is unanswered; nothing here says M2 passed.

## Evidence — commands run at `d915520`, and results

```
git status --porcelain -uall                        -> 0 lines; branch master; HEAD d915520
git log --oneline 2a17e17..d915520                  -> 8 commits (mail-migrate, model, isolation, duplicate, pipe-core, 63c46a7, report, plan table)
git log --oneline origin/master..HEAD               -> 16   (origin/master = 621bf26, local ref, not fetched)
git diff --stat 2a17e17..HEAD                       -> 19 files, +957 −173; dojo/pipeline.py new (174), dojo/storage.py +250
python3 -m unittest discover -s tests               -> Ran 121 tests in 45.165s, OK   (report said 121 at 63c46a7; no test changed since)
python3 -m unittest discover -s tests -p 'test_live.py'        -> Ran 4, OK
python3 -m unittest discover -s tests -p 'test_pipeline.py'    -> Ran 8, OK
python3 -m unittest discover -s tests -p 'test_storage.py' -k duplicate -> Ran 4, OK
python3 -m unittest discover -s tests -p 'test_storage.py' -k broadcast -> Ran 3, OK
python3 -m compileall -q dojo tests                 -> rc=0
CLI: confirm / broadcast / export --mode c / add twice / pipeline twice / events / list
   broadcast -> results [], suppressed [single-session provenance…]
   export --mode c -> error: single-session provenance cannot be exported as cross-session material (exit 2)
   add twice   -> error: duplicate content already stored as d-2c7462e66697 (status discussable, v2); no new version was created (exit 2)
   pipeline    -> events_written 2, then 0 (locate/challenge skipped at version 2)
   events      -> ['add','confirm_discussable','pipeline_pass','pipeline_pass']
ls inbox docs/evidence/reviews  -> report + README; verdict archived, no mail/
grep -c "Ran 98" docs/plan.md   -> 0 (exit 1)
curl -s -m 3 -o /dev/null -w '%{http_code}' http://127.0.0.1:4000/v1/models -> 401
Gate probes (isolated copies in /tmp, repo untouched):
   hyphen DEFAULT_MODEL in live.py       -> test_live 4 tests, FAILED (3)
   duplicate comparison disabled         -> -k duplicate, FAILED (3 of 4)
   single_session forced False           -> -k broadcast, FAILED (1 of 3)
   hyphen model id added to search.py    -> test_live OK  (scan does not cover it)
Not run, therefore not passed: the m2.0/m2.1 live scripts and any `discuss` session — endpoint answers 401 and they spend model/search budget; neither exercises an M2 acceptance item.
```

Effort: about 23 minutes of wall clock, no model call, no money, no push, no file written in `/home/z/vibe/dojo/`.