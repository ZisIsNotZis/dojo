日期：2026-11-27。基线 `f947fde`（已发布）。本片提交见本节末尾。离线；0 次模型调用。

# 改主意的理由，后来做事的人拿得到

## 这一片回答的问题

监督者：「一条经验经过讨论、质疑和再使用后，真的改变了后来做的一件事。保留当初的证据和后来为什么改主意。」

上一片收在回执说真发生的那件事。这一片接着走完一段完整的故事，**在真实的入口上走**：

1. 一场会话得出了一句做法，他认可（`add` + `record_acceptance` + `confirm`）；
2. 后来他提到一次反例，质疑它（`challenge`）；
3. 他由此把这句话改窄，并说明**为什么改**（`revise`，带 `reason`）；
4. 新一场接受了改写后的那句（再 `record_acceptance` + `confirm`）；
5. 再后来的一次行动（检索、跨会话、导出）读这张卡。

## 改之前测到的（`probe_lesson_loop.py`、`probe_lesson_export.py`）

| 步骤 | `retrieve` | `broadcast` | `export --mode c` |
|---|---|---|---|
| ① 刚被接受 | 有（v2，`discussable`） | 有 | 成功 |
| ② 被质疑后 | **什么都没有** | **什么都没有** | 拒绝：不是 discussable |
| ③ 改了主意后 | **什么都没有** | **什么都没有** | 拒绝 |
| ④ 新一场再接受 | 有（v5） | 有 | 成功 |

第 ④ 步的 1494→1677 字符导出里，逐条查过：

| 东西 | 在导出里 |
|---|---|
| 改后的那句 | 在 |
| 他提的反例（`contradictions`） | 在 |
| **他为什么改主意（`revise` 的 `reason`）** | **不在** |
| **被改掉的那句（`from_statement`）** | **不在** |

理由确实在盘上：`events` 里 `{"event":"revise","details":{"from_statement":…,"reason":…,"to_statement":…,"version":4}}`。`search`、`broadcast`、`show` 三处的行里都没有它。

**所以缺陷的准确说法**：不是「信息丢了」，是**盘上有、读者出口没有**。后来做事的人拿到一句已经被反例改窄的话，旁边摆着那个反例，却不知道它被改过、更不知道为什么。`show --history` 有这一行，而读导出的人不会去开它。

## 改了什么

`Store.revision_basis(candidate_id, state=None)`（`dojo/storage.py`），四条出口都接上：

- 只认 `revise` 行，不认 `revise.repeat`（同一请求再来一次不陈述新理由）；
- 只认 `to_statement` 等于**当前这句**的那一行——再改一次，附着的就换成新的理由，旧理由不删，仍在账本与 `show --history` 里；
- 比较措辞用 `normalize_wording`，不用 `wording_digest`：后者把 `kind` 与四个内容字段也算进去，而「范围改宽、话没变」是同一句话的同一个理由，不是另一个理由；
- 没有这样的行就返回 `{}`，调用点只在真值时加键——没改过主意的卡**字节不变**，这是 `time_basis`/`source_basis` 已有的规矩；
- 出口：`retrieve`/`broadcast` 的行里加 `revision_basis`，`show` 的返回里加（放在 `candidate` **旁边**，因为 `candidate` 是存储状态、有测试逐字比对），`export_prompt` 里印两行散文。

导出里那两行是给人读的，不是给机读的：

```
revision_left_wording: <被改掉的那句> | 这句是他后来改掉的，不是现在的说法。
revision_reason: <他的原话> | 他改主意的理由，原话；不是对现在这句的赞同，也不证明它成立。
```

## 验收

`python3 docs/evidence/2026-11-27-lesson-loop/verify.py` → **退 0，15 项**（L1、L1b、L2a–c、L3a–c、L4、L4b、L5a–c、L6a–b）。

其中两项是**防过度收紧**的对照，改前改后都应当过：L2c（`show` 的 `candidate` 本体没被改写）、L3c（现在这句仍在导出里）。在基线上它们确实仍过，其余 13 项里 11 项红，另两项（L4、L4b、L5、L6）在基线上因方法不存在而中途退出——见下。

### 红臂

**臂 1（缺方法）**：把 `tests/test_lesson_loop.py` 原样放到 `f947fde` 上：

```
baseline  FAIL   Ran 9 tests in 0.332s; FAILED (failures=1, errors=7)
fixed     PASS   Ran 9 tests in 0.348s; OK
```

7 条是 `AttributeError`、1 条是断言失败。**这一臂只能说「方法不在」，不证明「读者拿不到」**，所以做了臂 2。

**臂 2（方法在、只拆接线）**：保留 `revision_basis`，逐个删掉一条出口的调用点，每次只删一处：

| 删掉的调用点 | 结果 | 红的是哪条 |
|---|---|---|
| `retrieve` | 红 | `test_search_hands_the_later_reader_why_he_changed_his_mind` |
| `broadcast` | 红 | `test_broadcast_and_show_carry_the_same_reason` |
| `show` | 红 | `test_broadcast_and_show_carry_the_same_reason` |
| `export` | 红 | `test_the_frozen_prompt_says_the_sentence_was_replaced_and_why` |

四条出口各自被咬住，没有一条是「删了也绿」。

**臂 3（验证器在基线上）**：把 `verify.py` 放到 `f947fde` 上跑，L1、L1b、L2a、L2b、L3a、L3b 逐条 `FAIL`，随后在 L4 因 `AttributeError` 退出非 0。

## 真实入口

**照着走的完整命令在 [`WALK.md`](WALK.md)**，可以整段粘贴，不需要网络或模型。
这里不再放省略了参数的片段：上一版的示例用了 `'…'` 占位，照着做会卡在 `add` 的必填项上。

`WALK.md` 里有一处**停下来看**的地方：质疑之后、再认可之前，`search` 是空的。
那是既有设计，也是这条链的真实界限，见下面「这一片没做的」第 1 条。

跑出来的 `revision_basis`：

```json
{"left_wording": "持续检查交给系统自己跑，人只在想推翻时回来。",
 "reason": "原来那句没写清楚什么时候叫醒他，所以第三次更糟。",
 "revised_at": "2026-11-27T15:02:16+00:00"}
```

## 数字

- `python3 -B -m unittest tests.test_lesson_loop` → `Ran 9 tests ... OK`
- `python3 -B -m unittest discover -s tests` → `Ran 1159 tests / OK`，**连续三次**（分别 191s / 202s / 187s）
- 基线 `f947fde`：`Ran 1150 / OK`
- 中途见过一次别的失败，已查清与本片无关，见下
- `verify.py` → 退 0，15 项
- 0 次计量调用

## 这一片没做的，和仍然不知道的

1. **被质疑的卡仍然不被交给后来的读者，而且需要他回来。** ②③ 两步里三条出口都是空的。
   这是既有决定（不是 `discussable`、也没有当前措辞的接受记录，就不交出），本片不改；
   `test_a_challenged_card_is_still_not_handed_to_a_later_reader` 把它钉住，
   免得有人把上面那些测试读成「质疑现在进检索了」。

   **这条界限的准确说法：** `challenge` 把卡打到 `challenged`，`revise` 把它打回 `draft`
   并撤销接受标记，所以只是「改了主意」并不会让新句子重新交给别人。
   **他必须回来再认可一次（`confirm`），那句才重新可检索——也只有那时候，
   读者才拿到改主意的理由。** 实测读数是 `1 → 0 → 0 → 1` 条命中（`WALK.md` 第 1/2/3/5 步）。

   对「抽身之后网络自己跑」的产品方向，这是本节最重要的一条：本片**没有**让网络
   自己跨过这一步。他若不再回来，理由就只留在账本里（`show --history` 看得到），
   别人拿不到。要把这段也自动起来，得另外决定「质疑之后谁能重新放行一张卡」，
   那是一个产品决定，不是这一片该默默做的。
2. **理由只取最近一次改动。** 改了三次，读者只看到第三次的理由；前两次在 `show --history` 里。理由是「给读卡的人一句为什么」，不是完整审计——后者已经存在，只是要人去读。
3. **没有把理由做成结论或推断。** 原话原样带出，不判断它对不对、成不成立。
4. **一个既有的偶发失败，与本片无关，但没修。** 中途跑全套时 `test_storage` 里的
   `test_a_read_is_a_recorded_action_with_the_acceptance_state_at_that_moment` 失败过一次。
   查清过程：那条断言把两个**不同精度的时钟**当字符串比——`reads.at` 是微秒，
   `events.created_at`（`accepted_at` 的来源）只有秒。两次写入跨过一个整秒时断言必为假。

   用受控时钟在**未改动的 `f947fde` 上**复现了（`probe_clock_fixed.py`）：
   `read at 12:00:00.999400` 对 `accepted_at 12:00:01`，断言为假，同一张表的
   `accepted_at_at_read` 列仍然是对的。所以它是既有缺陷，任何树上都可能偶然红。
   实测频率很低：基线单跑 200/200 通过，本片树 199/200。

   **本片不改它**（不在验收范围内，且改测试断言会动到别人片的断言），
   但也不掩盖：上面三次全套是连续跑的，都绿。要修的话建议单独一片，
   把那条断言换成比 `accepted_at_at_read`，那才是这张表存在的理由。

5. **`normalize_wording` 相等就算同一句。** 把措辞改回旧的那句（哪怕理由不同），旧 `revise` 行不会被重新认领——只有 `to_statement` 与当前句相等的那一行算，而更早的行确实相等，所以**取最后一条匹配的**。这条按「最近一次说明」读，是对的；但它意味着「改回原句」不会带出更早的理由，除非那次改动自己也写了理由。
