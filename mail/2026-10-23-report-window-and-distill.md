kind:    report
from:    dojo (manager)
to:      root
spend:   machine_time, idle class; no device; no money; no metered call
id:      mail/2026-10-23-answer-unconfirmed-and-model

# `m2f` 现在是一个有期的窗，窗口里补上了 M2 的读者面；要花模型钱的那一局没跑

你昨天问的那一件事不再是问题：`m2f` 由 person 的 trace 或 2026-10-25T12:28Z 先到者开门，到点就用 `github_copilot/gpt-6-luna` 跑一局，我不再为「跑不跑」回来问一次。窗口内能推进的不等它，这一轮推进的那一件是可验证的整件：`python3 -m dojo distill --session <s>`。

## 现在为真的事

- **等待窗写死了两端**：`docs/plan.md` 的推进状态与 `## M2 的工作包与依赖` 都写「不早于 person 的 trace 落进 `docs/evidence/m1.5-checkpoint/`，不晚于 2026-10-25T12:28Z（`date -u` 读到 `2026-10-23T12:28:35Z`，48 小时后）」，两端先到先算，到点后跑一局，模型按计划页写的那个。
- **窗口内不空转**：同一页写明「不需要那一局的东西照常推进」，并把派发说明里原来那句「`m2f` 没跑完时其他 M2 包不开」改掉——`m2f` 是进门条件，指的是 M2 不能盖在空气上，不是别的包不许动。窗口里落地的东西一律只算能力就位，M2 仍不按通过记。
- **person 先跑反而更好，且进记录的方式写清了**：`docs/evidence/m1.5-checkpoint/README.md` 现在写明他那条路径原样写进记录、trace 原样复制进来、他的话一字不改地贴、判断写在他原话旁边并注明谁写的。「未确认」被写成**一个真实结果，不是失败**：他说「还是得管机制」和说「很好」一样要落盘，不为了让它好看而换问法再问一遍。
- **M2 的读者面补上了一块**（新的 `distill-list`）：`python3 -m dojo distill --session <s>` 把一场会话的每张卡摆成一条条给人看的行——`[新]`／`[变体]`／`[重复]`、对着哪张卡、理由，后面跟挑战提议；写 0 事件、0 处理标记，所以在 `pipeline` 之前或之后问都一样。`kind` 一列写「未判定」（`classify` 还没落地），不把写入时给的值冒充判定结果。这一条正是 `m2c` 一直缺的「尚未接成一条给用户看的提炼清单」。
- **`m2f` 那条命令的形状用回环桩验过，产物已删**：`DOJO_SESSIONS=docs/evidence/m1.5-checkpoint` 时 trace 落在证据目录，末行 `session_end` 带 `model`（`github_copilot/gpt-6-luna`），权限 0600；桩返回的不是合法主持格式，所以那一局只证明命令与落盘，不构成任何证据，跑完我把那个文件删了，证据目录里仍然只有 `README.md`。零计量调用。

## 命令与输出（写之前跑过，数字从输出复制）

```
$ python3 -m unittest discover -s tests
Ran 130 tests in 38.583s
OK

$ python3 -m unittest discover -s tests -p 'test_pipeline.py' -k distill
Ran 4 tests in 0.847s
OK

$ python3 -m compileall -q dojo tests   -> rc=0
$ git status --porcelain -uall | wc -l  -> 0
$ git log --oneline origin/master..HEAD | wc -l -> 26      (未推送)
```

`distill` 的只读性是量的、不是承诺的：`python3 -m dojo events | wc -l` 在 `distill` 前后都是 29，`pipeline_marks` 表 0 行（`sqlite3 … "select count(*) from pipeline_marks"` → `0`）。

## 还在等的东西，各自在等什么

| 等的东西 | 等什么 |
|---|---|
| `m2f checkpoint-rerun` | person 的 trace，或 2026-10-25T12:28Z。它要花 AIU，你的答复已经授权，届时我不再问 |
| `m2b classify` | 一次模型判定。它是 `distill` 里那列「未判定」变实的唯一办法；代码可以在窗口里写，判定不能凭空造 |
| `m2e integrate` 的整场部分 | 清单已能读，整场跑一遍与那份测试报告还没有；跑整场要模型调用 |
| 实验 harness（障碍清单 → 批量验证） | 一份能落地的设计。它今天只有计划页里一行「仅完成设计讨论」，没有可写的契约，也没有可跑的验收；这一轮的 20 分钟给不了它一个可验的结果，所以我没有用半成品占位。下一轮先写设计再动代码 |
| 广播口径（是否收紧成「两个独立组或缺席」） | person 的取舍：收紧会拒掉四张 seed，影响 M3 的演示材料。本轮没动 |

## 需要你定的事

没有。上一轮那个「谁先跑、花谁的钱」由你答完了。只有一条我按你的字面理解落的、写成假设而不是问题：**person 的 trace 先到时 `m2f` 仍然跑**（你的话是「Then it runs as the entry condition」），他那一局与 `m2f` 那一局都记在同一个目录里，他那一局排在前。若你的意思是「他的 trace 到了就不必再让模型跑」，改一行字即可，代价是零。

## 残余风险

- **到期没有人叫醒**：2026-10-25T12:28Z 只写在计划页里，本机没有定时器；下一个醒来的会话必须从 `docs/plan.md` 读到它。日程不在仓库里的代价是这一条。
- **`distill` 的清单还没有人读过**：它的形状是照 `m2c`/`m2e` 的需求写的，真正确认它「值得入库还是噪音」的是 person 的眼睛，而那一读还没发生。
- **测试数 130 只说明没回归**，不说明 M2 任何一条验收成立。

## effort

机器时间：读 root 的答复与现有计划页、两次提交（`5d37632`、`fb6710f`）、一次全量测试 38.6s、一次 `test_pipeline -k distill`、一次 `compileall`、一次回环桩运行（零额度，产物已删）。没有调用真实模型端点，没有推送，没有动 person 的时间。
