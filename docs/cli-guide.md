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
python3 -m dojo confirm life-01 \
  --basis '表述足够精确，值得在新讨论检索；不是事实确认' \
  --session life-anon-1
python3 -m dojo search '摩擦 持续 行为'
```

逐条读命中的 `matched_terms`、条件、来源、unknowns 和 contradictions。分数只计算不同查询词命中数，不代表可信度。草稿/撤回状态不返回；不匹配就接受空结果，不要换词直到“搜出答案”。

`search` 与 `broadcast` 是同一次词汇检索的两个出口，差别只在要不要跨会话材料：`search` 返回所有可讨论命中，`broadcast` 额外拒收两类卡，并把拒收原因列在 `suppressed` 里而不静默丢弃——单一会话来源的卡（写它的那个会话是它唯一的独立性来源），以及 `--session` 指名的那个会话自己写的卡（一场会话不把自己的话当别人的佐证）。每条命中带 `independence`：`independence_groups` 列出了几个互不相同的独立性来源，`independent` 表示是否至少两个。这些只做报告，不参与排序：

```sh
python3 -m dojo broadcast '摩擦 持续 行为' --session life-anon-1
python3 -m dojo export --mode c --id life-01 --budget-chars 6000   # 单一会话来源的卡会被拒
```

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
