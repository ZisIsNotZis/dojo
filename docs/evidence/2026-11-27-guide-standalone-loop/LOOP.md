# 一句话从「写了」到「真的成立」：指南里那句「单独复制一段也能跑」

范围：`docs/cli-guide.md` 的 `--comparison` 一小节，和守它的 `tests/test_doc_cli_flags.py`。
基线：`6aac311`（公开候选）。日期：2026-11-27。全部离线，不调用模型，不联网。

这份记录按真实发生顺序写：**先有的说法**、**追问**、**独立核查**、**改法**，最后是**同一个毛病在别处怎么用**。
每条断言后面都有能重跑的命令或文件，读的人不必相信我。

---

## 1. 最初的说法（`895a0f3` 写进去的）

指南在造合成账本那一段之后写：

> 这个构建器不联网、不调用模型，把场景说明写成一份合成探究库；目标路径已存在就拒绝，换个名字或先删掉。**下面每段都自带 `DB` 和 `STORY` 的取值，单独复制一段也能跑。**

同一句话出现在 `e4af6c6`/`1af799f` 的指南里吗？**没有**——那两个提交的 `docs/cli-guide.md` 里 `dojo-ledger` 出现 0 次，这一小节和这句承诺是随 `895a0f3` 才进来的：

```sh
git show 1af799f:docs/cli-guide.md | grep -c 'dojo-ledger'   # 0
git show 895a0f3:docs/cli-guide.md | grep -c '单独复制一段也能跑'  # 1
git log --oneline -S'单独复制一段也能跑' -- docs/cli-guide.md
```

所以这是我方血统的错，不是继承来的、也不是从别处带进来的。

## 2. 当时的验收为什么看不见它

`tests/test_doc_cli_flags.py` 在跑指南的块之前，把正文里的 `/tmp/dojo-ledger` **改写成测试自己的临时目录**：

```python
LEDGER_ROOT = '/tmp/dojo-ledger'
def tidy(self, block):
    return '\n'.join(block).replace(LEDGER_ROOT, str(self.work / 'dojo-ledger'))
```

两个后果，都是「测试绿、读者红」：

1. **固定路径的毛病被门自己抹掉。** 门每次都从一个干净的临时目录开始，所以「同机第二次就 `FileExistsError`」这一条永远不会在门里发生。
2. **页序当作读者页序。** 门按页序把所有块跑在一个 shell 里，于是「造库」块先跑过了，后面 `DB=/tmp/...` 的块当然能读。**「单独复制一段」这个承诺从来没有被单独测过。**

同一个文件的注释自己写着这条教训（`test_every_printed_library_path_is_redirectable`）：

> A route that only runs on a clean host is not a route.

`#3286` 把这条教训用在了两个 README 上（改成 `mktemp -d` + `DOJO_DB`，两次都是 rc 0），**没有用到指南门上**。

## 3. 追问：那就照读者那样跑一次

不重写正文，不注入参数，干净 `HOME`/`TMPDIR`，每个块单独一个 shell：

```sh
python3 docs/evidence/2026-11-27-guide-standalone-loop/replay.py <repo-root>
```

在 `6aac311` 上的读数（`--json` 里有逐块明细）：

| 块 | 行 | `alone` | `again` | 第一条命令 | stderr |
|---|---|---|---|---|---|
| 12 | 190 | 0 | **1** | `build_comparison_ledger.py /tmp/dojo-ledger.sqlite3` | `FileExistsError: … 已存在` |
| 13 | 196 | **2** | 2 | `DB=/tmp/dojo-ledger.sqlite3` | `error: --comparison 需要 STORY` |
| 14 | 205 | **2** | 2 | `DB=/tmp/dojo-ledger.sqlite3` | `error: --context 需要 STORY` |
| 17 | 245 | **1** | 1 | `--db "$DB" knowledge …` | `json.decoder.JSONDecodeError` |

四处红，各有各的原因，而**它们看起来是同一个原因被人为藏起来了**：

- 13/14 的 `STORY=$(… | python3 -c '…')` 在库不存在时**产出一个空串并照样退出 0**——管道最后一段是 `python3 -c`，它成功退出了。下一行就带着空 `STORY` 去读，于是「需要 STORY」。这不是「库坏了」，是**这段脚本自己没造库**。
- 17 用的 `$DB` 是**上一块设的**，复制过来就没有。
- 12 的固定 `/tmp` 名字让「明天再跑一次」直接失败。

## 4. 独立核查：这不是我的仪器在骗我

三条，都是我自己先怀疑过、再排除的：

1. **「是不是我的干净环境把 Python 弄坏了？」** 同一个干净环境里 `python3 -m dojo --help` 正常；`README.md` 的 8 个块在这个仪器下 7 个 rc 0（唯一失败的 `git clone` 是网络，见第 6 节）。仪器本身能跑通别的页面。
2. **「是不是上一块留下的库让它看起来能跑？」** 早版仪器没有清 `/tmp/dojo-ledger*`，块 13 读到块 12 留下的库，**假绿**。每次 `alone` 前清空前缀之后，13/14 才如实变红。这条是我仪器的错，已修，并写进脚本注释。
3. **「是不是单 shell/多 shell 的模型不同才红？」** 两种都跑：单 shell 整页（读者顺着读）时 12–18 全绿；单独复制一段时 4 个红。**差别就是承诺本身**，不是执行方式。

所以结论落在承诺上，而不是落在工具上：**同一棵树的两种读法给出不同结果，而页面承诺的是第二种。**

## 5. 改法：让承诺成立，而不是把它改软

正文每一段 `sh` 都自己铸一个目录、自己造库：

```sh
LEDGER=$(mktemp -d)
DB=$LEDGER/ledger.sqlite3
python3 -B fixtures/build_comparison_ledger.py "$DB"
```

承诺那句留在原地，只补上代价，因为它现在是真的：

> …目标路径已存在就拒绝，**所以每次调用都写到一个新的空目录**。下面每段都自带 `DB` 和 `STORY` 的取值，单独复制一段也能跑**——代价是每段各造一份自己的库，互不共享**。

门从「重写路径」改成「逐字执行」，并加三条**文本不变量**（不执行也能判）：

| 门的新增/改动 | 它拒绝的事 |
|---|---|
| 选择块的标记：`build_comparison_ledger.py`（原为 `dojo-ledger`） | 块因为「提到过那个路径」而被当作已登记 |
| `test_every_ledger_block_sets_the_variables_it_reads` | 块展开 `$DB`/`$STORY`/`$LEDGER` 却没自己赋值——**这正是 13/14/17 的病** |
| `test_no_ledger_block_names_a_fixed_library_path` | 块写死绝对 `.sqlite3` 路径——第二次跑必失败 |
| `test_every_ledger_block_runs_alone_and_on_a_second_sitting` | 真跑：每块一个干净 shell，再在同机连跑两次 |
| 删掉 `tidy()` / `LEDGER_ROOT` | 门再也不能靠改正文让自己变绿 |

**两臂都验过，用的是同一份只看页面的分类器：**

```sh
# 绿臂（改后）
python3 docs/evidence/2026-11-27-guide-standalone-loop/replay.py .
# blocks=19  promise-blocks=7  promise-failures=0     exit 0

# 红臂：在一次性检出里装回 6aac311 的指南，不碰你正在编辑的工作树
RED=$(mktemp -d)
# 需要在**带 .git 的检出**里跑：git archive 只认仓库，解出来的目录本身没有 .git。
git archive 6aac311 | tar -x -C "$RED"
cp docs/evidence/2026-11-27-guide-standalone-loop/replay.py "$RED"/
python3 "$RED/replay.py" "$RED"
# blocks=19  promise-blocks=7  promise-failures=4     exit 1
#   FAIL block 12 / 13 / 14 / 17
rm -rf -- "$RED"        # 只删你自己刚建的那个目录
```

**红臂不要用 `git show … > docs/cli-guide.md` 再 `git checkout --`。** 那会覆盖你工作树里的指南：如果你正在改它，改动就没了；如果两边同时跑，还会互相踩。上面的做法把基线解到一次性目录里，你的工作树一个字节都不动。

门自身也有红臂，同样在一次性检出里做：

```sh
# 新门 + 旧正文。只解包 6aac311 去跑 unittest，跑的是**旧门**——它当年在旧正文上是绿的，
# 所以那样证明不了任何事（实测：旧门配旧正文 Ran 14 / OK）。要证明新门挡得住旧正文，
# 得把新门放进去。
RED=$(mktemp -d)
git archive 6aac311 | tar -x -C "$RED"
cp tests/test_doc_cli_flags.py "$RED/tests/test_doc_cli_flags.py"   # 新门，旧正文
( cd "$RED" && env -u DOJO_ROOT python3 -m unittest tests.test_doc_cli_flags )
# 4 条失败：路径不变量、逐字执行、单独+第二次、正文数字
rm -rf -- "$RED"
```

在**修好的这棵树**上：`python3 -m unittest tests.test_doc_cli_flags` 为 **16/16 OK**，全套 **986/986 OK**。

## 6. 同一个毛病，换个地方用

这次的教训不是「`mktemp` 好用」，而是三条更一般的判据。它们**已经**在别处被用过，也**还**有没用到的地方：

| 判据 | 已经用到的证据 | 本次 |
|---|---|---|
| 「只在干净机器上能跑的路径不是路径」 | `#3286` 把两个 README 的块改成 `mktemp -d` + `DOJO_DB`。同一套「单独复制 + 再跑一次」的测法用到 `README.md` 上：8 块里 **7 块两次都 rc 0**，唯一失败的是含 `git clone` 的那块（本机无网络），不是路径问题 | 指南的 7 个 ledger 块以前从来没被这样测过 |
| 「文本命中 ≠ 可执行登记」 | `#3246`：在正文里点名一个 flag 不算登记，要有能复制的命令 | 选择块的标记从「提到路径」改成「真的跑构建器」 |
| 「门改正文再判，等于判自己」 | 本次删掉 `tidy()` | 这是唯一一条以前没被明确写下来的 |

**还没用到的地方，写给下一个接手的人：**
`README.md` 第 1 块含 `git clone https://…` 和 `cd dojo`。它在这个离线环境里 rc 1（无网络），**我没有把它当缺陷，也没有改它**——它是有意给第一次拿仓库的人看的，和「复制一段就能跑」不是一类承诺。如果以后要给它加门，判据应该是「在有网络时一次 clone 成功」，而不是把它改成 `mktemp`。

## 6.5 同一类错误的第二处：复核脚本自己删宿主的库

上一节那三条判据里，第一条我在指南上修好了，却在**自己的复核脚本**里犯了同型的错，而且是发布阻断级的。

`replay.py` 为了让「块 13 读到块 12 留下的库」这种假绿不可能发生，在每次 `alone` 之前清掉 `/tmp/dojo-ledger*.sqlite3`。我当时把这条写成「清前任留下的」，但它的真实语义是：**按前缀扫描整台机器的 `/tmp` 并删除匹配文件**。这意味着

- 同事用同样名字建的库会被删掉；
- 两份并行复跑会互相删对方的库，然后各自看到随机结果；
- 而它跟「隔离」根本不是一回事：隔离要作用在**创建侧**，不是清理侧。

这是独立复核者（监督者）读脚本时发现的，不是我自查发现的。我把它记在第一位，因为**这正是本记录第 2 节那个毛病的同一个形状**：一个局部看起来合理的清理，掩盖了一个本该在源头解决的隔离问题。门改正文、脚本删宿主文件，都是「在别人的东西上做补偿」。

改法（也已验）：

```diff
- for pattern in STALE_GLOBS:            # 扫宿主 /tmp，删别人的库
-     for stale in Path('/tmp').glob(pattern):
-         stale.unlink()
  alone_rc, alone_err = run(body, env_for(base / ('alone%d' % index)))
```

现在**每次运行自带私有 `TMPDIR`**（`env_for()` 里的 `'TMPDIR': str(base/'tmp')`），块里的 `/tmp/...` 只落进这次运行自己的目录；脚本不再删除、扫描或触碰自己临时目录以外的任何路径。

证据（可复跑，放在 `LOOP.md` 旁边的 `REPLAY-ISOLATION.md`）：先在宿主 `/tmp` 放一个同名库，整次复跑前后各取一次 SHA-256。

```
before=ef7db2cd7e3956f2ec0b382715e9812a4bc84c606df9b1ee208b58f707c2e6a6
REPLAY=0
after =ef7db2cd7e3956f2ec0b382715e9812a4bc84c606df9b1ee208b58f707c2e6a6
HOST FILE INTACT
colleague-library
```

**这条如何被另一个情境复用**：判据从「清理别人留下的同名文件」改成「每次运行自带私有目录」。同一个判据在指南里是 `mktemp -d`，在复跑脚本里是私有 `TMPDIR`，在门里是 `scratch_env()` —— 一处是页面上的命令，一处是脚本的环境变量，一处是测试的环境变量，但**动作都在创建侧，且都只碰自己创建的东西**。

## 6.6 第二件事：证据不能只活在 Markdown 里

记录写得再细，也只是「旁边一份文档」。产品自己的入口（`stories`、`--comparison`、`--proposal`、`knowledge`）读不回来它，就等于这条知识链只在我的笔记里成立。

所以同一份材料现在有两种读法，**内容同源**（都来自 `ledger.json`）：

| 想做的事 | 怎么读 |
|---|---|
| 看人读的叙事 | `docs/evidence/2026-11-27-guide-standalone-loop/LOOP.md`（本文） |
| 让 dojo 自己读 | `build_ledger.py` 造库 → `stories` / `--context` / `--comparison 10` / `--proposal 3` |

`build_ledger.py` 只做三件事，都在离线完成：把 `ledger.json` 写成探究库；按提案自己的 `premises` 建依赖边；**校验每条引文逐字出现在被引事件里**，对不上就拒绝建库（我自己第一次就被它拦下了：我把一句转述当引文抄了进去，它报「提案 #3 的引文在事件 #2 里找不到」）。

从账本入口读回来是什么样（`tests/test_evidence_ledger_loop.py` 钉住这几点）：

- `stories` 里这条故事 **`synthetic: false`**，不需要 `--synthetic`；它是真实材料，不该被标成角色扮演。
- `--proposal 3` 报 **`superseded`** —— 最初那个说法还在，并且明确是被替代的版本。
- `--comparison 3` **拒绝**并给出下一步：`事件 #3 的结论已被事件 #10 替代…当前版请用 stories STORY --comparison 10 查看`；照它读 #10 就是修正后的说法。
- `--context` 的 `missing_independence` 对 #10 报 **`open` / `no_source` / `no_independent_support`**。

最后这一条是这次最该保留的诚实边界，不要把它当缺陷去「修绿」：`dojo/stories.py` 的 `_source_url_key` 只承认 `https://` 开头的读取算「可独立阅读的来源正文」。我的证据引的是**本仓的文件和真实命令输出**（`repo://...`），所以在产品自己的判据下，它们**不是**独立外部材料。`no_source` 是正确的读数。`tests/test_evidence_ledger_loop.py` 把这个值**钉住**：如果哪天它变成 `checked`，那一定有人改了判据或改了材料，两种情况都需要自己的证据。

我不为了让它好看而伪造 `https://` URL：那会把「一处真实读取」变成为通过检查而编造的材料，比原来更糟。

## 7. 不确定与边界（读这条结论时要一起读）

- **只有一台机器、一个内核、一个 shell。** 没有测 macOS/BSD 的 `mktemp` 差异，也没有测 `sh` 不是 dash 的情况。
- **`alone` 的含义是我定的**：一个干净 shell、什么都不 export、磁盘上没有同名的库。页面只说「单独复制一段」，没说环境。我把这个解释写在 `replay.py` 的 docstring 里，读的人可以不同意，但不会猜不到我测了什么。
- **分类器靠正文措辞。** 它认「单独复制一段也能跑」和「已有探究库的路径」两句。措辞一改，分类就变；所以它把每个块的 scope 和依据都打印出来，而不是只给一个总数。
- **`supplied` 那一类不算缺陷。** `DB` 是「已有探究库的路径」那一节的块，单独跑本来就该失败——页面对读者说了要先有自己的库。这类块的数字照印，但不计红。
- **我没有证明「所有读者都会撞上」。** 我证明的是：照着这句承诺做，在冻结的这棵树上会失败四处；改后不再失败。这不等同于产品可用性结论。
- **一处我判断为「不是缺陷」而没改**：`--comparison` 小节里那段文字说「合成账本必须带 `--synthetic`，否则入口会说没有可见的故事」。单独跑块 13 时，`stories --synthetic` 读一个**不存在**的库会说「路径上没有文件」并以空列表退出 0——那是只读入口在如实说「我看不到这个库」，不是缺陷；但它确实是 `STORY` 为空的上游原因，所以我在改法里让每块**先造库**，而不是去改这句提示。

## 8. 怎么复现这份记录

```sh
# 1. 读者视角（红/绿两臂）
python3 docs/evidence/2026-11-27-guide-standalone-loop/replay.py .

# 2. 门
python3 -m unittest tests.test_doc_cli_flags        # 16 tests
python3 -m unittest discover -s tests               # 986 tests

# 3. 归属
git log --oneline -S'单独复制一段也能跑' -- docs/cli-guide.md
git show 1af799f:docs/cli-guide.md | grep -c 'dojo-ledger'
```

复跑时注意：**不要导出 `DOJO_ROOT`**。这个门先读 `DOJO_ROOT` 再看 `__file__`，导出它会让门去读另一棵树，绿就不属于你手上这棵。
