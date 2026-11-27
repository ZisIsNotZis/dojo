# 走一遍：屏幕上的命令，复制出来能不能用

2026-11-28，任务 #3419 第一段。监督者一共报了四次，后三次都在我上一版的修法之后：

> 我用 `--db` 指定不同的库开场时，照抄退出或回看里的草稿命令，仍跑去默认库并找不到。

> 在 A 目录以 `DOJO_DB=chosen.sqlite3` 启动讨论，退场提示没有 `--db`。我保持同一个环境
> 变量，换到 B 目录粘贴那行，结果退出 2 并在 B 新建了空数据库。

> 用一次性的绝对 `DOJO_DB` 启动，复制提示到同一 HOME 的普通终端，提示仍省略库，运行时
> 打开默认空库。

> 从默认库谈完，粘贴到平常用另一个库的终端：旧式短命令还是指错了库，续谈却以 0 退出。

四次都在真实 CLI 上先复现再改，探针是
`.scratch/3419/probe_{draft_cmds,relative_env,absolute_env,default_to_custom}.py`。
第三次的复现：

```
带 DOJO_DB=/var/tmp/…/chosen.sqlite3 开场，退出 0
  屏幕：python3 -m dojo show d-bb60f66bfc54          ← 没写库，指望那个环境变量
换一个不带 DOJO_DB 的终端（同一个 HOME、同一个目录），原样粘贴：
  exit=2 打开草稿=False
    error: candidate not found: d-bb60f66bfc54
  新终端里新建了默认库：True
```

前三次我都只把刚报的那个例子改对，所以还有下一个。第四次最严重：`--resume` 不报错，
它把这一场的后半段写进了那个另一个库。监督者的判断是对的：不要再逐例打补丁。

## 一条规则

**问题问错了。** 我一直在问「一条不带 `--db` 的命令现在会不会读到同一个文件」。这个答案
取决于提问时的环境——目录（相对 `$DOJO_DB`）和终端（一次性 `$DOJO_DB`）。一条印出去的
命令不可能带着这些条件。

第四次报告之后，连默认库的短形式也去掉了。短形式的含义是「默认库」，而「默认库」恰恰
是各个终端不同意的那件事。现在的规则一句，没有例外：

| 库是怎么来的 | 屏幕印什么 |
|---|---|
| 没指定，用默认位置 | `python3 -m dojo --db <那个位置的绝对路径> show <id>` |
| `--db <路径>`，相对或绝对 | `python3 -m dojo --db <绝对路径> show <id>` |
| `DOJO_DB=<路径>`，相对或绝对 | `python3 -m dojo --db <绝对路径> show <id>` |

同一类还有第二面：`DOJO_SESSIONS=sessions` 也是相对的，所以印出来的轨迹路径一律绝对。
第四次那个最严重：`--resume` 以 0 退出，把这一场的后半段写进了另一个库。

库路径仍然不写进轨迹（监督者第一条约束）：轨迹记他说了什么，路径只活在命令行上。

## 完整输出

从修好之后的工作树上重跑。库路径里故意带一个空格、一个单引号、一个 `$` 和一个反引号。

```
$ python3 docs/evidence/2026-11-28-printed-commands/verify.py
库：/var/tmp/…/a library's $HOME `x`/my dojo's.sqlite3
默认库（应当一直不存在）：/var/tmp/…/home/.local/share/dojo/dojo.sqlite3

A0. 四件问完之后的回执
  成立  A0a 四件问完后印出了回执
        主持人> 四件问完了：你在 情境、张力、代价 上说了原话；你在 失效 上说没有碰到过这样的例子（原话收下了；这一件没有材料，也不等于这条做法不会失效）。这些原话留在本场记录里，没有写进卡片。答没答到点上，这句不判——判断留给你。卡片是提问前
  成立  A0b 回执点名了回看命令
        python3 -m dojo --db '/var/tmp/…/a library'\''s $HOME `x`/my dojo'\''s.sqlite3' transcript '/var/tmp/…/a library'\''s $HOME `x`/sessions/discuss-3e64f3870bda452ea57959e638b7f992.jsonl'
  成立  A0c 回执里的回看命令带着这一场的库
        python3 -m dojo --db '/var/tmp/…/a library'\''s $HOME `x`/my dojo'\''s.sqlite3' transcript '/var/tmp/…/a library'\''s $HOME `x`/sessions/discuss-3e64f3870bda452ea57959e638b7f992.jsonl'
  成立  A0d 粘贴回执里的命令能读回原话
        exit=0

A. 开轨迹的一场（早退，留草稿）
  成立  A1 退出屏幕点名了打开草稿的命令
        python3 -m dojo --db '/var/tmp/…/a library'\''s $HOME `x`/my dojo'\''s.sqlite3' show d-2947240c5051
  成立  A2 那条命令带着这一场的库，且能被 shell 分成一个参数
        库参数：/var/tmp/…/a library's $HOME `x`/my dojo's.sqlite3
  成立  A3 原样粘贴能打开草稿
        exit=0
  成立  A4 粘贴后默认库仍不存在
        默认库：不存在
  成立  A5 退出屏幕点名了回看命令，且带着同一个库
        python3 -m dojo --db '/var/tmp/…/a library'\''s $HOME `x`/my dojo'\''s.sqlite3' transcript '/var/tmp/…/a library'\''s $HOME `x`/sessions/discuss-00ce9943398d49a1b248be1cbd3d9860.jsonl'
  成立  A6 粘贴回看命令能读回原话
        exit=0
  成立  A7 回看里的卡片命令也带着那个库
        python3 -m dojo --db '/var/tmp/…/a library'\''s $HOME `x`/my dojo'\''s.sqlite3' show d-2947240c5051
  成立  A8 回看里的卡片命令粘贴后打开草稿
        exit=0
  成立  A9 接着谈的命令也带着那个库
        python3 -m dojo --db '/var/tmp/…/a library'\''s $HOME `x`/my dojo'\''s.sqlite3' discuss --resume '/var/tmp/…/a library'\''s $HOME `x`/sessions/discuss-00ce9943398d49a1b248be1cbd3d9860.jsonl'
  成立  A10 库路径没有写进原话记录
        轨迹 discuss-00ce9943398d49a1b248be1cbd3d9860.jsonl：3039 字节
  成立  A11 全程默认库仍不存在
        默认库：不存在

B. 用 --no-trace 退出的一场
  成立  B1 不开轨迹时退出屏幕仍点名打开草稿的命令
        python3 -m dojo --db '/var/tmp/…/a library'\''s $HOME `x`/my dojo'\''s.sqlite3' show d-2947240c5051
  成立  B2 那条命令带着这一场的库，且能被 shell 分成一个参数
        库参数：/var/tmp/…/a library's $HOME `x`/my dojo's.sqlite3
  成立  B3 原样粘贴能打开草稿
        exit=0
  成立  B4 不开轨迹时不点名回看命令
        本场没有记录可看
  成立  B5 默认库仍不存在
        默认库：不存在

B2. 相对 DOJO_DB，换一个目录再粘贴
  成立  B2a 相对 DOJO_DB 下也能开场
        exit=0
  成立  B2b 退出命令写的是绝对路径（不是靠相对 DOJO_DB）
        python3 -m dojo --db /var/tmp/…/relative/A/chosen.sqlite3 show d-91d546382c9a
  成立  B2c 换到另一个目录粘贴，仍打开那个草稿
        exit=0
  成立  B2d 换目录粘贴没有在那里新建库
        /var/tmp/…/relative/B/chosen.sqlite3
  成立  B2e 回看也在另一个目录里可用
        exit=0
  成立  B2f 续谈命令带着同一个库
        python3 -m dojo --db /var/tmp/…/relative/A/chosen.sqlite3 discuss --resume /var/tmp/…/relative/A/sessions/discuss-4fda06bb1f7c4fd9acdaf88a009f0243.jsonl

B3. 相对 DOJO_SESSIONS，轨迹路径也要经得起换目录
  成立  B3a 相对 DOJO_SESSIONS 下也点名了回看命令
        python3 -m dojo --db /var/tmp/…/relative-sessions/A/dojo.sqlite3 transcript /var/tmp/…/relative-sessions/A/sessions/discuss-cb444daaea844da085fc9c73c1719c85.jsonl
  成立  B3b0 回看命令能被 shell 分成参数
        python3 -m dojo --db /var/tmp/…/relative-sessions/A/dojo.sqlite3 transcript /var/tmp/…/relative-sessions/A/sessions/discuss-cb444daaea844da085fc9c73c1719c85.jsonl
  成立  B3b 回看命令里的轨迹路径是绝对路径
        /var/tmp/…/relative-sessions/A/sessions/discuss-cb444daaea844da085fc9c73c1719c85.jsonl
  成立  B3c 换一个目录粘贴回看，仍能读到这一场
        exit=0

B4. 一次性的 DOJO_DB，换一个没有这个变量的终端
  成立  B4a 一次性 DOJO_DB 下也能开场
        exit=0
  成立  B4b 屏幕上的命令没靠那个变量
        python3 -m dojo --db /var/tmp/…/fresh-shell/chosen.sqlite3 show d-34cb1027787c
  成立  B4c 在没有那个变量的终端里粘贴，仍打开草稿
        exit=0
  成立  B4d 新终端里没有新建默认库
        /var/tmp/…/fresh-shell/home/.local/share/dojo/dojo.sqlite3

C. 三种选库方式，一条规则
  成立  C1 不用 --db、没设 DOJO_DB：印短形式
        python3 -m dojo show c1
  成立  C1b DOJO_DB 恰好指向这个库，也照样印 --db
        python3 -m dojo --db '/var/tmp/…/a library'\''s $HOME `x`/my dojo'\''s.sqlite3' show c1
  成立  C1c DOJO_DB 指向的是默认库时也不看环境
        python3 -m dojo show c1
  成立  C1d 显式库：印绝对路径
        python3 -m dojo --db /var/tmp/…/elsewhere/other.sqlite3 show c1
  成立  C2 带 '/var/tmp/praxi' 的路径是一个参数
        参数个数：1（原字："/var/tmp/…/a library's $HOME `x`/my dojo's.sqlite3"）
  成立  C2 带 'a b' 的路径是一个参数
        参数个数：1（原字：'a b'）
  成立  C2 带 "it's" 的路径是一个参数
        参数个数：1（原字："it's"）
  成立  C2 带 '$HOME/x' 的路径是一个参数
        参数个数：1（原字：'$HOME/x'）
  成立  C2 带 'back`tick`' 的路径是一个参数
        参数个数：1（原字：'back`tick`'）
  成立  C2 带 'both " and \' p 的路径是一个参数
        参数个数：1（原字：'both " and \' plus $x'）
  成立  C2 带 'trailing space' 的路径是一个参数
        参数个数：1（原字：'trailing space '）

全部成立（45 项）。
```

路径用 `…` 省了临时目录名，其余逐字未改；每次运行目录不同，草稿 ID 和会话 ID 也跟着变。

## 一个渲染器

之前有四处各自拼命令：`discuss` 用 `shlex.quote`，`storage` 用自己写的「有空格就加双
引号」，`transcript` 又是 `shlex.quote`，`demo` 直接 f-string 拼。四种拼法，其中两种是错的。
现在在 `dojo/commands.py` 一处：安全字节不加引号；只有空格和单引号加双引号（最常见也最好
读）；其余单引号加 `'\''`。`!` 也算不安全，因为交互式 bash 会做历史展开。

`quote()` 与 `shlex.quote` 有一处可逆差别：`shlex.quote` 给 `a b` 印 `'a b'`，这里印
`"a b"`。两种都对，选后者是因为屏幕上一眼看出是路径，而不是一个被引号包住的怪东西。

## 红臂

`python3 docs/evidence/2026-11-28-printed-commands/redarm.py`，九条，每条只改一处，全部变红，
且红的是它该红的那些项：

| 放回去的旧行为 | 红了几项 |
|---|---|
| 退出的 `show` 不带库（第一次报告） | 13 |
| 四件问完那行回执不带库 | 1（A0c） |
| 早退时退出屏幕的 `transcript` 不带库 | 6 |
| 回看不把库传给卡片命令 | 4 |
| 把库路径写进轨迹 | 1（A10） |
| 路径不加引号 | 16 |
| 默认库也带 `--db` | 2（C1 C1c） |
| 用环境变量判断「已经对了」（第二、三次报告） | 8（B2b–B2d B4b–B4d C1b C1c） |
| 回看印相对 `$DOJO_SESSIONS` 路径 | 2（B3b B3c） |

## 自己走过的坑

- 探针假通过：第一版探针自己手写了一条 `python3 -m dojo transcript ...` 去粘贴，而不是粘贴
  屏幕上印的那一行。屏幕那行当时还没带 `--db`，正是缺陷所在，被探针的写法盖住了。
- 证据里的 C1 第一版写的是 `exit in (0, 2)`，两个结果都算过 —— 等于没测；C1b 拿原始路径去
  `in` 一条已经加了引号的行，永远不成立。
- README 示例被真跑：`test_readme_views` 执行每一块 ```` ```sh ````，我那段指着
  `/home/me/...` 的例子因此红了。改成 `mktemp -d` 的真块，录下来的屏幕放进 ```` ```text ````。
- 两条红臂其实是绿的。它们让我发现两件真事：`transcript.command()` 改完后已经没人调用，是
  一处会再次走偏的第二渲染（删了）；「四件问完」那行回执从来没被量过，因为 A 段总是早退。
- 一条臂只靠抛异常变红：去掉引号后 `shlex.split` 炸掉整个 verify 进程，后面所有检查都没跑。
  一条无法被 shell 分开的命令应该是一条有名字的不成立，不是 traceback。
- 同样的错又犯一次：写「看环境变量」那条臂时我只换了判断语句，忘了那个文件已不再 `import
  os`，臂靠 `NameError` 变红。崩溃不是证据。补上 import 之后它红了 8 项有名字的检查。
- 同一次运行里两条检查都叫 `B3b`；已拆成 B3b0 / B3b。
