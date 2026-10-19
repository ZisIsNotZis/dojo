# 道场：本地无 UI 业务逻辑 POC

这是一个**本地 CLI 与 SQLite POC**，用于演练编程/agent 项目中的想法、经验主张、反例和未知如何成为可追溯的讨论候选。它记录讨论状态，不认证真假，也不自动把相似主张合并。没有 UI、服务器、登录或自动 agent；默认体验完全离线。显式选择 `chat` 或 `demo --live` 才会联网，并且必须先配置兼容端点。

## 当前产品方向与恢复入口

主体验是**陌生人分别讨论方法论，通过道藏连接理由、条件与异议**，见 [`docs/current-demo-direction.md`](docs/current-demo-direction.md)。`python3 -m dojo demo` 已按此方向实现三位陌生人的故事。

## 现有演示（约 2–5 分钟）

要求 Python 3.10+；只用 Python 标准库，无需安装依赖。从仓库根目录运行这一条命令：

```sh
python3 -m dojo demo
```

故事分三幕：甲（空间整洁）提出抽象道，经确认/编辑/拒绝后保存；乙（软件开发）在**独立**问题里被真实本地 Store 检索带回甲的抽象道与不同条件路线，并留下自己的应用路线；丙（抽象挑战）提出逻辑异议，产生关系与新版本而**不删除旧道**。醒目提示的预设台词是**模拟，不是实时 AI、用户研究或效果证明**；默认临时数据库在退出时清理。完整指南见 [`docs/demo-guide.md`](docs/demo-guide.md)。

可选：离线回放归档的两份实际 Luna 回答（不联网、不重新生成；这是旧 editor-bridge 评价的材料，不是当前故事）：

```sh
python3 -m dojo compare
```

四条 `seed-m01`–`seed-m04` 是 [`docs/packets/seed-pack-v2.md`](docs/packets/seed-pack-v2.md) 中的模拟材料；`seed` 可重复执行，已有 ID 不覆盖。

默认 SQLite 数据库是 `~/.local/share/dojo/dojo.sqlite3`，程序创建的应用目录为仅当前用户访问（权限 `0700`），数据库文件为 `0600`。可在仓库副本间设置 `DOJO_DB=/private/path/dojo.sqlite3` 或 `--db /private/path/dojo.sqlite3`。`discuss` 的可见、可编辑人物档案固定命名为数据库同目录的 `person.md`，首次创建后程序只在末尾追加日期与会话标记的条目，不覆盖用户编辑，文件权限为 `0600`；设置 `DOJO_PERSON=/private/path/person.md` 可改用其他路径。每场默认读取全文并作为上下文发送给模型，也允许模型追加稳定、可复用、非敏感的信息；开场会披露发送行为，`discuss --no-profile` 可让本场既不读取也不写入档案。模型的隐私与敏感信息约束是提示级，不是强制拦截。数据库只保存用户明确录入的候选、结构化来源摘要、匿名 session ID、版本和事件；**不会录制原始聊天**。导出目录与数据库分离，默认 `~/.local/share/dojo/exports`；可用 `DOJO_EXPORTS` 或 `export --outdir` 调整。导出使用唯一文件名，不覆盖既有文件。

用 `python3 -m dojo --help` 查看操作与参数。核心流程示例：

```sh
python3 -m dojo add --id idea-01 --kind abstract_idea \
  --statement '降低与目标无关的摩擦能让重复行为更容易持续' \
  --scope '日常重复行为' --unknown '哪些难度是有意义的训练而非无谓摩擦'
python3 -m dojo confirm idea-01 --basis '表述清楚，值得检索；不表示为真'
python3 -m dojo search '摩擦 持续 行为'
python3 -m dojo show idea-01 --history
python3 -m dojo revoke idea-01 --reason '范围仍不清楚'
```

`confirm` 仅将候选标为可继续讨论/检索；不会增加事实可信度。检索是可查看命中词的透明词汇重合（中文多字符查询按相邻二元组、单字符查询按单字匹配），不是语义理解。只返回当前 `discussable` 的候选，撤回、草稿和分裂父项不匹配；合并重定向解析到规范 ID。重复次数不加权。

显式人工作出等价判断后才能合并：

```sh
python3 -m dojo merge idea-alias idea-01 --confirm --reason '主持人核对主张及范围可互换'
python3 -m dojo show idea-alias  # 展示规范 ID 与重定向链
python3 -m dojo unmerge idea-alias --reason '复核后撤销'
```

如合并后任一相关记录又变化，程序会拒绝用旧快照覆盖后续工作；可以手动复核恢复。`split` 的 JSON 子项可用 `--children-json '[{...},{...}]'` 或 `--children-json @children.json` 输入；拆分保留父版本与来源 ID。`abstain` 仅记事件，不增加/降低可信度。

## 真实模型与 CLI/SQLite 操作

- `python3 -m dojo chat` 或 `python3 -m dojo demo --live`：只有显式选择这些模式且配置端点后才会发 HTTP 请求。详见 [`docs/demo-guide.md`](docs/demo-guide.md)；无端点配置时不联网、不回退到预设。
- `python3 -m dojo discuss --verbose`：把模型请求、检索 query 与命中域名、每轮耗时实时打到 stderr，stdout 与轨迹不变。一轮讨论会等待多次模型请求和检索（实测单轮 5–30 秒），没有这个通道就只能看到空提示符。`DOJO_LLM_MODEL` 必须与端点注册的模型名一字不差：本机端点是 `github_copilot/gpt-6-luna`（下划线），连字符版本会被端点以 HTTP 400 拒绝。
- `python3 -m dojo demo --auto`：无 stdin 的 CI 预设故事；`python3 -m dojo demo --details` 展开每条检索卡；`python3 -m dojo demo --workdir ./my-dojo-run` 可保存数据库和简短总结，目录必须为空且不会覆盖已有数据。
- `python3 -m dojo compare --full`：显示两份归档原文（旧 editor-bridge 评价，非当前故事）；默认 `compare` 提供短摘要、run ID 和输入文件路径，不联网。
- `python3 -m dojo freeze-materials`：生成四份独立模型输入；C 条件来自程序实际 Store 检索，输出不会覆盖现有目录。默认输出目录为 `docs/packets/frozen-conversation-v2/`。
- [`docs/evidence/conversation-demo-luna-v1/provenance.md`](docs/evidence/conversation-demo-luna-v1/provenance.md)：归档来源、摘要、sha256 和比较局限；两份原文均完整保留。
- [`docs/cli-guide.md`](docs/cli-guide.md)：15 分钟业务存储操作序列，含确认、撤销、challenge/revise、检索、abstain 与 B/C 导出。
- `sh scripts/demo.sh` 启动同一个中文故事；旧的后台 JSON 数据库检查改为 `sh scripts/storage-smoke.sh`。

## 文档与试验边界

- [`docs/philosophy.md`](docs/philosophy.md)：用户明确优先事项与可撤销 POC 设计分别标注。
- [`docs/poc-spec.md`](docs/poc-spec.md)：纸面阶段的历史规格与当前 CLI/SQLite 实现行为、简化差异。
- [`docs/packets/seed-pack-v2.md`](docs/packets/seed-pack-v2.md)：当前 demo 的四条模拟 seed 说明。
- [`docs/packets/seed-pack-v1.md`](docs/packets/seed-pack-v1.md)、[`docs/roleplay-guide.md`](docs/roleplay-guide.md)、[`docs/evaluation.md`](docs/evaluation.md)、[`docs/facilitator-notes.md`](docs/facilitator-notes.md)：旧 editor-bridge 评价的历史材料，不属于当前陌生人故事。

存储检索始终只是可检查的词汇重合，不是语义检索。`export --mode b` 生成不带 seed 的共同目标材料；`export --mode c --id seed-m01 --id seed-m02` 将同一目标与操作者显式选择的讨论候选合并。`--budget-chars` 是包含来源 ID 在内的硬字符上限，不是模型 token 估计；导出不含 actor/judge 笔记。`idea.md` 是历史原稿，保持原样。

运行标准库测试：

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q dojo tests
```

原始草案 [`idea.md`](idea.md) 保留原样，仅作为历史来源，不覆盖已明确优先事项。示例、角色和四条种子均为模拟材料，不代表研究结果、独立证据或产品效能。
