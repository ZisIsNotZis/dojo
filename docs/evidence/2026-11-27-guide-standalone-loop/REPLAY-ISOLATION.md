# 复跑脚本不碰它没创建的东西：怎么自己验一次

背景见 `LOOP.md` 第 6.5 节。这里只放**能自己跑一遍**的检查。

被检查的对象：`replay.py`。它曾经在每次「单独复制一段」之前，按前缀扫掉宿主的
`/tmp/dojo-ledger*.sqlite3`。那是删除别人的文件，且并行复跑会互相破坏。

现在的约束：**每次运行自带私有 `TMPDIR`；脚本不删除、不扫描、不触碰自己临时目录以外的任何路径。**

## 一、证明同名宿主库没有被碰过

```sh
set -u
PRE=/tmp/dojo-ledger.sqlite3
printf 'colleague-library\n' > "$PRE"          # 假装是同事的同名库
B=$(sha256sum "$PRE" | cut -d' ' -f1)

python3 docs/evidence/2026-11-27-guide-standalone-loop/replay.py .

A=$(sha256sum "$PRE" | cut -d' ' -f1)
[ "$B" = "$A" ] && echo 'HOST FILE INTACT' || echo 'HOST FILE CHANGED'
cat "$PRE"
rm -f "$PRE"                                   # 只删你自己刚建的那个
```

2026-11-27 在本机的实测：

```
before=ef7db2cd7e3956f2ec0b382715e9812a4bc84c606df9b1ee208b58f707c2e6a6
REPLAY=0
after =ef7db2cd7e3956f2ec0b382715e9812a4bc84c606df9b1ee208b58f707c2e6a6
HOST FILE INTACT
colleague-library
```

注意 `REPLAY=0`：脚本仍然给出了完整读数（`promise-blocks=7 promise-failures=0`），**不是靠放弃检查来换取安全**。

## 二、证明并行复跑互不干扰

```sh
for i in 1 2 3; do
  python3 docs/evidence/2026-11-27-guide-standalone-loop/replay.py . \
      --json "/tmp/replay-parallel-$i.json" &
done
wait
python3 - <<'EOF'
import json
runs = [json.load(open('/tmp/replay-parallel-%d.json' % i)) for i in (1, 2, 3)]
print([(r['promise_blocks'], r['promise_failures']) for r in runs])
EOF
rm -f /tmp/replay-parallel-*.json
```

三份读数应当彼此相同。旧版脚本在这里会互相删库，因此结果取决于谁先谁后。

## 三、为什么不是「清理得更小心」

一个「只在创建时隔离」的做法，和一个「运行前按前缀清理」的做法，在干净机器上看起来一模一样。区别只在别人也有同名文件的时候。所以判据应当落在**创建侧**：

| 位置 | 做法 |
|---|---|
| `docs/cli-guide.md` 的每段 | `LEDGER=$(mktemp -d)` |
| `replay.py` 的每次运行 | 私有 `TMPDIR` |
| `tests/test_doc_cli_flags.py` | `scratch_env()` 给每次执行独立的 `HOME`/`TMPDIR` |

三处都不需要知道别人有什么，也不删除任何东西。

## 四、这条还没被证明的部分

- 只在 Linux + `sh`(dash) + 一个 `/tmp` 上测过。私有 `TMPDIR` 依赖被执行的程序尊重 `TMPDIR`；一个自己硬写 `/tmp` 的程序不受这个隔离保护。本仓的 Python 代码走 `tempfile`，所以成立。
- **宿主 `/tmp` 满的时候，`mktemp` 和建库会失败，而且是静默的。** 开发目录的 `/tmp` 是 7.7G 的 tmpfs，被并行的其它任务占满到剩 13M 时，一次 `build_comparison_ledger.py` 写出了 **0 字节**的库，然后 `stories` 报「没有可见的故事」并通过退出码 0 给出空列表。看起来像代码 bug，其实是磁盘。复跑前先看一眼 `df -h $TMPDIR`；建完库可以用 `test -s "$DB"` 做一次留神检查。我没有删除别的项目的文件来腾空间。
- **不要把 `TMPDIR` 指到 drvfs（`/mnt/d` 之类）。** 那里 `chmod` 不生效（实测 `/tmp` 上 `chmod 600` 得到 `600`，`/mnt/d` 上得到 `777`），而本仓有 6 个测试断言文件权限是 `0o600`，会因此变红。这不是改动的缺陷，是文件系统属性；换回 `/tmp` 就绿。交付读数应该在权限语义正确的文件系统上取。
