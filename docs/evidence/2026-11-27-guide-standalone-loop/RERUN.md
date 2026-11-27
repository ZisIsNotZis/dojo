# 怎么复跑出这份交付的读数

三条检查，全部离线。**不要导出 `DOJO_ROOT`** —— 相关的门先读它再看 `__file__`，导出会让门去读另一棵树，绿就不属于你手上这棵。

## 0. 为什么命令外面套了一层 `unshare`

开发机的 `/tmp` 是 7.7G 的 tmpfs，被并行的其它任务占满（剩 ~13M），而 `/mnt/d` 是 drvfs，`chmod` 不生效（`chmod 600` 得到 `777`），本仓有 6 个测试断言 `0o600`。两种环境都会给出**不是代码问题**的红。

所以验收读数是在一个私有挂载命名空间里取的：给 `/tmp` 挂一个干净的 tmpfs，再把 `/root` 指到可写目录（`--map-root-user` 后 `HOME` 的名义值仍是 `/root`，本仓的导出路径来自 passwd 而不是 `$HOME`）。**宿主机的 `/tmp` 一个字节都没动**。

```sh
unshare -m --map-root-user sh -c '
  mount -t tmpfs -o size=4G tmpfs /tmp
  mkdir -p /tmp/root && mount --bind /tmp/root /root
  cd <checkout>
  env -u DOJO_ROOT python3 -m unittest discover -s tests
'
```

没有 `unshare` 权限时：`TMPDIR` 指到一个**权限语义正常**的盘（不要 drvfs），并在 `/tmp` 有空间时跑。

## 1. 读者视角：承诺是否成立

```sh
python3 docs/evidence/2026-11-27-guide-standalone-loop/replay.py <checkout>
```

- 期望：`blocks=19  promise-blocks=7  promise-failures=0`，退出码 0。
- 红臂：把指南换回基线正文再跑同一个脚本，期望 `promise-failures=4`（块 12/13/14/17），退出码 1。

红臂要在**一次性检出**里做，**不要**去改你自己的工作树（`git show … > docs/cli-guide.md` 会覆盖你正在编辑的指南，两边同时跑还会互相踩）：

```sh
# 在**带 .git 的检出**里跑：git archive 只认仓库。
RED=$(mktemp -d)
git archive 6aac311 | tar -x -C "$RED"          # 基线正文，只在这里
cp <checkout>/docs/evidence/2026-11-27-guide-standalone-loop/replay.py "$RED"/
python3 "$RED/replay.py" "$RED"
rm -rf -- "$RED"                                 # 只删你自己建的这个目录
```

同一个一次性检出也能测门的红臂：

```sh
# 新门 + 旧正文。只解包 6aac311 会跑旧门，而旧门在旧正文上本来就是绿的（实测 Ran 14 / OK），
# 那样是假绿，证明不了新门能挡住旧正文。
RED=$(mktemp -d)
git archive 6aac311 | tar -x -C "$RED"
cp <checkout>/tests/test_doc_cli_flags.py "$RED/tests/test_doc_cli_flags.py"
( cd "$RED" && env -u DOJO_ROOT python3 -m unittest tests.test_doc_cli_flags )
# 4 条失败：路径不变量、逐字执行、单独+第二次、正文数字
rm -rf -- "$RED"
```

## 2. 门

```sh
env -u DOJO_ROOT python3 -m unittest tests.test_doc_cli_flags   # 16 tests
env -u DOJO_ROOT python3 -m unittest tests.test_evidence_ledger_loop  # 6 tests
env -u DOJO_ROOT python3 -m unittest discover -s tests          # 986 tests
```

接受读数：`16 OK`、`6 OK`、`986 OK`。

## 3. 真实证据能不能从账本入口读回来

```sh
DB=$(mktemp -d)/evidence.sqlite3
python3 -B docs/evidence/2026-11-27-guide-standalone-loop/build_ledger.py "$DB"
S=6f1c1d0a9b7e4b2f8d3a5c0e7b91a4d2
python3 -m dojo --db "$DB" stories                       # synthetic: false，不需要 --synthetic
python3 -m dojo --db "$DB" stories "$S" --proposal 3     # state: superseded（最初那个说法）
python3 -m dojo --db "$DB" stories "$S" --comparison 3   # 拒绝，并指名 --comparison 10
python3 -m dojo --db "$DB" stories "$S" --comparison 10  # 修正后的说法；comparison_status: open
python3 -m dojo --db "$DB" stories "$S" --context        # missing_independence: open / no_source
```

`open` / `no_source` 是**正确的**读数：产品只把 `https://` 读取算作独立外部材料，而这份证据引的是仓内文件与命令输出。不要为了让它显示 `checked` 去伪造 URL 或改判据。

## 4. 复跑脚本不会碰它没创建的东西

见 `REPLAY-ISOLATION.md`：在宿主 `/tmp` 放一个同名库，复跑前后 SHA-256 应当相同。

## 5. 这份交付建立在哪个提交上

`git rev-parse HEAD`。基线是 `6aac311`（公开候选），本交付在其上新增一个提交。冻结后的读数在 `ACCEPTANCE.md`。
