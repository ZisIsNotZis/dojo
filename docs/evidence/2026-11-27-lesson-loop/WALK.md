# 照着走：一句话怎么被一次反例改窄，又怎么回到后来的读者手里

这是一段可以**整段粘贴**的运行。不需要网络、不需要模型、不需要装任何东西。
它建一个一次性的库，走完「接受 → 质疑 → 改主意 → 再接受 → 后来的行动」，
并且在**中间那两步**停下来，让你亲眼看到那时候检索是空的。

```sh
export DEMO=$(mktemp -d)
export DOJO_DB=$DEMO/lesson.sqlite3
export DOJO_EXPORTS=$DEMO/exports
cd "$(git rev-parse --show-toplevel)"     # 仓库根目录
```

## 1. 一条做法，他认可了

```sh
python3 -m dojo add --id c1 --kind abstract_idea \
  --statement '持续检查交给系统自己跑，人只在想推翻的时候回来。' \
  --scope '他已经抽身的时候' \
  --premise '系统能自己跑检查' \
  --alternative '把检查留给人' \
  --contradiction '检查必须发生在世界里时' \
  --unknown '他会不会来看回执' \
  --source-json '{"id":"s1","type":"claimed_firsthand","verification":"unverified","independence_group":"gA","claim":"他这样做过两次","scope_note":"两次都在同一团队"}' \
  --session sess-A

python3 -m dojo confirm c1 --basis '他在会话里认可了这句；不表示为真' --session sess-A

# 现在它能被检索到
python3 -m dojo search '持续检查 系统 自己 跑'
```

`add` 的 `--statement` 与 `--kind` 是必填；`--scope` 等五个都是可重复的 `--flag`，
`--source-json` 里 `type` 只能是 `claimed_firsthand` / `abstract_reasoning` /
`artifact_observation` / `secondhand_report` / `model_generated` /
`synthetic_roleplay` / `unknown`。少给必填项时命令会直接告诉你要补哪个，不会静默写入。

## 2. 后来他提出一个反例

```sh
python3 -m dojo challenge c1 --text '第三次在同一团队反而更糟：检查结果他根本没看。'

# ★ 此刻检索是空的。这是设计，不是 bug，下一节会讲清这条界限。
python3 -m dojo search '持续检查 系统 自己 跑'
```

## 3. 他改了主意，并说了为什么

```sh
python3 -m dojo revise c1 \
  --statement '持续检查交给系统自己跑，但只在检查结果会打断他时才叫醒他。' \
  --reason '原来那句没写清楚什么时候该叫醒他，所以第三次更糟。'

# ★ 改写本身不会让它回到检索里：改完是 draft，还没有人认可这句。仍然是空的。
python3 -m dojo search '持续检查 系统 自己 跑'
```

## 4. 他回来，再认可一次

```sh
python3 -m dojo confirm c1 --basis '新一场里他接受了改写后的这句' --session sess-C
```

## 5. 现在看后来的读者拿到的

```sh
# 检索行里带着 revision_basis
python3 -m dojo search '持续检查 系统 自己 跑'

# show 把它放在 candidate 旁边（candidate 本体仍是存储状态，逐字未改）
python3 -m dojo show c1

# 冻结给别人的提示词里，是两行散文，并明说旧句已被取代
python3 -m dojo export --mode c --id c1
```

导出的尾段会多出这两行：

```
revision_left_wording: 持续检查交给系统自己跑，人只在想推翻的时候回来。 | 这句是他后来改掉的，不是现在的说法。
revision_reason: 原来那句没写清楚什么时候该叫醒他，所以第三次更糟。 | 他改主意的理由，原话；不是对现在这句的赞同，也不证明它成立。
```

## 这条界限要说清楚

**第 2、3 步里检索是空的，第 4 步才回来。** 这不是本片引入的行为：一张卡只要不是
`discussable`、也没有「当前这句措辞」的接受记录，三条读者出口就都不交出它。
`challenge` 会把它打到 `challenged`，`revise` 会把它打回 `draft` 并撤销接受标记。

所以整条链的真实条件是：

> **这套东西能替他记住「为什么改」，但改完之后要有人再认可一次，那句才重新交给别人。**

产品方向里有一条是「他抽身之后网络自己跑」。在这一点上本片没有推进，也不假装推进了：
如果他不再回来认可，理由只留在账本里，`show --history` 看得到，别人拿不到。
`tests/test_lesson_loop.py::test_a_challenged_card_is_still_not_handed_to_a_later_reader`
把这个事实钉住了。

要一直跑到干净收尾：

```sh
rm -rf "$DEMO"
```
