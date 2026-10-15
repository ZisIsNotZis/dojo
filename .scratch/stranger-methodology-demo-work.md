# 陌生人方法论 Demo：恢复工作记录

## 当前状态

- 状态：新版三位陌生人 Demo 已实现并通过标准库测试；待用户在聊天中验收体验。
- 产品事实与完整验收：[docs/current-demo-direction.md](../docs/current-demo-direction.md)。不要仅根据旧故事或本记录推导产品承诺。
- 仓库：`/home/z/vibe/dojo`；当前 `master` 无提交，`.gitignore`、`.pi/`、`.scratch/`、`AGENTS.md`、`README.md`、`docs/`、`dojo/`、`idea.md`、`scripts/`、`tests/` 均未跟踪。保留已有工作，不 reset、清理或为隔离擅自提交。
- 用户在远端，不能运行命令或看文件；交付须在聊天直接展示完整新版体验。
- 当前没有后台执行任务。协助会话未派发工作、未触碰仓库。

## 授权与模式

- 用户已要求按陌生人方法论方向重新做 Demo；此前授权父级管理执行子代理和审查。
- 用户最新请求是立即亲自更新 SSOT，然后重开会话；本次按当前 Discussion / Eager Mode 直接写恢复记录，不借此启动额外实现。
- 新会话应刷新适用 `AGENTS.md`，不能沿用旧的无条件 Main 禁止实作规则。当前根规则：用户讲话进入 Eager Mode；明确要求继续自动推进才进入 Automatic Execution Mode；即时 Eager 请求由 Main 直接完成，不强制 Ticket／子代理／Review。
- 使用执行层子代理时仍固定 `github-copilot/gpt-6-luna`，不可静默替换。自动执行中 Main 管理、委派和独立验收；不可自行启动孙代理。
- 新会话先确认用户当前希望 Eager 立即实现还是继续自动推进，不把先前自动授权当作忽略用户介入的依据。已经确认的产品方向无需重问。

## 下一步

1. 用户在聊天中查看三幕体验与验收项，确认是否满足或需调整。
2. 如需真实模型演练，再单独显式配置 `chat`／`compare`；不得把旧归档当新故事证据。
3. 保留旧技术测试和真实 B/C 归档作为历史证据，不冒充新场景的验证结果。

## 已有证据（历史，需按新改动重验）

- 上个实现与父级报告：27 tests 通过；中文离线 demo／compare 已走查；两项 P2 已关闭；独立窄复核 6 tests 通过。
- 现有 HTTP adapter 仅本地 mock 测试；真实 Pi Luna B/C 回答是独立上下文的单样本，不是 HTTP adapter 端到端证据或严格效果 benchmark。
- `idea.md` 保留原稿；不得为 Demo 改写它。

## 过程日志

- 2026-10-13T18:26:22+08:00 — Main 检查真实当前时钟、Git 状态与根／项目 AGENTS。发现根策略已更新，明确 Eager 由 Main 直接执行；此前依据旧注入策略拒绝写 SSOT 属恢复判断错误。
- 同一恢复操作 — Main 创建产品方向 SSOT、更新 philosophy 场景与现有 live-mode 描述、README 指向当前方向、创建本记录和 active-work 入口；仅文档，未实现新版、未调用 API、未安装、未提交。
- 2026-10-13T18:29:13+08:00 — Main 自检通过：5 个本次文档、21 个本地链接、未跟踪文件 no-index whitespace 与 `git diff --check`；`idea.md` SHA-256 为 `595b9eb6e64b885ad46db9cff1b1527391540eb42bb2cda580392d70e0ac15b2`，与既有记录一致。未重新运行产品测试。
- 子代理基础设施记录 — 当前会话 tool registry 无 native subagent；helpagent 确认自身有工具但拒绝跨项目派发，未执行任何 Dojo 写入。它不再阻止当前 Eager 文档请求；是否影响后续自动执行须在新会话重新检查。
- 2026-10-13T18:40:31+08:00 — 用户选择 Eager；Main 直接实现新版（未派子代理、未提交）。新增三幕陌生人故事（甲整洁→乙开发方法→丙难度挑战）到 `dojo/demo.py`；`dojo/storage.py` 的 `SEEDS` 换成 `seed-m01`–`seed-m04` 并把 `export_prompt` 目标文本改为需求澄清案例；`dojo/cli.py` 冻结材料默认目录改为 `...-v2`；`dojo/compare.py` 标明为旧归档回放。
- 同一操作 — 同步更新 `tests/test_cli.py`、`tests/test_conversation.py`、`tests/test_storage.py`；重写 README、`docs/demo-guide.md`、`docs/cli-guide.md`、`docs/poc-spec.md`；新建 `docs/packets/seed-pack-v2.md`；生成真实检索产物 `docs/packets/frozen-conversation-v2/`；旧评价材料（evaluation、roleplay-guide、facilitator-notes、packets v1）加历史标注，不删除、不改动 `docs/evidence/` 与 `frozen-conversation-v1/`。
- 同一自检：`python3 -m unittest discover -s tests` 27 项通过；`python3 -m compileall -q dojo tests` 通过；`demo --auto` 103 行、`--details` 更长；`bash scripts/storage-smoke.sh` 通过；改动文件无行尾空白；`idea.md` 未改动。哈希：`demo.py 35745f2f…`、`storage.py d7db16f9…`、`cli.py 64953567…`、`current-demo-direction.md e6035178…`、`seed-pack-v2.md 79f732ee…`。未做：真实模型端到端、真实用户研究、在新故事上重跑 B/C。
- 同一操作 — 更新 `docs/current-demo-direction.md`“当前实现与证据边界”为已实现并保留模拟/非效果声明；更新本记录与 `.scratch/active-work.md`。未提交、未安装、未调用 API。
