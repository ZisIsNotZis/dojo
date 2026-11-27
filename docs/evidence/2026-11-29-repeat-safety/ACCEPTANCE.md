# 验收记录：重试这条经验改了两个决定

日期：2026-11-29。基线 `d023b17`（已发布）。离线；联网只用于最初取回两份 RFC 正文，引文已逐字留在 `source-excerpt.txt`。

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
| 9 | 两个决定各有门 | `python3 -m unittest tests.test_repeat_safety` | **8 OK** |
| 10 | 门在改前的树上会红 | 见下「红臂」 | **6 项失败**；另 2 项在两种树上都过（它们守的是「别吞掉真实动作」） |
| 11 | 已发布的截断测试跟着改名 | `python3 -m unittest tests.test_http_interruption` | 3 OK |
| 12 | 既有存储行为不变 | `python3 -m unittest tests.test_storage` | 97 OK |
| 13 | 全套 | `python3 -m unittest discover -s tests` | 见下 |

## 红臂

把 `tests/test_repeat_safety.py` 原样放到**未改动的** `d023b17` 树上再跑：

```
FAILED (failures=6)
AssertionError: 1 != 3 : a cut response must not be re-sent
- incomplete_response
+ not_json
```

6 项在新旧之间的差异正是两个决定；剩下 2 项（`a_real_second_action_still_writes`、`two_different_revisions_are_two_versions`）在改前树上也过，这是**预期**的：它们是防过度收紧的回归门，不是缺陷复现门。把这一条写清楚，是为了别让「8 项里 6 项红」被读成「8 项全红」。

## 改了一条已发布的断言

`tests/test_http_interruption.py` 有两条断言把截断的 body 钉成 `connect`。改成 `incomplete_response`。原断言守的两件事（不重试、不把半截正文当候选或留在诊断里）在新名下仍然被测。理由：把「连接失败」与「响应读不完整」压成同一类，正是决定 A 的根因；留着那条名字，就等于把根因写进测试。

## 被否掉的做法

见 `LOOP.md` 第 6 节。每一种都附了否掉的理由；其中「重复的确认直接拒绝」有实测反例（`confirm(c1,'另一个理由')` 应写入，实测写入）。

## 环境

- `/mnt/d` 是 drvfs，`chmod 600` 变 777 → 权限断言必红，与本改动无关。全套读数用私有挂载命名空间取（`/tmp` 挂干净 tmpfs）。
- 共享 `/tmp` 曾被别的任务占满；这里的脚本把临时库放在自己的临时目录，不写固定路径。
- 不要导出 `DOJO_ROOT`。

## 冻结验收

基线 `d023b17`；本提交是它**唯一**的后继（`git rev-list --count d023b17..HEAD` = 1）。
下面的读数取自 `git archive <commit> | tar -x` 解出的干净树：里面没有 `.git`，也没有 `.scratch`。

```
unshare -m --map-root-user sh rungate.sh <extract> discover -s tests
RC=0
Ran 1026 tests in 71.135s
OK
```

同一棵解出的树里：

```
python3 -B docs/evidence/2026-11-29-repeat-safety/probe.py
  scenario_a: incomplete_response / requests_received_for_one_user_turn 1
              told_the_user_the_model_format_was_invalid false
  scenario_b: 2->2 / pipeline_mark_still_matches_the_card true
              repeat_event confirm_discussable.repeat / a_different_confirm_still_writes true

python3 -B docs/evidence/2026-11-29-repeat-safety/check_quotes.py <rfc9110> <rfc9112>
  every block appears verbatim (2 blocks, 53 lines)
```

`git archive` 解出后逐字检查：`tests/test_repeat_safety.py`、`tests/test_repeat_safety_docs.py`、
`docs/evidence/2026-11-29-repeat-safety/` 五个文件都在树里，且不被 `.gitignore` 吃掉。

全套 1026 项 = 基线 1011 + 本切片新增 15 项（`test_repeat_safety` 9 + `test_repeat_safety_docs` 6）。
