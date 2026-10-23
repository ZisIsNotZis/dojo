# m1.5-checkpoint — 谁跑过 M1.5 的那一局，跑出来什么

owner：dojo 的 manager。用途：M1.5 用户检查点每一次重跑的落盘记录，一场运行一个文件 `rerun-<YYYY-MM-DD>.md`。

**这里现在的状态：还没有任何一局。** M1.5 是「未确认」——person 2026-10-23 说「还没。」（`mail/2026-10-23-answer-unconfirmed-and-model.md`，`8ed7cb5`），本目录不因此记任何东西为通过。

一个记录文件必须写下的四行，缺一行就不算跑过：

- 日期与执行者（person 亲手，或模型代跑）。
- trace 路径，以及那一局的 trace 能解析出来的行数与末行 `session_end`。
- 这一局用的模型，以及换过模型时的理由（`DOJO_LLM_MODEL` 覆盖了什么）。
- 这一局的请求数与（如端点回显）用量，供下一局比较。

验收命令（把 `<trace.jsonl>` 换成记录里写的那条路径）：

```sh
python3 -c "import json,sys;rows=[json.loads(l) for l in open(sys.argv[1])];print(len(rows), rows[-1]['event'], {r['model'] for r in rows})" <trace.jsonl>
```

模型代跑只保证 M2 起步时脚下有东西；「person 亲手跑过」这一句只有 person 能给，模型跑多少局都替代不了它。
