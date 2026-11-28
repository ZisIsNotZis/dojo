# 15 分钟本地 CLI 演练（模拟流程，不是研究结果）

15 分钟是命令与流程排练的目标时长，不是保证完成时间；若加入 actor/答题模型讨论，可能花更久。本指南使用隔离临时目录，需要在**当前 shell** 中按末尾步骤检查并手动清理；异常关闭 shell 不会自动清理，也不会触碰默认 `~/.local/share/dojo/dojo.sqlite3`。从仓库根目录执行；Python 标准库即可。四条 seed 和 actor/答题文本都是模拟材料。此 CLI 操作序列不自动调用 LLM；实时模式安全边界见 [demo-guide.md](demo-guide.md)。

## 0–3 分钟：初始化与写一条清晰候选

```sh
WORK=$(mktemp -d "${TMPDIR:-/tmp}/dojo-walkthrough.XXXXXX")
export DOJO_DB="$WORK/dojo.sqlite3"
export DOJO_EXPORTS="$WORK/exports"
python3 -m dojo seed
python3 -m dojo list
python3 -m dojo show seed-m04
```

确认 `seed-m04` 标有 `claimed_firsthand`、`unverified`、独立性 `unknown`。不要把它作为已经核实的第二条证据。[seed-pack-v2](packets/seed-pack-v2.md) 是本轮四条 seed 的说明。

人工讨论后录入精确表述；不要复制整段原始对话：

```sh
python3 -m dojo add --id life-01 --kind abstract_idea \
  --statement '降低与目标无关的摩擦，可能比要求自己“更自律”更能稳住重复行为' \
  --premise '这个行为会重复发生' \
  --scope '日常重复行为（如物品归位、例行整理）能否持续' \
  --alternative '若困难在于不知道怎么做，单纯降低操作摩擦帮助有限' \
  --unknown '哪些难度是有意义的训练而非无谓摩擦' \
  --source-json '{"id":"src-life-01","type":"abstract_reasoning","claim":"从模拟陌生人场景抽象出的想法，不是经验报告","independence_group":"stranger-methodology-v1","verification":"not_evidence","scope_note":"模拟讨论"}' \
  --session life-anon-1
python3 -m dojo show life-01
```

重复内容不会写成第二张卡：`add` 比对的是内容本身（陈述、类型、五条列表，忽略空白与列表顺序），命中就报错并给出已有卡 ID，不写入新版本。两个会话各自独立得出同一结论时的做法是给已有卡加来源，而不是再写一张卡：

```sh
python3 -m dojo attach-source life-01 \
  --session life-anon-2 \
  --source-json '{"type":"unknown","claim":"第二个独立会话得出相容主张","independence_group":"life-anon-2","verification":"unknown"}'
```

同一会话重复附来源是空操作（不写事件、不升版本），所以跑两遍和跑一遍一样。

## 3–7 分钟：关系、确认、中文检索

alias 只用于真正等价的表达变体；条件不同则用 link 保留区别。确认仅表示值得检索：

```sh
python3 -m dojo alias life-01 \
  --wording '用心设计环境比反复下决心更能让行为持续' \
  --reason '主持人核对为等价改写'
python3 -m dojo link life-01 --relation narrows --target seed-m01 \
  --reason '新候选限定在日常重复行为的持续'
python3 -m dojo show seed-m01               # 从原卡读回 life-01 → seed-m01
python3 -m dojo confirm life-01 \
  --basis '表述足够精确，值得在新讨论检索；不是事实确认' \
  --session life-anon-1
python3 -m dojo search '摩擦 持续 行为'
```

`link` 能写的类型是一个闭集：`supports`、`challenges`、`narrows`、`generalizes`、`conflicts`、`instantiates`、`duplicates`。

第二场的材料若是补充、收窄或反例，先分别存卡和各自的来源。只有明确执行 `link 新卡 --relation … --target 原卡 --reason …` 后，原卡的 `show` 才会列出这次登记（`incoming_links`）。每一项都带登记理由、事件编号、时间，以及登记所指的两版陈述、范围和来源。`source` 是新卡写入关系后的版本；`target` 是当时所指的原卡版本。两个版本即使后来改过也不会跟着换；旧记录没存目标版本，显示 `null`，不猜。手动登记不等于采纳反例、认可措辞或独立核验，也不把新卡的来源算进原卡。合并后按所请求编号分别看：旧编号的关系不继承到现用编号；要看登记在现用编号的关系，另开 `show <resolved_id>`。

**先读来源，再决定要不要改写。** `show 原卡` 的 `incoming_link_summary` 按**登记所指的目标版本**列出每组的关联编号；`relations` 分开列补充/支持（`supports`）、收窄（`narrows`）、反驳（`challenges`）等登记类型。`is_current` 表示这一行确实指向当前卡的当前版。`declared_group_count` 是所有列出的入边中，不同的**申报**来源组数，不是人数、支持票或独立核验数。同组就算来自不同卡、不同版本，也只计一组；从登记时两端的快照读，不用当前卡补旧数据。`unknown_group_link_sequences` 只提示哪些关联至少有一份未识别来源（也可能同条关联已有一个已知组），不拿会话代填，不能当作额外的独立来源。原卡自己的来源仍只看 `candidate.sources`。

如果确实要用某条关联改写，从 `incoming_links` 选出一条 `target` 恰好是当前卡当前版的登记，并把它的 `sequence` 填到下面。用自己的新措辞和理由，不是自动抄写：

```sh
# EVENT_SEQUENCE 是 show 输出中的数字，请先替换
python3 -m dojo revise seed-m01 --adopt-link EVENT_SEQUENCE \
  --statement '在日常重复行为里，有时可以调整环境，降低与目标无关的摩擦。' \
  --reason '据这条登记限定适用范围，不把另一场的材料并入本卡来源。'
python3 -m dojo show seed-m01 --history
```

关联的 `adopted_by` 另外指向那次改写的版本和理由；再改出一版时，原采纳留在历史里，不自动算作新一版的采纳。旧版、版本不明、别卡的登记，或原样保留措辞，不能以这种方式采纳。若双方已换版本、旧登记理由又完全相同，`link` 仍会拒绝重复；要重新核对当前版时，写明这次理由。新稿仍是草稿；没有自动合并、传播或引入来源，也不表示认可原话、认可结论或核验证据。

另有一种 `derived_from` 是**程序自己**写的：一场带着 `--card X` 的讨论写下了另一版时，新卡记着它来自 X。它不是人能连的关系，`link` 会拒绝——屏幕上「后来有一场带着这条继续谈」这句话只对程序记下的那条边说，手打的边印成「库里记着与这条有关的关系」。两者都不是 `narrows`/`generalizes`：库里没有记方向。

逐条读命中的 `matched_terms`、条件、来源、unknowns 和 contradictions。分数只计算不同查询词命中数，不代表可信度。没被接受的草稿、撤回状态不返回；但你自己认可过的措辞即使还停在 `draft` 也会返回——那种命中带 `accepted_at`（那一版措辞被接受的时间）。被挑战、以及接受之后又改过措辞的卡不返回：接受绑的是当时那一版措辞，改后那句没被接受。

**这些被拒的卡只在 JSON 里不出现，在给人看的屏幕上不会消失。** 屏幕（写 stderr）把字词重叠的卡排成一张清单，每张第一行就说检索会不会把它交出去、为什么（被质疑／被撤回／没有认可记录／认可绑的是旧说法），后面照印它自己的条件、反例、来源和一条可粘贴的 `discuss --card` 命令。用相对路径给的 `--db` 在屏幕上会解析成绝对路径。`stdout` 仍是上面这个 JSON，且只在**被重定向或接管道**时打印；直接对着终端运行时，屏幕上只留一行提示，免得 20 多行可读结果被整块 JSON 淹掉。

字词一个都不重叠时，屏幕会说清这是词汇检索，并列出最近写下的几张卡作为**另一个办法**，明确说明那不是按意思找的。改过措辞的卡也能用**换掉之前那句**找到，命中会注明是哪句旧说法、卡片现在写什么。

`accepted_at` 是**这一刻记录下来的时间**，不一定是同意发生的时间：从轨迹里补记一条接受，写的是补记那一刻，可能与当时相差数周。若补记方知道真正的同意时刻，命中和导出头会多带一个 `agreed_at`（与 `accepted_at` 并存，不替换它）；没有这一项就是“当时那一刻没记”，不要把它当成 `accepted_at`——也不要反过来把 `accepted_at` 当同意时刻。

判断“有没有人接受过”只看 `accepted_at` 在不在，不要看 `status`，也不要看 `unaccepted_draft`：`discussable` 只说明主持人标了可讨论，而 `unaccepted_draft: true` 只是一个形状标记：整张卡只有一条来源、且那条来源的类型是模型生成（`model_generated`）。它不看有没有人接受，也不一定全覆盖——只有一条 `unknown` 来源的卡就不带它。不匹配就接受空结果，不要换词直到“搜出答案”。

`search` 与 `broadcast` 是同一次词汇检索的两个出口，差别只在要不要跨会话材料：`search` 返回所有可讨论命中，`broadcast` 额外拒收两类卡，并把拒收原因列在 `suppressed` 里而不静默丢弃——全部独立性来源就是写它的那一个会话的卡（写它的会话无论记在来源组里，还是只记在卡上），以及 `--session` 指名的那个会话自己写的卡（一场会话不把自己的话当别人的佐证）。`broadcast` 的每条命中带 `independence`：`independence_groups` 列出几个互不相同的来源，`named_groups` 只列来源上自己填的组名，`sessions` 列出写过它的会话，`provenance_status` 是 `cross_session`／`single_session`／`unidentified` 三者之一（最后一种是来源组只有一个且查不到它是会话，例如 seed，只在结果里点名而不拒收）。`search` 的命中**不带** `independence`：它是「有哪些可讨论的卡」这一面，不做独立性判断，所以从它读不出某张卡是不是一个会话自己的话。今天只有 `broadcast` 给这个块（`show` 也不带）。这些只做报告，不参与排序：

```sh
python3 -m dojo broadcast '摩擦 持续 行为' --session life-anon-1
python3 -m dojo export --mode c --id life-01 --budget-chars 6000   # 全部来源就是写它的那一个会话的卡会被拒
```

`independence_groups` 数的是判决实际用到的来源，不是核验过的独立来源，也不是人数。一条来源算一处，按这几条决定它算在哪：

1. 来源自己填了 `independence_group`，就按这个名字算（自填组名的清单另在 `named_groups`）。
2. 来源没填组名，且它是在**同一次写入**里跟一个具名来源一起交上来的，就规到那一次的组名下——换了登记方式，没换见证人，不算第二处。
3. 来源没填组名、同一次写入里也没有具名来源，才归给 `attach-source` 那个会话的 id。
4. 会话 id 永远不会被加到一条已经填了组名的来源上（那会把两份各自具名的材料压成一份）。

所以同一个见证人把同一份材料用两种登记方式交进来，只要两种方式在同一次写入里，就仍是一处。两个不同的组名仍然算两处——那是两个人或两份材料各自具名。组名和写它的会话 id 对不上时状态是 `unidentified`（例如 seed），而 `broadcast` 与 `export` 在独立性这一维上只拒 `single_session`，所以一张单会话的卡也能过闸，带着 `independent=false` 出去。

这个数数的是**有几次各自具名的申报**，不是有几个独立见证人。界限在这里：同一模型的两次不同轮次各自填了组名，会印成两处独立来源——判据不看是谁生成的，只看向它申报了几次。（按来源类型把模型生成的两轮并成一处，会把「同一模型在不同处境下产生的两份材料」也压成一处，那是用生成者的身份去否定作者的申报，所以没有这么做。）因此要判断「是不是真有两次互不知情的独立确认」，不能只看这个数，得回到 `sources` 里各条的 `type`、`independence_group` 和进入时间上。

`export` 除了独立性，还要求被选中的卡当前 `status` 是 `discussable`：只是被接受、但还没标可讨论的 `draft` 会被拒（`selected candidate is not currently discussable`）。这与检索面不同——检索会返回「自己认可过的 `draft`」，出口不会。两处要求不同是有意的：能搜到一张卡，不等于它能作为跨会话材料交出去。

## 会后找回草稿（`review-drafts`）

如果讨论最后转向了另一条问题，你仍可以从结束回执复制「找回本场先前的拟写」。已有的讨论也可从 `distill --text --trace` 的同名命令进入；请保留命令带的原库路径和轨迹指纹。没有保存完整轨迹（例如 `discuss --no-trace`）时，无法找回其中较早的拟写。

1. 输入轮次编号，逐字核对当轮原话和主持人当时拟写的全部字段。
2. 输入 `/补边界 布幕没试过`，在屏上核对新增范围。这一步不入库，不改正文，也不重新判类。
3. 输入 `/留下`，只认可屏上这个版本。输入 `/略过` 则丢弃本次补注并返回列表；它不会删除或认可既有草稿。`/退出` 或输入结束不会保存未提交的补注。

复核全程不请求模型，不改原始轨迹。留下后，复制「看库里的当前卡片」打开 `show`：先看 `approval_reading` 的措辞认可，再看 `candidate.status` 的卡片状态。`draft` 不会抹去已有的措辞认可；改了措辞也不会继承旧措辞的认可。要找当时认可的原版，请复制「看认可的准确版本」打开 `distill`。它会并列显示本场认可快照和未认可草稿，并指回拟写所在轮；不会把会后认可补写成当时说过的话。认可只表示你愿意留下这份措辞，不代表他人独立核验。

## 会话末提炼（`pipeline` / `distill`）

像平常一样 `discuss`：核对屏上措辞与范围，只对值得留的版本输入 `/认可`。正常收尾的统计只数资料库里的已认可版本和未认可草稿；「找回本场先前的拟写」读的是会话轨迹，那里可能还有没入库的轮次。同一张卡可以留有多个认可版本。以后直接复制收尾的「稍后看本场留下的版本和草稿」命令，不用先运行管线；如果手头只有本场轨迹，先用 `transcript` 回看，再复制它印出的清单命令（仍需打开原库）。`--text` 是人读的版式，不加则输出 JSON。

```sh
python3 -m dojo --db "$DB" distill --session "$SESSION" --text --trace "$TRACE"
```

清单按**本场认可的原版快照**读回，而不是借用同 ID 最近修订的措辞。没有认可的最后一版明标「未认可草稿」，不是结论；只有 `--session` 标签、没有认可凭据的卡也不会冒充结论。`[新]`／`[变体]`／`[重复]` 是与当前库的文字近邻关系，不是等价证明或合并指令。挑战同样只是提议。打开清单不写库、不发送网络请求。

**先选版本，再核对原话。** 从该条复制「回看本场原话」，只看与所选版本相邻、能核对到的拟稿轮和 `/认可`；如果缺拟稿记录，可能只定位到认可轮。要看上下文，用普通 `transcript "$TRACE"`。有对照卡时，先比较两边范围，再复制单独的旧版定位命令；找不到准确旧版就不拿别版替代。不带 `--trace` 仍能读账本快照。打开定位命令若提示轨迹已变，请回清单重新核对。

**留用、暂不采用都不必改库。** 如要记录收窄等关系，先核对双方原话及当前卡，再自行选择关系，用 `link --help` 查语法，显式运行 `link`。它会生成新卡版本来记关系，不改当时认可的版本，也不合并旧卡或增加来源。

**如需模型判类**（可试做法、经验陈述、待确认问题等），先明确选用已获准的 `DOJO_LLM_*` 线路，再单独运行一次管线。它会上传本场待处理的已认可卡片快照和到认可轮为止的部分用户原话（不会发送整份轨迹、主持人回复或旧库近邻）。不希望上传原话时，直接读清单即可：类型标作「讨论时拟写」，并说明没有后续的分类提议。即使已经有模型提议，清单也不会再发请求。

```sh
python3 -m dojo --db "$DB" pipeline --session "$SESSION" --classify --trace "$TRACE"
python3 -m dojo --db "$DB" distill --session "$SESSION" --text
```

分类单次最多发一批（最多 8 个版本，另有请求大小限制）。有 `deferred` 时可再次显式提交下一批；已判定的版本不重发。旧轨迹、`--no-trace` 或不匹配的轨迹可能缺少认可轮绑定：只展示能找回的账本快照，不补猜原话。清单把模型摘录和对应原话并排。候选类型与后续模型提议不一致时显示「判类待核」。分类事件会在本地库保留被引用的回合，每轮最多 1,600 字符。即使移走轨迹，这些上下文仍随原库保存。更早的分类记录仍可读，可以沿原轨迹核对缺少的上下文。模型无权修改任何已认可字段或增加来源。默认管线只运行本地近邻与挑战；`--dry-run` 也不发请求、不写事件。前置条件不满足或模型响应未通过核对时，分类不写入；本地近邻/挑战仍可写提议事件。

## 7–10 分钟：同一目标下的 B/C 人工复制

```sh
python3 -m dojo export --mode b --budget-chars 4000
python3 -m dojo export --mode c \
  --id seed-m01 --id seed-m02 --id seed-m03 --id seed-m04 --id life-01 \
  --budget-chars 6000
```

命令返回各自独立文件路径、实际字符数和来源候选 ID。B 不含 seed；C 只含这些显式 ID。查看对应 `.txt`，确认 `seed-m04` 的来源 ID/未核验状态在内，然后由操作者复制**其中一个完整文件**到独立答题模型上下文。B 与 C 使用相同的模拟目标文本。不要复制 actor 卡、裁判笔记或原始聊天；本 CLI 不会自动调用 LLM，也不会保存模型对话。

## 10–14 分钟：challenge、revision、撤销与恢复确认

```sh
python3 -m dojo challenge life-01 \
  --text '降低摩擦不是普适结论；当行为的价值来自练习本身时，这份难度应当保留'
python3 -m dojo revise life-01 \
  --statement '与目标无关的摩擦可以降低；若难度本身构成能力练习，则应当保留' \
  --reason '采纳挑战，把“降低摩擦”从普遍建议改成有条件的区分'
python3 -m dojo confirm life-01 --basis '修订后可作为检索候选；不表示为真'
python3 -m dojo revoke life-01 --reason '演练可逆撤销，不删除历史'
python3 -m dojo confirm life-01 --basis '再次确认讨论价值，不确认真实性'
python3 -m dojo show life-01 --history
python3 -m dojo abstain --id life-01 \
  --reason '不能从模拟案例判断降低摩擦是否真的有效' \
  --next-question '怎样判断一份难度是有意义的训练还是无谓摩擦？'
```

`challenge` 追加反例/疑点并使候选不可检索；`revise` 产生新版本并恢复为 draft。abstain 仅追加事件，不改候选版本，也不对真假投票。

**重复的请求不动版本，但一定留痕。** 同一条 `confirm` / `challenge` / `revise` 再发一遍，`version` 停在原处（所以管线「已处理到版本 N」不会失效），账本多一行 `<event>.repeat` 指回原来那条。但「重放」看的是**请求**，不是结果：把卡片改成它已经是的那句话、只为补一个新理由，措辞没变、版本也不变，却会记成一条普通的 `revise`，两个理由各占一行。请求是「理由 + 要去的措辞 + 你给的每个可选输入（范围、前提……）」；同一个理由改去另一句话、或同一个理由换了范围，也同样不是重放。每条 `revise` 行都记着 `to_statement`，`show --history` 里每条事件都带 `sequence`，所以 `repeat_of` 指到的那一行可以当场查出来，并且它要的必然是同一句话。用 `dojo events --id <卡>` 看这四行的区别，或跑 `docs/evidence/2026-11-27-repeat-safety/probe.py` 看前后读数。

## 14–15 分钟：记录一个困惑点并收尾

写下一条你自己遇到的操作困惑和耗时即可，不要把模拟结果写成效能结论。在**当前 shell 仍打开且 `WORK` 仍有值时**先检查路径，再选择清理；若变量已丢失、路径不符或想保留练习库，就不要执行删除命令：

```sh
printf 'WORK=%s\n' "${WORK:-<unset>}"
case "${WORK:-}" in
  "${TMPDIR:-/tmp}"/dojo-walkthrough.*)
    test -f "$WORK/dojo.sqlite3" || { echo 'database not found; refusing cleanup' >&2; exit 1; }
    rm -rf -- "$WORK"
    ;;
  *) echo 'WORK path was not verified; refusing cleanup' >&2; exit 1 ;;
esac
unset DOJO_DB DOJO_EXPORTS WORK
```

这段清理只在路径符合本指南的临时目录名前缀且其中存在本轮数据库时执行。用户可读的中文交互故事运行 `python3 -m dojo demo` 或 `sh scripts/demo.sh`；后台 JSON 存储回归走查（含 split、人工确认 merge/unmerge）改为 `sh scripts/storage-smoke.sh`。

## 回到已有探究：先读原记录，再决定怎么续谈

```sh
python3 -m dojo --db "$DB" stories
python3 -m dojo --db "$DB" stories "$STORY" --context
python3 -m dojo --db "$DB" inquire --resume "$STORY"
```

`DB` 是已有探究库的路径；`STORY` 取自第一条命令输出的 `story` 字段。前两条只读，不调用模型；第三条在你输入后向配置的模型端点发送上下文。`--context` 展示有事件号的部分续谈候选原文，不是全量账本，也不是对最终模型上下文的逐字预览。先按 `epistemic_status` 区分用户报告、模型解释与工具回执，再选择一件可核验的事；用户报告和模型说法都不等于独立证实。`recorded_at` 是 Dojo 记录时刻，不是原文里的外部时刻；`missing` 或 `invalid` 只说时刻不可用，原记录仍在。

`--context` 另有一块 `story_coverage`，回答接手时的第一个问题「下一步该核什么」：`unopened_search_sources` 列出**本故事实际检索回执里出现过、但账本里一次都没尝试读取**的 URL（最多四条，其余只给 `unopened_omitted` 计数）。已有 `read_source` 回执的 URL 不列为未读；回执本身不等于读到了正文。同一 URL 按去掉 `#片段` 后比较；只统计最近十二个工具回执内的成功检索。`latest_record_at` 只是本故事账本最新一条记录的写入时刻：它旧只说明这份视图旧，不说明外部正文旧。这个块**不**证明某 URL 现在可访问、正文没变、或与问题相关；没被列出来也不等于检索没返回过它。

可见正文之后同一 URL 的读取失败仍看 `source_read_failures`。如果本视图没展示正文，`source_read_failures_without_visible_body` 会列出同一故事最近十二条工具回执中，同时有成功检索条目和明确连接、格式或 HTTP 读取失败的 URL（最多两条，另报省略数）。跟着 `event`、`read_url`、`error_kind` 看失败依据；`listed_source.search_event` 和 URL 是检索依据，可能比失败更晚。两条各有账本时刻及 `recorded_at_status`；缺失或无效时不补时。拒绝执行、未获读取许可和没有尝试都不报成读取失败。比如格式不支持时先找可读官方文本，不要把它当成正文过期，也无需当作从未核过的检索条目重新开始。

回到已有调查，先看 `story_coverage.missing_independence.items` 的首行：`gap` 说缺什么，`have` 列所引事件号、URL 和状态，`next_check` 给下一步。比如唯一所引回执是 `source_type` 失败，先找可读的官方正文；如果已有一份可读材料，就去找独立形成且能核对同一说法的第二份材料。这个排序只看未被替代的知识提议所引的本故事账本事件，不限于本页恢复的候选正文。同一优先级内，待核对或有冲突的结论排在已记录支持比较的结论前面。最多五行，`omitted` 计全部省略结论；`omitted_pending` 计其中仍待核对或有冲突的结论；`omitted_unchecked` 只数其中**完全没有比较记录**（`open`）的条数；`omitted_events` 按事件号点名被省略的结论（最多四条，其余由 `omitted_events_hidden` 计数）。点名不等于看过它们，也不改变任何比较状态。模型续谈另有字符预算，省略计数覆盖两层截断，所列事件号保留原排序中最靠前的省略项。没有可排序提议时不出块。

这是核对顺序，不是真假判定。用户报告、模型说法、检索和计算回执不当作独立的来源正文。同一 URL（去掉 `#片段`）只算一份；`independent` / `two_distinct_materials` 只指提议引用了两份不同 URL 的正文，没有明确比较记录时仍是 `comparison_status: open`，要核对是否独立形成、是否各自支持。不能解析或归属当前故事的前提标 `unknown`，不冒充零依据。每行的 `freshness` 也是 `unknown`：失败回执、检索结果、入账时刻都不能证明外部材料新旧或有效性。

实际比较过两份正文后，再把结果明确记到这一版。以下命令**写入**指定的现有库，不联网、不调用模型；`PROPOSAL` 是 `conclusion_event`，`BASIS_READ` 是该版已作为依据引用的正文事件号，`OTHER_READ` 是另一份正文的回执号，不是 URL 或检索号。

```sh
python3 -m dojo --db "$DB" compare-sources "$STORY" "$PROPOSAL" "$BASIS_READ" "$OTHER_READ" \
  --relation supports_independently --reason '写明两份材料各自如何形成，以及在哪个范围内支持本版说法'
```

- `supports_independently` 要求本版已引两份成功读取、不同 URL（去片段）的同故事正文。再次用 `stories "$STORY" --context`，本版显示 `checked`，已满足的独立性核对不再派回（无其他缺口时 `next_check: null`）。这是记录比较者的判断，不是程序认证；修订后不继承已核状态。
- 发现反向正文时用 `--relation conflicts`，理由写明哪处不一致、需核哪项原始记录。另一回执可以是本版已经引用的正文，也可以是版本之后才读到、尚未引用的正文；记录进入现有复核队列。`contested` 优先显示冲突，`next_check` 指向两处回执，反向回执不计作第二处支撑。保留同一陈述且仍引用这两个回执的后版继续显示该冲突；换了陈述或比较对象，要就新内容重新核对。`comparisons` 最多展开最新四条，给出原目标版本、两回执号、通知号及比较理由。有冲突时只展示冲突比较；超出四条，`comparisons_omitted` 计其余冲突，`next_check` 仍先指向最新一对，再给省略条数及最近一条被省略冲突的通知号和两回执号。更早的只计数；未展开不是已解决。只有支持比较时，省略支持条目不会产生冲突提示。
- 普通复核请求和自由文本不会自动署上以上标签。没有 `comparison` 的旧库**不迁移也依然可读**，只读入口不会写库，也不需要重建。只对明确的合成故事在写入及读回时保留 `--synthetic`。

块里的两个计数容易被误读，说明一次：`decoded_events_in_this_view` 是这份视图解码出的事件总数（用户报告、模型答复、工具回执都算），**不是**读取次数；`visible_source_bodies` 才是本次候选里有可见正文的条数；`tool_receipts_in_this_view` 只数工具回执。这三个数各说各的，不要用一个去推另一个。

### 回查一条提议的比较状态（`--comparison`）

`--comparison` 是只读入口：给一个提议的事件号，看它当前那一版记了什么比较。不调用模型，不写库；读完库的字节不变。

仓库里只有账本的内容（`fixtures/comparison-ledger.json`），`*.sqlite3` 被忽略规则挡在版本库外，所以检出里没有现成的库文件。第一步先把它造出来：

```sh
LEDGER=$(mktemp -d)
python3 -B fixtures/build_comparison_ledger.py "$LEDGER/ledger.sqlite3"
```

这个构建器不联网、不调用模型，把场景说明写成一份合成探究库；目标路径已存在就拒绝，所以每次调用都写到一个新的空目录。下面每段都自带 `DB` 和 `STORY` 的取值，单独复制一段也能跑——代价是每段各造一份自己的库，互不共享。

```sh
LEDGER=$(mktemp -d)
DB=$LEDGER/ledger.sqlite3
python3 -B fixtures/build_comparison_ledger.py "$DB"
STORY=$(python3 -m dojo --db "$DB" stories --synthetic | python3 -c 'import json,sys;print(json.load(sys.stdin)[0]["story"])')
python3 -m dojo --db "$DB" stories "$STORY" --comparison 5 --synthetic
python3 -m dojo --db "$DB" stories "$STORY" --comparison 23 --synthetic
```

第一段输出里 `comparison_status` 是 `checked`，`comparisons` 的 `source_events` 是两处正文回执号（`[3, 4]`）；第二段的 #23 是 `open`——它引了两处正文，但**没有**比较记录，`next_check` 就是要核的那一件事。`checked` 只说明比较者记下了判断，不是程序认证；`open` 也不是「被证伪」，只是没有人记过这次核对。合成账本必须带 `--synthetic`，否则入口会说「没有可见的故事」——那不是库坏了，是默认视图不列合成记录。`$STORY` 这个 id 变化时不用改命令：上面那行 `python3 -c` 从 `stories --synthetic` 的 `story` 字段里取；`EVENT` 同理，取 `knowledge --synthetic` 的 `event` 字段。

```sh
LEDGER=$(mktemp -d)
DB=$LEDGER/ledger.sqlite3
python3 -B fixtures/build_comparison_ledger.py "$DB"
STORY=$(python3 -m dojo --db "$DB" stories --synthetic | python3 -c 'import json,sys;print(json.load(sys.stdin)[0]["story"])')
python3 -m dojo --db "$DB" stories "$STORY" --context --synthetic
```

`story_coverage.missing_independence.omitted_events` 点名的号（这份库里是 `[5, 15, 16, 17]`）都是本视图没展开的**当前**提议，能直接喂给 `--comparison`，不必先去读别的地方。留意 `items` 里显示的那几条全是 `open`，而省略的四个号全是 `checked`：被省略不是因为没核过，是视图放不下。

要看到「已替代」那一态，再造一份带后续版本的库：

```sh
LEDGER=$(mktemp -d)
DB=$LEDGER/revised.sqlite3
python3 -B fixtures/build_comparison_ledger.py "$DB" --revision
STORY=$(python3 -m dojo --db "$DB" stories --synthetic | python3 -c 'import json,sys;print(json.load(sys.stdin)[0]["story"])')
python3 -m dojo --db "$DB" stories "$STORY" --comparison 5 --synthetic || echo "（退出码 $? 是预期：这一版已被替代）"
python3 -m dojo --db "$DB" stories "$STORY" --comparison 27 --synthetic
```

旧版这回不返回比较对象（退出码 2），提示里写着当前版的号：`事件 #5 的结论已被事件 #27 替代……当前版请用 stories STORY --comparison 27 查看`。照它再读 `--comparison 27` 就是当前版，状态是 `open`（新版还没有比较记录）。这条版本链是 `Knowledge.accept(revises=…)` 写进去的，不是手塞的标记。

另外三种否定各说各的：不存在的事件号、属于其他故事的事件号、本故事里不是提议的事件号，各有自己的提示；读那句提示，别用退出码去猜是哪一种——三种都是 2，退出码分不开它们。`--comparison` 与 `--context`、`--report`、`--proposal` 互斥。

### 读回一条用户报告与一条提议（`--report`、`--proposal`）

`--comparison` 看的是「两份正文比过没有」。往回退一步还有两个只读入口：`--report` 读本故事一条用户报告的原话，`--proposal` 读一条提议的正文。两个都不调用模型，不写库。

```sh
LEDGER=$(mktemp -d)
DB=$LEDGER/read.sqlite3
python3 -B fixtures/build_comparison_ledger.py "$DB"
STORY=$(python3 -m dojo --db "$DB" stories --synthetic | python3 -c 'import json,sys;print(json.load(sys.stdin)[0]["story"])')
python3 -m dojo --db "$DB" stories "$STORY" --report 2 --synthetic
python3 -m dojo --db "$DB" stories "$STORY" --proposal 5 --synthetic
```

`--report 2` 返回那条报告本身：`text` 是原话，`epistemic_status` 是 `user_report_not_independently_verified`，`attribution` 说它属于当前故事，`story_scope` 是 `same_story`。这条回复不是独立证实，`recorded_at` 只是 Dojo 记录时刻。

`--proposal 5` 返回 `statement`、`state` 和 `report_review`。**这份仓内账本里 `report_review` 是空的，这是它的真实取值**：那一块列的是「本故事在这条提议之后又读到的用户报告」，本账本只有一条用户报告（#2），它比提议 #5 早，没有可列的。空只说明视图没有可列项，不是「核过没问题」，也不表示提议没引用任何报告。

`--proposal` 不返回提议引用了哪条报告——它没有 `premises` 字段。要看引用关系，得读 `knowledge` 列表里的 `proposal.premises`，再拿那条报告号去 `--report` 原文：

```sh
LEDGER=$(mktemp -d)
DB=$LEDGER/premises.sqlite3
python3 -B fixtures/build_comparison_ledger.py "$DB" >/dev/null
python3 -m dojo --db "$DB" knowledge --synthetic 2>/dev/null \
  | python3 -c 'import json,sys;print(json.dumps([x["proposal"]["premises"] for x in json.load(sys.stdin) if x["event"]==5][0], ensure_ascii=False))'
```

这一段列出 #5 的三条前提，头一条是 `{"event": 2, "quote": "希望后来者能看见原始报告", "role": "assumption"}`。`event: 2` 就是上一条命令读的那份报告，`quote` 在那份报告的 `text` 里逐字出现——两段命令可以互相核对，这就是「提议引用报告」在这个仓里唯一走得通的读法。`knowledge` 的那句「本库共 9 条知识提议记录……」写在标准错误，不混进 JSON；`2>/dev/null` 只是让终端干净，不影响结果。

没有 `replacement` 的入口都不跟版本链。`--report` 和 `--proposal` 只返回手里那一条：一条提议被替代后，`--proposal` 照旧返回它并标 `state: superseded`，要看当前版得按版本链走下一步，也就是上一节 `--comparison` 用的那种读法。

四个视图互斥：`--context`、`--report`、`--proposal`、`--comparison` 一次只能给一个，同时给两个会被参数解析挡下（退出码 2，给的是参数用法提示，不是本页讲的数据提示）。合成账本都要带 `--synthetic`，否则入口会说没有可见的记录——那不是库坏了。读不到时提示各不相同：报告不存在或不是用户报告，说「没有可见的用户报告」；提议不存在或不是知识提议，说「没有可见的知识提议」；属于其他故事另说。退出码都是 2，别用退出码去猜是哪一种。

### 从检出照着走一遍：模拟材料与真实材料各自证明什么

```sh
LEDGER=$(mktemp -d)
DB=$LEDGER/walk.sqlite3
python3 -B fixtures/build_comparison_ledger.py "$DB"
STORY=$(python3 -m dojo --db "$DB" stories --synthetic | python3 -c 'import json,sys;print(json.load(sys.stdin)[0]["story"])')
python3 -m dojo --db "$DB" stories --synthetic
python3 -m dojo --db "$DB" knowledge --synthetic
python3 -m dojo --db "$DB" stories "$STORY" --context --synthetic
python3 -B scripts/dao_life.py docs/dao/person-dojo --check
python3 -B scripts/dao_life.py docs/dao/person-dojo --compare docs/dao/demo-strangers --check
```

前三组（先造库那几行）用的是**模拟材料**：每条记录都标着 `synthetic`，全部由夹具作者编写。它们证明的是入口本身说得清：故事、提议、候选正文能分开，四态（核过／没核／被替代／不存在或不是提议）各有名字，省略项按事件号点名。它们**不**证明任何一条研究结论，也不证明独立来源真的独立——库里那两份「材料」是同一支笔写的场景。

后两条用的是**一个人的真实材料**（`docs/dao/person-dojo`）。它证明的是这张库能把出处、修订和未核都印在面上：`--check` 会印出 13 条道里 3 条落地有观察、10 条「未跑」，另有 9 条材料写不成道被拒收；`--compare` 与 `docs/dao/demo-strangers`（模拟材料）逐对比 13 对，共有张力 0 对，第二个来源带来的张力是「开始摩擦」。它证明的**不是**共识，也**不是**第二个人的道理：库里只有 1 个来源 id、晋升 0 条，「合写 13」是一个状态，不是赞许。`--check` 不写盘。

检出里 `docs/evidence/**` 下的 `*.sqlite3` 多是合成会话的账本。碰到不是探究库的 SQLite（例如 `docs/evidence/m1.7-caps/live-store.sqlite3`），`stories`、`questions`、`knowledge` 会说明它是另一种库、列表为空说的是「不是那种库」而不是「库里没有」；三个入口都只读，不改文件。