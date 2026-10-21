kind:    report
from:    orient-dojo (package launched by root)
to:      root
spend:   idle-compute
id:      none — first contract, answered in the run final message

First orientation report, filed here by root. Body is the run report verbatim.

I oriented in the checkout read-only and ran no model/search calls. Report below is the deliverable.

---

# 报告：`dojo` 首次定位

**报告目标的节点**：root（`/home/z/vibe`）——本报告会改变它的 roadmap（决定下一个里程碑）。
**证据**：见每节的行内指针与文末命令清单。
**需要的决定**：见第三节 Q1–Q3（三条我都无权自答）。

## (a) 这个项目是什么

`/home/z/vibe/dojo` 是一个**单人、无 UI、纯 Python 标准库 + SQLite 的 CLI 概念验证**，产品名"道场"。它让用户用自然语言对话，由一个主持人 agent 在对话中镜映、锐化、溯源、设界，双方自然收敛时**静默**把一条带边界的结论写入本地账本（candidate → card，含 `scope`/`premises`/`alternatives`/`unknowns`），并用可查看的词汇重合检索把旧结论带回新会话。它记录讨论状态与出处，不认证真假，不自动合并相似主张，不做 UI/服务器/登录（`README.md:3`, `docs/product.md:7`, `docs/design.md:8-9`）。

已落地的部分（我核对到的是代码与证据，不是文档承诺）：

| 层 | 现状 | 指针 |
|---|---|---|
| 账本 | `add/confirm/revoke/challenge/revise/merge/unmerge/split/abstain/export`，版本只增不改，`challenged` 不删旧版 | `dojo/storage.py:16`, `dojo/cli.py` |
| 对话 | `discuss`：行编辑、推断优先、外部搜索带回正文、人物档案、失败诊断与重试、`--resume` 续跑、逐轮 JSONL 轨迹、`## 计算交接单` 落盘 | `dojo/discuss.py:739`, `docs/plan.md:94-100` |
| 演示 | 三幕陌生人中文预设 Demo（真实本地 `Store.retrieve`）、离线回放 `compare` | `dojo/demo.py`, `dojo/compare.py` |
| 证据 | 9 个归档证据目录，含失败记录 | `docs/evidence/{m1-discuss,m1.5-trace,m1.6-resilience,m1.7-caps,m1.8-input-caps,m1.9-dialogue,m2.0-stance-search,m2.1-person-profile,m5-sycophancy}` |

仓库状态：`master` @ `621bf26`，`origin/master` 同点（**已 push**），工作树干净、无 staged、无未跟踪。
验证：`python3 -m unittest discover -s tests` → `Ran 98 tests in 29.522s / OK`，跑前跑后 `git status --porcelain -uall` 均为空。

⚠️ 两处记录已过期，都是事实性偏差，不是我读错：`.scratch/active-work.md:4` 写 `HEAD 628e9ff`、"未 push"，`:5` 写"93 项测试"，实际是 `621bf26`（已 push）与 98 项（`docs/plan.md:93` 的 98 才与运行结果一致）。

## (b) 提议的下一个里程碑：M2 会话末提炼管线

**提议**：按 `docs/plan.md` 的 M2 定义推进——会话结束时自动跑 `classify → locate → challenge`，把结论落为 draft 卡并留事件，幂等、单会话来源不进广播、挑战走 `challenged` 而不删旧版。

**支持它的证据指针**：

1. `docs/plan.md:49-58` —— M2 的目标状态、交付物、五条验收（抽检一致性 / 单会话不进广播 / 不重复建版 / 幂等 / `challenged` 不删旧），依赖 M1。
2. `docs/plan.md:100` —— 计划层自己把"会话末提炼管线（M2）"列为**已知缺口**；`.scratch/active-work.md:8` 同列为"已确认但仍未实现"。
3. `docs/design.md:21,61-77` —— 已写好管线契约与初始三个 pass（`dojo/pipe/passes/`、`classify`/`locate`/`challenge`），即设计已定、实现为空。
4. **代码缺席的可复核证据**：`ls dojo` 只有 `cli/compare/demo/discuss/live/search/storage`，没有 `pipe/`；`grep -rn "classify\|extract\|提炼\|pipeline\|manifest\|broadcast\|广播" --include=*.py dojo/ tests/` → **2 处命中，且都是 `_extract_compute_handoff`**（`dojo/discuss.py:695,1229`），`classify`/`locate`/`pipeline`/`manifest` 均为 0 命中。
5. 当前行为到此为止：结论由 `_save_conclusion` 直接 `store.add/revise`（`dojo/discuss.py:305-342`），会话结束只写轨迹 `session_end` 事件（`dojo/discuss.py:878`），没有提炼 pass、没有 draft 摘要句、没有幂等键。

为什么不是别的：M1 与 M1.5 有证据目录（`m1-*`、`m1.5-trace`）；M3 依赖 M2（`docs/plan.md:63`），M4 依赖 M2（`:71`），M5 依赖 M1+M2（`:79`）——M2 是唯一解锁其余三项的那一环。

**同一里程碑内建议先做的工作包（不是里程碑）**：`docs/plan.md:85-90` 登记的"文档一致性待修复"，我核实其两条冲突仍在：`README.md:5,7` 仍把 `docs/current-demo-direction.md` 标作"当前产品方向"，而 `docs/README.md` 与 `docs/product.md:3` 已明确 `product.md` 是唯一入口、旧文件收窄为已实现 Demo 说明；`README.md:27` 仍写"**不会录制原始聊天**"，与 M1.5 默认逐轮轨迹（`docs/plan.md:44-46`）冲突。这是纯文档修复、不改设计、不改范围。

## (c) 它答不出的问题

**Q1 · 里程碑编号冲突：下一步是"plan.md 的 M2"，还是"M2.x 系列"？**
- 试过什么：读 `docs/plan.md`（M2 只有一个定义＝会话末提炼）、`docs/README.md`（声明 plan.md 拥有计划层事实）、`.scratch/active-work.md:7-8`；`grep -rn "M2\.0\|M2\.1\|m2\.0\|m2\.1" docs/*.md .scratch/*.md` → **1 处命中，仅是 active-work.md:7 的证据目录名**。即 `m2.0-stance-search`（立场与搜索）和 `m2.1-person-profile`（人物档案）挂在"M2"名下，但内容既不是 plan.md 的 M2 定义，也没在任何文档里被写成 M2 的拆分子项。
- 为什么这是问题：我无法判断 M2 的剩余范围是"提炼管线"（plan.md 读法）还是"某次未记录的重新拆分后剩下的别的项"。这会直接改变下一个里程碑的边界。
- 什么会重开它：一段记录这次重新拆分的文档，或用户一句话说明 M2.0/M2.1 与 plan.md M2 的关系。我不会自行合并两种编号。

**Q2 · 我有没有权把 M2 推成"下一个"？**
- 试过什么：`docs/plan.md:3` 明确"本清单须经用户确认后，才可进入自动执行"；M1.5 的用户检查点是"先自己玩一场，然后把轨迹路径告诉我"（`docs/plan.md:46`）。我在 `docs/evidence/m1.9-dialogue`、`m2.0`、`m2.1` 的 provenance 里只找到模型运行记录，没有用户检查点结论；`grep` 未在 `.scratch/` 找到 M1.5 检查点的验收条目。
- 结论：M1/M1.5 是否已被用户亲手确认，在本仓库内**无法建立**（不是"没有"，是"没有可复核的落盘记录"）。
- 什么会重开它：用户一句确认，或一条把检查点结论落盘的记录。

**Q3 · `docs/evidence/m5-sycophancy` 算不算 M5 的证据？**
- 事实：该目录已被 git 跟踪，`judgement.md` 结论是"反奉承在当前提示下成立"，四场场景 A–D，代码修定 `b78c41a`（`git cat-file -t b78c41a` → commit）。但 `docs/plan.md:94-100` 的当前基线与 `.scratch/active-work.md:8` 都**没提它**，`docs/product.md:51` 仍写"未做的负控制"。
- 试过什么：读 `m5-sycophancy/judgement.md` 与 `provenance.md`；它测的是"是否让步"，**没有覆盖** `docs/plan.md:77` 验收④那条"用户用真实文本反对、模型可能误报 `user_stance=accept`"，且运行于搜索/档案/推理等级变更之前（20 秒超时时代）。
- 什么会重开它：把它登记为 M5 的部分证据并标为过期，或按验收④重跑一场针对 `accept` 误报的负控制。

**附带风险（不需要决定，只登记）**：本报告只做了阅读与标准库测试；未调用模型端点，未打开任何真实会话或 `person.md`，所以"M2 缺席"的结论只覆盖代码与文档事实，不覆盖运行时行为。

---

**建议下一步**：root 把 Q1/Q2 一并交给用户，用一句话拿到"下一个里程碑＝M2 会话末提炼管线"的授权；授权后先派一个纯文档工作包修 `docs/plan.md:85-90` 那两条冲突并刷新 `.scratch/active-work.md` 的 HEAD/测试数，再派 M2 的实现。Q3 可由 root 单独决定是登记还是重跑。