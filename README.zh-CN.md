<p align="center"><img src="assets/logo.svg" alt="dojo 道场" width="200" height="40"></p>

[English](README.md) | **简体中文**

# 道场 · dojo

一个本地、无 UI 的 CLI 与 SQLite 概念验证：把想法、经验主张、反例和未知保存为可追溯的讨论候选，连同它从哪来、边界在哪、替换了哪个版本。

**道场记录「谁在什么依据下说了什么」，并且拒绝判定它为真：`confirm` 只表示"值得检索"，每次改写都保留被替换的版本，而一条「唯一来源就是写它的那个会话」的主张永远不会被当成他人佐证再广播回去。**

```sh
python3 -m dojo demo     # 三幕中文故事，离线，无依赖
```

## 快速开始

要求 Python 3.10+，别的都不要——运行时只用标准库，没有安装步骤。在仓库根目录运行：

```sh
git clone https://github.com/ZisIsNotZis/dojo.git
cd dojo

python3 -m dojo demo              # 离线三幕故事，临时数据库退出即清理
python3 -m dojo demo --auto       # 同一故事，不读 stdin（无提示）
python3 -m dojo demo --details    # 展开每条检索卡
python3 -m dojo --help            # 全部操作与参数
```

这份 Demo 是模拟台词，不是实时 AI，也不是用户研究。想跑一遍全部存储操作的真实端到端流程（临时库，不碰仓库数据）：

```sh
sh scripts/storage-smoke.sh
```

手工走一遍一条主张的一生：

```sh
python3 -m dojo add --id idea-01 --kind abstract_idea \
  --statement '降低与目标无关的摩擦能让重复行为更容易持续' \
  --scope '日常重复行为' --unknown '哪些难度是有意义的训练而非无谓摩擦'
python3 -m dojo confirm idea-01 --basis '表述清楚，值得检索；不表示为真'
python3 -m dojo search '摩擦 持续 行为'          # 词汇重合，命中词可见
python3 -m dojo show idea-01 --history          # 版本与事件
python3 -m dojo challenge idea-01 --text '把一切变容易未必有益'
python3 -m dojo revise idea-01 --statement '在难度不是训练的情况下，降低无关摩擦才让重复行为更容易持续' \
  --reason '补上失效条件，保留旧版本'
python3 -m dojo revoke idea-01 --reason '范围仍不清楚'   # 撤销的是可讨论性，不是历史
```


这份 Demo 是什么、不是什么：三位各有独立问题的陌生人——让整洁可持续、需求没想清就先写代码、以及「有些能力靠困难练出来」这条异议——各自拿到一个候选、一次来自真实本地 Store 的检索，以及一次产生新版本而不删除旧版本的挑战。每一句都是预设台词，`seed-m01`–`seed-m04` 是模拟材料，人物不是用户研究。`compare --full` 离线回放两份归档的 Luna 回答（旧 editor-bridge 评价材料，不是当前故事）；`freeze-materials` 生成四份冻结模型输入，其中 C 条件来自真实的 Store 检索；`demo --workdir ./run` 把数据库和简短总结留在一个新建或空目录里，拒绝覆盖已有数据。


合并从不自动发生；它要一次明确的人工判断，而且可撤销：

```sh
python3 -m dojo merge idea-alias idea-01 --confirm --reason '主持人核对主张及范围可互换'
python3 -m dojo show idea-alias      # 规范 ID 与重定向链
python3 -m dojo unmerge idea-alias --reason '复核后撤销'
```

接模型端点的自然语言讨论是显式选择，也是唯一会联网的路径：

```sh
export DOJO_LLM_BASE_URL=http://127.0.0.1:4000/v1
export DOJO_LLM_MODEL=github_copilot/gpt-6-luna   # 必须与端点注册的 model id 一字不差
# 若需要：在此 shell 里从你的密钥来源设置 DOJO_LLM_API_KEY；仓库里不存它
python3 -m dojo discuss            # 零表单、零 y/n 提示；只在达成一致的那一轮写入
python3 -m dojo discuss --verbose  # 在 stderr 实时显示请求与检索进度
```

## 现在能做什么

- **带出处的候选账本。** 每条记录带表述、类型、前提、范围、替代路线、矛盾、未知和结构化来源——从不保存原始聊天全文。
- **可讨论 ≠ 为真。** `confirm` 只把候选标为值得讨论与检索，`revoke` 撤回这个标记，`abstain` 记录不确定而不改动版本。
- **版本不可改写。** `revise`、`challenge`、`link`、`split`、`merge` 都保留旧版本与改动理由；`unmerge` 把合并前的记录原样恢复成一个新版本。
- **检索是透明的。** `search` 就是词汇重合，命中词直接打印——中文多字符查询按相邻二元组匹配，单字符按单字匹配。没有向量、没有隐藏排序；只返回当前 `discussable` 的候选，合并重定向解析到规范 ID。
- **重复不膨胀。** 同一内容再写一次会被拒绝并给出已有卡 ID；第二个独立会话得出同一结论时用 `attach-source` 加来源，而不是再写一张卡。
- **广播的独立性守卫。** `broadcast` 拒收「全部独立性来源就是写它的那个会话」的卡，也拒收 `--session` 指名的会话自己写的卡；被拒的卡连同原因列在 `suppressed` 里，不静默丢弃。
- **会话末管线是幂等的。** `pipeline --session <id>` 跑 `classify → locate → challenge`，每张卡每个修订只处理一次；重跑什么都不写，每个 pass 只提议不改写。
- **有上限的提示词导出。** `export --mode b`（共同目标，不带 seed）或 `--mode c --id …`（目标加显式选择的候选），`--budget-chars` 是硬字符上限；导出不含 actor/judge 笔记。
- **会记录代价的讨论。** `discuss` 对每条做法问四件事——情境、张力、代价、失效——每一件都记「谁写的」，并由最弱的一件封顶（只要有一件是系统补，状态就是 `合写`）。
- **先推断再回答的主持人。** 你没说的参数由它假设并写明条件，能推的公式当场推；结论依赖真实数值计算时，它写一节 `## 计算交接单`，程序落盘为 `<会话目录>/compute-<id>-<轮>.md` 交给外部执行器运行——它自己没有代码执行能力，也不会声称跑过计算。
- **请求有边界。** 检索带回页面正文，每条摘录上限 1200 字、每场 6000 字；推理等级用 `DOJO_LLM_REASONING`（默认 `medium`）；单次请求超时默认 60 秒，`DOJO_LLM_TIMEOUT` 接受 5–600 秒。
- **每场会话都有本地轨迹。** 每轮一行 JSON：你的原话、主持人的回答、当轮候选、是否写入及理由、用量、失败原因。默认开启，`--no-trace` 让整场不产生文件，`--resume <trace>` 续跑同一会话。
- **离线回放。** `compare` 打印两份归档的 Luna 回答及其出处与 sha256；`freeze-materials` 重新生成四份冻结模型输入，C 条件来自程序实际的本地检索。
- **「一条道的一生」这条 loop。** `scripts/dao_life.py` 从具体经历建出道库，检查自洽与可反驳，印出哪些落地格从未跑过、要什么才能跑，并按逐对关系比较两个库——不调模型、不联网、不连数据库。
- **一场真会话能写成探针笔记。** `scripts/dao_session.py` 把 `discuss` 的 JSONL 轨迹写成探针格式的笔记，并写一份 `session.json`：四件里哪几件是他真在会话里答到的。哪件没答、张力说不出两边、或回答里带着笔记无法逐字承载的字符，它就具名拒收、盘上不写；随后 `dao_life.py` 只按会话晋升过的那几件算作者，提炼里把没晋升的一件写成「他的原话」会被判不过。

## 架构

运行时刻意做小：一个 SQLite 文件就是全部状态，CLI 只是薄薄一层 argparse，存储层之上的一切要么提议、要么渲染。

```
dojo/
  cli.py         命令行面：每个存储操作一个子命令
  storage.py     SQLite schema、版本与事件、检索、合并/拆分、导出
  live.py        基于 urllib 的有界 OpenAI 兼容 HTTP 客户端
  discuss.py     自然语言循环：达成即写、轨迹、person.md 档案
  elicit.py      四句问法与「谁写的」规则，只有一份
  pipeline.py    classify → locate → challenge，每卡每修订一次
  search.py      词汇重合打分，命中词可见
  demo.py        三幕模拟故事；freeze-materials
  compare.py     归档回答的离线回放
scripts/
  dao_life.py    K1 loop：事件 → 道 → 回执 → 道图，含拒收
  dao_session.py discuss 轨迹 → 探针笔记 + 作者记录
  dao_live_session.py、dao_elicit.py、tension_overlap.py
  demo.sh、storage-smoke.sh
tests/           unittest 测试集，只用标准库
docs/            分层事实库，索引见 docs/README.md
docs/dao/        K1 数据：person-dojo、demo-strangers、probe-demo、vocabulary.json
inbox/、mail/    作为历史保留的工作笔记
idea.md          最初的原稿，保持原样
```

各部分怎么说话：`cli.py` 解析命令后交给 `Store`（`storage.py`），它是 SQLite 唯一的写入者，也是检索唯一的读取者。`discuss.py` 组装主持人提示词、调用 `live.py`、把每一轮写进本地 JSONL 轨迹，并且只在模型报告用户已同意时写卡。`pipeline.py` 读写同一个 store，在会话结束后运行。`scripts/dao_life.py` 完全不碰数据库：它读写 `docs/dao/` 下的 JSON 库，给定 `--at` 时重跑逐字节相同。

状态与隐私，直说：

- 默认数据库 `~/.local/share/dojo/dojo.sqlite3`（用 `DOJO_DB` 或 `--db` 改路径）；程序创建的应用目录权限 `0700`，数据库文件 `0600`。
- `discuss` 在数据库同目录维护固定的 `person.md`，权限 `0600`，首次创建后只在末尾追加；`--no-profile` 本场既不读也不写。
- 会话轨迹在 `<数据库目录>/sessions/<session>.jsonl`，`0600`，仅存本地、不上传。
- 导出到 `~/.local/share/dojo/exports`，唯一文件名，绝不覆盖（`DOJO_EXPORTS`、`--outdir`）。
- 模型侧的隐私约束是提示级的，不是强制拦截。数据库只保存候选、来源摘要、匿名 session ID、版本与事件，不存原始聊天；你的原话只出现在轨迹里，而轨迹可以整场关掉。

### 事实住在哪里

- [`docs/product.md`](docs/product.md) —— 产品方向、质量维度、非目标；「这是什么」的唯一入口。
- [`docs/design.md`](docs/design.md) —— 不变量、模块、管线、防风暴与防污染规则。
- [`docs/plan.md`](docs/plan.md) —— 里程碑、验收行、预算、交付契约；`## 当前推进状态` 写明现在卡在哪。
- [`docs/dao/README.md`](docs/dao/README.md) —— K1 库：每个文件是哪一种、谁写、现在哪里还弱。
- [`docs/cli-guide.md`](docs/cli-guide.md) —— 15 分钟存储操作序列；[`docs/demo-guide.md`](docs/demo-guide.md) —— 逐个参数讲 Demo。
- [`docs/evidence/`](docs/evidence/) —— 绑在具体 commit 上的归档证据，不是当前事实。

`idea.md` 是保留的原稿：它解释方向从哪来，永远不是行为规格。

## 开发

```sh
python3 -m unittest discover -s tests -v   # 全套测试，无需安装、不联网
python3 -m compileall -q dojo tests        # 全树语法检查
sh scripts/storage-smoke.sh                # 临时目录里的端到端 CLI 演练
```

开发约定与完整的分层文档索引见 [`docs/README.md`](docs/README.md)；协作边界（单人、无 UI、不从草案推导超出已确认范围的产品承诺）见 [`AGENTS.md`](AGENTS.md)。

## 参与

先读 [`CONTRIBUTING.md`](CONTRIBUTING.md)。一句话：这是一个范围受控的 POC——行为改动要先写验收行再动手，测试只跑标准库，不为了省事加依赖。

## 路线图

**已实现**

- 候选生命周期：带出处、不可改写版本、可撤销的合并与拆分；词汇检索带合并重定向；重复写入被拒。
- 广播独立性守卫、会话末 `classify → locate → challenge` 管线、有上限的 B/C 提示词导出。
- 三幕离线 Demo、离线对比回放、冻结材料生成器。
- `discuss`：零结构自然语言循环、在同意那一轮写入、本地轨迹、`--resume`、`person.md` 档案、答案需要真实计算时落盘计算交接单。
- K1「一条道的一生」：loop 已跑过一位真人的记录（13 条道、9 条写不成道的材料、1 条候选、1 对自相矛盾、26 条记录检查、0 条晋升），外加一个按构造就是模拟的第二个库，并自己写明这一点。
- 一场完成的 `discuss` 会话可以导出成探针笔记；哪几件是他的由会话决定、不由手写的提炼声明，提炼声称了一件没被晋升的会被库拒绝。
- 只用标准库的测试集，覆盖 CLI、存储、检索、讨论、Demo、管线与 K1 loop。

**计划中，且老实说没完成**

- M2 未达成：`classify` 报 `unavailable` 而不猜，所以还缺一次真实模型判定；会话末的提炼清单也还没整场跑过并经人过目。
- 实验 harness 与张力收敛探针已写成规格但还没跑；`docs/probe/notes/` 里零笔记。
- 记录里只有一位真人的材料。跨人的「道理数据库」这个承诺尚无跨人证据；在第二个人的材料进来之前，请把它读成一个人的思想整理器，而不是人类的道。
- 不建也不近期计划：UI、服务器、登录、社交、排行榜、信息流、计费、多节点联邦。

如果这条 loop 能在不止一个人身上活下来，方向是这样：一条主张到达你手里时，具体场合被剥掉了，但边界、反例和每一件的作者还在——于是面对真实决定的陌生人拿到的是带着条件的方法，分歧产生新版本而不是删除，重复不会把任何东西升级成真。

## 许可

GNU Affero General Public License v3.0 —— 见 [`LICENSE`](LICENSE)。Copyright (C) ZisIsNotZis。

`idea.md` 是作者最初的原稿，作为历史来源保留、不改写。仓库里的每个 Demo 角色、seed 与模拟语料都是模拟材料，不是研究结果、独立证据或产品效果的主张。
