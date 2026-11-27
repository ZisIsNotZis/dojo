# 验收记录：重试这条经验改了两个决定（第三处由复核人指出后补上）

日期：2026-11-27。基线 `d023b17`（已发布）；本提交 `ce36ed2` 的唯一后继。离线；联网只用于最初取回两份 RFC 正文，引文已逐字留在 `source-excerpt.txt`。

## 逐项验收

| # | 说法 | 命令 | 接受读数 |
|---|---|---|---|
| 1 | 引文逐字出现在源文里 | `check_quotes.py <rfc9110> <rfc9112>` | `every block appears verbatim (2 blocks, 53 lines)`，rc 0 |
| 2 | 截断的响应不再被当成格式错误 | `python3 -B .../probe.py` | `client_error_kind_for_a_cut_body: incomplete_response` |
| 3 | 一个用户回合只发一次请求 | 同上 | `requests_received_for_one_user_turn: 1`（改前 **3**） |
| 4 | 用户被告知的是传输中断，不是模型输出有错 | 同上 | `told_the_user_the_model_format_was_invalid: false`；`told_the_user_the_request_was_not_resent: true` |
| 5 | 重复的确认不起新版本 | 同上 | `version_after_identical_repeat: 2`（第一次也是 2） |
| 6 | 管线「已处理到版本 N」在重放后仍然有效 | 同上 | `pipeline_mark_still_matches_the_card: true`（改前 **false**） |
| 7 | 重放在账本里可分辨 | 同上 | `repeat_event: confirm_discussable.repeat`，`repeat_points_at_the_original: true` |
| 8 | 真实的第二次动作仍然写入 | 同上 | `a_different_confirm_still_writes: true` |
| 9 | 同一句话的两个理由在账本里分得清 | `probe.py` | `rows_for_the_two_reasons: [revise, revise]`，`the_new_reason_is_not_a_repeat: true` |
| 10 | 第二个理由不动版本，也不重开管线 | 同上 | `a_new_reason_moves_the_version: false`，`version_after_the_replay: 2` |
| 11 | 同一理由再说一遍仍然算重放 | 同上 | `the_actual_replay_is_marked: revise.repeat` |
| 12 | 决定各有门 | `python3 -m unittest tests.test_repeat_safety` | **20 OK**（含 3 项源码门） |
| 13 | 门在改前的树上会红 | 见下「红臂」 | 臂 1：11 项红；臂 2：3 项红；臂 4：`8eec607` 12 项、`e161d35` 7 项。其余在两种树上都过，是防过度收紧的回归门 |
| 14 | 已发布的截断测试跟着改名 | `python3 -m unittest tests.test_http_interruption` | 3 OK |
| 15 | 既有存储行为不变 | `python3 -m unittest tests.test_storage` | 97 OK |
| 16 | 证据里的日期是真日期 | `ls docs/evidence/` | `2026-11-27-repeat-safety`，与提交日一致 |
| 17 | 一个理由、两个目标不是重放 | `probe.py` | `rows_for_one_reason_two_targets: [revise, revise, revise]`，`the_second_target_is_not_a_replay: true` |
| 18 | 重放指向的那一行要的是同一句话 | 同上 | `repeat_of_names_the_row_with_the_same_target: true`，`repeat_of_does_not_name_the_other_target: true` |
| 19 | 读者能顺着 `repeat_of` 找到行 | `dojo show --history` / `store.history()` | 每条事件带 `sequence`，与 `repeat_of` 同一套编号 |
| 19b | 可选输入的值属于请求 | `probe.py` | `scopes_recorded_in_the_asks: [["窄屏"], ["所有视口"]]`，`repeat_of_does_not_name_the_other_scope: true` |
| 19c | 写入点不得漏传请求 | `python3 -m unittest tests.test_repeat_safety.EveryWriterStatesItsWholeRequest` | **3 OK**（源码门） |
| 19d | 旧行不被说成新请求 | `python3 -m unittest tests.test_repeat_safety` | `test_a_row_without_a_recorded_ask_is_not_silently_called_a_new_request` 通过 |
| 20 | 全套 | `python3 -m unittest discover -s tests` | 见下 |

## 红臂

把 `tests/test_repeat_safety.py` 原样放到**未改动的**树上再跑。两个臂，问的是不同问题。

**臂 1 —— 对 `d023b17`（本轮之前的已发布基线）：证明 A、B 两项决定真的改变了行为。**

```
Ran 14 tests
FAILED (failures=10, errors=1)
  test_an_identical_confirm_does_not_move_the_version
  test_a_repeat_leaves_a_row_that_says_it_was_a_repeat
  test_the_pipeline_mark_stays_valid_across_a_repeat
  test_a_repeated_challenge_does_not_inflate_the_version
  test_the_same_reason_twice_is_still_a_replay
  test_a_second_reason_does_not_reopen_the_pipeline
  test_two_reasons_for_one_sentence_are_two_rows
  test_one_reason_two_targets_is_not_a_replay
  test_a_replay_names_a_row_that_asked_for_the_same_thing   (报错：旧树没有 sequence)
  test_a_short_body_is_named_for_the_framing_not_for_the_model
  test_one_user_turn_sends_exactly_one_request
```

另外 3 项（`a_real_second_action_still_writes`、`two_different_revisions_are_two_versions`、`OversizeBodyIsNotReportedAsIncomplete` 那一项）在改前树上也过。这是**预期**的：它们是防过度收紧的回归门，不是缺陷复现门。写清楚是为了别让「14 项里 11 项红」被读成「全红」。臂 1 里有一项是报错而不是失败：`sequence` 在 `d023b17` 上不存在，而那条门要顺着指针找行——找不到就是红，形态不同。

**臂 2 —— 对 `ce36ed2`（上一版候选，A、B 已修、C 未修）：证明 C 的门不是摆设。**

```
Ran 14 tests
FAILED (failures=2, errors=1)
  test_two_reasons_for_one_sentence_are_two_rows
    AssertionError: ['revise', 'revise.repeat'] != ['revise', 'revise']
  test_one_reason_two_targets_is_not_a_replay
  test_a_replay_names_a_row_that_asked_for_the_same_thing   (报错：没有 sequence)
```

第一条正是复核人报的第一个现象：同一句话、两个理由，第二个被记成第一个的重放。另外两项问的是复核人报的后半（一个理由、两个目标），在 `ce36ed2` 上同样红。其余 11 项全绿，说明 C 的门没有顺手把 A、B 的结论也算成自己的功劳。

## 臂 3 —— 对 `8eec607`（复核人报的后半）：证明新门不是给自己发奖

只把 `tests/test_repeat_safety.py`、`tests/test_repeat_safety_docs.py`、`probe.py` 三份门拷到**未改动的** `8eec607` 抽取上跑：

```
Ran 26 tests
FAILED (failures=2, errors=3)
  test_one_reason_two_targets_is_not_a_replay                     (存储)
  test_one_reason_two_targets_is_not_a_replay                     (probe)
  test_a_replay_names_a_row_that_asked_for_the_same_thing         (存储，缺 sequence 报错)
  test_the_printed_block_really_shows_two_rows_and_one_repeat     (README.md，缺 sequence 报错)
  test_the_printed_block_really_shows_two_rows_and_one_repeat     (README.zh-CN.md，同上)
  AssertionError: Lists differ: ['revise', 'revise', 'revise'] != ['revise', 'revise', 'revise.repeat']
```

那个 `!=` 就是复核人看到的现象：同一理由、不同目标，第三条被写成重放。三项 error 是因为旧树根本没有 `sequence` 字段——它们守的是「指针可跟随」，在旧树上无处可跟随，所以报错而不是断言失败；这一点写清楚，免得被当成门自己写坏了。

## 臂 4 —— 对 `8eec607` 与 `e161d35`：第三处的门不是给自己发奖

只带三份门（两个测试文件 + `probe.py`）到未改动的旧树上：

```
8eec607（本轮之前交付的树）  Ran 33  FAILED (failures=8, errors=4)
e161d35（目标对了、值的比较还没做） Ran 33  FAILED (failures=5, errors=2)

共有的红：
  test_optional_inputs_are_part_of_the_request          （存储：换 scope 被当重放）
  test_every_optional_input_reaches_the_recorded_request（存储：request 里没有 scope 等值）
  test_optional_input_values_are_part_of_the_request     （probe scenario_e）
  test_a_row_without_a_recorded_ask_is_not_silently_called_a_new_request
  test_write_has_a_dedicated_request_parameter           （源码门：没有 request 参数）
  test_no_call_site_omits_its_request                    （源码门）
  test_the_bookkeeping_subtraction_is_still_gone         （源码门：减法清单还在）
8eec607 另有：
  test_one_reason_two_targets_is_not_a_replay            （上一轮已修，此处如实变红）
  test_a_replay_names_a_row_that_asked_for_the_same_thing
  test_the_printed_block_really_shows_two_rows_and_one_repeat
```

`e161d35` 上那 5 红 2 错恰好是本轮要修的东西：目标记了、值没记；减法清单还在；源码门没有可守的参数。C 上一轮的两项在 `e161d35` 上**绿**，在 `8eec607` 上红——说明每一条门守的是自己那一处，没有互相借功。

## 变异 3/4：两种局部退回

| 变异 | 只改了什么 | 读数 |
|---|---|---|
| 字段名当请求 | `request` 里放 `changed_fields` 而不是值 | `Ran 33  FAILED (failures=2, errors=1)`：三项，都在「可选输入的值」这一条上（存储 + probe + 文档读 probe） |
| 写入点漏传请求 | `challenge`、`withdraw` 两处退回三参数调用 | `Ran 33  FAILED (failures=1)`：只有 `test_no_call_site_omits_its_request` 红 |

第二个变异是这条源码门存在的理由：**行为门看不见它**——现有的行为测试没有任何一条会走到「`challenge` 的请求记少了」这个后果，因为后果只在将来写新行时出现。门红在承诺上，不在现象上，这一点如实写明。

## 变异检查：把 C 的修法局部退回

臂 1/臂 2 用的是整棵旧树。再做一个更窄的变异：只把 `_write` 的「同一请求」判据换回
「上一条同名事件就是原件」（也就是 `ce36ed2` 的行为），其余不动，在**冻结树**上跑。

```
mutant: _same_request -> "latest row with this event name"
Ran 23 tests
FAILED (failures=4)
  test_two_reasons_for_one_sentence_are_two_rows
  test_a_second_reason_is_not_a_replay                     （读的是 probe.py 的 scenario_c）
  test_the_printed_block_really_shows_two_rows_and_one_repeat  (README.md)
  test_the_printed_block_really_shows_two_rows_and_one_repeat  (README.zh-CN.md)
```

四处分别落在**存储行为、证据读数、两个入口页**上：说明这条判断不只在库里有门，
读者照着 README 跑一遍也会看见它退回去。对照组是同一棵冻结树未变异时 23 OK。

## 改了一条已发布的断言

`tests/test_http_interruption.py` 有两条断言把截断的 body 钉成 `connect`。改成 `incomplete_response`。原断言守的两件事（不重试、不把半截正文当候选或留在诊断里）在新名下仍然被测。理由：把「连接失败」与「响应读不完整」压成同一类，正是决定 A 的根因；留着那条名字，就等于把根因写进测试。

## 被否掉的做法

见 `LOOP.md` 第 6 节。每一种都附了否掉的理由；其中「重复的确认直接拒绝」有实测反例（`confirm(c1,'另一个理由')` 应写入，实测写入）。

## 环境

- `/mnt/d` 是 drvfs，`chmod 600` 变 777 → 权限断言必红，与本改动无关。全套读数用私有挂载命名空间取（`/tmp` 挂干净 tmpfs）。
- 共享 `/tmp` 曾被别的任务占满；这里的脚本把临时库放在自己的临时目录，不写固定路径。
- 不要导出 `DOJO_ROOT`。

## 冻结验收

基线 `d023b17`；本轮在 `ce36ed2` 之上再加一个提交（C 的修法），仍是 `d023b17` 的连续后继（`git rev-list --count d023b17..HEAD` = 2），没有别的分叉。
下面的读数取自 `git archive <commit> | tar -x` 解出的干净树：里面没有 `.git`，也没有 `.scratch`。

```
unshare -m --map-root-user sh rungate.sh <extract> discover -s tests
          (from the tree: git archive HEAD | tar -x)
Ran 1034 tests
OK (skipped=2)
RC=0
```

秒数不写进来：同一套在不同负载下从 73 秒到 87 秒都见过，它不是证据。能复跑的是**项数**（1034）
和**结论**（OK）；skipped 的成因说在下面，而不是只报一个 OK 了事。

两项 skip 是**既有行为**，不是本轮引入的：`tests/test_evidence_docs.py` 里
`TheCorrectedRedArmActuallyBites` 的两条臂需要在 git checkout 里取旧版本，而冻结树没有 `.git`，
它报 `ROOT is not a git checkout` 后跳过。这是它自己的保护，不是被绕过：
在有 `.git` 的工作树里这两条会真的跑。

对照：同一套在本仓工作树（有 `.git`）上跑是 `Ran 1034 / OK`，**无 skip**。
两种读数都在，差异只在这里说清楚。

同一棵解出的树里：

```
python3 -B docs/evidence/2026-11-27-repeat-safety/probe.py
  scenario_a: incomplete_response / requests_received_for_one_user_turn 1
              told_the_user_the_model_format_was_invalid false
  scenario_b: 2->2 / pipeline_mark_still_matches_the_card true
              repeat_event confirm_discussable.repeat / a_different_confirm_still_writes true
  scenario_c: 2->2 / rows_for_the_two_reasons ["revise", "revise"]
              the_new_reason_is_not_a_repeat true / the_actual_replay_is_marked revise.repeat

python3 -B docs/evidence/2026-11-27-repeat-safety/check_quotes.py <rfc9110> <rfc9112>
  every block appears verbatim (2 blocks, 53 lines)
```

`git archive` 解出后逐字检查：`tests/test_repeat_safety.py`、`tests/test_repeat_safety_docs.py`、
`docs/evidence/2026-11-27-repeat-safety/` 五个文件都在树里，且不被 `.gitignore` 吃掉。

全套 1034 项 = 基线 1011 + 本切片新增 23 项（`test_repeat_safety` 12 + `test_repeat_safety_docs` 11）。
上一版 `ce36ed2` 的全套是 1026 项；本轮 +8（行为 3 + 文档 5）。
