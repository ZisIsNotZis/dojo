# Independent acceptance review: K1 / K2

- **Bound commit:** `90d6db53b9fb2ebc95b1208cd5a72e06eb1a7878` (`90d6db5 Say on the public face that a session can enter the dao loop`)
- **Review date:** 2026-10-27
- **Reviewer model:** OpenAI reviewer model; exact runtime model ID was not exposed in this session.
- **Scope:** `docs/proposal-knowledge-network.md` §七 A1–A7; `docs/plan.md` K1-1..K1-43 and 第八次推进 K2-1..K2-6; session exporter and session branch/tests. Review was read-only except this verdict file. Tests and scripted traces used no network/model.

## Top-line verdict

- **K1: fail (acceptance incomplete).** A1 and A3 pass on the committed artifacts; A6 passes the current suite. A2, A4, and A5 require the human verdict named by the acceptance and are not confirmed at this commit. A7's historical call/person-time totals are asserted in prose but not independently auditable from a cost ledger.
- **K2: fail.** K2-4 and K2-6 pass; a real offline `run_discuss` trace exports. K2-1's recorded `/tmp` CLI sequence is missing the vocabulary setup and fails as written; K2-2/K2-3 tests do not establish the asserted exactness; K2-5 has a reproducible authorship overclaim path by editing the supposedly authoritative `session.json`.

## K1 acceptance A1–A7

| Line | Verdict | Finding |
|---|---|---|
| A1 — Six parts | **pass** | The first three entries have all six nonempty components. Independent reading: each has an actionable boundary/stop or reverse condition (e.g. dojo-d-001 withholds when evidence must come from the world; dojo-d-002 switches when the shape cannot be known or the user requests detail; dojo-d-003 stops asking about negligible/system-paid cost). This judges usability, not truth. |
| A2 — Organization | **unjudgeable — person verdict required** | `b-001`/`con-001` are printed as pending, but there is no one-sentence confirmation or rejection from the person in the committed record. The plan correctly says a test cannot replace this. |
| A3 — Adversarial receipts | **pass** | Current `receipts.json` contains structure/falsifiable/field records; the first two have cases/actions and field is either an observation with kind/source or `not_run`. The `dao_life --check` output below reproduces the current 13-entry state. This is structural evidence, not proof the simulations are world-valid. |
| A4 — Independence/exposure | **unjudgeable — human verdict required** | No exposure scenario is recorded: `docs/dao/person-dojo/exposures.json` has zero rows and the second library is explicitly synthetic. The required A→B exposure-and-agreement scenario is not evidenced. |
| A5 — Withdrawal | **unjudgeable — human verdict required** | The artifact says no further contact and remains runnable, but the acceptance requires a human withdrawal/experience judgment; no such verdict is recorded. |
| A6 — No regression | **pass (test portion)** | Full suite passes at this commit (203 tests); compileall is clean. This establishes automated regression checks, not a human comparison of every M1/M2 experience. |
| A7 — Budget | **unjudgeable** | Plan claims 0 calls and ≤40 minutes, but there is no independent usage/person-time ledger for the historical milestone. This review itself made no model/network calls. |

## K1-1..K1-43 advance records

The 43 K1 workpackage claims are historical records, not all independently replayed as separate commands in this review. Their durable current outputs are consistent on the main counts: the person library is 13 entries, 9 refusals, 1 candidate, 1 contradiction, 26 record checks, 0 promotions; all are marked 合写, with 3 weak field observations and 10 `未跑`. The current `--check` passes. The plan itself still records A2 as pending and an independent review as outstanding; therefore those historical “过” entries do not turn the overall K1 milestone into accepted. A source-attribution defect is listed below.

## K2-1..K2-6

| Line | Verdict | Finding |
|---|---|---|
| K2-1 — Export and run loop | **fail as documented; pass with explicit vocabulary setup** | A real trace exports. However the recorded `/tmp/lib` invocation of `dao_life.py <dir> --check` does not find `vocabulary.json` beside `/tmp/lib` and exits 1 unless the vocabulary is copied or `--vocabulary docs/dao/vocabulary.json` is supplied. The test only calls `build_library_from_note()` directly after preparing extraction; it does not exercise that CLI sequence. |
| K2-2 — Verbatim/timestamps | **fail (acceptance test not demonstrated)** | The test module does not assert each emitted `[MM:SS]` line against the original trace or assert timestamp monotonicity. Exporter lines 67–87 put elicitation `answer` values into the same `inputs` list that is then searched, so the “answer exists in inputs” part can be self-confirming when the elicitation event has no `user` property (the real event schema in `dojo/discuss.py` records `answer`, not `user`). |
| K2-3 — Only answered tension | **fail (test/check is tautological)** | Splitting the tension response to make the sides is a reasonable construction, but the purported side validation at `dao_session.py:88–90` asks whether each side is in the very answer it was just split from; it can never fail. Tests only check a delimiter-free refusal and do not assert both emitted sides are literal substrings of the original user round. The error says “first side or second side” rather than identifying which side is missing. |
| K2-4 — Refuse unanswered | **pass** | Tests generate a real scripted discuss trace with unanswered cost, and reject empty trace, absent `session_end`, and absent elicitation; they assert no output directory for the relevant failures. |
| K2-5 — Authorship ceiling | **fail** | `dao_life.py` trusts editable `session.json` booleans and checks only that four elicited parts are promoted. It does not bind that file to the trace or check its `answer` text; `move` and `provenance` remain whatever `extraction.json` says. Reproduction below changed a session answer to text absent from the trace, marked all six extraction parts as his, and `dao_life --check` exited 0. |
| K2-6 — No regression | **pass for automated checks** | 203 tests pass; compileall is clean; current `daos.json` SHA-256 exactly matches the value recorded in the plan; both requested library checks pass. The stated zero-cost history is not independently auditable, as noted for A7. |

The one-conclusion-per-session cap is explicitly stated in the plan at lines 683–684 and in `docs/dao/README.md` under the session-export section. It is not silently assumed.

## Exact command evidence (copied from this review)

### Required full suite

Command:

```text
python3 -m unittest discover -s tests
```

Actual output included these warnings and final result:

```text
.................../home/z/vibe/dojo/dojo/discuss.py:818: ResourceWarning: unclosed database in <sqlite3.Connection object at 0x77cf695fe980>
  allowed_extra_keys=frozenset({"user_stance", "person_updates"}),
ResourceWarning: Enable tracemalloc to get the object allocation traceback
... (same ResourceWarning repeated for six SQLite connections) ...
----------------------------------------------------------------------
Ran 203 tests in 16.691s

OK
```

The suite also emits expected captured CLI/test fixture output after the summary; exit status was 0.

### Required compile check

Command:

```text
python3 -m compileall -q dojo tests
```

Actual output: **no output**; exit status 0.

### Required person library check

Command:

```text
python3 scripts/dao_life.py docs/dao/person-dojo --check
```

Actual output:

```text
dao-life：13 条道（docs/dao/person-dojo，落盘库）
  dojo-d-001  v1  合写 · 检（3/3：自洽 过 / 可反驳 过 / 落地 过）
  dojo-d-002  v1  合写 · 检（3/3：自洽 过 / 可反驳 过 / 落地 过）
  dojo-d-003  v1  合写 · 检（3/3：自洽 过 / 可反驳 过 / 落地 过）
  dojo-d-004  v1  合写 · 未检（2/3：自洽 过 / 可反驳 过 / 落地 未跑）
  dojo-d-005  v1  合写 · 未检（2/3：自洽 过 / 可反驳 过 / 落地 未跑）
  dojo-d-006  v1  合写 · 未检（2/3：自洽 过 / 可反驳 过 / 落地 未跑）
  dojo-d-007  v1  合写 · 未检（2/3：自洽 过 / 可反驳 过 / 落地 未跑）
  dojo-d-008  v1  合写 · 未检（2/3：自洽 过 / 可反驳 过 / 落地 未跑）
  dojo-d-009  v1  合写 · 未检（2/3：自洽 过 / 可反驳 过 / 落地 未跑）
  dojo-d-010  v1  合写 · 未检（2/3：自洽 过 / 可反驳 过 / 落地 未跑）
  dojo-d-011  v1  合写 · 未检（2/3：自洽 过 / 可反驳 过 / 落地 未跑）
  dojo-d-012  v1  合写 · 未检（2/3：自洽 过 / 可反驳 过 / 落地 未跑）
  dojo-d-013  v2  合写 · 未检（2/3：自洽 过 / 可反驳 过 / 落地 未跑）
  入道 13 条；拒收 9 条（情境 3 / 张力 4 / 动作 2 / 代价 2 / 失效 1 / 归属 1 / 重复 1）；候选 1 条；库内同张力 0 对同一条、1 对相反
  作者：合写 13；记录检查 26 条（确认 9 / 部分 9 / 收窄 2 / 推翻 0 / 未表态 6）；晋升 0 条
独立来源 1 组（不同的人 1 个；曝光账本 0 行）。曝光未知按「不独立」算：这里是一个人的道理，不是共识。
--check：不写盘
```

### Required probe demo check

Command:

```text
python3 scripts/dao_life.py docs/dao/probe-demo --check
```

Actual output:

```text
dao-life：1 条道（docs/dao/probe-demo，由 docs/dao/probe-demo/note.md 推出）
  dao-p-demo-T1  v1  模拟 · 未检（2/3：自洽 过 / 可反驳 过 / 落地 未跑）
  入道 1 条；拒收 0 条（情境 0 / 张力 0 / 动作 0 / 代价 0 / 失效 0 / 归属 0 / 重复 0）；候选 0 条；库内同张力 0 对同一条、0 对相反
  作者：合写 1；记录检查 0 条（确认 0 / 部分 0 / 收窄 0 / 推翻 0 / 未表态 0）；晋升 0 条
来源是模拟材料（1 个来源 id，曝光账本 0 行）：它不是一个人的道理，也不是共识，只能用来测这张库装不装得下第二个来源。
--check：不写盘
```

### Real offline `run_discuss` export

The fixture was created by `tests/test_dao_session.py`'s `run_discuss` + `ScriptedHost`; no model was called. Exact exporter invocation and output:

```text
$ python3 scripts/dao_session.py --trace /tmp/dao-review-5ujhr0sh/tmpwtwfojhe/run-0/sessions/discuss-a36490dafa2c436baea6d531faa52f39.jsonl --out /tmp/dao-review-5ujhr0sh/tmpwtwfojhe/out --person p-review --sample acquaintances
写入 /tmp/dao-review-5ujhr0sh/tmpwtwfojhe/out/note.md 与 session.json
exit 0
```

A configured CLI check, with the vocabulary explicitly supplied, passed:

```text
$ python3 scripts/dao_life.py /tmp/dao-review-5ujhr0sh/tmpwtwfojhe/out --vocabulary /tmp/dao-review-5ujhr0sh/tmpwtwfojhe/vocabulary.json --check
dao-life：1 条道（/tmp/dao-review-5ujhr0sh/tmpwtwfojhe/out，由 /tmp/dao-review-5ujhr0sh/tmpwtwfojhe/out/note.md 推出）
  dao-p-review-T1  v1  模拟 · 未检（2/3：自洽 过 / 可反驳 过 / 落地 未跑）
  入道 1 条；拒收 0 条（情境 0 / 张力 0 / 动作 0 / 代价 0 / 失效 0 / 归属 0 / 重复 0）；候选 0 条；库内同张力 0 对同一条、0 对相反
  作者：他的 1；记录检查 0 条（确认 0 / 部分 0 / 收窄 0 / 推翻 0 / 未表态 0）；晋升 0 条
来源是模拟材料（1 个来源 id，曝光账本 0 行）：它不是一个人的道理，也不是共识，只能用来测这张库装不装得下第二个来源。
--check：不写盘
exit 0
```

The corresponding first attempt omitted the vocabulary option/copy and failed before checking the extraction:

```text
$ python3 scripts/dao_life.py /tmp/dao-review-usxx1bk8/tmpzfolfwf9/out --check
拒收（/tmp/dao-review-usxx1bk8/tmpzfolfwf9）：词表读不出来：[Errno 2] No such file or directory: '/tmp/dao-review-usxx1bk8/vocabulary.json'
词表默认取数据目录上一层的 vocabulary.json，可用 --vocabulary 指定。没有写任何文件。
exit 1
```

### K2-5 hostile edit reproduction

Starting from the exported session, I changed only its `price.answer` to `伪造的逐字回答，实际 trace 中从未出现`, marked all six extraction parts `他的原话`, and ran the check. It still exited 0 and accepted `作者：他的 1`:

```text
$ python3 scripts/dao_life.py /tmp/dao-review-5ujhr0sh/tmpwtwfojhe/out --vocabulary /tmp/dao-review-5ujhr0sh/tmpwtwfojhe/vocabulary.json --check
dao-life：1 条道（/tmp/dao-review-5ujhr0sh/tmpwtwfojhe/out，由 /tmp/dao-review-5ujhr0sh/tmpwtwfojhe/out/note.md 推出）
  dao-p-review-T1  v1  模拟 · 未检（2/3：自洽 过 / 可反驳 过 / 落地 未跑）
  入道 1 条；拒收 0 条（情境 0 / 张力 0 / 动作 0 / 代价 0 / 失效 0 / 归属 0 / 重复 0）；候选 0 条；库内同张力 0 对同一条、0 对相反
  作者：他的 1；记录检查 0 条（确认 0 / 部分 0 / 收窄 0 / 推翻 0 / 未表态 0）；晋升 0 条
来源是模拟材料（1 个来源 id，曝光账本 0 行）：它不是一个人的道理，也不是共识，只能用来测这张库装不装得下第二个来源。
--check：不写盘
exit 0
fabricated session price answer: 伪造的逐字回答，实际 trace 中从未出现
```

### Other release checks

- `python3 -m dojo demo --auto` — exited 0 and printed the scripted three-act demo, explicitly labelled simulated.
- `sh scripts/storage-smoke.sh` — exited 0; printed `Finished. All database and export files were in /tmp/dojo-demo.lwB5YX and are removed on exit.`
- Local Markdown links in `README.md`, `README.zh-CN.md`, and `docs/**/*.md`: `broken relative markdown links: 0`.
- `sha256sum docs/dao/person-dojo/daos.json` — `2ec777230989d81bd616c042e861f4bf14cdfd7f92c09517f03c1e7319e01acc`, matching plan line 671.
- `git status --short` and tracked-junk scan produced no output. `__pycache__` directories are ignored, not committed.

## Defects and one-line fixes

| # | Severity | Reproduction / location | Defect | One-line fix suggestion |
|---|---|---|---|---|
| 1 | Acceptance blocker | `docs/plan.md:221`; `docs/dao/person-dojo/道图.md` “连接与边界” | A2 remains `待确认`; no person sentence confirms/refutes the connection/boundary. | Obtain and record the person's one-sentence verdict, or keep K1 explicitly unaccepted. |
| 2 | Acceptance blocker | `docs/dao/person-dojo/exposures.json` (empty); proposal §七 A4 | No A→B exposure-and-agreement run or human verdict; the synthetic library is not a substitute. | Run and record the specified exposure scenario and its human verdict; otherwise leave A4 unaccepted. |
| 3 | Acceptance blocker | `docs/plan.md:219–227`; proposal §七 A5 | The plan asserts withdrawal, but the required human withdrawal verdict is absent. | Record the human verdict on the post-session output without contacting the person during the withdrawn interval. |
| 4 | High | `scripts/dao_life.py:1102–1107,1150–1155`; reproduction above | `session.json` is a mutable, unbound file; its `promoted` flags alone authorize authorship, and its answer is never compared with the trace. `move`/`provenance` can still be claimed as his directly in extraction. | Bind `session.json` to a trace digest and validate promoted parts/answers against the original trace; gate every part, including move/provenance, on supported source evidence. |
| 5 | High | `scripts/dao_session.py:65–87`; `tests/test_dao_session.py:68–78` | K2-2's promised line-by-line assertion is absent. Elicitation answers are included in the list searched for those same answers; the test only checks direction and resulting tension. | Add a test comparing every emitted line to an independently selected trace user-input field and assert the emitted times are monotonic. |
| 6 | Medium | `scripts/dao_session.py:88–90`; `tests/test_dao_session.py:122–129` | Side membership test is tautological (`side` was just split from `answer`); negative test only checks generic refusal, not each side. | Remove the tautology and assert the emitted left/right sides against the original tension answer, with a specific missing-side error test. |
| 7 | Medium | `docs/plan.md:646,661–667`; reproduced `/tmp` CLI attempt above | K2-1's printed `/tmp/lib`→`dao_life --check` sequence omits the vocabulary setup; tests call the library function directly, while the actual CLI refuses without vocabulary in the output parent. | Include `--vocabulary docs/dao/vocabulary.json` (or copy the vocabulary into the documented output layout) and test the CLI command itself. |
| 8 | Medium | `docs/dao/README.md:49,106`; current `docs/dao/vocabulary.json` | README says eight total vocabulary terms and four tension terms; current file has 13 tensions and 14 moves. | Derive the counts from the current file or remove the stale counts. |
| 9 | Medium | `docs/dao/person-dojo/episodes.json:55–71`; `docs/dao/person-dojo/道图.md:45–46`; `道图.md:48` | `“还没。”` comes from a root relay explicitly lacking the session trace, yet the chart lists it under “原话” and labels provenance `他的原话`; this overstates verbatim support. | Render it as “root 转述（未核）” and mark the provenance source as relayed, not the person's verbatim words. |
| 10 | Low | `README.md:67`; `README.zh-CN.md:67` | `DOJO_LLM_API_KEY=...` is a literal placeholder in the public setup example. | Replace it with a non-placeholder read-from-environment command or explicitly instruct the reader to set their own key outside the copied block. |

## Residual risks

- Tests pass with six `ResourceWarning: unclosed database` warnings pointing at `dojo/discuss.py:818`; these did not fail the suite but should be investigated.
- A5/A7 cannot be promoted to pass by this code review; they need the required human/cost evidence.
- `session.json` and JSON trace files are local editable files, not authenticated audit records; claims based on them must not be presented as tamper-proof.
