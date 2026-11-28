# 走一遍：他后来那一版，和原来那条之间的关系

2026-11-28，基线 `33cd298`。离线，干净检出即可重跑：模型是一个本地回环桩，脚本里的回答
**不是**真人会话，也**不是**模型判断。下面每条命令都在仓库根目录执行。

## 0. 一步看到全貌

```bash
python3 docs/evidence/2026-11-28-derivation-edge/verify.py
```

它按顺序走：一场讨论 → 带着那张卡再谈、停在没人认可的另一版 → 再一场当场认可的新一版 →
过几天用记得的话去找 → 手打的边与真讨论的边对照 → 300/600 张卡的库上检索 → 机器输出核对。
结尾是读数，退出码 0 表示全部成立。

## 1. 自己看着屏幕上发生什么

先用一个端点开一场（没有真端点时任何 `DOJO_LLM_*` 指向的回环服务都可以；这一片本身不需要
端点，读数脚本自带桩）：

```bash
export DOJO_LLM_BASE_URL=http://127.0.0.1:4000/v1
export DOJO_LLM_MODEL=<你的模型名>
python3 -m dojo --db /tmp/lineage.sqlite3 discuss
#   聊到一句你认可的带边界的话，然后回答四件事，结束输入。
```

记下回执里那张卡的 ID，然后把它带进新的一场，并在这一场里**说出一个反例**，让主持人改一版——
**不要**认可那一版（直接结束输入）：

```bash
python3 -m dojo --db /tmp/lineage.sqlite3 discuss --card <第一张卡的 ID>
```

现在搜你记得的那句话：

```bash
python3 -m dojo --db /tmp/lineage.sqlite3 search '<你记得的几个词>'
```

屏幕上应该看到两件事：

- 旧卡那一条下面：「后来有一场带着这条继续谈，写下了另一版（不是替换，也不说明变窄还是变宽；
  两版都在库里）」，点名新卡的 id、它自己的句子和它自己的认可状态；
- 新卡那一条：「这条的来源：这一版是在一场带着它的讨论里写下的 <旧卡 id>（库里记下的边，不表示
  变窄或变宽）」，以及一条能直接粘的 `show` 命令。

再把新卡带进第三场，开场第一屏会重复同一句话——屏幕和发给模型的资料说的是同一件事。

## 2. 对照：库里原本就有的手打边

老版本的 `link` 能写 `derived_from`。这样的库不需要重建：读它的时候屏幕不再声称有讨论。

```bash
python3 -m dojo --db /path/to/old.sqlite3 search '<那条边指向的那张卡里的词>'
#   库里记着与这条有关的关系（不是一场讨论留下的，也不表示谁写下了谁）：
```

现在的 `link` 会拒绝这个类型：

```bash
python3 -m dojo --db /tmp/lineage.sqlite3 link <A> --relation derived_from --target <B> --reason '试一试'
#   error: argument --relation: invalid choice: 'derived_from' ...
```

## 3. 严格的版本

```bash
python3 docs/evidence/2026-11-28-derivation-edge/verify.py   # 39 项读数
python3 docs/evidence/2026-11-28-derivation-edge/redarm.py   # 11 条红臂
python3 -B -m unittest tests.test_derivation_edge             # 13 项
python3 -B -m unittest discover -s tests -q                  # 全量（1388 项）
```

`redarm.py` 会先确认 `verify.py` 是绿的，再逐条还原一处行为，要求**指定的那一项**变红。它自己也会
拒绝不唯一的锚点：一条臂找不到唯一的替换位置时算「不成立」，而不是悄悄绿着。

## 4. 主管的两份复现

- 规模：`/var/tmp/dojo-search-lineage-scale.WmglSP`——600 张没有关系的卡上普通 `search`。
  现在正确的结果是每份库只读一次候选表；`verify.py` 的 D4 段就是这件事的常驻读数。
- 来路：`/var/tmp/dojo-lineage-provenance.3dtLjtD6`——两张手写并确认的卡，手动连起来。
  `candidate.sqlite` 直接用这一版读，屏幕印「库里记着与这条有关的关系」，不再说这是一场讨论。
