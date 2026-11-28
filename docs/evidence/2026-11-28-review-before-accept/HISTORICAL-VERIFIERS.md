# 四个旧验证器的复跑版本

下面四个 `verify.py` 保留原样作为历史证据。它们的桩仍用模型返回的 `user_stance: accept` 触发写入；现版必须先核对屏上版本，再由用户单独输入 `/认可`。这四条命令在现版均退出 1，不是现版回归检查，也不推翻原来版本的读数。

| 保留的脚本 | 已实跑、退出 0 的公开旧提交 |
| --- | --- |
| `docs/evidence/2026-11-27-closing-line/verify.py` | [`85cb55867143`](https://github.com/ZisIsNotZis/dojo/commit/85cb55867143) |
| `docs/evidence/2026-11-27-receipt-truth/verify.py` | [`7f5d55162282`](https://github.com/ZisIsNotZis/dojo/commit/7f5d55162282) |
| `docs/evidence/2026-11-28-derivation-edge/verify.py` | [`68dbda9c5b73`](https://github.com/ZisIsNotZis/dojo/commit/68dbda9c5b73) |
| `docs/evidence/2026-11-28-transcript-view/verify.py` | [`7f5d55162282`](https://github.com/ZisIsNotZis/dojo/commit/7f5d55162282) |

复跑时检出表里对应的旧提交，从该版本的仓库根目录执行 `python3 -B <脚本路径>`。旧脚本与当时的 `dojo` 代码一起跑，不要把脚本单独复制到现版。
