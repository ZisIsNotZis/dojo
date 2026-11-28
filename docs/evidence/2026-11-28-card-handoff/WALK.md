# 照着走：一句被反例改窄的话，怎么进入后来的一场会话

这是一段可以整段粘贴的运行。不需要网络、不需要模型、不需要装任何东西。
它建一个一次性的库，走完「接受 → 质疑 → 改主意 → 交给新的一场」，
并且把**新那一场真正收到的东西**打出来。下面标日期的屏幕与读数是当时记录。
`verify.py` 验证原样重复旧卡时，先展示待核对版本，再单独输入 `/认可`，而不是由回环桩代按认可。

```sh
export DEMO=$(mktemp -d)
export DOJO_DB=$DEMO/handoff.sqlite3
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
```

## 2. 后来一个反例推翻它，他改窄了这句，并说了为什么

```sh
python3 -m dojo challenge c1 --text '第三次在同一团队反而更糟：检查结果他根本没看。'
python3 -m dojo revise c1 \
  --statement '持续检查交给系统自己跑，但只在检查结果会打断他时才叫醒他。' \
  --reason '原来那句没写清楚什么时候该叫醒他，所以第三次更糟。'
python3 -m dojo confirm c1 --basis '新一场里他接受了改写后的这句' --session sess-C
```

## 3. 打错 id：本地说本地的话

```sh
env -u DOJO_LLM_BASE_URL python3 -m dojo discuss --card c9 </dev/null
```

```
无法开始讨论：这张卡读不出来（candidate not found: c9）；未发送网络请求。
```

这一条是走真实入口时发现的：以前这里报的是「未配置 DOJO_LLM_BASE_URL」，
把打错卡名的人送去查端点设置。

## 4. 交对的卡

端点仍然没配，所以对话本身开不起来——**但卡已经先读出来了**：

```sh
env -u DOJO_LLM_BASE_URL python3 -m dojo discuss --card c1 </dev/null
```

```
无法启动讨论：未配置 DOJO_LLM_BASE_URL，未发送网络请求。
```

要看到这一步之后的那一屏，需要端点；`docs/evidence/2026-11-28-card-handoff/verify.py`
用离线假客户端把它整段打出来，不需要任何网络：

```
python3 docs/evidence/2026-11-28-card-handoff/verify.py
```

那一屏是：

```
这一场带上了一张以前写下的卡 d-…，状态：可讨论（有人认可它值得讨论，不表示为真）。
  「持续检查交给系统自己跑，但只在检查结果会打断他时才叫醒他。」
  它比更早那句窄：原来是「持续检查交给系统自己跑，人只在想推翻的时候回来。」
  他后来改主意时说的是：「原来那句没写清楚什么时候该叫醒他，所以第三次更糟。」
  它有 1 条来源记录：他自称亲历、未经核验。这是记录条数，不是人数；核验状态如上，不代表这句是真的。
  这场里它是资料，不是你说过的话。你若只是重复它，记录不会把本场算成第二个独立来源；
  你若推翻或改窄它，那会是本场新说的话。
```

同一张卡，同一个理由，同时也在模型的请求里（`verify.py` 的 C7 读的是真实 payload）。

## 4b. 真的把这一场跑起来（不打模型，打本机回环端点）

上面几节靠 `verify.py` 里的进程内假客户端。**那不等于真实入口**：这一片最早就是这样
漏掉了一个崩溃——discuss 分支持有的 store 是 `None`，`store.show` 当场 `AttributeError`，
端点收到 0 个请求。下面这一条跑的是 `python3 -m dojo`，也就是人真正敲的命令：

```sh
python3 .scratch/3363/repro_card_crash.py .
```

它会自己起一个 loopback 端点、自己建库、跑两次（错卡号 / 对卡号），并打印端点实际收到
几个请求、请求里有没有旧措辞、新措辞、理由和来源。2026-11-28 的读数：

```
=== 打错卡号 ===
exit=2 requests=0
无法开始讨论：这张卡读不出来（candidate not found: c9）；未发送网络请求。

=== 对卡号 + 回环端点 ===
exit=0 requests=1
  旧措辞: True
  新措辞: True
  理由:   True
```

`verify.py` 的 C14–C18 把同一条路径收成了证据：它删掉 store 就会红（臂 A）。

## 4c. 把同一场**续跑**起来，中途还改一张卡

这是监督者退回的第二条：第一半好好的，`--resume` 之后端点收到了回答，但请求里
旧措辞、新措辞、理由、来源**四件全没了**。轨迹里明明写着，`_load_resume_trace`
校验完 `handout` 行之后把它丢了。

要 `cp -a` 一份库才能手动看，这条脚本自己做完（建库 → 第一半 → 改卡 → 续跑）：

```sh
python3 .scratch/3363/probe_resume_handout.py .
```

2026-11-28 的读数（`1413770` → 本片；右列为探针实际打印）：

```
第一半请求：旧措辞       True      True
第一半请求：新措辞       True      True
第一半请求：理由         True      True
第一半请求：来源         False     True
续跑请求：旧措辞         False     True
续跑请求：新措辞         False     True
续跑请求：理由           False     True
续跑请求：来源           False     True
续跑请求：混进库里更新的一版 False   False
读记录行数（续跑前, 后）  (1, 1)    (1, 1)
```

三件要看清：

1. **续跑那四行全由 `False` 变 `True`。** 这就是监督者退回的那一条。
2. **第一半的“来源”也是 `False`**，因为 `1413770` 里来源还没出库；那是同一片里另
   一条修复，所以这一列一起变了，不是探针的噪声。
3. **读记录两边都是 1 行。** 改前续跑根本没拿到卡，所以也没写第二行；改后拿到了卡，
   所以需要那条 `resume_state is None` 的闸才不写第二行。臂 E 把它拿掉，就会变成
   `['discuss-…', 'discuss-…']` 两行同一个会话 —— C22b 红。

中间那条「混进库里更新的一版」是关键：续跑不应该去 `store.show`。一场对话讲的是
一句具体的话；续跑时把库里**更新**的那一版递给模型，这一场到底在说哪句就无从回答了。
`verify.py` 的 C19–C22b 把这几件都收成了证据；`.scratch/3363/redarm_resume.py` 的
七条臂每一条都能让它们变红。

## 5. 后来的人读这张卡

```sh
python3 -m dojo show c1
```

`candidate` 里是现在这句；`candidate` **旁边**是：

```
revision_basis:
  reason: 原来那句没写清楚什么时候该叫醒他，所以第三次更糟。
  left_wording: 持续检查交给系统自己跑，人只在想推翻的时候回来。
```

## 6. 记录里能查到这一场被交付过

```sh
python3 -m dojo reads --id c1
```

会有一行 `surface=discuss`，`reader_session` 是那一场的会话 id。
回声门读的就是这一行：**被交过这张卡的会话再说一遍它，不算第二个独立来源**。
