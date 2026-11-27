# 验收记录：这一轮交付了什么、怎么独立复跑、还剩什么不确定

日期：2026-11-27。离线，不调用模型，不联网，不推送。

## 交付的提交

| 提交 | 内容 |
|---|---|
| `6aac311` | 基线（公开候选，未改） |
| `3b249af` | 指南的「单独复制一段也能跑」由假变真；门改成逐字执行 + 三条文本不变量 |
| `5e2f5c0` | 复跑脚本不再碰宿主文件；真实证据可从 dojo 账本入口读回 |

两个提交都在分支 `candidate/dojo-guide-loop` 上，**未推送**。

## 逐项验收（每条都能自己跑）

| # | 说法 | 命令 | 接受读数 |
|---|---|---|---|
| 1 | 指南的 7 个 ledger 块单独复制可跑、同机第二次可跑 | `replay.py <checkout>` | `promise-blocks=7 promise-failures=0`，退出码 0 |
| 2 | 同一脚本在基线正文上会红（不是随便就绿） | 换回 `6aac311` 的 `docs/cli-guide.md` 再跑 | `promise-failures=4`（块 12/13/14/17），退出码 1 |
| 3 | 门能拒绝「块读了它没设的变量」 | `python3 -m unittest tests.test_doc_cli_flags` | 16 OK；换回基线正文时 4 条失败 |
| 4 | 真实证据可从账本入口读回，且版本链正确 | `build_ledger.py` + `--proposal 3` / `--comparison 3` / `--comparison 10` | `superseded` / 拒绝并指名 #10 / 修正版正文 |
| 5 | 证据门钉住这几点，且红臂有效 | `python3 -m unittest tests.test_evidence_ledger_loop` | 6 OK；删掉 `revises` 链接后 3 条失败 |
| 6 | 产品如实报 `no_source`，没有伪造外部来源 | `--context` 的 `missing_independence` | `open` / `no_source` / `no_independent_support` |
| 7 | 复跑脚本不删宿主同名库 | 宿主 `/tmp` 放同名库，复跑前后比 SHA-256 | 前后同为 `ef7db2cd…`，`HOST FILE INTACT` |
| 8 | 全套 | `python3 -m unittest discover -s tests` | 986 OK |

读数 8 是在私有挂载命名空间里取的（`/tmp` 挂干净 tmpfs、`/root` 指到可写目录），因为开发机的共享 `/tmp` 被其它任务占满、`/mnt/d` 是 drvfs 会让 6 个权限断言必红。具体原因与命令见 `RERUN.md`。**宿主的 `/tmp` 没有被删除或修改。**

## 证据文件与哈希（这份记录对应的字节）

```
271255c76ffbfb27ecc234e157f506ddf1a24d38ddec74b4d1fc30974d0c3100  docs/cli-guide.md
a42d023b5495b02e371175674914947ede8bf315cea427c655cf0675c5ba802e  tests/test_doc_cli_flags.py
ddabad8857ebe097f40b8fb5f4b102b3a8ed8bee6d925ba44000d5f063fb4157  tests/test_evidence_ledger_loop.py
550c633560e3041c83b61a27f6e2df33806095a281ca5f0e307a75f47841ac4c  docs/evidence/2026-11-27-guide-standalone-loop/replay.py
86b7a97ec625b709a36d133cd70fc84e65f19e192fcc5614745efe49b15525eb  docs/evidence/2026-11-27-guide-standalone-loop/build_ledger.py
5bb729a5447412ce2157665b4195bd40ba1a421c3e426a57422a3be93e0fc5b8  docs/evidence/2026-11-27-guide-standalone-loop/ledger.json
d87fd42dfd4ca6582dcd0e6823f4baf07a6e47260c5ca8bb43a4955072d9e13e  docs/evidence/2026-11-27-guide-standalone-loop/LOOP.md
```

## 这段闭环的内容（人读版在 `LOOP.md`）

1. **最初没想清楚的说法**：指南写着「下面每段都自带 `DB` 和 `STORY` 的取值，单独复制一段也能跑」，同一位写作者（本工作区，提交 `895a0f3`）的理由是「门是绿的，正文只是描述」。基线 `e4af6c6`/`1af799f` 的指南里根本没有这一小节。
2. **追问与独立核查**：不重写正文、干净 `HOME`/`TMPDIR`、每块一个 shell，单独跑。四处红：13/14 报「需要 STORY」、17 是 JSON 解码失败、12 在同机第二次 `FileExistsError`。门看不见，是因为它在执行前把 `/tmp/dojo-ledger` 改写成临时目录，并按页序跑（前面造库的块先跑过了）。
3. **修正**：每段自己 `mktemp -d` 造库；门删掉 `tidy()`，改成逐字执行，并加三条文本不变量（不执行也能判）。红/绿两臂都验。
4. **另一个情境复用**：判据从「清理别人留下的同名文件」改成「每次运行自带私有目录」。同一判据落成三处：指南里的 `mktemp -d`、`replay.py` 的私有 `TMPDIR`、门里的 `scratch_env()`。**这只是我把判据搬到三处，不是三个人各自独立得出的结论**——不要读成跨情境的独立验证。
5. **被这个闭环改掉的第二处**：复核脚本删宿主 `/tmp`。这是独立复核者（监督者）读脚本发现的，不是我自查发现的；我把它当作证据保留，因为它和第一处是同一个形状。

## 不确定与边界（当结论读时一起读）

- **不是用户研究。** 「user」事件是仓库原文摘录，「tool_result」是本机命令输出。`ledger.json` 的 `record_provenance` 每行都这么标。没有任何真实用户参与。
- **「复用」是同一个人的搬运，不是独立复现。** 三处隔离都是我按同一条判据改的；没有任何第二个人或第二个团队独立得到它。这是本闭环最弱的一环。
- **证据由 agent 誊写。** 引文逐字、能被 `build_ledger.py` 校验，但「哪些读取值得记」是我的选择。
- **产品把这份证据判为 `no_source`。** 这是正确读数，不是待修的缺陷：`_source_url_key` 只认 `https://`。想让它变成 `checked`，需要真的去读一份外部可读材料，而不是改判据。
- **只在一台机器上测过**（Linux、dash、单核数量级的并行度）。没有测 macOS/BSD 的 `mktemp`、没有测 `sh` 不是 dash、没有测 `TMPDIR` 不被尊重的程序。
- **`alone` 的定义是我给的**：一个干净 shell、什么都不 export、磁盘上没有同名库、私有 `TMPDIR`。页面只说「单独复制一段」。这个解释写在 `replay.py` 的 docstring 里，读的人可以不同意。
- **`README.md` 第 1 块含 `git clone`**，本机无网络时 rc 1。我没有把它当缺陷、也没有改它：它是给第一次拿仓库的人看的，和「复制一段就能跑」不是同一类承诺。
