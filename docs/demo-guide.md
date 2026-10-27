# 中文交互体验与实时模型聊天

先用一条命令完成约 2–5 分钟的离线故事：

```sh
python3 -m dojo demo
```

体验者选择是否开始；剧本分三幕，分别演练甲（空间整洁）、乙（软件开发）、丙（抽象挑战）三位互不认识的陌生人。甲提出抽象道，经确认/编辑/拒绝后保存；乙在自己的**独立**问题里被真实 `Store.retrieve` 带回甲的抽象道与不同条件路线，再留下自己的应用路线（单独的 `application` 记录，`instantiates` 指向抽象道，不合并）；丙用逻辑挑战补充边界，产生 `challenges` 关系与修订版本而不删除旧道。检索结果默认压缩为 ID、观点、关键条件/分歧、未知与来源核验状态；`python3 -m dojo demo --details` 展开全部字段。若用 `--workdir ./my-dojo-run` 保留数据库，可用 `python3 -m dojo --db ./my-dojo-run/dojo.sqlite3 show ID --history` 查看完整候选和版本。退出清理默认临时私有数据库。可输入自定义源想法，但离线预设脚本不会解释它：只能丢弃该输入并继续固定故事，或取消后显式配置 `python3 -m dojo chat`。自编辑卡在保存前必须由用户明确确认仍符合其沿用的类型和范围；脚本不会分类，固定后半段也不会对用户编辑卡声称理解（此时挑战作用在预设抽象 seed 上，并明确告知）。EOF、取消和默认否都不会冒充同意。

离线故事醒目提示：它是**预设/模拟台词，不是实时 AI、用户研究或效果证明**。甲/乙/丙的台词写死，不代表真实用户，也不理解自由输入；检索为透明词汇重合，不是语义匹配、建议排名或真相排序。丙的挑战会与不同适用条件路线并列保留，没有唯一正确答案。

## 仅在明确选择时调用模型

`python3 -m dojo chat` 或 `python3 -m dojo demo --live` 是真实网络模式。必须显式设置 OpenAI-compatible endpoint：

```sh
export DOJO_LLM_BASE_URL='https://your-approved-compatible-endpoint/v1'
export DOJO_LLM_MODEL='github_copilot/gpt-6-luna'  # 不设则用同一个默认值；不会静默替换
# 可选：只对需要 token 的服务设置；本地服务可以省略。
# 从本机安全方式取得 token 后，在此 shell 里设置 DOJO_LLM_API_KEY；不要写进仓库或命令历史。
python3 -m dojo chat
```

不要把密钥写入 shell 历史、仓库或 URL。程序不探测账号、不提供/购买账号、不输出 token；仅在请求 `Authorization` header 中发送。没有配置 endpoint 时立即失败，不发网络请求，也不回退成预设脚本。Base URL 只接受 HTTP/HTTPS；明文 HTTP 限 loopback（localhost/回环 IP）；远端必须 HTTPS。endpoint 不接受 URL 内嵌凭据、query 或 fragment；HTTP 重定向会被拒绝，避免跳转绕过明文/主机限制。使用 HTTP 的本地 mock server 可离线测试 adapter。

每次请求最多等待 20 秒、最多读取 24 KB 响应；每轮用户输入不超过 1,600 字，最多 12 次模型请求、最多约 900 输出 tokens。context 包含该轮 Store 透明检索及有限近期对话；不传裁判/主持人笔记或 actor 卡。超时、HTTP 错误、超预算或严格 JSON/schema 不匹配时清楚失败，不生成假候选、不静默换脚本、不保存候选。服务端内容是不可信数据，没有 tools；候选只可显示、编辑或拒绝。保存草稿及“值得继续讨论”的确认是两次人类选择；确认不代表事实。`/challenge ID | 内容`、`/revise ID | 新观点 | 理由` 可在本地追加挑战、保存新版本，之后仍须人明确确认；`/history ID` 可见版本轨迹。旧版本不覆盖。

原始聊天只在进程内存保留，退出即丢弃。明确确认保存候选时，SQLite 仅保存结构化观点、来源摘要和状态；用户输入来源、模型生成来源与模拟来源分开标记，模型不提供经验证据。挑战/修订由用户明确提交时会作为候选事件保留。聊天并非端到端保密保证；不要输入密钥或无必要的个人信息。`chat` 默认沿用本机 `DOJO_DB`/私有数据库；`demo --live` 默认使用退出清理的临时数据库，`--workdir` 可保存但只接受新建或空目录。

## 冻结对照输入（供实际 Luna 消费）

运行 `python3 -m dojo freeze-materials` 默认在 `docs/packets/frozen-conversation-v2/` 创建四个独立文件：source contribution、无道场 B、带实际 Store 检索 C、challenge。已有输出目录会被拒绝覆盖。C 由程序调用真实 `Store.retrieve` 产生，只含本次实际分配的候选及来源状态；不含答案键、actor 或 judge 笔记。B/C 使用相同冻结 target 文本。

已有两份实际 Luna 输出可用 `python3 -m dojo compare` 离线回放；`--full` 阅读原文。原文与 provenance 保存在 [`docs/evidence/conversation-demo-luna-v1/`](evidence/conversation-demo-luna-v1/provenance.md)。这两次是 Pi 子代理独立新上下文消费，不是 HTTP adapter 请求，也不是用户研究；输入/输出 token 长度不同、预算未严格匹配、样本各一，不能据此宣布胜负或 C 更好。它们展示的只是这两次实际文本。

脚本模式用于快速看懂用户流程；其余 SQLite 操作与 15 分钟人工业务演练见 [`cli-guide.md`](cli-guide.md)。存储、来源和检索边界见 [`poc-spec.md`](poc-spec.md)；模拟 target 的单人探索性评价边界见 [`evaluation.md`](evaluation.md)。
