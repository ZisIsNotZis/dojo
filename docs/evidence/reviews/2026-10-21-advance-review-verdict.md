> 归档评审记录（2026-10-21 收到，读完即删出 `inbox/`，原文保真）。它绑定的是 `939bf90`，只在那个修订上可复核；此后代码一动，里面的命令与命中数即过期，须重跑而不是引用。它评审的对象是 `621bf26..939bf90` 这五个提交。
>
> 以下为原文。

## Verdict: **fail** — M2 does not pass at `939bf90`; 1 of its 5 acceptance items holds (and only as a pre-existing store capability), 4 do not

Read at `939bf905e6ed6feb7acecbc2c94af04178c01117`, worktree clean (`git status --porcelain -uall` empty), branch `master`, ahead 7, nothing staged.

### Base I used

`621bf26` (`origin/master` at review time) — the base the project's own records name: `docs/plan.md` says "提交范围看 `git log --oneline origin/master..HEAD`", and `mail/2026-10-21-gate-and-review.md` counts the range as "two of yours that this advance inherits" plus "the five this advance made".

```
$ git log --oneline origin/master..HEAD
939bf90 mail: report the advance stopped at M2's gate and ask for one verdict
13c3eee Bind the retired entrance's staleness to dates instead of a guessed span
68de2cd Name what M2 already has, so its five acceptance items stop reading as five builds
b5dec04 Retire .scratch/ and move its work records under docs/evidence
ef52239 Land root's answer, retire the scratch entrance, tell the truth in README
7753d73 mail: root answers the first report, and the next milestone      <- root, inherited
436aad0 mail: first orientation report filed by root                    <- root, inherited
```

The advance's own five: `ef52239`, `b5dec04`, `68de2cd`, `13c3eee`, `939bf90`. Bound: `origin/master` is a local remote-tracking ref; I did not fetch, so the base is the one the project's records name, not one confirmed against the remote.

### What the advance changed toward M2, and what it only named

Changed: nothing executable.

```
$ git diff --stat 621bf26..HEAD -- dojo/ tests/ scripts/
(empty)
$ git diff --stat 621bf26..HEAD
 README.md, docs/README.md, docs/current-demo-direction.md, docs/plan.md,
 docs/evidence/work-records/* (5 files), mail/README.md,
 mail/2026-10-21-{orientation,answers,gate-and-review}.md   — 199 insertions, 28 deletions
```

Zero code, zero tests, zero new acceptance commands. Every M2 behaviour at `939bf90` is the behaviour at `621bf26`.

Only named, and the naming is accurate where I could check it:
- ⑤ as already present — true; `dojo/storage.py:345` is `def challenge`, `tests/test_storage.py:53` is the named test, both citations resolve exactly.
- ④ new scaffolding, ①③ new judgements — true, evidenced below.
- `store.add(..., kind=...)` already takes `kind` — true (`dojo/storage.py:197-213`, validated against `KINDS`).
- `store.retrieve` is visible lexical overlap — true; the code's own `method` string says "transparent lexical overlap… not semantic search or truth ranking" (`dojo/storage.py:599-648`).
- `discuss` dedupes only within one session — true; `_save_conclusion` revises `saved_candidate_id` for the live session (`dojo/discuss.py:305-330`), nothing crosses sessions.
- `discuss` writes only a `session_end` trace event at the end — true (`dojo/discuss.py:879-884`).
- The retired entrance's staleness (`13c3eee`) — true; `git show ef52239^:.scratch/active-work.md` records HEAD `628e9ff`, "未 push", 93 tests, while `628e9ff` is dated 2026-10-18 and `621bf26` is 2026-10-21 and is `origin/master`.

### M2 acceptance, item by item

| # | item | holds? | evidence |
|---|---|---|---|
| ① | 抽检提炼结果与对话结论一致 | **no** | no distillation output exists to sample |
| ② | 单一会话来源不进入广播 | **no** | no broadcast code; the nearest surfaces admit single-session cards |
| ③ | 重复内容不产生新版本 | **no** | duplicate `add` yields a second v1 card; no duplicate detection |
| ④ | 同会话重跑管线幂等无副作用 | **no** | no pipeline, no idempotency key |
| ⑤ | 挑战产生 `challenged` 且不删除旧版本 | **yes, as a store capability only** | test passes; probe confirms history kept |

**① fail.** `grep -rEn "classify" dojo/ tests/` → 0 hits; `grep -rn "提炼" tests/` → 0 hits. The only end-of-session hook is the `session_end` trace event, and its tests (`tests/test_discuss.py:169`, `:619`) assert that event, not a distillation list. No 提炼结果清单 exists at any revision under `docs/evidence/`. Inference from `dojo/discuss.py:305-340`: the conclusion card is written mid-session at the agreement round by `_save_conclusion`, so there is no second artefact whose agreement with the dialogue could be sampled.

**② fail, and it fails in the direction that is dangerous to pass.** `grep -rn "broadcast" dojo/ tests/` → 0; `grep -rn "广播" dojo/ tests/` → 0. The invariant written at `docs/design.md:91` ("单一会话来源不进入广播") is enforced nowhere: no consumer filters on `sessions` or `independence_group`. Reproduction, at `939bf90`:

```
$ python3 - <<'PY'   # store in /tmp only
c = s.add(stmt, "application", scope=["交接"], session="sess-A",
          sources=[{... "independence_group":"sess-A", "scope_note":"单一会话来源；不构成独立佐证。"}])
s.confirm(c["id"], "worth discussing")
print([r["id"] for r in s.retrieve("交接 版本 范围")["results"]])
print(c["id"] in open(<mode-c export>).read())
PY
retrieve_returns_single_session_card: ['d-f4f45b5a0de9']
export_includes_single_session_card: True
```

The source is marked single-session, and the retrieval and export surfaces that M3's broadcast would draw from include it anyway; the only barrier is `discussable`, which one `confirm` crosses. Passing ② because "no broadcast exists" is passing on absence.

**③ fail.** `dojo/storage.py:197-240` checks only for ID collision; there is no content comparison. Reproduction: two `add` calls with identical statement, scope and session → `d-43d3720c9f3d`, `d-334d149bc2bf`, `same_id: False`, `candidate_count: 2`, both version 1. `grep -rEn "变体" dojo/` → 0, so no 新/变体/重复 three-way judgement exists. Extra obstacle a locate pass would hit: `retrieve` skips every non-`discussable` card (`dojo/storage.py:609-611`), so it cannot even see the drafts it would have to classify. A literal defender could say "no *version* was produced, only a second candidate" — that reading is vacuous; the behaviour is exactly the duplicate the item exists to prevent, and the m2c row that owns it ("重复不改版本") is unimplemented.

**④ fail.** There is nothing to rerun: `grep -rni idempot dojo/` → 0, and no "processed to version N" marker exists on any candidate. The one test with `idempotent` in its name, `tests/test_storage.py:25 test_seed_load_is_four_simulated_and_idempotent`, is seed loading; counting it as ④ would be a false pass.

**⑤ yes, but not as a milestone behaviour.** Standalone run of the named test:

```
$ python3 -m unittest discover -s tests -p 'test_storage.py' -k challenge -v
test_challenge_revision_and_alias_link_versions_preserve_sources (test_storage.StoreTests...) ... ok
Ran 1 test in 0.643s — OK
```

Independent probe at this revision: after `confirm` + `challenge`, `status: challenged`, `version: 3`, `history_versions: [1, 2, 3]`, contradiction recorded. So the operation holds. It does not hold as M2 behaviour: `grep -n "challenge" dojo/discuss.py` → 0 hits, so nothing in a session ever calls it; and the capability is present unchanged at base `621bf26`, so counting it as advance progress double-counts inherited work.

Also unmet but in 目标状态 rather than 验收: the user should see one sentence "我记下了这条，边界是……"; today `discuss` prints nothing mid-session and ends with "本场结论卡片 ID：…" (`dojo/discuss.py:891`).

### Commands run at `939bf90`, and what they established

```
git rev-parse HEAD                                   -> 939bf905e6ed... (clean worktree, nothing staged)
git log --oneline origin/master..HEAD                -> 7 commits, 5 of them the advance's
git diff --stat 621bf26..HEAD -- dojo/ tests/ scripts/ -> empty
python3 -m unittest discover -s tests                -> Ran 98 tests ... OK  (run twice: 43.274s, 38.070s)
python3 -m compileall -q dojo tests                  -> rc=0
python3 -m unittest discover -s tests -p 'test_storage.py' -k challenge -v -> 1 test, ok
python3 -m dojo --db /tmp/m2rv/x.sqlite3 discuss --no-trace  (endpoint unset)
                                                     -> "无法启动讨论：未配置 DOJO_LLM_BASE_URL，未发送网络请求。"; no file created
curl -m 3 http://127.0.0.1:4000/v1/models            -> HTTP 401
env | grep -c DOJO_                                   -> 0
```

Not run, therefore not passed: the m2.0 and m2.1 live commands their provenance names (`DOJO_LLM_BASE_URL=http://127.0.0.1:4000/v1 python3 docs/evidence/m2.0-stance-search/run_live_dialogues.py`, and the m2.1 equivalent) — the endpoint answers 401 and no model key is in this environment; they spend model and search budget; and neither exercises an M2 acceptance item, since they are stance/search and person-profile evidence, not distillation. I also did not run any npx/tooling beyond the above.

### Blocking — what makes a pass unsafe even though the checks pass

1. **No M2 acceptance has a command.** `docs/plan.md`'s M2 section is prose; the contracts with acceptance commands are deliberately deferred to dispatch. So `98 tests OK` says nothing about M2 — every one of the five verdicts above rests on code reading plus two store probes. A pass at this revision cannot be re-derived by anyone else from a command, and dies at the next commit.
2. **The gate has no record.** M2 is gated on the person's M1/M1.5 confirmation, and `docs/plan.md` states no verifiable record of it exists. Any claim that M2 passed or progressed crosses the project's own precondition; the mail's own position ("stopped at M2's gate") is the only safe one.
3. **⑤ is inherited, not earned.** It holds at `621bf26` and the advance changed no code; reading it as advance progress double-counts.
4. **The ② vacuity trap.** Zero broadcast code makes "single-session sources don't enter broadcast" true by absence, while the probes show the retrieve/export surfaces accept single-session cards. A shallow pass on ② hands M3 a false base.
5. **No M2 property is runtime-verified.** Nothing about M2 can be sampled from a live session at this revision (there is no pipeline, and no model key here), so ①'s "抽检" cannot be performed at all — it is not a check I skipped, it is a check with no subject.

### Document finding (non-blocking for M2)

`docs/plan.md` 当前基线 promises "不在这里存数字（会过期）" and then stores one in the same line: "最近一次：2026-10-21，`master` @ 7753d73，`Ran 98 tests … OK`". The number is still true at HEAD (I measured 98 OK), but the revision pointer is 4 commits behind HEAD and the sentence contradicts its own promise. That is the only claim in the advance's diff I could not read as true-as-written; everything M2-related in it verified.

Residual risks I carry: I did not fetch the remote, so the base is the records' base; my probes construct store state directly, so they show capabilities rather than an end-to-end milestone path; the m2.0/m2.1 evidence was not re-executed and carries no M2 weight here; and the README privacy/trace-mode claims remain code-checked, not run-checked — consistent with the advance's own stated residual risk.