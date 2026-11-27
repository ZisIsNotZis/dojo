# 一条文档里的经验，怎么变成后来人能直接用的判断

材料：四份**可公开引用的官方文档**，加本机实测。全部离线可复跑，联网只用于最初取回正文。
日期：2026-11-28。基线：`b508019`。

| 材料 | 用处 |
|---|---|
| https://sqlite.org/quirks.html §5 | 经验侧：这是历史遗留的 bug，保留是为了兼容，给了 workaround 与三条例外 |
| https://sqlite.org/lang_createtable.html §3.5 | 规范侧：说清**为什么危险**——NULL 彼此不同，所以能存在很多个 |
| https://www.postgresql.org/docs/current/ddl-constraints.html §5.5.4 | 对照：主键「requires that the values be both unique and not null」 |
| https://dev.mysql.com/doc/refman/8.0/en/create-table.html | 对照：主键列「must be defined as NOT NULL」 |

---

## 1. 最初的说法：只是一条要记住的怪癖

读到 SQLite 文档里那句「PRIMARY KEYs Can Sometimes Contain NULLs」，很容易把它收成一句注意事项：

> SQLite 的 PRIMARY KEY 允许 NULL，记住这个怪癖，别依赖 NULL 主键就行。

这句话**不错**，但它不是判断，是记忆。记忆没有边界条件，也没有后果模型：

- 它没说**什么时候会咬人**——哪些操作会因此出错，哪些不会；
- 它没说**什么时候不会**——文档点名的三条例外是不是真的例外；
- 它没说**该写什么**——只知道「别依赖」，不知道要在 schema 里怎么做，才不用每次记住。

## 2. 追问：那它到底会咬谁

问题换成三个可回答的：

1. 一个 NULL 主键真的能进表吗？进去之后能存在几个？
2. 文档说的三条例外（`INTEGER PRIMARY KEY`、`WITHOUT ROWID`、`STRICT`）真的成立吗？
3. **我们自己这个仓里有没有这个口子？**

第 3 问是关键的一步。前两问读文档就能答；只有第 3 问会把「别人的经验」变成「我们这边的事实」。

## 3. 独立核查：本机跑，不信转述

`probe.py`（就放在这个目录）在 SQLite 3.53.4 上的读数：

```
plain text pk        accepted/accepted stored_null_keys=2 matched_by_IS_NULL=2 NOT distinguishable
text pk + NOT NULL   refused        stored_null_keys=0
composite pk, plain  accepted/accepted stored_null_keys=2 matched_by_IS_NULL=2 NOT distinguishable
INTEGER PRIMARY KEY  accepted/accepted stored_null_keys=0   ← NULL 被改写成 1、2
WITHOUT ROWID        refused
STRICT               refused
duplicate cost: 2 rows -> one DELETE ... WHERE k IS NULL removes 2
```

文档说的四件事全部成立，**包括我一开始差点写错的那条**：`INTEGER PRIMARY KEY` 上插入 NULL 并不留下 NULL，而是落成递增整数。我第一版探针把这一行标成「NULL admitted」，随后对照文档原文才改过来——**这是我自己的一个错误，保留在这里**，因为它是「读文档也要拿文档本身校验」的实例。

第 3 问的读数（**修复前**）：

```
candidates 表：id TEXT PRIMARY KEY，没有 NOT NULL
list_candidates() -> 2 条，其中 id=None
store._get(None)  -> DojoError: candidate not found: None
```

**这行会被列出来，却打不开。** 本仓的保证在 `Store.add` 的 `ID_RE` 校验里，不在 schema 里：任何绕过 API 的写入路径（迁移脚本、手写 SQL、另一个工具）都能造出这种行，而读者会看到一个「计数是 2、只能打开 1 个」的库。这正是「知道有这回事」不够用的地方。

## 4. 修正：把判断写成三条，并且让 schema 自己兜住

**判断**（提案 #12，可在账本里读）：

1. **会咬人的**是「按主键分辨或定位一行」的地方。多个 NULL 主键彼此不可区分，一条 `WHERE k IS NULL` 可以命中多行——`DELETE` 一次删掉两条。只数行数、不按主键取行的代码看不出问题。
2. **不会咬人的**是文档点名的例外：`INTEGER PRIMARY KEY`（NULL 被改写）、`WITHOUT ROWID`、`STRICT`，以及列上已写 `NOT NULL`。
3. **所以写 schema 时**把 `NOT NULL` 写在主键列上，让保证落在 schema。只靠应用层校验，等于把保证寄托在「每个写入口都记得」——而写入口会变多。

**改动**（一处，可逆）：

```diff
-                id TEXT PRIMARY KEY,
+                -- NOT NULL is not redundant here. ...
+                id TEXT NOT NULL PRIMARY KEY,
```

**门**（`tests/test_primary_key_null.py`，6 项）：

| 测什么 | 拒绝什么 |
|---|---|
| schema 文本里有 `NOT NULL` | 有人把它删掉 |
| 用真实 schema 建库、绕过 API 写 NULL | 只有文本对、行为不对 |
| 每个列级主键都带 NOT NULL，**但放行 INTEGER ROWID 别名** | 以后新加的主键重新开洞；也不会因为不懂例外而乱加约束 |
| 跑 `probe.py` 读回四种状态 | 文件与文档悄悄漂移 |
| 一条语句删掉所有 NULL 主键行 | 代价模型改变 |
| 本仓 schema 现在拒绝 NULL | 保证又退回调用方 |

**红臂**：把 `NOT NULL` 删回去，6 项里 **4 项失败**；加回去 6/6 OK。`tests.test_storage` 97 项不受影响，全套见 `ACCEPTANCE.md`。

## 5. 这份材料能支撑到什么程度（读结论时要一起读）

- **账本给它的状态是 `checked` / `two_distinct_materials`，但这份独立性要打折。** 产品的判据是「去掉 `#` 片段后 URL 不同」，四份材料是四个不同 URL，于是算两处以上独立材料。可其中两处来自 sqlite.org 同一个作者、同一套文档。**这是判据的粒度问题，不是材料真的独立。**我没有为了好看去改判据，也没有把它当成「四次独立观察」来写。
- **`INTEGER PRIMARY KEY` 那条我一开始写错了**，已用文档原文纠正；探针里保留了更正后的读数。
- **只在 SQLite 3.53.4 上实测。** 文档描述的行为跨很多版本，我没有逐版本验证。
- **PostgreSQL/MySQL 的文档只是对照**，证明「主键非空」不是某一家的口味；我没有在它们上面跑任何东西。
- **本仓的洞在当前代码路径下到不了**（`Store.add` 会校验）。我修的是「保证的层次」，不是「现在就能被利用的漏洞」——这两件事不要混着说。
- **没测 drvfs/其它文件系统上的行为**，与本题无关，但上次踩过，记在这里防止误读读数。

## 6. 怎么复跑

```sh
# 1. 本机读数（离线）
python3 docs/evidence/2026-11-28-primary-key-null/probe.py

# 2. 门
env -u DOJO_ROOT python3 -m unittest tests.test_primary_key_null     # 6 tests

# 3. 账本（离线；四份 https 正文已逐字写进 ledger.json，不再联网）
DB=$(mktemp -d)/pk.sqlite3
python3 -B docs/evidence/2026-11-28-primary-key-null/build_ledger.py "$DB"
S=3c9e5b7a1d2f4a86b0c7e93d5a1f8b24
python3 -m dojo --db "$DB" stories "$S" --comparison 3    # 被替代，指名 #12
python3 -m dojo --db "$DB" stories "$S" --comparison 12   # checked / two_distinct_materials
python3 -m dojo --db "$DB" stories "$S" --proposal 3      # superseded：最初那句「记住就好」
```

复跑注意：**不要导出 `DOJO_ROOT`**，它会让门去读另一棵树。

## 7. 复盘：已有库这一条被否了四次，每次都是同一类错误

| 版本 | 做法 | 被否的原因 |
|---|---|---|
| 1 | 只管新建的库 | 旧库仍能写 NULL 主键（`CREATE TABLE IF NOT EXISTS` 不改已有表） |
| 2 | 打开时就地改写 `sqlite_master`，把主文件复制当「备份」 | WAL 下复制出来的**是空的**（实测 0 行 vs 原库 1 行），`--restore` 会用它覆盖活库；且报 `upgraded` 时 `changed: false` |
| 3 | 固定临时表名的 `DROP`/`RENAME` 重建 | 删掉 `candidates` 上的索引和触发器；用户自己叫 `candidates_upgrade` 的表被覆盖，仍报 `upgraded / integrity ok` |
| 4 | 重建时用**写死的**新声明、不复制 rowid | 用户给 `version` 加的 `CHECK(... BETWEEN 1 AND 10)` 被换成 `CHECK(version > 0)`，之后 version 99 可写；rowid 77 变成 1 |

**现在（第 5 版）**：

| 场景 | 行为 |
|---|---|
| 新库 | `candidates.id` 带 `NOT NULL` |
| 可写打开旧库 | 拒绝并点名：库路径、`candidates.id`、升级命令。**不改一个字节** |
| 只读打开旧库 | **照常可用**；只读不是缺口的一部分 |
| 显式迁移 | `scripts/upgrade_key_constraint.py`：一个事务内的重建 |
| 有别的进程在用 | 拒绝（取不到写锁；判据是锁，不是 `-wal`/`-shm` 是否存在） |
| 有 NULL 主键行 / 形状不认识 | 拒绝，原样不动 |

迁移现在的四条保真规则：

1. **新声明由旧声明派生**，只把 `id` 的 `TEXT PRIMARY KEY` 换成 `TEXT NOT NULL PRIMARY KEY`。其它列的 `CHECK`、`DEFAULT`、`COLLATE` 一律原样保留；找不到这个片段就**拒绝**，不生成一个自己以为对的建表语句。
2. **rowid 显式复制**，前后逐行比对 `(rowid, id, version, state_json)`。行身份变了，别处按 rowid 的引用就指向了别的行。
3. **库自己的索引与触发器**按原定义重建，对象集合前后比对，多一个少一个都算失败。
4. **核对在 COMMIT 之前做**。发现任何差异就 `ROLLBACK`，库保持原样——不是「报告已经造成的损坏」，而是「没发生时撤销」。

### 四次被否的共同形状

每次我都在**别人的东西上做假设**，而验证只覆盖我自己造的那份状态：

1. 我造的新库有约束，就以为「库」都有；
2. 我测的库没有并发，就以为复制主文件等于备份；
3. 我造的测试库没有用户表、没有索引，就以为重建不会碰到它们；
4. 我造的表没有额外 `CHECK`、rowid 从我 1 开始，就以为声明可以重写、行号可以重排。

复核者每次都只加了一样我没加的东西：一个已存在的库、一个保持打开的连接、一张同名的用户表、一个额外的 `CHECK` 和一个不从 1 开始的 rowid。**这四样都不是边角情况，是真实使用里最普通的状态。**

所以这套判断最后落在一条比技术细节更重要的规则上：**迁移可以拒绝，但不能悄悄改变库的含义；无法完整保留的形状，就原样拒绝。**
