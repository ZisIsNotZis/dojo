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
DEMO=$(mktemp -d)
export DOJO_DB=$DEMO/lifecycle.sqlite3   # 临时目录：不会碰你自己的库
python3 -m dojo add --id idea-01 --kind abstract_idea \
  --statement '降低与目标无关的摩擦能让重复行为更容易持续' \
  --scope '日常重复行为' --unknown '哪些难度是有意义的训练而非无谓摩擦'
python3 -m dojo confirm idea-01 --basis '表述清楚，值得检索；不表示为真'
python3 -m dojo search '摩擦 持续 行为'          # 词汇重合，命中词可见
python3 -m dojo show idea-01 --history          # 版本与事件
python3 -m dojo challenge idea-01 --text '把一切变容易未必有益'
python3 -m dojo revise idea-01 --statement '在难度不是训练的情况下，降低无关摩擦才让重复行为更容易持续' \
  --reason '补上失效条件，保留旧版本'
python3 -m dojo confirm idea-01 --basis '修订后仍值得检索；仍不表示为真'   # 挑战与修订都会撤销这个标记
python3 -m dojo revoke idea-01 --reason '范围仍不清楚'   # 撤销的是可讨论性，不是历史
```


这份 Demo 是什么、不是什么：三位各有独立问题的陌生人——让整洁可持续、需求没想清就先写代码、以及「有些能力靠困难练出来」这条异议——各自拿到一个候选、一次来自真实本地 Store 的检索，以及一次产生新版本而不删除旧版本的挑战。每一句都是预设台词，`seed-m01`–`seed-m04` 是模拟材料，人物不是用户研究。`compare --full` 离线回放两份归档的 Luna 回答（旧 editor-bridge 评价材料，不是当前故事）；`freeze-materials` 生成四份冻结模型输入，其中 C 条件来自真实的 Store 检索；`demo --workdir ./run` 把数据库和简短总结留在一个新建或空目录里，拒绝覆盖已有数据。


合并从不自动发生；它要一次明确的人工判断，而且可撤销：

```sh
DEMO=$(mktemp -d)
export DOJO_DB=$DEMO/merge.sqlite3        # 自己的库：别名得先存在，才谈得上合并
python3 -m dojo add --id idea-01 --kind abstract_idea \
  --statement '降低与目标无关的摩擦能让重复行为更容易持续' --scope '日常重复行为'
python3 -m dojo add --id idea-alias --kind abstract_idea \
  --statement '与目标无关的摩擦可以降低，重复行为就更容易持续' --scope '日常重复行为'
python3 -m dojo merge idea-alias idea-01 --confirm --reason '主持人核对主张及范围可互换'
python3 -m dojo show idea-alias      # 规范 ID 与重定向链
python3 -m dojo unmerge idea-alias --reason '复核后撤销'
```

把一条故事的知识链读回有四个只读视图，都不写库。它们读的账本是文本（`fixtures/comparison-ledger.json`）；生成出来的 `*.sqlite3` 被忽略规则挡在版本库外，所以检出里要自己造一份：

```sh
# 每跑一次都在一个新目录里建库，所以第二遍不会动到第一遍的库
DEMO=$(mktemp -d)
DB=$DEMO/ledger.sqlite3
python3 -B fixtures/build_comparison_ledger.py "$DB"
STORY=$(python3 -m dojo --db "$DB" stories --synthetic | python3 -c 'import json,sys;print(json.load(sys.stdin)[0]["story"])')
python3 -m dojo --db "$DB" stories "$STORY" --context --synthetic
python3 -m dojo --db "$DB" stories "$STORY" --comparison 5 --synthetic
python3 -m dojo --db "$DB" stories "$STORY" --report 2 --synthetic
python3 -m dojo --db "$DB" stories "$STORY" --proposal 5 --synthetic
```

`--context` 读回这条故事还没核过来源独立性的部分；它的 `omitted_events`（`[5, 15, 16, 17]`）是本视图放不下的当前提议，每个都能直接拿去 `--comparison` 读。`--comparison 5` 返回 `comparison_status: checked` 和 `source_events: [3, 4]`——那是比较者记下「核过两份回执」的判断，不是程序认证。`--report 2` 返回用户原话，`epistemic_status` 是 `user_report_not_independently_verified`。`--proposal 5` 返回提议的 `statement` 和 `state`；这份账本里它的 `report_review` 是空的，空只表示这里没有可列项，不是「核过没问题」。用 `--revision` 再造一份，还能看到「已替代」那一态：`--comparison 5` 退出码 2，并指明当前版是 #27。四个视图互斥，一次只给一个。完整走法和每种拒绝的含义见 [`docs/cli-guide.md`](docs/cli-guide.md)。

真实聊天/讨论、探究工具和限额知识复核会联网；以下是旧讨论入口：

```sh
export DOJO_LLM_BASE_URL=http://127.0.0.1:4000/v1
export DOJO_LLM_MODEL=github_copilot/gpt-6-luna   # 必须与端点注册的 model id 一字不差
# 若需要：在此 shell 里从你的密钥来源设置 DOJO_LLM_API_KEY；仓库里不存它
python3 -m dojo discuss            # 零表单、零 y/n 提示；达成一致才写入结论
python3 -m dojo discuss --verbose  # 在 stderr 实时显示请求与检索进度
python3 -m dojo list               # 没人认可的版本保留为 `unaccepted_draft: true` 草稿
```

### 按库里的卡开一场，以及续跑同一场

`--card ID` 把一张已有的卡交给这一场。开场会点名那句、它替换掉的上一版、库里记下的改动
理由、库里有没有这套说法的认可记录，以及它的**边界**——什么时候成立、什么时候不成立、
还没定的是什么、靠哪些前提，逐条照库里的原话印；来源记录也逐条印出它说的是什么，连同
写它的人自己的限定。第一个真正到达模型的请求带着同样这些内容，并写明这是资料，不是你本
轮说的话。只是把那张卡重复一遍，不算第二个独立来源——交付那一刻写的读记录，就是回声门
读的那一行。

屏幕上每一句都只说程序查过的事，所以有三句话有刻意的写法：

- `draft` 只印「草稿」。草稿不等于没人认可过它——在讨论里认可的结论在有人把它标成可讨论
  之前一直是 `draft`；认可与否由库里那条 `wording_accepted` 记录说，单独成句。库里查不到
  时说的是「这个库里没记下」，不是「没人认可过」。
- 「可讨论」的括号说「有人把它标成值得讨论」。`confirm` 和「认可这套说法」是两个动作，
  共用一个词会让同一屏读起来自相矛盾。
- 改过说法时印「库里记着这一句换过说法，之前是……」，**不**印「变窄」或「变宽」：
  `revise` 记了从哪句、为什么，没记方向，也没记是谁改的。质疑进去的反例和原来的反例
  一起印在「什么时候不成立」下面。

「另一条路」（`alternatives`）不上开场屏幕：它帮不上「我这边要不要照做」这个决定，
而五行边界已经够长。`show` 和模型那边照旧有。

```sh
python3 -m dojo discuss --card c1 --resume discuss-<id>.jsonl   # 拒绝：卡是开场的选择
python3 -m dojo discuss --card c9                               # 打错卡名在本地就回答，不去扰端点
```

```text
无法续跑：--card 与 --resume 不能同时使用。
无法开始讨论：这张卡读不出来（candidate not found: c9）；未发送网络请求。
```

`--resume TRACE` 续跑写下那份轨迹的同一场，追加写入同一个文件，并且沿用这一场**开场时**
带的那张卡——不是库里后来 `revise` 过的那一版。它要求两件事：轨迹必须是这一场自己写的
（库目录下的 `sessions/discuss-<32 位十六进制>.jsonl`，或 `DOJO_SESSIONS` 指向的地方），
且不能与 `--no-trace` 同时用，因为要续跑的正是那份轨迹。

```sh
python3 -m dojo discuss --resume sessions/discuss-0123456789abcdef0123456789abcdef.jsonl
```

没有配置端点时，两个开关仍会先做完本地那部分：卡在要端点之前就已经读出来了，所以看到
`无法启动讨论：未配置 DOJO_LLM_BASE_URL，未发送网络请求。` 说明卡本身没问题。
完整走法（屏幕与请求都打出来）见
[`docs/evidence/2026-11-28-card-handoff/WALK.md`](docs/evidence/2026-11-28-card-handoff/WALK.md)。

### 回看一场已经结束的讨论

`transcript TRACE` 是一场讨论的只读回看：你说了什么、主持人怎么回，然后四件追问逐件列出
当时问的是哪句、你说的是什么、记录把它记成了什么。它不打开库、不写任何东西、不发请求。
写到一半断了的轨迹照样能读，屏幕会说哪一行只写了一半；不能续跑时它也会直说，不会印一条
复制过去必被拒的 `--resume` 命令。

最后那句是关键：这些原话是**材料，不是结论**。一件被收下，只说明系统留下了你当时说的话；
回看不判它答没答到点上，也不代表你认可了那张卡。

```sh
python3 -m dojo transcript sessions/discuss-0123456789abcdef0123456789abcdef.jsonl
python3 -m dojo transcript sessions/discuss-0123456789abcdef0123456789abcdef.jsonl --json
```

四件问完时那句回执会点名这条命令，所以「原话留在本场记录里」不需要先学会 JSONL 才用得上。

### 屏幕上的命令复制出来就能跑

这个程序印的每条命令都是给你复制的 —— 在哪个目录粘都行，按真终端那样做变量和历史展开。
带空格、单引号、`$` 或反引号的路径也是一个参数：

```sh
DB="$(mktemp -d)/我的 库/my dojo's.sqlite3"
mkdir -p "$(dirname "$DB")"
python3 -m dojo --db "$DB" add --id c1 --kind abstract_idea \
  --statement "把持续检查交给系统，人这一侧只保留随时可以推翻的位置。" \
  --scope "一个人已经抽身、只在自己想推翻时回来时"
python3 -m dojo --db "$DB" show c1
```

在那个库上开一场讨论，结束时屏幕印的是（真实运行录下来的，见
[`docs/evidence/2026-11-28-printed-commands/WALK.md`](docs/evidence/2026-11-28-printed-commands/WALK.md)）：

```text
这一场没有写下被认可的卡片；结束时留了一张未认可的草稿：d-1e56e2a1614c（系统整理的那一版，
没有人认可过）。先看它：python3 -m dojo --db "/tmp/x/我的 库/my dojo's.sqlite3" show d-1e56e2a1614c
回看这一场说了什么：python3 -m dojo --db "/tmp/x/我的 库/my dojo's.sqlite3" transcript "/tmp/x/我的 库/sessions/discuss-….jsonl"
```

粘这条命令，在哪个目录打开的都是**那个库**里的草稿；不带 `--db` 它会去读默认库，回你
`candidate not found`。

没有短形式：**每条卡片和回看命令都写绝对路径，不看环境变量。** 印出去的那行在哪儿粘都得
是同一件事，而「默认库」恰恰是各个终端不同意的那件事：`DOJO_DB=chosen.sqlite3` 在每个
目录指不同的文件，只给一条命令设的变量在下一个终端里根本不在，而一个平常用另一个库的
终端也不是印出这行的那一个。`--db 相对路径/dojo.sqlite3` 同理写全。轨迹路径也一律绝对，
因为 `$DOJO_SESSIONS` 也可能是相对的。

代价是常见情况下那行更长。愿意付这个代价的原因：有短形式时，从默认库开始的一场把
`--resume` 粘到一个用另一个库的 shell，会以 0 退出，**并把这场对话的后半段写进那个库**。

库路径从不写进轨迹——你说了什么就是什么，跟那个文件放在哪台机器上无关。

## 现在能做什么

- **带出处的候选账本。** 每条记录带表述、类型、前提、范围、替代路线、矛盾、未知和结构化来源——从不保存原始聊天全文。
- **可讨论 ≠ 为真。** `confirm` 只把候选标为值得讨论与检索，`revoke` 撤回这个标记，`abstain` 记录不确定而不改动版本。
- **版本不可改写。** `revise`、`challenge`、`link`、`split`、`merge` 都保留旧版本与改动理由；`unmerge` 把合并前的记录原样恢复成一个新版本。
- **改主意的理由跟着那句话走。** 他后来把一句改窄了，那么 `search`、`broadcast`、`show` 和 `export` 都会带上 `revision_basis`：被改掉的那句、他给的 `reason` 原话、以及改动时间。只对**现在这句**说话——再改一次，附着的就换成新的理由，旧理由留在 `show --history` 里不删。没改过主意的卡一个字节都不变（没有这个键），同一请求重放也不改它。这不是「他认可现在这句」的背书，理由是他给的话，不是库的判断。
- **检索是透明的。** `search` 就是词汇重合，命中词直接打印——中文多字符查询按相邻二元组匹配，单字符按单字匹配。没有向量、没有隐藏排序；只返回当前 `discussable` 的候选，合并重定向解析到规范 ID。
- **重复不膨胀。** 同一内容再写一次会被拒绝并给出已有卡 ID；第二个独立会话得出同一结论时用 `attach-source` 加来源，而不是再写一张卡。
- **广播的独立性守卫。** `broadcast` 拒收「全部独立性来源就是写它的那个会话」的卡，也拒收 `--session` 指名的会话自己写的卡；被拒的卡连同原因列在 `suppressed` 里，不静默丢弃。
- **会话末管线是幂等的。** `pipeline --session <id>` 跑 `classify → locate → challenge`，每张卡每个修订只处理一次；重跑什么都不写，每个 pass 只提议不改写。
- **有上限的提示词导出。** `export --mode b`（共同目标，不带 seed）或 `--mode c --id …`（目标加显式选择的候选），`--budget-chars` 是硬字符上限；导出不含 actor/judge 笔记。
- **保留代价与出处的讨论。** `discuss` 对每条做法问情境、张力、代价、失效，按问题和字段键记录完整自由文本。收集到回答不等于候选字段已获语义来源锚定，不会仅因非空就升格为“他的原话”；模型生成的候选在映射未完成前仍标 `系统补`。这不否认用户的贡献：他真说了的原话会逐字**附在卡片上**（另建一张表，挨着句子存），用他自己用过的词就能搜回这张卡。附上去不是映射：他的条件不会变成 `scope`，代价不会变成 `contradictions`，字段作者与附着的材料是两件事、分开打印，这场也不判回答有没有答到点上。卡片上那一句和它的条件仍是提问**之前**写下的，问答从不改写它。四件问完（或中途结束输入）后会有一句回执，说清每件怎么了和回答去了哪。**回答最后在哪，取决于一个开关，回执会说是哪一种**：正常一场，原话在卡片上，后来的 `search`、`show`、`discuss --card` 都找得到，回执说「附在卡片 … 上了」并点名跳过或没答的那些件；用 `--no-trace` 时什么文件都不留——包括卡片，它也是同一个盘上的文件——回执说「没有附到卡片上」，`show` 里没有回答，想留下哪一句就自己跑 `promote`。修之前这个开关只关掉了会话记录：屏幕说没留，磁盘上没有轨迹文件，而四条回答其实都在卡片上。每件只用一个结局词，而且必须是真发生的那一个：**原话收下了**（屏幕说的是「你在 X 上说了原话」，不说「你答了」——程序只查过这句不是空、不是跳过、不是收场，没查过它答没答到点上，回执里也这么说）；说跳过；问到这一件时他结束了输入（不说成“没答出来”，那不是他答不上来）；被一句“剩下/接下来几件先不问”搁下；问了两轮没答出来；根本没问到。“剩下的几件”按他说的范围读，不替他假定：“接下来两题先跳过”只搁下两题、最后一题照旧问，“这几题我想先跳过”搁下所剩的，而数量读不出来的请求**不**结束这场、剩下的照问。「先跳过这一题」这类普通话里的跳过请求被当成跳过，不当成回答；讲一条做法的原话（「我跳过这一步的时候就会出错」「剩下的流程我都不讲给新人听」）仍然是回答。
- **先推断再回答的主持人。** 你没说的参数由它假设并写明条件，能推的公式当场推；结论依赖真实数值计算时，它写一节 `## 计算交接单`，程序落盘为 `<会话目录>/compute-<id>-<轮>.md` 交给外部执行器运行——它自己没有代码执行能力，也不会声称跑过计算。
- **请求有边界。** 检索带回页面正文，每条摘录上限 1200 字、每场 6000 字；推理等级用 `DOJO_LLM_REASONING`（默认 `medium`）；单次请求超时默认 60 秒，`DOJO_LLM_TIMEOUT` 接受 5–600 秒。
- **每场会话都有本地轨迹。** 每轮一行 JSON：你的原话、主持人的回答、当轮候选、是否写入及理由、用量、失败原因。默认开启；`--no-trace` 让整场不产生文件，并且四件的回答也不会附到卡片上——这一场结束，你说过的句子不落在任何文件里，真要保留某句就显式跑 `promote`。`--resume <trace>` 续跑同一会话。
- **离线回放。** `compare` 打印两份归档的 Luna 回答及其出处与 sha256；`freeze-materials` 重新生成四份冻结模型输入，C 条件来自程序实际的本地检索。
- **「一条道的一生」这条 loop。** `scripts/dao_life.py` 从具体经历建出道库，检查自洽与可反驳，印出哪些落地格从未跑过、要什么才能跑，并按逐对关系比较两个库——不调模型、不联网、不连数据库。
- **一场真会话能写成探针笔记。** `scripts/dao_session.py` 把 `discuss` 的 JSONL 轨迹写成探针格式的笔记，并写一份 `session.json`：四件里哪几件是他真在会话里答到的。哪件没答、张力说不出两边、或回答里带着笔记无法逐字承载的字符，它就具名拒收、盘上不写；随后 `dao_life.py` 只按会话晋升过的那几件算作者，提炼里把没晋升的一件写成「他的原话」会被判不过。

**一条判断，改了这里的两处决定。** 规则是：重复请求看的是**意图效果**；客户端只有在**有证据**说明第一次没有生效时才可以重试。本仓有两处决定在这条规则下是错的：

- **截断的响应被重发了。** 正文比 `Content-Length` 短，被归成「模型输出格式不合法」并自动重试两次——一个用户回合发了三个请求，还让用户去改提示词。现在它是 `incomplete_response`：不重试，并告诉用户是传输断了。
- **第二个理由被记成了重放。** 把卡片改成它已经是的那句话、只为补一个新理由，措辞一点没变——而存储层把「卡片没动」读成了「同一个请求又来了」，于是新理由被记成第一个的重放。两个不同的论点在账本里共用一个名字。现在守的规则是：*版本只在库存的卡片变了时才动；而「是不是重放」看请求，不看结果*。只看理由还是半条规则：先按无障碍需求把卡片改成「窄屏显示状态」，再按另一个理由改成「所有视口显示状态」，最后又以无障碍需求重申「所有视口」——理由重复了，请求没有；旧读法把指针指回那次改窄屏的行，可那一行要的不是这句话。只看「哪些字段变了」也是半条：正文和理由都一样、只是把范围从「窄屏」改成「所有视口」，两行记下的都是 `["statement","scope"]`，于是后一次被当成前一次的重放。现在判重比的是整份请求——`details.request` 里存着调用方给的每一个输入（范围、前提等都算），直接比这两个对象，不再靠「哪些键要忽略」的清单（那份清单错了两次）。`show --history` 里每条事件都带 `repeat_of` 所用的那个 `sequence`，从重放能一路走到真正要了同一件事的那一行；早于这次改动、没存请求的行会在新行里被记成 `earlier_rows_without_a_recorded_request`，而不是被默默当成另一个请求。

下面的块在真实库上演示第二处：两个理由，两行；同一个理由再来一次，一行，加一行 `.repeat`。
```sh
DEMO=$(mktemp -d)
export DOJO_DB=$DEMO/twice.sqlite3
python3 -m dojo add --id same-words --kind abstract_idea --statement '一键确认很好用'
python3 -m dojo revise same-words --statement '一键确认很快' --reason '移动端同伴看不见活动灯'
python3 -m dojo revise same-words --statement '一键确认很快' --reason '触屏读屏需要一个可读状态'
python3 -m dojo revise same-words --statement '一键确认很快' --reason '触屏读屏需要一个可读状态'
python3 -m dojo events --id same-words   # 两个理由都在，外加一行说自己是一次重放
```

两个理由各是一行普通 `revise`，谁也不指谁。重放那一行是 `revise.repeat`，指名它重放的是哪一条；`version` 全程停在 2，所以已经处理完的管线 pass 不会重新变成待办。每条行上都记着 `to_statement`（这次要去的措辞），和 `from_statement`（来的地方）并排——所以重放不可能指到一行要的是别的话；`details.request` 存着整份请求，所以范围一变就不再是同一个请求。两处决定的前后读数、以及在旧树上会红的臂，都在 [`docs/evidence/2026-11-27-repeat-safety/`](docs/evidence/2026-11-27-repeat-safety/)。

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
docs/dao/        K1 数据：repeat-safety、person-dojo、demo-strangers、probe-demo、vocabulary.json
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
- [`docs/dao/README.md`](docs/dao/README.md) —— K1 库：每个文件是哪一种、谁写、现在哪里还弱。[`docs/dao/repeat-safety/LOOP.md`](docs/dao/repeat-safety/LOOP.md) 是唯一走完全程的一条链：一段有出处的真实叙述、从它拔出来的判断、以及这条判断改过的两处决定（被截断的响应曾经重发，一个用户回合 3 个请求变 1 个；`attach-source` 曾把第二个来源静默丢掉）。
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
- `discuss`：零结构自然语言循环；被认可的版本成为候选，没人认可的版本保留为 `unaccepted_draft` 草稿（来源标 `model_generated`/`unverified`，不可讨论，所以别的会话不会拿它当材料）。本地轨迹、`--resume`、`person.md` 档案、答案需要真实计算时落盘计算交接单。
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
