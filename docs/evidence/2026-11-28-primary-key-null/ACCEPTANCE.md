# 验收记录：NULL 主键这条经验，变成了什么可用的东西

日期：2026-11-28。基线 `b508019`（已发布）。离线；联网只用于最初取回四份文档正文，正文已逐字写进 `ledger.json`。

## 交付

| 文件 | 作用 |
|---|---|
| `docs/evidence/2026-11-28-primary-key-null/LOOP.md` | 人读版：说法 → 追问 → 核查 → 修正 → 复用，含不确定 |
| `.../ledger.json` + `build_ledger.py` | 同一份材料进账本；`--proposal 3` / `--comparison 12` 可读回 |
| `.../probe.py` | 本机读数：文档说的四种状态逐条验证，外加本仓 schema 那一问 |
| `tests/test_primary_key_null.py` | 6 项门；红臂见下 |
| `dojo/storage.py` | 一处 schema 改动：`id TEXT PRIMARY KEY` → `id TEXT NOT NULL PRIMARY KEY` |

## 逐项验收

| # | 说法 | 命令 | 接受读数 |
|---|---|---|---|
| 1 | 文档说的怪癖与三条例外，本机成立 | `python3 .../probe.py` | plain/复合主键存下 2 个 NULL；`NOT NULL`/`WITHOUT ROWID`/`STRICT` 均拒绝；`INTEGER PRIMARY KEY` 不落 NULL |
| 2 | 一条语句能删掉所有 NULL 主键行 | 同上 `duplicate_cost` | `2 rows -> one DELETE removes 2` |
| 3 | 本仓的保证现在在 schema 里 | 同上 `repository_schema` | `schema refuses a NULL key (NOT NULL constraint failed: candidates.id)` |
| 4 | 门钉住这件事 | `python3 -m unittest tests.test_primary_key_null` | 6 OK |
| 5 | 红臂有效 | 把 `NOT NULL` 删回去再跑 4 | **4 项失败**；加回去 6/6 OK |
| 6 | 不影响既有存储行为 | `python3 -m unittest tests.test_storage` | 97 OK |
| 7 | 账本能读回，且版本链正确 | `--proposal 3` / `--comparison 3` / `--comparison 12` | `superseded` / 拒绝并指名 #12 / `checked`、`two_distinct_materials` |
| 8 | 全套 | `python3 -m unittest discover -s tests` | **996 OK** |

读数 8 在私有挂载命名空间里取（`/tmp` 挂干净 tmpfs、`/root` 指到可写目录）。原因不是本题的一部分，而是这台机器上的两个已知陷阱：共享 `/tmp` 会被别的任务占满；`/mnt/d` 是 drvfs，`chmod` 不生效，6 个权限断言必红（这是我第一次跑这套验收时的 6 个 FAIL，不是改动的问题）。

## 账本状态与它的折扣

`--comparison 12` 报 `checked` / `two_distinct_materials`，列出四个 URL。**这个独立性要打折**：产品的判据是「去掉 `#` 片段后 URL 不同」，其中两处是 sqlite.org 同一作者的两页。我没有改判据去换一个更好看的数字，也没有把这四个 URL 写成「四次独立观察」。这一点同时写进了 `LOOP.md` 的不确定一节和 `ledger.json` 的 `record_provenance`。

## 哈希

```
见 git show --stat <commit>；build_ledger.py 会校验每条引文逐字出现在被引事件里
```

## 剩下的不确定

- 只在 SQLite 3.53.4 上实测；文档覆盖的版本范围更宽，没有逐版本验证。
- PostgreSQL / MySQL 的文档只作对照，没有在它们上面跑任何东西。
- 本仓那个洞在当前代码路径下**到不了**（`Store.add` 有 `ID_RE` 校验）。改的是保证的层次，不是「现在可被利用的漏洞」。
- `INTEGER PRIMARY KEY` 那条我第一版写错（标成「NULL admitted」），已按文档原文更正；错误与更正都留在 `LOOP.md` 里。

## 追加：已有库（被否四次后的最终形态）

| # | 说法 | 命令 | 接受读数 |
|---|---|---|---|
| 9 | 可写打开旧库：拒绝且不改字节 | `Store(旧库)` 前后比 SHA-256 | 抛 `DojoError`，点名 `candidates.id` 与升级命令；字节相同；不产生备份文件 |
| 10 | 只读打开旧库：照常可用 | `Store(旧库, readonly=True)` + `list` / `show` | 数据可读、内容正确；字节不变 |
| 11 | 迁移保留每一行与行身份 | 迁移含 rowid 77 的旧库 | `upgraded`；`(rowid, id)` 仍是 `(77, ...)`；`integrity_check ok` |
| 12 | 迁移保留其它列的约束 | 迁移带 `CHECK(version BETWEEN 1 AND 10)` 的旧库 | 迁移后写 `version=99` 仍被拒绝；建表语句里仍有 `BETWEEN 1 AND 10` |
| 13 | 迁移保留库自己的结构 | 迁移带用户索引、用户触发器、同名用户表的旧库 | 三者与其数据全部保留，对象集合前后相同 |
| 14 | 不认识的形状原样拒绝 | 迁移 `id TEXT COLLATE NOCASE PRIMARY KEY` 的库 | 退出码 2、`unsupported_shape`、字节不变 |
| 15 | 核对失败在提交前回滚 | 注入一处差异后再迁移 | `verification_failed`、字节不变、`id` 仍未 NOT NULL |
| 16 | 迁移幂等 | 再跑一次 | `already_constrained`，字节不变 |
| 17 | 别人在用就拒绝 | 独立进程持 `BEGIN IMMEDIATE` + WAL | 退出码 2、`in_use`；对方提交的 `d-keepme` 仍在；释放后成功 |
| 18 | 有 NULL 主键行就拒绝 | 迁移这种库 | 退出码 2、`has_null_keys`，字节不变 |
| 19 | `--check` 不写 | 前后比 SHA-256 | 相同 |
| 20 | CLI 给句子不给 traceback | 迁移前跑 `list` | 点名 `candidates.id` 与升级命令；无 Traceback |

`tests/test_legacy_library_key.py` 15 项；`tests/test_primary_key_null.py` 6 项；全套 **1011 OK**。

被删掉的东西：`PRAGMA writable_schema` 改写、`<库>.pre-not-null.bak`、`--restore`、固定临时表名、写死的建表语句、不带 rowid 的复制、COMMIT 之后的核对。理由分别可复跑：`repro_wal.py`（WAL 下主文件复制是空备份）。

本仓已提交的库里没有旧 schema 的（`docs/evidence/m1.7-caps/live-store.sqlite3` 已是 `NOT NULL`）。
